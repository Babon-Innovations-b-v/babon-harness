#!/bin/bash
# The commit-gate CronJob's command (infra/k8s/deploy/commit-gate.yaml): the
# verifying lane, in a pod of its own beside the deploy cycle.
#
#   bookmark   ConfigMap deploy-bookmark -> $STATE_DIR/last-deployed-sha, the
#              file verify_ahead.sh and eject.sh read
#   verify     dispatch.sh: every queued commit in a tree of its own, its suite
#              as gate Jobs, its verdict written into THIS pod's state
#   publish    lane_drawers.py pack -> ConfigMap commit-gate-verdicts, within
#              COMMIT_GATE_PUBLISH_POLL_SECONDS of a new verdict or eject
#              decision, every COMMIT_GATE_PUBLISH_SECONDS while dispatch runs,
#              and once after; step 18 of the cycle unpacks it
#   kick       a publish that changed the ConfigMap starts a deploy-cycle Job
#              at once unless one is active, so a verdict does not wait for the
#              cycle's two-minute tick
#
# KUBE ACCESS IS FOR THIS SCRIPT AND THE GATE JOBS IT MAKES. The pod mounts its
# service account token at a path of its own, never the in-cluster default, and
# every kubectl call here and in run_one.sh is pointed at it. The suites run in
# gate Jobs, which mount no token.
#
# FAILURE POLICY: every failure here is a log line and exit 0, because a lane
# that writes nothing costs exactly what it cost before it existed: the cycle
# gates every commit itself. No bookmark means no range, so nothing is run.
set -u

SELF="$(cd "$(dirname "$0")" && pwd)"
REPO="${COMMIT_GATE_REPO:-${HARNESS_ROOT:-/opt/harness}/repo}"
STATE_DIR="${STATE_DIR:-/var/lib/harness}"
NAMESPACE="${DEPLOY_NAMESPACE:-deploy}"
BOOKMARK_CONFIGMAP="${DEPLOY_BOOKMARK_CONFIGMAP:-deploy-bookmark}"
LANE_CONFIGMAP="${COMMIT_GATE_LANE_CONFIGMAP:-commit-gate-verdicts}"
COMMIT_GATE_BRANCH="${COMMIT_GATE_BRANCH:-origin/main}"
PUBLISH_SECONDS="${COMMIT_GATE_PUBLISH_SECONDS:-20}"
PUBLISH_POLL_SECONDS="${COMMIT_GATE_PUBLISH_POLL_SECONDS:-3}"
KUBE_TOKEN_DIR="${COMMIT_GATE_KUBE_TOKEN_DIR:-/var/run/harness/kube}"
LANE_KUBECONFIG="${COMMIT_GATE_KUBECONFIG:-${TMPDIR:-/tmp}/commit-gate-kubeconfig}"

log() { printf '[%s] [commit-gate lane] %s\n' "$(date -Iseconds)" "$*" >&2; }

# The pod's own token as a kubeconfig, exported for run_one.sh's gate Jobs.
_lane_write_kubeconfig() {
    [ -n "${KUBERNETES_SERVICE_HOST:-}" ] || return 0
    [ -r "$KUBE_TOKEN_DIR/token" ] || return 0
    cat > "$LANE_KUBECONFIG" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: in-cluster
    cluster:
      server: https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT:-443}
      certificate-authority: $KUBE_TOKEN_DIR/ca.crt
users:
  - name: commit-gate
    user:
      tokenFile: $KUBE_TOKEN_DIR/token
contexts:
  - name: lane
    context: {cluster: in-cluster, user: commit-gate, namespace: $NAMESPACE}
current-context: lane
EOF
    export KUBECONFIG="$LANE_KUBECONFIG"
}

_lane_kubectl() {
    kubectl -n "$NAMESPACE" "$@"
}

# The bookmark as the cycle last wrote it. An unreadable or malformed one
# leaves the previous file alone: a stale bookmark only makes the lane verify a
# commit the cycle has already passed, while no bookmark makes it verify nothing.
lane_pull_bookmark() {
    local sha
    if ! sha="$(_lane_kubectl get configmap "$BOOKMARK_CONFIGMAP" -o 'jsonpath={.data.sha}' 2>&1)"; then
        log "could not read ConfigMap $BOOKMARK_CONFIGMAP: $sha"
        return 1
    fi
    if [ "${#sha}" -ne 40 ] || [ -n "${sha//[0-9a-f]/}" ]; then
        log "ConfigMap $BOOKMARK_CONFIGMAP holds '${sha:-nothing}', which is not a commit"
        return 1
    fi
    mkdir -p "$STATE_DIR" 2>/dev/null
    printf '%s\n' "$sha" > "$STATE_DIR/last-deployed-sha.tmp" \
        && mv -f "$STATE_DIR/last-deployed-sha.tmp" "$STATE_DIR/last-deployed-sha"
}

# Everything the lane wrote for the commits still queued, as one ConfigMap.
# Server-side apply under one field manager, so a key this lane stops sending
# (a commit the bookmark passed) is removed rather than kept for ever. A
# publish that changed what the ConfigMap holds then starts the deploy cycle.
LANE_PUBLISHED=""
lane_publish() {
    local bookmark shas_file packed answer digest
    bookmark="$(cat "$STATE_DIR/last-deployed-sha" 2>/dev/null || true)"
    [ -n "$bookmark" ] || return 0
    shas_file="$(mktemp -t commit-gate-shas-XXXXXX)"
    packed="$(mktemp -t commit-gate-pack-XXXXXX)"
    git -C "$REPO" rev-list --first-parent "$bookmark..$COMMIT_GATE_BRANCH" > "$shas_file" 2>/dev/null || true
    if ! python3 "$SELF/lane_drawers.py" pack --state-dir "$STATE_DIR" \
            --shas-file "$shas_file" --name "$LANE_CONFIGMAP" --namespace "$NAMESPACE" > "$packed"; then
        log "could not pack the drawers for ConfigMap $LANE_CONFIGMAP"
    elif ! answer="$(_lane_kubectl apply --server-side --force-conflicts \
            --field-manager=commit-gate-lane -f "$packed" 2>&1)"; then
        log "could not publish to ConfigMap $LANE_CONFIGMAP: $answer"
    else
        digest="$(sha256sum < "$packed" | cut -c1-64)"
        if [ -n "$LANE_PUBLISHED" ] && [ "$digest" != "$LANE_PUBLISHED" ]; then
            lane_kick_cycle
        fi
        LANE_PUBLISHED="$digest"
    fi
    rm -f "$shas_file" "$packed"
    return 0
}

# A new verdict starts the deploy cycle now unless one runs. A refused start is
# a log line; the tick still comes, and the cycle takes its lock as on any tick.
lane_kick_cycle() {
    local active answer
    [ "${COMMIT_GATE_KICK_CYCLE:-1}" = "1" ] || return 0
    if ! active="$(_lane_kubectl get jobs -l app.kubernetes.io/name=deploy-cycle \
            -o 'jsonpath={range .items[*]}{.status.active}{"\n"}{end}' 2>&1)"; then
        log "could not list deploy-cycle Jobs, so the cycle waits for its tick: $active"
        return 0
    fi
    printf '%s\n' "$active" | grep -q '^[1-9]' && return 0
    if answer="$(_lane_kubectl create job --from=cronjob/deploy-cycle "deploy-cycle-lane-$(date +%s)" 2>&1)"; then
        log "a new verdict started the deploy cycle: $answer"
    else
        log "could not start the deploy cycle, so it waits for its tick: $answer"
    fi
    return 0
}

# 0 when a verdict or an eject decision was written after <stamp>.
_lane_state_moved() {
    find "$STATE_DIR/gate-verdicts" "$STATE_DIR/eject-decisions" -maxdepth 1 -type f \
        -newer "$1" -print -quit 2>/dev/null | grep -q .
}

main() {
    local dispatch_pid stamp last now
    _lane_write_kubeconfig
    if ! lane_pull_bookmark; then
        log "no bookmark, so there is no range to verify ahead of this tick"
        return 0
    fi
    lane_publish

    stamp="$(mktemp -t commit-gate-published-XXXXXX)" || stamp=""
    last="$(date +%s)"
    bash "$SELF/dispatch.sh" &
    dispatch_pid=$!
    while kill -0 "$dispatch_pid" 2>/dev/null; do
        sleep "$PUBLISH_POLL_SECONDS" &
        wait $! 2>/dev/null
        now="$(date +%s)"
        if [ $(( now - last )) -ge "$PUBLISH_SECONDS" ]; then
            last="$now"
            [ -n "$stamp" ] && touch "$stamp"
            lane_pull_bookmark || true
            lane_publish
        elif [ -n "$stamp" ] && _lane_state_moved "$stamp"; then
            # The stamp moves before the publish, so a verdict written while
            # it runs is caught by the next look.
            touch "$stamp"
            lane_publish
        fi
    done
    wait "$dispatch_pid" 2>/dev/null
    lane_publish
    [ -n "$stamp" ] && rm -f "$stamp"
    return 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
