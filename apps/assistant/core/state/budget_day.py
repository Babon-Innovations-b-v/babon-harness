"""`budget_day` table adapter, durable daily Anthropic spend counter.

Storage-grammar table adapter (blueprint §2.3): the charge upsert and
the spend read live together. Durability is the point:
a pod restart no longer zeroes the counter, so a CrashLoop can't reset
spend and burn the daily cap. The cap policy lives in `shared.budget`;
this adapter only stores euros.

FAILURE POLICY: Tier-1 fail-loud, a failed budget write propagates.
Silently losing a charge would let spend run past the cap (the house rules
anti-pattern).
"""
from __future__ import annotations

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.today_utc import today_utc


def budget_spend_today_eur() -> float:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT spend_eur FROM budget_day WHERE day_utc = ?",
            (today_utc(),),
        ).fetchone()
    if row is None:
        return 0.0
    return float(row["spend_eur"])


def budget_charge(cost_eur: float) -> None:
    today = today_utc()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO budget_day (day_utc, spend_eur, calls) VALUES (?, ?, 1) "
            "ON CONFLICT(day_utc) DO UPDATE SET "
            "spend_eur = spend_eur + ?, calls = calls + 1",
            (today, cost_eur, cost_eur),
        )
        conn.commit()
