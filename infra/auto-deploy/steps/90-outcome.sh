#!/bin/bash
# Step 90: decide what the cycle did, move the bookmark, post the statuses,
# and clean up.
#
# THE BOOKMARK ($STATE_DIR/last-deployed-sha, copied to ConfigMap
# deploy-bookmark when it moves) moves only when the commit shipped
# whole: a green gate (or nothing to verify), every changed service built and
# booted, no ship action abandoned. One exception: a red whose eject PUSHED a
# revert sitting directly on the rejected commit (the restore route) moves it to
# that commit, so the next cycle gates the revert rather than a commit that is
# gone. On the lift route main had moved, so the bookmark holds.
#
# THE STATUSES. vm/deploy on the whole range; vm/build and vm/boot as the
# terminal roll-up of step 50 (only final here). `failure` the stage said no,
# `error` it could not form an opinion; never one for the other.
#
# THE FROZEN QUEUE. A bookmark that has not moved for QUEUE_BLOCKED_LIMIT cycles
# with work behind it alerts once, keyed on the bookmark: when the eject is off
# that alert is the whole hand-back, so it fires on the first
# cycle a red holds the queue.
#
# FAILURE POLICY: exits 1 when the cycle failed, so the cycle's Job is marked
# failed; never before the bookkeeping is done.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

bookmark_moved=0
queue_hold=""
cycle_failed=0
if [ "${gate_red:-0}" -eq 1 ]; then
    queue_hold="the gate rejected"
    if [ "${eject_pushed:-0}" -eq 1 ] && [ -n "${eject_base_sha:-}" ] && [ "$eject_base_sha" = "$NEW_SHA" ]; then
        bookmark_moved=1
        echo "$eject_base_sha" > "$LAST_SHA_FILE"
        log "gate RED and ${NEW_SHA:0:12} was reverted directly on top; the bookmark moves to it so the next cycle gates the revert"
    else
        log "gate RED; the bookmark stays at $(cat "$LAST_SHA_FILE" 2>/dev/null || echo none)"
    fi
    record_deploy_verdict gate_red
elif [ "${#FAILED_SERVICES[@]}" -eq 0 ] && [ "${ship_abandoned:-0}" -eq 0 ]; then
    bookmark_moved=1
    echo "$NEW_SHA" > "$LAST_SHA_FILE"
    rm -f "$BUILD_HEAD_RED_FILE" 2>/dev/null || true
    record_deploy_verdict success
    record_deploy_metric harness_deploy_last_success_timestamp_seconds "$(date +%s)"
    gh_status_range "success" "deployed: ${DEPLOYED_SERVICES[*]:-nothing to deploy}"
    log "deploy complete at ${NEW_SHA:0:12}: ${DEPLOYED_SERVICES[*]:-nothing to deploy}"
elif [ "${#FAILED_SERVICES[@]}" -eq 0 ]; then
    queue_hold="a ship action was deferred for"
    record_deploy_verdict ship_abandoned
    gh_status_range "error" "deferred to the next tick; this commit is retried"
    log "a ship action was abandoned; the bookmark holds and the next tick retries"
else
    queue_hold="the deploy failed (${FAILED_SERVICES[*]}) for"
    cycle_failed=1
    record_deploy_verdict partial_fail
    gh_status_range "error" "deploy failed: ${FAILED_SERVICES[*]}"
    log "PARTIAL FAILURE: ok=${DEPLOYED_SERVICES[*]:-none} failed=${FAILED_SERVICES[*]}; the bookmark holds and the next cycle retries"
fi
[ "$bookmark_moved" -eq 1 ] && cluster_bookmark_push

if [ "${gate_red:-0}" -eq 0 ]; then
    if [ "${#BUILD_RED_SERVICES[@]}" -ne 0 ]; then
        gh_stage_range "vm/build" "failure" "image build failed: ${BUILD_RED_SERVICES[*]}"
    elif [ "${#BUILD_FAILED_SERVICES[@]}" -ne 0 ]; then
        gh_stage_range "vm/build" "error" "could not build on this server: ${BUILD_FAILED_SERVICES[*]}"
    elif [ "${#DEPLOYED_SERVICES[@]}" -gt 0 ]; then
        gh_stage_range "vm/build" "success" "built: ${DEPLOYED_SERVICES[*]}"
    fi
    if [ "${#BOOT_FAILED_SERVICES[@]}" -ne 0 ]; then
        gh_stage_range "vm/boot" "failure" "did not boot, rolled back: ${BOOT_FAILED_SERVICES[*]}"
    elif [ "${#DEPLOYED_SERVICES[@]}" -gt 0 ]; then
        gh_stage_range "vm/boot" "success" "booted: ${DEPLOYED_SERVICES[*]}"
    fi
fi

# A build the box could not do, three cycles running, is a box to fix.
BUILD_AMBER_FILE="$STATE_DIR/build-amber-streak"
if [ "${#BUILD_FAILED_SERVICES[@]}" -eq 0 ]; then
    rm -f "$BUILD_AMBER_FILE" 2>/dev/null || true
elif [ "${#BUILD_RED_SERVICES[@]}" -eq 0 ]; then
    build_amber_streak=$(( $(cat "$BUILD_AMBER_FILE" 2>/dev/null || echo 0) + 1 ))
    echo "$build_amber_streak" > "$BUILD_AMBER_FILE" 2>/dev/null || true
    if [ "$build_amber_streak" -ge "${BUILD_AMBER_LIMIT:-3}" ]; then
        fire_alert_once "build-box-fault" "$(cat "$LAST_SHA_FILE" 2>/dev/null || echo none)" \
            "auto-deploy: this server cannot build images" \
            "Image builds have failed for $build_amber_streak cycles running, for reasons about this machine rather than any commit (disk, registry, docker). Nothing is reverted and the bookmark holds until a build succeeds. Services: ${BUILD_FAILED_SERVICES[*]}. Logs: $STATE_DIR/build-logs/. Start with df -h and docker info." \
            --wakes-somebody
    fi
fi

# ── The frozen queue ────────────────────────────────────────────────────────
EJECT_DECISION_DIR="${EJECT_DECISION_DIR:-$STATE_DIR/eject-decisions}"
queue_key="${OLD_SHA:-no-baseline}"
queue_state="$STATE_DIR/queue-blocked"
decided=""; decided_reason=""
[ -r "$EJECT_DECISION_DIR/${NEW_SHA:-none}" ] \
    && read -r decided decided_reason _ < "$EJECT_DECISION_DIR/$NEW_SHA" 2>/dev/null
if [ "$bookmark_moved" -eq 0 ] && [ -n "$queue_hold" ]; then
    queue_seen=""; queue_runs=0
    [ -r "$queue_state" ] && read -r queue_seen queue_runs < "$queue_state"
    case "$queue_runs" in "" | *[!0-9]*) queue_runs=0 ;; esac
    if [ "$queue_seen" = "$queue_key" ]; then queue_runs=$(( queue_runs + 1 )); else queue_runs=1; fi
    printf '%s %s\n' "$queue_key" "$queue_runs" > "$queue_state" 2>/dev/null || true
    queue_limit="${QUEUE_BLOCKED_LIMIT:-5}"
    # Nothing else will act on a red when the eject is off or declined for good.
    if [ "${gate_red:-0}" -eq 1 ] && [ "$decided" != "pushed" ]; then
        case "${eject_outcome:-}:${eject_reason:-$decided_reason}" in
            *:parent_unverified|*:rate_limited|*:already_decided|*:already_reverted) ;;
            *) queue_limit=1 ;;
        esac
    fi
    if [ "$queue_runs" -ge "$queue_limit" ] && [ "$decided" != "pushed" ]; then
        if [ "${gate_red:-0}" -eq 1 ]; then
            fire_alert_once "queue-blocked" "$queue_key" \
                "auto-deploy: a red commit is holding the deploy queue" \
                "The gate rejected ${NEW_SHA:0:12}, \"$(_commit_subject "$NEW_SHA")\" (${gate_red_reason:-unknown}), and it is still on main. $bookmark_depth commit(s) are waiting behind the bookmark. The eject ${eject_outcome:-did not run}${eject_reason:+ ($eject_reason)}. Fix or revert ${NEW_SHA:0:12} on main and the queue drains on the next tick. Log: $LOG" \
                --wakes-somebody
        else
            fire_alert_once "queue-blocked-unshipped" "$queue_key" \
                "auto-deploy: the deploy bookmark is stuck" \
                "$queue_hold ${NEW_SHA:0:12}, so the bookmark has not moved for $queue_runs cycle(s) and $bookmark_depth commit(s) wait behind it. The gate is not the problem: a build, a boot or a ship action is failing every cycle. Logs: $LOG and $STATE_DIR/build-logs/." \
                --wakes-somebody
        fi
    fi
else
    rm -f "$queue_state" 2>/dev/null || true
fi

# ── Clean up ────────────────────────────────────────────────────────────────
for evidence_dir in "$GATE_VERDICT_DIR" "$STATE_DIR/gate-red-tails" "$STATE_DIR/gate-scopes" "$EJECT_DECISION_DIR"; do
    [ -d "$evidence_dir" ] && find "$evidence_dir" -maxdepth 1 -type f -mtime +30 -delete 2>/dev/null
done
if [ -n "${BUILD_TREE:-}" ] && [ "${BUILD_TREE#"$BUILD_TREE_ROOT"/}" != "$BUILD_TREE" ]; then
    rm -rf "$BUILD_TREE" 2>/dev/null || true
fi
if [ -n "${STEPS_SNAPSHOT:-}" ] && [ "${STEPS_SNAPSHOT#/tmp/harness-deploy-steps-}" != "$STEPS_SNAPSHOT" ]; then
    rm -rf "$STEPS_SNAPSHOT" 2>/dev/null || true
fi

[ "$cycle_failed" -eq 0 ] || exit 1
