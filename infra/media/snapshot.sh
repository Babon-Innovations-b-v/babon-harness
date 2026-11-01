#!/usr/bin/env bash
# snapshot.sh: back up the media box and keep the newest $KEEP backups.
# Run on the laptop with `scw` configured, by hand or from the laptop's cron.
#
# The main server needs no snapshot, because it is rebuilt from the
# repository. The media box is provisioned by hand, so its state is not
# entirely in the repository, and a backup is how it comes back.
#
# FAILURE POLICY: fail-loud (`set -euo pipefail`). A failed backup should be
# seen, not pass silently.
set -euo pipefail

ZONE="${MEDIA_ZONE:-fr-par-1}"
SERVER_NAME="${MEDIA_SERVER_NAME:-harness-media}"
KEEP="${KEEP:-7}"

server_id=$(scw instance server list name="$SERVER_NAME" zone="$ZONE" -o json \
              | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d[0]["id"] if d else "")')
[ -n "$server_id" ] || { echo "no server named $SERVER_NAME"; exit 1; }

stamp=$(date -u +%Y%m%d-%H%M)
scw instance server backup "$server_id" name="$SERVER_NAME-$stamp" zone="$ZONE" >/dev/null
echo "[media-snapshot] backup $SERVER_NAME-$stamp created"

scw instance image list zone="$ZONE" -o json | python3 -c '
import json, subprocess, sys
prefix, keep, zone = sys.argv[1] + "-", int(sys.argv[2]), sys.argv[3]
images = [image for image in json.load(sys.stdin) if (image.get("name") or "").startswith(prefix)]
images.sort(key=lambda image: image.get("creation_date") or "", reverse=True)
for old in images[keep:]:
    subprocess.run(["scw", "instance", "image", "delete", old["id"], f"zone={zone}",
                    "with-snapshots=true"], check=True)
    print(f"[media-snapshot] pruned {old['"'"'name'"'"']}")
' "$SERVER_NAME" "$KEEP" "$ZONE"
