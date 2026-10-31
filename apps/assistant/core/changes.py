"""The change-feed, what actually happened since a point in time.

A grounded report starts here: instead of re-narrating old notes, it asks
"what changed since my last report" and reports THAT. This module answers
it from the real record on GitHub (push is the deploy interface, so commits
on main ARE what deployed): the commits that landed and the issues that
were created or changed since a timestamp.

`digest_since(since_iso)` returns a plain-text block the report + chat loops
paste in; the underlying `commits_since` / `issues_since` are the seams a
test drives. Backed by `gh api` (already in the image, auth via GH_TOKEN),
the same subprocess style as the read-only gh tools.

Every rendered line carries an absolute UTC timestamp, and an empty read is
rendered differently from a failed read. Both are answers to the grounding
contract: "none (or could not read)" would fuse two opposite facts into
one string, and a feed without timestamps lets a report call yesterday
afternoon "overnight".

A list cut at its cap says so, and the header names how wide the window is: a bare "Commits on main (40, ...)" reads
as a complete count, and a wide window clipped to its newest rows reads as the
last day's.

FAILURE POLICY: Tier-2 best-effort, a gh failure yields a short "could not
read X" line, never an exception, so a report degrades to what it could
gather rather than dying.
"""
from __future__ import annotations

from apps.assistant.shared.project import GITHUB_REPO

import json
import subprocess
from dataclasses import dataclass
from typing import Any
from datetime import datetime, timezone

_REPO = GITHUB_REPO
_TIMEOUT_S = 25
_MAX_COMMITS = 40
# The most commits one call can list: GitHub serves at most 100 per page, and
# one row past the cap is asked for so a cut list knows it is cut.
MAX_COMMITS_PER_CALL = 99
_MAX_ISSUES = 40

# Rendered in place of a timestamp we could not parse. Never blank: a missing
# stamp has to be visible, not silently absent.
NO_TIMESTAMP = "time-unreadable"


@dataclass(frozen=True)
class FeedRead:
    """One gh read: the rows it returned AND whether the read itself worked.

    An empty list and a failed call are opposite facts (nothing happened vs we
    do not know what happened). Fusing them lets a report state "quiet night"
    after gh exited non-zero.
    """

    rows: tuple[dict[str, str], ...]
    ok: bool
    returncode: int
    reason: str = ""
    capped: bool = False


def _run_gh(args: list[str]) -> tuple[int, str, str]:
    """One `gh` call; (returncode, stdout, stderr). The single seam a test
    mocks."""
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=_TIMEOUT_S, check=False
    )
    return result.returncode, result.stdout, result.stderr


def _now_iso() -> str:
    """Now, as ISO8601 UTC with seconds precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_stamp(raw: str) -> str:
    """`raw` as ISO8601 UTC with seconds precision and a trailing Z."""
    text = (raw or "").strip()
    if not text:
        return NO_TIMESTAMP
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return NO_TIMESTAMP
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def commits_since(since_iso: str, cap: int = _MAX_COMMITS) -> FeedRead:
    """At most `cap` commits on main since `since_iso` (ISO8601 UTC), newest
    first: {sha, message, at} (first message line only, `at` is the commit
    date). Asks for one row past the cap, so `capped` knows whether more
    exist."""
    returncode, out, _err = _run_gh([
        "api",
        f"repos/{_REPO}/commits?sha=main&since={since_iso}&per_page={cap + 1}",
        "--jq",
        '.[] | {sha: .sha[0:10], message: (.commit.message | split("\\n")[0]), '
        "at: .commit.committer.date}",
    ])
    if returncode != 0:
        return FeedRead(
            rows=(), ok=False, returncode=returncode,
            reason=f"gh exited {returncode}",
        )
    commits: list[dict[str, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if line:
            try:
                commits.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return FeedRead(
        rows=tuple(commits[:cap]), ok=True, returncode=0,
        capped=len(commits) > cap,
    )


def issues_since(since_date: str) -> FeedRead:
    """Issues created or updated since `since_date` (YYYY-MM-DD), with their
    current state, so a report grounds on the REAL state (not a stale note)."""
    returncode, out, _err = _run_gh([
        "issue", "list", "--repo", _REPO, "--state", "all",
        "--search", f"updated:>={since_date}", "--limit", str(_MAX_ISSUES + 1),
        "--json", "number,title,state,updatedAt,assignees",
    ])
    if returncode != 0:
        return FeedRead(
            rows=(), ok=False, returncode=returncode,
            reason=f"gh exited {returncode}",
        )
    text = out.strip()
    if not text:  # the call worked and gh printed nothing: an empty result
        return FeedRead(rows=(), ok=True, returncode=0)
    try:
        rows = json.loads(text) or []
    except json.JSONDecodeError:
        return FeedRead(
            rows=(), ok=False, returncode=returncode,
            reason="gh output was not JSON",
        )
    return FeedRead(
        rows=tuple(rows[:_MAX_ISSUES]), ok=True, returncode=0,
        capped=len(rows) > _MAX_ISSUES,
    )


def _empty_read_line(label: str, read_at: str) -> str:
    """The read worked and the record held nothing."""
    return f"{label}: none. Read succeeded at {read_at}."


def _failed_read_line(label: str, reason: str, read_at: str) -> str:
    """The read did not work, so nothing at all is known about this source."""
    return f"{label}: COULD NOT READ ({reason}) at {read_at}."


def _commit_lines(rows: tuple[dict[str, str], ...]) -> list[str]:
    """One line per commit, absolute UTC stamp first."""
    return [
        f"- {_utc_stamp(row.get('at', ''))} {row['sha']} {row['message']}"
        for row in rows
    ]


def owner_label(assignees: list[dict[str, Any]] | None) -> str:
    """`owner: <logins>`, or `owner: unassigned` written out, never blank: a
    missing owner column was read as "nobody owns this"."""
    logins = [str(person.get("login", "")).strip() for person in assignees or []]
    named = [login for login in logins if login]
    return f"owner: {', '.join(named)}" if named else "owner: unassigned"


def _issue_lines(rows: tuple[dict[str, Any], ...]) -> list[str]:
    """One line per issue, absolute UTC stamp first, owner last."""
    return [
        f"- {_utc_stamp(row.get('updatedAt', ''))} #{row['number']} "
        f"[{row['state']}] {row['title']} | {owner_label(row.get('assignees'))}"
        for row in rows
    ]


def _oldest_stamp(rows: tuple[dict[str, str], ...], stamp_key: str) -> str:
    """The earliest readable UTC stamp among `rows`' `stamp_key` values."""
    stamps = [_utc_stamp(row.get(stamp_key, "")) for row in rows]
    readable = [stamp for stamp in stamps if stamp != NO_TIMESTAMP]
    return min(readable) if readable else NO_TIMESTAMP


def _count_label(label: str, read: FeedRead, stamp_key: str, suffix: str = "") -> str:
    """The heading over a list of rows: the count, or, when the list hit its
    cap, that it is cut and where the shown part stops."""
    if read.capped:
        return (
            f"{label}: {len(read.rows)} shown, MORE EXIST (list capped; the oldest "
            f"shown is {_oldest_stamp(read.rows, stamp_key)}, earlier rows in the "
            f"window are not listed{suffix}):"
        )
    return f"{label} ({len(read.rows)}{suffix}):"


def _window_width(since_iso: str, now: datetime) -> str:
    """How long the window from `since_iso` to `now` is, in hours or days."""
    try:
        start = datetime.fromisoformat(since_iso.strip().replace("Z", "+00:00"))
    except ValueError:
        return "width unreadable"
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    hours = (now - start).total_seconds() / 3600
    if hours < 48:
        return f"{hours:.0f} hours"
    return f"{hours / 24:.1f} days"


def digest_since(since_iso: str, commit_cap: int = _MAX_COMMITS) -> str:
    """A plain-text block: the commits that landed (at most `commit_cap`) and
    the issues that changed since `since_iso`, each stamped, each source
    reporting rows, an empty read or a failed read as three distinct
    outcomes."""
    since_date = since_iso[:10]
    commits = commits_since(since_iso, commit_cap)
    issues = issues_since(since_date)
    read_at = _now_iso()

    width = _window_width(since_iso, datetime.now(timezone.utc))
    lines = [f"WHAT CHANGED SINCE {since_iso} (window {width}; the record, not memory):"]
    if not commits.ok:
        lines.append(_failed_read_line("Commits on main", commits.reason, read_at))
    elif not commits.rows:
        lines.append(_empty_read_line("Commits on main", read_at))
    else:
        lines.append(_count_label("Commits on main", commits, "at", ", push is deploy"))
        lines += _commit_lines(commits.rows)
    if not issues.ok:
        lines.append(
            _failed_read_line("Issues created/changed", issues.reason, read_at)
        )
    elif not issues.rows:
        lines.append(_empty_read_line("Issues created/changed", read_at))
    else:
        lines.append(_count_label("Issues created/changed", issues, "updatedAt"))
        lines += _issue_lines(issues.rows)
    return "\n".join(lines)

