#!/bin/bash
# Step 15: fast-forward the clone to origin/main under the lock, so a dead push
# webhook makes a deploy late rather than invisible.
#
# The webhook (infra/webhook/trigger-deploy.sh) pulls on every push and owns the
# REPAIR of a dirty or diverged clone. This step only moves a clone that is
# behind; two writers with two repair policies on one clone is worse than the
# stall either fixes.
#
# When it did move the clone, it STOPS the cycle: the fetch rewrote steps 20 to
# 90 on disk after this cycle snapshotted them, so the next tick runs the whole
# job from one commit.
#
# FAILURE POLICY: every path returns 0; a clone that cannot move runs this
# cycle on the tree it has. A dirty or diverged clone alerts once per sha,
# because nothing in the cycle will fix it.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

AUTO_DEPLOY_FETCH_ENABLED="${AUTO_DEPLOY_FETCH_ENABLED:-1}"
WEBHOOK_LOG="${WEBHOOK_LOG:-$LOG_DIR/webhook.log}"

fast_forward_the_clone() {
    local head_before head_after dirty
    if [ "$AUTO_DEPLOY_FETCH_ENABLED" != "1" ]; then
        log "[fresh] AUTO_DEPLOY_FETCH_ENABLED=0: not fetching"
        return 0
    fi
    head_before=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo "")
    if [ -z "$head_before" ]; then
        log "[fresh] cannot read HEAD in $REPO; leaving the clone alone"
        return 0
    fi
    dirty=$(git -C "$REPO" status --porcelain --untracked-files=no 2>/dev/null | wc -l)
    if [ "${dirty:-0}" -gt 0 ]; then
        log "[fresh] the clone carries ${dirty} uncommitted change(s); not fast-forwarding"
        fire_alert_once "clone-frozen" "$head_before" \
            "auto-deploy: the server clone is dirty and cannot be fast-forwarded" \
            "$REPO is at ${head_before:0:12} with uncommitted tracked changes, so no fetch can move it. The next push repairs it (the webhook parks the edits under $HARNESS_ROOT/repo-selfheal/ and resets the clone). If pushes are not arriving either, look at it by hand: cd $REPO && git status. Log: $LOG" \
            --wakes-somebody
        return 0
    fi
    if ! timeout "${AUTO_DEPLOY_FETCH_TIMEOUT:-60}" git -C "$REPO" fetch --quiet origin main >> "$LOG" 2>&1; then
        log "[fresh] fetch of origin/main failed; this cycle runs on ${head_before:0:8}"
        return 0
    fi
    if ! git -C "$REPO" merge --ff-only FETCH_HEAD >> "$LOG" 2>&1; then
        if git -C "$REPO" merge-base --is-ancestor HEAD FETCH_HEAD 2>/dev/null; then
            log "[fresh] the merge could not run this tick; the clone is behind, not diverged, and the next tick retries"
            return 0
        fi
        log "[fresh] ${head_before:0:8} is not a fast-forward of origin/main; refusing to move it"
        fire_alert_once "clone-frozen" "$head_before" \
            "auto-deploy: the server clone has diverged from origin/main" \
            "$REPO is at ${head_before:0:12}, which origin/main does not contain, so the cycle cannot fast-forward it and deliberately will not reset it. Look at it by hand: cd $REPO && git status && git log --oneline -5. Log: $LOG" \
            --wakes-somebody
        return 0
    fi
    head_after=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo "$head_before")
    [ "$head_after" = "$head_before" ] && return 0
    if [ -r "$WEBHOOK_LOG" ] && grep -q "commit ${head_after:0:8} " "$WEBHOOK_LOG" 2>/dev/null; then
        log "[fresh] fast-forwarded ${head_before:0:8} -> ${head_after:0:8}; the webhook logged this push too, so this tick only beat it"
    else
        record_to_talk "auto-deploy: a push the webhook never logged" \
            "The timer, not the webhook, brought ${head_after:0:12} onto the server. Deploys still land, one tick late. Check the listener: systemctl status harness-webhook, $WEBHOOK_LOG, and the hook's recent deliveries in the repository's GitHub settings."
    fi
    log "[fresh] stopping here so the next tick runs the whole cycle from one commit"
    exit 0
}

fast_forward_the_clone \
    || log "[fresh] freshness check aborted unexpectedly; running on the tree the clone has"
