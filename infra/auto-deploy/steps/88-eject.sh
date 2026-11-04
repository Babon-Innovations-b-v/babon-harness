#!/bin/bash
# Step 88: the cycle's eject. Takes a commit the gate rejected back off main and
# hands it to its author on a branch and a draft pull request.
#
# OFF WHEN UNSET OR 0 (the shipped config sets EJECT_ENABLED=1): then this step
# decides nothing, the red holds the bookmark, and step 90 alerts that the
# queue is frozen. The mechanism
# and its bounds are in steps/eject_body.sh; this file holds the cycle's own two
# hooks and the record of what happened.
#
# This arm answers the reds the verifying lane never sees: the commit the cycle
# is gating itself, every rc 2 to 5, a build the commit broke and a service that
# would not boot. It STANDS DOWN for a commit whose decision file already says
# `pushed` (the lane's arm reverted it first).
#
# Numbered 88 on purpose: its push moves main, so it sits after every step that
# reads the clone, and 90 is the only step after it.
#
# FAILURE POLICY: best-effort. Nothing here can fail the cycle; a decision that
# could not finish leaves main untouched and the red standing.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

# The cycle's own refusals: its range must be ONE commit sitting on the
# bookmark (a red on a jumped range names no commit), and the bookmark's own
# verdict must not be red.
_eject_arm_preconditions_hold() {
    local p_sha="" p_word="" p_scope="" p_at="" p_reason="" p_tree=""
    if [ "${EJECT_REQUIRE_ISOLATED:-1}" = "1" ] && [ "${gate_range_isolated:-0}" -ne 1 ]; then
        eject_reason="not_isolated"; return 1
    fi
    if [ -n "${OLD_SHA:-}" ] && [ -r "$GATE_VERDICT_DIR/$OLD_SHA" ]; then
        read -r p_sha p_word p_scope p_at p_reason p_tree < "$GATE_VERDICT_DIR/$OLD_SHA" 2>/dev/null || true
        : "$p_scope$p_at$p_reason"
        if [ "$p_sha" = "$OLD_SHA" ] && [ "$p_word" = "red" ] && [ -n "$p_tree" ] \
                && [ "$p_tree" = "$(git -C "$REPO" rev-parse "${OLD_SHA}^{tree}" 2>/dev/null)" ]; then
            eject_reason="parent_red"; return 1
        fi
    fi
    return 0
}

# Which failure text to quote: the commit's own tail from the lane, unless this
# cycle ran pytest itself and went red at rc=1, when the cycle's tail is about
# the same commit and carries the assertion lines.
_eject_evidence_paths() {
    local own_tail="$STATE_DIR/gate-red-tails/${NEW_SHA:-}"
    EJECT_TAIL_FILE="$STATE_DIR/gate-red-tail"
    if [ "${gate_reused:-0}" = "1" ] || [ "${gate_red_reason:-}" != "regression" ] || [ ! -s "$EJECT_TAIL_FILE" ]; then
        [ -s "$own_tail" ] && EJECT_TAIL_FILE="$own_tail"
    fi
    EJECT_SCOPE_FILE="$STATE_DIR/gate-scope.json"
    EJECT_NO_TAIL_HINT="No pytest tail was captured for this run; the deploy log on the server has it."
    return 0
}

if ! . "$(dirname "${BASH_SOURCE[0]}")/eject_body.sh"; then
    log "eject: steps/eject_body.sh did not load, so no red is answered this cycle"
    eject_pushed=0
    return 0
fi
commits_ahead="${queue_depth:-0}"

_eject_record() {
    local trigger="$1" outcome="$2" reason="$3"
    : "$trigger"
    [ "$outcome" = "off" ] || _eject_write_decision "$outcome" "$reason"
    case "$outcome" in
        pushed)
            log "eject: reverted ${NEW_SHA:0:12} on main as ${eject_revert_sha:0:12} ($reason); hand-back ${eject_issue:-none}"
            record_to_talk "auto-deploy: a commit was reverted on main" \
                "The gate rejected ${NEW_SHA:0:12}, \"$(_commit_subject "$NEW_SHA")\" ($reason). It was reverted on main as ${eject_revert_sha:0:12} and handed back on ${eject_branch:+pull request }#${eject_issue:-none}. Its author is notified by GitHub."
            ;;
        dry_run)
            log "eject: DRY RUN, would have reverted ${OLD_SHA:0:12}..${NEW_SHA:0:12} ($reason); issue ${eject_issue:-none}"
            ;;
        aborted)
            fire_alert_once "eject-aborted" "$NEW_SHA" "auto-deploy: an eject could not finish" \
                "The deploy server decided to revert ${NEW_SHA:0:12} and could not: $reason. main is untouched and the red still stands, so the commit is still blocking everything behind it. Log: $LOG"
            ;;
        off)
            log "eject: off (EJECT_ENABLED=0); the red on ${NEW_SHA:0:12} stands until a person fixes or reverts it"
            ;;
        *)
            log "eject: declined ($reason) for ${NEW_SHA:0:12}; the red stands"
            ;;
    esac
    return 0
}

_eject_cycle() {
    local trigger decided="" rest=""
    trigger="$(_eject_trigger)"
    [ -n "$trigger" ] || return 0
    if [ -r "$EJECT_DECISION_DIR/$NEW_SHA" ]; then
        read -r decided rest < "$EJECT_DECISION_DIR/$NEW_SHA" 2>/dev/null || true
        : "$rest"
        if [ "$decided" = "pushed" ]; then
            log "eject: the verifying lane already reverted ${NEW_SHA:0:12}; this arm decides nothing about it"
            return 0
        fi
    fi
    _eject_decide "$trigger"
    _eject_record "$trigger" "$eject_outcome" "${eject_reason:-$trigger}"
    return 0
}

_eject_cycle || log "eject: step aborted unexpectedly (deploy unaffected)"
