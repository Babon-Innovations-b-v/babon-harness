#!/bin/bash
# Verify ONE commit in a world of its own: its own exported tree, its own scope,
# its own suite as gate Jobs, its own images, its own verdict.
#
#   commit_gate/run_one.sh <sha>
#   COMMIT_GATE_BATCH_BASE=<base> commit_gate/run_one.sh <sha>   (batch.sh)
#
# The verifying lane (CronJob commit-gate, cluster_lane.sh) runs this ahead of
# the deploy cycle for every commit queued past the bookmark, so when the cycle
# reaches a commit its verdict is usually already written. It shares nothing
# with the cycle but main's clone (read-only): no lock, no working tree, no
# scope file, no volume. The suite runs where the cycle's does: gate Jobs, one
# per module group, in the image the commit's own infra/gate-image/pin names
# (`python3 -m infra.deploy_loop gate-run`), with the break replay of every
# register row the commit touches in the first Job.
#
# EXIT CODES, the deploy gate's table: 0 green; 1 to 5 red; anything else amber.
# This script's own refusals are amber: 65 not a commit, 70 export failed, 72 an
# image the builder could not build, 75 nothing to run the suite with (no repo
# URL or cycle image, or a triage that could not run its comparisons), 76 no
# ignore list, 77 empty selection, 79 this commit's ignore list is not the
# clone's. `scope none` is not green: exit 3, no verdict, and the nightly
# unselected audit is the cover.
#
# ONLY rc 0 AND rc 1 ARE WRITTEN DOWN, because only those are a function of the
# tree alone. A verdict is never REPLACED when it was written after this run
# started, or when a green for this exact tree is already there: that green is
# what the cycle shipped on.
#
# A RED IS SORTED BEFORE IT IS WRITTEN (../steps/red_triage.sh, the cycle's own
# rule): a test that flips, or fails on the bookmark too, is quarantined and the
# suite runs again without it; a red that is the commit's is written and handed
# to eject.sh at once. A green whose break replay also passed is written with
# the word `replayed`, the only green `deploy_loop trusted-head` accepts.
#
# A BATCH (COMMIT_GATE_BATCH_BASE): the whole range base..sha is verified once
# on sha's tree. A green also writes `green <scope> <at> batch:<sha12> <tree>`
# for every commit under sha; a red writes, posts and ejects nothing, and
# batch.sh splits the range.
#
# Statuses: vm/gate from the SUITE's rc, vm/build from the build, so a broken
# image is never reported as a broken test. Nothing pending is ever posted, and
# amber posts nothing.

set -u
SELF="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$SELF/../steps/doors.sh"
REPO="${COMMIT_GATE_REPO:-$HARNESS_ROOT/repo}"
harness_load_config "$REPO"
STATE_DIR="${STATE_DIR:-/var/lib/harness}"
GATE_VERDICT_DIR="${GATE_VERDICT_DIR:-$STATE_DIR/gate-verdicts}"
COMMIT_GATE_ROOT="${COMMIT_GATE_ROOT:-$HARNESS_ROOT/commit-gate}"
COMMIT_GATE_TIMEOUT="${COMMIT_GATE_TIMEOUT:-1200}"
COMMIT_GATE_SETUP_SECONDS="${COMMIT_GATE_SETUP_SECONDS:-900}"
COMMIT_GATE_SHARD_JOBS="${COMMIT_GATE_SHARD_JOBS:-64}"
COMMIT_GATE_TRIAGE_ROUNDS="${COMMIT_GATE_TRIAGE_ROUNDS:-6}"
COMMIT_GATE_KEEP="${COMMIT_GATE_KEEP:-0}"
COMMIT_GATE_BUILD_ENABLED="${COMMIT_GATE_BUILD_ENABLED:-1}"
COMMIT_GATE_STATUS="${COMMIT_GATE_STATUS:-1}"
COMMIT_GATE_BATCH_BASE="${COMMIT_GATE_BATCH_BASE:-}"
GH_REPO_SLUG="${GH_REPO_SLUG:-$(harness_repo_slug "$REPO")}"
LOG="${COMMIT_GATE_LOG:-/var/log/harness/commit-gate.log}"
{ : >> "$LOG"; } 2>/dev/null || LOG="/tmp/harness-commit-gate.log"
RUN_STARTED="$(date +%s)"
CG_STATUS_ARMED=0
log() { printf '[%s] [commit-gate %s] %s\n' "$(date -Iseconds)" "${SHA:0:12}" "$*" | tee -a "$LOG" >&2; }

_cg_post_status() {
    [ "$COMMIT_GATE_STATUS" = "1" ] || return 0
    gh_post_status "${4:-${SHA:-}}" "${3:-vm/gate}" "$1" "$2" ""
    return 0
}

# Posted from the EXIT trap, so a killed run still says what it knows. A batch
# that went red says nothing: its red names no commit.
_cg_resolve_status() {
    local suite_rc="${SUITE_RC:-$1}"
    [ "$CG_STATUS_ARMED" = "1" ] || return 0
    CG_STATUS_ARMED=0
    case "$suite_rc" in
        0) _cg_post_status "success" "green ($SCOPE scope), verified ahead of the cycle" ;;
        1|2|3|4|5)
            if [ -n "$COMMIT_GATE_BATCH_BASE" ]; then
                log "the batch is red; no status posted, batch.sh splits it"
            else
                _cg_post_status "failure" "red (pytest rc=$suite_rc, $SCOPE scope), verified ahead of the cycle"
            fi ;;
        *) log "no vm/gate posted (rc=$suite_rc): this run could not finish, so the cycle gates this commit itself" ;;
    esac
    case "${BUILD_STATE:-not-run}" in
        green) _cg_post_status "success" "images built from this commit's own tree" "vm/build" ;;
        red)   _cg_post_status "failure" "an image could not be built from this commit" "vm/build" ;;
    esac
    return 0
}

SHA="${1:-}"
[ -n "$SHA" ] || { printf 'usage: run_one.sh <sha>\n' >&2; exit 64; }
if ! SHA="$(git -C "$REPO" rev-parse --verify --quiet "${SHA}^{commit}")"; then
    log "not a commit in $REPO"
    exit 65
fi
TREE_HASH="$(git -C "$REPO" rev-parse "${SHA}^{tree}" 2>/dev/null || echo "")"
[ -n "$TREE_HASH" ] || { log "cannot resolve the tree"; exit 65; }
BOOKMARK="$(cat "$STATE_DIR/last-deployed-sha" 2>/dev/null || echo "")"

# The cycle runs the suite its CLONE's 40-gate.sh names; a verdict from here is
# only about that suite if this commit's step names the same ignore list.
GATE_STEP_PATH="infra/auto-deploy/steps/40-gate.sh"
_cg_ignore_flags() {
    grep -oE -- '--ignore=[^[:space:]]+' | LC_ALL=C sort
}
TREE_IGNORES="$(git -C "$REPO" show "$SHA:$GATE_STEP_PATH" 2>/dev/null | _cg_ignore_flags)"
CLONE_IGNORES="$(_cg_ignore_flags < "$REPO/$GATE_STEP_PATH" 2>/dev/null)"
if [ -z "$TREE_IGNORES" ] || [ -z "$CLONE_IGNORES" ]; then
    log "could not read the gate's ignore list from both this commit and the clone"
    exit 79
fi
if [ "$TREE_IGNORES" != "$CLONE_IGNORES" ]; then
    log "this commit's 40-gate.sh names a different ignore list than the clone's; leaving it to the cycle"
    exit 79
fi

WORK="$COMMIT_GATE_ROOT/$SHA"
cleanup() {
    local rc=$?
    _cg_resolve_status "$rc"
    if [ "$COMMIT_GATE_KEEP" != "1" ]; then
        case "$WORK" in "$COMMIT_GATE_ROOT"/*) rm -rf "$WORK" 2>/dev/null ;; esac
    fi
    return 0
}
# One EXIT trap; TERM and INT route into it with a non-zero code, or a killed
# shell would read $? as 0 there and post success.
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

_cg_record_gate_run() {
    mkdir -p "$STATE_DIR/gate-runs" 2>/dev/null || return 0
    python3 - "$STATE_DIR/gate-runs/$SHA.json" "$SHA" "$SCOPE" "$RC" "$PATHS_FILE" <<'PYEOF' 2>>"$LOG" || true
import json, pathlib, sys, time
out, sha, scope, rc, paths_file = sys.argv[1:6]
try:
    paths = [line for line in pathlib.Path(paths_file).read_text().splitlines() if line]
except OSError:
    paths = []
staged = pathlib.Path(out + ".tmp")
staged.write_text(json.dumps({"sha": sha, "scope": scope, "paths": paths, "rc": int(rc), "ts": int(time.time())}))
staged.replace(pathlib.Path(out))
PYEOF
}

mkdir -p "$WORK" 2>/dev/null || { log "cannot make $WORK"; exit 70; }
[ "$COMMIT_GATE_KEEP" = "1" ] && : > "$COMMIT_GATE_ROOT/.keep-$SHA" 2>/dev/null
if ! ( git -C "$REPO" archive --format=tar "$SHA" | tar -x -C "$WORK" ) 2>/dev/null; then
    log "export failed"
    exit 70
fi
OBJECTS="$( cd "$REPO" && cd "$(git rev-parse --git-common-dir 2>/dev/null)" && pwd )/objects"
if ! ( git -C "$WORK" init -q \
        && printf '%s\n' "$OBJECTS" > "$WORK/.git/objects/info/alternates" \
        && git -C "$WORK" update-ref HEAD "$SHA" \
        && git -C "$WORK" read-tree HEAD ) 2>/dev/null; then
    log "could not make the tree a git repository"
    exit 70
fi

# The scope is asked of the TREE: the selector this commit ships, about the
# diff this commit is (a batch: the whole range's).
CHANGED_FILE="$WORK/.commit-gate-changed"
DIFF_BASE="${COMMIT_GATE_BATCH_BASE:-${SHA}^}"
git -C "$REPO" -c core.quotePath=false diff --name-only --no-renames "$DIFF_BASE" "$SHA" > "$CHANGED_FILE" 2>/dev/null \
    || git -C "$REPO" ls-tree -r --name-only "$SHA" > "$CHANGED_FILE" 2>/dev/null || true
SCOPE="full"
PATHS_FILE="$WORK/.commit-gate-paths"
: > "$PATHS_FILE"
if scope_word="$( cd "$WORK" && python3 -m tools.gate_scope --changed-file "$CHANGED_FILE" --repo "$WORK" \
        --out-paths "$PATHS_FILE" --out-json "$WORK/.commit-gate-scope.json" 2>/dev/null )"; then
    case "$scope_word" in none | selected | full) SCOPE="$scope_word" ;; esac
fi
SELECTED=$(wc -l < "$PATHS_FILE" 2>/dev/null | tr -d ' ')
log "scope $SCOPE, ${SELECTED:-0} selected path(s)${COMMIT_GATE_BATCH_BASE:+, a batch since ${COMMIT_GATE_BATCH_BASE:0:12}}"
if [ "$SCOPE" = "none" ]; then
    log "no test can reach anything this commit touched"
    exit 3
fi
if [ -z "${DEPLOY_REPO_URL:-}" ] || [ -z "${DEPLOY_CYCLE_IMAGE:-}" ]; then
    log "DEPLOY_REPO_URL or DEPLOY_CYCLE_IMAGE is empty, so no gate Job can be made"
    exit 75
fi

IGNORE_ARGS=()
while IFS= read -r flag; do
    [ -n "$flag" ] && IGNORE_ARGS+=("$flag")
done < <(grep -oE -- '--ignore=[^[:space:]]+' "$WORK/$GATE_STEP_PATH" 2>/dev/null)
if [ "${#IGNORE_ARGS[@]}" -eq 0 ]; then
    log "no --ignore flags in this tree's 40-gate.sh; refusing to run a suite that is not the gate's"
    exit 76
fi
SELECTED_ARGS=()
if [ "$SCOPE" = "selected" ]; then
    while IFS= read -r path; do
        [ -n "$path" ] && [ -e "$WORK/$path" ] && SELECTED_ARGS+=("$path")
    done < "$PATHS_FILE"
    [ "${#SELECTED_ARGS[@]}" -gt 0 ] || { log "the selection names nothing this tree contains"; exit 77; }
fi

# The wrong-commit / wrong-test sorter and main's quarantine (not a step).
CG_TRIAGE_LOADED=1
# shellcheck disable=SC1091
if ! . "$SELF/../steps/red_triage.sh" 2>/dev/null; then
    CG_TRIAGE_LOADED=0
    log "steps/red_triage.sh did not load, so every red here is the commit's"
    _quarantine_list() { return 0; }
fi

# Quarantined tests leave the run: as `--ignore <path>`, two arguments, so the
# ignore-list comparison above never sees them.
QUARANTINE_ARGS=()
_cg_leave_out() {
    local test="$1" kept=() path
    QUARANTINE_ARGS+=(--ignore "$test")
    for path in ${SELECTED_ARGS[@]+"${SELECTED_ARGS[@]}"}; do
        [ "$path" = "$test" ] || kept+=("$path")
    done
    SELECTED_ARGS=(${kept[@]+"${kept[@]}"})
}
while IFS= read -r quarantined_test; do
    [ -n "$quarantined_test" ] && [ -e "$WORK/$quarantined_test" ] || continue
    _cg_leave_out "$quarantined_test"
    log "$quarantined_test is quarantined, so this run leaves it out"
done < <(_quarantine_list)

# One gate Job per module group, as the cycle's step 40 splits it: the tree's
# own register, at most COMMIT_GATE_SHARD_JOBS. Sets SHARDS_FILE, empty for one
# Job, whose paths are then pytest's own arguments.
SHARDS_FILE=""
_cg_write_shards() {
    local list="$WORK/.commit-gate-shard-paths" out="$WORK/.commit-gate-shards" left_out
    SHARDS_FILE=""
    case "$COMMIT_GATE_SHARD_JOBS" in ''|*[!0-9]*|0|1) return 0 ;; esac
    [ -d "$WORK/tools/test_register" ] || return 0
    if [ "$SCOPE" = "selected" ]; then
        printf '%s\n' ${SELECTED_ARGS[@]+"${SELECTED_ARGS[@]}"} > "$list"
    else
        ( cd "$WORK" && python3 -c 'from tools.test_register import ROWS
print("\n".join(row.test for row in ROWS if row.test.endswith(".py")))' ) > "$list" 2>>"$LOG" || return 0
        if [ "${#QUARANTINE_ARGS[@]}" -gt 0 ]; then
            left_out="$(printf '%s\n' "${QUARANTINE_ARGS[@]}" | grep -vx -- '--ignore')"
            grep -vxF -- "$left_out" "$list" > "$list.kept" 2>/dev/null || : > "$list.kept"
            mv -f "$list.kept" "$list"
        fi
    fi
    [ -s "$list" ] || return 0
    ( cd "$WORK" && python3 -m tools.test_register --shards "$list" --max "$COMMIT_GATE_SHARD_JOBS" \
        --repo "$WORK" ) > "$out" 2>>"$LOG" || return 0
    [ "$(cut -f1 "$out" | LC_ALL=C sort -u | wc -l)" -gt 1 ] || return 0
    SHARDS_FILE="$out"
}

# One gate Job (or one per shard) for <sha>, in the image the pin file <pin>
# names; pytest's code, or 124/125/126/137 for a Job that could not finish.
_cg_gate_job() {
    local sha="$1" pin="$2" run_log="$3" changed="$4" replay_file="$5" shards="$6" pin_new=()
    shift 6
    [ "${1:-}" = "--" ] && shift
    if [ -n "$changed" ] && grep -qx 'infra/gate-image/pin' "$changed" 2>/dev/null; then
        pin_new=(--pin-is-new)
    fi
    (cd "$REPO" && python3 -m infra.deploy_loop gate-run \
        --sha "$sha" --repo-url "$DEPLOY_REPO_URL" --gate-pin "$pin" ${pin_new[@]+"${pin_new[@]}"} \
        --cycle-image "$DEPLOY_CYCLE_IMAGE" --pool-label "${POOL_ROLE_LABEL:-harness/role}" \
        --seconds "$COMMIT_GATE_TIMEOUT" --setup-seconds "$COMMIT_GATE_SETUP_SECONDS" \
        --changed-file "$changed" --replay-workers "${GATE_REPLAY_WORKERS:-1}" --replay-rc-file "$replay_file" \
        --cpu "${GATE_JOB_CPU:-2}" --memory "${GATE_JOB_MEMORY:-6Gi}" --shards-file "$shards" \
        --log "$run_log" -- "$@" ) 2>>"$run_log"
}

# The caller's hook for red_triage.sh: the listed test files of this commit
# (`same`) or of the bookmark (`good`), in a gate Job of their own, no replay.
_red_triage_run() {
    local which="$1" list="$2" out="$3" sha="$SHA" pin="$WORK/infra/gate-image/pin" run_log rc path files=()
    while IFS= read -r path; do
        [ -n "$path" ] && files+=("$path")
    done < "$list"
    [ "${#files[@]}" -gt 0 ] || return 125
    run_log="$(mktemp -t commit-gate-triage-XXXXXX)" || return 125
    if [ "$which" = "good" ]; then
        sha="$BOOKMARK"
        pin="$run_log.pin"
        if [ -z "$sha" ] || ! git -C "$REPO" show "$sha:infra/gate-image/pin" > "$pin" 2>/dev/null; then
            rm -f "$run_log" "$pin"
            : > "$out"
            return 125
        fi
    fi
    _cg_gate_job "$sha" "$pin" "$run_log" "" "" "" -- -q -rfE -p no:cacheprovider "${files[@]}"
    rc=$?
    _red_failing_files "$run_log" "$sha" > "$out"
    cat "$run_log" >> "$LOG" 2>/dev/null
    rm -f "$run_log" "$run_log.pin"
    return "$rc"
}

# After a red: 0 runs the suite again at once, 1 is the answer. A test's fault
# leaves the run, for as many rounds as each one leaves something new out; a red
# naming no file runs once more; a triage that could not compare is amber (75).
CG_ROUNDS=0
CG_UNNAMED=0
_cg_next_attempt() {
    local failing left_out_before line test reason
    case "$RC" in 1|2|3|4) : ;; *) return 1 ;; esac
    [ "$CG_TRIAGE_LOADED" -eq 1 ] && [ "${GATE_TRIAGE_ENABLED:-1}" = "1" ] || return 1
    [ -n "$COMMIT_GATE_BATCH_BASE" ] && return 1
    failing="$WORK/.commit-gate-failing"
    _red_failing_files "$RUN_LOG" "$SHA" > "$failing"
    if [ ! -s "$failing" ]; then
        CG_UNNAMED=$(( CG_UNNAMED + 1 ))
        [ "$CG_UNNAMED" -eq 1 ] && { log "red (rc=$RC) naming no test file: once more"; return 0; }
        return 1
    fi
    if [ "$CG_ROUNDS" -ge "$COMMIT_GATE_TRIAGE_ROUNDS" ]; then
        log "still red after $CG_ROUNDS triage rounds that each left a test's fault out; amber"
        RC=75
        return 1
    fi
    CG_ROUNDS=$(( CG_ROUNDS + 1 ))
    left_out_before="${#QUARANTINE_ARGS[@]}"
    _red_triage "$BOOKMARK" "$failing" "$SHA"
    log "triage: $red_triage_kind"
    case "$red_triage_kind" in
        test)
            for line in ${red_triage_tests[@]+"${red_triage_tests[@]}"}; do
                test="${line%%$'\t'*}"
                reason="${line#*$'\t'}"
                _red_quarantine "$test" "$reason" "$SHA" "$RUN_LOG"
                _cg_leave_out "$test"
                log "quarantined $test: it $reason${red_quarantine_issue:+ (#$red_quarantine_issue)}"
            done
            [ "${#QUARANTINE_ARGS[@]}" -gt "$left_out_before" ] || return 1
            if [ "$SCOPE" = "selected" ] && [ "${#SELECTED_ARGS[@]}" -eq 0 ]; then
                RC=0
                return 1
            fi
            return 0 ;;
        setup) RC=75; return 1 ;;
    esac
    return 1
}

# The register must agree with the tree before anything runs, as in step 40.
RC=0
REASON=""
REPLAY_RC_FILE="$WORK/.commit-gate-replay-rc"
RUN_LOG="$WORK/.commit-gate-run.log"
: > "$RUN_LOG"
CG_STATUS_ARMED=1
if [ -d "$WORK/tools/test_register" ] \
        && ! ( cd "$WORK" && python3 -m tools.test_register --check --repo "$WORK" ) >> "$RUN_LOG" 2>&1; then
    RC=1
    REASON="register"
    log "the test register and the tree disagree"
fi
while [ -z "$REASON" ]; do
    _cg_write_shards
    RUN_PATHS=(${SELECTED_ARGS[@]+"${SELECTED_ARGS[@]}"})
    [ -n "$SHARDS_FILE" ] && RUN_PATHS=()
    RUN_LOG="$WORK/.commit-gate-run-$CG_ROUNDS-$CG_UNNAMED.log"
    : > "$RUN_LOG"
    rm -f "$REPLAY_RC_FILE"
    _cg_gate_job "$SHA" "$WORK/infra/gate-image/pin" "$RUN_LOG" "$CHANGED_FILE" "$REPLAY_RC_FILE" "$SHARDS_FILE" \
        -- -q --tb=no -rfE "${IGNORE_ARGS[@]}" ${QUARANTINE_ARGS[@]+"${QUARANTINE_ARGS[@]}"} \
        ${RUN_PATHS[@]+"${RUN_PATHS[@]}"}
    RC=$?
    _cg_next_attempt || break
done
SUITE_RC=$RC

# A green suite is not yet proof: a test that passes with its own break applied
# checks nothing. Only a replay that ran clean earns `replayed`.
if [ "$RC" -eq 0 ] && [ -z "$REASON" ]; then
    replay_rc="$(cat "$REPLAY_RC_FILE" 2>/dev/null || echo "")"
    case "$replay_rc" in
        0) REASON="replayed" ;;
        1) RC=1; SUITE_RC=1; REASON="unfalsifiable_test"; log "a test passed with its own break applied" ;;
        "") REASON="none" ;;
        *) REASON="none"; log "the break replay could not finish (rc=$replay_rc); a plain green" ;;
    esac
fi

# Build only after a green suite, push nothing.
BUILD_STATE="not-run"
if [ "$RC" -eq 0 ] && [ "$COMMIT_GATE_BUILD_ENABLED" = "1" ]; then
    COMMIT_GATE_CHANGED_FILE="$CHANGED_FILE" bash "$SELF/build_images.sh" "$SHA" "$WORK"
    case "$?" in
        0) BUILD_STATE="green" ;;
        1) BUILD_STATE="red"; RC=1; REASON="build_regression" ;;
        *) BUILD_STATE="box"; RC=72 ;;
    esac
fi

# Write one verdict line for <sha>, unless the one there must stand.
_cg_write_verdict() {
    local sha="$1" verdict="$2" reason="$3" tree="$4"
    local live_sha="" live_verdict="" live_scope="" live_at="" live_reason="" live_tree=""
    [ -r "$GATE_VERDICT_DIR/$sha" ] \
        && read -r live_sha live_verdict live_scope live_at live_reason live_tree < "$GATE_VERDICT_DIR/$sha"
    : "$live_scope$live_reason"
    case "$live_at" in "" | *[!0-9]*) live_at=0 ;; esac
    if [ "$live_sha" = "$sha" ] && [ "$live_tree" = "$tree" ]; then
        if [ "$live_at" -ge "$RUN_STARTED" ]; then
            log "${sha:0:12}: the $live_verdict verdict for this tree stands: it was written after this run started"
            return 1
        elif [ "$live_verdict" = "green" ] && [ "$verdict" = "red" ]; then
            log "${sha:0:12}: the green for this exact tree stands: it is what the cycle shipped on"
            return 1
        fi
    fi
    printf '%s %s %s %s %s %s\n' "$sha" "$verdict" "$SCOPE" "$(date +%s)" "$reason" "$tree" \
        > "$GATE_VERDICT_DIR/$sha.tmp.$$" 2>/dev/null \
        && mv -f "$GATE_VERDICT_DIR/$sha.tmp.$$" "$GATE_VERDICT_DIR/$sha" 2>/dev/null \
        || { log "could not record the verdict for ${sha:0:12}"; return 1; }
    return 0
}

case "$RC" in
    0) VERDICT="green" ;;
    1) VERDICT="red"; REASON="${REASON:-regression}" ;;
    *) VERDICT="" ;;
esac
if [ -n "$COMMIT_GATE_BATCH_BASE" ] && [ "$VERDICT" = "red" ]; then
    log "the batch since ${COMMIT_GATE_BATCH_BASE:0:12} is red (rc=$RC); nothing written, batch.sh splits it"
    VERDICT=""
fi
if [ -n "$VERDICT" ]; then
    mkdir -p "$GATE_VERDICT_DIR" 2>/dev/null
    if _cg_write_verdict "$SHA" "$VERDICT" "$REASON" "$TREE_HASH"; then
        log "$VERDICT (rc=$RC, scope $SCOPE, $REASON)"
        _cg_record_gate_run
    fi
    if [ -n "$COMMIT_GATE_BATCH_BASE" ] && [ "$VERDICT" = "green" ]; then
        while read -r member member_tree; do
            [ -n "$member" ] && [ "$member" != "$SHA" ] || continue
            _cg_write_verdict "$member" green "batch:${SHA:0:12}" "$member_tree" \
                && _cg_post_status "success" "green, covered by the batch verified on ${SHA:0:12}" "vm/gate" "$member"
        done < <(git -C "$REPO" log --first-parent --format='%H %T' "$COMMIT_GATE_BATCH_BASE..$SHA" 2>/dev/null)
    fi
else
    log "no verdict written (rc=$RC)"
    tail -3 "$RUN_LOG" >&2 2>/dev/null || true
fi

if [ "$VERDICT" = "red" ]; then
    mkdir -p "$STATE_DIR/gate-red-tails" "$STATE_DIR/gate-scopes" 2>/dev/null
    grep -E '^(FAILED|ERROR) |^E ' "$RUN_LOG" 2>/dev/null | head -60 > "$STATE_DIR/gate-red-tails/$SHA" 2>/dev/null || true
    cp -f "$WORK/.commit-gate-scope.json" "$STATE_DIR/gate-scopes/$SHA.json" 2>/dev/null || true
    bash "$SELF/eject.sh" "$SHA" "$REASON" || log "the eject exited non-zero; the verdict stands"
fi
exit "$RC"
