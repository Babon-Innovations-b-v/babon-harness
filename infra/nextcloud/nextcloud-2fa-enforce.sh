#!/usr/bin/env bash
# Enforce two-factor authentication for every Nextcloud user. Idempotent.
#
# Nextcloud is the one login in the stack: every SSO-gated subdomain
# sends the browser here. So it gets a second factor (TOTP, the 6-digit
# codes from an authenticator app), enforced for everyone.
#
# The deploy loop runs this every cycle so enforcement survives a server
# rebuild. It does nothing until you set NEXTCLOUD_2FA_ENFORCE=1 in the
# vault, a deliberate step after every account has enrolled.
#
# FAIL-CLOSED: before turning enforcement ON, every existing user must
# already have a second factor. If ANY user has none, or occ output cannot
# be positively parsed, it ABORTS instead of locking someone out. Once
# enforcement is on, Nextcloud itself walks new users through setup.
#
# Usage (on the server, from the repository checkout):
#   infra/nextcloud/nextcloud-2fa-enforce.sh --check   # read-only: who is enrolled?
#   infra/nextcloud/nextcloud-2fa-enforce.sh           # enforce (needs the flag)
#
# Exit codes: 0 = enforced / already enforced / flag off / --check done
#             3 = aborted (someone would be locked out, or occ failed)
set -u

HARNESS_ROOT="${HARNESS_ROOT:-/opt/harness}"
REPO="${REPO:-$HARNESS_ROOT/repo}"
ENV_FILE="${ENV_FILE:-$HARNESS_ROOT/harness.env}"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO/docker-compose.yml}"
MODE="${1:-enforce}"

# env_get KEY: one value from the env file, without sourcing it (values
# may hold spaces that a shell would run as commands). Environment wins.
env_get() {
    local key="$1" value
    value="$(printenv "$key" || true)"
    if [ -z "$value" ] && [ -r "$ENV_FILE" ]; then
        value="$({ grep -E "^${key}=" "$ENV_FILE" || true; } | tail -1 | cut -d= -f2-)"
        value="${value%\"}"; value="${value#\"}"
        value="${value%\'}"; value="${value#\'}"
    fi
    printf '%s' "$value"
}

log() { printf "[2fa-enforce] %s\n" "$*"; }

# </dev/null matters: exec -T reads stdin, and inside the per-user while
# loops that would swallow the remaining user list, silently checking
# only the first user (a lockout risk when enforcing).
occ() {
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \
        exec -T -u www-data nextcloud php occ "$@" </dev/null
}

# User ids, one per line; non-zero (fail closed) if they can't be read.
list_uids() {
    local users_json
    users_json="$(occ user:list --output=json 2>/dev/null)" || return 1
    printf '%s' "$users_json" \
        | python3 -c 'import json,sys; print("\n".join(json.load(sys.stdin).keys()))'
}

# True only on the positive "is enabled for user" line. The negative reads
# "is not enabled", so anything ambiguous counts as NOT enrolled.
is_enrolled() {
    occ twofactorauth:state "$1" 2>/dev/null | grep -qi "is enabled for user"
}

is_enforced() {
    occ twofactorauth:enforce 2>/dev/null | grep -qi "enforced for all users"
}

# Without the TOTP provider nobody CAN enrol. Idempotent.
occ app:enable twofactor_totp >/dev/null 2>&1 \
    || log "note: could not enable twofactor_totp (is the nextcloud container running?)"

if [ "$MODE" = "--check" ]; then
    uids="$(list_uids)" || { log "ABORT: could not list users"; exit 3; }
    blockers=""
    while IFS= read -r uid; do
        [ -z "$uid" ] && continue
        if is_enrolled "$uid"; then
            log "  enrolled : $uid"
        else
            log "  NO 2FA   : $uid"
            blockers="${blockers}${uid} "
        fi
    done <<< "$uids"
    if [ -n "$blockers" ]; then
        log "WOULD ABORT: these users have no active 2FA yet: $blockers"
    else
        log "OK: all users enrolled; enforce would succeed."
    fi
    if is_enforced; then log "enforcement: ON"; else log "enforcement: OFF"; fi
    exit 0
fi

if [ "$(env_get NEXTCLOUD_2FA_ENFORCE)" != "1" ]; then
    log "off (NEXTCLOUD_2FA_ENFORCE is not 1): nothing to do"
    exit 0
fi

if is_enforced; then
    log "already enforced: nothing to do"
    exit 0
fi

uids="$(list_uids)" || {
    log "ABORT: could not list Nextcloud users; enforcement NOT applied"
    exit 3
}

unenrolled=""
while IFS= read -r uid; do
    [ -z "$uid" ] && continue
    is_enrolled "$uid" || unenrolled="${unenrolled}${uid} "
done <<< "$uids"

if [ -n "$unenrolled" ]; then
    log "ABORT: these users have no second factor and would be locked out: $unenrolled"
    log "Have them log in, open Settings > Security, set up TOTP, then re-run."
    exit 3
fi

if occ twofactorauth:enforce --on; then
    log "2FA is now enforced for all users"
    exit 0
fi
log "ABORT: occ twofactorauth:enforce --on failed"
exit 3
