"""The code index answers only through the pinned binary and from a finished index of the commit asked about.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

Its GitHub issues are part of that answer: fetched with `gh`, written into the index as Issue rows with CHILD_OF
edges, put back after a rebuild drops them, and when gh cannot answer the reply says why and names the fix. Those
tests drive `cbm_issues.answer` and the server with a stand-in `gh` on PATH and a scratch index in the tool's own
schema; the issue numbers, titles and states they expect are the stand-in's, never read from the code under test.

A published index is fetched through a stand-in `gh` serving one labelled asset, into a scratch git repository; the
cleanup runs against a scratch cache holding tree indexes, binary versions and leftovers of known ages.

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
- test_an_issue_is_answered_by_number_with_its_parent_even_after_a_rebuild_dropped_the_rows: in
  `cbm_issues.answer`, `everything = _held(database, project) < len(cached["issues"])` made `everything = False`
  (a rebuilt index stays without its Issue rows).
- test_without_a_gh_login_an_issue_question_says_issues_are_not_loaded_and_names_the_fix: in
  `cbm_issues.gh_unready`, `if done.returncode != 0:` made `if done.returncode == 0:`.
- test_only_a_question_that_names_issues_waits_on_github: in `server.answer`, `if cbm_issues.names_issues(tool,
  given) else ""` made `if True else ""` (every question pays for a gh call).
- test_a_published_index_of_an_ancestor_commit_is_installed_as_this_checkouts_own: in
  `cbm_fetch.rename_project`, `if qualified:` made `if False:` (qualified names keep the publisher's prefix).
- test_a_published_index_of_a_commit_this_checkout_lacks_or_already_has_is_not_installed: in
  `cbm_fetch._check_offer`, `if not head or not is_ancestor(shared, commit, head):` made `if not head:`.
- test_cleanup_removes_a_stale_tree_index_an_old_binary_and_leftover_build_files: in `cbm_clean._trees`,
  `if gone or now - _newest(directory, live) > IDLE_DAYS * 86400:` made `if gone:` (an idle tree is kept).
"""
from __future__ import annotations

import inspect


# From the index answers only from the pinned build and a finished index of this commit.

import hashlib


import json


import os


import pathlib


import re


import shutil


import sqlite3


import subprocess


import sys


import time


import pytest


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


import cbm_clean  # noqa: E402


import cbm_fetch  # noqa: E402


import cbm_index  # noqa: E402


import cbm_issues  # noqa: E402


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


def _only_the_pinned_build_is_accepted(tmp_path: pathlib.Path) -> None:
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


def _every_shipped_platform_has_a_complete_pin() -> None:
    """pin.env names an asset and two distinct sha256s for each platform upstream ships."""
    fields = cbm_pin.read()
    for key in _PLATFORMS:
        build = cbm_pin.build_for(fields, key)
        system, cpu = key.split("_")
        assert build.asset.endswith(".tar.gz") and system in build.asset and cpu in build.asset, key
        assert _HEX64.fullmatch(build.tarball_sha256) and _HEX64.fullmatch(build.sha256), key
        assert build.tarball_sha256 != build.sha256, key


def _the_binary_lives_under_the_cache_by_version(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Installed by version under the cache, never in the shared ~/.local/bin."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert cbm_pin.binary_path("v9.9.9") == tmp_path / "harness/cbm/v9.9.9/codebase-memory-mcp"


def _an_unstamped_or_outdated_index_is_built_before_it_is_asked(
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


def _a_build_that_wrote_no_rows_is_never_stamped_or_placed(
        repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An index with no rows for the project raises with the rebuild as its fix, and nothing is placed."""
    monkeypatch.setattr(cbm_index, "ensure_binary", lambda: pathlib.Path("/no/binary"))
    monkeypatch.setattr(cbm_index, "index_into", _stand_in_indexer(rows=0))
    with pytest.raises(cbm_index.BuildError) as refused:
        cbm_index.build(repo, force=True)
    assert refused.value.fix == cbm_index.REBUILD
    assert not (pathlib.Path(os.environ["CBM_CACHE_DIR"]) / f"{cbm_index.project_for(repo)}.db").exists()


def _a_failed_question_answers_its_cause_and_the_fix(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _a_malformed_call_is_answered_and_the_server_keeps_reading(monkeypatch: pytest.MonkeyPatch) -> None:
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


_ISSUE_PAGE = {"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": False}, "nodes": [
    {"number": 10, "url": "https://github.com/o/r/issues/10", "title": "The effort", "state": "OPEN",
     "createdAt": "2026-10-01T00:00:00Z", "updatedAt": "2026-10-02T00:00:00Z", "closedAt": None,
     "body": "- [ ] first open task\n- [x] done task", "labels": {"nodes": [{"name": "PRD"}]},
     "assignees": {"nodes": [{"login": "someone"}]}, "parent": None,
     "comments": {"totalCount": 0, "nodes": []}, "latest": {"nodes": []}},
    {"number": 11, "url": "https://github.com/o/r/issues/11", "title": "A piece of it", "state": "CLOSED",
     "createdAt": "2026-10-01T00:00:00Z", "updatedAt": "2026-10-03T00:00:00Z",
     "closedAt": "2099-01-01T00:00:00Z", "body": "", "labels": {"nodes": []}, "assignees": {"nodes": []},
     "parent": {"number": 10}, "comments": {"totalCount": 0, "nodes": []}, "latest": {"nodes": []}},
]}}}}


@pytest.fixture
def issues_box(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """A checkout naming `o/r`, a stand-in gh logged in or not, and an empty index in the tool's schema."""
    root = tmp_path / "checkout"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude/project.json").write_text(json.dumps({"repo": "o/r"}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    page = tmp_path / "page.json"
    page.write_text(json.dumps(_ISSUE_PAGE))
    gh = bin_dir / "gh"
    gh.write_text(f"""#!{sys.executable}
import sys, os
if sys.argv[1:2] == ["auth"]:
    sys.exit(int(os.environ.get("FAKE_GH_AUTH", "0")))
if any("OPEN, CLOSED" in argument for argument in sys.argv):  # the live sync: nothing changed since
    print('{{"data": {{"repository": {{"issues": {{"pageInfo": {{"hasNextPage": false}}, "nodes": []}}}}}}}}')
else:
    print(open({str(page)!r}).read())
""")
    gh.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    database = tmp_path / "cache" / "p.db"
    database.parent.mkdir()
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE nodes (id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL, label TEXT NOT NULL,
            name TEXT NOT NULL, qualified_name TEXT NOT NULL, file_path TEXT DEFAULT '',
            start_line INTEGER DEFAULT 0, end_line INTEGER DEFAULT 0, properties TEXT DEFAULT '{}',
            UNIQUE(project, qualified_name));
        CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL, source_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL, type TEXT NOT NULL, properties TEXT DEFAULT '{}',
            UNIQUE(source_id, target_id, type));
        CREATE VIRTUAL TABLE nodes_fts USING fts5(name, qualified_name, label, file_path, body, content='');
    """)
    connection.close()
    return root, database


def _issue_rows(database: pathlib.Path) -> dict:
    """Issue number to (title, properties, parent number) as the index holds them."""
    connection = sqlite3.connect(database)
    try:
        rows = {json.loads(props)["number"]: (name, json.loads(props), None) for name, props in connection.execute(
            "SELECT name, properties FROM nodes WHERE label = 'Issue'")}
        for child, parent in connection.execute(
                "SELECT c.qualified_name, p.qualified_name FROM edges e JOIN nodes c ON c.id = e.source_id "
                "JOIN nodes p ON p.id = e.target_id WHERE e.type = 'CHILD_OF'"):
            number = int(child.split(":")[1])
            rows[number] = (*rows[number][:2], int(parent.split(":")[1]))
        return rows
    finally:
        connection.close()


def _an_issue_is_answered_by_number_with_its_parent_even_after_a_rebuild_dropped_the_rows(issues_box) -> None:
    """gh's issues land as Issue rows with their fields and CHILD_OF edge, and come back after a rebuild."""
    root, database = issues_box
    said = cbm_issues.answer(database, "p", root)
    assert "live" in said and "NOT" not in said and "0 changed" in said
    rows = _issue_rows(database)
    assert set(rows) == {10, 11}
    title, props, parent = rows[10]
    assert title == "The effort" and props["state"] == "open" and props["is_prd"] is True
    assert props["open_tasks"] == "- [ ] first open task" and props["done_tasks_count"] == 1
    assert props["assignees"] == ["someone"] and props["url"].endswith("/issues/10")
    assert rows[11][1]["state"] == "closed" and rows[11][2] == 10
    assert cbm_issues.cache_beside(database).exists()

    connection = sqlite3.connect(database)
    connection.execute("DELETE FROM nodes WHERE label = 'Issue'")
    connection.execute("DELETE FROM edges")
    connection.commit()
    connection.close()
    cbm_issues.answer(database, "p", root)
    assert set(_issue_rows(database)) == {10, 11} and _issue_rows(database)[11][2] == 10


def _without_a_gh_login_an_issue_question_says_issues_are_not_loaded_and_names_the_fix(
        issues_box, monkeypatch: pytest.MonkeyPatch) -> None:
    """No login and no cache: "not loaded" and gh auth login. A cache and a failing gh: its age and the fix."""
    root, database = issues_box
    monkeypatch.setenv("FAKE_GH_AUTH", "1")
    said = cbm_issues.answer(database, "p", root)
    assert "not loaded" in said and "not logged in" in said and "gh auth login" in said
    assert _issue_rows(database) == {}

    monkeypatch.setenv("FAKE_GH_AUTH", "0")
    cbm_issues.status_of(cbm_issues.cache_beside(database)).unlink()
    cbm_issues.answer(database, "p", root)
    monkeypatch.setenv("PATH", "/nonexistent")
    stale = cbm_issues.answer(database, "p", root)
    assert "NOT live" in stale and "minutes ago" in stale and "gh auth login" in stale
    assert set(_issue_rows(database)) == {10, 11}


def _only_a_question_that_names_issues_waits_on_github(monkeypatch: pytest.MonkeyPatch) -> None:
    """An Issue query carries the sync's line; a question about code never calls it."""
    calls = []
    monkeypatch.setattr(cbm_index, "ready", lambda here: {"path": "/x/p.db", "project": "p", "head": ""})
    monkeypatch.setattr(cbm_index, "ask", lambda tool, given: {"ok": True, "result": "rows: 1"})
    monkeypatch.setattr(cbm_issues, "answer", lambda database, project, root: calls.append(project) or "rows live")
    asked = server.answer("query_graph", {"query": "MATCH (i:Issue) RETURN i.number"})
    assert asked["issues"] == "rows live" and calls == ["p"]
    assert "[index] rows live" in server._as_text(asked)
    code = server.answer("query_graph", {"query": "MATCH (f:Function) RETURN f.name"})
    assert "issues" not in code and calls == ["p"]


def _published(tmp_path: pathlib.Path, project: str, head: str) -> pathlib.Path:
    """An index in the tool's schema built as `project` for `head`, the file a publisher uploads."""
    database = tmp_path / "published.db"
    database.unlink(missing_ok=True)
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE projects (name TEXT PRIMARY KEY, indexed_at TEXT, root_path TEXT);
        CREATE TABLE nodes (id INTEGER PRIMARY KEY, project TEXT, label TEXT, name TEXT, qualified_name TEXT);
        CREATE INDEX idx_nodes_qn ON nodes(project, qualified_name);
        CREATE TABLE store_meta (k TEXT PRIMARY KEY, v TEXT);
    """)
    connection.execute("INSERT INTO projects VALUES (?, '', '/elsewhere/repo')", (project,))
    connection.execute("INSERT INTO nodes VALUES (1, ?, 'Function', 'f', ?)", (project, f"{project}.a.f"))
    connection.execute("INSERT INTO store_meta VALUES (?, '1')", (f"fp:{project}",))
    connection.commit()
    connection.close()
    cbm_index.write_stamp(database, project, head)
    return database


@pytest.fixture
def release(repo: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """A stand-in gh serving one release asset labelled with a commit; returns a setter for that commit."""
    served = tmp_path / "served"
    served.mkdir()
    label = tmp_path / "label"
    bin_dir = tmp_path / "ghbin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f"""#!{sys.executable}
import json, shutil, sys
arguments = sys.argv[1:]
if arguments[:2] == ["release", "view"]:
    print(json.dumps({{"assets": [{{"name": "i.db.zst", "label": open({str(label)!r}).read()}}]}}))
elif arguments[:2] == ["release", "download"]:
    shutil.copy({str(served / "i.db.zst")!r}, arguments[arguments.index("-D") + 1])
else:
    sys.exit(1)
""")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    # The asset is served uncompressed; what is under test is what is installed, not the codec.
    monkeypatch.setattr(cbm_fetch, "unzstd", lambda source, into: shutil.copy(source, into))

    def publish(head: str) -> None:
        shutil.copy(_published(tmp_path, "elsewhere-repo", head), served / "i.db.zst")
        label.write_text(head)
    return publish


def _a_published_index_of_an_ancestor_commit_is_installed_as_this_checkouts_own(
        repo: pathlib.Path, release) -> None:
    """Published for an ancestor of HEAD: placed under this checkout's project, prefix and root, its commit kept."""
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "b.py").write_text("y = 2\n")
    _git(repo, "add", "b.py")
    _git(repo, "commit", "-q", "-m", "two")
    release(first)
    got = cbm_fetch.fetch(repo, slug="o/r", tag="t", asset="i.db.zst")
    project = cbm_index.project_name(repo)
    assert got["head"] == first and got["behind"] == 1 and got["project"] == project
    database = pathlib.Path(got["path"])
    assert cbm_index.stamp_of(database, project) == first
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT project, qualified_name FROM nodes").fetchall() == [
        (project, f"{project}.a.f")]
    assert connection.execute("SELECT root_path FROM projects").fetchall() == [(str(repo),)]
    assert connection.execute("SELECT k FROM store_meta").fetchall() == [(f"fp:{project}",)]
    connection.close()


def _a_published_index_of_a_commit_this_checkout_lacks_or_already_has_is_not_installed(
        repo: pathlib.Path, release) -> None:
    """A commit not in this history, or one no newer than the index here, places nothing."""
    release("0" * 40)
    with pytest.raises(cbm_fetch.FetchError, match="not HEAD or an ancestor"):
        cbm_fetch.fetch(repo, slug="o/r", tag="t", asset="i.db.zst")
    assert not (cbm_index.cache_dir() / f"{cbm_index.project_name(repo)}.db").exists()

    first = _git(repo, "rev-parse", "HEAD")
    release(first)
    cbm_fetch.fetch(repo, slug="o/r", tag="t", asset="i.db.zst")
    (repo / "b.py").write_text("y = 2\n")
    _git(repo, "add", "b.py")
    _git(repo, "commit", "-q", "-m", "two")
    with pytest.raises(cbm_fetch.FetchError, match="as new as"):
        cbm_fetch.fetch(repo, slug="o/r", tag="t", asset="i.db.zst")


def _cleanup_removes_a_stale_tree_index_an_old_binary_and_leftover_build_files(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gone or idle trees, unpinned versions, dead builds' leftovers and a log's head go; the live and the pinned stay."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("CBM_CACHE_DIR", str(tmp_path / "codebase-memory-mcp"))
    cache, trees = tmp_path / "codebase-memory-mcp", tmp_path / "codebase-memory-mcp-trees"
    cache.mkdir()
    now = 1_800_000_000.0  # a fixed instant: every age below is measured from it, never from the wall clock
    old = now - 4 * 86400
    dead_pid = 2 ** 22 + 7  # above Linux's pid_max default, so never a live process

    def tree(name: str, root: pathlib.Path, when: float) -> pathlib.Path:
        directory = trees / name
        directory.mkdir(parents=True)
        (directory / "meta.json").write_text(json.dumps({"root": str(root)}))
        (cache / f"{name}.db").write_bytes(b"x" * 10)
        for path in (directory / "meta.json", directory, cache / f"{name}.db"):
            os.utime(path, (when, when))
        return directory

    gone = tree("gone-tree", tmp_path / "removed-worktree", now)
    idle = tree("idle-tree", tmp_path, old)
    kept = tree("kept-tree", tmp_path, now)
    pinned = cbm_pin.read()["CBM_VERSION"]
    for version in (pinned, "v0.0.1"):
        (tmp_path / "harness/cbm" / version).mkdir(parents=True)
        (tmp_path / "harness/cbm" / version / "codebase-memory-mcp").write_bytes(b"b" * 100)
    legacy = tmp_path / "legacy/cbm/v0.0.2"
    legacy.mkdir(parents=True)
    leftovers = [tmp_path / f".cbm-build.p.{dead_pid}", kept / f".work.{dead_pid}",
                 cache / ".p.build.lock"]
    leftovers[0].mkdir()
    leftovers[1].mkdir()
    leftovers[2].write_text("")
    young = tmp_path / f".cbm-fetch.p.{dead_pid + 1}"
    young.mkdir()
    os.utime(young, (now - 60, now - 60))
    for path in leftovers:
        os.utime(path, (now - 7200, now - 7200))
    log = cache / "gaps.jsonl"
    log.write_text("".join(f'{{"n": {number}, "padding": "{"x" * 80}"}}\n' for number in range(30)))

    removed = {path for path, _ in cbm_clean.sweep(now, older_roots=(tmp_path / "legacy/cbm",),
                                                   capped=((log, 10),))}
    assert [json.loads(line)["n"] for line in log.read_text().splitlines()] == list(range(20, 30))
    for path in (gone, idle, cache / "gone-tree.db", cache / "idle-tree.db",
                 tmp_path / "harness/cbm/v0.0.1", legacy, *leftovers):
        assert str(path) in removed and not path.exists(), path
    for path in (kept, cache / "kept-tree.db", tmp_path / "harness/cbm" / pinned, young):
        assert path.exists(), path


def _a_checkout_whose_project_json_names_no_repository_uses_its_github_origin(tmp_path: pathlib.Path) -> None:
    """A fresh copy of a template has an empty `repo`; its GitHub origin names the repository instead."""
    import cbm_issues
    root = tmp_path / "copy"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude/project.json").write_text(json.dumps({"repo": ""}))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", "git@github.com:someone/my-company.git"], check=True)
    assert cbm_issues.repository(root) == "someone/my-company"
    (root / ".claude/project.json").write_text(json.dumps({"repo": "o/r"}))
    assert cbm_issues.repository(root) == "o/r"


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
    *_cases(_only_the_pinned_build_is_accepted),
    *_cases(_every_shipped_platform_has_a_complete_pin),
    *_cases(_the_binary_lives_under_the_cache_by_version),
    *_cases(_an_unstamped_or_outdated_index_is_built_before_it_is_asked),
    *_cases(_a_build_that_wrote_no_rows_is_never_stamped_or_placed),
    *_cases(_a_failed_question_answers_its_cause_and_the_fix),
    *_cases(_a_malformed_call_is_answered_and_the_server_keeps_reading),
    *_cases(_an_issue_is_answered_by_number_with_its_parent_even_after_a_rebuild_dropped_the_rows),
    *_cases(_without_a_gh_login_an_issue_question_says_issues_are_not_loaded_and_names_the_fix),
    *_cases(_only_a_question_that_names_issues_waits_on_github),
    *_cases(_a_published_index_of_an_ancestor_commit_is_installed_as_this_checkouts_own),
    *_cases(_a_published_index_of_a_commit_this_checkout_lacks_or_already_has_is_not_installed),
    *_cases(_cleanup_removes_a_stale_tree_index_an_old_binary_and_leftover_build_files),
    *_cases(_a_checkout_whose_project_json_names_no_repository_uses_its_github_origin),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_the_index_answers_only_from_the_pinned_build_and_a_finished_index_of_this_commit(scenario, given, uses, request):
    """The code index answers only through the pinned binary and from a finished index of the commit asked about: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
