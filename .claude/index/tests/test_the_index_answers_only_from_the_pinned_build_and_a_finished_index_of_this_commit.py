"""The code index answers only through the pinned binary and from a finished index of the commit asked about.

Driven as its callers drive it: `cbm_pin.verified` with fake binaries whose sha256 this test computes itself,
`cbm_index.ready` and `cbm_index.build` against a scratch git repository and a scratch cache (`CBM_CACHE_DIR`), with
the tool's indexer replaced by a stand-in that writes a `nodes` table, and the MCP server's `respond` with JSON-RPC
messages. No real binary runs and nothing touches the network, the real cache or the real checkout. Each expected
answer is the rule's (a sha256 is 64 hex characters; upstream v0.12.1 ships four non-Windows tarballs; an index with
no stamp, or stamped for another commit, is not an answer), never read from the code under test.

The break that turns each test red (applied once each, seen red, reverted):

- test_only_the_pinned_build_is_accepted: in `cbm_pin.verified`, `if not is_pinned_build(binary, build)` made
  `if not binary.exists()` (any existing file accepted).
- test_every_shipped_platform_has_a_complete_pin: one `CBM_SHA256_*` line deleted from `pin.env`.
- test_the_binary_lives_under_the_cache_by_version: `install_dir` returns `~/.local/bin`.
- test_an_unstamped_or_outdated_index_is_built_before_it_is_asked: in `cbm_index.ready`, the condition made
  `if not stamp:` (an index of an older commit is answered from).
- test_a_build_that_wrote_no_rows_is_never_stamped_or_placed: the `row_count` refusal in `_assembled` deleted.
- test_a_failed_question_answers_its_cause_and_the_fix: in `server._called`, `"isError": False`.
- test_a_malformed_call_is_answered_and_the_server_keeps_reading: the `isinstance(arguments, dict)` refusal in
  `server.answer` deleted (a string as arguments raised and ended the server).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import cbm_index  # noqa: E402
import cbm_pin  # noqa: E402
import server  # noqa: E402

_PLATFORMS = ("linux_amd64", "linux_arm64", "darwin_amd64", "darwin_arm64")
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _fake_binary(path: pathlib.Path, version: str) -> str:
    """Write an executable that reports `version`; return its sha256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho 'codebase-memory-mcp {version}'\n")
    path.chmod(0o755)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: pathlib.Path, *args: str) -> str:
    """Run git in the scratch repository with a fixed identity."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, env=env,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """A one-commit git repository and a private cache for its index."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "a.py").write_text("x = 1\n")
    _git(root, "add", "a.py")
    _git(root, "commit", "-q", "-m", "one")
    monkeypatch.setenv("CBM_CACHE_DIR", str(tmp_path / "cache"))
    return root.resolve()


def _stand_in_indexer(rows: int):
    """Replaces the tool's indexer: a `nodes` table holding `rows` rows for the project."""
    def index_into(binary, root, project, env, rebuild=cbm_index.REBUILD) -> None:
        connection = sqlite3.connect(pathlib.Path(env["CBM_CACHE_DIR"]) / f"{project}.db")
        connection.execute("CREATE TABLE IF NOT EXISTS nodes (project TEXT, label TEXT, name TEXT)")
        connection.executemany("INSERT INTO nodes VALUES (?, 'File', 'a.py')", [(project,)] * rows)
        connection.commit()
        connection.close()
    return index_into


def test_only_the_pinned_build_is_accepted(tmp_path: pathlib.Path) -> None:
    """The pinned hash and version pass; another hash, a swapped file and no file do not."""
    binary = tmp_path / "codebase-memory-mcp"
    digest = _fake_binary(binary, "0.12.1")
    assert cbm_pin.verified(binary, cbm_pin.Build("v0.12.1", "a.tar.gz", "0" * 64, digest))
    assert not cbm_pin.verified(binary, cbm_pin.Build("v0.12.1", "a.tar.gz", "0" * 64, "f" * 64))
    _fake_binary(binary, "0.11.0")
    stamp = binary.stat()
    os.utime(binary, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
    assert not cbm_pin.verified(binary, cbm_pin.Build("v0.12.1", "a.tar.gz", "0" * 64, digest))
    assert not cbm_pin.verified(tmp_path / "missing", cbm_pin.Build("v0.12.1", "a", "0" * 64, digest))


def test_every_shipped_platform_has_a_complete_pin() -> None:
    """pin.env names an asset and two distinct sha256s for each platform upstream ships."""
    fields = cbm_pin.read()
    for key in _PLATFORMS:
        build = cbm_pin.build_for(fields, key)
        system, cpu = key.split("_")
        assert build.asset.endswith(".tar.gz") and system in build.asset and cpu in build.asset, key
        assert _HEX64.fullmatch(build.tarball_sha256) and _HEX64.fullmatch(build.sha256), key
        assert build.tarball_sha256 != build.sha256, key


def test_the_binary_lives_under_the_cache_by_version(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Installed by version under the cache, never in the shared ~/.local/bin."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert cbm_pin.binary_path("v9.9.9") == tmp_path / "harness/cbm/v9.9.9/codebase-memory-mcp"


def test_an_unstamped_or_outdated_index_is_built_before_it_is_asked(
        repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No index or an older commit's: ready builds first. This commit's: ready builds nothing."""
    monkeypatch.setattr(cbm_index, "ensure_binary", lambda: pathlib.Path("/no/binary"))
    monkeypatch.setattr(cbm_index, "index_into", _stand_in_indexer(rows=1))
    first = cbm_index.ready(repo)
    assert first.get("rebuilt") and "error" not in first
    head = _git(repo, "rev-parse", "HEAD")
    assert cbm_index.stamp_of(pathlib.Path(first["path"]), first["project"]) == head

    assert not cbm_index.ready(repo).get("rebuilt")

    (repo / "a.py").write_text("x = 2\n")
    _git(repo, "commit", "-q", "-am", "two")
    moved = cbm_index.ready(repo)
    assert moved.get("rebuilt")
    assert cbm_index.stamp_of(pathlib.Path(moved["path"]), moved["project"]) == _git(repo, "rev-parse", "HEAD")


def test_a_build_that_wrote_no_rows_is_never_stamped_or_placed(
        repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An index with no rows for the project raises with the rebuild as its fix, and nothing is placed."""
    monkeypatch.setattr(cbm_index, "ensure_binary", lambda: pathlib.Path("/no/binary"))
    monkeypatch.setattr(cbm_index, "index_into", _stand_in_indexer(rows=0))
    with pytest.raises(cbm_index.BuildError) as refused:
        cbm_index.build(repo, force=True)
    assert refused.value.fix == cbm_index.REBUILD
    assert not (pathlib.Path(os.environ["CBM_CACHE_DIR"]) / f"{cbm_index.project_for(repo)}.db").exists()


def test_a_failed_question_answers_its_cause_and_the_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    """A call that cannot be answered is an error naming its cause and fix, never an empty result."""
    monkeypatch.setattr(cbm_index, "ready", lambda here: {
        "error": "the index could not be built: no network", "fix": cbm_pin.INSTALL})
    reply = server.respond({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                            "params": {"name": "query_graph", "arguments": {"query": "MATCH (n) RETURN n"}}})
    assert reply["id"] == 7 and reply["result"]["isError"] is True
    text = reply["result"]["content"][0]["text"]
    assert "no network" in text and f"fix: {cbm_pin.INSTALL}" in text

    listed = server.respond({"jsonrpc": "2.0", "id": 8, "method": "tools/list"})
    assert {tool["name"] for tool in listed["result"]["tools"]} == {"search_graph", "query_graph", "search_code"}
    assert server.respond({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert json.dumps(server.respond({"jsonrpc": "2.0", "id": 9, "method": "nope"})).count("-32601") == 1


def test_a_malformed_call_is_answered_and_the_server_keeps_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    """Arguments, params or a name of the wrong shape get an error reply; none of them ends the server."""
    monkeypatch.setattr(cbm_index, "ready", lambda here: {"path": "", "project": "p", "head": ""})
    monkeypatch.setattr(cbm_index, "ask", lambda tool, given: {"ok": True, "result": "rows: 0"})
    for params in ({"name": "search_graph", "arguments": "oops"}, {"name": "search_graph", "arguments": []},
                   {"name": ["search_graph"], "arguments": {}}):
        reply = server.respond({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": params})
        assert reply["result"]["isError"] is True and "fix: " in reply["result"]["content"][0]["text"]
    refused = server.respond({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": ["x"]})
    assert refused["error"]["code"] == -32602
    lines = ['{"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "query_graph", "arguments": "x"}}',
             "[1, 2]", '{"jsonrpc": "2.0", "id": 6, "method": "ping"}']
    done = subprocess.run([sys.executable, str(pathlib.Path(server.__file__))], input="\n".join(lines) + "\n",
                          capture_output=True, text=True, timeout=30, check=False)
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [reply.get("id") for reply in replies] == [5, None, 6] and done.returncode == 0
