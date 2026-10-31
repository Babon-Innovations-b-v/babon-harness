#!/usr/bin/env bash
# Keep sign-in sessions at seven days, and the SSO cookie at eight hours.
#
# Four settings decide how often people type a password and a code. They
# live in Nextcloud's database and in oauth2-proxy's flags, not in a file
# a rebuild restores, so the deploy loop re-asserts them every cycle:
#
#   1. Nextcloud remember_login_cookie_lifetime = 604800 (7 days)
#   2. Nextcloud session_lifetime               = 604800. Its default of
#      24 hours is what forces a daily full login with a second factor.
#   3. oidc app expire_time                     = 604800, so the id token
#      outlives the proxy cookie.
#   4. oauth2-proxy runs with --cookie-expire=8h and --cookie-refresh=0s.
#      READ-ONLY check: the flags live in infra/nextcloud/compose.yml, so
#      drift is reported, not rewritten.
#
# The 8-hour proxy cookie against the 7-day Nextcloud session is on
# purpose. The proxy never re-checks inside its cookie, so a long cookie
# would let a disabled account keep opening the dashboards. Expiring it
# sends the browser back through Nextcloud, whose 7-day session signs the
# person straight back in without a prompt, while re-checking the account.
# Shortening the Nextcloud values instead brings back the daily prompt.
#
# Changing 1 to 3 is safe: they apply to cookies and sessions minted
# from now on, and lock nobody out.
#
# FAILURE POLICY: never blocks a deploy. Prints what it fixed or could not
# fix; exit 4 means drift that needs a person.
# Exit codes: 0 = all asserted; 4 = drift found and not repaired.
set -u

HARNESS_ROOT="${HARNESS_ROOT:-/opt/harness}"
REPO="${REPO:-$HARNESS_ROOT/repo}"
ENV_FILE="${ENV_FILE:-$HARNESS_ROOT/harness.env}"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO/docker-compose.yml}"

WEEK_SECONDS=604800
REQUIRED_PROXY_FLAGS=("--cookie-expire=8h" "--cookie-refresh=0s")

log() { printf "[session-lifetime] %s\n" "$*"; }

compose() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }
occ() { compose exec -T -u www-data nextcloud php occ "$@" </dev/null 2>/dev/null; }

DRIFT=0

# assert_setting <label> <current value> <set command...>
assert_setting() {
    local label="$1" current="$2"; shift 2
    if [ "$current" = "$WEEK_SECONDS" ]; then
        return 0
    fi
    log "$label was '$current', setting $WEEK_SECONDS"
    if "$@" >/dev/null; then
        log "$label restored to $WEEK_SECONDS"
    else
        DRIFT=1
        log "$label could NOT be restored"
    fi
}

assert_setting "remember_login_cookie_lifetime" \
    "$(occ config:system:get remember_login_cookie_lifetime || true)" \
    occ config:system:set remember_login_cookie_lifetime --value="$WEEK_SECONDS" --type=integer

assert_setting "session_lifetime" \
    "$(occ config:system:get session_lifetime || true)" \
    occ config:system:set session_lifetime --value="$WEEK_SECONDS" --type=integer

assert_setting "oidc expire_time" \
    "$(occ config:app:get oidc expire_time || true)" \
    occ config:app:set oidc expire_time --value="$WEEK_SECONDS"

proxy_id="$(compose ps -q oauth2-proxy 2>/dev/null || true)"
proxy_args=""
if [ -n "$proxy_id" ]; then
    proxy_args="$(docker inspect "$proxy_id" --format '{{json .Args}}' 2>/dev/null || true)"
fi
for flag in "${REQUIRED_PROXY_FLAGS[@]}"; do
    case "$proxy_args" in
        *"$flag"*) ;;
        *)
            DRIFT=1
            log "oauth2-proxy is running without $flag; restore it in infra/nextcloud/compose.yml"
            ;;
    esac
done

if [ "$DRIFT" -ne 0 ]; then
    exit 4
fi
log "session settings asserted"
exit 0
