"""A meeting handed to the GPU skips the CPU path, and the held GPU is always released.

WHAT IT PINS. `minutes.process_job`, the pipeline from an uploaded recording to
minutes: a recording the GPU tier takes is marked `transcribing` and left to
the worker; a dispatch that raises fails the job; on the CPU path a recording
with almost no words is `no_speech`, one under five minutes is `too_short`,
and a real meeting is structured and stored as `committing` before its commit
is tried. Whichever way it goes, the GPU held while the meeting recorded is
released. Every collaborator (dispatch, storage, ffmpeg, whisper, the model,
the commit, the job row) is replaced by a recorder.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each case is a
made-up transcript and duration, and the status sequence is written from the
module's stated thresholds: fewer than 50 words is no speech, under 300
seconds is too short, anything else goes structuring then committing.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row never
releases the held GPU, so every case fails.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

process_module = importlib.import_module("apps.notulen.app.core.minutes.process_job")

MEETING = " ".join(["word"] * 120)

CASES = [
    pytest.param("gpu", None, ["transcribing"], id="the-gpu-takes-it"),
    pytest.param("raises", None, ["failed"], id="a-dispatch-that-raises-fails-the-job"),
    pytest.param("cpu", ("hello there", 900.0), ["transcribing", "no_speech"], id="no-speech"),
    pytest.param("cpu", (MEETING, 120.0), ["transcribing", "too_short"], id="shorter-than-a-meeting"),
    pytest.param("cpu", (MEETING, 1800.0), ["transcribing", "structuring", "committing"], id="a-real-meeting"),
]


@pytest.mark.parametrize("dispatch, heard, expected", CASES)
def test_a_meeting_handed_to_the_gpu_skips_the_cpu_path_and_the_held_gpu_is_always_released(
        dispatch: str, heard: tuple | None, expected: list, monkeypatch: pytest.MonkeyPatch) -> None:
    """The statuses the job row moved through are the hand-derived ones, and the GPU was released once."""
    statuses: list[str] = []
    released: list[str] = []

    def dispatched(*_args) -> bool:
        if dispatch == "raises":
            raise RuntimeError("cluster refused the Job")
        return dispatch == "gpu"

    monkeypatch.setattr(process_module, "try_dispatch_gpu", dispatched)
    monkeypatch.setattr(process_module, "release_gpu", released.append)
    monkeypatch.setattr(process_module, "update_job", lambda job_id, **fields: statuses.append(fields["status"]))
    monkeypatch.setattr(process_module, "session_files", lambda job_id: SimpleNamespace(cleanup=lambda: None))
    monkeypatch.setattr(process_module, "get_s3", lambda: SimpleNamespace(download_file=lambda *args: None))
    monkeypatch.setattr(process_module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(process_module, "transcribe_cpu", lambda wav_path: heard)
    monkeypatch.setattr(process_module, "generate_notulen", lambda *args: "# Minutes\n")
    monkeypatch.setattr(process_module, "finalize_commit", lambda *args: "https://example.org/minutes")
    monkeypatch.setattr(process_module, "get_db", lambda: None)
    process_module.process_job("job-1", "uploads/job-1.webm", "Weekly", "2026-05-04", ["Sam"])
    assert (statuses, released) == (expected, ["job-1"])
