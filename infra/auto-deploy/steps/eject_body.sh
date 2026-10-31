#!/bin/bash
# The eject's body: how a commit the gate rejected comes off main and goes back
# to its author, in one copy.
#
# OFF BY DEFAULT. EJECT_ENABLED=0 (the default) decides nothing at all: no
# claim, no revert, no branch, no issue. A red then holds the bookmark and step
# 90 alerts that the queue is frozen until a person fixes or reverts the commit.
# EJECT_ENABLED=1 arms it; DEPLOY_STATUS_TOKEN then needs contents write and
# pull requests. EJECT_DRY_RUN=1 (with EJECT_ENABLED=0) opens the hand-back
# issue saying what it WOULD have done and pushes nothing, so the call can be
# judged before it is armed.
#
# NOT A STEP. It defines functions and defaulted constants, runs nothing, and
# ends in `true`. Two callers decide about different reds: steps/88-eject.sh for
# the reds the cycle sees (the commit it gates, a build or boot it could not
# do), commit_gate/eject.sh for the reds a verifying run produced about one
# commit. The decision is theirs; the mechanism is here, once, because a fix in
# one copy and not the other reverts somebody wrongly.
#
# THE SEAM. The caller defines, before sourcing: `log`, the gh_* doors from
# doors.sh, and two hooks: `_eject_arm_preconditions_hold <trigger>` (the arm's
# own refusals, setting `eject_reason`) and `_eject_evidence_paths` (which tail
# and scope files describe this commit). And sets REPO, STATE_DIR, GH_REPO_SLUG,
# GATE_VERDICT_DIR, LAST_SHA_FILE, LOG; before deciding also NEW_SHA, OLD_SHA,
# CHANGED, gate_red, gate_red_reason, BOOT_FAILED_SERVICES, BUILD_RED_SERVICES,
# queue_depth and commits_ahead.
#
# WHAT BOUNDS IT, each refusal one word in `eject_reason`:
#   - It takes back ONE commit, never a range it cannot name: two routes only.
#     restore: main is still at NEW_SHA, so revert OLD_SHA..NEW_SHA and push only
#     a tree byte-identical to OLD_SHA's (`git write-tree` equality). lift: main
#     moved and the range is one commit, so revert that commit alone, which must
#     apply cleanly and remove something. Anything else is `main_moved`. There
#     is deliberately no wider route: reverting a whole queue buys liveness with
#     commits nobody objected to. Both push a computed sha, never HEAD.
#   - The parent must be known good (a red parent means this tree carries
#     somebody else's failure): `parent_red`, `parent_unverified`.
#   - `self_authored`: a commit carrying the eject's own committer address or an
#     `Auto-Eject:` trailer is never reverted, so it cannot revert its own revert.
#   - One WRITE per sha, ever: a `mkdir` claim in $STATE_DIR/ejected that fails
#     CLOSED, released only by an attempt that pushed nothing.
#   - EJECT_COOLDOWN_SECONDS between decisions, as a rate and not a budget.
#   - EJECT_PROTECTED_PATHS, an extended regex of paths it may never revert.
#
# THE HAND-BACK is a branch auto-eject/<sha12> carrying the rejected work byte
# for byte, and a DRAFT pull request; the branch gate (../branch_gate/) marks it
# ready once its merge with main passes the suite. Its text says: do not press
# merge. The branch opens with the tree the gate refused, and the gate judges
# every commit against its own tree, so a merge puts a permanently red commit on
# main. Fix it on the branch, then squash it onto main as ONE commit with
# "Closes #<the PR>". Every way the pull request can fail falls back to an issue.

_eject_body_missing=""
for _eject_body_helper in \
    log gh_commit_author_login gh_email_is_not_a_person gh_login_for_email \
    gh_login_is_assignable gh_issue_create gh_pull_request_create \
    _eject_arm_preconditions_hold _eject_evidence_paths
do
    declare -F "$_eject_body_helper" >/dev/null 2>&1 \
        || _eject_body_missing="$_eject_body_missing $_eject_body_helper"
done
unset _eject_body_helper
if [ -n "$_eject_body_missing" ]; then
    printf '[eject] the eject body was sourced without:%s; defining nothing\n' "$_eject_body_missing" >&2
    unset _eject_body_missing
    return 1
fi
unset _eject_body_missing

EJECT_DECISION_DIR="${EJECT_DECISION_DIR:-$STATE_DIR/eject-decisions}"
EJECT_BOT_NAME="${EJECT_BOT_NAME:-harness-auto-deploy}"
EJECT_BOT_EMAIL="${EJECT_BOT_EMAIL:-auto-deploy@harness.invalid}"
EJECT_LABELS="${EJECT_LABELS:-bug}"
EJECT_TAIL_FILE="${EJECT_TAIL_FILE:-}"
EJECT_SCOPE_FILE="${EJECT_SCOPE_FILE:-}"
EJECT_NO_TAIL_HINT="${EJECT_NO_TAIL_HINT:-No pytest tail was captured for this run.}"
EJECT_DECISION_LOCK="${EJECT_DECISION_LOCK:-/tmp/harness-eject-decision.lock}"
eject_pushed=0
eject_branch=""
eject_outcome=""
eject_reason=""
eject_range_count=0
eject_range_shas=""
eject_coauthors=""
eject_worktrees=""
eject_assignee=""
eject_revert_sha=""
eject_mode="restore"
eject_base_sha=""
eject_issue=""
eject_parent_state="unknown"

_eject_remote_url() {
    printf 'https://x-access-token:%s@github.com/%s.git' "${DEPLOY_STATUS_TOKEN:-}" "$GH_REPO_SLUG"
}

_eject_redact() {
    sed -E 's#(x-access-token:)[^@]+@#\1***@#g'
}

# Which red this is: the gate's, a boot that failed, or a build the COMMIT broke.
_eject_trigger() {
    if [ "${gate_red:-0}" -eq 1 ]; then
        printf 'gate-red'
    elif [ "${#BOOT_FAILED_SERVICES[@]}" -gt 0 ]; then
        printf 'boot-check'
    elif [ "${#BUILD_RED_SERVICES[@]}" -gt 0 ]; then
        printf 'build-fail'
    fi
    return 0
}

_eject_claim_sha() {
    mkdir -p "$STATE_DIR/ejected" 2>/dev/null || return 1
    find "$STATE_DIR/ejected" -maxdepth 1 -mindepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null || true
    mkdir "$STATE_DIR/ejected/${NEW_SHA:-unknown}" 2>/dev/null
}

_eject_release_claim() {
    [ -n "${NEW_SHA:-}" ] && rmdir "$STATE_DIR/ejected/$NEW_SHA" 2>/dev/null
    return 0
}

# A claim with no row in the eject log, older than EJECT_CLAIM_STALE_SECONDS, is
# one whose attempt died: released and decided again. A young row-less claim is
# a decision IN FLIGHT and is left alone.
_eject_claim_is_stranded() {
    local claim="$STATE_DIR/ejected/${NEW_SHA:-unknown}" claimed_at
    [ -d "$claim" ] || return 1
    if [ -e "$STATE_DIR/eject-log" ]; then
        [ -r "$STATE_DIR/eject-log" ] || return 1
        grep -q " ${NEW_SHA:-nosha} " "$STATE_DIR/eject-log" 2>/dev/null && return 1
    fi
    claimed_at="$(stat -c %Y "$claim" 2>/dev/null || echo "")"
    case "$claimed_at" in "" | *[!0-9]*) return 1 ;; esac
    [ $(( $(date +%s) - claimed_at )) -ge "${EJECT_CLAIM_STALE_SECONDS:-600}" ]
}

_eject_rate_ok() {
    local rate_log="$STATE_DIR/eject-log" epoch rest newest=0
    [ -e "$rate_log" ] || return 0
    [ -r "$rate_log" ] || { log "eject: the rate log cannot be read; declining rather than guessing"; return 1; }
    while read -r epoch rest; do
        : "$rest"
        case "$epoch" in ''|*[!0-9]*) log "eject: the rate log has a malformed line; declining"; return 1 ;; esac
        [ "$epoch" -gt "$newest" ] && newest="$epoch"
    done < "$rate_log"
    if [ "$newest" -gt 0 ] && [ $(( $(date +%s) - newest )) -lt "${EJECT_COOLDOWN_SECONDS:-900}" ]; then
        log "eject: the last decision was $(( $(date +%s) - newest ))s ago (cooldown ${EJECT_COOLDOWN_SECONDS:-900}s); the red stands"
        return 1
    fi
    return 0
}

_eject_trailer_values() {
    local key_lower sha line
    key_lower="$(printf '%s' "$1" | tr 'A-Z' 'a-z')"
    [ -n "${OLD_SHA:-}" ] && [ -n "${NEW_SHA:-}" ] || return 0
    for sha in $(git -C "$REPO" rev-list --reverse "$OLD_SHA..$NEW_SHA" 2>/dev/null); do
        git -C "$REPO" log -1 --format='%B' "$sha" 2>/dev/null | git interpret-trailers --parse 2>/dev/null \
            | while IFS= read -r line; do
                if [ "$(printf '%s' "${line%%:*}" | tr 'A-Z' 'a-z')" = "$key_lower" ]; then
                    line="${line#*:}"
                    [ -n "${line# }" ] && printf '%s\n' "${line# }"
                fi
            done
    done | awk '!seen[$0]++'
    return 0
}

# The parent is known good when the bookmark already contains it, or a green
# verdict for its CURRENT tree is recorded. A recorded red about the parent's
# own tree is read first and wins over everything.
_eject_parent_is_green() {
    local parent="${OLD_SHA:-}" bookmark tree_now
    local r_sha="" r_verdict="" r_scope="" r_at="" r_reason="" r_tree=""
    eject_parent_state="unknown"
    [ -n "$parent" ] || return 1
    [ -r "$GATE_VERDICT_DIR/$parent" ] \
        && read -r r_sha r_verdict r_scope r_at r_reason r_tree < "$GATE_VERDICT_DIR/$parent" 2>/dev/null
    : "$r_scope$r_at$r_reason"
    tree_now="$(git -C "$REPO" rev-parse "${parent}^{tree}" 2>/dev/null || echo "")"
    if [ "$r_sha" = "$parent" ] && [ "$r_verdict" = "red" ] && [ -n "$r_tree" ] && [ "$r_tree" = "$tree_now" ]; then
        eject_parent_state="red"
        return 1
    fi
    bookmark="$(cat "$LAST_SHA_FILE" 2>/dev/null || echo "")"
    if [ -n "$bookmark" ] && git -C "$REPO" merge-base --is-ancestor "$parent" "$bookmark" 2>/dev/null; then
        eject_parent_state="green"
        return 0
    fi
    if [ "$r_sha" = "$parent" ] && [ "$r_verdict" = "green" ] && [ -n "$r_tree" ] && [ "$r_tree" = "$tree_now" ]; then
        eject_parent_state="green"
        return 0
    fi
    return 1
}

_eject_preconditions_hold() {
    local trigger="$1" remote_head
    eject_reason=""
    if [ -n "${RELEASE_FORCE:-}" ]; then eject_reason="release_force"; return 1; fi
    if [ -z "$trigger" ]; then eject_reason="no_trigger"; return 1; fi
    if [ -d "$STATE_DIR/ejected/${NEW_SHA:-unknown}" ]; then
        if _eject_claim_is_stranded; then
            log "eject: the claim on ${NEW_SHA:0:12} records no decision; releasing it and deciding again"
            _eject_release_claim
        else
            eject_reason="already_decided"; return 1
        fi
    fi
    if [ -z "${OLD_SHA:-}" ] || ! git -C "$REPO" cat-file -e "${OLD_SHA}^{commit}" 2>/dev/null; then
        eject_reason="no_baseline"; return 1
    fi
    if [ "$OLD_SHA" = "${NEW_SHA:-}" ]; then eject_reason="empty_range"; return 1; fi
    _eject_arm_preconditions_hold "$trigger" || return 1
    eject_range_count=$(git -C "$REPO" rev-list --count "$OLD_SHA..$NEW_SHA" 2>/dev/null || echo 0)
    eject_range_shas=$(git -C "$REPO" rev-list --abbrev=12 --abbrev-commit "$OLD_SHA..$NEW_SHA" 2>/dev/null | tr '\n' ' ')
    if [ "$eject_range_count" -lt 1 ] || [ "$eject_range_count" -gt "${EJECT_MAX_RANGE:-5}" ]; then
        eject_reason="range_too_wide"; return 1
    fi
    eject_coauthors=$(_eject_trailer_values 'Co-Authored-By' \
        | awk '{ if (match($0, /<[^>]+>/)) v = substr($0, RSTART + 1, RLENGTH - 2); else v = $0; v = tolower(v); if (v != "" && !seen[v]++) print v }' \
        | tr '\n' ' ')
    eject_worktrees=$(_eject_trailer_values 'Worktree' | tr '\n' ' ')
    if [ "$(git -C "$REPO" rev-list --merges --count "$OLD_SHA..$NEW_SHA" 2>/dev/null || echo 1)" -ne 0 ]; then
        eject_reason="merge_in_range"; return 1
    fi
    if git -C "$REPO" log --format='%ce%n%b' "$OLD_SHA..$NEW_SHA" 2>/dev/null \
            | grep -qiE "^$(printf '%s' "$EJECT_BOT_EMAIL" | sed 's/[.[\*^$]/\\&/g')\$|^Auto-Eject:"; then
        eject_reason="self_authored"; return 1
    fi
    if [ -n "${EJECT_PROTECTED_PATHS:-}" ] && printf '%s\n' "${CHANGED:-}" | grep -qE "$EJECT_PROTECTED_PATHS"; then
        eject_reason="protected_path"; return 1
    fi
    _eject_rate_ok || { eject_reason="rate_limited"; return 1; }
    if [ -z "${DEPLOY_STATUS_TOKEN:-}" ] || [ -z "${GH_REPO_SLUG:-}" ]; then
        eject_reason="no_token"; return 1
    fi
    remote_head=$(timeout 30 git ls-remote "$(_eject_remote_url)" refs/heads/main 2>/dev/null | cut -f1)
    if [ -z "$remote_head" ]; then eject_reason="main_unreadable"; return 1; fi
    eject_base_sha="$remote_head"
    if [ "$remote_head" = "$NEW_SHA" ]; then
        eject_mode="restore"
    elif [ "$eject_range_count" -eq 1 ]; then
        eject_mode="lift"
        log "eject: main is at ${remote_head:0:12}; lifting ${NEW_SHA:0:12} alone"
    else
        eject_reason="main_moved"; return 1
    fi
    _eject_claim_sha || { eject_reason="already_decided"; return 1; }
    return 0
}

# The failure, for the hand-back: the failing tests, the assertion lines, and
# what the gate selected for this commit.
_eject_evidence() {
    local trigger="$1" clean lines assertions
    _eject_evidence_paths
    case "$trigger" in
        boot-check)
            printf 'These services built and then would not boot on the server:\n'
            printf '  %s\n' ${BOOT_FAILED_SERVICES[@]+"${BOOT_FAILED_SERVICES[@]}"}
            printf '\nContainer logs on the server: %s/build-logs/<service>-boot.log\n' "$STATE_DIR"
            return 0 ;;
        build-fail)
            printf 'These images could not be built from this commit:\n'
            printf '  %s\n' ${BUILD_RED_SERVICES[@]+"${BUILD_RED_SERVICES[@]}"}
            printf '\nBuild logs on the server: %s/build-logs/<service>.log\n' "$STATE_DIR"
            return 0 ;;
    esac
    if [ ! -r "$EJECT_TAIL_FILE" ]; then
        printf '%s\n' "$EJECT_NO_TAIL_HINT"
        return 0
    fi
    clean=$(sed -e 's/\x1b\[[0-9;]*m//g' "$EJECT_TAIL_FILE" 2>/dev/null)
    lines=$(printf '%s\n' "$clean" | grep -E '^(FAILED|ERROR) ' | head -20)
    [ -n "$lines" ] && printf '%s\n' "$lines"
    assertions=$(printf '%s\n' "$clean" | grep -E '^E ' | head -25)
    [ -n "$assertions" ] && printf '\nWHAT THE FAILURE SAID:\n\n%s\n' "$assertions"
    [ -z "$lines$assertions" ] && printf '%s\n' "$(printf '%s\n' "$clean" | tail -n 25)"
    if [ -r "$EJECT_SCOPE_FILE" ]; then
        printf '\nWHAT THE GATE RAN FOR THIS COMMIT:\n\n'
        python3 - "$EJECT_SCOPE_FILE" <<'PYEOF' 2>/dev/null || true
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit(0)
paths = doc.get("paths") or []
print(f"scope: {doc.get('scope', '?')} ({doc.get('reason', 'no reason recorded')})")
for path in paths[:20]:
    print(f"  {path}")
if len(paths) > 20:
    print(f"  ... and {len(paths) - 20} more")
PYEOF
    fi
    return 0
}

_eject_reason_words() {
    case "$1" in
        gate-red)
            case "${gate_red_reason:-}" in
                regression)          printf 'its own test suite failed (pytest rc=1)' ;;
                build_regression)    printf 'its tests passed and one of its images would not build' ;;
                no_tests_collected)  printf 'the gate collected no tests, so nothing was verified' ;;
                broken_tree)         printf 'the tree could not be loaded' ;;
                register)            printf 'a test in it has no row in the test register' ;;
                unfalsifiable_test)  printf 'a test passed with its own break applied' ;;
                *)                   printf 'the gate said no (%s)' "${gate_red_reason:-unknown}" ;;
            esac ;;
        boot-check) printf 'a service it changed would not boot' ;;
        build-fail) printf 'an image could not be built from it' ;;
        *)          printf '%s' "$1" ;;
    esac
}

_eject_message() {
    local trigger="$1" msgfile="$2" reason
    reason="$(_eject_reason_words "$trigger")"
    {
        printf 'revert: auto-eject %s, %s\n\n' "${NEW_SHA:0:12}" "$reason"
        printf 'The deploy gate rejected %s: %s.\n' "${NEW_SHA:0:12}" "$reason"
        printf 'A red gate holds the deploy bookmark, so this commit was blocking every\n'
        printf 'commit pushed after it. It is reverted here so the queue moves.\n\n'
        if [ "$eject_mode" = "lift" ]; then
            printf 'This revert takes back this one commit and leaves every commit pushed\n'
            printf 'after it in place; it applied cleanly and removed something.\n\n'
        else
            printf "This revert restores the tree this commit's parent carried, byte for byte.\n\n"
        fi
        printf 'Reverted range (%s commit(s)): %s..%s\n' "$eject_range_count" "${OLD_SHA:0:12}" "${NEW_SHA:0:12}"
        printf '  %s\n' $eject_range_shas
        printf '\nAuto-Eject: %s\n' "$NEW_SHA"
        printf 'Auto-Eject-Range: %s..%s\n' "$OLD_SHA" "$NEW_SHA"
        printf 'Auto-Eject-Reason: %s\n' "$trigger"
    } > "$msgfile" 2>/dev/null
}

_eject_build_revert() {
    local work="$1" url="$2" msgfile="$3" tmplog revert_sha rc=0 depth
    tmplog="$(mktemp)"
    depth=$(( eject_range_count + 3 ))
    [ "$eject_mode" = "lift" ] && depth=$(( eject_range_count + ${commits_ahead:-0} + 25 ))
    if ! timeout 300 git clone --quiet --depth "$depth" --branch main --single-branch "$url" "$work" > "$tmplog" 2>&1; then
        _eject_redact < "$tmplog" >> "$LOG" 2>/dev/null; rm -f "$tmplog"
        log "eject: the throwaway clone failed; nothing reverted"
        return 1
    fi
    revert_sha="$(
        (
            cd "$work" || exit 1
            if [ "$eject_mode" = "lift" ]; then
                git merge-base --is-ancestor "$NEW_SHA" HEAD || exit 1
                git revert --no-commit --no-edit "$NEW_SHA" >&2 || exit 1
                git diff --cached --quiet && exit 1
            else
                [ "$(git rev-parse HEAD)" = "$NEW_SHA" ] || exit 1
                git revert --no-commit --no-edit "$OLD_SHA..$NEW_SHA" >&2 || exit 1
                [ "$(git write-tree)" = "$(git rev-parse "$OLD_SHA^{tree}")" ] || exit 1
            fi
            git -c user.name="$EJECT_BOT_NAME" -c user.email="$EJECT_BOT_EMAIL" commit -q -F "$msgfile" >&2 || exit 1
            git rev-parse HEAD
        ) 2>> "$tmplog"
    )" || rc=$?
    _eject_redact < "$tmplog" >> "$LOG" 2>/dev/null; rm -f "$tmplog"
    if [ "$rc" -ne 0 ] || [ -z "$revert_sha" ]; then
        log "eject: the revert could not be built safely ($eject_mode route); nothing committed, nothing pushed"
        return 1
    fi
    printf '%s' "$revert_sha"
}

_eject_push() {
    local work="$1" url="$2" ref_sha="$3" ref="$4" tmplog rc=0
    [ -n "$ref_sha" ] || return 1
    tmplog="$(mktemp)"
    ( cd "$work" && timeout 60 git push -q "$url" "$ref_sha:refs/heads/$ref" ) > "$tmplog" 2>&1 || rc=$?
    _eject_redact < "$tmplog" >> "$LOG" 2>/dev/null; rm -f "$tmplog"
    return "$rc"
}

# The hand-back branch: the revert reverted, so its tree is what main carried
# just before the revert, which is the rejected work byte for byte.
_eject_build_branch() {
    local work="$1" revert_sha="$2" msgfile="$3" branch_sha rc=0
    branch_sha="$(
        (
            cd "$work" || exit 1
            git checkout -q -b "$eject_branch" "$revert_sha" >&2 || exit 1
            git revert --no-commit --no-edit "$revert_sha" >&2 || exit 1
            [ "$(git write-tree)" = "$(git rev-parse "${revert_sha}^^{tree}")" ] || exit 1
            git -c user.name="$EJECT_BOT_NAME" -c user.email="$EJECT_BOT_EMAIL" commit -q -F "$msgfile" >&2 || exit 1
            git rev-parse HEAD
        ) 2>> "$LOG"
    )" || rc=$?
    [ "$rc" -eq 0 ] && [ -n "$branch_sha" ] || return 1
    printf '%s' "$branch_sha"
}

_eject_land_instructions() {
    printf 'Fix it on this branch and push. Then land the result on main as ONE\n'
    printf 'commit. Do NOT press merge: this branch opens with the tree the gate\n'
    printf 'already refused, and the gate judges every commit against its own tree,\n'
    printf 'so a merge puts a permanently red commit on main and freezes the deploy\n'
    printf 'bookmark behind it. Squash it yourself instead:\n\n'
    printf '    git fetch origin main && git checkout -B fix origin/%s\n' "$eject_branch"
    printf '    git reset --soft origin/main && git commit\n'
    printf '    git push origin HEAD:main\n\n'
    printf 'Landing on main is what re-tests it; "Closes #<this PR>" in the commit\n'
    printf 'message closes this. If it fails again it comes back on a new branch.\n'
}

_eject_branch_message() {
    local trigger="$1" msgfile="$2" value
    {
        printf 're-land: %s, once its gate is green\n\n' "${NEW_SHA:0:12}"
        printf 'This restores the work the deploy server reverted on main, unchanged.\n\n'
        _eject_land_instructions
        printf '\nAuto-Eject-Reland: %s\nAuto-Eject-Reason: %s\n' "$NEW_SHA" "$trigger"
        _eject_trailer_values 'Co-Authored-By' | while IFS= read -r value; do printf 'Co-Authored-By: %s\n' "$value"; done
        _eject_trailer_values 'Worktree' | while IFS= read -r value; do printf 'Worktree: %s\n' "$value"; done
    } > "$msgfile" 2>/dev/null
}

# Who the hand-back goes to: the commit's GitHub author when they can be
# assigned, otherwise EJECT_FALLBACK_ASSIGNEE, otherwise the repository owner.
_eject_resolve_assignee() {
    local login
    login="$(gh_commit_author_login "$NEW_SHA")"
    if [ -n "$login" ] && gh_login_is_assignable "$login"; then
        eject_assignee="$login"
    else
        eject_assignee="${EJECT_FALLBACK_ASSIGNEE:-${GH_REPO_OWNER:-}}"
    fi
    log "eject: hand-back assigned to ${eject_assignee:-nobody}"
}

_eject_effort_lines() {
    local slug
    if [ -z "${eject_worktrees:-}" ]; then
        printf 'The commit records no Worktree trailer, so the effort it came from is unknown.\n'
        return 0
    fi
    for slug in $eject_worktrees; do printf '  %s\n' "$slug"; done
}

_eject_subject() {
    git -C "$REPO" log -1 --format='%s' "$NEW_SHA" 2>/dev/null | cut -c1-70
}

_eject_open_pull_request() {
    local trigger="$1" body
    body="$(
        printf 'The deploy gate rejected this commit, so the deploy server took it off\n'
        printf 'main and put your work here, unchanged.\n\n## What failed\n\n'
        if [ "$trigger" = "gate-red" ]; then
            printf '```\n'; _eject_evidence "$trigger"; printf '```\n\n'
        else
            _eject_evidence "$trigger"; printf '\n'
        fi
        printf '## What to do\n\n'
        _eject_land_instructions
        printf '\nThe branch gate runs the suite against the merge of this branch into\n'
        printf 'main and marks this ready for review once it passes.\n\n'
        printf '<details>\n<summary>What the machine did</summary>\n\n'
        printf 'Reason: %s.\n\nTaken back: %s..%s (%s)\n\n' "$(_eject_reason_words "$trigger")" \
            "${OLD_SHA:0:12}" "${NEW_SHA:0:12}" "$eject_mode"
        [ -n "$eject_revert_sha" ] && printf 'Reverted on main as `%s`.\n\n' "${eject_revert_sha:0:12}"
        printf 'Which effort it came from:\n\n'
        _eject_effort_lines
        printf '\n</details>\n'
    )"
    GH_PULL_REQUEST_DRAFT="${BRANCH_GATE_DRAFT_BLOCK:-1}" \
        gh_pull_request_create "re-land: $(_eject_subject)" "$body" "$eject_branch" "$eject_assignee" "$EJECT_LABELS"
}

_eject_open_issue() {
    local trigger="$1" armed="$2" verb title body
    if [ "$armed" = "1" ]; then
        verb="was reverted on main"
        title="auto-deploy reverted ${NEW_SHA:0:12}: $(_eject_subject)"
    else
        verb="would have been reverted on main (the eject is off; nothing was pushed)"
        title="auto-deploy would have reverted ${NEW_SHA:0:12}: $(_eject_subject)"
    fi
    body="$(
        printf 'Commit %s %s.\n\n' "${NEW_SHA:0:12}" "$verb"
        printf 'WHY: %s. A red gate holds the deploy bookmark, so it was blocking every\n' "$(_eject_reason_words "$trigger")"
        printf 'commit pushed after it.\n\nRANGE: %s..%s\n' "${OLD_SHA:0:12}" "${NEW_SHA:0:12}"
        printf 'WHICH EFFORT:\n'; _eject_effort_lines
        if [ -n "$eject_revert_sha" ] && [ "$armed" = "1" ]; then
            printf '\nREVERT COMMIT: %s\nTO RE-LAND: git revert %s, fix the failure below, push again.\n' \
                "$eject_revert_sha" "$eject_revert_sha"
        fi
        printf '\nWHAT FAILED:\n\n'; _eject_evidence "$trigger"
    )"
    gh_issue_create "$title" "$body" "$eject_assignee" "$EJECT_LABELS"
}

_eject_note_decision() {
    local landed="dryrun"
    [ "$eject_pushed" -eq 1 ] && landed="$eject_revert_sha"
    printf '%s %s %s %s\n' "$(date +%s)" "$NEW_SHA" "$landed" "${eject_outcome:-decided}" \
        >> "$STATE_DIR/eject-log" 2>/dev/null || true
}

# `<outcome> <reason> <epoch>` per sha: the interlock between the two arms and
# what step 90 reads. A `pushed` record is never downgraded.
_eject_write_decision() {
    local outcome="$1" reason="$2" recorded="" rest=""
    [ -n "${NEW_SHA:-}" ] || return 0
    mkdir -p "$EJECT_DECISION_DIR" 2>/dev/null || return 0
    if [ "$outcome" != "pushed" ] && [ -r "$EJECT_DECISION_DIR/$NEW_SHA" ]; then
        read -r recorded rest < "$EJECT_DECISION_DIR/$NEW_SHA" 2>/dev/null || true
        : "$rest"
        [ "$recorded" = "pushed" ] && return 0
    fi
    printf '%s %s %s\n' "$outcome" "$reason" "$(date +%s)" > "$EJECT_DECISION_DIR/$NEW_SHA.tmp.$$" 2>/dev/null \
        && mv -f "$EJECT_DECISION_DIR/$NEW_SHA.tmp.$$" "$EJECT_DECISION_DIR/$NEW_SHA" 2>/dev/null || true
    return 0
}

# One decision at a time across both arms, so two cannot both revert one sha.
_eject_decide() {
    local trigger="$1" rc=0
    if [ "${EJECT_ENABLED:-0}" != "1" ] && [ "${EJECT_DRY_RUN:-0}" != "1" ]; then
        eject_outcome="off"
        eject_reason="eject_off"
        return 0
    fi
    if exec 6>"$EJECT_DECISION_LOCK" 2>/dev/null; then
        flock -w "${EJECT_DECISION_LOCK_WAIT:-600}" 6 2>/dev/null \
            || log "eject: another decision held the lock too long; deciding anyway"
        _eject_decide_alone "$trigger"; rc=$?
        exec 6>&-
    else
        _eject_decide_alone "$trigger"; rc=$?
    fi
    return $rc
}

_eject_decide_alone() {
    local trigger="$1" work msgfile url armed=0 branchmsg branch_sha
    if ! _eject_preconditions_hold "$trigger"; then
        eject_outcome="declined"
        return 0
    fi
    [ "${EJECT_ENABLED:-0}" = "1" ] && armed=1
    url="$(_eject_remote_url)"
    work="$(mktemp -d)"
    msgfile="$(mktemp)"
    _eject_message "$trigger" "$msgfile"
    eject_revert_sha="$(_eject_build_revert "$work" "$url" "$msgfile")" || eject_revert_sha=""
    rm -f "$msgfile"
    if [ -z "$eject_revert_sha" ]; then
        rm -rf "$work"; _eject_release_claim
        eject_outcome="aborted"; eject_reason="revert_not_identical"
        return 0
    fi
    # The arm is asked again just before the push: a verdict may have landed
    # while the clone was being made.
    if ! _eject_arm_preconditions_hold "$trigger"; then
        rm -rf "$work"; _eject_release_claim
        eject_outcome="declined"
        return 0
    fi
    if [ "$armed" -eq 1 ]; then
        if ! _eject_push "$work" "$url" "$eject_revert_sha" main; then
            rm -rf "$work"; _eject_release_claim
            eject_outcome="aborted"; eject_reason="push_rejected"
            return 0
        fi
        eject_pushed=1
        eject_outcome="pushed"
    else
        eject_outcome="dry_run"
    fi
    _eject_note_decision
    _eject_write_decision "$eject_outcome" "${eject_reason:-$trigger}"
    if [ "$armed" -eq 1 ]; then
        eject_branch="auto-eject/${NEW_SHA:0:12}"
        branchmsg="$(mktemp)"
        if _eject_branch_message "$trigger" "$branchmsg" \
                && branch_sha="$(_eject_build_branch "$work" "$eject_revert_sha" "$branchmsg")" \
                && _eject_push "$work" "$url" "$branch_sha" "$eject_branch"; then
            log "eject: hand-back branch $eject_branch pushed at ${branch_sha:0:12}"
        else
            log "eject: no hand-back branch for ${NEW_SHA:0:12}; the hand-back is an issue"
            eject_branch=""
        fi
        rm -f "$branchmsg"
    fi
    rm -rf "$work"
    _eject_resolve_assignee
    [ -n "$eject_branch" ] && eject_issue="$(_eject_open_pull_request "$trigger")"
    [ -n "$eject_issue" ] || eject_issue="$(_eject_open_issue "$trigger" "$armed")"
    [ -n "$eject_issue" ] || log "eject: no issue could be opened for ${NEW_SHA:0:12}; the log and the revert message carry the hand-back"
    return 0
}

true
