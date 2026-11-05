#!/bin/bash
# ONE pass of the verifying lane: every commit between the deploy bookmark and
# origin/main that has no verdict for its current tree yet, handed to
# run_many.sh, at most COMMIT_GATE_AHEAD_MAX of them, oldest first.
#
#   commit_gate/verify_ahead.sh            the queue past the bookmark
#   commit_gate/verify_ahead.sh <sha>...   these commits
#
# By default it leaves alone the commit the cycle is gating right now (the
# first one past the bookmark). COMMIT_GATE_TAKE_CYCLE_HEAD=1, which the
# commit-gate CronJob sets, takes it too: the lane has its own pod and volume,
# so every commit gets a verdict of its own and the cycle can ship on them
# (`deploy_loop trusted-head`). run_one.sh never replaces a green the cycle
# shipped on.
#
# COMMIT_GATE_BATCH=1 (set by the CronJob): two or more unanswered commits in a
# row, from the oldest on, go to batch.sh as one batch, verified once on the
# newest and split only while red; the rest wait for the next pass. Not capped
# by COMMIT_GATE_AHEAD_MAX, since a batch is one run.
#
# Its own lock (fd 8), never the cycle's. Every path exits 0: the cycle gates
# whatever this did not answer.

set -u
SELF="$(cd "$(dirname "$0")" && pwd)"
REPO="${COMMIT_GATE_REPO:-${HARNESS_ROOT:-/opt/harness}/repo}"
STATE_DIR="${STATE_DIR:-/var/lib/harness}"
GATE_VERDICT_DIR="${GATE_VERDICT_DIR:-$STATE_DIR/gate-verdicts}"
COMMIT_GATE_ROOT="${COMMIT_GATE_ROOT:-${HARNESS_ROOT:-/opt/harness}/commit-gate}"
COMMIT_GATE_SLOTS="${COMMIT_GATE_SLOTS:-4}"
export COMMIT_GATE_SLOTS
COMMIT_GATE_AHEAD_MAX="${COMMIT_GATE_AHEAD_MAX:-$(( COMMIT_GATE_SLOTS * 2 ))}"
COMMIT_GATE_BRANCH="${COMMIT_GATE_BRANCH:-origin/main}"
COMMIT_GATE_TAKEN_FILE="${COMMIT_GATE_TAKEN_FILE:-}"
COMMIT_GATE_SKIP_FILE="${COMMIT_GATE_SKIP_FILE:-}"
log() { printf '[%s] [verify-ahead] %s\n' "$(date -Iseconds)" "$*" >&2; }
_asked_to_skip() {
    local sha="$1"
    [ -n "$COMMIT_GATE_SKIP_FILE" ] || return 1
    [ -r "$COMMIT_GATE_SKIP_FILE" ] || return 1
    grep -qxF -- "$sha" "$COMMIT_GATE_SKIP_FILE" 2>/dev/null
}
mkdir -p "$COMMIT_GATE_ROOT" 2>/dev/null || { log "cannot make $COMMIT_GATE_ROOT"; exit 0; }
exec 8>"$COMMIT_GATE_ROOT/.verify-ahead.lock" || { log "cannot open the lock"; exit 0; }
if ! flock -n 8; then
    log "another driver holds the lock; leaving the queue to it"
    exit 0
fi
QUEUE=()
if [ "$#" -gt 0 ]; then
    for arg in "$@"; do
        if resolved="$(git -C "$REPO" rev-parse --verify --quiet "${arg}^{commit}")"; then
            QUEUE+=("$resolved")
        else
            log "$arg is not a commit in $REPO, skipping it"
        fi
    done
else
    bookmark=""
    [ -r "$STATE_DIR/last-deployed-sha" ] \
        && bookmark="$(cat "$STATE_DIR/last-deployed-sha" 2>/dev/null || true)"
    if [ -z "$bookmark" ]; then
        log "no bookmark, so there is no range to verify ahead of; leaving it"
        exit 0
    fi
    if ! git -C "$REPO" merge-base --is-ancestor "$bookmark" "$COMMIT_GATE_BRANCH" 2>/dev/null; then
        log "the bookmark is not an ancestor of $COMMIT_GATE_BRANCH; the cycle will say so too"
        exit 0
    fi
    while IFS= read -r sha; do
        [ -n "$sha" ] && QUEUE+=("$sha")
    done < <(git -C "$REPO" rev-list --reverse --first-parent \
        "$bookmark..$COMMIT_GATE_BRANCH" 2>/dev/null)
    if [ "${COMMIT_GATE_TAKE_CYCLE_HEAD:-0}" != "1" ]; then
        if [ "${#QUEUE[@]}" -gt 0 ]; then
            QUEUE=("${QUEUE[@]:1}")
        fi
    fi
fi
if [ "${#QUEUE[@]}" -eq 0 ]; then
    log "nothing queued"
    exit 0
fi
TODO=()
for sha in "${QUEUE[@]}"; do
    if _asked_to_skip "$sha"; then
        continue
    fi
    tree_now="$(git -C "$REPO" rev-parse "${sha}^{tree}" 2>/dev/null || echo "")"
    cached_sha=""; cached_verdict=""; cached_scope=""; cached_at=""; cached_reason=""
    cached_tree=""
    if [ -r "$GATE_VERDICT_DIR/$sha" ]; then
        read -r cached_sha cached_verdict cached_scope cached_at cached_reason \
            cached_tree < "$GATE_VERDICT_DIR/$sha" || true
    fi
    if [ "$cached_sha" = "$sha" ] && [ -n "$cached_tree" ] && [ "$cached_tree" = "$tree_now" ]; then
        continue
    fi
    TODO+=("$sha")
done
if [ "${#TODO[@]}" -eq 0 ]; then
    log "${#QUEUE[@]} commit(s) queued, all already answered"
    exit 0
fi
# The run of unanswered commits from TODO's first on, each the first-parent
# child of the one before it, as one batch.
if [ "${COMMIT_GATE_BATCH:-0}" = "1" ] && [ "${#TODO[@]}" -ge 2 ]; then
    base="$(git -C "$REPO" rev-parse --verify --quiet "${TODO[0]}^" 2>/dev/null || echo "")"
    if [ -n "$base" ]; then
        RUN=("${TODO[0]}")
        for sha in "${TODO[@]:1}"; do
            [ "$(git -C "$REPO" rev-parse --verify --quiet "${sha}^" 2>/dev/null)" = "${RUN[-1]}" ] || break
            RUN+=("$sha")
        done
        if [ "${#RUN[@]}" -ge 2 ]; then
            log "verifying ${#RUN[@]} commit(s) as one batch since ${base:0:12}"
            if [ -n "$COMMIT_GATE_TAKEN_FILE" ]; then
                printf '%s\n' "${RUN[@]}" 2>/dev/null > "$COMMIT_GATE_TAKEN_FILE" \
                    || log "could not record which commits this pass took on"
            fi
            bash "$SELF/batch.sh" "$base" "${RUN[@]}" 8>&-
            exit 0
        fi
    fi
fi
if [ "${#TODO[@]}" -gt "$COMMIT_GATE_AHEAD_MAX" ]; then
    log "${#TODO[@]} commit(s) need a verdict; taking the first $COMMIT_GATE_AHEAD_MAX in order"
    TODO=("${TODO[@]:0:$COMMIT_GATE_AHEAD_MAX}")
fi
log "verifying ${#TODO[@]} commit(s) ahead of the cycle, $COMMIT_GATE_SLOTS at a time"
if [ -n "$COMMIT_GATE_TAKEN_FILE" ]; then
    printf '%s\n' "${TODO[@]}" 2>/dev/null > "$COMMIT_GATE_TAKEN_FILE" \
        || log "could not record which commits this pass took on"
fi
bash "$SELF/run_many.sh" "${TODO[@]}" 8>&-
many_rc=$?
case "$many_rc" in
    0) log "every commit taken answered green" ;;
    1) log "at least one commit answered red; an rc=1 red left a verdict the cycle will read, and an rc 2-5 red left none, so the cycle runs that one itself" ;;
    *) log "the driver could not finish (rc=$many_rc); the cycle gates itself as usual" ;;
esac
exit 0
