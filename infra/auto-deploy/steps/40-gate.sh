#!/bin/bash
# Step 40: the gate. Runs pytest on the exported tree, narrowed to the tests the
# commit can reach (step 20 decided the scope; this step classifies nothing).
#
# THREE VERDICTS, and the gate FAILS CLOSED:
#
#   green  pytest exited 0. Cached per (sha, scope, tree) and shipped.
#   red    the run HAPPENED and said no: rc 1 a regression, rc 2 to 4 a tree
#          that could not be collected or run, rc 5 a run that collected
#          nothing, a test with no register row, or a test that passed with its
#          own break applied. Nothing ships. Only rc 0 and rc 1 are cached,
#          because only those are a function of the tree alone.
#   amber  the run could not start or finish: uv sync failed, a timeout (124),
#          no interpreter (126/127), killed (137). Nothing ships either, from
#          the first one. Amber is never cached, never a regression and never
#          ejects; the bookmark holds and the next tick retries. Three ambers in
#          a row escalate the alert to red.
#
# A red sets gate_red=1 with one word in gate_red_reason and never exits: it
# blocks SHIPS only. Step 30's Caddy reload and step 90's bookkeeping still run.
#
# Scope `none` runs no pytest and posts NO vm/gate status: nothing ran, so there
# is nothing to report, and it must never read as success. The nightly
# unselected audit is what covers such a commit.
#
# The noop exit below ends the WHOLE cycle: a commit that touches nothing the
# box runs and that no test can reach is marked deployed without building.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

if ! ${compose_changed:-false} && ! ${caddy_changed:-false} && ! ${units_changed:-false} \
        && ! ${assistant_workspace_changed:-false} && ! ${vm_runs_changed_code:-false} \
        && [ "${ENV_CHANGED:-false}" != true ] && [ "${gate_scope:-full}" = "none" ]; then
    log "no deployable change and no reachable test; marking ${NEW_SHA:0:8} done without deploys"
    gh_status_range "success" "no deployable change (documents only)"
    echo "$NEW_SHA" > "$LAST_SHA_FILE"
    record_deploy_verdict noop
    exit 0
fi

gate_ok=1
gate_red=0
gate_red_reason=""
AMBER_FILE="$STATE_DIR/gate-amber-streak"
AMBER_LIMIT="${GATE_AMBER_LIMIT:-3}"

gate_paths=()
if [ -f "$gate_paths_file" ]; then
    while IFS= read -r selected_path; do
        [ -n "$selected_path" ] && gate_paths+=("$selected_path")
    done < "$gate_paths_file"
fi
case "$gate_scope" in
    none) gate_timeout=180 ;;
    selected) gate_timeout="${GATE_TIMEOUT_SELECTED:-900}" ;;
    *) gate_timeout="${GATE_TIMEOUT_FULL:-1200}" ;;
esac

# ── The verdict cache ───────────────────────────────────────────────────────
# Replay a verdict only for the same sha, the same scope word, the same tree,
# AND a run that cannot have measured less than this one needs: the range is
# one commit, or the recorded run was `full`, or it measured this same range.
gate_cached=0
gate_reused=0
if [ -z "${RELEASE_FORCE:-}" ] && [ "${GATE_ENABLED:-1}" = "1" ]; then
    cached_sha=""; cached_verdict=""; cached_scope=""; cached_at=""; cached_reason=""; cached_tree=""
    read -r cached_sha cached_verdict cached_scope cached_at cached_reason cached_tree \
        2>/dev/null < "$GATE_VERDICT_DIR/$NEW_SHA" || true
    gate_tree_now="$(git -C "$REPO" rev-parse "${NEW_SHA}^{tree}" 2>/dev/null || echo "")"
    gate_cache_reusable=0
    if [ "${gate_range_isolated:-0}" -eq 1 ] || [ "$cached_scope" = "full" ]; then
        gate_cache_reusable=1
    elif [ -n "${OLD_SHA:-}" ] && [ "$(cat "$GATE_VERDICT_DIR/$NEW_SHA.range" 2>/dev/null)" = "$OLD_SHA" ]; then
        gate_cache_reusable=1
    fi
    if [ "$cached_sha" = "$NEW_SHA" ] && [ "$cached_scope" = "$gate_scope" ] \
            && [ "$gate_cache_reusable" -eq 1 ] \
            && [ -n "$cached_tree" ] && [ "$cached_tree" = "$gate_tree_now" ]; then
        case "$cached_verdict" in
            green)
                gate_cached=1; gate_reused=1; gate_ok=1; gate_red=0
                log "[gate] ${NEW_SHA:0:12} already verified GREEN at scope $gate_scope; not re-running pytest" ;;
            red)
                gate_cached=1; gate_reused=1; gate_ok=0; gate_red=1
                gate_red_reason="${cached_reason:-regression}"
                log "[gate] ${NEW_SHA:0:12} already verified RED ($gate_red_reason) at scope $gate_scope; deploys stay skipped" ;;
        esac
    fi
fi

# One record per cycle that reached the gate, read by the nightly audit to
# check whether a narrowed run ever missed a failing test. A cycle with no
# record cannot be checked, so failing to write one pins the gate to full.
_record_gate_run() {
    local rc="$1"
    if ! mkdir -p "$STATE_DIR/gate-runs" 2>/dev/null; then
        _gate_run_unrecorded "could not create $STATE_DIR/gate-runs"
        return 0
    fi
    python3 - "$STATE_DIR/gate-runs/$NEW_SHA.json" "$NEW_SHA" "$gate_scope" "$rc" "$gate_paths_file" <<'PYEOF' >> "$LOG" 2>&1 || true
import json, pathlib, sys, time
out, sha, scope, rc, paths_file = sys.argv[1:6]
try:
    paths = [line for line in pathlib.Path(paths_file).read_text().splitlines() if line]
except OSError:
    paths = []
pathlib.Path(out).write_text(json.dumps({"sha": sha, "scope": scope, "paths": paths, "rc": int(rc), "ts": int(time.time())}))
PYEOF
    [ -s "$STATE_DIR/gate-runs/$NEW_SHA.json" ] || _gate_run_unrecorded "no record written for ${NEW_SHA:0:12}"
    return 0
}

_gate_run_unrecorded() {
    log "[gate] $1; tonight's audit cannot check this cycle, so the gate goes back to full scope"
    : > "$STATE_DIR/gate-selection-miss" 2>/dev/null || true
}

# rc 1 where every reported failure is a pytest-xdist worker the box killed is
# a run that could not finish, not a regression. Arithmetic, not a string
# match: crash lines must cover every FAILED/ERROR line. Only relevant when
# GATE_PYTEST_WORKERS asks for workers.
_gate_run_lost_a_worker() {
    local slice crashes failures
    slice=$(tail -c "+$(( ${gate_log_offset:-0} + 1 ))" "$LOG" 2>/dev/null) || return 1
    case "$slice" in *"node down: "*) : ;; *) return 1 ;; esac
    crashes=$(printf '%s\n' "$slice" | grep -c "^worker '.*' crashed while running '" || true)
    failures=$(printf '%s\n' "$slice" | grep -cE '^(FAILED|ERROR) ' || true)
    [ "$crashes" -ge 1 ] && [ "$failures" -ge 1 ] && [ "$crashes" -ge "$failures" ]
}

# The test paths of the commit's top-level directories that failed, for the
# vm/gate description.
_gate_failing_modules() {
    tail -n 600 "$LOG" 2>/dev/null | grep '^FAILED ' | sed 's/^FAILED //; s/::.*//' \
        | awk -F/ '{ print ($2 != "" ? $1 "/" $2 : $1) }' | sort -u | paste -sd, - | cut -c1-90
}

# The failure section of the run, kept for the eject's hand-back.
_gate_red_evidence() {
    local window banner
    window=$(tail -n 600 "$LOG" 2>/dev/null) || return 1
    banner=$(printf '%s\n' "$window" | grep -n '^=* FAILURES =*$' | tail -1 | cut -d: -f1)
    if [ -n "$banner" ]; then
        printf '%s\n' "$window" | tail -n "+$banner" | head -n 200
    else
        printf '%s\n' "$window" | tail -n 80
    fi
}

# A selected path the export does not contain, or that holds no test there, is
# dropped; a selection left empty is scope none, not a red.
if [ "$gate_scope" = "selected" ] && [ -n "${BUILD_TREE:-}" ] && [ -d "${BUILD_TREE:-}" ] \
        && [ "${#gate_paths[@]}" -gt 0 ]; then
    gate_paths_testable=()
    for gate_path in "${gate_paths[@]}"; do
        if [ -e "$BUILD_TREE/$gate_path" ] && [ -n "$(find "$BUILD_TREE/$gate_path" \
                \( -name 'test_*.py' -o -name '*_test.py' \) -print -quit 2>/dev/null)" ]; then
            gate_paths_testable+=("$gate_path")
        else
            log "[gate] selected path $gate_path holds no test at ${NEW_SHA:0:8}; dropped"
        fi
    done
    gate_paths=(${gate_paths_testable[@]+"${gate_paths_testable[@]}"})
    gate_selected_count="${#gate_paths[@]}"
    if [ "${#gate_paths[@]}" -eq 0 ]; then
        log "[gate] every selected path is testless at ${NEW_SHA:0:8}; scope none"
        gate_scope="none"
    fi
fi

# ── The environment: the export's own, a sibling of the export ──────────────
GATE_UV_SYNC_ARGS="${GATE_UV_SYNC_ARGS:---all-packages --all-extras --all-groups}"
sync_ok=1
if [ "$gate_cached" -eq 0 ] && [ "${GATE_ENABLED:-1}" = "1" ] && [ "$gate_scope" != "none" ] \
        && [ -n "${BUILD_TREE:-}" ] && [ -d "${BUILD_TREE:-}" ]; then
    GATE_VENV="$GATE_VENV_ROOT/$NEW_SHA"
    mkdir -p "$GATE_VENV_ROOT" 2>/dev/null
    rm -rf "${GATE_VENV_ROOT:?}"/* 2>/dev/null
    # shellcheck disable=SC2086
    if ( cd "$BUILD_TREE" && UV_PROJECT_ENVIRONMENT="$GATE_VENV" \
            timeout "${GATE_SYNC_TIMEOUT:-1200}" uv sync $GATE_UV_SYNC_ARGS ) >> "$LOG" 2>&1; then
        log "[gate] the exported tree has its own environment at $GATE_VENV"
    else
        log "[gate] uv sync for $BUILD_TREE failed; the gate has no environment to run in"
        sync_ok=0
        GATE_VENV=""
    fi
fi

gate_worker_args=()
case "${GATE_PYTEST_WORKERS:-0}" in
    0|'') ;;
    *[!0-9]*) log "[gate] GATE_PYTEST_WORKERS='${GATE_PYTEST_WORKERS}' is not a number; running one process" ;;
    *) gate_worker_args=(-n "$GATE_PYTEST_WORKERS" --dist loadfile) ;;
esac

if [ "$gate_cached" -eq 1 ]; then
    :
elif [ "${GATE_ENABLED:-1}" != "1" ]; then
    gate_ok=0
    log "[gate] the gate is disabled (GATE_ENABLED != 1); this deploy is not verified"
    gh_stage_head "vm/gate" "error" "gate disabled (GATE_ENABLED != 1); deploy not verified"
elif [ "$gate_scope" = "none" ]; then
    gate_ok=0
    log "[gate] no test can reach this change; pytest not run, and no vm/gate status posted"
    [ "${env_only:-false}" = true ] || _record_gate_run -1
elif [ -z "${BUILD_TREE:-}" ] || [ ! -d "${BUILD_TREE:-}" ]; then
    gate_ok=0
    gate_red=1
    gate_red_reason="no_export"
    log "[gate] no exported tree to verify; nothing was tested and nothing ships"
    gh_stage_head "vm/gate" "error" "no exported tree to test; nothing verified, nothing shipped"
elif [ -d "$BUILD_TREE/tools/test_register" ] \
        && ! register_report=$( cd "$BUILD_TREE" && python3 -m tools.test_register --check --repo "$BUILD_TREE" 2>&1 ); then
    gate_ok=0
    gate_red=1
    gate_red_reason="register"
    log "[gate] the test register and the tree disagree; nothing was tested and nothing ships"
    printf '%s\n' "$register_report" | while IFS= read -r register_line; do log "[gate]   $register_line"; done
    gh_stage_head "vm/gate" "failure" "a test in the tree has no register row; nothing verified, nothing shipped"
elif [ "$sync_ok" -eq 1 ]; then
    gh_stage_head "vm/gate" "pending" "verifying ($gate_scope scope, $gate_selected_count paths)"
    gate_log_offset=$(wc -c < "$LOG" 2>/dev/null || echo 0)
    # A clean environment: the box's production settings must not be visible
    # to a test that asserts a variable is ABSENT. Keep this list identical to
    # tools/gate_scope/audit_full_run.sh, or the audit stops being evidence.
    ( cd "$BUILD_TREE" || exit 126
    env -i \
        HOME="$HOME" \
        PATH="/usr/local/bin:/usr/bin:/bin" \
        LANG=C.UTF-8 \
        PYTHONPATH="$BUILD_TREE" \
        timeout "$gate_timeout" "$GATE_VENV/bin/pytest" -q -rfE \
        ${gate_worker_args[@]+"${gate_worker_args[@]}"} \
        --ignore=.claude/worktrees \
        ${gate_paths[@]+"${gate_paths[@]}"} \
        >> "$LOG" 2>&1 )
    gate_rc=$?
    _record_gate_run "$gate_rc"
    if [ "$gate_rc" -eq 0 ]; then
        rm -f "$AMBER_FILE"
        # A green suite is not yet proof: every register row this commit
        # touches has its break replayed, and a test that passes with its own
        # break applied checks nothing.
        if [ -d "$BUILD_TREE/tools/test_register" ] && [ -s "$STATE_DIR/gate-changed-paths" ]; then
            replay_report=$( cd "$BUILD_TREE" && env -i \
                HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" LANG=C.UTF-8 PYTHONPATH="$BUILD_TREE" \
                timeout 900 "$GATE_VENV/bin/python" -m tools.test_register \
                --changed-file "$STATE_DIR/gate-changed-paths" --repo "$BUILD_TREE" 2>&1 )
            replay_rc=$?
            printf '%s\n' "$replay_report" | while IFS= read -r replay_line; do
                [ -n "$replay_line" ] && log "[gate] $replay_line"
            done
            if [ "$replay_rc" -eq 1 ]; then
                gate_ok=0
                gate_red=1
                gate_red_reason="unfalsifiable_test"
                log "[gate] RED: a test passed with its own break applied, so it checks nothing"
                gh_stage_head "vm/gate" "failure" "a test passed with its own break applied; nothing shipped"
            elif [ "$replay_rc" -ne 0 ]; then
                log "[gate] the break replay could not finish (rc=$replay_rc); nothing was proved by it and nothing is held for it"
            fi
        fi
        if [ "${gate_red:-0}" -ne 1 ]; then
            record_gate_verdict green
            gh_stage_head "vm/gate" "success" "gate green ($gate_scope scope)"
        fi
    elif [ "$gate_rc" -eq 1 ]; then
        gate_ok=0
        if [ "${#gate_worker_args[@]}" -gt 0 ] && _gate_run_lost_a_worker; then
            gate_red=1
            gate_red_reason="worker_crash"
            amber_streak=$(( $(cat "$AMBER_FILE" 2>/dev/null || echo 0) + 1 ))
            echo "$amber_streak" > "$AMBER_FILE"
            log "[gate] pytest said no (rc=1) but every failure was a worker this box killed; amber, not a regression"
            gh_stage_head "vm/gate" "error" "a test worker was killed mid-run (streak $amber_streak/$AMBER_LIMIT); nothing verified, nothing shipped"
            if [ "$amber_streak" -ge "$AMBER_LIMIT" ]; then
                fire_alert_once "gate-worker-crash" "$NEW_SHA" "auto-deploy: the gate keeps losing test workers" \
                    "Test workers were killed for $amber_streak cycles, most recently at ${NEW_SHA:0:12}, so nothing has shipped. That is memory on this box, not a broken test: lower GATE_PYTEST_WORKERS. Log: $LOG" \
                    --wakes-somebody --blocks-deploy yes
            fi
        else
            gate_red=1
            gate_red_reason="regression"
            rm -f "$AMBER_FILE"
            if [ "${gate_range_isolated:-0}" -eq 1 ]; then
                record_gate_verdict red
            fi
            _gate_red_evidence > "$STATE_DIR/gate-red-tail" 2>/dev/null || true
            log "[gate] RED (test regression); skipping deploys of ${NEW_SHA:0:12}"
            if [ "${gate_range_isolated:-0}" -eq 1 ]; then
                gh_status_range "failure" "gate red: test regression, deploy skipped"
            else
                gh_status_range "failure" "held: ${OLD_SHA:0:8}..${NEW_SHA:0:8} failed the gate as one range"
            fi
            gate_red_modules="$(_gate_failing_modules)"
            gh_stage_head "vm/gate" "failure" "${gate_red_modules:+$gate_red_modules: }test regression; deploy skipped"
            if [ "${EJECT_ENABLED:-0}" = "1" ]; then
                log "[gate] RED at ${NEW_SHA:0:12}; not alerting, the eject speaks for this commit"
            else
                fire_alert_once "gate-red" "$NEW_SHA" "auto-deploy: the gate is red" \
                    "pytest failed (rc=1) at ${NEW_SHA:0:12}, \"$(_commit_subject "$NEW_SHA")\"; nothing shipped. The eject is off, so the commit stays on main and the bookmark stays put until it is fixed or reverted by hand. Log: $LOG" \
                    --wakes-somebody --blocks-deploy yes --exit-code "$gate_rc"
            fi
        fi
    elif [ "$gate_rc" -eq 5 ]; then
        gate_red=1
        gate_ok=0
        gate_red_reason="no_tests_collected"
        rm -f "$AMBER_FILE"
        log "[gate] RED: pytest collected no tests at scope $gate_scope ($gate_selected_count selected paths)"
        gh_status_range "failure" "gate red: the run collected no tests"
        gh_stage_head "vm/gate" "failure" "no tests collected at scope $gate_scope; nothing was verified"
        fire_alert_once "gate-empty" "$NEW_SHA" "auto-deploy: the gate collected no tests" \
            "pytest collected 0 tests at ${NEW_SHA:0:12} with scope $gate_scope. A selection that collects nothing is a broken selector. Check $gate_scope_json and $LOG." \
            --wakes-somebody --blocks-deploy yes --exit-code "$gate_rc"
    elif [ "$gate_rc" -ge 2 ] && [ "$gate_rc" -le 4 ]; then
        gate_red=1
        gate_ok=0
        gate_red_reason="broken_tree"
        rm -f "$AMBER_FILE"
        log "[gate] RED (rc=$gate_rc: the suite could not be collected or run against this tree)"
        gh_status_range "failure" "gate red: pytest rc=$gate_rc, nothing verified"
        gh_stage_head "vm/gate" "failure" "pytest rc=$gate_rc (collection, internal or usage error); nothing verified"
        fire_alert_once "gate-broken-tree" "$NEW_SHA" "auto-deploy: the gate could not load the code" \
            "pytest exited rc=$gate_rc at ${NEW_SHA:0:12}: a collection, internal or usage error, so the repository's own code could not be loaded. Nothing shipped. Log: $LOG" \
            --wakes-somebody --blocks-deploy yes --exit-code "$gate_rc"
    else
        gate_ok=0
        gate_red=1
        amber_streak=$(( $(cat "$AMBER_FILE" 2>/dev/null || echo 0) + 1 ))
        echo "$amber_streak" > "$AMBER_FILE"
        if [ "$amber_streak" -ge "$AMBER_LIMIT" ]; then
            gate_red_reason="amber_escalated"
            log "[gate] AMBER $amber_streak times in a row (rc=$gate_rc); escalating to red"
            gh_stage_head "vm/gate" "error" "gate stuck: rc=$gate_rc for $amber_streak cycles; escalated to red"
            fire_alert_once "gate-stuck" "$NEW_SHA" "auto-deploy: the gate is stuck" \
                "pytest could not run (rc=$gate_rc) for $amber_streak cycles at ${NEW_SHA:0:12}; nothing ships until it can. Fix the box (disk, memory, uv) or raise GATE_AMBER_LIMIT. Log: $LOG" \
                --wakes-somebody --blocks-deploy yes --exit-code "$gate_rc"
        else
            gate_red_reason="amber"
            log "[gate] pytest could not start or finish (rc=$gate_rc, streak $amber_streak); nothing shipped, the next tick retries"
            gh_stage_head "vm/gate" "error" "gate could not run (rc=$gate_rc, streak $amber_streak/$AMBER_LIMIT); nothing shipped, the next tick retries"
            gh_status_range "error" "the gate could not run (rc=$gate_rc); nothing shipped"
        fi
    fi
else
    gate_ok=0
    gate_red=1
    amber_streak=$(( $(cat "$AMBER_FILE" 2>/dev/null || echo 0) + 1 ))
    echo "$amber_streak" > "$AMBER_FILE"
    if [ "$amber_streak" -ge "$AMBER_LIMIT" ]; then
        gate_red_reason="sync_stuck"
        gh_stage_head "vm/gate" "error" "uv sync failed $amber_streak times; escalated to red"
        fire_alert_once "gate-sync-stuck" "$NEW_SHA" "auto-deploy: the gate cannot prepare its environment" \
            "uv sync failed for $amber_streak cycles at ${NEW_SHA:0:12}; nothing ships until it works. Log: $LOG" \
            --wakes-somebody --blocks-deploy yes
    else
        gate_red_reason="sync_failed"
        log "[gate] uv sync failed (streak $amber_streak); nothing shipped, the next tick retries"
        gh_stage_head "vm/gate" "error" "uv sync failed (streak $amber_streak/$AMBER_LIMIT); nothing shipped, the next tick retries"
        gh_status_range "error" "the gate could not be prepared (uv sync failed); nothing shipped"
    fi
fi

[ "$gate_ok" -eq 1 ] && log "[gate] gate green"

# A red on a range of several commits names no commit, so it is not a verdict.
# Recorded against the bookmark instead; step 20 then drops back to one commit.
if [ "${gate_red:-0}" -eq 1 ] && [ "${gate_range_isolated:-0}" -ne 1 ] \
        && [ -n "${OLD_SHA:-}" ] && [ "$OLD_SHA" != "$NEW_SHA" ]; then
    range_seen=1
    prev_bookmark=""; prev_head=""; prev_at=""; prev_reason=""; prev_count=""
    if [ -r "$BUILD_HEAD_RED_FILE" ]; then
        read -r prev_bookmark prev_head prev_at prev_reason prev_count < "$BUILD_HEAD_RED_FILE" 2>/dev/null || true
        : "$prev_head$prev_at$prev_reason"
        case "$prev_count" in "" | *[!0-9]*) prev_count=1 ;; esac
        [ "$prev_bookmark" = "$OLD_SHA" ] && range_seen=$(( prev_count + 1 ))
    fi
    printf '%s %s %s %s %s\n' "$OLD_SHA" "$NEW_SHA" "$(date +%s)" "${gate_red_reason:-unknown}" "$range_seen" \
        > "$BUILD_HEAD_RED_FILE.tmp" 2>/dev/null && mv -f "$BUILD_HEAD_RED_FILE.tmp" "$BUILD_HEAD_RED_FILE" 2>/dev/null || true
    log "[gate] ${OLD_SHA:0:8}..${NEW_SHA:0:8} went red as a range; the next cycle takes the single commit after the bookmark"
fi
