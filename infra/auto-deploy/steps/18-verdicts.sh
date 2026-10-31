#!/bin/bash
# Step 18: when the verifying lane (../commit_gate/) runs on ANOTHER box, send it
# the bookmark and fetch the verdicts it wrote, so step 20 can see them.
#
# On one box (the default) the lane writes into this box's STATE_DIR directly
# and this step does nothing. COMMIT_GATE_LANE_HOST (user@host) turns it on;
# that box must then run with EJECT_RUN_ENABLED=0, because the eject's
# once-per-sha claim is a directory and two boxes deciding could take one
# commit off main twice.
#
# `--ignore-existing` on every fetch, so nothing off the network replaces a
# verdict this box wrote. Must stay above 20, which reads what it fetched.
#
# FAILURE POLICY: every path returns 0. Nothing fetched means the cycle gates
# the commit itself, which is what it does without a lane.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

COMMIT_GATE_LANE_HOST="${COMMIT_GATE_LANE_HOST:-}"
COMMIT_GATE_LANE_STATE="${COMMIT_GATE_LANE_STATE:-/var/lib/harness}"
COMMIT_GATE_LANE_TIMEOUT="${COMMIT_GATE_LANE_TIMEOUT:-25}"

_lane_rsync() {
    rsync --archive --timeout="$COMMIT_GATE_LANE_TIMEOUT" "$@" \
        -e "ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new" \
        > /dev/null 2>&1
}

_exchange_with_lane() {
    local drawer failed=0
    [ -n "$COMMIT_GATE_LANE_HOST" ] || return 0
    if ! command -v rsync > /dev/null 2>&1; then
        log "[verdicts] rsync is not on this box; the cycle gates every commit itself"
        return 0
    fi
    if [ -r "$LAST_SHA_FILE" ]; then
        _lane_rsync "$LAST_SHA_FILE" "$COMMIT_GATE_LANE_HOST:$COMMIT_GATE_LANE_STATE/last-deployed-sha" \
            || log "[verdicts] the bookmark did not reach $COMMIT_GATE_LANE_HOST"
    fi
    for drawer in gate-verdicts gate-red-tails gate-scopes; do
        mkdir -p "$STATE_DIR/$drawer" 2>/dev/null || true
        _lane_rsync --ignore-existing "$COMMIT_GATE_LANE_HOST:$COMMIT_GATE_LANE_STATE/$drawer/" \
            "$STATE_DIR/$drawer/" || failed=$(( failed + 1 ))
    done
    [ "$failed" -eq 0 ] || log "[verdicts] $failed of 3 drawers did not come back from $COMMIT_GATE_LANE_HOST; this cycle gates what it cannot read"
    return 0
}

_exchange_with_lane || true
