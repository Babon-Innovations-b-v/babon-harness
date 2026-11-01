"""A Talk call that is not recordable yet is retried without paging, and a real refusal pages once.

WHAT IT PINS. `start_recording_with_retry` in
`app/core/sessions/recording_guard.py`, the seam between `call_started` and a
recording actually running. Nextcloud fires `call_started` before the call is
recordable and answers the first start with `400 {"error": "call"}`; giving up
there loses the meeting in silence, and paging there pages on every call.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the shape
of the OCS answers themselves: `400` with `ocs.data.error == "call"` is the
"not in progress yet" race, `200` is a started recording, and `403` is a real
refusal. A scripted Talk answers race, race, started for the first call and
refusal for the second; the clock and sleep are fakes, so no time passes.

WHAT IT WAS PROVED AGAINST. Reading the race as a real error, so the first
call pages and gives up on its first answer and the first assertions trip.
"""
from __future__ import annotations

import json

from apps.notulen.app.core.sessions.recording_guard import start_recording_with_retry

_RACE = (400, json.dumps({"ocs": {"data": {"error": "call"}}}))
_STARTED = (200, json.dumps({"ocs": {"data": []}}))
_REFUSED = (403, json.dumps({"ocs": {"data": []}}))


def _run(answers: list[tuple[int, str]]) -> tuple[bool, int, list[str]]:
    """Run the guard against scripted answers; return (started, posts, pages)."""
    remaining = list(answers)
    posts: list[str] = []
    pages: list[str] = []

    def post_start(token: str) -> tuple[int, str]:
        posts.append(token)
        return remaining.pop(0)

    started = start_recording_with_retry(
        "roomtoken1",
        post_start=post_start,
        is_active=lambda token: True,
        on_failed=lambda token, reason: pages.append(reason),
        sleep=lambda seconds: None,
        monotonic=lambda: 0.0,
    )
    return started, len(posts), pages


def test_a_talk_call_that_is_not_recordable_yet_is_retried_without_paging_and_a_real_refusal_pages_once() -> None:
    """Race twice then start: started, three posts, no page. Refusal: one page."""
    started, posts, pages = _run([_RACE, _RACE, _STARTED])
    assert started is True
    assert posts == 3
    assert pages == []

    started, posts, pages = _run([_REFUSED])
    assert started is False
    assert posts == 1
    assert len(pages) == 1
