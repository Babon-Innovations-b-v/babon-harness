"""A metric is pushed as one group replacement when a Pushgateway is set, and written whole as a textfile otherwise.

WHAT IT PINS. `infra.observability.node_textfile.textfile.publish`, the one
call every job's metrics leave through: with `PUSHGATEWAY_URL` set it sends a
PUT to `<url>/metrics/job/<name>` carrying the lines, with it unset it writes
`<name>.prom` into `HARNESS_TEXTFILE_DIR` and leaves no temporary file behind.
The network is replaced by a recorder of the request it was handed.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
Pushgateway's documented API (PUT replaces the job's whole group) and the
textfile collector's contract (one `*.prom` file, newline-terminated): the URL,
method and body are written out by hand from the made-up job name and lines.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row sends the
push as a POST, which adds to the group instead of replacing it, so the push
case fails.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import importlib

import pytest

textfile = importlib.import_module("infra.observability.node_textfile.textfile")

LINES = ["# TYPE harness_backup_ok gauge", "harness_backup_ok 1"]
BODY = "# TYPE harness_backup_ok gauge\nharness_backup_ok 1\n"

CASES = [
    pytest.param(
        "http://pushgateway.monitoring:9091/",
        ("PUT", "http://pushgateway.monitoring:9091/metrics/job/backup", BODY, []),
        id="pushed-as-a-group-replacement",
    ),
    pytest.param("", (None, None, BODY, ["backup.prom"]), id="written-as-one-whole-textfile"),
    pytest.param("   ", (None, None, BODY, ["backup.prom"]), id="a-blank-url-is-no-pushgateway"),
]


class _Answer:
    def __enter__(self) -> "_Answer":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.mark.parametrize("pushgateway, expected", CASES)
def test_a_metric_is_pushed_as_one_group_replacement_when_a_pushgateway_is_set_and_written_whole_as_a_textfile_otherwise(
        pushgateway: str, expected: tuple, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """(method, url, body, files left in the directory) is the hand-written one."""
    sent: list = []
    monkeypatch.setattr(textfile.urllib.request, "urlopen", lambda request, timeout: sent.append(request) or _Answer())
    monkeypatch.setenv("PUSHGATEWAY_URL", pushgateway)
    monkeypatch.setenv("HARNESS_TEXTFILE_DIR", str(tmp_path))
    textfile.publish("backup", LINES)
    files = sorted(path.name for path in tmp_path.iterdir())
    if sent:
        request = sent[0]
        seen = (request.get_method(), request.full_url, request.data.decode(), files)
    else:
        seen = (None, None, (tmp_path / "backup.prom").read_text(), files)
    assert seen == expected
