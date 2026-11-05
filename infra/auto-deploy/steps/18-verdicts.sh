#!/bin/bash
# Step 18: keep the cycle and the verifying lane (../commit_gate/, CronJob
# commit-gate) in step: copy the verdicts the lane published into this cycle's
# state, then start the lane if no lane Job is running.
#
# The lane reads the bookmark ConfigMap itself and publishes its drawers
# (verdicts, eject decisions, failing-test tails, scope records, gate-run
# records) as ConfigMap commit-gate-verdicts (COMMIT_GATE_LANE_CONFIGMAP), so
# neither pod reaches into the other's volume. Nothing copied ever replaces a
# file this cycle already holds. Must stay above 20, which reads what it copied.
#
# FAILURE POLICY: every path returns 0. A verdict that does not arrive is a
# commit the cycle gates itself, which is what it does without a lane, so a
# lane that is down costs only speed. COMMIT_GATE_LANE_CONFIGMAP="" turns the
# step off.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

cluster_lane_verdicts_pull || true
cluster_lane_kick || true
