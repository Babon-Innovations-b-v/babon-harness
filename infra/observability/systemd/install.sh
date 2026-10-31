#!/usr/bin/env bash
# Install (or refresh) the observability systemd units. Run as root on the
# server, from the deploy loop or by hand; safe to repeat.
#
#   sudo HARNESS_ROOT=/opt/harness infra/observability/systemd/install.sh
#
# The unit files name /opt/harness; this rewrites that to HARNESS_ROOT, copies
# every harness-* unit here into /etc/systemd/system, creates the state and
# textfile directories, and enables the timers. Any other harness unit can
# page on failure by adding: OnFailure=harness-notify-failure@%n.service
set -euo pipefail

HARNESS_ROOT="${HARNESS_ROOT:-/opt/harness}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

install -d -m 0755 /var/lib/harness /var/lib/harness/textfile

changed=0
for unit in "$HERE"/harness-*.service "$HERE"/harness-*.timer; do
    name="$(basename "$unit")"
    rendered="$(sed "s|/opt/harness|${HARNESS_ROOT}|g" "$unit")"
    if [[ ! -f "$TARGET_DIR/$name" ]] || [[ "$(cat "$TARGET_DIR/$name")" != "$rendered" ]]; then
        printf '%s\n' "$rendered" > "$TARGET_DIR/$name"
        changed=1
    fi
done

if [[ "$changed" == 1 ]]; then
    systemctl daemon-reload
fi

for timer in "$HERE"/harness-*.timer; do
    systemctl enable --now "$(basename "$timer")" >/dev/null
done
echo "observability units installed (root ${HARNESS_ROOT})"
