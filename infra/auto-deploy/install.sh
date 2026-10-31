#!/usr/bin/env bash
# First-time server setup for the deploy loop. Run as root, once, after the
# repository is cloned to $HARNESS_ROOT/repo and the vault cache
# ($HARNESS_ROOT/harness.env) has been pulled:
#
#   sudo HARNESS_ROOT=/opt/harness /opt/harness/repo/infra/auto-deploy/install.sh
#
# What it does, each step safe to repeat:
#   1. the deploy user (DEPLOY_USER, default `harness`), in the docker group
#   2. docker, uv (for the deploy user) and the adnanh/webhook binary
#   3. /var/lib/harness (state), /var/log/harness (logs), $HARNESS_ROOT ownership
#   4. git hooks for the server clone (core.hooksPath) and the deploy bookmark,
#      seeded at the commit that is checked out now, so the first cycle does not
#      redeploy everything seconds after the first start
#   5. a sudoers rule naming exactly what the cycle runs as root: systemctl, and
#      writing or removing unit files in /etc/systemd/system
#   6. the units in infra/auto-deploy/systemd and infra/webhook/systemd, rendered
#      for this box; every other unit in the repository is installed by the
#      deploy cycle itself (step 80) on its first green commit
#
# After it: point a GitHub webhook at https://deploy.$DOMAIN/hooks/deploy (the
# last lines print the exact command), and give DEPLOY_STATUS_TOKEN commit
# statuses and deployments on the repository.
#
# Note on the docker group: membership is root-equivalent on this machine. The
# deploy user runs every container, so that trust already exists; the sudoers
# rule below does not widen it.

set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
    echo "run me as root: sudo $0" >&2
    exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
HARNESS_ROOT="${HARNESS_ROOT:-$(dirname "$REPO")}"
DEPLOY_USER="${DEPLOY_USER:-harness}"
STATE_DIR="/var/lib/harness"
WEBHOOK_VERSION="${WEBHOOK_VERSION:-2.8.1}"
export HARNESS_ROOT DEPLOY_USER
LOG=/dev/null
log() { echo "[install] $*"; }
# shellcheck disable=SC1091
. "$HERE/steps/doors.sh"
harness_load_config "$REPO"

# 1. The deploy user.
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash "$DEPLOY_USER"
    log "created user $DEPLOY_USER"
fi

# 2. docker, uv, webhook.
if ! command -v docker >/dev/null 2>&1; then
    log "installing docker (get.docker.com)"
    curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "$DEPLOY_USER"
if ! sudo -u "$DEPLOY_USER" -H bash -lc 'command -v uv || test -x "$HOME/.local/bin/uv"' >/dev/null 2>&1; then
    log "installing uv for $DEPLOY_USER"
    sudo -u "$DEPLOY_USER" -H bash -lc 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi
if ! { [ -x /usr/local/bin/webhook ] && /usr/local/bin/webhook -version 2>&1 | grep -q "$WEBHOOK_VERSION"; }; then
    case "$(uname -m)" in
        x86_64) arch=amd64 ;;
        aarch64|arm64) arch=arm64 ;;
        *) echo "no webhook build for $(uname -m)" >&2; exit 1 ;;
    esac
    work="$(mktemp -d)"
    curl -fsSL -o "$work/webhook.tgz" \
        "https://github.com/adnanh/webhook/releases/download/${WEBHOOK_VERSION}/webhook-linux-${arch}.tar.gz"
    tar -xzf "$work/webhook.tgz" -C "$work"
    install -m 0755 "$work/webhook-linux-${arch}/webhook" /usr/local/bin/webhook
    rm -rf "$work"
    log "installed webhook $WEBHOOK_VERSION"
fi

# 3. Directories.
install -d -m 0755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$STATE_DIR" "$STATE_DIR/textfile" /var/log/harness
chown "$DEPLOY_USER:$DEPLOY_USER" "$HARNESS_ROOT"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$REPO"
if [ -f "$HARNESS_ROOT/harness.env" ]; then
    chown "$DEPLOY_USER:$DEPLOY_USER" "$HARNESS_ROOT/harness.env"
    chmod 600 "$HARNESS_ROOT/harness.env"
else
    log "WARNING: no vault cache at $HARNESS_ROOT/harness.env yet; pull it before the first deploy (infra/secrets/)"
fi

# 4. Git hooks and the bookmark.
sudo -u "$DEPLOY_USER" git -C "$REPO" config core.hooksPath .claude/hooks
if [ ! -f "$STATE_DIR/last-deployed-sha" ] && head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)"; then
    echo "$head" > "$STATE_DIR/last-deployed-sha"
    chown "$DEPLOY_USER:$DEPLOY_USER" "$STATE_DIR/last-deployed-sha"
    log "seeded the deploy bookmark at ${head:0:12}"
fi

# 5. sudoers.
sudoers="/etc/sudoers.d/harness-deploy"
cat > "$sudoers.tmp" <<EOF
# Installed by infra/auto-deploy/install.sh: what the deploy loop runs as root.
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl, /usr/bin/tee /etc/systemd/system/*, /usr/bin/rm -f /etc/systemd/system/*, /usr/bin/install -d -m 0755 -o $DEPLOY_USER -g $DEPLOY_USER /var/log/harness
EOF
if visudo -cf "$sudoers.tmp" >/dev/null; then
    install -m 0440 "$sudoers.tmp" "$sudoers"
    log "installed $sudoers"
fi
rm -f "$sudoers.tmp"

# 6. The deploy loop's own units.
manifest="$STATE_DIR/installed-units"
touch "$manifest"
for unit in "$HERE"/systemd/*.service "$HERE"/systemd/*.timer "$REPO"/infra/webhook/systemd/*.service; do
    [ -f "$unit" ] || continue
    name="$(basename "$unit")"
    harness_render_unit "$unit" > "/etc/systemd/system/$name"
    grep -qxF "$name" "$manifest" || echo "$name" >> "$manifest"
    log "installed $name"
done
chown "$DEPLOY_USER:$DEPLOY_USER" "$manifest"
systemctl daemon-reload
for timer in "$HERE"/systemd/*.timer; do
    systemctl enable --now "$(basename "$timer")" >/dev/null
done
systemctl enable --now harness-webhook.service >/dev/null || log "harness-webhook did not start; is DEPLOY_WEBHOOK_SECRET in the vault cache?"

slug="$(harness_repo_slug "$REPO")"
log "done. Check with: systemctl list-timers 'harness-*'"
log ""
log "Register the push webhook once, from a machine where gh is signed in:"
log "  gh api -X POST /repos/${slug:-<owner>/<repo>}/hooks -f name=web -F active=true \\"
log "    -f 'config[url]=https://deploy.${DOMAIN:-<your domain>}/hooks/deploy' -f 'config[content_type]=json' \\"
log "    -f \"config[secret]=\$DEPLOY_WEBHOOK_SECRET\" -f 'events[]=push'"
