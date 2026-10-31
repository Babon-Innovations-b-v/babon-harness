"""Shared hard limits of the stack-liveness monitor, declared once.

The sweep loop, the check timeouts, and the flap-suppression threshold
all read from here (campaign rule: one home per duplicated constant).
`core/limits.py` holds the LLM-loop caps; these are the monitor's own.

FAILURE POLICY: constants only, nothing to fail.
"""
from __future__ import annotations

# How long the background runner sleeps between sweeps. ~60s gives a
# down-detection latency of DOWN_THRESHOLD * SWEEP_INTERVAL_SECONDS (≈3
# min at the defaults), matching the issue's "within the threshold
# window".
SWEEP_INTERVAL_SECONDS = 60

# Consecutive failed checks before a poll component flips to `down`. A
# down PAGE fires only on the transition into down, so a single flaky
# check never pages. Recovery is first-ok-after-down (no threshold).
DOWN_THRESHOLD = 3

# How many consecutive failed checks before a component that is ALREADY
# down is raised to the digest again. The digest only ever sees
# TRANSITIONS, so before this a component that flipped down got exactly
# one look: if that look said SILENT, nothing ever mentioned it again,
# however long it stayed down. A wrong silence was permanent, and so was
# a correct one whose reason expired ("a deploy just landed" is fine at
# minute one and not at hour three).
#
# 60 sweeps at SWEEP_INTERVAL_SECONDS is roughly hourly. It re-raises,
# it does not re-page: the digest still decides whether to speak, so a
# genuinely quiet thing stays quiet and costs one judgement an hour.
STILL_DOWN_REPAGE_EVERY = 60

# Per-check network timeout (HTTP GET, DB connect, external probe). Kept
# short so one unreachable component can't stall the whole sweep: worst
# case a sweep takes len(registry) * CHECK_TIMEOUT_SECONDS, and it runs
# off the event loop in a daemon thread so /health is never blocked.
CHECK_TIMEOUT_SECONDS = 5
