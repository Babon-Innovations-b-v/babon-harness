#!/bin/bash
# Run by the webhook listener (harness-webhook.service) on each push to main.
#
#   $1 = head_commit.id   $2 = pusher.name    (from the GitHub payload)
#
# It pulls the new commit into the clone, then starts the verifying lane and a
# deploy cycle without waiting for either, so GitHub gets its answer at once.
# The deploy cycle's lock serialises it against the timer and against
# back-to-back pushes.
#
# THE REPAIR LIVES HERE AND NOWHERE ELSE. The cycle's step 15 only fast-forwards
# a clone that is behind. When a fetch or a rebase fails here, the clone is
# dirty or has diverged: every dirty tracked file is copied to
# $HARNESS_ROOT/repo-selfheal/<time>/ first (nothing is ever destroyed), then the
# clone is reset to origin/main. It alerts only for what it could NOT fix, or
# when somebody's edits on the server were parked: a repair that worked and lost
# nothing pages nobody.
#
# A reset that loses git's index lock to a concurrent git process is a race
# with the cycle's own step 15, which is moving the clone itself; that pages
# nobody either.
#
# FAILURE POLICY: always starts the cycle, whatever happened above, and always
# exits 0.

set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HARNESS_ROOT="${HARNESS_ROOT:-$(dirname "$REPO")}"
LOG_DIR="${AUTO_DEPLOY_LOG_DIR:-/var/log/harness}"
LOG="${WEBHOOK_LOG:-$LOG_DIR/webhook.log}"
{ : >> "$LOG"; } 2>/dev/null || LOG="/tmp/harness-webhook.log"
SHA="${1:-unknown}"
PUSHER="${2:-unknown}"
log() { echo "[$(date -Iseconds)] $*" >> "$LOG"; }

# This exact line is what step 15 looks for to tell a push the listener saw
# from one only the timer brought in. Keep the "commit <sha8> " shape.
log "push from ${PUSHER}, commit ${SHA:0:8} - pulling and starting a deploy"

if ! { git -C "$REPO" fetch --quiet origin main >> "$LOG" 2>&1 \
        && git -C "$REPO" rebase --autostash origin/main >> "$LOG" 2>&1; }; then
    log "fetch or rebase failed; parking local edits and resetting to origin/main"
    git -C "$REPO" rebase --abort >> "$LOG" 2>&1 || true
    git -C "$REPO" merge --abort >> "$LOG" 2>&1 || true
    backup_dir="$HARNESS_ROOT/repo-selfheal/$(date +%Y%m%d-%H%M%S)"
    dirty_files=$(git -C "$REPO" status --porcelain=v1 | grep -v '^??' | sed 's/^...//; s/^.* -> //; s/^"//; s/"$//')
    if [ -n "$dirty_files" ]; then
        mkdir -p "$backup_dir"
        printf '%s\n' "$dirty_files" | while IFS= read -r dirty_file; do
            [ -f "$REPO/$dirty_file" ] && ( cd "$REPO" && cp --parents "$dirty_file" "$backup_dir/" ) 2>/dev/null
        done
        log "parked local edits in $backup_dir"
    fi
    reset_failed=""
    reset_output=$(mktemp)
    git -C "$REPO" reset --hard origin/main > "$reset_output" 2>&1 || reset_failed=1
    cat "$reset_output" >> "$LOG"
    if [ -n "$reset_failed" ] && grep -qE 'index\.lock|Another git process seems to be running' "$reset_output"; then
        reset_failed=""
        log "the reset lost the index lock to a concurrent git process (the deploy cycle's own fast-forward); paging nobody"
    fi
    rm -f "$reset_output"
    if [ -n "$dirty_files" ] || [ -n "$reset_failed" ]; then
        if [ -n "$reset_failed" ]; then
            subject="deploy webhook: the server clone is still stale"
            body="reset --hard could not repair the clone on push ${SHA:0:8}; deploys keep using stale code. See $LOG."
        else
            subject="deploy webhook: local edits on the server were parked"
            body="The clone had uncommitted edits on push ${SHA:0:8} and was reset to origin/main. The edits are in $backup_dir; nothing is lost, but they are not on main."
        fi
        if [ -r "$REPO/infra/auto-deploy/steps/doors.sh" ]; then
            # shellcheck disable=SC1091
            . "$REPO/infra/auto-deploy/steps/doors.sh" && harness_load_config "$REPO" \
                && fire_alert "$subject" "$body" --wakes-somebody
        fi
    else
        log "the clone had drifted with no local edits; reset to origin/main, paging nobody"
    fi
fi

# The lane first: it gains most from starting early, ships nothing and holds no
# deploy lock. Optional: a refused start costs five minutes, never a deploy.
sudo -n /usr/bin/systemctl start --no-block harness-commit-gate.service 2>>"$LOG" \
    || log "could not start harness-commit-gate (its timer covers this)"
sudo -n /usr/bin/systemctl start --no-block harness-auto-deploy.service 2>>"$LOG" \
    || log "could not start harness-auto-deploy (its two-minute timer covers this)"
log "deploy started at HEAD=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null)"
exit 0
