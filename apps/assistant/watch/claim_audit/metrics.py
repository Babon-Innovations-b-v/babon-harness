"""The audit's outcome as a node-exporter textfile, so a bad week is a number.

Same contract and same reasoning as every textfile metric here: the only
other trace of a run is a Talk post, and a Talk post nobody opens is
indistinguishable from a run that never happened. Written into the textfile
directory the seven bash collectors use, because it is the only path from the
VM into Prometheus that needs no listening port, and replaced atomically so a
scrape never reads half a file.

WHAT THE SENTINELS MEAN. `harness_claim_audit_findings` and
`harness_claim_audit_messages` are counts and cannot be negative, so neither
carries a second meaning. `harness_claim_audit_unbacked_messages` is the count of
messages in the window with no readings recorded, which is the number that says
how much of the audit could actually run: a week where every message predates
the recording reads clean and means nothing.

THE TWO FAMILIES, and what each cannot say. The per-road
ratio is emitted ONLY for the roads a share can honestly be computed for, and
`harness_claim_audit_uncounted_roads` says how many roads were left out of it. A
dashboard averaging the ratio without that second number averages over whichever
roads keep the best records. `harness_claim_audit_unheard_subjects` and its
critical variant count subjects nothing was ever delivered about;
`harness_claim_audit_held_messages` counts what is waiting on purpose behind the
quiet-hours and pacing brakes, which is not a fault and must never be alerted on
as one. The unheard families count DECISIONS THE POD MADE and never arrivals at
Alertmanager: a null receiver, an inhibit rule, an operator silence, a
group_wait fold, a refused bearer and a malformed body all leave zero rows, so a
night the webhook was broken publishes a confident zero here.

FAILURE POLICY: Tier-2. A directory this process cannot write is logged and
returns False. Losing the metric is worse than losing nothing and better than
losing the report.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path

log = logging.getLogger("openclaw.claim_audit.metrics")

OUT_DIR_ENV = "OPENCLAW_CLAIM_AUDIT_TEXTFILE_DIR"
DEFAULT_OUT_DIR = "/var/lib/node-exporter-textfile"
FILENAME = "openclaw_claim_audit.prom"


def render(
    *,
    messages: int,
    findings: int,
    unbacked: int,
    at: float,
    road_shares: Mapping[str, float] | None = None,
    uncounted_roads: int = 0,
    unheard: int = 0,
    unheard_critical: int = 0,
    held: int = 0,
) -> str:
    """The exposition text. Pure, so a test can read it without a filesystem."""
    return "\n".join([
        "# HELP harness_claim_audit_messages Messages the last audit judged.",
        "# TYPE harness_claim_audit_messages gauge",
        f"harness_claim_audit_messages {messages}",
        ("# HELP harness_claim_audit_findings Claims the last audit could not "
         "support from the readings recorded beside them."),
        "# TYPE harness_claim_audit_findings gauge",
        f"harness_claim_audit_findings {findings}",
        ("# HELP harness_claim_audit_unbacked_messages Messages in the window "
         "with no readings recorded, which the evidence-taking rules could not "
         "run on at all."),
        "# TYPE harness_claim_audit_unbacked_messages gauge",
        f"harness_claim_audit_unbacked_messages {unbacked}",
        ("# HELP harness_claim_audit_road_readings_ratio Share of the messages a "
         "road sent that carry the readings behind them. Emitted only for the "
         "roads both a delivery count and a readings count exist for."),
        "# TYPE harness_claim_audit_road_readings_ratio gauge",
        *_road_lines(road_shares),
        ("# HELP harness_claim_audit_uncounted_roads Roads no share could be "
         "computed for, each named in the report with the reason. Read this "
         "beside the ratio above: without it the ratio averages over whichever "
         "roads keep the best records."),
        "# TYPE harness_claim_audit_uncounted_roads gauge",
        f"harness_claim_audit_uncounted_roads {uncounted_roads}",
        ("# HELP harness_claim_audit_unheard_subjects Subjects that arrived in "
         "the window and were never delivered about. Counts decisions the pod "
         "made, never arrivals at Alertmanager."),
        "# TYPE harness_claim_audit_unheard_subjects gauge",
        f"harness_claim_audit_unheard_subjects {unheard}",
        ("# HELP harness_claim_audit_unheard_critical_subjects The unheard "
         "subjects that could be the first word about an outage. A judged "
         "silence is normal; this is the variant worth acting on."),
        "# TYPE harness_claim_audit_unheard_critical_subjects gauge",
        f"harness_claim_audit_unheard_critical_subjects {unheard_critical}",
        ("# HELP harness_claim_audit_held_messages Messages waiting on purpose "
         "behind the quiet-hours and pacing brakes at the moment of the read. "
         "Held is not unheard and must not be alerted on as a fault."),
        "# TYPE harness_claim_audit_held_messages gauge",
        f"harness_claim_audit_held_messages {held}",
        ("# HELP harness_claim_audit_last_run_timestamp_seconds Unix time the "
         "last audit finished."),
        "# TYPE harness_claim_audit_last_run_timestamp_seconds gauge",
        f"harness_claim_audit_last_run_timestamp_seconds {at:.0f}",
        "",
    ])


def _road_lines(road_shares: Mapping[str, float] | None) -> list[str]:
    """One labelled sample per road a share exists for, in a stable order.

    No sample at all for a road with no share, which is the point: a road that
    sent nothing has not achieved perfect coverage, and publishing a 1.0 for it
    would clear it every week it stays dead.
    """
    name = "harness_claim_audit_road_readings_ratio"
    return [
        f'{name}{{road="{road}"}} {share:.4f}'
        for road, share in sorted((road_shares or {}).items())
    ]


def publish(text: str) -> bool:
    """Write the exposition atomically. False when it could not be written."""
    target = Path(os.environ.get(OUT_DIR_ENV, DEFAULT_OUT_DIR)) / FILENAME
    try:
        scratch = target.with_suffix(".prom.tmp")
        scratch.write_text(text)
        scratch.replace(target)
        target.chmod(0o644)
        return True
    except OSError as exc:
        log.error("could not publish %s: %s", target, exc)
        return False
