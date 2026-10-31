#!/bin/bash
# The verifying lane's entry point, run by harness-commit-gate.timer every five
# minutes and started by the push webhook on every push.
#
# It owns four things and nothing else: a snapshot of this drawer (so a push
# landing mid-run cannot hand one pass half of one commit's scripts and half of
# another's), the sweep of trees left by killed runs, the per-commit attempt
# cap, and the drain: passes of verify_ahead.sh until a pass takes nothing on.
#
# THE ATTEMPT CAP counts ANSWERS, not offers. A commit taken on
# COMMIT_GATE_ATTEMPT_MAX times without ever getting a verdict (every run amber,
# or rc 2 to 5) is parked, never offered again, and alerts once. Refusals no
# retry can change (3 scope none, 79 another ignore list, no room) are not
# counted. The deploy cycle still gates a parked commit itself.
#
# COMMIT_GATE_DISPATCH_ENABLED=0 is the switch that works: step 80 re-enables
# every repository timer each cycle, so `systemctl disable` is undone in two
# minutes.
#
# FAILURE POLICY: every path exits 0; the cycle gates whatever the lane did not.

set -u
SELF="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$SELF/../steps/doors.sh"
REPO="${COMMIT_GATE_REPO:-$HARNESS_ROOT/repo}"
harness_load_config "$REPO"
export HARNESS_ROOT
STATE_DIR="${STATE_DIR:-/var/lib/harness}"
GATE_VERDICT_DIR="${GATE_VERDICT_DIR:-$STATE_DIR/gate-verdicts}"
COMMIT_GATE_ROOT="${COMMIT_GATE_ROOT:-$HARNESS_ROOT/commit-gate}"
COMMIT_GATE_DISPATCH_ENABLED="${COMMIT_GATE_DISPATCH_ENABLED:-1}"
COMMIT_GATE_ATTEMPT_MAX="${COMMIT_GATE_ATTEMPT_MAX:-5}"
COMMIT_GATE_MAX_PASSES="${COMMIT_GATE_MAX_PASSES:-20}"
COMMIT_GATE_DISPATCH_DEADLINE="${COMMIT_GATE_DISPATCH_DEADLINE:-1800}"
COMMIT_GATE_ORPHAN_MIN_AGE_MIN="${COMMIT_GATE_ORPHAN_MIN_AGE_MIN:-90}"
COMMIT_GATE_EVIDENCE_KEEP_DAYS="${COMMIT_GATE_EVIDENCE_KEEP_DAYS:-30}"
COMMIT_GATE_FETCH="${COMMIT_GATE_FETCH:-0}"
ATTEMPT_DIR="$COMMIT_GATE_ROOT/attempts"
SKIP_FILE="$COMMIT_GATE_ROOT/.dispatch-skip"
TAKEN_FILE="$COMMIT_GATE_ROOT/.dispatch-taken"
OUTCOME_FILE="$COMMIT_GATE_ROOT/.dispatch-outcome"
PAGED_DIR="$COMMIT_GATE_ROOT/paged"
LOG="${COMMIT_GATE_LOG:-/var/log/harness/commit-gate.log}"
{ : >> "$LOG"; } 2>/dev/null || LOG="/tmp/harness-commit-gate.log"
DISPATCH_SNAPSHOT=""
DRAWER="$SELF"
log() { printf '[%s] [commit-gate dispatch] %s\n' "$(date -Iseconds)" "$*" | tee -a "$LOG" >&2; }

# Only where no deploy cycle runs beside the lane: there the webhook and step
# 15 move the clone, and here nothing else would.
_dispatch_fetch() {
    [ "$COMMIT_GATE_FETCH" = "1" ] || return 0
    git -C "$REPO" fetch --quiet origin main 2>/dev/null \
        && git -C "$REPO" merge --ff-only --quiet origin/main 2>/dev/null \
        || log "could not move $REPO to origin/main; this pass reads what it had"
    return 0
}

_dispatch_snapshot() {
    local made
    if made="$(mktemp -d -t harness-commit-gate-XXXXXX 2>/dev/null)" \
        && cp -R "$SELF" "$made/" 2>/dev/null \
        && mkdir -p "$made/steps" 2>/dev/null \
        && cp "$SELF/../steps/doors.sh" "$SELF/../steps/eject_body.sh" \
              "$SELF/../steps/build_verdict.sh" "$made/steps/" 2>/dev/null; then
        DISPATCH_SNAPSHOT="$made"
        DRAWER="$made/$(basename "$SELF")"
        return 0
    fi
    rm -rf "${made:-/nonexistent}" 2>/dev/null || true
    log "no snapshot; running the lane from $SELF"
    return 0
}

_dispatch_cleanup() {
    case "$DISPATCH_SNAPSHOT" in */harness-commit-gate-*) rm -rf "$DISPATCH_SNAPSHOT" 2>/dev/null ;; esac
    return 0
}

# A tree older than any live run can be is a leak from a killed one. Selective,
# never `rm -rf "$ROOT"/*`: several runs may be live, and a hand run takes no
# lock at all.
_dispatch_sweep() {
    local entry name store
    for entry in "$COMMIT_GATE_ROOT"/*; do
        [ -d "$entry" ] || continue
        name="${entry##*/}"
        name="${name#venv-}"
        [ "${#name}" -eq 40 ] || continue
        case "$name" in *[!0-9a-f]*) continue ;; esac
        [ -e "$COMMIT_GATE_ROOT/.keep-$name" ] && continue
        [ -n "$(find "$entry" -maxdepth 0 -mmin "+$COMMIT_GATE_ORPHAN_MIN_AGE_MIN" 2>/dev/null)" ] || continue
        rm -rf "$entry" 2>/dev/null || true
    done
    for store in "$STATE_DIR/gate-sync-tails" "$ATTEMPT_DIR" "$PAGED_DIR"; do
        [ -d "$store" ] && find "$store" -maxdepth 1 -type f -mtime "+$COMMIT_GATE_EVIDENCE_KEEP_DAYS" -delete 2>/dev/null
    done
    return 0
}

_dispatch_has_verdict() {
    local sha="$1" r_sha="" r_verdict="" r_scope="" r_at="" r_reason="" r_tree=""
    [ -r "$GATE_VERDICT_DIR/$sha" ] || return 1
    read -r r_sha r_verdict r_scope r_at r_reason r_tree < "$GATE_VERDICT_DIR/$sha"
    : "$r_verdict$r_scope$r_at$r_reason"
    [ "$r_sha" = "$sha" ] && [ -n "$r_tree" ] \
        && [ "$r_tree" = "$(git -C "$REPO" rev-parse "${sha}^{tree}" 2>/dev/null)" ]
}

_dispatch_attempt_was_spent() {
    local line
    line="$(grep -m1 -- "^$1 " "$OUTCOME_FILE" 2>/dev/null || true)"
    case "${line#* }" in refused|3|79) return 1 ;; esac
    return 0
}

_dispatch_attempts() {
    local count=0
    [ -r "$ATTEMPT_DIR/$1" ] && read -r count < "$ATTEMPT_DIR/$1" 2>/dev/null
    case "$count" in "" | *[!0-9]*) count=0 ;; esac
    printf '%s' "$count"
}

_dispatch_page_once() {
    local sha="$1" count="$2"
    mkdir -p "$PAGED_DIR" 2>/dev/null
    [ -e "$PAGED_DIR/$sha" ] && return 0
    : > "$PAGED_DIR/$sha" 2>/dev/null || true
    fire_alert "commit gate: a commit cannot get a verdict" \
        "${sha:0:12} was taken on $count times and left no verdict, so it is parked. Every attempt was amber or an exit code pytest does not decide from the tree alone (a failed uv sync, a collection error, a timeout). The deploy cycle still gates this commit itself, so nothing ships unverified. Read journalctl -u harness-commit-gate and $STATE_DIR/gate-sync-tails/$sha. To offer it again: rm $ATTEMPT_DIR/$sha" \
        --wakes-somebody
}

_dispatch_record_attempt() {
    local sha="$1" count
    count=$(( $(_dispatch_attempts "$sha") + 1 ))
    mkdir -p "$ATTEMPT_DIR" 2>/dev/null
    printf '%s\n' "$count" > "$ATTEMPT_DIR/$sha" 2>/dev/null || true
    [ "$count" -ge "$COMMIT_GATE_ATTEMPT_MAX" ] && _dispatch_page_once "$sha" "$count"
    return 0
}

_dispatch_park_the_capped() {
    local file sha
    [ -d "$ATTEMPT_DIR" ] || return 0
    for file in "$ATTEMPT_DIR"/*; do
        [ -f "$file" ] || continue
        sha="${file##*/}"
        [ "$(_dispatch_attempts "$sha")" -ge "$COMMIT_GATE_ATTEMPT_MAX" ] || continue
        if _dispatch_has_verdict "$sha"; then
            rm -f "$file"
            continue
        fi
        printf '%s\n' "$sha" >> "$SKIP_FILE" 2>/dev/null || true
    done
    return 0
}

_dispatch_drain() {
    local pass=0 taken sha deadline
    deadline=$(( $(date +%s) + COMMIT_GATE_DISPATCH_DEADLINE ))
    : > "$SKIP_FILE" 2>/dev/null || true
    _dispatch_park_the_capped
    while [ "$pass" -lt "$COMMIT_GATE_MAX_PASSES" ]; do
        [ "$(date +%s)" -lt "$deadline" ] || { log "out of time after $pass pass(es)"; return 0; }
        pass=$(( pass + 1 ))
        : > "$TAKEN_FILE" 2>/dev/null || true
        : > "$OUTCOME_FILE" 2>/dev/null || true
        COMMIT_GATE_TAKEN_FILE="$TAKEN_FILE" COMMIT_GATE_SKIP_FILE="$SKIP_FILE" \
            COMMIT_GATE_OUTCOME_FILE="$OUTCOME_FILE" \
            COMMIT_GATE_REPO="$REPO" STATE_DIR="$STATE_DIR" COMMIT_GATE_ROOT="$COMMIT_GATE_ROOT" \
            bash "$DRAWER/verify_ahead.sh" 7>&- || true
        taken=0
        while IFS= read -r sha; do
            [ -n "$sha" ] || continue
            taken=$(( taken + 1 ))
            printf '%s\n' "$sha" >> "$SKIP_FILE" 2>/dev/null || true
            if _dispatch_has_verdict "$sha"; then
                rm -f "$ATTEMPT_DIR/$sha" 2>/dev/null
            elif _dispatch_attempt_was_spent "$sha"; then
                _dispatch_record_attempt "$sha"
            fi
        done < "$TAKEN_FILE"
        [ "$taken" -gt 0 ] || return 0
        log "pass $pass took $taken commit(s) on"
    done
    return 0
}

main() {
    if [ "$COMMIT_GATE_DISPATCH_ENABLED" != "1" ]; then
        log "COMMIT_GATE_DISPATCH_ENABLED=$COMMIT_GATE_DISPATCH_ENABLED; the deploy cycle gates every commit itself"
        return 0
    fi
    mkdir -p "$COMMIT_GATE_ROOT" 2>/dev/null || { log "cannot make $COMMIT_GATE_ROOT"; return 0; }
    # Its own lock and its own fd (7); never verify_ahead.sh's (8) or the cycle's (9).
    exec 7>"$COMMIT_GATE_ROOT/.dispatch.lock" || return 0
    flock -n 7 || { log "a drain is still running; leaving this tick to it"; return 0; }
    trap _dispatch_cleanup EXIT
    _dispatch_fetch
    _dispatch_sweep
    _dispatch_snapshot
    _dispatch_drain
    return 0
}

main "$@"
exit 0
