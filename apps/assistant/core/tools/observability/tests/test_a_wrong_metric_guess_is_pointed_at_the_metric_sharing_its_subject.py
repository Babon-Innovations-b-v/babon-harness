"""A wrong metric guess is pointed at the real metric that shares its subject.

WHAT IT PINS. `prom_query._unknown_names_refusal`, the text a guessed metric
name is refused with: the hint names the real metric that shares the guess's
distinctive words before names that are only spelled alike. Otherwise a
guess such as ops_alert_drill_age_days would be offered only
ops_secret_age_days and ops_secret_max_age_days, and the drill metric would
go unread.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The known names
are a small set Prometheus could hold, and the real drill metric is read from
the drill's own configuration (`delivery_drill._config.METRIC_NAME`). Its
difflib ratio against the guess is 0.47, under the 0.5 cutoff, which is why a
spelling-only hint cannot name it; it shares "alert" and "drill" with the
guess, which is what a reader means by the same subject.
"""
from __future__ import annotations

from apps.assistant.core.tools.observability import prom_query

_DRILL_METRIC = "harness_alert_delivery_drill_last_success_timestamp_seconds"

_KNOWN = frozenset(
    {
        "ops_secret_age_days",
        "ops_secret_max_age_days",
        _DRILL_METRIC,
        "up",
    }
)


def test_a_wrong_metric_guess_is_pointed_at_the_metric_sharing_its_subject() -> None:
    refusal = prom_query._unknown_names_refusal(["ops_alert_drill_age_days"], _KNOWN)

    hint = refusal.split("Closest real names: ", 1)[1]
    assert hint.startswith(_DRILL_METRIC), refusal


def test_a_guess_spelled_like_a_real_name_still_gets_it() -> None:
    refusal = prom_query._unknown_names_refusal(["ops_secret_age_day"], _KNOWN)

    assert "ops_secret_age_days" in refusal
