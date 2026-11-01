"""The repository's GitHub issues in the code index: fetched with gh, kept beside it, synced before a read.

WHAT. The issues of the repository ``.claude/project.json`` names (its ``repo``
key) are fetched with ``gh`` when gh is installed and logged in: the open ones
and those closed in the last ``CLOSED_WITHIN_DAYS`` days, each with its body,
labels, assignees, parent and newest comment. They are kept in a cache file
beside the index (``<project>.issues.json`` next to ``<project>.db``) and
written into the index as ``Issue`` rows and ``CHILD_OF`` edges, so one Cypher
query answers where an effort stands::

    MATCH (i:Issue) WHERE i.number = 12 RETURN i.number, i.name, i.state

An Issue row is named by the title, keyed ``issue:<number>``, and carries
``number``, ``url``, ``state``, ``labels``, ``assignees``, ``updated``,
``closed``, ``is_prd``, ``open_tasks`` (the body's unticked ``- [ ]`` lines),
``open_tasks_count``, ``done_tasks_count``, ``last_comment`` and ``docstring``
(the body and the kept comments). A repository with its own index passes adds
fields of its own through ``extra``.

LIVE. A question that names issues (``names_issues``) first runs ``answer``:
one gh GraphQL call for the issues changed since the last sync, capped at
``SYNC_TIMEOUT`` seconds, merged into the cache and written into the index row
by row. The first question on a box, with no cache yet, fetches the whole list
instead. Once an hour a full fetch runs in the background, which is what drops
a deleted or transferred issue that a since-filter cannot see. When gh, the
login or the network is missing, the answer is the cache with a line saying how
old it is, or a plain "issues not loaded" line naming the fix.

WHY THE INDEX REBUILD DOES NOT LOSE THEM. A rebuild renames a fresh file over
the index, without these rows. ``answer`` counts the Issue rows before a read
and writes every cached issue back when the index holds fewer than the cache.

Standard library only: this runs on a box with ``python3`` and ``gh``.

Command line::

    python3 .claude/index/cbm_issues.py refresh [ROOT]   # fetch every issue now

FAILURE POLICY: reports, never raises. Every gh call has a timeout; a failed
fetch is written beside the cache as its cause and fix and the old cache stays;
a cache is written to a temp file and renamed into place, because a
half-written cache is worse than a stale one.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import sqlite3
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

#: The command that fetches every issue by hand, named in every fix it is.
REFRESH = "python3 .claude/index/cbm_issues.py refresh"
#: How old the full fetch may grow before a question starts one in the background.
REFRESH_EVERY = 3600
#: Seconds a box with no cache waits before trying the first full fetch again,
#: so a failing network costs one question a minute and not every question.
_RETRY_AFTER = 60
#: Closed issues older than this are not fetched: open work and its recent past
#: is what a session asks about, and every closed issue ever is most of the cost.
CLOSED_WITHIN_DAYS = 90
#: Seconds one gh call of a full fetch may take.
GH_TIMEOUT = 60
#: Seconds the live sync before an issue answer may take, all pages together.
#: One page measured 0.7 s on 2026-11-01; past this the cache answers.
SYNC_TIMEOUT = 3.0
#: How far each sync reaches back past the last one, so an issue GitHub stamped
#: a moment before the clock read is not missed. Merging one twice is harmless.
SYNC_OVERLAP = 120
#: Bytes one property may hold and still come back whole: the pinned
#: codebase-memory-mcp cuts every returned value at 511 bytes of its
#: JSON-escaped form, so a longer one would arrive cut mid-word with no mark.
PROPERTY_BYTES = 500
#: The index label and the edge type, shared with every repository's queries.
LABEL = "Issue"
PARENT_EDGE = "CHILD_OF"
#: The tools whose answers can hold issue rows. ``search_code`` reads files.
ISSUE_TOOLS = ("query_graph", "search_graph")

# A markdown checklist line, ticked or not, at any indent.
_TASK = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(.*\S)\s*$")

_ISSUES_QUERY = """
query($owner: String!, $name: String!, $cursor: String, $since: DateTime) {
  repository(owner: $owner, name: $name) {
    issues(first: 50, after: $cursor, states: [STATES], filterBy: {since: $since},
           orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number url title state createdAt updatedAt closedAt body
        labels(first: 30) { nodes { name } }
        assignees(first: 10) { nodes { login } }
        parent { number }
        comments(first: 60) {
          totalCount
          nodes { author { login } createdAt body }
        }
        latest: comments(last: 1) { nodes { author { login } createdAt body } }
      }
    }
  }
}
"""
#: The full fetch's query, asked for both states at once, for the live sync.
_CHANGED_QUERY = _ISSUES_QUERY.replace("STATES", "OPEN, CLOSED")


# ── where ──────────────────────────────────────────────────────────────────


def repository(root: pathlib.Path) -> str:
    """``owner/name``: the ``repo`` key of ``.claude/project.json``, else the GitHub ``origin`` remote, or empty."""
    try:
        named = json.loads((pathlib.Path(root) / ".claude/project.json")
                           .read_text(encoding="utf-8")).get("repo")
    except (OSError, ValueError, AttributeError):
        named = None
    if isinstance(named, str) and "/" in named:
        return named.strip()
    return _origin_repository(root)


#: ``owner/name`` out of an https or ssh GitHub remote URL.
_GITHUB_REMOTE = re.compile(r"github\.com[:/]+([^/\s]+/[^/\s]+?)(?:\.git)?/?$")


def _origin_repository(root: pathlib.Path) -> str:
    """``owner/name`` of the checkout's ``origin`` remote when it is on GitHub, or empty."""
    try:
        url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    found = _GITHUB_REMOTE.search(url)
    return found.group(1) if found else ""


def cache_beside(database: pathlib.Path) -> pathlib.Path:
    """The cache file beside an index: ``<project>.issues.json`` next to ``<project>.db``."""
    return pathlib.Path(database).with_suffix(".issues.json")


def status_of(cache: pathlib.Path) -> pathlib.Path:
    """The file beside the cache that says why the last fetch did not happen."""
    return cache.with_suffix(".status")


# ── the cache ──────────────────────────────────────────────────────────────


def load(cache: pathlib.Path | None) -> dict | None:
    """The cached issues, or ``None`` when missing, unreadable or malformed."""
    if cache is None or not cache.exists():
        return None
    try:
        loaded = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(loaded, dict) or not isinstance(loaded.get("issues"), list):
        return None
    loaded.setdefault("fetched_at", int(cache.stat().st_mtime))
    return loaded


def not_loaded(cache: pathlib.Path | None, refresh: str = REFRESH) -> dict | None:
    """Why there are no issues, with the fix, or ``None`` when a cache exists."""
    if cache is not None and cache.exists():
        return None
    if cache is None:
        return {"cause": "git did not name a directory for the issue cache",
                "fix": f"run {refresh} from inside a checkout"}
    try:
        noted = json.loads(status_of(cache).read_text(encoding="utf-8"))
        if isinstance(noted, dict) and noted.get("cause"):
            return {"cause": str(noted["cause"]), "fix": str(noted.get("fix") or refresh)}
    except (OSError, ValueError):
        pass
    return {"cause": "no issue fetch has run on this machine yet",
            "fix": f"gh auth login, then {refresh}"}


def _write(cache: pathlib.Path, payload: dict) -> None:
    """Write the cache to a temp file and rename it into place."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    writing = cache.with_name(cache.name + ".writing")
    writing.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    os.replace(writing, cache)


def _note(cache: pathlib.Path, cause: str, fix: str) -> None:
    """Write why the fetch did not happen beside the cache, for the answers to quote."""
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        status_of(cache).write_text(
            json.dumps({"cause": cause, "fix": fix, "at": int(time.time())}) + "\n",
            encoding="utf-8")
    except OSError:
        pass  # the cause is also the return value; losing the note loses no data


def seconds_since_attempt(cache: pathlib.Path) -> float:
    """Seconds since the cache was written or a fetch last failed, whichever is newer."""
    stamps = [one.stat().st_mtime for one in (cache, status_of(cache)) if one.exists()]
    return time.time() - max(stamps) if stamps else float("inf")


# ── gh ─────────────────────────────────────────────────────────────────────


def _gh_environment() -> dict[str, str]:
    """The environment gh runs in, with the user-local bin it is often installed in."""
    environment = dict(os.environ)
    local_bin = pathlib.Path.home() / ".local" / "bin"
    environment["PATH"] = f"{local_bin}{os.pathsep}{environment.get('PATH', '')}"
    return environment


def gh_unready(refresh: str = REFRESH) -> tuple[str, str] | None:
    """Why gh cannot fetch, with the fix, or ``None`` when it is logged in."""
    gh = shutil.which("gh", path=_gh_environment()["PATH"])
    if gh is None:
        return ("gh is not installed on this machine, so no GitHub issues are loaded",
                f"install gh (https://cli.github.com), gh auth login, then {refresh}")
    try:
        done = subprocess.run([gh, "auth", "status", "--hostname", "github.com"],
                              capture_output=True, timeout=GH_TIMEOUT,
                              env=_gh_environment(), check=False)
    except (OSError, subprocess.SubprocessError) as failed:
        return (f"gh auth status did not answer ({failed}), so no GitHub issues are loaded",
                refresh)
    if done.returncode != 0:
        return ("gh is not logged in on this machine, so no GitHub issues are loaded",
                f"gh auth login, then {refresh}")
    return None


def _graphql(query: str, repo: str, cursor: str | None, since: str | None,
             timeout: float = GH_TIMEOUT) -> dict:
    """One gh GraphQL call, with the cursor and the since left out when unset."""
    owner, _, name = repo.partition("/")
    command = ["gh", "api", "graphql", "-f", f"query={query}",
               "-F", f"owner={owner}", "-F", f"name={name}"]
    if cursor:
        command += ["-F", f"cursor={cursor}"]
    if since:
        command += ["-f", f"since={since}"]
    answered = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=True, timeout=timeout, env=_gh_environment())
    return json.loads(answered.stdout)


def _pages(query: str, repo: str, since: str | None, deadline: float | None) -> list[dict]:
    """Every issue the query answers, page by page, as cache records."""
    fetched: list[dict] = []
    cursor: str | None = None
    for _page in range(200):
        timeout = GH_TIMEOUT
        if deadline is not None:
            timeout = deadline - time.time()
            if timeout <= 0:
                raise subprocess.TimeoutExpired("gh api graphql", SYNC_TIMEOUT)
        answered = _graphql(query, repo, cursor, since, timeout=timeout)
        block = ((answered.get("data") or {}).get("repository") or {}).get("issues")
        if not isinstance(block, dict):
            raise RuntimeError(f"gh answered with no issues block: {str(answered)[:300]}")
        fetched.extend(_cache_record(node) for node in block.get("nodes") or [])
        page = block.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return fetched
        cursor = page.get("endCursor")
    raise RuntimeError("the issue list did not end after 200 pages; stopping")


def fetch_all(repo: str) -> list[dict]:
    """The open issues, then those closed in the last ``CLOSED_WITHIN_DAYS`` days.

    GitHub has no closed-since filter, so the closed half asks for issues
    updated since the cut-off, which every recently closed one is, and keeps
    those whose ``closedAt`` is inside the window.
    """
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                           time.gmtime(time.time() - CLOSED_WITHIN_DAYS * 86400))
    fetched = _pages(_ISSUES_QUERY.replace("STATES", "OPEN"), repo, None, None)
    fetched.extend(issue for issue in
                   _pages(_ISSUES_QUERY.replace("STATES", "CLOSED"), repo, cutoff, None)
                   if str(issue.get("closedAt") or "") >= cutoff)
    return fetched


def _cache_record(node: dict) -> dict:
    """One GitHub issue, flattened to the fields the rows are built from."""
    parent = node.get("parent") or {}
    labels = (node.get("labels") or {}).get("nodes") or []
    assignees = (node.get("assignees") or {}).get("nodes") or []
    comments = (node.get("comments") or {}).get("nodes") or []
    latest = ((node.get("latest") or {}).get("nodes") or [None])[-1]
    return {
        "number": node["number"],
        "url": node.get("url") or "",
        "title": node.get("title") or "",
        "state": (node.get("state") or "").lower(),
        "labels": [label["name"] for label in labels],
        "assignees": [person["login"] for person in assignees],
        "createdAt": node.get("createdAt"),
        "updatedAt": node.get("updatedAt"),
        "closedAt": node.get("closedAt"),
        "parent": parent.get("number"),
        "body": node.get("body") or "",
        "comments": [_comment_record(comment) for comment in comments],
        "comment_count": (node.get("comments") or {}).get("totalCount") or 0,
        "last_comment": _comment_record(latest),
    }


def _comment_record(comment: dict | None) -> dict | None:
    """One GitHub comment as the cache keeps it, or ``None`` for none."""
    if not comment:
        return None
    return {"author": ((comment.get("author") or {}).get("login") or ""),
            "at": comment.get("createdAt"), "body": comment.get("body") or ""}


# ── fetching and syncing ───────────────────────────────────────────────────


def refresh(cache: pathlib.Path, repo: str, *, refresh_command: str = REFRESH,
            max_age: float | None = None) -> tuple[bool, str]:
    """Fetch every open and recently closed issue and write the cache.

    Args:
        cache: the cache file to write.
        repo: ``owner/name``.
        refresh_command: the command a failure names as its fix.
        max_age: skip when the cache, or the last failed attempt, is younger
            than this many seconds. ``None`` always fetches.

    Returns:
        Whether a fetch landed, and one line saying what happened. Never raises.
    """
    if not repo:
        cause = "no GitHub repository is named in .claude/project.json or found as the origin remote, so no GitHub issues are loaded"
        _note(cache, cause, 'set "repo": "<owner>/<name>" in .claude/project.json')
        return False, cause
    if max_age is not None and seconds_since_attempt(cache) < max_age:
        return False, f"the issue cache at {cache} was tried under {max_age:.0f} s ago"
    unready = gh_unready(refresh_command)
    if unready:
        _note(cache, *unready)
        return False, unready[0]
    # Stamped when the fetch starts: the live sync asks for everything changed
    # since this, and an issue edited during a long fetch may be in neither half.
    started = int(time.time())
    try:
        issues = fetch_all(repo)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, RuntimeError) as failed:
        cause = f"gh is logged in but fetching the issues failed: {failed}"
        _note(cache, cause, refresh_command)
        return False, cause
    _write(cache, {"repository": repo, "fetched_at": started,
                   "closed_within_days": CLOSED_WITHIN_DAYS, "issues": issues})
    status_of(cache).unlink(missing_ok=True)
    return True, f"{len(issues)} issues cached at {cache}"


def sync(cache: pathlib.Path | None, repo: str, *, timeout: float = SYNC_TIMEOUT,
         refresh_command: str = REFRESH) -> dict:
    """Fetch the issues GitHub changed since the last sync and merge them into the cache.

    Returns:
        ``synced`` (whether GitHub answered), ``fetched`` (the changed issues
        as cache records) and ``say``, one plain line for the answer: live, or
        how old the cache is, why, and the fix. Never raises, and never writes
        the cache when nothing changed.
    """
    cached = load(cache)
    if cached is None:
        why = not_loaded(cache, refresh_command) or {}
        return {"synced": False, "fetched": [],
                "say": (f"Issues are not loaded: {why.get('cause') or 'no issue cache'}. "
                        f"Fix: {why.get('fix') or refresh_command}")}
    last = float(cached.get("synced_at") or cached.get("fetched_at") or 0)
    started = time.time()
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last - SYNC_OVERLAP))
    if not repo:
        return {"synced": False, "fetched": [], "say": _stale_line(
            last, "no GitHub repository is named in .claude/project.json or found as the origin remote",
            'set "repo": "<owner>/<name>" in .claude/project.json, then ask again')}
    try:
        if shutil.which("gh", path=_gh_environment()["PATH"]) is None:
            raise RuntimeError("gh is not installed on this machine")
        fetched = _pages(_CHANGED_QUERY, repo, since, started + timeout)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, RuntimeError) as failed:
        return {"synced": False, "fetched": [], "say": _stale_line(last, _sync_cause(failed))}
    merged = _merged(cached["issues"], fetched)
    if merged is not None:
        _write(cache, {**cached, "issues": merged, "synced_at": int(started)})
    return {"synced": True, "fetched": fetched,
            "say": (f"issue rows are live: synced with GitHub just now, "
                    f"{len(fetched)} changed since {since}")}


def _merged(held: list[dict], fetched: list[dict]) -> list[dict] | None:
    """The cached issues with the fetched ones in place, or ``None`` when none differ."""
    by_number = {entry.get("number"): entry for entry in held}
    differs = [entry for entry in fetched if by_number.get(entry["number"]) != entry]
    if not differs:
        return None
    for entry in differs:
        by_number[entry["number"]] = entry
    return list(by_number.values())


def _sync_cause(failed: Exception) -> str:
    """Why the live sync did not happen, in one line."""
    if isinstance(failed, subprocess.TimeoutExpired):
        return f"GitHub did not answer within {SYNC_TIMEOUT:.0f} s"
    if isinstance(failed, subprocess.CalledProcessError):
        said = (failed.stderr or "").strip().splitlines()
        return f"gh failed: {said[-1] if said else f'exit {failed.returncode}'}"
    return str(failed)


def _stale_line(last: float, cause: str,
                fix: str = "gh auth login (or check the network), then ask again") -> str:
    """How old the cached issue rows are, why they were not synced, and the fix."""
    minutes = max(0.0, time.time() - last) / 60.0
    age = f"{minutes:.0f} minutes" if minutes < 120 else f"{minutes / 60:.1f} hours"
    return (f"issue rows are NOT live: {cause}, so they are GitHub as of {age} ago "
            f"and may miss what changed since. Fix: {fix}")


# ── rows ───────────────────────────────────────────────────────────────────


def properties(entry: dict, repo: str) -> dict:
    """One cached issue's row properties, everything but its text."""
    labels = [str(name) for name in entry.get("labels") or []]
    open_tasks, done = _tasks(entry.get("body") or "")
    return {
        "number": int(entry["number"]),
        "url": entry.get("url") or f"https://github.com/{repo}/issues/{entry['number']}",
        "state": str(entry.get("state") or "").lower(),
        "labels": labels,
        "assignees": [str(login) for login in entry.get("assignees") or []],
        "updated": entry.get("updatedAt"),
        "closed": entry.get("closedAt"),
        "is_prd": "PRD" in labels,
        "open_tasks": _task_list(open_tasks),
        "open_tasks_count": len(open_tasks),
        "done_tasks_count": done,
        "last_comment": _last_comment(entry),
    }


def _tasks(body: str) -> tuple[list[str], int]:
    """The body's unticked checklist lines, as written, and how many are ticked."""
    unticked: list[str] = []
    ticked = 0
    for line in body.splitlines():
        match = _TASK.match(line)
        if match is None:
            continue
        if match.group(1) == " ":
            unticked.append(f"- [ ] {match.group(2)}")
        else:
            ticked += 1
    return unticked, ticked


def _task_list(unticked: list[str]) -> str:
    """The unticked lines, each shortened evenly, as many as fit one property.

    Every line gets the same share of ``PROPERTY_BYTES`` so the third task is
    not lost to a long first one; lines that still do not fit are counted in a
    closing ``+N more`` line, and the full text stays on GitHub.
    """
    if not unticked:
        return ""
    share = max(80, PROPERTY_BYTES // len(unticked) - 4)
    shortened = [fitted(line, share) for line in unticked]
    for kept in range(len(shortened), 0, -1):
        rest = len(shortened) - kept
        text = "\n".join(shortened[:kept] + ([f"+{rest} more"] if rest else []))
        if _escaped_bytes(text) <= PROPERTY_BYTES:
            return text
    return f"{len(shortened)} open tasks"


def fitted(text: str, limit: int) -> str:
    """``text`` cut to at most ``limit`` escaped bytes, marked with ``...`` when cut."""
    if _escaped_bytes(text) <= limit:
        return text
    while text and _escaped_bytes(text + "...") > limit:
        text = text[:-1]
    return text.rstrip() + "..."


def _escaped_bytes(text: str) -> int:
    """Bytes ``text`` takes as an ASCII-escaped JSON string body, the form the cap counts."""
    return len(json.dumps(text)) - 2


def _last_comment(entry: dict) -> str:
    """The newest comment as ``<date> <author>: <its start>``, or empty when none.

    The cache's own ``last_comment`` is GitHub's newest; a cache written before
    it existed falls back to the last kept comment, but only when every comment
    was kept, since otherwise that one is not the newest.
    """
    newest = entry.get("last_comment")
    kept = entry.get("comments") or []
    if not newest and kept and (entry.get("comment_count") or 0) <= len(kept):
        newest = kept[-1]
    if not newest:
        return ""
    said = " ".join((newest.get("body") or "").split())
    who = f"{(newest.get('at') or '')[:10]} {newest.get('author') or 'somebody'}: "
    return fitted(who + said, PROPERTY_BYTES)


def issue_text(entry: dict) -> str:
    """One issue as a single readable document: its body, then its comments with author and date."""
    parts = []
    body = (entry.get("body") or "").strip()
    if body:
        parts.append(body)
    for comment in entry.get("comments") or []:
        said = (comment.get("body") or "").strip()
        if not said:
            continue
        who = comment.get("author") or "somebody"
        when = (comment.get("at") or "")[:10]
        parts.append(f"--- comment by {who} {when} ---\n{said}")
    held = entry.get("comment_count") or 0
    kept = len(entry.get("comments") or [])
    if held > kept:
        parts.append(f"--- {held - kept} further comments are not in this index ---")
    return "\n\n".join(parts)


def land(database: pathlib.Path, project: str, entries: list[dict], repo: str, *,
         source: str = "issues", extra=None) -> int:
    """Write these issues into the index as Issue rows and their CHILD_OF edges.

    Args:
        database: the index file.
        project: the project its rows are scoped by.
        entries: cache records.
        repo: ``owner/name``, for an issue whose url the cache lacks.
        source: the proof written on each parent edge.
        extra: optional ``extra(entry) -> dict`` of a repository's own fields.

    Returns:
        How many rows were written. A row keeps its id when it is already
        there, so every edge pointing at it stays placed; a parent the index
        does not hold is skipped, and the old parent edges of these rows go
        first, so a parent removed on GitHub is removed here too.
    """
    connection = sqlite3.connect(database, timeout=5)
    try:
        searchable = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'nodes_fts'").fetchone() is not None
        written: dict[str, int] = {}
        for entry in entries:
            carried = {**properties(entry, repo), **(extra(entry) if extra else {})}
            text = issue_text(entry)
            if text:
                carried["docstring"] = text
            qualified = f"issue:{entry['number']}"
            written[qualified] = _upsert_row(
                connection, project, str(entry.get("title") or ""), qualified,
                json.dumps(carried, default=str), searchable)
        if written:
            marks = ",".join("?" * len(written))
            connection.execute(
                f"DELETE FROM edges WHERE project = ? AND source_id IN ({marks}) "
                "AND type = ?", (project, *written.values(), PARENT_EDGE))
        for entry in entries:
            parent = entry.get("parent")
            if not isinstance(parent, int):
                continue
            target = connection.execute(
                "SELECT id FROM nodes WHERE project = ? AND qualified_name = ?",
                (project, f"issue:{parent}")).fetchone()
            if target is None:
                continue
            connection.execute(
                "INSERT OR IGNORE INTO edges (project, source_id, target_id, type, "
                "properties) VALUES (?,?,?,?,?)",
                (project, written[f"issue:{entry['number']}"], target[0], PARENT_EDGE,
                 json.dumps({"source": source})))
        connection.commit()
        return len(written)
    finally:
        connection.close()


def _upsert_row(connection: sqlite3.Connection, project: str, name: str,
                qualified: str, carried: str, searchable: bool) -> int:
    """One Issue row in place, by its qualified name, and its search entry; its id."""
    held = connection.execute(
        "SELECT id, name, qualified_name, label, file_path FROM nodes "
        "WHERE project = ? AND qualified_name = ?", (project, qualified)).fetchone()
    if held is None:
        row_id = connection.execute(
            "INSERT INTO nodes (project, label, name, qualified_name, file_path, "
            "start_line, end_line, properties) VALUES (?,?,?,?,?,?,?,?)",
            (project, LABEL, name, qualified, "", 0, 0, carried)).lastrowid
    else:
        row_id = held[0]
        if searchable:
            # Contentless FTS5: an old entry is removed by handing back its values.
            connection.execute(
                "INSERT INTO nodes_fts (nodes_fts, rowid, name, qualified_name, "
                "label, file_path) VALUES ('delete', ?, ?, ?, ?, ?)", held)
        connection.execute(
            "UPDATE nodes SET label = ?, name = ?, file_path = '', start_line = 0, "
            "end_line = 0, properties = ? WHERE id = ?", (LABEL, name, carried, row_id))
    if searchable:
        connection.execute(
            "INSERT INTO nodes_fts (rowid, name, qualified_name, label, file_path) "
            "VALUES (?,?,?,?,?)", (row_id, name, qualified, LABEL, ""))
    return row_id


def _held(database: pathlib.Path, project: str) -> int:
    """How many Issue rows the index holds for this project."""
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        return connection.execute(
            "SELECT count(*) FROM nodes WHERE project = ? AND label = ?",
            (project, LABEL)).fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        connection.close()


# ── the answer ─────────────────────────────────────────────────────────────


def names_issues(tool: str, arguments: dict) -> bool:
    """Whether a question can read issue rows: a graph tool whose arguments name issues."""
    return tool in ISSUE_TOOLS and "issue" in repr(arguments).lower()


def answer(database: pathlib.Path, project: str, root: pathlib.Path) -> str:
    """Bring the index's issue rows up to GitHub before a read; the line the answer carries.

    Args:
        database: the index file, ready for this question.
        project: the project its rows are scoped by.
        root: the checkout whose ``.claude/project.json`` names the repository.

    The first question on a box fetches the whole list; every later one syncs
    what changed, and starts the hourly full fetch in the background when it
    is due. Never raises.
    """
    repo = repository(root)
    cache = cache_beside(database)
    held = load(cache)
    if held is None:
        refresh(cache, repo, max_age=_RETRY_AFTER)
    elif time.time() - float(held.get("fetched_at") or 0) >= REFRESH_EVERY:
        _in_background(cache, root)
    synced = sync(cache, repo)
    cached = load(cache)
    if cached is None:
        return synced["say"]
    try:
        everything = _held(database, project) < len(cached["issues"])
        land(database, project, cached["issues"] if everything else synced["fetched"],
             repo, source=cache.name)
    except (sqlite3.Error, OSError, KeyError, ValueError) as failed:
        return (f"issue rows are NOT live: the index could not be written ({failed!r}). "
                "Fix: ask again; a read during a rebuild can fail")
    return synced["say"]


def _in_background(cache: pathlib.Path, root: pathlib.Path) -> None:
    """Start a full fetch detached, at most once an hour, so a question never waits on one."""
    started = cache.with_suffix(".started")
    try:
        if time.time() - started.stat().st_mtime < REFRESH_EVERY:
            return
    except OSError:
        pass  # never started on this box
    try:
        started.touch()
        subprocess.Popen([sys.executable, str(HERE / "cbm_issues.py"), "refresh", str(root)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass  # the live sync still answered; the next question tries again


def main(argv: list[str]) -> int:
    """``refresh [ROOT]``: fetch every issue now and write them into the index."""
    if not argv or argv[0] != "refresh":
        print("usage: cbm_issues.py refresh [ROOT]", file=sys.stderr)
        return 2
    import cbm_index  # the sibling module; imported here so a library caller never needs it
    root = cbm_index.shared_checkout(pathlib.Path(argv[1]) if len(argv) > 1 else cbm_index.REPO)
    project = cbm_index.project_name(root)
    database = cbm_index.cache_dir() / f"{project}.db"
    fetched, said = refresh(cache_beside(database), repository(root))
    print(said)
    if not fetched:
        return 1
    if database.exists():
        cached = load(cache_beside(database)) or {}
        print(f"{land(database, project, cached.get('issues') or [], repository(root), source=cache_beside(database).name)} issue rows written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
