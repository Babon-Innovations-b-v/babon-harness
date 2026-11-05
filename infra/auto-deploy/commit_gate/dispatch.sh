#!/bin/bash
# The verifying lane's drain, run by cluster_lane.sh in the pod of CronJob
# commit-gate (infra/k8s/deploy/commit-gate.yaml), every two minutes and at
# once on every push (the receiver starts a Job from the CronJob).
#
# It owns four things and nothing else: a snapshot of this drawer (so a push
# landing mid-run cannot hand one pass half of one commit's scripts and half of
# another's), the sweep of trees left by killed runs, the per-commit attempt
# cap, and the drain: passes of verify_ahead.sh until a pass takes nothing on.
# With COMMIT_GATE_FETCH=1 (the CronJob sets it) the clone moves to origin/main
# between looks, so a commit pushed while the lane runs is seen. Up to
# COMMIT_GATE_PASSES passes run side by side: a commit pushed while a pass runs
# gets a pass of its own at once instead of waiting for that pass to end, and
# with COMMIT_GATE_IDLE_SECONDS the drain keeps looking that long once the
# queue is empty, so a push in that time costs no new lane pod.
#
# THE ATTEMPT CAP counts ANSWERS, not offers. A commit taken on
# COMMIT_GATE_ATTEMPT_MAX times without ever getting a verdict (every run amber,
# or rc 2 to 5) is parked, never offered again, and alerts once. Refusals no
# retry can change (3 scope none, 79 another ignore list, no room) are not
# counted. The deploy cycle still gates a parked commit itself.
#
# The switch is the CronJob's `suspend`; COMMIT_GATE_DISPATCH_ENABLED=0 makes a
# run that does start do nothing.
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
# Passes in flight at once. 1 is one pass after another. A pass takes only the
# commits no pass in flight has taken, so two passes never run one commit.
COMMIT_GATE_PASSES="${COMMIT_GATE_PASSES:-1}"
# Seconds between looks at the branch while passes run or the drain waits for a
# commit. A pass that ends wakes the drain at once.
COMMIT_GATE_POLL_SECONDS="${COMMIT_GATE_POLL_SECONDS:-5}"
# How long an idle drain keeps looking for a new commit before it ends. 0 ends
# at the first idle look. The deadline still ends a busy one.
COMMIT_GATE_IDLE_SECONDS="${COMMIT_GATE_IDLE_SECONDS:-0}"
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

# The lane's clone is its own, on its own volume: nothing else moves it.
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
        && cp "$SELF/../steps/doors.sh" "$SELF/../steps/eject_body.sh" "$SELF/../steps/red_triage.sh" \
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

# What a pass reported for one sha: the run's exit code, `refused`, or nothing
# when run_many.sh never got that far.
_dispatch_outcome() {
    local sha="$1" file="${2:-$OUTCOME_FILE}" line=""
    [ -r "$file" ] || return 0
    line="$(grep -m1 -- "^$sha " "$file" 2>/dev/null || true)"
    [ -n "$line" ] && printf '%s' "${line#* }"
    return 0
}

_dispatch_attempt_was_spent() {
    case "$(_dispatch_outcome "$1" "${2:-$OUTCOME_FILE}")" in refused|3|79) return 1 ;; esac
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
        "${sha:0:12} was taken on $count times and left no verdict, so it is parked. Every attempt was amber or an exit code pytest does not decide from the tree alone (a gate Job that could not start, a collection error, a timeout). The deploy cycle still gates this commit itself, so nothing ships unverified. Read the lane's log (kubectl -n ${DEPLOY_NAMESPACE:-deploy} logs -l app.kubernetes.io/name=commit-gate). To offer it again: rm $ATTEMPT_DIR/$sha in the lane's volume" \
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

# ── One pass ────────────────────────────────────────────────────────────────
#
# `7>&-` closes this script's lock for the child. `flock` is held by an open file
# description, which children inherit, so a run that somehow outlived its parent
# would keep the dispatcher locked out for as long as it lived.
#
# The lock a pass runs under is `verify_ahead.sh`'s own default only in slot 0.
# That lock is on a fixed path on fd 8, non-blocking, and locks are per open
# file description: a second pass re-opening the same path while the first
# held it would be refused, exit 0, and take nothing on. So every other pass
# slot names a lock of its own (`COMMIT_GATE_DRIVER_LOCK`). A concurrent HAND
# run of `verify_ahead.sh` meets slot 0's, and there the reading is right: the
# queue has another driver, so leaving it alone is correct.
#
# Every pass has its own taken and outcome files, `<file>-<pass>`, so passes in
# flight side by side never read each other's answers.
PASS_PIDS=()
PASS_NUMBERS=()
PASS_SLOTS=()

_dispatch_free_slot() {
    local slot used held
    for (( slot = 0; slot < COMMIT_GATE_PASSES; slot++ )); do
        used=0
        for held in ${PASS_SLOTS[@]+"${PASS_SLOTS[@]}"}; do
            [ "$held" = "$slot" ] && used=1
        done
        if [ "$used" -eq 0 ]; then
            printf '%s' "$slot"
            return 0
        fi
    done
    return 1
}

# Start pass <number> in <slot> and return once it has decided what it takes:
# its taken file is filled, or it ended having taken nothing. What it took goes
# into the skip list before this returns, so the next pass cannot take it too.
_dispatch_start_pass() {
    local number="$1" slot="$2" lock pid sha
    local taken="$TAKEN_FILE-$number" outcome="$OUTCOME_FILE-$number"
    : 2>/dev/null > "$taken" || true
    : 2>/dev/null > "$outcome" || true
    lock="$COMMIT_GATE_ROOT/.verify-ahead.lock"
    [ "$slot" -gt 0 ] && lock="$COMMIT_GATE_ROOT/.verify-ahead-$slot.lock"
    COMMIT_GATE_TAKEN_FILE="$taken" COMMIT_GATE_SKIP_FILE="$SKIP_FILE" \
        COMMIT_GATE_OUTCOME_FILE="$outcome" COMMIT_GATE_DRIVER_LOCK="$lock" \
        COMMIT_GATE_REPO="$REPO" STATE_DIR="$STATE_DIR" COMMIT_GATE_ROOT="$COMMIT_GATE_ROOT" \
        bash "$DRAWER/verify_ahead.sh" 7>&- &
    pid=$!
    until [ -s "$taken" ] || ! kill -0 "$pid" 2>/dev/null; do
        sleep 0.2
    done
    if [ -r "$taken" ]; then
        while IFS= read -r sha; do
            [ -n "$sha" ] && printf '%s\n' "$sha" 2>/dev/null >> "$SKIP_FILE"
        done < "$taken"
    fi
    PASS_PIDS+=("$pid")
    PASS_NUMBERS+=("$number")
    PASS_SLOTS+=("$slot")
    return 0
}

# Take a commit out of the skip list, so a later pass of this invocation may
# take it on again.
_dispatch_unskip() {
    local sha="$1" kept
    kept="$(grep -vxF -- "$sha" "$SKIP_FILE" 2>/dev/null || true)"
    printf '%s\n' "$kept" 2>/dev/null > "$SKIP_FILE.tmp" \
        && mv -f "$SKIP_FILE.tmp" "$SKIP_FILE" 2>/dev/null
    return 0
}

# What one finished pass <number> did to each commit it took. The counter is
# the only thing that can park a commit for ever, so it is asked twice before
# it moves: did this commit end up with a verdict, and did this pass actually
# spend an attempt on it. Both questions have a false-page behind them.
#
# ONE MORE ANSWER, for a batch that found its red (`batch.sh`): the commits
# after the red one were taken but never run, so they spend no attempt and
# leave the skip list, and the next pass of this invocation batches what is
# behind the revert. Every such pass writes down a red the skip list keeps, so
# this cannot go round for ever. Sets DISPATCH_PASS_TOOK to the commits taken.
DISPATCH_PASS_TOOK=0
_dispatch_account() {
    local number="$1" sha found_red=0
    local taken="$TAKEN_FILE-$number" outcome="$OUTCOME_FILE-$number"
    DISPATCH_PASS_TOOK=0
    [ -r "$taken" ] || return 0
    grep -q ' 1$' "$outcome" 2>/dev/null && found_red=1
    while IFS= read -r sha; do
        [ -n "$sha" ] || continue
        DISPATCH_PASS_TOOK=$(( DISPATCH_PASS_TOOK + 1 ))
        if _dispatch_has_verdict "$sha"; then
            rm -f "$ATTEMPT_DIR/$sha" 2>/dev/null
        elif [ "$found_red" -eq 1 ] && [ -z "$(_dispatch_outcome "$sha" "$outcome")" ]; then
            _dispatch_unskip "$sha"
        elif _dispatch_attempt_was_spent "$sha" "$outcome"; then
            _dispatch_record_attempt "$sha"
        fi
    done < "$taken"
    return 0
}

# Collect every pass that has ended. Sets DISPATCH_PROGRESS to 1 when one of
# them took a commit on, which is what earns the next pass a look.
DISPATCH_PROGRESS=0
_dispatch_reap() {
    local index pids=() numbers=() slots=()
    for index in "${!PASS_PIDS[@]}"; do
        if kill -0 "${PASS_PIDS[$index]}" 2>/dev/null; then
            pids+=("${PASS_PIDS[$index]}")
            numbers+=("${PASS_NUMBERS[$index]}")
            slots+=("${PASS_SLOTS[$index]}")
            continue
        fi
        wait "${PASS_PIDS[$index]}" 2>/dev/null
        _dispatch_account "${PASS_NUMBERS[$index]}"
        if [ "$DISPATCH_PASS_TOOK" -gt 0 ]; then
            DISPATCH_PROGRESS=1
            log "pass ${PASS_NUMBERS[$index]} took $DISPATCH_PASS_TOOK commit(s) on"
        fi
        rm -f "$TAKEN_FILE-${PASS_NUMBERS[$index]}" "$OUTCOME_FILE-${PASS_NUMBERS[$index]}" 2>/dev/null
    done
    PASS_PIDS=(${pids[@]+"${pids[@]}"})
    PASS_NUMBERS=(${numbers[@]+"${numbers[@]}"})
    PASS_SLOTS=(${slots[@]+"${slots[@]}"})
    return 0
}

# Sleep up to the poll interval, waking at once when a pass ends.
_dispatch_nap() {
    local sleeper
    sleep "$COMMIT_GATE_POLL_SECONDS" &
    sleeper=$!
    wait -n "$sleeper" ${PASS_PIDS[@]+"${PASS_PIDS[@]}"} 2>/dev/null
    kill "$sleeper" 2>/dev/null
    wait "$sleeper" 2>/dev/null
    return 0
}

_dispatch_head() {
    git -C "$REPO" rev-parse --verify --quiet "${COMMIT_GATE_BRANCH:-origin/main}^{commit}" 2>/dev/null
    return 0
}

# What this lane runs on that main can move under a long drain: the gate image
# the branch pins and the scripts the snapshot copied. Printed as one string,
# compared with the one at the start.
_dispatch_ground() {
    local branch="${COMMIT_GATE_BRANCH:-origin/main}" path
    git -C "$REPO" show "$branch:infra/gate-image/pin" 2>/dev/null \
        | grep -v '^#' | sed '/^[[:space:]]*$/d' | tail -n 1 | tr -d '[:space:]'
    for path in infra/auto-deploy/commit_gate infra/auto-deploy/steps/doors.sh \
            infra/auto-deploy/steps/eject_body.sh \
            infra/auto-deploy/steps/build_verdict.sh \
            infra/auto-deploy/steps/red_triage.sh; do
        printf ' %s' "$(git -C "$REPO" rev-parse --verify --quiet "$branch:$path" 2>/dev/null)"
    done
    return 0
}

# ── The drain ───────────────────────────────────────────────────────────────
#
# A new pass starts when a pass slot is free and something may have changed
# since the last look: the branch moved, or a pass that took commits ended. A
# commit is offered at most once per invocation (it is in the skip list from
# the moment a pass takes it, whatever comes back, bar the batch rule above),
# the queue is finite, and the deadline and the pass ceiling stop new passes,
# so the drain ends. It ends early when no pass is in flight, the last look
# took nothing, and the branch stood still for `COMMIT_GATE_IDLE_SECONDS`.
# It also starts no new pass once main moved its ground (`_dispatch_ground`):
# the lane's code is read once per lane Job and its image is the pod's, so the
# next lane Job, on main's image and code, takes over.
_dispatch_drain() {
    local pass=0 deadline now slot head looked="" idle_since="" ground moved=0
    deadline=$(( $(date +%s) + COMMIT_GATE_DISPATCH_DEADLINE ))
    ground="$(_dispatch_ground)"
    : 2>/dev/null > "$SKIP_FILE" || true
    _dispatch_park_the_capped
    DISPATCH_PROGRESS=1

    while :; do
        _dispatch_reap
        now="$(date +%s)"
        head="$(_dispatch_head)"
        [ "$moved" -eq 0 ] && [ "$head" != "$looked" ] && [ "$(_dispatch_ground)" != "$ground" ] && moved=1
        if [ "$now" -ge "$deadline" ] || [ "$pass" -ge "$COMMIT_GATE_MAX_PASSES" ] || [ "$moved" -eq 1 ]; then
            if [ "${#PASS_PIDS[@]}" -eq 0 ]; then
                if [ "$moved" -eq 1 ]; then
                    log "main changed the lane's scripts or its gate image; the next lane Job runs them"
                elif [ "$pass" -ge "$COMMIT_GATE_MAX_PASSES" ]; then
                    log "stopped at the $COMMIT_GATE_MAX_PASSES pass ceiling; the next tick continues"
                else
                    log "out of time after $pass pass(es); the next tick picks up the rest"
                fi
                return 0
            fi
        elif { [ "$DISPATCH_PROGRESS" -eq 1 ] || [ "$head" != "$looked" ]; } \
                && slot="$(_dispatch_free_slot)"; then
            pass=$(( pass + 1 ))
            DISPATCH_PROGRESS=0
            looked="$head"
            _dispatch_start_pass "$pass" "$slot"
            [ -s "$TAKEN_FILE-$pass" ] && idle_since=""
            continue
        fi
        if [ "${#PASS_PIDS[@]}" -eq 0 ] && [ "$DISPATCH_PROGRESS" -eq 0 ] && [ "$head" = "$looked" ]; then
            [ -n "$idle_since" ] || idle_since="$now"
            if [ $(( now - idle_since )) -ge "$COMMIT_GATE_IDLE_SECONDS" ]; then
                # Five different states reach this line and only one of them
                # is a drained queue: the pass may also have found another
                # driver on the lock, no bookmark, a bookmark that is not an
                # ancestor of the branch, or nothing left after the commit the
                # cycle is on is dropped. Each says which above, so this line
                # does not claim.
                log "pass $pass took no commit on; whatever the reason, this tick is done"
                return 0
            fi
        fi
        _dispatch_nap
        _dispatch_fetch
    done
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
