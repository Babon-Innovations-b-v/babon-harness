#!/usr/bin/env bash
# rotate_webhook_secret.sh: rotate OPENCLAW_WEBHOOK_SECRET with no downtime.
#
# The secret signs every call into the assistant's door: Alertmanager's
# webhook, the timers on the server, and the gateway's tool calls. A plain
# swap would refuse every caller still holding the old value until it is
# restarted. The door accepts two secrets at once (`shared/auth.py`):
# OPENCLAW_WEBHOOK_SECRET and OPENCLAW_WEBHOOK_SECRET_PREV. So a rotation is
# two pushes to the vault, one deploy cycle apart:
#
#   start   PREV = the old value, current = a new one. Push. The next cycle
#           pulls it, every container restarts with the new value, and the
#           door still accepts the old one from anything not yet restarted.
#   finish  PREV removed. Push. From the next cycle on, only the new value
#           opens the door.
#
# Usage (on the laptop, against the full env file you push with):
#   apps/assistant/ops/rotate_webhook_secret.sh start  <env-file>
#   apps/assistant/ops/rotate_webhook_secret.sh finish <env-file>
#
# The env file is edited in place and pushed with infra/secrets/push-env.sh.
# The value is never printed.
#
# FAILURE POLICY: fail-loud. Any step that fails stops before the push, so the
# vault never holds a half-rotated pair.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"

if [[ $# -ne 2 || ( "$1" != start && "$1" != finish ) ]]; then
    echo "usage: $0 start|finish <env-file>" >&2
    exit 2
fi
mode="$1"
env_file="$2"
[[ -s "$env_file" ]] || { echo "no env file at $env_file" >&2; exit 2; }

python3 - "$mode" "$env_file" <<'PY'
import pathlib, secrets, sys

mode, path = sys.argv[1], pathlib.Path(sys.argv[2])
lines = path.read_text(encoding="utf-8").splitlines()
values = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in lines if "=" in line and not line.startswith("#")}
current = values.get("OPENCLAW_WEBHOOK_SECRET", "").strip()
if not current:
    sys.exit("OPENCLAW_WEBHOOK_SECRET is not in the env file; nothing to rotate")
kept = [line for line in lines if not line.startswith(("OPENCLAW_WEBHOOK_SECRET=", "OPENCLAW_WEBHOOK_SECRET_PREV="))]
if mode == "start":
    if values.get("OPENCLAW_WEBHOOK_SECRET_PREV"):
        sys.exit("a rotation is already in progress: run finish first")
    kept += [f"OPENCLAW_WEBHOOK_SECRET={secrets.token_urlsafe(32)}", f"OPENCLAW_WEBHOOK_SECRET_PREV={current}"]
else:
    kept += [f"OPENCLAW_WEBHOOK_SECRET={current}"]
path.write_text("\n".join(kept) + "\n", encoding="utf-8")
PY

"$root/infra/secrets/push-env.sh" "$env_file"
if [[ "$mode" == start ]]; then
    echo "pushed a new webhook secret; the old one stays valid. After the next deploy cycle, run: $0 finish $env_file"
else
    echo "pushed the finished rotation; the old webhook secret stops working after the next deploy cycle"
fi
