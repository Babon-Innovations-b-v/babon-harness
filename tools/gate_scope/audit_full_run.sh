#!/bin/bash
# The nightly UNSELECTED run of the deploy gate's suite.
#
# WHY THIS EXISTS. infra/auto-deploy/steps/20-changes.sh may hand the gate a
# subset of the suite instead of all of it. Running less than everything is
# only defensible while a control proves the narrowing works, and this script
# is that control. It runs the whole suite once a night with no selection and
# answers two questions:
#
#   1. Does the suite pass when nothing is narrowed? Then it stamps
#      $STATE_DIR/last-full-audit-ok with the time. Step 20 pins the gate back
#      to `full` when that stamp is missing or older than 48 hours, so the
#      licence expires by itself if this job stops running.
#   2. If not, did any failing test sit OUTSIDE a selection a narrowed cycle
#      reported green? That is a selection miss: it writes
#      $STATE_DIR/gate-selection-miss and alerts, and step 20 pins the gate to
#      full until a person removes that file, because a register row that
#      claimed a test reads less than it does cannot be trusted to be wrong once.
#
# The evidence for question 2 is $STATE_DIR/gate-runs/<sha>.json, one record per
# cycle or verifying run that reached the gate. This script is the only reader
# and also sweeps records older than a week.
#
# SAME SUITE, SAME WAY. It runs the gate's own suite in the gate's own way: the
# `--ignore` list is GREPPED out of infra/auto-deploy/steps/40-gate.sh, never
# restated; the run is a `git archive` export of the clone's HEAD with a `.git`
# of its own, never the clone; the environment is built for that export, never
# borrowed from the clone; and the clean environment pytest runs in is the
# gate's. A test compares
# the two scripts so they cannot drift.
#
# FAILURE POLICY: fail toward the FULL gate. Anything this cannot do (no uv, an
# export or a sync that fails, a timeout) leaves the stamp untouched and exits
# non-zero, so the unit fails, its failure handler pages, and the 48-hour
# licence runs out. No path stamps a green it did not observe.
#
# NOT A DEPLOY GATE. It takes no deploy lock and blocks nothing; it runs at
# `nice 19` with idle IO.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${GATE_AUDIT_REPO:-$(cd "$HERE/../.." && pwd)}"
HARNESS_ROOT="${HARNESS_ROOT:-$(dirname "$REPO")}"
STATE_DIR="${GATE_AUDIT_STATE_DIR:-/var/lib/harness}"
LOG="${GATE_AUDIT_LOG:-/var/log/harness/gate-audit.log}"
GATE_STEP="$REPO/infra/auto-deploy/steps/40-gate.sh"
STAMP="$STATE_DIR/last-full-audit-ok"
MISS_FILE="$STATE_DIR/gate-selection-miss"
RUNS_DIR="$STATE_DIR/gate-runs"
AUDIT_TIMEOUT="${GATE_AUDIT_TIMEOUT:-3600}"
RECORD_KEEP_DAYS="${GATE_AUDIT_KEEP_DAYS:-7}"
GATE_UV_SYNC_ARGS="${GATE_UV_SYNC_ARGS:---all-packages --all-extras --all-groups}"

# The alert door needs the assistant's address and bearer from the config.
if [ -r "$REPO/infra/auto-deploy/steps/doors.sh" ]; then
    # shellcheck disable=SC1091
    . "$REPO/infra/auto-deploy/steps/doors.sh" && harness_load_config "$REPO"
fi

mkdir -p "$STATE_DIR" 2>/dev/null || true
{ : >> "$LOG"; } 2>/dev/null || LOG="/tmp/harness-gate-audit.log"
log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

# Alert through the deploy system's own door: a record unless it wakes somebody.
audit_alert() {
    log "ALERT: $1"
    python3 "$REPO/infra/auto-deploy/notify.py" "$1" "$2" >> "$LOG" 2>&1 || true
    return 0
}

cd "$REPO" || { log "FATAL: cannot cd $REPO"; exit 1; }

UV="$(command -v uv 2>/dev/null || true)"
[ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
if [ -z "$UV" ]; then
    log "FATAL: no uv on PATH or at \$HOME/.local/bin/uv; no audit ran, the narrowing licence expires on its own"
    exit 1
fi

ignore_args=()
while IFS= read -r flag; do
    [ -n "$flag" ] && ignore_args+=("$flag")
done < <(grep -oE -- '--ignore=[^[:space:]]+' "$GATE_STEP" 2>/dev/null)
if [ "${#ignore_args[@]}" -eq 0 ]; then
    log "FATAL: no --ignore flags found in $GATE_STEP; refusing to run a suite that is not the gate's"
    exit 1
fi

head_sha=$(git rev-parse HEAD 2>/dev/null || echo "")

AUDIT_TREE_ROOT="${GATE_AUDIT_TREE_ROOT:-$HARNESS_ROOT/audit-tree}"
AUDIT_VENV_ROOT="${GATE_AUDIT_VENV_ROOT:-$HARNESS_ROOT/audit-venv}"
audit_tree="$AUDIT_TREE_ROOT/${head_sha:-unknown}"
audit_venv="$AUDIT_VENV_ROOT/${head_sha:-unknown}"
mkdir -p "$AUDIT_TREE_ROOT" "$AUDIT_VENV_ROOT" 2>/dev/null
rm -rf "${AUDIT_TREE_ROOT:?}"/* "${AUDIT_VENV_ROOT:?}"/* 2>/dev/null
trap 'rm -rf "${AUDIT_TREE_ROOT:?}"/* "${AUDIT_VENV_ROOT:?}"/* 2>/dev/null' EXIT
mkdir -p "$audit_tree" || { log "FATAL: cannot make $audit_tree"; exit 1; }
if ! git archive "$head_sha" | tar -x -C "$audit_tree"; then
    log "FATAL: could not export ${head_sha:0:12}; no audit ran"
    exit 1
fi
audit_objects="$( cd "$REPO" && cd "$(git rev-parse --git-common-dir)" && pwd )/objects"
if ! { git -C "$audit_tree" init -q \
        && printf '%s\n' "$audit_objects" > "$audit_tree/.git/objects/info/alternates" \
        && git -C "$audit_tree" update-ref HEAD "$head_sha" \
        && git -C "$audit_tree" read-tree HEAD; }; then
    log "FATAL: could not make $audit_tree a git repository; no audit ran"
    exit 1
fi
# shellcheck disable=SC2086
if ! ( cd "$audit_tree" && UV_PROJECT_ENVIRONMENT="$audit_venv" "$UV" sync $GATE_UV_SYNC_ARGS ) >> "$LOG" 2>&1; then
    log "FATAL: could not build an environment for ${head_sha:0:12}; no audit ran"
    exit 1
fi

started=$(date +%s)
log "[audit] running the unselected suite at ${head_sha:0:12} (${#ignore_args[@]} ignores, cap ${AUDIT_TIMEOUT}s)"
run_log=$(mktemp -t harness-gate-audit-XXXX.log)
(
    cd "$audit_tree" || exit 1
    env -i \
        HOME="$HOME" \
        PATH="/usr/local/bin:/usr/bin:/bin" \
        LANG=C.UTF-8 \
        PYTHONPATH="$audit_tree" \
        nice -n 19 ionice -c 3 \
        timeout "$AUDIT_TIMEOUT" "$audit_venv/bin/pytest" -q --tb=no -rf \
        "${ignore_args[@]}"
) > "$run_log" 2>&1
audit_rc=$?
elapsed=$(( $(date +%s) - started ))
cat "$run_log" >> "$LOG"

find "$RUNS_DIR" -maxdepth 1 -name '*.json' -mtime "+$RECORD_KEEP_DAYS" -delete 2>/dev/null || true

if [ "$audit_rc" -eq 0 ]; then
    date +%s > "$STAMP.tmp" && mv -f "$STAMP.tmp" "$STAMP"
    log "[audit] GREEN in ${elapsed}s; narrowing licensed for another 48h"
    rm -f "$run_log"
    exit 0
fi

# Not green. Was anything that failed outside a selection that a narrowed cycle
# reported green? Scope `full` ran this same suite; rc 0 green, -1 scope none.
miss_report=$(python3 - "$RUNS_DIR" "$run_log" "$STAMP" <<'PYEOF'
import json
import pathlib
import sys

runs_dir, run_log, stamp = (pathlib.Path(argument) for argument in sys.argv[1:4])
failed_files = set()
for line in run_log.read_text(encoding="utf-8", errors="replace").splitlines():
    if line.startswith("FAILED "):
        failed_files.add(line[len("FAILED "):].split(" ")[0].split("::")[0])
try:
    licensed_from = int(stamp.read_text().strip())
except (OSError, ValueError):
    licensed_from = 0


def covers(selection, test_file):
    return any(test_file == entry or test_file.startswith(entry + "/") for entry in selection)


misses = []
for record_path in sorted(runs_dir.glob("*.json")) if runs_dir.is_dir() else []:
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        misses.append(f"{record_path.name} unreadable")
        continue
    if record.get("scope") == "full" or record.get("rc") not in (0, -1):
        continue
    if int(record.get("ts", 0)) < licensed_from:
        continue
    selection = [str(entry) for entry in record.get("paths", [])]
    for test_file in sorted(failed_files):
        if not covers(selection, test_file):
            misses.append(f"{record.get('sha', '?')} {record.get('scope', '?')} {test_file}")
print("\n".join(misses))
PYEOF
)

if [ -n "$miss_report" ]; then
    {
        echo "# written by tools/gate_scope/audit_full_run.sh at $(date -Iseconds)"
        echo "# a narrowed gate reported green without running a test that is now failing."
        echo "# remove this file by hand once the register row has been fixed."
        printf '%s\n' "$miss_report"
    } >> "$MISS_FILE"
    log "[audit] SELECTION MISS after ${elapsed}s; the gate is pinned to the full suite until $MISS_FILE is removed"
    audit_alert "gate audit: a narrowed gate missed a real failure" \
        "The nightly unselected run at ${head_sha:0:12} failed tests a narrowed cycle reported green without running:

$(printf '%s\n' "$miss_report" | head -20)

A row in tools/test_register claims one of those tests reads less of the tree than it does. Until $MISS_FILE is removed by hand, every deploy runs the full suite. Log: $LOG"
    rm -f "$run_log"
    exit 3
fi

log "[audit] RED after ${elapsed}s (pytest rc=$audit_rc), but every failure was inside a selection that ran; no narrowing miss, and no stamp"
rm -f "$run_log"
exit 1
