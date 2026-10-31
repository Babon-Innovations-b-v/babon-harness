"""The weekly compact, fold a week of raw memory into one durable
summary.

`compact_week() -> str | None` takes everything since the previous
compact (all senders' chat turns, incl. the outbound pages `core.outbound`
recorded, plus the journal notes, plus the commits and issue changes GitHub
holds for the window) and runs ONE no-tools LLM call that
writes the week's summary: what happened, what was decided, what is still
open, per-person facts worth keeping. The summary lands in the
`weekly_compacts` table and from then on rides into every loop's prompt
via `core.journal.render()`, this is how openclaw still knows in August
what happened in June after the raw windows rolled off.

The `harness-assistant-weekly-compact` VM timer POSTs `/webhook/compact` weekly.
Windows chain: each run starts where the last compact ended
(`state.latest_week_end`), so a missed week is folded into the next run
and a double-fired timer finds a near-empty window and skips.

Single public callable: `compact_week()`.

FAILURE POLICY: Tier-2 best-effort, an empty window, a tripped budget or
an Anthropic fault skips this week's compact (log + return None; the raw
rows stay in SQLite, so the NEXT run summarises them, nothing is lost,
only deferred). The compact write itself is Tier-1 and propagates.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apps.assistant.core import brain as _brain
from apps.assistant.core import changes as _changes
from apps.assistant.core import principles
from apps.assistant.core import state
from apps.assistant.shared import budget

log = logging.getLogger("openclaw.compact")

# A double-fired timer finds a window shorter than this and skips.
_MIN_WINDOW_HOURS = 24
# Newest-first char cap on the raw dump fed to the LLM (well under the
# model context; a normal week is far smaller).
_MAX_DUMP_CHARS = 60_000

_TASK = """Below is your raw memory of the past week: every Signal exchange
(what people asked, what you answered, what you paged them about) and your
journal notes. Compress it into ONE summary you will rely on for months.

Keep, in plain compact prose:
- what happened (incidents with cause and resolution, deploys that mattered,
  findings and their outcomes)
- what was decided or taught
- open threads that still need following up
- per-person facts worth keeping (who asked for what, vacations, preferences)

Drop routine chatter, greetings and anything that resolved without meaning.

Three rules, because a summary is read for months as fact:
- Keep a note's hedge ("likely", "probably", "guess") and never add "fine" or
  "artifact" that the source did not prove.
- Copy times and figures exactly as the source gives them. A "last succeeded"
  time is not when something started failing.
- Say something has no resolution only after checking the WHAT CHANGED block
  at the end; if a commit or issue there addresses it, name it. When that
  block says MORE EXIST or COULD NOT READ, write "not checked", never "no
  resolution".

Write it as your own memory ("I paged the owner about X, cause was Y, fixed by Z").
Plain text, no markdown, at most ~1500 characters. Output ONLY the summary."""


def _render_dump(start_iso: str, end_iso: str) -> str:
    """The week's raw rows as one text dump, oldest-first, trimmed
    oldest-first when it exceeds the char cap (the newest rows carry the
    most still-open context)."""
    lines: list[str] = []
    for note in state.notes_between(start_iso, end_iso):
        who = f" (about {note['person']})" if note["person"] else ""
        lines.append(f"[{note['added_at'][:16]}Z journal{who}] {note['text']}")
    for turn in state.turns_between(start_iso, end_iso):
        lines.append(
            f"[{turn['created_at'][:16]}Z {turn['sender']} {turn['role']}] "
            f"{turn['text']}"
        )
    lines.sort()  # ISO timestamps prefix-sort chronologically
    dump = "\n".join(lines)
    if len(dump) > _MAX_DUMP_CHARS:
        dump = dump[-_MAX_DUMP_CHARS:]
    return dump


def _landed_since(start_iso: str) -> str:
    """What GitHub holds for the window: the commits on main and the issues
    that changed, so a fix that landed is in front of the summariser.

    A page can be fixed within the hour by a commit, and a compact that saw
    only notes and chat would write "no resolution recorded" into memory that
    rides every prompt for months.
    Tier-2: a read that fails says so in the block, so the summariser knows it
    cannot rule a resolution out, and the compact still runs.
    """
    # GitHub reads "+00:00" in a query string as " 00:00" and applies the
    # wrong bound, so the stored isoformat() is sent as whats_changed sends it.
    since = datetime.fromisoformat(start_iso).astimezone(timezone.utc)
    try:
        return _changes.digest_since(
            since.strftime("%Y-%m-%dT%H:%M:%SZ"), _changes.MAX_COMMITS_PER_CALL
        )
    except Exception as exc:  # noqa: BLE001 - Tier-2: the compact runs without it
        log.warning("compact could not read what changed: %s", exc)
        return (
            f"WHAT CHANGED: COULD NOT READ GitHub ({exc}). A resolution may "
            "exist that you cannot see, so do not write that something has none."
        )


def compact_week() -> str | None:
    """Summarise the window since the last compact into one
    `weekly_compacts` row. Returns the summary text, or None when the
    window is too fresh/empty or the brain is unavailable (deferred to
    the next run)."""
    end = datetime.now(timezone.utc)
    start_iso = state.latest_week_end() or (end - timedelta(days=7)).isoformat()
    end_iso = end.isoformat()

    start = datetime.fromisoformat(start_iso)
    if end - start < timedelta(hours=_MIN_WINDOW_HOURS):
        log.info("compact window under %dh; skipping", _MIN_WINDOW_HOURS)
        return None

    dump = _render_dump(start_iso, end_iso)
    if not dump.strip():
        log.info("compact window empty; skipping")
        return None

    if budget.is_tripped():
        log.warning("budget tripped; deferring this week's compact")
        return None

    outcome = _brain.run(
        system=f"{principles.render()}\n\n{_TASK}",
        messages=[
            {"role": "user", "content": f"{dump}\n\n{_landed_since(start_iso)}"}
        ],
        tools=[],
        cap=1,
    )
    if not outcome.finished:
        # Deferred, not lost (Tier-2): the raw rows stay put and the next
        # run's window covers them.
        log.warning("compact brain unavailable (%s); deferring", outcome.status)
        return None

    parts = [
        block.text
        for block in outcome.response.content
        if getattr(block, "type", None) == "text" and block.text
    ]
    summary = "".join(parts).strip()
    if not summary:
        log.warning("compact brain returned empty; deferring")
        return None

    state.add_compact(week_start=start_iso, week_end=end_iso, text=summary)
    log.info("weekly compact stored (%d chars, %s -> %s)", len(summary), start_iso, end_iso)
    return summary
