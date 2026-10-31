#!/usr/bin/env bash
# pull-env.sh: refresh the server's env cache from the vault (server side).
#
# Reads a scoped credentials file, fetches the latest version of the vault
# secret over the Secret Manager HTTPS API, and atomically rewrites the
# cache at $HARNESS_ROOT/harness.env (mode 600), the file docker compose
# reads with --env-file. The deploy loop runs this every cycle.
#
# The credentials file ($HARNESS_ROOT/scw-secrets.env, mode 600, written
# once by onboarding, never in git) holds:
#   SCW_SECRET_KEY=<an API key allowed to read this one secret>
#   SCW_REGION=<region of the secret, default fr-par>
#   VAULT_SECRET_NAME=<default harness-env>
#   VAULT_SECRET_ID=<optional; looked up by name when empty>
#
# RESILIENCE POLICY: the cache is the fallback. On ANY failure (missing
# credentials, network down, API error, garbage payload) this script keeps
# the existing cache untouched and exits 0 with a warning, so a Secret
# Manager blip can never take the stack down.
set -u
umask 177

HARNESS_ROOT="${HARNESS_ROOT:-/opt/harness}"
CREDS_FILE="${CREDS_FILE:-$HARNESS_ROOT/scw-secrets.env}"
CACHE_FILE="${CACHE_FILE:-$HARNESS_ROOT/harness.env}"

warn() { echo "[pull-env] WARNING: $*, keeping the existing cache" >&2; }

if [ ! -f "$CREDS_FILE" ]; then
    warn "$CREDS_FILE missing (vault not set up on this server yet)"
    exit 0
fi

# shellcheck disable=SC1090
. "$CREDS_FILE"

REGION="${SCW_REGION:-fr-par}"
SECRET_NAME="${VAULT_SECRET_NAME:-harness-env}"
API_BASE="https://api.scaleway.com/secret-manager/v1beta1/regions/$REGION"

if [ -z "${SCW_SECRET_KEY:-}" ]; then
    warn "SCW_SECRET_KEY not set in $CREDS_FILE"
    exit 0
fi

api_get() {
    curl -sf --max-time 20 -H "X-Auth-Token: $SCW_SECRET_KEY" "$1"
}

# One retry with a pause: fresh API keys take a few seconds to propagate.
fetch() {
    api_get "$1" || { sleep 5; api_get "$1"; }
}

SECRET_ID="${VAULT_SECRET_ID:-}"
if [ -z "$SECRET_ID" ]; then
    if ! LISTING=$(fetch "$API_BASE/secrets?name=$SECRET_NAME"); then
        warn "could not look up the vault secret $SECRET_NAME"
        exit 0
    fi
    SECRET_ID=$(printf '%s' "$LISTING" | python3 -c '
import json, sys
name = sys.argv[1]
for secret in json.load(sys.stdin).get("secrets", []):
    if secret.get("name") == name:
        print(secret.get("id", ""))
        break' "$SECRET_NAME" 2>/dev/null)
    if [ -z "$SECRET_ID" ]; then
        warn "no vault secret named $SECRET_NAME in $REGION"
        exit 0
    fi
fi

if ! RESPONSE=$(fetch "$API_BASE/secrets/$SECRET_ID/versions/latest/access"); then
    warn "vault fetch failed twice"
    exit 0
fi

# The payload is base64 in the "data" field. Base64 has no quote
# characters, so this extraction is safe without jq.
DATA_B64=$(printf '%s' "$RESPONSE" | grep -o '"data":"[^"]*"' | head -1 | cut -d'"' -f4)
if [ -z "$DATA_B64" ]; then
    warn "vault response had no data field"
    exit 0
fi

if ! NEW_CONTENT=$(printf '%s' "$DATA_B64" | base64 -d 2>/dev/null); then
    warn "could not decode the vault payload"
    exit 0
fi

if ! printf '%s\n' "$NEW_CONTENT" | grep -q '^DOMAIN='; then
    warn "vault payload does not look like the harness env (no DOMAIN= line)"
    exit 0
fi

# Atomic replace: write a private temp file next to the target, then
# rename over it, so readers only ever see the old file or the new one.
if ! TMP_FILE=$(mktemp "$CACHE_FILE.XXXXXX"); then
    warn "mktemp failed"
    exit 0
fi
if ! printf '%s\n' "$NEW_CONTENT" > "$TMP_FILE"; then
    warn "writing the new cache failed"
    rm -f "$TMP_FILE"
    exit 0
fi
chmod 600 "$TMP_FILE"
if ! mv "$TMP_FILE" "$CACHE_FILE"; then
    warn "replacing $CACHE_FILE failed"
    rm -f "$TMP_FILE"
    exit 0
fi

echo "[pull-env] $CACHE_FILE refreshed from the latest vault version"
