"""stack_status counts new pods apart from in-place restarts and shows the window before.

WHAT IT PINS. `stack_status.execute`, the tool's public interface, over a real
`pod_boots` table: the container-start line names new pods (rollouts or reschedules)
and in-place container restarts as two numbers, never one total called
"restarts", and it carries the previous window's numbers so a "was N" figure is
read from the answer rather than recalled.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Kubernetes
keeps a pod's name across a container restart in place and gives a replacement
pod a new one, so a pod name's first start is a new pod and every later start
of the same name is in place. The seeded history is counted by hand: this week
pods a, b, c start once each (3 new), a starts again and pod x, first seen 20
days ago, starts again (2 in place); the week before, pods d and e start once
(2 new, 0 in place).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apps.assistant.core import state
from apps.assistant.core.state import pod_boots
from apps.assistant.core.state.reset import reset_for_tests
from apps.assistant.core.tools.meta import stack_status


def _boot(monkeypatch, pod: str, days_ago: float) -> None:
    stamp = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    monkeypatch.setattr(pod_boots, "utcnow_iso", lambda: stamp)
    state.pod_boots.record_boot(pod)


def test_counts_new_pods_apart_from_in_place_restarts_and_shows_the_window_before(
    tmp_path, monkeypatch
) -> None:
    """This week reads 3 new and 2 in place, the week before 2 new and 0 in place."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    reset_for_tests()
    try:
        _boot(monkeypatch, "openclaw-x", 20)
        _boot(monkeypatch, "openclaw-d", 12)
        _boot(monkeypatch, "openclaw-e", 9)
        _boot(monkeypatch, "openclaw-a", 6)
        _boot(monkeypatch, "openclaw-b", 5)
        _boot(monkeypatch, "openclaw-a", 4)
        _boot(monkeypatch, "openclaw-x", 3)
        _boot(monkeypatch, "openclaw-c", 1)
        answer = stack_status.execute({})
    finally:
        reset_for_tests()
    assert "(last 7d): 3 new pods, 2 in-place container restarts" in answer
    assert "the 7d before that: 2 new pods, 0 in-place container restarts" in answer
    assert "pod restarts" not in answer
