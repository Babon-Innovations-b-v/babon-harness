#!/bin/bash
# Run several commits through run_one.sh at once, up to COMMIT_GATE_SLOTS.
#
#   commit_gate/run_many.sh <sha> [<sha> ...]
#
# Decides nothing: every verdict is written by the run that produced it. Free
# space is checked before EACH launch, against COMMIT_GATE_MIN_FREE_MB. Each run
# is one pytest process by default (COMMIT_GATE_WORKERS=0), which is why several
# of them side by side beat one wide run.
#
# Exit 0 all green, 1 at least one red, 2 at least one run could not finish.
# Records `<sha> <rc>` or `<sha> refused` in COMMIT_GATE_OUTCOME_FILE when set,
# so the driver can tell an answer from a launch that never happened.

set -u
SELF="$(cd "$(dirname "$0")" && pwd)"
COMMIT_GATE_SLOTS="${COMMIT_GATE_SLOTS:-4}"
COMMIT_GATE_ROOT="${COMMIT_GATE_ROOT:-${HARNESS_ROOT:-/opt/harness}/commit-gate}"
COMMIT_GATE_MIN_FREE_MB="${COMMIT_GATE_MIN_FREE_MB:-4096}"
COMMIT_GATE_OUTCOME_FILE="${COMMIT_GATE_OUTCOME_FILE:-}"
log() { printf '[%s] [commit-gate] %s\n' "$(date -Iseconds)" "$*" >&2; }
_record_outcome() {
    local sha="$1" outcome="$2"
    [ -n "$COMMIT_GATE_OUTCOME_FILE" ] || return 0
    printf '%s %s\n' "$sha" "$outcome" 2>/dev/null >> "$COMMIT_GATE_OUTCOME_FILE" \
        || log "could not record what happened to ${sha:0:12}"
    return 0
}
_report_one() {
    local sha="$1" rc="$2"
    _record_outcome "$sha" "$rc"
    case "$rc" in
        0) log "${sha:0:12} GREEN" ;;
        1) log "${sha:0:12} RED (rc=1), verdict written" ;;
        3) log "${sha:0:12} had nothing to run (scope none); no verdict, and no re-run can change that" ;;
        79) log "${sha:0:12} would not have run the cycle's own suite; left to the cycle" ;;
        2|4|5) log "${sha:0:12} RED for this run (rc=$rc), nothing written; the next reader runs it again" ;;
        *) log "${sha:0:12} could not be judged (rc=$rc)" ;;
    esac
    return 0
}
[ "$#" -gt 0 ] || { printf 'usage: run_many.sh <sha> [<sha> ...]\n' >&2; exit 64; }
mkdir -p "$COMMIT_GATE_ROOT" 2>/dev/null
free_mb() {
    local answer
    answer="$(df --output=avail -m "$COMMIT_GATE_ROOT" 2>/dev/null | tail -1 | tr -d ' ')"
    case "$answer" in
        "" | *[!0-9]*) printf '0' ;;
        *) printf '%s' "$answer" ;;
    esac
}
declare -a PIDS=() SHAS=()
started=0
worst=0
_collect_oldest() {
    local rc
    wait "${PIDS[0]}"
    rc=$?
    _report_one "${SHAS[0]}" "$rc"
    case "$rc" in
        0) ;;
        1|2|3|4|5) [ "$worst" -lt 1 ] && worst=1 ;;
        *) worst=2 ;;
    esac
    PIDS=("${PIDS[@]:1}")
    SHAS=("${SHAS[@]:1}")
    return 0
}
for sha in "$@"; do
    while [ "${#PIDS[@]}" -ge "$COMMIT_GATE_SLOTS" ]; do
        _collect_oldest
    done
    have="$(free_mb)"
    if [ "$have" -lt "$COMMIT_GATE_MIN_FREE_MB" ]; then
        log "only ${have} MB free at $COMMIT_GATE_ROOT (floor ${COMMIT_GATE_MIN_FREE_MB} MB), not starting ${sha:0:12}"
        _record_outcome "$sha" "refused"
        continue
    fi
    log "starting ${sha:0:12}"
    bash "$SELF/run_one.sh" "$sha" &
    PIDS+=("$!")
    SHAS+=("$sha")
    started=$(( started + 1 ))
done
while [ "${#PIDS[@]}" -gt 0 ]; do
    _collect_oldest
done
log "$started run(s) finished"
exit "$worst"
