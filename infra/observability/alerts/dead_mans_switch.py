"""Dead-man's switch: page when the alerting pipeline itself goes silent.

Prometheus fires an alert called `Watchdog` all the time (rules/watchdog.yml),
and Alertmanager routes it to a receiver that sends nothing. Every link of the
pipeline sits upstream of it: if Prometheus, a rule file or Alertmanager
breaks, `Watchdog` stops being refreshed in Alertmanager. This oneshot runs
every 15 minutes, reads Alertmanager's API directly (ALERTMANAGER_URL, default
the loopback port compose publishes), and pages straight through signal-cli
when the heartbeat has been unseen for more than an hour. After a page it
waits another full hour before nagging again.

State: `$HARNESS_STATE_DIR/dead_mans_state.json`.

FAILURE POLICY: Tier 1, this IS the canary. A crash propagates so the unit
fails and `harness-notify-failure@` pages. The two narrow swallows (state read,
Alertmanager fetch) both degrade toward paging, never toward silence.
"""
from __future__ import annotations

import calendar
import json
import logging
import os
import sys
import time
import urllib.request

from infra.observability.alerts.deadman import state_dir
from infra.observability.alerts.notify import fan_out

log = logging.getLogger("harness.dead_mans_switch")


def _state_path():
    return state_dir() / "dead_mans_state.json"


def _load_state() -> dict:
    # A missing or corrupt state file means "never seen, never paged", which
    # pages: the safe direction for a dead-man's switch.
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def watchdog_seen_ts(alertmanager_url: str, watchdog_name: str) -> float | None:
    """Most recent `updatedAt` of the Watchdog alert (epoch seconds), or None.

    Unreachable Alertmanager returns None, which `should_page` reads as silence.
    """
    try:
        with urllib.request.urlopen(f"{alertmanager_url}/api/v2/alerts", timeout=10) as response:
            alerts = json.loads(response.read())
    except Exception as exc:  # noqa: BLE001 (degrade toward a page)
        log.warning("alertmanager fetch failed: %s", exc)
        return None
    most_recent: float | None = None
    for alert in alerts:
        if (alert.get("labels") or {}).get("alertname") != watchdog_name:
            continue
        try:
            seen = calendar.timegm(time.strptime((alert.get("updatedAt") or "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            continue
        if most_recent is None or seen > most_recent:
            most_recent = seen
    return most_recent


def should_page(
    *,
    last_seen_ts: float | None,
    last_paged_ts: float | None,
    now: float,
    silent_threshold_s: int,
    repage_interval_s: int,
) -> bool:
    """Page when the heartbeat is older than the threshold and no page went out
    within the repage interval. A heartbeat never seen pages once, then hourly."""
    if last_paged_ts is not None and (now - last_paged_ts) < repage_interval_s:
        return False
    if last_seen_ts is None:
        return True
    return (now - last_seen_ts) >= silent_threshold_s


def main() -> int:
    alertmanager_url = os.environ.get("ALERTMANAGER_URL", "http://127.0.0.1:9094").rstrip("/")
    silent_threshold_s = int(os.environ.get("DEAD_MANS_SILENT_THRESHOLD_S", "3600"))
    repage_interval_s = int(os.environ.get("DEAD_MANS_REPAGE_INTERVAL_S", "3600"))
    state = _load_state()
    now = time.time()
    seen = watchdog_seen_ts(alertmanager_url, "Watchdog")
    if seen is not None:
        state["last_watchdog_seen_ts"] = seen
    last_seen = state.get("last_watchdog_seen_ts")
    if should_page(
        last_seen_ts=last_seen,
        last_paged_ts=state.get("last_paged_ts"),
        now=now,
        silent_threshold_s=silent_threshold_s,
        repage_interval_s=repage_interval_s,
    ):
        silent_for = f"{int((now - last_seen) // 60)} min" if last_seen is not None else "ever (never seen)"
        result = fan_out(
            "Dead-man: the alerting pipeline is silent",
            f"Alertmanager has not seen the Watchdog heartbeat for {silent_for}.\n"
            "Prometheus -> Alertmanager -> alert-relay is broken somewhere, so no "
            "other alert can reach you right now.\n"
            "Look: docker compose ps prometheus alertmanager alert-relay",
            signal_direct=True,
        )
        log.error("dead-man paged: %s", result)
        if any(result.values()):
            state["last_paged_ts"] = now
    else:
        log.info("ok (watchdog last seen %s)", last_seen)
    _save_state(state)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
