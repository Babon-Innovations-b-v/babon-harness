#!/bin/bash
# Step 50: build the stack images this commit changed, roll each out by
# digest, and undo any rollout that does not finish.
#
#   1. Which images: infra/auto-deploy/compose_fragments.py names the compose
#      services each changed path belongs to (`all` when the root
#      docker-compose.yml or config/ changed); the stack's own images are the
#      ones a manifest names with the placeholder tag set-by-deploy-loop
#      (python3 -m infra.deploy_loop stack-images). The step builds the ones in
#      both lists, every commit, never a batch.
#   2. Build each from the VERIFIED tree with BuildKit (Deployment buildkitd),
#      pushed as <IMAGE_REGISTRY>/<name>:git-<sha12> with the registry cache
#      <name>:buildcache. A failed build is the commit's fault or the box's
#      (steps/build_verdict.sh): the commit's can be ejected, the box's holds
#      the bookmark and alerts, and neither rolls anything.
#   3. Roll by digest: `kubectl set image` on every Deployment, StatefulSet,
#      DaemonSet and CronJob running another tag of that image, then
#      `kubectl rollout status`. One that does not finish inside
#      BOOT_CHECK_TIMEOUT is undone (`kubectl rollout undo`) and recorded in
#      BOOT_FAILED_SERVICES. A rolled image's reference is kept in
#      $STATE_DIR/stack-images/<name>, which step 80 re-pins after an apply.
#   4. The loop's own image: when the tree's infra/deploy_loop differs from the
#      deploy-cycle image in use, build it, smoke-test it and try it on
#      CronJob deploy-cycle alone (steps/cluster.sh, cluster_ship_cycle_image).
#
# A red gate ships nothing: this step returns before building anything.
#
# FAILURE POLICY: a failed build or rollout is recorded and the bookmark
# holds; the next cycle retries. Nothing here exits the cycle.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

BOOT_CHECK_TIMEOUT="${BOOT_CHECK_TIMEOUT:-300}"
DEPLOY_LOG_DIR="$STATE_DIR/build-logs"

_deploy_services() {
    local services=() svc fault deployment tree="${VERIFIED_TREE:-}" ref
    local -A context_of dockerfile_of built
    if [ "${gate_red:-0}" -eq 1 ]; then
        log "[deploy] the gate is red (${gate_red_reason:-unknown}); nothing is built or rolled"
        return 0
    fi
    if [ -z "$tree" ]; then
        if ${compose_changed:-false}; then
            log "[deploy] no verified tree this cycle; nothing rolled, the next cycle retries"
            ship_abandoned=1
        fi
        return 0
    fi
    local name context dockerfile
    while read -r name context dockerfile; do
        [ -n "$name" ] || continue
        context_of[$name]="$context"
        dockerfile_of[$name]="$dockerfile"
    done < <(cd "$REPO" && python3 -m infra.deploy_loop stack-images "$tree" 2>>"$LOG")
    mapfile -t services < <(python3 "$tree/infra/auto-deploy/compose_fragments.py" \
        --repo "$tree" --changed-file "$STATE_DIR/gate-changed-paths" 2>>"$LOG" || echo all)
    if [ "${#services[@]}" -gt 0 ] && [ "${services[0]}" = "all" ]; then
        services=("${!context_of[@]}")
    fi
    local wanted=()
    for svc in ${services[@]+"${services[@]}"}; do
        [ -n "${context_of[$svc]+set}" ] && wanted+=("$svc")
    done
    if [ "${#wanted[@]}" -eq 0 ]; then
        log "[deploy] no stack image changed"
        return 0
    fi
    log "[deploy] images: ${wanted[*]} (from ${tree##*/})"
    mkdir -p "$DEPLOY_LOG_DIR" "$STATE_DIR/stack-images" 2>/dev/null

    # Build every image first; roll nothing if any build failed.
    for svc in "${wanted[@]}"; do
        if [ "${dockerfile_of[$svc]}" = "-" ]; then
            log "[deploy] $svc is a stack image no compose service builds; the commit's fault"
            FAILED_SERVICES+=("$svc"); BUILD_FAILED_SERVICES+=("$svc"); BUILD_RED_SERVICES+=("$svc")
            continue
        fi
        if ref=$(cluster_build_image "$svc" "${context_of[$svc]}" "${dockerfile_of[$svc]}"); then
            built[$svc]="$ref"
            log "[deploy] $svc built as $ref"
            continue
        fi
        fault=$(_build_fault_kind "$DEPLOY_LOG_DIR/$svc.log")
        FAILED_SERVICES+=("$svc")
        BUILD_FAILED_SERVICES+=("$svc")
        if [ "$fault" = "commit" ]; then
            BUILD_RED_SERVICES+=("$svc")
            log "[deploy] $svc did not build, and the fault is this commit's (log: $DEPLOY_LOG_DIR/$svc.log)"
        else
            log "[deploy] $svc did not build, and the fault is this box's (log: $DEPLOY_LOG_DIR/$svc.log)"
        fi
    done
    if [ "${#BUILD_FAILED_SERVICES[@]}" -gt 0 ]; then
        log "[deploy] build failed for ${BUILD_FAILED_SERVICES[*]}; nothing is rolled this cycle"
        return 0
    fi

    tree_is_pinned "before the rollouts" || { ship_abandoned=1; return 0; }
    for svc in "${wanted[@]}"; do
        deployment="$(gh_deployment_create "$svc" "${gate_scope:-full}")"
        if cluster_roll_image "${built[$svc]}"; then
            DEPLOYED_SERVICES+=("$svc")
            printf '%s\n' "${built[$svc]}" > "$STATE_DIR/stack-images/$svc"
            gh_deployment_status "$deployment" "$svc" "success" "live at ${NEW_SHA:0:12}"
            log "[deploy] $svc is live on ${built[$svc]}"
        else
            BOOT_FAILED_SERVICES+=("$svc")
            FAILED_SERVICES+=("$svc")
            gh_deployment_status "$deployment" "$svc" "failure" "did not roll out; undone"
            log "[deploy] $svc did not roll out; the objects that failed were undone"
        fi
    done
    return 0
}

_deploy_services || log "[deploy] step aborted unexpectedly; the bookmark holds"
cluster_ship_cycle_image || log "[cycle-image] aborted unexpectedly; the loop keeps the image it runs"
