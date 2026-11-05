#!/bin/bash
# The cycle's calls to the cluster: the bookmark, the gate Job, the image
# builder, the rollouts. Every Kubernetes question is asked of
# `python3 -m infra.deploy_loop` (infra/deploy_loop/__main__.py) or kubectl
# here, so the steps keep their meaning and only this file knows the cluster.
#
# NOT A STEP. It defines functions and runs nothing; sourced by 10-prelude.sh.
#
#   cluster_bookmark_pull          ConfigMap deploy-bookmark -> $LAST_SHA_FILE
#   cluster_bookmark_push          $LAST_SHA_FILE -> ConfigMap deploy-bookmark
#   cluster_gate_run SECONDS -- ARGS
#                                  pytest ARGS in a gate Job for $NEW_SHA, or one Job per
#                                  shard of $GATE_SHARDS_FILE at once; their code
#   cluster_gate_triage_run SHA PIN SECONDS LOG -- ARGS
#                                  pytest ARGS in a gate Job for SHA, no replay; its code
#   cluster_build_image NAME CONTEXT DOCKERFILE
#                                  build and push one image; prints repo:tag@digest
#   cluster_roll_image REF         set REF on every object running another tag of it,
#                                  wait for each rollout, undo the ones that fail
#   cluster_repin_images           put every stack image back on its last good digest
#   cluster_lane_verdicts_pull     ConfigMap commit-gate-verdicts -> the cycle drawers
#   cluster_lane_kick              start the commit-gate lane unless a lane Job runs
#   cluster_ship_cycle_image       rebuild the deploy-cycle image when its baked files
#                                  changed, smoke-test it, try it on deploy-cycle alone
#
# FAILURE POLICY: per function, below. None exits the cycle.

# A bookmark the ConfigMap refuses (never seeded, or not a sha) stops the cycle
# before it can gate anything: without a bookmark it would take the tip of
# main. Exit 0, like the kill switch: a person seeds it once.
cluster_bookmark_pull() {
    local sha
    if ! sha=$(cd "$REPO" && python3 -m infra.deploy_loop bookmark-read 2>>"$LOG"); then
        log "[bookmark] ConfigMap deploy-bookmark is refused (see above); no cycle runs until it is seeded"
        fire_alert_once "bookmark-unseeded" "none" "auto-deploy: the deploy bookmark is not seeded" \
            "ConfigMap deploy-bookmark in namespace ${DEPLOY_NAMESPACE:-deploy} has no usable sha key, so no deploy cycle runs. Seed it with the last commit that is live (infra/auto-deploy/CLAUDE.md). Log: $LOG" \
            --wakes-somebody --blocks-deploy yes
        exit 0
    fi
    if [ -n "$sha" ]; then
        printf '%s\n' "$sha" > "$LAST_SHA_FILE"
    else
        rm -f "$LAST_SHA_FILE"
    fi
    log "[bookmark] configmap deploy-bookmark -> ${sha:-none yet}"
}

# Best-effort: a write that fails leaves the file ahead of the ConfigMap, and
# the next cycle's pull puts the file back, so the commit is gated again
# rather than skipped.
cluster_bookmark_push() {
    local sha
    sha=$(cat "$LAST_SHA_FILE" 2>/dev/null) || return 0
    [ -n "$sha" ] || return 0
    if (cd "$REPO" && python3 -m infra.deploy_loop bookmark-write "$sha") >> "$LOG" 2>&1; then
        log "[bookmark] ${sha:0:12} -> configmap deploy-bookmark"
    else
        log "[bookmark] could not write ${sha:0:12} to ConfigMap deploy-bookmark; the next cycle gates it again"
    fi
    return 0
}

# Returns the Job's verdict code (pytest's own, or 124/125/126/137 for a run
# that could not start or finish). Writes the break replay's code, when one
# ran, to $STATE_DIR/gate-replay-rc. The pod runs the gate image the GATED
# tree's own pin names.
cluster_gate_run() {
    local seconds="$1" pin_new=()
    shift
    [ "${1:-}" = "--" ] && shift
    rm -f "$STATE_DIR/gate-replay-rc"
    if grep -qx 'infra/gate-image/pin' "$STATE_DIR/gate-changed-paths" 2>/dev/null; then
        pin_new=(--pin-is-new)
    fi
    (cd "$REPO" && python3 -m infra.deploy_loop gate-run \
        --sha "$NEW_SHA" --repo-url "${DEPLOY_REPO_URL:?}" \
        --gate-pin "$BUILD_TREE/infra/gate-image/pin" ${pin_new[@]+"${pin_new[@]}"} \
        --cycle-image "${DEPLOY_CYCLE_IMAGE:?}" --pool-label "${POOL_ROLE_LABEL:-harness/role}" \
        --seconds "$seconds" --setup-seconds "${GATE_SETUP_SECONDS:-900}" \
        --changed-file "$STATE_DIR/gate-changed-paths" --replay-workers "${GATE_REPLAY_WORKERS:-1}" \
        --replay-rc-file "$STATE_DIR/gate-replay-rc" \
        --cpu "${GATE_JOB_CPU:-2}" --memory "${GATE_JOB_MEMORY:-6Gi}" \
        --shards-file "${GATE_SHARDS_FILE:-}" \
        --log "$LOG" -- "$@" ) 2>>"$LOG"
}

# One triage run (steps/red_triage.sh): the listed test files of SHA, in the
# gate image the pin file PIN names, in a gate Job of its own, so a re-run is a
# fresh pod. No changed paths, so no break replay, and its log goes to LOG
# rather than the cycle's. Returns the Job's verdict code.
cluster_gate_triage_run() {
    local sha="$1" pin="$2" seconds="$3" run_log="$4"
    shift 4
    [ "${1:-}" = "--" ] && shift
    (cd "$REPO" && python3 -m infra.deploy_loop gate-run \
        --sha "$sha" --repo-url "${DEPLOY_REPO_URL:?}" --gate-pin "$pin" \
        --cycle-image "${DEPLOY_CYCLE_IMAGE:?}" --pool-label "${POOL_ROLE_LABEL:-harness/role}" \
        --seconds "$seconds" --setup-seconds "${GATE_SETUP_SECONDS:-900}" \
        --cpu "${GATE_JOB_CPU:-2}" --memory "${GATE_JOB_MEMORY:-6Gi}" \
        --log "$run_log" -- "$@" ) 2>>"$run_log"
}

# Prints `<registry>/<name>:git-<sha12>@sha256:<digest>` on success. Its log is
# $DEPLOY_LOG_DIR/<name>.log, which _build_fault_kind reads on failure.
cluster_build_image() {
    local name="$1" context="$2" dockerfile="$3" ref meta digest
    ref="${IMAGE_REGISTRY:?}/$name:git-${NEW_SHA:0:12}"
    meta="$DEPLOY_LOG_DIR/$name.meta.json"
    rm -f "$meta"
    buildctl build --frontend dockerfile.v0 \
        --local "context=$VERIFIED_TREE/$context" \
        --local "dockerfile=$VERIFIED_TREE/$(dirname "$dockerfile")" \
        --opt "filename=$(basename "$dockerfile")" \
        --opt "build-arg:GIT_SHA=$NEW_SHA" \
        --import-cache "type=registry,ref=${IMAGE_REGISTRY}/$name:buildcache" \
        --export-cache "type=registry,ref=${IMAGE_REGISTRY}/$name:buildcache,mode=max" \
        --output "type=image,name=$ref,push=true" \
        --metadata-file "$meta" > "$DEPLOY_LOG_DIR/$name.log" 2>&1 || return 1
    digest=$(jq -r '."containerimage.digest" // empty' "$meta" 2>/dev/null)
    [ -n "$digest" ] || { echo "no image digest in $meta" >> "$DEPLOY_LOG_DIR/$name.log"; return 1; }
    printf '%s@%s\n' "$ref" "$digest"
}

# 0 when every object running another tag of REF now runs REF and its rollout
# finished; 1 when one did not, after `kubectl rollout undo` put it back. A
# CronJob has no rollout: its next run takes the new image.
cluster_roll_image() {
    local ref="$1" namespace kind name container failed=0
    while read -r namespace kind name container; do
        [ -n "$name" ] || continue
        if ! kubectl -n "$namespace" set image "$kind/$name" "$container=$ref" >> "$LOG" 2>&1; then
            log "[deploy] could not set $ref on $namespace/$kind/$name"
            failed=1
            continue
        fi
        [ "$kind" = cronjob ] && continue
        if ! kubectl -n "$namespace" rollout status "$kind/$name" --timeout="${BOOT_CHECK_TIMEOUT:-300}s" >> "$LOG" 2>&1; then
            log "[deploy] $namespace/$kind/$name did not roll out on $ref; undoing"
            kubectl -n "$namespace" rollout undo "$kind/$name" >> "$LOG" 2>&1 \
                || log "[deploy] rollout undo of $namespace/$kind/$name FAILED too"
            failed=1
        fi
    done < <(cd "$REPO" && python3 -m infra.deploy_loop image-targets "$ref" 2>>"$LOG")
    return "$failed"
}

# After an apply, every stack image is the placeholder tag again; put each
# back on the last digest that rolled out. An image with no record yet is left
# on the placeholder, and its pods do not start until its first build.
cluster_repin_images() {
    local record ref
    for record in "$STATE_DIR"/stack-images/*; do
        [ -f "$record" ] || continue
        ref=$(cat "$record" 2>/dev/null)
        [ -n "$ref" ] || continue
        cluster_roll_image "$ref" || log "[manifests] re-pinning ${record##*/} to $ref did not roll out cleanly"
    done
    return 0
}

# ── The verifying lane's verdicts ───────────────────────────────────────────
# The commit-gate CronJob (../commit_gate/cluster_lane.sh) publishes what it
# wrote as one ConfigMap; this copies it into the drawers under $STATE_DIR,
# never replacing a file the cycle holds. Every failure is a log line: a
# verdict that does not arrive is a commit this cycle gates itself.
COMMIT_GATE_LANE_CONFIGMAP="${COMMIT_GATE_LANE_CONFIGMAP-commit-gate-verdicts}"
cluster_lane_verdicts_pull() {
    local document fetched
    [ -n "$COMMIT_GATE_LANE_CONFIGMAP" ] || return 0
    if ! document=$(kubectl -n "${DEPLOY_NAMESPACE:-deploy}" get configmap "$COMMIT_GATE_LANE_CONFIGMAP" -o json 2>&1); then
        log "[verdicts] could not read configmap $COMMIT_GATE_LANE_CONFIGMAP; this cycle gates what it cannot read: $document"
        return 0
    fi
    if ! fetched=$(printf '%s' "$document" \
            | python3 "$REPO/infra/auto-deploy/commit_gate/lane_drawers.py" unpack --state-dir "$STATE_DIR" 2>>"$LOG"); then
        log "[verdicts] the lane's configmap could not be unpacked; this cycle gates what it cannot read"
        return 0
    fi
    [ "${fetched:-0}" != "0" ] && log "[verdicts] $fetched new file(s) from the commit-gate lane"
    return 0
}

# The receiver starts the lane on a push; this starts it when a cycle finds it
# idle, so a commit the lane missed is not left waiting for its own tick.
cluster_lane_kick() {
    local jobs answer
    [ -n "$COMMIT_GATE_LANE_CONFIGMAP" ] && [ "${COMMIT_GATE_KICK:-1}" = "1" ] || return 0
    if ! jobs=$(kubectl -n "${DEPLOY_NAMESPACE:-deploy}" get jobs -l app.kubernetes.io/name=commit-gate \
            -o jsonpath='{range .items[*]}{.status.active}{"\n"}{end}' 2>&1); then
        log "[verdicts] could not list commit-gate Jobs, so the lane waits for its tick: $jobs"
        return 0
    fi
    printf '%s\n' "$jobs" | grep -q '^[1-9]' && return 0
    if answer=$(kubectl -n "${DEPLOY_NAMESPACE:-deploy}" create job --from=cronjob/commit-gate "commit-gate-kick-$(date +%s)" 2>&1); then
        log "[verdicts] started the commit-gate lane now: $answer"
    else
        log "[verdicts] could not start the commit-gate lane, so it waits for its tick: $answer"
    fi
    return 0
}

# ── The deploy-cycle image rebuilds itself ──────────────────────────────────
# When the shipped tree's baked files (infra/deploy_loop, tests and markdown
# aside: infra/deploy_loop/_cycle_image.py) are not the image in use's, build
# deploy-cycle:git-<sha12>, smoke-test it in a pod (image/smoke.sh), and try it
# on CronJob deploy-cycle alone, pinned by digest. CronJob
# deploy-cycle-image-guard, still on the old image, moves every other object
# onto it after one green cycle in it, or puts deploy-cycle back when cycles in
# it fail or none ends green in time. State: ConfigMap $CYCLE_IMAGE_CONFIGMAP.
# Nothing here holds the deploy: a build or smoke that says no alerts or logs,
# and the loop goes on in the image it has.
CYCLE_IMAGE_CONFIGMAP="${CYCLE_IMAGE_CONFIGMAP:-deploy-cycle-image}"
CYCLE_IMAGE_RETRY_SECONDS="${CYCLE_IMAGE_RETRY_SECONDS:-21600}"

_cluster_cycle_image_state_write() {
    kubectl -n "${DEPLOY_NAMESPACE:-deploy}" patch configmap "$CYCLE_IMAGE_CONFIGMAP" --type merge -p "$1" >>"$LOG" 2>&1
}

# A trial the guard rolled back alerts once per refused image.
_cluster_cycle_image_page_refusal() {
    local state="$1" refused refused_at
    refused=$(printf '%s' "$state" | python3 -c 'import json,sys;print((json.load(sys.stdin).get("data") or {}).get("refused_image",""))' 2>/dev/null)
    refused_at=$(printf '%s' "$state" | python3 -c 'import json,sys;print((json.load(sys.stdin).get("data") or {}).get("refused_at",""))' 2>/dev/null)
    [ -n "$refused" ] && [ -n "$refused_at" ] || return 0
    fire_alert_once "cycle-image-refused" "${refused##*:}-$refused_at" \
        "auto-deploy: a new deploy-cycle image was rolled back" \
        "Image: $refused. It failed its smoke test, or no cycle in it ended green, so the loop runs on in the image every other object runs. The guard's log (kubectl -n ${DEPLOY_NAMESPACE:-deploy} logs -l app.kubernetes.io/name=deploy-cycle-image-guard) says why; the same baked files are built again after $(( CYCLE_IMAGE_RETRY_SECONDS / 3600 )) h, or at once when a commit changes them."
    return 0
}

# 0 the image's smoke test passed in a pod, 1 it said no, 2 the pod could not
# run or be read in CYCLE_IMAGE_SMOKE_SECONDS.
_cluster_smoke_pod() {
    local image="$1" name="$2" phase="" rc=2 namespace="${DEPLOY_NAMESPACE:-deploy}" deadline
    if ! python3 -c '
import json, sys
image, name, label = sys.argv[1:4]
print(json.dumps({"apiVersion": "v1", "kind": "Pod",
    "metadata": {"name": name, "labels": {"app.kubernetes.io/name": "cycle-image-smoke"}},
    "spec": {"restartPolicy": "Never", "automountServiceAccountToken": False,
             "priorityClassName": "deploy-loop", "nodeSelector": {label: "system"},
             "tolerations": [{"key": label, "operator": "Equal", "value": "system", "effect": "NoSchedule"}],
             "imagePullSecrets": [{"name": "registry-pull"}],
             "securityContext": {"runAsUser": 1000, "runAsGroup": 1000, "runAsNonRoot": True},
             "containers": [{"name": "smoke", "image": image,
                             "command": ["bash", "/app/infra/deploy_loop/image/smoke.sh"],
                             "resources": {"requests": {"cpu": "100m", "memory": "128Mi"},
                                           "limits": {"memory": "512Mi"}}}]}}))' \
            "$image" "$name" "${POOL_ROLE_LABEL:-harness/role}" \
            | kubectl -n "$namespace" apply -f - >>"$LOG" 2>&1; then
        return 2
    fi
    deadline=$(( $(date +%s) + ${CYCLE_IMAGE_SMOKE_SECONDS:-300} ))
    until [ "$(date +%s)" -ge "$deadline" ]; do
        phase=$(kubectl -n "$namespace" get pod "$name" -o 'jsonpath={.status.phase}' 2>/dev/null || true)
        case "$phase" in
            Succeeded) rc=0; break ;;
            Failed) rc=1; break ;;
        esac
        sleep 5
    done
    kubectl -n "$namespace" logs "$name" >>"$LOG" 2>&1 || true
    kubectl -n "$namespace" delete pod "$name" --wait=false >>"$LOG" 2>&1 || true
    return "$rc"
}

cluster_ship_cycle_image() {
    local tree="${VERIFIED_TREE:-}" tree_sum state decision word pinned smoke_rc now good_field
    [ "${gate_red:-0}" -eq 0 ] && [ "${ship_abandoned:-0}" -eq 0 ] || return 0
    [ -n "$tree" ] && [ -d "$tree/infra/deploy_loop/image" ] || return 0
    if ! tree_sum=$(cd "$REPO" && python3 -m infra.deploy_loop cycle-image-sum "$tree" 2>>"$LOG"); then
        log "[cycle-image] could not sum the baked files of ${tree##*/}; no build this cycle"
        return 0
    fi
    if ! state=$(kubectl -n "${DEPLOY_NAMESPACE:-deploy}" get configmap "$CYCLE_IMAGE_CONFIGMAP" -o json 2>>"$LOG"); then
        log "[cycle-image] could not read configmap $CYCLE_IMAGE_CONFIGMAP; no build this cycle"
        return 0
    fi
    _cluster_cycle_image_page_refusal "$state"
    decision=$(printf '%s' "$state" | (cd "$REPO" && python3 -m infra.deploy_loop cycle-image-decide \
        --sum "$tree_sum" --retry-seconds "$CYCLE_IMAGE_RETRY_SECONDS") 2>>"$LOG") \
        || decision="current the state could not be read"
    word=${decision%% *}
    if [ "$word" != "build" ]; then
        [ "$word" = "current" ] || log "[cycle-image] ${decision#* }"
        return 0
    fi
    log "[cycle-image] the baked files are $tree_sum, not the image in use's; building deploy-cycle at ${NEW_SHA:0:12}"
    if ! pinned=$(cluster_build_image deploy-cycle . infra/deploy_loop/image/Dockerfile); then
        fire_alert_once "cycle-image-build" "$NEW_SHA" "auto-deploy: the deploy-cycle image did not build" \
            "SHA: $NEW_SHA. The loop keeps the image it runs and tries again next cycle. Build log: $DEPLOY_LOG_DIR/deploy-cycle.log"
        return 0
    fi
    _cluster_smoke_pod "$pinned" "cycle-image-smoke-${NEW_SHA:0:12}"
    smoke_rc=$?
    now=$(date +%s)
    if [ "$smoke_rc" -eq 2 ]; then
        log "[cycle-image] the smoke pod for $pinned could not run or be read; nothing tried, next cycle again"
        return 0
    fi
    if [ "$smoke_rc" -ne 0 ]; then
        _cluster_cycle_image_state_write "{\"data\":{\"refused_image\":\"$pinned\",\"refused_sum\":\"$tree_sum\",\"refused_at\":\"$now\"}}" \
            || log "[cycle-image] could not record the refusal of $pinned"
        log "[cycle-image] $pinned failed its smoke test (the pod log is above); nothing runs it"
        return 0
    fi
    # The image in use becomes the recorded good one when none is yet, so the
    # guard has somewhere to roll back to from the first trial on.
    good_field=$(printf '%s' "$state" | python3 -c 'import json,sys
data = json.load(sys.stdin).get("data") or {}
print("" if data.get("good") or not sys.argv[1] else ",\"good\":\"" + sys.argv[1] + "\"")' "${DEPLOY_CYCLE_IMAGE:-}" 2>/dev/null)
    if ! _cluster_cycle_image_state_write "{\"data\":{\"candidate\":\"$pinned\",\"candidate_sum\":\"$tree_sum\",\"candidate_since\":\"$now\"$good_field}}"; then
        log "[cycle-image] could not start the trial of $pinned in configmap $CYCLE_IMAGE_CONFIGMAP; next cycle again"
        return 0
    fi
    if kubectl -n "${DEPLOY_NAMESPACE:-deploy}" patch cronjob deploy-cycle --type strategic -p \
            "{\"spec\":{\"jobTemplate\":{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"cycle\",\"image\":\"$pinned\",\"env\":[{\"name\":\"DEPLOY_CYCLE_IMAGE\",\"value\":\"$pinned\"}]}]}}}}}}" >>"$LOG" 2>&1; then
        log "[cycle-image] trying $pinned on cronjob/deploy-cycle; the guard moves everything else after one green cycle"
    else
        log "[cycle-image] kubectl refused $pinned on cronjob/deploy-cycle; the guard ends the trial it cannot see"
    fi
    return 0
}

true
