#!/bin/bash
# The verifying lane's eject: take ONE red commit off main and hand it back,
# for a red a verifying run produced.
#
#   commit_gate/eject.sh <sha> <reason>
#
# run_one.sh calls it the moment it writes a red verdict. It re-checks that
# itself and refuses a sha with no red verdict for its CURRENT tree, so a hand
# run on a mistyped sha reverts nothing. OLD_SHA is <sha>^, so whether the
# commit can be taken back turns on its PARENT being known good rather than on
# the bookmark; `parent_unverified` is this arm's ordinary first answer, and the
# cycle's arm (steps/88-eject.sh) decides the commit later if this one cannot.
#
# EJECT_ENABLED=1 arms it, as it arms the whole eject; EJECT_RUN_ENABLED=0
# leaves every red to the cycle's arm. Keep it 1 in the cluster: the cycle
# jumps past a red once a newer commit is green, so a red only this lane saw
# would never be taken back. The two arms keep their claims on two volumes;
# what stops a second revert is the decision this arm writes, which travels to
# the cycle in ConfigMap commit-gate-verdicts, and eject_body.sh declining a
# commit whose `Auto-Eject:` revert is already on main (`already_reverted`).
#
# The mechanism is steps/eject_body.sh; this file holds the lane's two hooks.
# Exit code is always 0: run_one.sh's exit code is the suite's verdict, not this.

set -u
SELF="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$SELF/../steps/doors.sh"
REPO="${COMMIT_GATE_REPO:-$HARNESS_ROOT/repo}"
harness_load_config "$REPO"
STATE_DIR="${STATE_DIR:-/var/lib/harness}"
GATE_VERDICT_DIR="${GATE_VERDICT_DIR:-$STATE_DIR/gate-verdicts}"
LAST_SHA_FILE="$STATE_DIR/last-deployed-sha"
GH_REPO_SLUG="${GH_REPO_SLUG:-$(harness_repo_slug "$REPO")}"
GH_REPO_OWNER="${GH_REPO_OWNER:-$(harness_repo_owner "$REPO")}"
LOG="${COMMIT_GATE_LOG:-/var/log/harness/commit-gate.log}"
{ : >> "$LOG"; } 2>/dev/null || LOG="/tmp/harness-commit-gate.log"
NEW_SHA="${1:-}"
RED_REASON="${2:-regression}"
log() { printf '[%s] [eject %s] %s\n' "$(date -Iseconds)" "${NEW_SHA:0:12}" "$*" | tee -a "$LOG" >&2; }

if [ "${EJECT_ENABLED:-0}" != "1" ] && [ "${EJECT_DRY_RUN:-0}" != "1" ]; then
    log "the eject is off (EJECT_ENABLED=0); the red verdict stands and the cycle holds the bookmark"
    exit 0
fi
if [ "${EJECT_RUN_ENABLED:-1}" != "1" ]; then
    log "EJECT_RUN_ENABLED=0; the cycle's arm decides this red"
    exit 0
fi
[ -n "$NEW_SHA" ] || { log "usage: eject.sh <sha> <reason>"; exit 0; }
NEW_SHA="$(git -C "$REPO" rev-parse --verify --quiet "${NEW_SHA}^{commit}" 2>/dev/null)" || { log "not a commit"; exit 0; }
OLD_SHA="$(git -C "$REPO" rev-parse --verify --quiet "${NEW_SHA}^" 2>/dev/null || echo "")"
CHANGED="$(git -C "$REPO" diff --name-only "$OLD_SHA" "$NEW_SHA" 2>/dev/null || true)"
gate_red=1
gate_red_reason="$RED_REASON"
BOOT_FAILED_SERVICES=()
BUILD_RED_SERVICES=()
queue_depth=$(git -C "$REPO" rev-list --count "${NEW_SHA}..origin/main" 2>/dev/null || echo 0)
commits_ahead="$queue_depth"

# The lane's refusals: the verdict must still be a red for this tree, and the
# parent must be known good.
_eject_arm_preconditions_hold() {
    local r_sha="" r_verdict="" r_scope="" r_at="" r_reason="" r_tree=""
    read -r r_sha r_verdict r_scope r_at r_reason r_tree < "$GATE_VERDICT_DIR/$NEW_SHA" 2>/dev/null || true
    : "$r_scope$r_at$r_reason"
    if [ "$r_sha" != "$NEW_SHA" ] || [ "$r_verdict" != "red" ] \
            || [ "$r_tree" != "$(git -C "$REPO" rev-parse "${NEW_SHA}^{tree}" 2>/dev/null)" ]; then
        eject_reason="no_red_verdict"; return 1
    fi
    if ! _eject_parent_is_green; then
        if [ "$eject_parent_state" = "red" ]; then eject_reason="parent_red"; else eject_reason="parent_unverified"; fi
        return 1
    fi
    if git -C "$REPO" merge-base --is-ancestor "$NEW_SHA" "$(cat "$LAST_SHA_FILE" 2>/dev/null || echo none)" 2>/dev/null; then
        eject_reason="already_shipped"; return 1
    fi
    return 0
}

_eject_evidence_paths() {
    EJECT_TAIL_FILE="$STATE_DIR/gate-red-tails/$NEW_SHA"
    EJECT_SCOPE_FILE="$STATE_DIR/gate-scopes/$NEW_SHA.json"
    EJECT_NO_TAIL_HINT="No failing-test list was recorded for this commit; the lane's log has the run (kubectl -n ${DEPLOY_NAMESPACE:-deploy} logs -l app.kubernetes.io/name=commit-gate)."
    return 0
}

# shellcheck disable=SC1091
if ! . "$SELF/../steps/eject_body.sh"; then
    log "steps/eject_body.sh did not load; the cycle's arm decides this red"
    exit 0
fi

trigger="gate-red"
_eject_decide "$trigger"
case "$eject_outcome" in
    declined|off) [ "$eject_outcome" = off ] || _eject_write_decision "$eject_outcome" "${eject_reason:-unknown}" ;;
esac
log "outcome ${eject_outcome:-none} (${eject_reason:-$trigger})${eject_issue:+, hand-back #$eject_issue}"
exit 0
