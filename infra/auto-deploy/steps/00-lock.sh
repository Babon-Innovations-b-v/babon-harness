#!/bin/bash
# Step 00: serialise the cycle with flock(1) on fd 9, before anything else runs.
#
# FAILURE POLICY: if another cycle holds the lock, log and exit 0; the timer
# fires again in two minutes. The kernel releases the lock on SIGKILL, OOM and
# reboot, so a stale lockfile on disk never blocks (the flock test, not a file
# test, is the guard).
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

# The clone this file lives in is the repository the cycle deploys:
# $HARNESS_ROOT/repo/infra/auto-deploy/steps/00-lock.sh.
REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
HARNESS_ROOT="${HARNESS_ROOT:-$(dirname "$REPO")}"
LOCK="${AUTO_DEPLOY_LOCK:-/tmp/harness-deploy.lock}"
STATE_DIR="${AUTO_DEPLOY_STATE_DIR:-/var/lib/harness}"
LAST_SHA_FILE="$STATE_DIR/last-deployed-sha"

# Where the cycle builds from: an export of the commit the gate verifies, one
# directory per sha. The gate's environment is a SIBLING of the export, never
# inside it, because the export is also a docker build context and a venv in it
# would be sent to the daemon once per service. Both on one filesystem with
# ~/.cache/uv, so uv hardlinks instead of copying.
BUILD_TREE_ROOT="${AUTO_DEPLOY_BUILD_ROOT:-$HARNESS_ROOT/build-tree}"
GATE_VENV_ROOT="${AUTO_DEPLOY_GATE_VENV_ROOT:-$HARNESS_ROOT/gate-venv}"
BUILD_TREE_MIN_FREE_MB="${AUTO_DEPLOY_BUILD_MIN_FREE_MB:-2048}"
# A passed tree that outlives the cycle, for anything that bind-mounts it.
VERIFIED_ROOT="${AUTO_DEPLOY_VERIFIED_ROOT:-$HARNESS_ROOT/verified-trees}"
VERIFIED_KEEP="${AUTO_DEPLOY_VERIFIED_KEEP:-3}"

# The log lives on a disk that survives a reboot; /tmp only when that fails.
LOG_DIR="${AUTO_DEPLOY_LOG_DIR:-/var/log/harness}"
if [ ! -w "$LOG_DIR" ]; then
    sudo -n install -d -m 0755 -o "$(id -un)" -g "$(id -gn)" "$LOG_DIR" >/dev/null 2>&1 || true
fi
if [ -w "$LOG_DIR" ]; then
    LOG="$LOG_DIR/auto-deploy.log"
else
    LOG="/tmp/harness-auto-deploy.log"
fi

# The verdict files. Both fail toward MORE work: anything unreadable, malformed
# or stale means run the gate again.
#   gate-verdicts/<sha>  "<sha> <green|red> <scope> <epoch> <reason> <tree>"
#                        one per commit, so several runs can be in flight.
#   deploy-verdict       "<sha> <success|partial_fail|gate_red|ship_abandoned|noop> <epoch>"
#                        what the cycle decided; written for a person.
#   build-head-red       "<bookmark> <head> <epoch> <reason> <count>": a red on a
#                        range of several commits names no commit, so it is not a
#                        verdict; step 20 reads it to drop back to one commit.
GATE_VERDICT_DIR="$STATE_DIR/gate-verdicts"
GATE_VERDICT_FILE="$STATE_DIR/gate-verdict"
BUILD_HEAD_RED_FILE="$STATE_DIR/build-head-red"
DEPLOY_VERDICT_FILE="$STATE_DIR/deploy-verdict"
PAGED_DIR="$STATE_DIR/paged"

log() { echo "[$(date -Iseconds)] $*" >> "$LOG"; }

exec 9>"$LOCK"
if ! flock -n 9; then
    log "previous run still active; skipping cycle"
    exit 0
fi
# fd 9 stays open for the script's lifetime; flock releases it on exit.

# Safe only here: we hold the lock, so every leftover snapshot is a dead cycle's.
rm -rf /tmp/harness-deploy-steps-* 2>/dev/null || true
