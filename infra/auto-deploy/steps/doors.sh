#!/bin/bash
# The deploy system's doors: configuration, alerts, verdict files and GitHub.
#
# NOT A STEP. It defines functions and constants and runs nothing, so it is not
# in ../auto-deploy.sh's source list and must never be. It lives in steps/
# because the cycle snapshots steps/ before it runs, and everything that needs
# these doors (the cycle, ../commit_gate/, ../branch_gate/) sources this one
# copy. Two copies of a door drift, and a drifted door posts to the wrong place.
#
# What a caller must define before sourcing: `log` and `LOG`. Everything here
# returns 0 on every path unless it says otherwise: a broken notifier or an
# unreachable GitHub must never fail a deploy, it is logged instead.
#
# CONFIGURATION, three places and nothing else:
#   1. .claude/project.json            the GitHub repository (`repo`), and the
#                                       owner the eject falls back to.
#   2. config/harness.env              non-secret settings, owner-filled.
#   3. $HARNESS_ROOT/harness.env       the vault cache (mode 600), pulled from
#                                       the owner's secret store each cycle.
# Later files win over earlier ones, and anything already in the environment
# (a hand run, a test) wins over both.

HARNESS_ROOT="${HARNESS_ROOT:-/opt/harness}"

# ── Configuration ───────────────────────────────────────────────────────────

# Read KEY=VALUE lines into the environment without executing the file.
# Values may be quoted; comments and blank lines are skipped; a key already set
# in the environment is left alone, so a hand run can override any setting.
harness_load_env_file() {
    local file="$1" line key value
    [ -r "$file" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"${line%%[![:space:]]*}"}"
        case "$line" in ''|'#'*) continue ;; esac
        line="${line#export }"
        key="${line%%=*}"
        [ "$key" = "$line" ] && continue
        case "$key" in *[!A-Za-z0-9_]*|[0-9]*|'') continue ;; esac
        value="${line#*=}"
        case "$value" in
            \"*\") value="${value#\"}"; value="${value%\"}" ;;
            \'*\') value="${value#\'}"; value="${value%\'}" ;;
        esac
        if [ -z "${!key+set}" ] || [ -n "${_HARNESS_LOADED_KEYS[$key]+set}" ]; then
            export "$key=$value"
            _HARNESS_LOADED_KEYS[$key]=1
        fi
    done < "$file"
    return 0
}

# Load the two env files, the committed settings first and the vault cache
# second, so a value the vault carries wins over the settings file but never
# over the caller's own environment.
harness_load_config() {
    local repo="${1:-${REPO:-$HARNESS_ROOT/repo}}"
    declare -gA _HARNESS_LOADED_KEYS=()
    harness_load_env_file "$repo/config/harness.env"
    harness_load_env_file "${HARNESS_ENV_FILE:-$HARNESS_ROOT/harness.env}"
    HARNESS_ROOT="${HARNESS_ROOT:-/opt/harness}"
    return 0
}

# The GitHub repository as owner/name: `repo` in .claude/project.json, then the
# clone's origin URL. Empty when neither says, and every GitHub door below is
# then a no-op, which is what a box that has not run setup-github.py should do.
harness_repo_slug() {
    local repo="${1:-${REPO:-$HARNESS_ROOT/repo}}" slug=""
    if [ -r "$repo/.claude/project.json" ]; then
        slug="$(python3 -c 'import json,sys
try:
    print(json.load(open(sys.argv[1])).get("repo") or "")
except Exception:
    print("")' "$repo/.claude/project.json" 2>/dev/null)"
    fi
    if [ -z "$slug" ]; then
        slug="$(git -C "$repo" remote get-url origin 2>/dev/null \
            | sed -E 's#^(git@github\.com:|https://([^@]*@)?github\.com/)##; s#\.git$##')"
        case "$slug" in */*) ;; *) slug="" ;; esac
    fi
    printf '%s' "$slug"
}

# The repository owner from .claude/project.json, the eject's last-resort
# assignee for a hand-back nobody else can be found for.
harness_repo_owner() {
    local repo="${1:-${REPO:-$HARNESS_ROOT/repo}}"
    [ -r "$repo/.claude/project.json" ] || return 0
    python3 -c 'import json,sys
try:
    print(json.load(open(sys.argv[1])).get("owner") or "")
except Exception:
    print("")' "$repo/.claude/project.json" 2>/dev/null
}

# ── Alerts ──────────────────────────────────────────────────────────────────
# fire_alert <subject> <body> [--wakes-somebody] [--blocks-deploy yes|no]
#                             [--exit-code N] [--qualifier TEXT]
#
# THE DEFAULT IS A RECORD, NOT A PAGE. Without --wakes-somebody the alert is a
# line in the deploy log and nothing more. With it, the alert goes to the
# assistant's notify webhook (infra/auto-deploy/notify.py), which sends it from
# the owner's Signal number. The test at the call site: what does a person DO
# when this arrives? If the answer is nothing, pass no flag. A default that
# pages means every call site added later pages too, and a page people learn to
# swipe away is worse than none.
fire_alert() {
    local subject="$1" body="$2" wake="" facts=()
    shift 2
    while [ $# -gt 0 ]; do
        case "$1" in
            --wakes-somebody) wake=1; shift ;;
            --blocks-deploy|--exit-code|--qualifier|--error-line)
                facts+=("${1#--}=${2:-}"); shift 2 ;;
            *) log "[page] ignoring an unknown alert argument: $1"; shift ;;
        esac
    done
    if [ -z "$wake" ]; then
        log "RECORD: $subject | $body"
        return 0
    fi
    log "ALERT: $subject"
    python3 "${HARNESS_NOTIFY:-${REPO:-$HARNESS_ROOT/repo}/infra/auto-deploy/notify.py}" \
        "$subject" "$body" ${facts[@]+"${facts[@]}"} >> "$LOG" 2>&1 || true
    return 0
}

# A record for something that happened and asks nothing of anybody.
record_to_talk() {
    log "RECORD: $1 | $2"
    return 0
}

# Page once per (kind, sha), not once per two-minute tick. `mkdir` is the
# test-and-set: atomic on one filesystem, so two cycles cannot both page. A
# STATE_DIR that cannot be written means page anyway: fail toward being told.
fire_alert_once() {
    local kind="$1" sha="$2" subject="$3" body="$4"
    shift 4
    local marker="${PAGED_DIR:-$STATE_DIR/paged}/${kind}.${sha}"
    mkdir -p "${PAGED_DIR:-$STATE_DIR/paged}" 2>/dev/null || { fire_alert "$subject" "$body" "$@"; return 0; }
    find "${PAGED_DIR:-$STATE_DIR/paged}" -maxdepth 1 -mindepth 1 -type d -mtime +7 \
        -exec rm -rf {} + 2>/dev/null || true
    if mkdir "$marker" 2>/dev/null; then
        fire_alert "$subject" "$body" "$@"
    else
        log "[page] suppressed duplicate $kind alert for ${sha:0:8} (already sent)"
    fi
    return 0
}

# The subject line of a commit, for an alert that names a sha.
_commit_subject() {
    local sha="${1:-}" subject
    [ -n "$sha" ] || { printf 'unknown commit'; return 0; }
    subject=$(git -C "$REPO" log -1 --format=%s "$sha" 2>/dev/null | tr -d '"' | cut -c1-90)
    printf '%s' "${subject:-subject unavailable}"
    return 0
}

# ── GitHub ──────────────────────────────────────────────────────────────────
# Every door uses DEPLOY_STATUS_TOKEN against GH_REPO_SLUG. That token needs
# commit statuses and deployments; with EJECT_ENABLED=1 it also needs contents
# write and pull requests. No token or no slug: every door is a quiet no-op.

_gh_api() {
    # _gh_api <method> <path> [json body]; prints body then the HTTP code on its
    # own last line. Path is relative to /repos/<slug> unless it starts with /.
    local method="$1" path="$2" data="${3:-}" url
    case "$path" in
        /users/*|/search/*|/graphql) url="https://api.github.com$path" ;;
        *) url="https://api.github.com/repos/$GH_REPO_SLUG$path" ;;
    esac
    if [ -n "$data" ]; then
        curl -sS -m 15 -w '\n%{http_code}' -X "$method" \
            -H "Authorization: Bearer $DEPLOY_STATUS_TOKEN" \
            -H "Accept: application/vnd.github+json" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            "$url" -d "$data" 2>>"$LOG" || printf '\n000'
    else
        curl -sS -m 15 -w '\n%{http_code}' -X "$method" \
            -H "Authorization: Bearer $DEPLOY_STATUS_TOKEN" \
            -H "Accept: application/vnd.github+json" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            "$url" 2>>"$LOG" || printf '\n000'
    fi
}

_gh_ready() {
    [ -n "${DEPLOY_STATUS_TOKEN:-}" ] && [ -n "${GH_REPO_SLUG:-}" ]
}

_gh_json() {
    # _gh_json <python expression over `d`>: reads a JSON body on stdin.
    python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)
value = eval(sys.argv[1])
if value is not None:
    print(value)' "$1" 2>/dev/null || true
}

# The newest state a context carries on one commit, or `none`.
gh_status_of() {
    local sha="$1" context="$2" response
    if ! _gh_ready || [ -z "$sha" ]; then printf 'none'; return 0; fi
    response="$(_gh_api GET "/commits/$sha/statuses?per_page=100" | head -n -1)"
    printf '%s' "$response" | python3 -c 'import json,sys
try:
    rows = json.load(sys.stdin)
except Exception:
    print("none"); raise SystemExit
mine = [r for r in rows if isinstance(r, dict) and r.get("context") == sys.argv[1]] if isinstance(rows, list) else []
print(max(mine, key=lambda r: r.get("created_at", ""))["state"] if mine else "none")' "$context" 2>/dev/null \
        || printf 'none'
    return 0
}

# One commit status. `success` the stage did its job; `failure` it ran and said
# no, or was not attempted because the stage before said no; `error` it could
# not form an opinion. Never collapse `error` into either other word.
gh_post_status() {
    local sha="$1" context="$2" state="$3" description="$4" target_url="${5:-}"
    _gh_ready || return 0
    [ -n "$sha" ] || return 0
    description="$(printf '%.138s' "$description")"
    _gh_api POST "/statuses/$sha" "$(python3 -c 'import json,sys
print(json.dumps({"state": sys.argv[1], "context": sys.argv[2], "description": sys.argv[3], "target_url": sys.argv[4]}))' \
        "$state" "$context" "$description" "$target_url")" > /dev/null
    return 0
}

# A stage status on every commit the cycle covers, OLD_SHA..NEW_SHA, at most 50.
gh_stage_range() {
    local context="$1" state="$2" description="$3" target_url="${4:-}"
    local from="${OLD_SHA:-}" to="${NEW_SHA:-}" shas="" sha
    [ -n "$to" ] || return 0
    if [ -n "$from" ] && [ "$from" != "$to" ]; then
        shas=$(git -C "$REPO" rev-list --first-parent "$from..$to" 2>/dev/null | head -50)
    fi
    [ -n "$shas" ] || shas="$to"
    for sha in $shas; do
        gh_post_status "$sha" "$context" "$state" "$description" "$target_url"
    done
    return 0
}

# vm/deploy on the whole range.
gh_status_range() {
    gh_stage_range "vm/deploy" "$1" "$2" ""
    return 0
}

# A stage status on the commit the cycle is about.
gh_stage_head() {
    gh_post_status "${NEW_SHA:-}" "$1" "$2" "$3" "${4:-}"
    return 0
}

# A GitHub Deployment for one service; prints its id. "required_contexts": []
# and "auto_merge": false are load-bearing: without them GitHub refuses the
# deployment because the vm/* statuses are still pending, or merges main.
gh_deployment_create() {
    local svc="$1" scope="${2:-}" response http
    _gh_ready || return 0
    [ -n "${NEW_SHA:-}" ] || return 0
    response="$(_gh_api POST "/deployments" "$(python3 -c 'import json,sys
print(json.dumps({"ref": sys.argv[1], "environment": "production-" + sys.argv[2], "description": ("deploy " + sys.argv[2] + " @ " + sys.argv[1][:12])[:140], "auto_merge": False, "required_contexts": [], "production_environment": True, "transient_environment": False, "payload": {"service": sys.argv[2], "gate_scope": sys.argv[3]}}))' \
        "$NEW_SHA" "$svc" "$scope")")"
    http="$(printf '%s' "$response" | tail -n1)"
    case "$http" in
        201) printf '%s' "$response" | head -n -1 | _gh_json 'd.get("id")' ;;
        401|403|404)
            fire_alert_once "gh-deployments-denied" "token" \
                "auto-deploy: GitHub deployments API denied" \
                "POST /deployments returned HTTP $http. Give DEPLOY_STATUS_TOKEN 'Deployments: read and write'. Deploys are unaffected; only the Environments view is missing." ;;
        *) log "[gh] deployment create for $svc returned HTTP $http (record skipped)" ;;
    esac
    return 0
}

gh_deployment_status() {
    local deployment_id="$1" svc="$2" state="$3" description="$4"
    _gh_ready || return 0
    [ -n "$deployment_id" ] || return 0
    _gh_api POST "/deployments/$deployment_id/statuses" "$(python3 -c 'import json,sys
print(json.dumps({"state": sys.argv[1], "description": sys.argv[2][:138], "environment": "production-" + sys.argv[3]}))' \
        "$state" "$description" "$svc")" > /dev/null
    return 0
}

# The GitHub login that authored a commit, or nothing.
gh_commit_author_login() {
    local sha="$1"
    _gh_ready || return 0
    [ -n "$sha" ] || return 0
    _gh_api GET "/commits/$sha" | head -n -1 | _gh_json '(d.get("author") or {}).get("login") or ""'
    return 0
}

# True for an address that is a bot or a tool, never a person to hand work to.
gh_email_is_not_a_person() {
    local lower entry
    [ -n "${1:-}" ] || return 1
    lower="$(printf '%s' "$1" | tr 'A-Z' 'a-z')"
    for entry in $(printf '%s' "${EJECT_TRAILER_DENY_EMAILS:-noreply@anthropic.com,noreply@github.com,${EJECT_BOT_EMAIL:-auto-deploy@harness.invalid}}" | tr 'A-Z,' 'a-z '); do
        [ "$entry" = "$lower" ] && return 0
    done
    return 1
}

# A login for a commit address: the noreply form first, then a commit by that
# address in this repository. Nothing when neither answers.
gh_login_for_email() {
    local address="$1" lower encoded
    _gh_ready || return 0
    [ -n "$address" ] || return 0
    gh_email_is_not_a_person "$address" && return 0
    lower="$(printf '%s' "$address" | tr 'A-Z' 'a-z')"
    if [[ "$lower" =~ ^([0-9]+\+)?([a-z0-9-]+)@users\.noreply\.github\.com$ ]]; then
        printf '%s' "${BASH_REMATCH[2]}"
        return 0
    fi
    encoded="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$lower")"
    _gh_api GET "/commits?author=$encoded&per_page=1" | head -n -1 \
        | _gh_json '((d[0].get("author") or {}).get("login") or "") if isinstance(d, list) and d else ""'
    return 0
}

gh_login_is_assignable() {
    local login="$1"
    _gh_ready || return 1
    [ -n "$login" ] || return 1
    [ "$(_gh_api GET "/assignees/$login" | tail -n1)" = "204" ]
}

# Open an issue; prints its number.
gh_issue_create() {
    local title="$1" body="$2" assignee="$3" labels_csv="${4:-}" response http
    _gh_ready || return 0
    [ -n "$title" ] || return 0
    response="$(_gh_api POST "/issues" "$(python3 -c 'import json,sys
d = {"title": sys.argv[1][:250], "body": sys.argv[2], "labels": [l for l in sys.argv[4].split(",") if l]}
if sys.argv[3]:
    d["assignees"] = [sys.argv[3]]
print(json.dumps(d))' "$title" "$body" "$assignee" "$labels_csv")")"
    http="$(printf '%s' "$response" | tail -n1)"
    case "$http" in
        201) printf '%s' "$response" | head -n -1 | _gh_json 'd.get("number")' ;;
        *) log "[gh] issue create returned HTTP $http (the hand-back is not tracked on GitHub)" ;;
    esac
    return 0
}

# Open a pull request from <head> into main; prints its number. Opened as a
# draft when GH_PULL_REQUEST_DRAFT=1, retried as an ordinary one where the plan
# has no drafts.
gh_pull_request_create() {
    local title="$1" body="$2" head="$3" assignee="$4" labels_csv="${5:-}"
    local draft="${GH_PULL_REQUEST_DRAFT:-0}" response http number
    _gh_ready || return 0
    [ -n "$title" ] && [ -n "$head" ] || return 0
    while : ; do
        response="$(_gh_api POST "/pulls" "$(python3 -c 'import json,sys
print(json.dumps({"title": sys.argv[1][:250], "body": sys.argv[2], "head": sys.argv[3], "base": "main", "maintainer_can_modify": True, "draft": sys.argv[4] == "1"}))' \
            "$title" "$body" "$head" "$draft")")"
        http="$(printf '%s' "$response" | tail -n1)"
        if [ "$http" = "422" ] && [ "$draft" = "1" ]; then
            log "[gh] the hand-back could not be opened as a draft (HTTP 422); retrying as an ordinary pull request"
            draft=0
            continue
        fi
        break
    done
    if [ "$http" != "201" ]; then
        log "[gh] pull request create returned HTTP $http (handing back as an issue instead)"
        return 0
    fi
    number="$(printf '%s' "$response" | head -n -1 | _gh_json 'd.get("number")')"
    [ -n "$number" ] || return 0
    _gh_api PATCH "/issues/$number" "$(python3 -c 'import json,sys
d = {"labels": [l for l in sys.argv[2].split(",") if l]}
if sys.argv[1]:
    d["assignees"] = [sys.argv[1]]
print(json.dumps(d))' "$assignee" "$labels_csv")" > /dev/null
    printf '%s' "$number"
    return 0
}

true
