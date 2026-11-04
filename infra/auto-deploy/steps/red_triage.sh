# shellcheck shell=bash
# NOT A STEP, and it must never go in ../auto-deploy.sh's source list: it only
# defines functions. Sourced by 40-gate.sh. Needs doors.sh (`_gh_api`,
# `_gh_ready`, `log`) loaded first.
#
# WHOSE FAULT A RED IS. Nothing ever holds the queue: a red gate is a WRONG
# COMMIT or a WRONG TEST. Each test file a red run names is run twice more,
#
#   same    the same commit, in a fresh gate Job
#   good    the last good tree, the one the deploy shipped (the bookmark)
#
# and `python3 -m tools.red_triage` sorts the answers (the rule is in
# tools/red_triage/_triage.py). A test that flips, or fails on the last good
# tree too, is QUARANTINED: an issue is opened for its owner under the backlog
# PRD, its register row gets `quarantined=` on main through the GitHub API, and
# the gate runs again without it, so the deploy continues. There is no time
# limit: the owner deletes the line in the commit that fixes the test. Every
# other test stays in the gate and the gate still fails closed on it. A red
# that is the commit's goes to the eject.
#
# THE CALLER'S HOOK. `_red_triage_run <same|good> <list> <out>` runs the test
# files listed in <list> against this commit or the last good tree, writes the
# files that failed to <out> (`_red_failing_files`) and returns pytest's exit
# code. The caller knows where its tree and its Job are; this file knows only
# the rule.
#
# FAILURE POLICY: nothing here may turn a red into a green. A triage that cannot
# run answers `setup` (the box: amber, never a revert) when a run could not
# happen, and `commit` when the sorter itself is missing, which is what the
# gate answered before this file existed. A run counts as an answer only when
# it exited 0, or exited 1 to 4 AND named the files it failed.
#
# THE QUARANTINE LIVES ON MAIN AND NOWHERE ELSE. No record is kept in the
# cycle's state: one would outlive the owner's fix. A quarantine GitHub refuses
# still leaves the test out of THIS run; the next red on it tries again. The
# write is committed as GATE_AUTHOR_EMAIL, the one address the register
# believes a `quarantined=` line from; with that setting empty nothing is
# written, because nothing written would be believed.

RED_TRIAGE_ROWS="tools/test_register/_rows.py"

# Every quarantine the gate honours: in main's rows (the clone at REPO), and
# only the lines the gate's own address added. Never the tested tree's rows: a
# commit that broke a test could otherwise quarantine it in the same commit and
# ship green.
_quarantine_list() {
    ( cd "${REPO:-.}" && python3 -m tools.test_register --quarantined ) 2>/dev/null \
        | sed '/^$/d' | LC_ALL=C sort -u
    return 0
}

# 0 when one triage run answered: it passed, or it said no and named files.
_red_run_answered() {
    local rc="$1" out="$2"
    [ "$rc" -eq 0 ] && return 0
    [ "$rc" -ge 1 ] && [ "$rc" -le 4 ] && [ -s "$out" ] && return 0
    return 1
}

# The test files a run's output names on its FAILED and ERROR lines, only those
# that are files in commit <sha>, asked of git because the tree that ran is
# inside a gate Job.
_red_failing_files() {
    local output="$1" sha="$2" path
    grep -E '^(FAILED|ERROR) ' "$output" 2>/dev/null \
        | sed -E 's/^(FAILED|ERROR) //; s/::.*//; s/ - .*//; s/ .*//' \
        | LC_ALL=C sort -u \
        | while IFS= read -r path; do
            [ -n "$path" ] && git -C "${REPO:-.}" cat-file -e "$sha:$path" 2>/dev/null \
                && printf '%s\n' "$path"
        done
    return 0
}

# 0 when the last good tree cannot speak for <path>: it does not have the file,
# or <sha> changed it. A diff git cannot answer counts as changed.
_red_test_is_the_commits() {
    local good="$1" sha="$2" path="$3"
    git -C "${REPO:-.}" cat-file -e "$good:$path" 2>/dev/null || return 0
    [ -n "$sha" ] || return 1
    git -C "${REPO:-.}" diff --quiet "$good" "$sha" -- "$path" 2>/dev/null && return 1
    return 0
}

# Sort one red. <good> is the last good commit, <failing> the list of test
# files the red run named, <sha> the commit that went red. Sets
# `red_triage_kind` (commit, test or setup) and `red_triage_tests`
# (`<test>\t<reason>` per file that leaves the gate).
_red_triage() {
    local good="$1" failing="$2" sha="${3:-}" work rc rerun="null" known="null" path answer
    red_triage_kind="commit"
    red_triage_tests=()
    [ -s "$failing" ] || return 0
    work="$(mktemp -d -t red-triage-XXXXXX)" || return 0
    : > "$work/new"
    _red_triage_run same "$failing" "$work/again"
    rc=$?
    if _red_run_answered "$rc" "$work/again"; then
        rerun="$work/again"
        grep -Fxf "$work/again" "$failing" > "$work/still" 2>/dev/null || : > "$work/still"
        if [ ! -s "$work/still" ]; then
            : > "$work/good"; known="$work/good"
        elif [ -n "$good" ]; then
            while IFS= read -r path; do
                _red_test_is_the_commits "$good" "$sha" "$path" && printf '%s\n' "$path"
            done < "$work/still" > "$work/new"
            grep -vxFf "$work/new" "$work/still" > "$work/old" 2>/dev/null || : > "$work/old"
            if [ -s "$work/old" ]; then
                _red_triage_run good "$work/old" "$work/good"
                rc=$?
                _red_run_answered "$rc" "$work/good" && known="$work/good"
            else
                : > "$work/good"; known="$work/good"
            fi
        fi
    fi
    if answer="$(python3 -c '
import json, sys
def files(path):
    if path == "null":
        return None
    with open(path, encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]
failing, rerun, good, new = sys.argv[1:5]
print(json.dumps({"failing": files(failing), "rerun_failing": files(rerun),
                  "good_failing": files(good), "new_files": files(new)}))' \
            "$failing" "$rerun" "$known" "$work/new" \
            | ( cd "${REPO:-.}" && python3 -m tools.red_triage ) 2>/dev/null )" && [ -n "$answer" ]; then
        red_triage_kind="$(printf '%s\n' "$answer" | head -1)"
        mapfile -t red_triage_tests < <(printf '%s\n' "$answer" | sed -n 's/^quarantine\t//p')
    else
        log "[triage] the sorter could not run, so this red stays the commit's"
    fi
    rm -rf "$work"
    return 0
}

# Quarantine one test file: the owner's issue first, then the row on main, so
# the row can name the issue. Sets `red_quarantine_issue` (empty when no issue
# could be opened). The caller leaves the test out of this run either way.
# <evidence>, optional, is the red run's output; its lines about this test go
# in the issue.
_red_quarantine() {
    local test="$1" reason="$2" sha="$3" evidence="${4:-}" work issue
    red_quarantine_issue=""
    if ! _gh_ready; then
        log "[triage] no DEPLOY_STATUS_TOKEN or GH_REPO_SLUG: $test is left out of this run only, and no issue was opened"
        return 0
    fi
    work="$(mktemp -d -t red-quarantine-XXXXXX)" || return 0
    if [ -n "$evidence" ]; then
        grep -F "$test" "$evidence" 2>/dev/null | grep -E '^(FAILED|ERROR) ' | head -20 > "$work/failures"
    fi
    if ! ( cd "${REPO:-.}" && python3 -m tools.test_register --quarantine-issue "$test" --commit "$sha" \
            --reason "$reason" ${evidence:+--failures "$work/failures"} ) > "$work/issue.json" 2>/dev/null; then
        log "[triage] the register could not write the issue for $test; it is left out of this run only"
        rm -rf "$work"
        return 0
    fi
    issue="$(_red_open_issue "$work/issue.json")"
    if [ -z "$issue" ]; then
        log "[triage] no issue could be opened for $test; it is left out of this run, and the next red on it tries again"
        rm -rf "$work"
        return 0
    fi
    red_quarantine_issue="$issue"
    _red_publish_quarantine "$test" "$reason" "$sha" "$issue" "$work" \
        || log "[triage] the quarantine of $test could not be committed to main; it is left out of this run, and the next red on it tries again"
    rm -rf "$work"
    return 0
}

# Print the number of the open issue the register's JSON titles, opening it
# (assigned, labelled, nested under its parent) when none is open yet.
_red_open_issue() {
    local spec="$1" title answer number id parent body
    title="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["title"])' "$spec" 2>/dev/null)" || return 0
    [ -n "$title" ] || return 0
    answer="$(_gh_api GET "/issues?state=open&per_page=100")"
    number="$(printf '%s\n' "$answer" | sed '$d' | TITLE="$title" python3 -c '
import json, os, sys
try:
    issues = json.load(sys.stdin)
except ValueError:
    raise SystemExit(0)
for issue in issues:
    if issue.get("title") == os.environ["TITLE"] and "pull_request" not in issue:
        print(issue["number"])
        break' 2>/dev/null)"
    if [ -n "$number" ]; then
        printf '%s\n' "$number"
        return 0
    fi
    body="$(python3 -c '
import json, sys
spec = json.load(open(sys.argv[1]))
issue = {"title": spec["title"], "body": spec["body"], "labels": spec.get("labels") or []}
if spec.get("assignee"):
    issue["assignees"] = [spec["assignee"]]
print(json.dumps(issue))' "$spec" 2>/dev/null)" || return 0
    answer="$(_gh_api POST "/issues" "$body")"
    [ "$(printf '%s\n' "$answer" | tail -1)" = "201" ] || return 0
    read -r number id < <(printf '%s\n' "$answer" | sed '$d' \
        | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["number"], d["id"])' 2>/dev/null)
    case "$number" in ''|*[!0-9]*) return 0 ;; esac
    parent="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("parent") or "")' "$spec" 2>/dev/null)"
    if [ -n "$parent" ] && [ -n "$id" ]; then
        [ "$(_gh_api POST "/issues/$parent/sub_issues" "{\"sub_issue_id\": $id}" | tail -1)" = "201" ] \
            || log "[triage] issue #$number could not be nested under #$parent"
    fi
    printf '%s\n' "$number"
}

# Add `quarantined=` to the test's row on main through the contents API, as
# GATE_AUTHOR_EMAIL. Retried on a conflict: a person may have pushed to the
# rows a second earlier.
_red_publish_quarantine() {
    local test="$1" reason="$2" sha="$3" issue="$4" work="$5" attempt blob payload answer
    if [ -z "${GATE_AUTHOR_EMAIL:-}" ]; then
        log "[triage] GATE_AUTHOR_EMAIL is empty, so no quarantine would be believed; $test is left out of this run only"
        return 1
    fi
    for attempt in 1 2 3; do
        answer="$(_gh_api GET "/contents/$RED_TRIAGE_ROWS?ref=main")"
        [ "$(printf '%s\n' "$answer" | tail -1)" = "200" ] || continue
        printf '%s\n' "$answer" | sed '$d' > "$work/meta"
        blob="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha"])' "$work/meta" 2>/dev/null)"
        python3 -c 'import base64,json,sys; sys.stdout.buffer.write(base64.b64decode(json.load(open(sys.argv[1]))["content"]))' \
            "$work/meta" > "$work/rows" 2>/dev/null || continue
        ( cd "${REPO:-.}" && python3 -m tools.test_register --quarantine "$test" --commit "$sha" \
            --reason "$reason" --issue "$issue" --since "$(date -u +%Y-%m-%d)" --from "$work/rows" ) \
            > "$work/new" 2>/dev/null || return 1
        cmp -s "$work/rows" "$work/new" && return 0
        payload="$(python3 -c '
import base64, json, os, sys
message, blob, path = sys.argv[1], sys.argv[2], sys.argv[3]
person = {"name": "deploy gate", "email": os.environ["GATE_AUTHOR_EMAIL"]}
print(json.dumps({"message": message, "sha": blob, "branch": "main", "committer": person, "author": person,
                  "content": base64.b64encode(open(path, "rb").read()).decode()}))' \
            "test_register: quarantine ${test##*/} (#$issue)

The deploy gate found $test to be the wrong test at ${sha:0:12}: it $reason. It leaves the gate until its owner fixes it under #$issue." \
            "$blob" "$work/new")" || continue
        case "$(_gh_api PUT "/contents/$RED_TRIAGE_ROWS" "$payload" | tail -1)" in
            200|201)
                log "[triage] $test quarantined on main under #$issue"
                return 0 ;;
        esac
    done
    return 1
}

# Sourced into a shell that may have `set -e` on: end on a command that succeeds.
true
