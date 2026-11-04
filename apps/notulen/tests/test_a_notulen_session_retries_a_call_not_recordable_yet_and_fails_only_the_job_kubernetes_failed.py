"""A notulen session retries a call that is not recordable yet without paging, pages a real refusal once, and fails only the job Kubernetes failed.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

A Talk call that is not recordable yet is retried without paging, and a real refusal pages once.

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

A notulen GPU job Kubernetes failed fails its row; a running or finished one does not.

WHAT IT PINS. `failed_job_reasons` in `app/core/sessions/dead_gpu_jobs.py`, the
seam that decides which rows the dead-GPU-job watch flips to `failed`. Reading a
finished Job as failed would fail a meeting whose minutes are being committed;
missing a failed one leaves the row "transcribing" for ever.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From what
Kubernetes reports for a Job killed at its deadline: condition `Failed`, reason
`DeadlineExceeded`, message "Job was active longer than specified deadline".
Beside it, a Job with condition `Complete` and one with no conditions yet, which
is what Kubernetes reports for a finished and a still-running Job. Only the
first may come back.

WHAT IT WAS PROVED AGAINST. Making the watch accept `Complete` as well as
`Failed`, so the finished Job is reported and the exact-mapping assertion trips.
"""
from __future__ import annotations

import inspect
import pytest


# From a talk call that is not recordable yet is retried without paging and a real refusal pages once.

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


def _a_talk_call_that_is_not_recordable_yet_is_retried_without_paging_and_a_real_refusal_pages_once() -> None:
    """Race twice then start: started, three posts, no page. Refusal: one page."""
    started, posts, pages = _run([_RACE, _RACE, _STARTED])
    assert started is True
    assert posts == 3
    assert pages == []

    started, posts, pages = _run([_REFUSED])
    assert started is False
    assert posts == 1
    assert len(pages) == 1

# From a notulen gpu job kubernetes failed fails its and a running or finished one does not.

import os


# A placeholder DSN for anything that resolves one at import. Nothing here
# opens a connection.
os.environ.setdefault("DB_URL", "postgresql://test/none")


from kubernetes.client import (  # noqa: E402
    V1Job,
    V1JobCondition,
    V1JobStatus,
    V1ObjectMeta,
)


from apps.notulen.app.core.sessions.dead_gpu_jobs import (  # noqa: E402
    failed_job_reasons,
)


DEAD = "00000000-0000-4000-8000-00000000dead"


FINISHED = "00000000-0000-4000-8000-00000000d0e5"


RUNNING = "00000000-0000-4000-8000-0000000000a1"


def _job(job_id: str, conditions: list[V1JobCondition] | None) -> V1Job:
    return V1Job(
        metadata=V1ObjectMeta(labels={"app": "notulen-worker", "job-id": job_id}),
        status=V1JobStatus(conditions=conditions),
    )


def _only_the_job_kubernetes_failed_is_reported_with_its_reason() -> None:
    """The deadline-killed Job comes back with Kubernetes' message; the others do not."""
    jobs = [
        _job(DEAD, [V1JobCondition(
            type="Failed", status="True", reason="DeadlineExceeded",
            message="Job was active longer than specified deadline",
        )]),
        _job(FINISHED, [V1JobCondition(type="Complete", status="True")]),
        _job(RUNNING, None),
    ]
    assert failed_job_reasons(jobs) == {
        DEAD: "Job was active longer than specified deadline",
    }


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_a_talk_call_that_is_not_recordable_yet_is_retried_without_paging_and_a_real_refusal_pages_once),
    *_cases(_only_the_job_kubernetes_failed_is_reported_with_its_reason),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_notulen_session_retries_a_call_not_recordable_yet_and_fails_only_the_job_kubernetes_failed(scenario, given, uses, request):
    """A notulen session retries a call that is not recordable yet without paging, pages a real refusal once, and fails only the job Kubernetes failed: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
