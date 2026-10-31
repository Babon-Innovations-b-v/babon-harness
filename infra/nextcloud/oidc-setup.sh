#!/usr/bin/env bash
# oidc-setup.sh: make Nextcloud the identity provider for the single sign-on.
#
# Run once on the server after Nextcloud's first boot, and again whenever
# you add an SSO-gated subdomain. Idempotent: every step checks first.
#
#   1. installs (or enables) Nextcloud's `oidc` app through occ,
#   2. creates the OIDC client oauth2-proxy logs in with, unless it exists,
#   3. registers https://<sub>.$DOMAIN/oauth2/callback for every SSO
#      subdomain (SSO_SUBDOMAINS, comma-separated, default auth,notulen) with
#      add_oidc_redirect_uri.php,
#   4. writes OIDC_CLIENT_ID and OIDC_CLIENT_SECRET to an env file
#      (mode 600) so you can put them in the vault with push-env.sh.
#
# Usage (on the server, from the repository checkout):
#   infra/nextcloud/oidc-setup.sh [--out FILE]
#
# --out FILE   where to write the two keys. Default:
#              $HARNESS_ROOT/oidc-client.env. If FILE already holds an
#              environment, the two lines are replaced in place and every
#              other line is kept, so you can point it at a copy of your
#              full vault env and push that file straight back.
#
# Then: copy the two lines into your vault env file on the laptop, run
# infra/secrets/push-env.sh <that file>, and the next deploy cycle starts
# oauth2-proxy with them.
#
# Exit codes: 0 done, 2 usage, 3 occ or Nextcloud failure.
set -euo pipefail

HARNESS_ROOT="${HARNESS_ROOT:-/opt/harness}"
REPO="${REPO:-$HARNESS_ROOT/repo}"
ENV_FILE="${ENV_FILE:-$HARNESS_ROOT/harness.env}"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO/docker-compose.yml}"
CLIENT_NAME="${OIDC_CLIENT_NAME:-harness-sso}"
OUT_FILE="$HARNESS_ROOT/oidc-client.env"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

while [ $# -gt 0 ]; do
    case "$1" in
        --out) OUT_FILE="${2:?--out needs a file}"; shift 2 ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

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

DOMAIN="$(env_get DOMAIN)"
[ -n "$DOMAIN" ] || { echo "DOMAIN is not set (expected in $ENV_FILE)" >&2; exit 2; }
SSO_SUBDOMAINS="$(env_get SSO_SUBDOMAINS)"
SSO_SUBDOMAINS="${SSO_SUBDOMAINS:-auth,notulen}"

log() { printf "[oidc-setup] %s\n" "$*"; }
die() { printf "[oidc-setup] ERROR: %s\n" "$*" >&2; exit 3; }

compose() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

# occ is Nextcloud's admin CLI; it runs inside the container as www-data.
# </dev/null: `exec -T` reads stdin, which would swallow a caller's here-doc.
occ() { compose exec -T -u www-data nextcloud php occ "$@" </dev/null; }

# 1. The oidc app.
if occ app:list --output=json | python3 -c '
import json, sys
apps = json.load(sys.stdin)
sys.exit(0 if "oidc" in apps.get("enabled", {}) else 1)'; then
    log "oidc app already enabled"
else
    occ app:install oidc >/dev/null 2>&1 || occ app:enable oidc >/dev/null \
        || die "could not install or enable the oidc app"
    log "oidc app installed and enabled"
fi

# 2. The client. oidc:list prints every client as JSON, secret included.
read_client() {
    occ oidc:list | python3 -c '
import json, sys
name = sys.argv[1]
for client in json.load(sys.stdin) or []:
    if client.get("name") == name:
        print(client.get("client_id", ""), client.get("client_secret", ""))
        break' "$CLIENT_NAME"
}

callbacks=()
IFS=', ' read -r -a subdomains <<< "$SSO_SUBDOMAINS"
for sub in "${subdomains[@]}"; do
    [ -n "$sub" ] && callbacks+=("https://$sub.$DOMAIN/oauth2/callback")
done

existing="$(read_client)" || die "occ oidc:list failed"
if [ -z "$existing" ]; then
    occ oidc:create "$CLIENT_NAME" "${callbacks[@]}" \
        --type confidential --flow code --algorithm RS256 >/dev/null \
        || die "occ oidc:create failed"
    log "created client $CLIENT_NAME"
    existing="$(read_client)" || die "occ oidc:list failed after create"
else
    log "client $CLIENT_NAME already exists"
fi
client_id="${existing%% *}"
client_secret="${existing#* }"
[ -n "$client_id" ] && [ -n "$client_secret" ] && [ "$client_id" != "$client_secret" ] \
    || die "could not read the client id and secret back from oidc:list"

# 3. Redirect URIs for every SSO subdomain (a new subdomain lands here).
compose cp "$HERE/add_oidc_redirect_uri.php" nextcloud:/tmp/add_oidc_redirect_uri.php
compose exec -T -u www-data nextcloud \
    php /tmp/add_oidc_redirect_uri.php "$CLIENT_NAME" "${callbacks[@]}" </dev/null \
    || die "adding redirect URIs failed"

# 4. Write the two keys back, replacing old lines and keeping the rest.
umask 177
touch "$OUT_FILE"
chmod 600 "$OUT_FILE"
tmp="$(mktemp "$OUT_FILE.XXXXXX")"
grep -v -E '^(OIDC_CLIENT_ID|OIDC_CLIENT_SECRET)=' "$OUT_FILE" > "$tmp" || true
printf 'OIDC_CLIENT_ID=%s\nOIDC_CLIENT_SECRET=%s\n' "$client_id" "$client_secret" >> "$tmp"
mv "$tmp" "$OUT_FILE"

log "wrote OIDC_CLIENT_ID and OIDC_CLIENT_SECRET to $OUT_FILE (mode 600)"
log "next: add them to your vault env file and run infra/secrets/push-env.sh <file>"
