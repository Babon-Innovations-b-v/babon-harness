#!/usr/bin/env bash
# push-env.sh: push the full environment to the vault (laptop side).
#
# The vault is one Scaleway Secret Manager secret, named by
# VAULT_SECRET_NAME (default harness-env), whose content is the complete
# KEY=value environment the stack needs: the settings from
# config/harness.env plus every secret listed in config/vault.env.example.
# Every change is a NEW VERSION of that one secret. The server pulls the
# latest version into $HARNESS_ROOT/harness.env every deploy cycle (see
# pull-env.sh), so a pushed version is live within one cycle, no ssh.
#
# Usage:
#   infra/secrets/push-env.sh <file-with-the-full-env>
#
# Uses the scw CLI already configured on this laptop: its access key,
# secret key and default project come from `scw init`, never from a file
# in this repository. Creates the secret on first use. NEVER prints the
# content.
set -euo pipefail

SECRET_NAME="${VAULT_SECRET_NAME:-harness-env}"
REGION="${SCW_REGION:-fr-par}"

if [[ $# -ne 1 ]]; then
    echo "usage: $0 <env-file>" >&2
    exit 2
fi
ENV_CONTENT_FILE="$1"

if [[ ! -s "$ENV_CONTENT_FILE" ]]; then
    echo "refusing to push: $ENV_CONTENT_FILE is missing or empty" >&2
    exit 2
fi

# A shape check so a wrong file (a log, a PDF) never becomes the env.
if ! grep -q '^DOMAIN=' "$ENV_CONTENT_FILE"; then
    echo "refusing to push: $ENV_CONTENT_FILE has no DOMAIN= line, so it does not look like the harness env" >&2
    exit 2
fi

if ! command -v scw >/dev/null 2>&1; then
    echo "the scw CLI is not installed; see https://www.scaleway.com/en/cli/ and run scw init" >&2
    exit 2
fi

# json_field <field>: read one string field from the JSON on stdin.
json_field() {
    python3 -c '
import json, sys
data = json.load(sys.stdin)
if isinstance(data, list):
    data = data[0] if data else {}
print(data.get(sys.argv[1], ""))
' "$1"
}

SECRET_ID=$(scw secret secret list name="$SECRET_NAME" region="$REGION" -o json | json_field id)
if [[ -z "$SECRET_ID" ]]; then
    echo "vault secret $SECRET_NAME does not exist yet in $REGION; creating it"
    SECRET_ID=$(scw secret secret create name="$SECRET_NAME" region="$REGION" -o json | json_field id)
fi
if [[ -z "$SECRET_ID" ]]; then
    echo "could not find or create the vault secret $SECRET_NAME" >&2
    exit 1
fi

# data=@file makes the CLI read the file; the content never appears on the
# command line or in this script's output.
REVISION=$(scw secret version create "$SECRET_ID" region="$REGION" data=@"$ENV_CONTENT_FILE" -o json | json_field revision)
if [[ -z "$REVISION" ]]; then
    echo "pushing the new version failed" >&2
    exit 1
fi

echo "pushed vault version $REVISION of $SECRET_NAME"
echo "it goes live on the server at the next deploy cycle, or now with: infra/secrets/pull-env.sh (on the server)"
