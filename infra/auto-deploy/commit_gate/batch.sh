#!/bin/bash
# batch.sh <base> <sha>... : a burst verified as one batch, split only when red.
#
#   <base>   the commit under the first one, already answered (the bookmark,
#            or the newest commit with a verdict)
#   <sha>... the commits after it, oldest first, on main's first-parent line
#
# The whole range is verified once, on the newest commit's tree, with the
# selection of every change in it (`run_one.sh` with COMMIT_GATE_BATCH_BASE),
# and a green answers every commit in it. A red is split: the older half is
# asked on its own, a green half moves the base past it, and the search goes on
# until one commit is red on its own run, which writes the red and hands it to
# the eject as any lane red is. That commit and those after it are left to the
# next pass, which batches what is behind the revert.
#
#   rc of a run            what happens next
#   0 green                everything up to its head is answered; ask the rest
#   1 red, several         ask the older half
#   1 red, one commit      found: its run wrote the red; stop
#   3 no test reachable    as green: no commit in the range reaches a test
#   anything else          stop: no verdict, the next pass asks again
#
# FAILURE POLICY: the driver decides nothing itself. Every verdict is written by
# the run that produced it, and every path exits 0, as verify_ahead.sh does.
set -u

SELF="$(cd "$(dirname "$0")" && pwd)"
COMMIT_GATE_OUTCOME_FILE="${COMMIT_GATE_OUTCOME_FILE:-}"

log() { printf '[%s] [commit-gate batch] %s\n' "$(date -Iseconds)" "$*" >&2; }

BASE="${1:-}"
shift || true
COMMITS=("$@")
if [ -z "$BASE" ] || [ "${#COMMITS[@]}" -eq 0 ]; then
    printf 'usage: batch.sh <base> <sha>...\n' >&2
    exit 0
fi

# One run of the range from index <lo> to <hi>; prints nothing, returns its rc.
_batch_run() {
    local lo="$1" hi="$2" base="$BASE" head="${COMMITS[$2]}" rc
    [ "$lo" -gt 0 ] && base="${COMMITS[$(( lo - 1 ))]}"
    if [ "$lo" -eq "$hi" ]; then
        log "${head:0:12} on its own"
        bash "$SELF/run_one.sh" "$head"
    else
        log "${head:0:12} as a batch of $(( hi - lo + 1 )) since ${base:0:12}"
        COMMIT_GATE_BATCH_BASE="$base" bash "$SELF/run_one.sh" "$head"
    fi
    rc=$?
    [ -n "$COMMIT_GATE_OUTCOME_FILE" ] && printf '%s %s\n' "$head" "$rc" >> "$COMMIT_GATE_OUTCOME_FILE" 2>/dev/null
    return "$rc"
}

lo=0
last=$(( ${#COMMITS[@]} - 1 ))
hi=$last
red_head=-1
while [ "$lo" -le "$hi" ]; do
    _batch_run "$lo" "$hi"
    rc=$?
    case "$rc" in
        0 | 3)
            lo=$(( hi + 1 ))
            if [ "$red_head" -ge "$lo" ]; then
                hi=$red_head
            else
                red_head=-1
                hi=$last
            fi ;;
        1)
            if [ "$lo" -eq "$hi" ]; then
                log "${COMMITS[$hi]:0:12} is the red commit; what follows it waits for the next pass"
                break
            fi
            red_head=$hi
            hi=$(( lo + (hi - lo + 1) / 2 - 1 )) ;;
        *)
            log "no verdict (rc=$rc); the next pass asks again"
            break ;;
    esac
done
exit 0
