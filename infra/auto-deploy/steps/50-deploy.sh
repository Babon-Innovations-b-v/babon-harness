#!/bin/bash
# Step 50: build and start the containers this commit changed, then check each
# one boots, and roll back any that does not.
#
#   1. Which services: tools in infra/auto-deploy/compose_fragments.py read the
#      fragment each changed path belongs to. `all` when the root
#      docker-compose.yml or config/ changed, or a new vault version arrived.
#   2. Build each from the VERIFIED tree, one service at a time so a failure
#      names its service. A failed build is the commit's fault or the box's
#      (steps/build_verdict.sh): the commit's can be ejected, the box's holds
#      the bookmark and alerts, and neither starts anything.
#   3. Start from the verified tree too: `docker compose up -d --no-deps` with
#      the compose files of $VERIFIED_TREE, so every bind mount reads a tree the
#      gate passed and that outlives the cycle (never the clone, which the
#      webhook moves; never $BUILD_TREE, which step 90 deletes).
#   4. The boot check: a service with a healthcheck must report healthy, one
#      without must still be running after BOOT_SETTLE_SECONDS. One that does
#      not is rolled back to the image and tree it ran before, and recorded in
#      BOOT_FAILED_SERVICES, which the eject reads.
#
# A red gate ships nothing: this step returns before touching a container.
#
# FAILURE POLICY: a failed build, start or boot is recorded and the bookmark
# holds; the next cycle retries. Nothing here exits the cycle.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

BOOT_CHECK_TIMEOUT="${BOOT_CHECK_TIMEOUT:-180}"
BOOT_SETTLE_SECONDS="${BOOT_SETTLE_SECONDS:-20}"
DEPLOY_LOG_DIR="$STATE_DIR/build-logs"

_compose_in() {
    # _compose_in <tree> <args...>: compose against one tree's files.
    local tree="$1"
    shift
    docker compose -p "$COMPOSE_PROJECT" --env-file "$HARNESS_ENV_FILE" \
        --project-directory "$tree" -f "$tree/docker-compose.yml" "$@"
}

_service_container() {
    docker ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
        --filter "label=com.docker.compose.service=$1" 2>/dev/null | head -1
}

# health of one service: healthy, unhealthy, starting, running, exited, missing.
_service_health() {
    local cid health state
    cid=$(_service_container "$1")
    [ -n "$cid" ] || { printf 'missing'; return 0; }
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$cid" 2>/dev/null)
    if [ -n "$health" ]; then printf '%s' "$health"; return 0; fi
    state=$(docker inspect --format '{{if .State.Restarting}}restarting{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null)
    printf '%s' "${state:-missing}"
}

_boot_check() {
    local svc="$1" waited=0 health
    while [ "$waited" -lt "$BOOT_CHECK_TIMEOUT" ]; do
        health=$(_service_health "$svc")
        case "$health" in
            healthy) return 0 ;;
            unhealthy|exited|dead|missing) return 1 ;;
            running)
                [ "$waited" -ge "$BOOT_SETTLE_SECONDS" ] && return 0 ;;
        esac
        sleep 5
        waited=$(( waited + 5 ))
    done
    log "[deploy] $svc did not settle within ${BOOT_CHECK_TIMEOUT}s (last state: $(_service_health "$svc"))"
    return 1
}

# Remember what each service runs now, so a failed boot can go back to it.
declare -A ROLLBACK_IMAGE ROLLBACK_NAME ROLLBACK_FILES ROLLBACK_DIR
_snapshot_service() {
    local svc="$1" cid
    cid=$(_service_container "$svc")
    [ -n "$cid" ] || return 0
    ROLLBACK_IMAGE[$svc]=$(docker inspect --format '{{.Image}}' "$cid" 2>/dev/null)
    ROLLBACK_NAME[$svc]=$(docker inspect --format '{{.Config.Image}}' "$cid" 2>/dev/null)
    ROLLBACK_FILES[$svc]=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$cid" 2>/dev/null)
    ROLLBACK_DIR[$svc]=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$cid" 2>/dev/null)
}

_rollback_service() {
    local svc="$1" files=() file
    if [ -z "${ROLLBACK_IMAGE[$svc]:-}" ] || [ -z "${ROLLBACK_DIR[$svc]:-}" ]; then
        log "[deploy] no earlier container for $svc (a first deploy); nothing to roll back to"
        return 0
    fi
    docker tag "${ROLLBACK_IMAGE[$svc]}" "${ROLLBACK_NAME[$svc]}" >> "$LOG" 2>&1 || true
    IFS=',' read -r -a files <<< "${ROLLBACK_FILES[$svc]}"
    local file_args=()
    for file in "${files[@]}"; do file_args+=(-f "$file"); done
    if docker compose -p "$COMPOSE_PROJECT" --env-file "$HARNESS_ENV_FILE" \
            --project-directory "${ROLLBACK_DIR[$svc]}" "${file_args[@]}" \
            up -d --no-deps --no-build "$svc" >> "$LOG" 2>&1; then
        log "[deploy] rolled $svc back to ${ROLLBACK_IMAGE[$svc]:0:19}"
    else
        log "[deploy] rolling $svc back FAILED; it is down"
        fire_alert_once "rollback-failed-$svc" "$NEW_SHA" \
            "auto-deploy: $svc is down and could not be rolled back" \
            "$svc did not boot at ${NEW_SHA:0:12}, and starting its previous image failed too. Look at it by hand: docker compose -p $COMPOSE_PROJECT ps; docker logs. Log: $LOG" \
            --wakes-somebody
    fi
}

_deploy_services() {
    local services=() svc build_log fault deployment tree="${VERIFIED_TREE:-}" up_args=()
    if [ "${gate_red:-0}" -eq 1 ]; then
        log "[deploy] the gate is red (${gate_red_reason:-unknown}); nothing is built or started"
        return 0
    fi
    if [ "${env_only:-false}" = true ]; then
        # No new commit: start the stack again from the tree it already runs.
        tree="$(cat "$STATE_DIR/live-tree" 2>/dev/null || echo "")"
        [ -d "$tree" ] || tree="$REPO"
        services=(all)
    elif [ -z "$tree" ]; then
        if ${compose_changed:-false}; then
            log "[deploy] no verified tree this cycle; nothing started, the next cycle retries"
            ship_abandoned=1
        fi
        return 0
    elif [ ! -f "$tree/docker-compose.yml" ]; then
        log "[deploy] the tree has no docker-compose.yml; there is nothing to start"
        return 0
    else
        if [ "${ENV_CHANGED:-false}" = true ]; then
            services=(all)
        else
            mapfile -t services < <(python3 "$REPO/infra/auto-deploy/compose_fragments.py" \
                --repo "$tree" --changed-file "$STATE_DIR/gate-changed-paths" 2>>"$LOG" || echo all)
        fi
    fi
    if [ "${#services[@]}" -eq 0 ]; then
        log "[deploy] no compose service changed"
        printf '%s\n' "$tree" > "$STATE_DIR/live-tree" 2>/dev/null || true
        return 0
    fi
    if [ "${services[0]}" = "all" ]; then
        mapfile -t services < <(_compose_in "$tree" config --services 2>>"$LOG")
        if [ "${#services[@]}" -eq 0 ]; then
            log "[deploy] docker compose could not read $tree/docker-compose.yml; nothing started"
            FAILED_SERVICES+=(compose-config)
            BUILD_FAILED_SERVICES+=(compose-config)
            return 0
        fi
    fi
    if [ "${caddy_invalid:-0}" -eq 1 ]; then
        # Step 30 found the commit's Caddyfile does not parse: the commit's
        # fault, and Caddy stays on the config it has.
        local kept=()
        for svc in "${services[@]}"; do [ "$svc" = "caddy" ] || kept+=("$svc"); done
        services=(${kept[@]+"${kept[@]}"})
        FAILED_SERVICES+=(caddy)
        BUILD_FAILED_SERVICES+=(caddy)
        BUILD_RED_SERVICES+=(caddy)
        log "[deploy] caddy left on its current config: the commit's Caddyfile does not validate"
        [ "${#services[@]}" -gt 0 ] || return 0
    fi
    log "[deploy] services: ${services[*]} (from ${tree##*/})"
    mkdir -p "$DEPLOY_LOG_DIR" 2>/dev/null

    # Build every service first; start nothing if any build failed.
    for svc in "${services[@]}"; do
        build_log="$DEPLOY_LOG_DIR/$svc.log"
        if [ "${env_only:-false}" = true ]; then break; fi
        if ! _compose_in "$tree" build --build-arg "GIT_SHA=$NEW_SHA" "$svc" > "$build_log" 2>&1; then
            fault=$(_build_fault_kind "$build_log")
            FAILED_SERVICES+=("$svc")
            BUILD_FAILED_SERVICES+=("$svc")
            if [ "$fault" = "commit" ]; then
                BUILD_RED_SERVICES+=("$svc")
                log "[deploy] $svc did not build, and the fault is this commit's (log: $build_log)"
            else
                log "[deploy] $svc did not build, and the fault is this box's (log: $build_log)"
            fi
        fi
    done
    if [ "${#BUILD_FAILED_SERVICES[@]}" -gt 0 ]; then
        log "[deploy] build failed for ${BUILD_FAILED_SERVICES[*]}; nothing is started this cycle"
        return 0
    fi

    for svc in "${services[@]}"; do _snapshot_service "$svc"; done
    up_args=(up -d --no-deps --no-build --remove-orphans)
    if ! _compose_in "$tree" "${up_args[@]}" "${services[@]}" >> "$LOG" 2>&1; then
        log "[deploy] docker compose up returned non-zero; the boot check decides per service"
    fi
    for svc in "${services[@]}"; do
        deployment="$(gh_deployment_create "$svc" "${gate_scope:-full}")"
        if _boot_check "$svc"; then
            DEPLOYED_SERVICES+=("$svc")
            gh_deployment_status "$deployment" "$svc" "success" "live at ${NEW_SHA:0:12}"
            log "[deploy] $svc is up"
        else
            BOOT_FAILED_SERVICES+=("$svc")
            FAILED_SERVICES+=("$svc")
            docker logs --tail 80 "$(_service_container "$svc")" > "$DEPLOY_LOG_DIR/$svc-boot.log" 2>&1 || true
            gh_deployment_status "$deployment" "$svc" "failure" "did not boot; rolled back"
            log "[deploy] $svc did not boot (container log: $DEPLOY_LOG_DIR/$svc-boot.log); rolling back"
            _rollback_service "$svc"
        fi
    done
    if [ "${#FAILED_SERVICES[@]}" -eq 0 ]; then
        printf '%s\n' "$tree" > "$STATE_DIR/live-tree" 2>/dev/null || true
    fi
    return 0
}

_deploy_services || log "[deploy] step aborted unexpectedly; the bookmark holds"
