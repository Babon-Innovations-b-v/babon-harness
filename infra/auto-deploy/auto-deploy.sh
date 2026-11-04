#!/bin/bash
# Auto-deploy: the whole CI/CD of this repository, run in the cluster.
#
# CronJob deploy-cycle (infra/k8s/deploy) runs this every two minutes, and the
# push receiver (infra/deploy_loop) starts it on every push to main.
# Pushing to main IS the deploy: the cycle takes ONE commit past the deploy
# bookmark, verifies it with the gate, rebuilds the containers it changed,
# checks they boot, and only then moves the bookmark.
#
# This file owns ONLY the step ordering. Every slice of behaviour lives in a
# step file under steps/, sourced below IN ORDER into this one shell process,
# so all steps share globals, helper functions and the lock on fd 9.
#
#   00-lock.sh               take the lock; paths and the log
#   10-prelude.sh            configuration, the vault cache, the kill switch,
#                            the shared result variables
#   15-freshness.sh          fast-forward the clone to origin/main
#   18-verdicts.sh           fetch verdicts from a verifying lane on another box
#   20-changes.sh            pick the one commit, diff it, decide the gate scope
#   35-export.sh             git archive the commit: the tree the gate verifies
#                            and every image is built from
#   40-gate.sh               the gate: pytest in a gate Job, narrowed, fails closed
#   45-verified.sh           keep a passed tree that outlives the cycle
#   50-deploy.sh             build the changed stack images (BuildKit), roll
#                            each out by digest, undo a rollout that fails
#   68-assistant-workspace.sh  render the assistant's workspace
#   80-manifests.sh          apply infra/k8s when the commit changed it
#   88-eject.sh              take a rejected commit back off main (armed in the shipped config)
#   90-outcome.sh            move the bookmark, post the statuses, clean up
#
# Not steps, sourced by the steps that need them: steps/doors.sh (config,
# alerts, GitHub), steps/cluster.sh (the cluster calls), steps/eject_body.sh,
# steps/build_verdict.sh, steps/red_triage.sh (whose fault a red is).
#
# FAILURE POLICY: declared per step. Summary: the gate fails CLOSED (red and
# amber both ship nothing); a failed build or boot holds the bookmark and the
# next cycle retries; everything edge- or cleanup-shaped is best-effort and may
# never block a deploy.

set -u

# Name the usual tool locations; the cycle's pod has no login shell.
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

AUTO_DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Explicit list, not a glob: a step that goes missing must be a loud sourcing
# error, never a silent skip.
# shellcheck disable=SC1091
. "$AUTO_DEPLOY_DIR/steps/00-lock.sh"

# ── Source the rest from a snapshot, not from the clone ─────────────────────
# Step 15 fast-forwards this very clone, and the steps after it are read off
# disk over minutes. A push landing mid-cycle could otherwise hand step 40 a
# different commit's step file than step 20 came from, and under `set -u` two
# step files that disagree about a variable kill the cycle with no record.
#
# The snapshot is taken AFTER the lock: most ticks exit inside step 00, and a
# snapshot above it would leak a directory per skipped tick.
#
# FAILURE POLICY: fail safe. No mktemp, no cp: the cycle runs off the clone.
STEPS_SNAPSHOT=""
if _snapshot_dir=$(mktemp -d -t harness-deploy-steps-XXXXXX 2>/dev/null) \
    && cp -R "$AUTO_DEPLOY_DIR/steps" "$_snapshot_dir/" 2>/dev/null; then
    STEPS_SNAPSHOT="$_snapshot_dir"
    AUTO_DEPLOY_DIR="$_snapshot_dir"
else
    rm -rf "${_snapshot_dir:-/nonexistent}" 2>/dev/null || true
fi
unset _snapshot_dir
. "$AUTO_DEPLOY_DIR/steps/10-prelude.sh"
. "$AUTO_DEPLOY_DIR/steps/15-freshness.sh"
. "$AUTO_DEPLOY_DIR/steps/18-verdicts.sh"
. "$AUTO_DEPLOY_DIR/steps/20-changes.sh"
. "$AUTO_DEPLOY_DIR/steps/35-export.sh"
. "$AUTO_DEPLOY_DIR/steps/40-gate.sh"
. "$AUTO_DEPLOY_DIR/steps/45-verified.sh"
. "$AUTO_DEPLOY_DIR/steps/50-deploy.sh"
. "$AUTO_DEPLOY_DIR/steps/68-assistant-workspace.sh"
. "$AUTO_DEPLOY_DIR/steps/80-manifests.sh"
. "$AUTO_DEPLOY_DIR/steps/88-eject.sh"
. "$AUTO_DEPLOY_DIR/steps/90-outcome.sh"
