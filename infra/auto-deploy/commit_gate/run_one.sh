#!/bin/bash
# Verify ONE commit in a world of its own: its own exported tree, its own
# environment, its own scope, its own suite, its own images, its own verdict.
#
#   commit_gate/run_one.sh <sha>
#
# The verifying lane runs this ahead of the deploy cycle for every commit queued
# past the bookmark, so when the cycle reaches a commit its verdict is usually
# already written and the gate is a cache hit. It shares nothing with the cycle
# but the clone's object database (read-only, through git alternates): no lock,
# no working tree, no scope file. It never writes inside the clone and never
# takes the cycle's lock.
#
# EXIT CODES, the deploy gate's table: 0 green; 1 to 5 red; anything else amber.
# This script's own refusals are amber: 65 not a commit, 70 export failed, 72 an
# image this box could not build, 75 environment, 76 no ignore list, 77 empty
# selection, 78 run as root, 79 this commit's ignore list is not the clone's.
# `scope none` is not green: exit 3, no verdict, and the nightly unselected
# audit is the cover.
#
# ONLY rc 0 AND rc 1 ARE WRITTEN DOWN, because only those are a function of the
# tree alone; 2 to 5 depend on box state the commit does not pin, and the
# cycle's own run answers those. A verdict is never REPLACED when it was written
# after this run started, or when a green for this exact tree is already there:
# that green is what the cycle shipped on.
#
# A red verdict is handed to commit_gate/eject.sh at once (which does nothing
# while the eject is off). Statuses: vm/gate from the SUITE's rc, vm/build from
# the build, so a broken image is never reported as a broken test. Nothing
# pending is ever posted, and amber posts nothing.

set -u
SELF="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$SELF/../steps/doors.sh"
REPO="${COMMIT_GATE_REPO:-$HARNESS_ROOT/repo}"
harness_load_config "$REPO"
STATE_DIR="${STATE_DIR:-/var/lib/harness}"
GATE_VERDICT_DIR="${GATE_VERDICT_DIR:-$STATE_DIR/gate-verdicts}"
COMMIT_GATE_ROOT="${COMMIT_GATE_ROOT:-$HARNESS_ROOT/commit-gate}"
COMMIT_GATE_TIMEOUT="${COMMIT_GATE_TIMEOUT:-2400}"
COMMIT_GATE_SYNC_TIMEOUT="${COMMIT_GATE_SYNC_TIMEOUT:-1200}"
COMMIT_GATE_WORKERS="${COMMIT_GATE_WORKERS:-0}"
COMMIT_GATE_KEEP="${COMMIT_GATE_KEEP:-0}"
COMMIT_GATE_BUILD_ENABLED="${COMMIT_GATE_BUILD_ENABLED:-1}"
COMMIT_GATE_STATUS="${COMMIT_GATE_STATUS:-1}"
GATE_UV_SYNC_ARGS="${GATE_UV_SYNC_ARGS:---all-packages --all-extras --all-groups}"
GH_REPO_SLUG="${GH_REPO_SLUG:-$(harness_repo_slug "$REPO")}"
LOG="${COMMIT_GATE_LOG:-/var/log/harness/commit-gate.log}"
{ : >> "$LOG"; } 2>/dev/null || LOG="/tmp/harness-commit-gate.log"
RUN_STARTED="$(date +%s)"
CG_STATUS_ARMED=0
log() { printf '[%s] [commit-gate %s] %s\n' "$(date -Iseconds)" "${SHA:0:12}" "$*" | tee -a "$LOG" >&2; }

_cg_post_status() {
    [ "$COMMIT_GATE_STATUS" = "1" ] || return 0
    gh_post_status "${SHA:-}" "${3:-vm/gate}" "$1" "$2" ""
    return 0
}

# Posted from the EXIT trap, so a killed run still says what it knows.
_cg_resolve_status() {
    local suite_rc="${SUITE_RC:-$1}"
    [ "$CG_STATUS_ARMED" = "1" ] || return 0
    CG_STATUS_ARMED=0
    case "$suite_rc" in
        0) _cg_post_status "success" "green ($SCOPE scope), verified ahead of the cycle" ;;
        1|2|3|4|5) _cg_post_status "failure" "red (pytest rc=$suite_rc, $SCOPE scope), verified ahead of the cycle" ;;
        *) log "no vm/gate posted (rc=$suite_rc): this run could not finish, so the cycle gates this commit itself" ;;
    esac
    case "${BUILD_STATE:-not-run}" in
        green) _cg_post_status "success" "images built from this commit's own tree" "vm/build" ;;
        red)   _cg_post_status "failure" "an image could not be built from this commit" "vm/build" ;;
    esac
    return 0
}

if [ "$(id -u)" = "0" ]; then
    printf 'run_one.sh: refusing to run as root: root ignores the file modes tests depend on\n' >&2
    exit 78
fi
SHA="${1:-}"
[ -n "$SHA" ] || { printf 'usage: run_one.sh <sha>\n' >&2; exit 64; }
if ! SHA="$(git -C "$REPO" rev-parse --verify --quiet "${SHA}^{commit}")"; then
    log "not a commit in $REPO"
    exit 65
fi
TREE_HASH="$(git -C "$REPO" rev-parse "${SHA}^{tree}" 2>/dev/null || echo "")"
[ -n "$TREE_HASH" ] || { log "cannot resolve the tree"; exit 65; }

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
VENV="$COMMIT_GATE_ROOT/venv-$SHA"
cleanup() {
    local rc=$?
    _cg_resolve_status "$rc"
    if [ "$COMMIT_GATE_KEEP" != "1" ]; then
        case "$WORK" in "$COMMIT_GATE_ROOT"/*) rm -rf "$WORK" 2>/dev/null ;; esac
        case "$VENV" in "$COMMIT_GATE_ROOT"/*) rm -rf "$VENV" 2>/dev/null ;; esac
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
# diff this commit is.
CHANGED_FILE="$WORK/.commit-gate-changed"
git -C "$REPO" -c core.quotePath=false diff --name-only --no-renames "${SHA}^" "$SHA" > "$CHANGED_FILE" 2>/dev/null \
    || git -C "$REPO" ls-tree -r --name-only "$SHA" > "$CHANGED_FILE" 2>/dev/null || true
SCOPE="full"
PATHS_FILE="$WORK/.commit-gate-paths"
: > "$PATHS_FILE"
if scope_word="$( cd "$WORK" && python3 -m tools.gate_scope --changed-file "$CHANGED_FILE" --repo "$WORK" \
        --out-paths "$PATHS_FILE" --out-json "$WORK/.commit-gate-scope.json" 2>/dev/null )"; then
    case "$scope_word" in none | selected | full) SCOPE="$scope_word" ;; esac
fi
SELECTED=$(wc -l < "$PATHS_FILE" 2>/dev/null | tr -d ' ')
log "scope $SCOPE, ${SELECTED:-0} selected path(s)"
if [ "$SCOPE" = "none" ]; then
    log "no test can reach anything this commit touched"
    exit 3
fi

SYNC_LOG="$WORK/.commit-gate-sync.log"
# shellcheck disable=SC2086
if ! ( cd "$WORK" && UV_PROJECT_ENVIRONMENT="$VENV" timeout "$COMMIT_GATE_SYNC_TIMEOUT" uv sync $GATE_UV_SYNC_ARGS ) > "$SYNC_LOG" 2>&1; then
    log "uv sync failed, so there is no environment to run the suite in"
    mkdir -p "$STATE_DIR/gate-sync-tails" 2>/dev/null
    tail -40 "$SYNC_LOG" > "$STATE_DIR/gate-sync-tails/$SHA" 2>/dev/null || true
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
WORKER_ARGS=()
[ "$COMMIT_GATE_WORKERS" != "0" ] && WORKER_ARGS=(-n "$COMMIT_GATE_WORKERS" --dist loadfile)

CG_STATUS_ARMED=1
RUN_LOG="$WORK/.commit-gate-run.log"
( cd "$WORK" || exit 126
  env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" LANG=C.UTF-8 PYTHONPATH="$WORK" \
      timeout "$COMMIT_GATE_TIMEOUT" "$VENV/bin/pytest" -q --tb=no -rfE \
      ${WORKER_ARGS[@]+"${WORKER_ARGS[@]}"} "${IGNORE_ARGS[@]}" ${SELECTED_ARGS[@]+"${SELECTED_ARGS[@]}"} ) > "$RUN_LOG" 2>&1
RC=$?
SUITE_RC=$RC

# Build only after a green suite, push nothing.
BUILD_STATE="not-run"
RED_REASON=""
if [ "$RC" -eq 0 ] && [ "$COMMIT_GATE_BUILD_ENABLED" = "1" ]; then
    COMMIT_GATE_CHANGED_FILE="$CHANGED_FILE" bash "$SELF/build_images.sh" "$SHA" "$WORK"
    case "$?" in
        0) BUILD_STATE="green" ;;
        1) BUILD_STATE="red"; RC=1; RED_REASON="build_regression" ;;
        *) BUILD_STATE="box"; RC=72 ;;
    esac
fi

case "$RC" in
    0) VERDICT="green"; REASON="none" ;;
    1) VERDICT="red"; REASON="${RED_REASON:-regression}" ;;
    *) VERDICT=""; REASON="" ;;
esac
if [ -n "$VERDICT" ]; then
    mkdir -p "$GATE_VERDICT_DIR" 2>/dev/null
    live_sha=""; live_verdict=""; live_scope=""; live_at=""; live_reason=""; live_tree=""
    [ -r "$GATE_VERDICT_DIR/$SHA" ] \
        && read -r live_sha live_verdict live_scope live_at live_reason live_tree < "$GATE_VERDICT_DIR/$SHA"
    : "$live_scope$live_reason"
    case "$live_at" in "" | *[!0-9]*) live_at=0 ;; esac
    verdict_stands=""
    if [ "$live_sha" = "$SHA" ] && [ "$live_tree" = "$TREE_HASH" ]; then
        if [ "$live_at" -ge "$RUN_STARTED" ]; then
            verdict_stands="it was written after this run started"
        elif [ "$live_verdict" = "green" ] && [ "$VERDICT" = "red" ]; then
            verdict_stands="a green for this exact tree is what the cycle shipped on"
        fi
    fi
    if [ -n "$verdict_stands" ]; then
        log "$VERDICT (rc=$RC), but the $live_verdict verdict for this tree stands: $verdict_stands"
    else
        printf '%s %s %s %s %s %s\n' "$SHA" "$VERDICT" "$SCOPE" "$(date +%s)" "$REASON" "$TREE_HASH" \
            > "$GATE_VERDICT_DIR/$SHA.tmp.$$" 2>/dev/null \
            && mv -f "$GATE_VERDICT_DIR/$SHA.tmp.$$" "$GATE_VERDICT_DIR/$SHA" 2>/dev/null \
            || log "could not record the verdict"
        log "$VERDICT (rc=$RC, scope $SCOPE)"
        _cg_record_gate_run
    fi
else
    log "no verdict written (rc=$RC): it depends on box state this commit does not pin"
    tail -3 "$RUN_LOG" >&2 2>/dev/null || true
fi

if [ "$VERDICT" = "red" ]; then
    mkdir -p "$STATE_DIR/gate-red-tails" "$STATE_DIR/gate-scopes" 2>/dev/null
    grep -E '^(FAILED|ERROR) |^E ' "$RUN_LOG" 2>/dev/null | head -60 > "$STATE_DIR/gate-red-tails/$SHA" 2>/dev/null || true
    cp -f "$WORK/.commit-gate-scope.json" "$STATE_DIR/gate-scopes/$SHA.json" 2>/dev/null || true
    bash "$SELF/eject.sh" "$SHA" "$REASON" || log "the eject exited non-zero; the verdict stands"
fi
exit "$RC"
