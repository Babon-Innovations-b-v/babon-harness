#!/bin/bash
# The branch gate: verifies the eject's hand-back pull requests, and is the
# only thing that marks one safe to merge.
#
# The eject (steps/eject_body.sh) puts a rejected commit's work on a branch
# auto-eject/<sha12> and opens a DRAFT pull request. Every 15 minutes this job
# lists the open pull requests whose head is such a branch IN THIS REPOSITORY
# (anyone can name a branch auto-eject/anything, and this job runs the suite of
# whatever it tests), runs the deploy gate's suite against GitHub's merge of the
# branch into main (refs/pull/<N>/merge), posts `vm/branch-gate`, and on a green
# marks the pull request ready for review. What blocks a merge is the DRAFT
# state, not a ruleset: everybody pushes main directly, and a required status
# would stop all work.
#
# The draft is a block, not a starting position: an open hand-back that is
# ready for review with no `success` for its CURRENT head is put back to a
# draft, with a comment saying why. Even marked ready, the pull request is not
# to be merged: the hand-back text says to squash the fix onto main as one
# commit, because the branch opens with the tree the gate refused.
#
# Containment: never part of the deploy cycle. Own timer, own lock, own clone
# ($HARNESS_ROOT/branch-gate-repo), and it refuses (never falls back) if pointed
# at the cycle's lock or clone. The suite runs in a `git archive` export of the
# merge ref, never in the clone, and is deliberately NOT narrowed: a green
# branch must mean what a green main means. `nice 19`, idle IO.
#
# Three states, `error` never collapsed into `success`: success (ran, passed),
# failure (ran, rc 1 to 5), error (could not run). The head sha is re-read just
# before every post, and nothing is posted when it moved.
#
# FAILURE POLICY: every path exits 0 except a refused configuration.
# BRANCH_GATE_ENABLED=0 posts nothing, so every hand-back stays a draft.

set -uo pipefail
BRANCH_GATE_ENABLED="${BRANCH_GATE_ENABLED:-1}"
BRANCH_GATE_DRAFT_BLOCK="${BRANCH_GATE_DRAFT_BLOCK:-1}"
BRANCH_GATE_PYTEST_WORKERS="${BRANCH_GATE_PYTEST_WORKERS:-0}"
BRANCH_GATE_TIMEOUT="${BRANCH_GATE_TIMEOUT:-2400}"
BRANCH_GATE_MAX_BRANCHES="${BRANCH_GATE_MAX_BRANCHES:-3}"
BRANCH_GATE_MIN_FREE_MB="${BRANCH_GATE_MIN_FREE_MB:-4096}"
BRANCH_GATE_REF_PREFIX="${BRANCH_GATE_REF_PREFIX:-auto-eject/}"
BRANCH_GATE_SYNC_TIMEOUT="${BRANCH_GATE_SYNC_TIMEOUT:-1200}"
SELF="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$SELF/../steps/doors.sh"
BRANCH_GATE_DEPLOY_REPO="${BRANCH_GATE_DEPLOY_REPO:-$HARNESS_ROOT/repo}"
harness_load_config "$BRANCH_GATE_DEPLOY_REPO"
GH_REPO_SLUG="${BRANCH_GATE_REPO_SLUG:-$(harness_repo_slug "$BRANCH_GATE_DEPLOY_REPO")}"
GATE_UV_SYNC_ARGS="${GATE_UV_SYNC_ARGS:---all-packages --all-extras --all-groups}"
BRANCH_GATE_CONTEXT="${BRANCH_GATE_CONTEXT:-vm/branch-gate}"
BRANCH_GATE_CLONE="${BRANCH_GATE_CLONE:-$HARNESS_ROOT/branch-gate-repo}"
BRANCH_GATE_TREE_ROOT="${BRANCH_GATE_TREE_ROOT:-$HARNESS_ROOT/branch-gate-tree}"
BRANCH_GATE_DEPLOY_LOCK="${BRANCH_GATE_DEPLOY_LOCK:-/tmp/harness-deploy.lock}"
BRANCH_GATE_LOCK="${BRANCH_GATE_LOCK:-/tmp/harness-branch-gate.lock}"
_bg_log() {
    printf '[%s] [branch-gate] %s\n' "$(date -Iseconds)" "$*" >&2
}
_bg_real_path() {
    realpath -m -- "$1" 2>/dev/null || printf '%s' "$1"
}
_bg_remote_url() {
    printf 'https://x-access-token:%s@github.com/%s.git' \
        "${DEPLOY_STATUS_TOKEN:-}" "$GH_REPO_SLUG"
}
_bg_load_token() {
    return 0
}
_bg_api_get() {
    local path="$1"
    local token="${DEPLOY_STATUS_TOKEN:-}"
    [ -z "$token" ] && return 1
    curl -sS -m 20 -f \
        -H "Authorization: Bearer $token" \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/$GH_REPO_SLUG$path"
}
_bg_api_post_status() {
    local sha="$1" state="$2" description="$3" target_url="$4"
    local token="${DEPLOY_STATUS_TOKEN:-}"
    local payload
    [ -z "$token" ] && return 1
    [ -z "$sha" ] && return 1
    description="$(printf '%.138s' "$description")"
    payload="$(python3 -c 'import json,sys; print(json.dumps({"state": sys.argv[1], "context": sys.argv[2], "description": sys.argv[3], "target_url": sys.argv[4]}))' \
        "$state" "$BRANCH_GATE_CONTEXT" "$description" "$target_url")" || return 1
    curl -sS -m 20 -f -o /dev/null \
        -X POST \
        -H "Authorization: Bearer $token" \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/$GH_REPO_SLUG/statuses/$sha" \
        -d "$payload"
}
_bg_api_mark_ready() {
    local node_id="$1"
    local token="${DEPLOY_STATUS_TOKEN:-}"
    local payload response
    [ -z "$token" ] && return 1
    [ -z "$node_id" ] && return 1
    payload="$(python3 -c 'import json,sys
query = "mutation MarkReady($id: ID!) { markPullRequestReadyForReview(input: {pullRequestId: $id}) { pullRequest { number isDraft } } }"
print(json.dumps({"query": query, "variables": {"id": sys.argv[1]}}))' "$node_id")" || return 1
    response="$(curl -sS -m 20 -f \
        -X POST \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        "https://api.github.com/graphql" \
        -d "$payload")" || return 1
    printf '%s' "$response" | python3 -c 'import json,sys
try:
    body = json.load(sys.stdin)
except ValueError:
    raise SystemExit(1)
raise SystemExit(1 if body.get("errors") else 0)'
}
_bg_api_convert_to_draft() {
    local node_id="$1"
    local token="${DEPLOY_STATUS_TOKEN:-}"
    local payload response
    [ -z "$token" ] && return 1
    [ -z "$node_id" ] && return 1
    payload="$(python3 -c 'import json,sys
query = "mutation ToDraft($id: ID!) { convertPullRequestToDraft(input: {pullRequestId: $id}) { pullRequest { number isDraft } } }"
print(json.dumps({"query": query, "variables": {"id": sys.argv[1]}}))' "$node_id")" || return 1
    response="$(curl -sS -m 20 -f \
        -X POST \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        "https://api.github.com/graphql" \
        -d "$payload")" || return 1
    printf '%s' "$response" | python3 -c 'import json,sys
try:
    body = json.load(sys.stdin)
except ValueError:
    raise SystemExit(1)
raise SystemExit(1 if body.get("errors") else 0)'
}
_bg_comment_redrafted() {
    local number="$1"
    local token="${DEPLOY_STATUS_TOKEN:-}"
    local payload
    [ -z "$token" ] && return 1
    payload="$(python3 -c 'import json
print(json.dumps({"body": (
    "This hand-back was marked ready for review before anything had verified "
    "it, so it has been put back to a draft.\n\n"
    "The branch carries the tree the deploy gate rejected, byte for byte. "
    "Merging it as it stands puts that tree back on main and the deploy queue "
    "blocks on it again, and the eject will not take back its own re-land, so a "
    "person then has to move the deploy bookmark by hand.\n\n"
    "Fix the failure on this branch and push. The branch gate runs the deploy "
    "gate suite against the merge of this branch into main every 15 minutes and "
    "marks it ready by itself once it passes. Then land it on main as ONE commit "
    "(squash), never with the merge button.\n\n"
    "BRANCH_GATE_DRAFT_BLOCK=0 on the deploy server turns this off deliberately."
)}))')" || return 1
    curl -sS -m 20 -f -o /dev/null \
        -X POST \
        -H "Authorization: Bearer $token" \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com/repos/$GH_REPO_SLUG/issues/$number/comments" \
        -d "$payload"
}
_bg_hand_backs() {
    local body
    body="$(_bg_api_get "/pulls?state=open&per_page=100")" || return 1
    printf '%s' "$body" | python3 -c 'import json,sys
prefix = sys.argv[1]
slug = sys.argv[2]
try:
    pulls = json.load(sys.stdin)
except ValueError:
    raise SystemExit(1)
if not isinstance(pulls, list):
    raise SystemExit(1)
rows = []
for pull in pulls:
    head = pull.get("head") or {}
    ref = str(head.get("ref") or "")
    if not ref.startswith(prefix):
        continue
    if str((head.get("repo") or {}).get("full_name") or "") != slug:
        continue
    number = pull.get("number")
    sha = head.get("sha") or ""
    node = pull.get("node_id") or ""
    if number is None or not sha or not node:
        continue
    draft = "draft" if pull.get("draft", True) else "ready"
    rows.append((int(number), ref, sha, node, draft))
for number, ref, sha, node, draft in sorted(rows):
    print("\t".join([str(number), ref, sha, node, draft]))' "$BRANCH_GATE_REF_PREFIX" "$GH_REPO_SLUG"
}
_bg_decided_state() {
    local body
    body="$(_bg_api_get "/commits/$1/statuses?per_page=100")" || return 0
    printf '%s' "$body" | python3 -c 'import json,sys
context = sys.argv[1]
try:
    rows = json.load(sys.stdin)
except ValueError:
    raise SystemExit(0)
if not isinstance(rows, list):
    raise SystemExit(0)
for row in rows:
    if row.get("context") == context:
        print(row.get("state") or "")
        break' "$BRANCH_GATE_CONTEXT"
}
_bg_pull_head_sha() {
    local body
    body="$(_bg_api_get "/pulls/$1")" || return 0
    printf '%s' "$body" | python3 -c 'import json,sys
try:
    pull = json.load(sys.stdin)
except ValueError:
    raise SystemExit(0)
if pull.get("state") != "open":
    raise SystemExit(0)
print((pull.get("head") or {}).get("sha") or "")'
}
_bg_free_mb() {
    local probe="$1"
    while [ -n "$probe" ] && [ "$probe" != "/" ] && [ ! -d "$probe" ]; do
        probe="$(dirname "$probe")"
    done
    df -Pm "$probe" 2>/dev/null | awk 'NR == 2 { print $4 }'
}
_bg_clone_ready() {
    local clone deploy
    clone="$(_bg_real_path "$BRANCH_GATE_CLONE")"
    deploy="$(_bg_real_path "$BRANCH_GATE_DEPLOY_REPO")"
    if [ "$clone" = "$deploy" ] \
       || [ "${clone#"$deploy"/}" != "$clone" ] \
       || [ "${deploy#"$clone"/}" != "$deploy" ]; then
        _bg_log "REFUSING: BRANCH_GATE_CLONE ($BRANCH_GATE_CLONE) is the deploy clone ($BRANCH_GATE_DEPLOY_REPO), or one contains the other. This job must never work in the tree the deploy cycle reads."
        return 1
    fi
    [ -d "$BRANCH_GATE_CLONE/.git" ] && return 0
    mkdir -p "$BRANCH_GATE_CLONE" 2>/dev/null || return 1
    git init --quiet -b branch-gate "$BRANCH_GATE_CLONE" || return 1
    _bg_log "created the branch gate repository at $BRANCH_GATE_CLONE"
    return 0
}
_bg_fetch_merge_ref() {
    local number="$1"
    ( cd "$BRANCH_GATE_CLONE" || exit 1
      nice -n 19 ionice -c 3 git fetch --quiet --force "$(_bg_remote_url)" \
          "+refs/pull/$number/merge:refs/branch-gate/pr-$number" ) >&2
}
_bg_merge_ref_covers_head() {
    local number="$1" head_sha="$2"
    ( cd "$BRANCH_GATE_CLONE" || exit 1
      git merge-base --is-ancestor "$head_sha" "refs/branch-gate/pr-$number" ) 2>/dev/null
}
_bg_checkout_merge_ref() {
    local number="$1"
    ( cd "$BRANCH_GATE_CLONE" || exit 1
      git checkout --quiet --detach "refs/branch-gate/pr-$number" \
          && git clean -qfdx -e .venv ) >&2
}
_bg_export_merge_tree() {
    local number="$1" sha="$2" tree
    [ -n "$sha" ] || return 1
    mkdir -p "$BRANCH_GATE_TREE_ROOT" 2>/dev/null || return 1
    find "$BRANCH_GATE_TREE_ROOT" -maxdepth 1 -mindepth 1 -type d \
        -exec rm -rf {} + 2>/dev/null || true
    tree="$BRANCH_GATE_TREE_ROOT/$sha"
    mkdir -p "$tree" 2>/dev/null || return 1
    if ! ( cd "$BRANCH_GATE_CLONE" || exit 1
           git archive --format=tar "refs/branch-gate/pr-$number" \
               | tar -x -C "$tree" ) >&2; then
        rm -rf "$tree" 2>/dev/null || true
        return 1
    fi
    [ -n "$(ls -A "$tree" 2>/dev/null)" ] || { rm -rf "$tree" 2>/dev/null; return 1; }
    printf '%s' "$tree"
}
_bg_environment_ready() {
    local hash_file="$BRANCH_GATE_CLONE/.git/branch-gate-lock-hash" lock_hash
    lock_hash="$( cd "$BRANCH_GATE_CLONE" 2>/dev/null \
        && cat uv.lock pyproject.toml 2>/dev/null \
        | sha256sum | cut -d' ' -f1 )"
    if ( cd "$BRANCH_GATE_CLONE" 2>/dev/null && [ -x .venv/bin/pytest ] \
            && .venv/bin/pytest --version >/dev/null 2>&1 ) \
       && [ -n "$lock_hash" ] && [ "$lock_hash" = "$(cat "$hash_file" 2>/dev/null)" ]; then
        _bg_log "environment unchanged since the last tick, skipping uv sync"
        return 0
    fi
    if ( cd "$BRANCH_GATE_CLONE" || exit 1
         nice -n 19 ionice -c 3 timeout "$BRANCH_GATE_SYNC_TIMEOUT" \
             uv sync $GATE_UV_SYNC_ARGS ) >&2; then
        printf '%s\n' "$lock_hash" > "$hash_file" 2>/dev/null || true
        return 0
    fi
    _bg_log "uv sync failed in $BRANCH_GATE_CLONE, so there is no environment to run the suite in"
    return 1
}
_bg_ignore_flags() {
    grep -oE -- '--ignore=[^[:space:]]+' "$1" 2>/dev/null
}
_bg_gate_step_path() {
    printf '%s/infra/auto-deploy/steps/40-gate.sh' "${1:-$BRANCH_GATE_CLONE}"
}
_bg_run_suite() {
    local run_log="$1" tree="$2"
    local step ignore_args=() flag worker_args=()
    [ "${BRANCH_GATE_PYTEST_WORKERS:-0}" != "0" ] && worker_args=(-n "$BRANCH_GATE_PYTEST_WORKERS" --dist loadfile)
    [ -n "$tree" ] || return 126
    step="$(_bg_gate_step_path "$tree")"
    while IFS= read -r flag; do
        [ -n "$flag" ] && ignore_args+=("$flag")
    done < <(_bg_ignore_flags "$step")
    if [ "${#ignore_args[@]}" -eq 0 ]; then
        _bg_log "no --ignore flags in $step, refusing to run a suite that is not the deploy gate's"
        return 125
    fi
    ( cd "$tree" || exit 126
      env -i \
          HOME="$HOME" \
          PATH="/usr/local/bin:/usr/bin:/bin" \
          LANG=C.UTF-8 \
          nice -n 19 ionice -c 3 \
          timeout "$BRANCH_GATE_TIMEOUT" "$BRANCH_GATE_CLONE/.venv/bin/pytest" -q --tb=no -rf \
          ${worker_args[@]+"${worker_args[@]}"} \
          "${ignore_args[@]}" ) > "$run_log" 2>&1
}
_bg_verdict_state() {
    case "$1" in
        0) printf 'success' ;;
        1|2|3|4|5) printf 'failure' ;;
        *) printf 'error' ;;
    esac
}
_bg_first_failure() {
    grep -m1 '^FAILED ' "$1" 2>/dev/null | cut -c1-80
}
_bg_verdict_description() {
    local rc="$1" run_log="$2" first
    case "$rc" in
        0)   printf 'the deploy gate suite passed on the merge of this branch into main' ;;
        1)   first="$(_bg_first_failure "$run_log")"
             printf 'the suite failed on the merge of this branch into main: %s' \
                 "${first:-see journalctl -u harness-branch-gate}" ;;
        2)   printf 'the suite could not collect this merge tree (rc=2), so its code does not load' ;;
        3)   printf 'pytest hit an internal error on this merge tree (rc=3)' ;;
        4)   printf 'pytest refused this run as a usage error (rc=4)' ;;
        5)   printf 'the suite collected no test at all (rc=5), which is not a pass' ;;
        124) printf 'the run did not finish inside %ss, so there is no verdict about this branch' \
                 "$BRANCH_GATE_TIMEOUT" ;;
        125) printf 'the branch gate could not read the deploy gate ignore list, so it ran no suite' ;;
        126|127) printf 'no runnable pytest in the branch gate environment, so no suite ran' ;;
        137) printf 'the run was killed before it could finish (out of memory), so there is no verdict' ;;
        *)   printf 'the branch gate could not run the suite (rc=%s), so there is no verdict' "$rc" ;;
    esac
}
_bg_report() {
    local number="$1" tested_sha="$2" state="$3" description="$4" live_sha
    live_sha="$(_bg_pull_head_sha "$number")"
    if [ -z "$live_sha" ]; then
        _bg_log "pr $number: no open head to report on any more, posting no $state status"
        return 1
    fi
    if [ "$live_sha" != "$tested_sha" ]; then
        _bg_log "pr $number: head moved ${tested_sha:0:12} -> ${live_sha:0:12} during the tick, posting nothing; the next tick verifies the new head"
        return 1
    fi
    if ! _bg_api_post_status "$tested_sha" "$state" "$description" \
            "https://github.com/$GH_REPO_SLUG/pull/$number"; then
        _bg_log "pr $number: could not post the $state status on ${tested_sha:0:12}"
        return 1
    fi
    _bg_log "pr $number: $state on ${tested_sha:0:12}, $description"
    return 0
}
_bg_mark_ready() {
    local number="$1" node_id="$2"
    if _bg_api_mark_ready "$node_id"; then
        _bg_log "pr $number: green, marked ready for review"
        return 0
    fi
    _bg_log "pr $number: green, but marking it ready for review failed, so it stays a draft"
    return 1
}
_bg_verify_one() {
    local number="$1" head_ref="$2" head_sha="$3" node_id="$4"
    local free_mb rc state description run_log tree
    _bg_log "pr $number: verifying $head_ref at ${head_sha:0:12}"
    free_mb="$(_bg_free_mb "$BRANCH_GATE_CLONE")"
    case "$free_mb" in
        ''|*[!0-9]*) free_mb="" ;;
    esac
    if [ -z "$free_mb" ] || [ "$free_mb" -lt "$BRANCH_GATE_MIN_FREE_MB" ]; then
        _bg_report "$number" "$head_sha" "error" \
            "no room to verify this branch: ${free_mb:-unreadable} MB free against a ${BRANCH_GATE_MIN_FREE_MB} MB floor"
        return 0
    fi
    if ! _bg_clone_ready; then
        _bg_report "$number" "$head_sha" "error" \
            "the branch gate has no repository to verify in; see journalctl -u harness-branch-gate"
        return 0
    fi
    if ! _bg_fetch_merge_ref "$number"; then
        _bg_report "$number" "$head_sha" "error" \
            "this branch does not merge cleanly into main, so there is no merge tree to verify"
        return 0
    fi
    if ! _bg_merge_ref_covers_head "$number" "$head_sha"; then
        _bg_report "$number" "$head_sha" "error" \
            "the branch moved while this tick was starting; the next tick verifies the new head"
        return 0
    fi
    if ! _bg_checkout_merge_ref "$number"; then
        _bg_report "$number" "$head_sha" "error" \
            "the branch gate could not check out the merge tree, so no suite ran"
        return 0
    fi
    if ! _bg_environment_ready; then
        _bg_report "$number" "$head_sha" "error" \
            "the branch gate could not build an environment for this tree, so no suite ran"
        return 0
    fi
    if ! tree="$(_bg_export_merge_tree "$number" "$head_sha")" || [ -z "$tree" ]; then
        _bg_report "$number" "$head_sha" "error" \
            "the branch gate could not export the merge tree, so no suite ran"
        return 0
    fi
    if ! run_log="$(mktemp -t branch-gate-XXXXXX.log)"; then
        _bg_report "$number" "$head_sha" "error" \
            "the branch gate could not open a run log, so no suite ran"
        return 0
    fi
    _bg_run_suite "$run_log" "$tree"
    rc=$?
    state="$(_bg_verdict_state "$rc")"
    description="$(_bg_verdict_description "$rc" "$run_log")"
    _bg_log "pr $number: pytest rc=$rc -> $state"
    tail -n 20 "$run_log" >&2 2>/dev/null
    if _bg_report "$number" "$head_sha" "$state" "$description" \
       && [ "$state" = "success" ] && [ "$BRANCH_GATE_DRAFT_BLOCK" = "1" ]; then
        _bg_mark_ready "$number" "$node_id"
    fi
    rm -f "$run_log"
    rm -rf "$tree" 2>/dev/null || true
    return 0
}
_bg_cycle() {
    local rows verified=0 number head_ref head_sha node_id decided
    if [ "$BRANCH_GATE_ENABLED" != "1" ]; then
        _bg_log "disabled (BRANCH_GATE_ENABLED != 1), nothing verified, every hand-back stays a draft"
        return 0
    fi
    _bg_load_token
    if ! rows="$(_bg_hand_backs)"; then
        if [ -z "${DEPLOY_STATUS_TOKEN:-}" ]; then
            _bg_log "no DEPLOY_STATUS_TOKEN or no repository in .claude/project.json, nothing verified this tick, every hand-back stays a draft"
        else
            _bg_log "GitHub would not list the open pull requests, nothing verified this tick"
        fi
        return 0
    fi
    if [ -z "$rows" ]; then
        _bg_log "no open ${BRANCH_GATE_REF_PREFIX}* hand-back to verify"
        return 0
    fi
    while IFS=$'\t' read -r number head_ref head_sha node_id draft_state; do
        [ -z "$number" ] && continue
        if [ "$verified" -ge "$BRANCH_GATE_MAX_BRANCHES" ]; then
            _bg_log "pr $number: $BRANCH_GATE_MAX_BRANCHES branch(es) verified this tick, the rest wait for the next one"
            break
        fi
        decided="$(_bg_decided_state "$head_sha")"
        if [ "${BRANCH_GATE_DRAFT_BLOCK:-1}" = "1" ] \
                && [ "$draft_state" = "ready" ] && [ "$decided" != "success" ]; then
            if _bg_api_convert_to_draft "$node_id"; then
                _bg_log "pr $number: marked ready with no green branch-gate verdict for ${head_sha:0:12}; put back to a draft"
                _bg_comment_redrafted "$number" \
                    || _bg_log "pr $number: put back to a draft, but the comment saying why could not be posted"
            else
                _bg_log "pr $number: marked ready with no green verdict and it could NOT be put back to a draft; this one can be merged unverified"
            fi
        fi
        case "$decided" in
            success|failure)
                _bg_log "pr $number: ${head_sha:0:12} already carries a $decided branch-gate verdict, not re-running"
                continue
                ;;
        esac
        verified=$(( verified + 1 ))
        _bg_verify_one "$number" "$head_ref" "$head_sha" "$node_id"
    done <<< "$rows"
    _bg_log "tick done, $verified branch(es) verified"
    return 0
}
_bg_lock_path() {
    if [ "$(_bg_real_path "$BRANCH_GATE_LOCK")" = "$(_bg_real_path "$BRANCH_GATE_DEPLOY_LOCK")" ]; then
        _bg_log "REFUSING: BRANCH_GATE_LOCK ($BRANCH_GATE_LOCK) is the deploy cycle's own lock ($BRANCH_GATE_DEPLOY_LOCK). Holding it would stop deploys."
        return 1
    fi
    printf '%s' "$BRANCH_GATE_LOCK"
}
_bg_main() {
    local lock
    lock="$(_bg_lock_path)" || return 1
    exec 8>"$lock" || { _bg_log "cannot open $lock"; return 1; }
    if ! flock -n 8; then
        _bg_log "another tick still holds $lock, skipping this one"
        return 0
    fi
    _bg_cycle
}
_bg_main

