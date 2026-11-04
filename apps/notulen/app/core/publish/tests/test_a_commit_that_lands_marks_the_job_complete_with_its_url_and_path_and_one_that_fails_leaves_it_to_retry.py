"""A commit that lands marks the job complete with its URL and path, and one that fails leaves it to retry.

WHAT IT PINS. How the two modules of `publish` fit: `retry.finalize_commit`
hands the minutes to `github.commit_notulen_to_github` and marks the job
complete only with what the commit returned. The seam is `finalize_commit`
with the real GitHub writer behind it, talking to an in-memory stand-in for
the Contents API, and a recorder in place of the job table, so nothing leaves
the box.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each case is a
repository state made up here: empty, the day's file already holding other
minutes, or a write the API refuses. The expected path is cut by hand from the
folder, the month, the attendees' first names sorted (`alex_sam`) and the
day, with `-2` when the first path is taken; the URL is the one the stand-in
answers with. A refused write must leave the job untouched for the retry loop.

ONE FUNCTION. This group's one test. A new check is a parametrized case of it,
never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row records the
commit URL where the file's path belongs, so the two landed cases fail.

GUARDS. One test per module group (#1210), 2026-11-04.
"""
from __future__ import annotations

import base64
import functools

import pytest

from apps.notulen.app.core.publish import commit_notulen_to_github, finalize_commit

FOLDER = "minutes"
COMMIT_URL = "https://example.com/team/notes/commit/abc123"
FIRST = f"{FOLDER}/2026-05/alex_sam/2026-05-04.md"
SECOND = f"{FOLDER}/2026-05/alex_sam/2026-05-04-2.md"

CASES = [
    pytest.param({}, 201, (COMMIT_URL, FIRST), id="empty-repository-lands-on-the-first-path"),
    pytest.param({FIRST: "# Earlier meeting\n"}, 201, (COMMIT_URL, SECOND), id="a-taken-path-is-never-overwritten"),
    pytest.param({}, 422, None, id="a-refused-write-stays-for-the-retry"),
]


class _Refused(Exception):
    """What the stand-in raises for a status the real API would refuse."""


class _Answer:
    def __init__(self, status: int, body: dict) -> None:
        self.status_code, self._body = status, body

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise _Refused(f"{self.status_code}")


class _ContentsApi:
    """The repository's files by path, answering GET and PUT as the Contents API does."""

    def __init__(self, files: dict[str, str], put_status: int) -> None:
        self.files, self.put_status = dict(files), put_status

    def _path(self, url: str) -> str:
        return url.split("/contents/", 1)[1]

    def get(self, url: str, headers: dict) -> _Answer:
        text = self.files.get(self._path(url))
        if text is None:
            return _Answer(404, {})
        return _Answer(200, {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()})

    def put(self, url: str, headers: dict, json: dict) -> _Answer:
        if self.put_status >= 400:
            return _Answer(self.put_status, {})
        self.files[self._path(url)] = base64.b64decode(json["content"]).decode()
        return _Answer(self.put_status, {"commit": {"html_url": COMMIT_URL}})


@pytest.mark.parametrize("files, put_status, landed", CASES)
def test_a_commit_that_lands_marks_the_job_complete_with_its_url_and_path_and_one_that_fails_leaves_it_to_retry(
        files: dict, put_status: int, landed: tuple | None, monkeypatch: pytest.MonkeyPatch) -> None:
    """The job is marked complete with exactly the hand-derived URL and path, or not marked at all."""
    monkeypatch.setenv("NOTULEN_TARGET_PATH", FOLDER)
    monkeypatch.setenv("NOTULEN_TARGET_REPO", "team/notes")
    api = _ContentsApi(files, put_status)
    marked: list[dict] = []

    url = finalize_commit(
        "job-1", "Weekly sync", "2026-05-04", "# Weekly sync\n", ["Sam Example", "alex"],
        committer=functools.partial(commit_notulen_to_github, token="not-a-real-token", session=api),
        updater=lambda job_id, **fields: marked.append({"job_id": job_id, **fields}),
    )

    if landed is None:
        assert url is None and marked == []
        return
    assert url == landed[0]
    assert marked == [{"job_id": "job-1", "status": "complete",
                       "output_commit_url": landed[0], "output_path": landed[1]}]
