#!/usr/bin/env bash
# deploy.sh: put this directory on the media box and (re)start its stack.
# Run on the laptop: `infra/media/deploy.sh <media-box-ip>`.
#
# A push to main changes nothing on the media box; this script is the only
# way a change gets there. It reads the vault with the laptop's `scw`, writes
# the media box's .env with only the keys that box needs, copies the
# directory over, runs setup.sh and `docker compose up -d --build`.
#
# FAILURE POLICY: fail-loud (`set -euo pipefail`). The vault copy lives in a
# mode-600 temp file that is removed on exit and never printed.
set -euo pipefail

ip="${1:?usage: deploy.sh <media-box-ip>}"
here="$(cd "$(dirname "$0")" && pwd)"
SECRET_NAME="${VAULT_SECRET_NAME:-harness-env}"
REGION="${SCW_REGION:-fr-par}"
REMOTE=/opt/media-stack

vault=$(mktemp); env_out=$(mktemp)
trap 'rm -f "$vault" "$env_out"' EXIT
chmod 600 "$vault" "$env_out"

secret_id=$(scw secret secret list name="$SECRET_NAME" region="$REGION" -o json \
              | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d[0]["id"] if d else "")')
[ -n "$secret_id" ] || { echo "no vault secret named $SECRET_NAME"; exit 1; }
scw secret version access "$secret_id" revision=latest region="$REGION" raw=true > "$vault"

keys="DOMAIN MEDIA_PUBLIC_IP TALK_SIGNALING_SECRET TALK_RECORDING_SECRET TALK_INTERNAL_SECRET TALK_SESSION_HASHKEY TALK_SESSION_BLOCKKEY"
for key in $keys; do
    line=$(grep -E "^${key}=" "$vault" | tail -1 || true)
    [ -n "${line#*=}" ] || { echo "the vault has no value for $key"; exit 1; }
    printf '%s\n' "$line" >> "$env_out"
done

ssh "root@$ip" "mkdir -p $REMOTE"
scp -q -r "$here/docker-compose.yml" "$here/Caddyfile" "$here/setup.sh" \
         "$here/templates" "$here/patches" "root@$ip:$REMOTE/"
scp -q "$env_out" "root@$ip:$REMOTE/.env"
ssh "root@$ip" "cd $REMOTE && bash setup.sh && docker compose up -d --build"
echo "media box $ip deployed; check https://signaling.<domain>/api/v1/welcome"
