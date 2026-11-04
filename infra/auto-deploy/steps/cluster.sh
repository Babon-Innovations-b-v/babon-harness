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
#                                  pytest ARGS in a gate Job for $NEW_SHA; its code
#   cluster_build_image NAME CONTEXT DOCKERFILE
#                                  build and push one image; prints repo:tag@digest
#   cluster_roll_image REF         set REF on every object running another tag of it,
#                                  wait for each rollout, undo the ones that fail
#   cluster_repin_images           put every stack image back on its last good digest
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
        --log "$LOG" -- "$@" ) 2>>"$LOG"
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

true
