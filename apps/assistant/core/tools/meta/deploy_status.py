"""Read-only `deploy_status` tool: the live deploy picture.

The deploy loop on the server posts GitHub commit statuses for every commit it
handles, under contexts that start with `vm/` (`vm/gate`, `vm/build`,
`vm/boot`, `vm/swap`, `vm/deploy`). This tool reads them back with `gh` and
composes the picture a person asks for: which commit is live, what is waiting
on main, whether the last cycle passed, and which recent commits failed.

It is sight only: this tool never triggers or changes a deploy.

`snapshot()` is the same picture as data, for callers that must not go through
an LLM: it carries `source_ok` so "the deploy state is unreadable" can never be
rendered as "the deploy is fine". `execute()` renders that snapshot; the two
never gather separately.

Tool-module grammar: `NAME`, `DEFINITION`, `execute`. Output bounded by
`text.truncate`.

FAILURE POLICY: never raises. A `gh` miss degrades to the part it could read,
with a note, so a partial view still helps.
"""
from __future__ import annotations

from apps.assistant.shared.project import GITHUB_REPO

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from apps.assistant.core.tools.meta.text import truncate

log = logging.getLogger("openclaw.tools.deploy_status")

NAME = "deploy_status"

_REPO = GITHUB_REPO
_ROWS = 12
_CONTEXT_PREFIX = "vm/"
_DEPLOY_CONTEXT = "vm/deploy"

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "The deploy picture: the live commit, how many commits wait on main, the "
        "last deploy cycle's result, recent deploy failures. Read-only."
    ),
    "input_schema": {"type": "object", "properties": {}},
}


def _recent_rows() -> list[dict] | str:
    """The recent commits on main that carry a `vm/*` status, newest first,
    as rows: action (`deploy_success`, `deploy_failed` or `deploy_pending`),
    sha, the contexts seen, the failed contexts, and the newest status time.
    Returns an error string instead of raising."""
    listing = _gh(["api", f"repos/{_REPO}/commits?sha=main&per_page={_ROWS}", "--jq", ".[].sha"])
    if listing is None:
        return "deploy state unreadable: gh could not list the commits on main"
    rows: list[dict] = []
    for sha in listing.split():
        raw = _gh(["api", f"repos/{_REPO}/commits/{sha}/statuses?per_page=100"])
        if raw is None:
            continue
        try:
            statuses = json.loads(raw) or []
        except json.JSONDecodeError:
            continue
        row = _row_for(sha, statuses)
        if row is not None:
            rows.append(row)
    return rows


def _row_for(sha: str, statuses: list[dict]) -> dict | None:
    """One commit's `vm/*` statuses as a row, or None when it has none. The
    API lists newest first, so the first status per context is its current
    state."""
    latest: dict[str, dict] = {}
    for status in statuses:
        context = str(status.get("context") or "")
        if context.startswith(_CONTEXT_PREFIX) and context not in latest:
            latest[context] = status
    if not latest:
        return None
    failed = sorted(ctx for ctx, st in latest.items() if st.get("state") in ("failure", "error"))
    deployed = latest.get(_DEPLOY_CONTEXT, {}).get("state") == "success"
    action = "deploy_failed" if failed else ("deploy_success" if deployed else "deploy_pending")
    newest = max(str(st.get("updated_at") or st.get("created_at") or "") for st in latest.values())
    return {
        "action": action,
        "sha": sha[:10],
        "services": ",".join(sorted(latest)),
        "failed": ",".join(failed) or None,
        "at": _utc_stamp(_parse_stamp(newest)),
    }


def _parse_stamp(raw: str) -> Any:
    """GitHub's `2026-10-14T18:11:29Z` as an aware datetime, or the raw text."""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw


def _utc_stamp(created_at: Any) -> str:
    """A row's time as ISO UTC ending in Z, the shape every other time source
    The assistant reads uses (`changes._utc_stamp`).

    str() cut to 19 characters would drop the "+00:00", and a reader would
    take the bare clock as local, hours off. A naive
    value is UTC, because the session reads in UTC.
    """
    if not isinstance(created_at, datetime):
        return str(created_at)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh(args: list[str]) -> str | None:
    """Run a `gh` command, return stdout or None on any failure."""
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


@dataclass(frozen=True)
class PendingVsMain:
    """How far behind main the live deploy is: the rendered detail plus the
    commit count (None when gh could not answer)."""

    detail: str
    count: int | None


def _pending_vs_main(deployed_sha: str | None) -> PendingVsMain:
    """How far behind main the live deploy is, best-effort via gh."""
    main_head = _gh(["api", f"repos/{_REPO}/commits/main", "--jq", ".sha"])
    if not main_head:
        return PendingVsMain("main HEAD unavailable (gh)", None)
    main_short = main_head[:12]
    if not deployed_sha:
        return PendingVsMain(
            f"main is at {main_short}; no recorded deployed commit to compare", None
        )
    if main_head.startswith(deployed_sha) or deployed_sha.startswith(main_short):
        return PendingVsMain(f"up to date with main ({main_short})", 0)
    compare = _gh([
        "api", f"repos/{_REPO}/compare/{deployed_sha}...{main_head}",
        "--jq", "{ahead: .ahead_by, msgs: [.commits[].commit.message | split(\"\\n\")[0]]}",
    ])
    if not compare:
        return PendingVsMain(f"behind main ({main_short}); commit list unavailable", None)
    try:
        data = json.loads(compare)
    except json.JSONDecodeError:
        return PendingVsMain(f"behind main ({main_short})", None)
    msgs = "\n".join(f"  - {message}" for message in data.get("msgs", [])[:10])
    ahead = data.get("ahead")
    return PendingVsMain(
        f"{ahead if ahead is not None else '?'} commit(s) behind main "
        f"({main_short}):\n{msgs}",
        ahead if isinstance(ahead, int) else None,
    )


def _empty_snapshot(source_ok: bool, reason: str) -> dict[str, Any]:
    """A snapshot that carries no deploy facts, only why it carries none."""
    return {
        "source_ok": source_ok,
        "reason": reason,
        "live_sha": None,
        "live_sha_at": None,
        "last_cycle_action": None,
        "last_cycle_at": None,
        "last_cycle_sha": None,
        "last_cycle_failed": None,
        "pending_count": None,
        "pending_detail": None,
        "recent_failures": [],
    }


def snapshot() -> dict[str, Any]:
    """The deploy picture as data: what is live, what the last cycle did, how
    much is pending, and whether the sources could be read at all."""
    try:
        rows = _recent_rows()
    except Exception as exc:  # noqa: BLE001, never raises (tool + evidence caller)
        log.warning("deploy_status snapshot failed: %s", exc)
        return _empty_snapshot(False, f"deploy state unreadable: {type(exc).__name__}")
    if isinstance(rows, str):
        return _empty_snapshot(False, rows)
    if not rows:
        return _empty_snapshot(True, "no deploy activity recorded yet")

    last = rows[0]
    successes = [row for row in rows if row["action"] == "deploy_success"]
    live_sha = successes[0]["sha"] if successes else None
    pending = _pending_vs_main(live_sha)
    return {
        "source_ok": True,
        "reason": "",
        "live_sha": live_sha,
        "live_sha_at": successes[0]["at"] if successes else None,
        "last_cycle_action": last["action"],
        "last_cycle_at": last["at"],
        "last_cycle_sha": last["sha"],
        "last_cycle_failed": last["failed"],
        "pending_count": pending.count,
        "pending_detail": pending.detail,
        "recent_failures": [row for row in rows if "fail" in row["action"]][:5],
    }


def _render(snap: dict[str, Any]) -> str:
    """The snapshot as the tool's answer text."""
    if snap["last_cycle_action"] is None:  # unreadable source, or an empty table
        return snap["reason"]

    lines = [
        f"Live deploy: {snap['live_sha'] or 'unknown'}"
        + (f" (last success {snap['live_sha_at']})" if snap["live_sha"] else ""),
        f"Pending: {snap['pending_detail']}",
        f"Last cycle: {snap['last_cycle_action']} at {snap['last_cycle_at']}"
        + (f" sha={snap['last_cycle_sha']}" if snap["last_cycle_sha"] else "")
        + (f" failed={snap['last_cycle_failed']}" if snap["last_cycle_failed"] else ""),
    ]
    if snap["recent_failures"]:
        lines.append("Recent deploy failures:")
        for failure in snap["recent_failures"]:
            detail = failure["failed"] or failure["sha"] or ""
            lines.append(f"  {failure['at']} {failure['action']} {detail}".rstrip())
    else:
        lines.append("No recent deploy failures.")
    return truncate("\n".join(lines))


def execute(tool_input: dict[str, Any]) -> str:
    return _render(snapshot())
