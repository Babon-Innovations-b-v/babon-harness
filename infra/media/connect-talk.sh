#!/usr/bin/env bash
# connect-talk.sh: point the main server's Nextcloud Talk at the media box and
# install the recording bot. Runs ON the main server, from the repository
# checkout, after the media box answers on https://signaling.$DOMAIN.
#
#   1. installs and enables Talk (spreed) when it is missing
#   2. adds the signaling server and the recording server
#   3. installs the "Minutes" webhook bot that calls notulen's
#      /api/talk/webhook, and prints its id for OPENCLAW_TALK_BOT_ID
#
# Every step checks first, so a second run changes nothing. Undo with
# `occ talk:signaling:delete`, `occ talk:recording:delete` and
# `occ talk:bot:uninstall <id>`.
#
# FAILURE POLICY: fail-loud (`set -euo pipefail`). Secrets come from the env
# cache the vault writes and are never printed.
set -euo pipefail

cd "$(dirname "$0")/../.."   # the root docker-compose.yml names the stack
HARNESS_ROOT="${HARNESS_ROOT:-/opt/harness}"
ENV_FILE="${ENV_FILE:-$HARNESS_ROOT/harness.env}"
COMPOSE=(docker compose --env-file "$ENV_FILE")
set -a; . "$ENV_FILE"; set +a
: "${DOMAIN:?}" "${TALK_SIGNALING_SECRET:?}" "${TALK_RECORDING_SECRET:?}" "${TALK_BOT_SECRET:?}"

occ() { "${COMPOSE[@]}" exec -T -u www-data nextcloud php occ "$@"; }

occ app:list --output=json | grep -q '"spreed"' || occ app:install spreed
occ app:enable spreed >/dev/null

if ! occ talk:signaling:list --output=json | grep -q "signaling.$DOMAIN"; then
    occ talk:signaling:add "https://signaling.$DOMAIN" "$TALK_SIGNALING_SECRET" --verify
fi
if ! occ talk:recording:list --output=json | grep -q "recording.$DOMAIN"; then
    occ talk:recording:add "https://recording.$DOMAIN" "$TALK_RECORDING_SECRET" --verify
fi

bot_url="https://notulen.$DOMAIN/api/talk/webhook"
if ! occ talk:bot:list --output=json | grep -q "$bot_url"; then
    occ talk:bot:install --feature=webhook --no-setup \
        "Minutes" "$TALK_BOT_SECRET" "$bot_url" "Records calls into meeting minutes" >/dev/null
fi
bot_id=$(occ talk:bot:list --output=json | python3 -c '
import json, sys
url = sys.argv[1]
print(next((str(bot["id"]) for bot in json.load(sys.stdin) if bot.get("url") == url), ""))
' "$bot_url")
[ -n "$bot_id" ] || { echo "the bot did not install"; exit 1; }
echo "Talk points at the media box. Put OPENCLAW_TALK_BOT_ID=$bot_id in config/harness.env and the vault."
