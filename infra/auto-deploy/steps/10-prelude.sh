#!/bin/bash
# Step 10: configuration, the vault cache, the kill switch, and the variables
# every later step shares.
#
# FAILURE POLICY: the kill switch exits 0 (deploys paused by hand, not broken).
# The vault pull never fails the cycle: on any problem the existing cache stays.
# Everything else here only defines.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

# shellcheck disable=SC1091
. "$(dirname "${BASH_SOURCE[0]}")/doors.sh"
# shellcheck disable=SC1091
. "$(dirname "${BASH_SOURCE[0]}")/cluster.sh"

# ── The vault: refresh the env cache before reading it ──────────────────────
# infra/secrets/pull-env.sh writes the secret named VAULT_SECRET_NAME to
# $HARNESS_ROOT/harness.env (mode 600). A cache that changed means a new secret
# version was pushed, and step 50 then restarts the whole stack even when no
# commit landed: that is what makes a rotation need no ssh.
HARNESS_ENV_FILE="${HARNESS_ENV_FILE:-$HARNESS_ROOT/harness.env}"
ENV_CHANGED=false
if [ -x "$REPO/infra/secrets/pull-env.sh" ] && [ "${AUTO_DEPLOY_VAULT_PULL:-1}" = "1" ]; then
    _env_sum_before=$(md5sum "$HARNESS_ENV_FILE" 2>/dev/null | cut -d' ' -f1)
    "$REPO/infra/secrets/pull-env.sh" >> "$LOG" 2>&1 \
        || log "[vault] pull-env.sh failed; this cycle runs on the cache it already had"
    _env_sum_after=$(md5sum "$HARNESS_ENV_FILE" 2>/dev/null | cut -d' ' -f1)
    if [ -n "$_env_sum_before" ] && [ "$_env_sum_before" != "$_env_sum_after" ]; then
        ENV_CHANGED=true
        log "[vault] the env cache changed (a new vault version); every service is restarted this cycle"
    fi
    unset _env_sum_before _env_sum_after
fi

harness_load_config "$REPO"
GH_REPO_SLUG="${GH_REPO_SLUG:-$(harness_repo_slug "$REPO")}"
GH_REPO_OWNER="${GH_REPO_OWNER:-$(harness_repo_owner "$REPO")}"
DEPLOY_REPO_URL="${DEPLOY_REPO_URL:-https://github.com/$GH_REPO_SLUG.git}"
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-harness}"

AUTO_DEPLOY_ENABLED="${AUTO_DEPLOY_ENABLED:-1}"
if [ -z "${RELEASE_FORCE:-}" ] && [ "$AUTO_DEPLOY_ENABLED" != "1" ]; then
    log "AUTO_DEPLOY_ENABLED=$AUTO_DEPLOY_ENABLED: scheduled deploys are paused"
    exit 0
fi

# The bookmark's durable copy is ConfigMap deploy-bookmark; every step reads
# the file it always read.
cluster_bookmark_pull

# How far back the eject may reach, in commits.
EJECT_MAX_RANGE="${EJECT_MAX_RANGE:-5}"

# `_build_fault_kind <log>` prints `commit` or `box` for a failed image build.
# If the rule cannot load, every failed build is the box's: it holds the
# bookmark and reverts nothing, the only safe answer from an unreadable rule.
if ! . "$(dirname "${BASH_SOURCE[0]}")/build_verdict.sh" 2>/dev/null; then
    _build_fault_kind() { printf 'box'; return 0; }
    log "steps/build_verdict.sh did not load, so every failed build this cycle is the box's fault"
fi

# ── The two verdict writers ─────────────────────────────────────────────────
# Here rather than in step 40, because step 40's noop exit records a deploy
# verdict and that exit ends the cycle before step 90 is sourced. One line,
# written atomically: a torn verdict read as a valid one would SKIP a gate.
record_gate_verdict() {
    local verdict="$1"
    local sha="${2:-${NEW_SHA:-}}"
    local scope="${3:-${gate_scope:-full}}"
    local tree="${4:-}"
    local reason="${5:-${gate_red_reason:-none}}"
    local target
    [ -n "$sha" ] || return 0
    # The tree hash is what makes the answer safe to reuse: a sha and a scope
    # do not say the bytes were the same.
    [ -n "$tree" ] || tree="$(git -C "$REPO" rev-parse "${sha}^{tree}" 2>/dev/null || echo "")"
    mkdir -p "$GATE_VERDICT_DIR" 2>/dev/null
    target="$GATE_VERDICT_DIR/$sha"
    printf '%s %s %s %s %s %s\n' "$sha" "$verdict" "$scope" "$(date +%s)" \
        "${reason:-none}" "${tree:-unknown}" > "$target.tmp" 2>/dev/null \
        && mv -f "$target.tmp" "$target" 2>/dev/null \
        || log "[gate] could not record the verdict for $sha (the next cycle re-runs the gate)"
    # Which range this verdict measured, in a sibling file: a one-commit range
    # and a jumped union carry the same scope word over different path sets, so
    # step 40 may replay a union verdict only for the same range.
    if [ "$sha" = "${NEW_SHA:-}" ]; then
        if [ "${gate_range_isolated:-1}" -ne 1 ] && [ -n "${OLD_SHA:-}" ]; then
            printf '%s\n' "$OLD_SHA" > "$target.range" 2>/dev/null || true
        else
            rm -f "$target.range" 2>/dev/null || true
        fi
        printf '%s %s %s %s %s\n' "$sha" "$verdict" "$scope" "$(date +%s)" "${reason:-none}" \
            > "$GATE_VERDICT_FILE" 2>/dev/null || true
    fi
    return 0
}

record_deploy_verdict() {
    printf '%s %s %s\n' "${NEW_SHA:-}" "$1" "$(date +%s)" \
        > "$DEPLOY_VERDICT_FILE.tmp" 2>/dev/null \
        && mv -f "$DEPLOY_VERDICT_FILE.tmp" "$DEPLOY_VERDICT_FILE" 2>/dev/null \
        || log "outcome: could not record the deploy verdict for ${NEW_SHA:-unknown}"
    return 0
}

# Publish one Prometheus gauge for the cycle. Best-effort. In the cluster
# (PUSHGATEWAY_URL set, infra/k8s/deploy/cycle.yaml) it replaces group
# job=deploy-<name> on the Pushgateway, since the cycle's pod ends with the
# cycle; on a server it is a node-exporter textfile.
record_deploy_metric() {
    local name="$1" value="$2" dir="${HARNESS_TEXTFILE_DIR:-$STATE_DIR/textfile}"
    if [ -n "${PUSHGATEWAY_URL:-}" ]; then
        printf '%s %s\n' "$name" "$value" \
            | curl -fsS --max-time 10 -X PUT --data-binary @- \
                "${PUSHGATEWAY_URL%/}/metrics/job/deploy-$name" >/dev/null 2>&1 \
            || log "outcome: could not push $name to the Pushgateway"
        return 0
    fi
    mkdir -p "$dir" 2>/dev/null || return 0
    printf '%s %s\n' "$name" "$value" > "$dir/.deploy-$name.prom.$$" 2>/dev/null \
        && mv -f "$dir/.deploy-$name.prom.$$" "$dir/deploy-$name.prom" 2>/dev/null || true
    return 0
}

# ── Tree pin ────────────────────────────────────────────────────────────────
# The webhook can move the clone at any moment. Wherever the cycle is about to
# commit to something read from the clone, it asks whether HEAD is still the
# commit step 20 measured, and abandons the ship actions if not. `tree_moved`
# latches. Abandoning costs one cycle: the bookmark does not move.
tree_moved=0
tree_is_pinned() {
    local where="$1" head_now
    [ "$tree_moved" -eq 1 ] && return 1
    head_now=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo "")
    [ -n "$head_now" ] && [ "$head_now" = "${NEW_SHA:-}" ] && return 0
    tree_moved=1
    log "[pin] HEAD moved from ${NEW_SHA:0:8} to ${head_now:0:8} at $where; abandoning the ship actions for this cycle"
    return 1
}

# ── Shared variables, declared before any step can read them under set -u ───
gate_scope="full"
gate_paths_file=""
gate_scope_json=""
gate_selected_count=0
gate_range_isolated=0
gate_red=0
gate_red_reason=""
gate_reused=0
gate_cached=0
build_head_source="next"
build_head_jumped=0
queue_depth=0
bookmark_depth=0
BUILD_TREE=""
VERIFIED_TREE=""
ship_abandoned=0
DEPLOYED_SERVICES=()
FAILED_SERVICES=()
BUILD_FAILED_SERVICES=()
BUILD_RED_SERVICES=()
BOOT_FAILED_SERVICES=()
