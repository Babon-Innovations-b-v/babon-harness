"""The knowledge index, collect sources, rebuild the FTS5 table,
search it, and keep it fresh on its own.

Sources: the bible chapters and ADRs from the image's `docs/`, every
markdown page the owner drops into this package's knowledge directory, and
soul, CONTEXT and the issues via `gh`. Collection is behind
small seams (`_read_docs`, `_gh_text`, `_gh_issues`) so a test drives
`rebuild(sources=...)` and `search(...)` without touching disk or GitHub.

FAILURE POLICY: Tier-2 best-effort, a source that cannot be read is
skipped (the index is still useful), and `ensure_fresh` swallows a rebuild
fault so a search never dies on a stale index; the last good index stays.
The FTS writes themselves propagate within a rebuild.
"""
from __future__ import annotations

from apps.assistant.shared.project import GITHUB_REPO

import glob
import json
import logging
import os
import re
import subprocess
import threading
import time

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

log = logging.getLogger("openclaw.knowledge")

_REPO = GITHUB_REPO
_DOCS_ROOT = os.environ.get("OPENCLAW_DOCS_ROOT", "docs")
_FRESH_MAX_AGE_S = 1800  # 30 min: a search past this rebuilds first
_MAX_ISSUES = 200
_TIMEOUT_S = 25

Source = tuple[str, str, str, str]  # (source, ref, title, body)


# ── tables ───────────────────────────────────────────────────────────────
def _ensure_tables(conn) -> None:
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts "
        "USING fts5(source, ref, title, body)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS knowledge_meta (k TEXT PRIMARY KEY, v TEXT)")


# ── sources ──────────────────────────────────────────────────────────────
def _split_chapters(text: str, source: str) -> list[Source]:
    """Split a markdown doc on its '## ' headings into (source, ref, title,
    body) rows, so a search returns the relevant chapter, not the whole file."""
    rows: list[Source] = []
    parts = re.split(r"^(##\s+.+)$", text, flags=re.MULTILINE)
    if len(parts) == 1:  # no chapters: index whole
        return [(source, source, source, text.strip())]
    for index in range(1, len(parts), 2):
        heading = parts[index].lstrip("# ").strip()
        body = parts[index + 1] if index + 1 < len(parts) else ""
        rows.append((source, heading, heading, body.strip()))
    return rows


def _read_docs(docs_root: str) -> list[Source]:
    """Bible chapters and each ADR from the image's docs/, plus every page in
    the knowledge directory beside this module. That directory ships with one
    example page; the owner adds how-to pages there and they are indexed on
    the next rebuild."""
    rows: list[Source] = []
    bible = os.path.join(docs_root, "bible.md")
    if os.path.exists(bible):
        rows += _split_chapters(open(bible, encoding="utf-8").read(), "bible")
    for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), "*.md"))):
        if os.path.basename(path) == "CLAUDE.md":
            continue
        rows += _split_chapters(open(path, encoding="utf-8").read(), "knowledge")
    adr_dir = os.path.join(docs_root, "adr")
    for path in sorted(glob.glob(os.path.join(adr_dir, "*.md"))):
        text = open(path, encoding="utf-8").read()
        title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), os.path.basename(path))
        rows.append(("adr", os.path.basename(path), title, text))
    return rows


def _run_gh(args: list[str]) -> tuple[int, str]:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=_TIMEOUT_S, check=False)
    return result.returncode, result.stdout


def _gh_text(path: str, source: str) -> list[Source]:
    """Fetch a repo file's raw content via gh (for sources not in the image:
    soul, CONTEXT). Empty list if it cannot be read."""
    rc, out = _run_gh(["api", f"repos/{_REPO}/contents/{path}",
                       "-H", "Accept: application/vnd.github.raw"])
    if rc != 0 or not out.strip():
        return []
    return [(source, path, source, out)]


def _memory_rows() -> list[Source]:
    """the assistant's OWN memory as searchable rows: every journal note and every
    weekly compact. So when asked something it once learned ('did the disk
    alert ever get fixed'), it finds its own note before saying 'I don't know'. Read via
    the unbounded state helpers, not the small prompt windows."""
    from apps.assistant.core import state

    rows: list[Source] = []
    for note in state.all_notes():
        ref = f"note-{note['id']}"
        who = f" ({note['person']})" if note.get("person") else ""
        title = f"journal {note.get('added_at', '')[:10]}{who}"
        rows.append(("journal", ref, title, note.get("text", "")))
    for compact in state.all_compacts():
        ref = f"week-{compact.get('week_end', '')}"
        title = f"weekly recap {compact.get('week_start', '')}..{compact.get('week_end', '')}"
        rows.append(("compact", ref, title, compact.get("text", "")))
    return rows


def _gh_issues() -> list[Source]:
    """Every issue (title + body) so a report/answer grounds on the real
    backlog, not memory."""
    rc, out = _run_gh(["issue", "list", "--repo", _REPO, "--state", "all",
                       "--limit", str(_MAX_ISSUES), "--json", "number,title,body,state"])
    if rc != 0:
        return []
    try:
        issues = json.loads(out) or []
    except json.JSONDecodeError:
        return []
    return [
        ("issue", f"#{i['number']}", f"#{i['number']} [{i.get('state','')}] {i['title']}",
         (i.get("body") or ""))
        for i in issues
    ]


def collect_sources() -> list[Source]:
    """All knowledge rows from disk + gh. Best-effort: a failing source is
    simply absent."""
    rows: list[Source] = []
    try:
        rows += _read_docs(_DOCS_ROOT)
    except Exception as exc:  # noqa: BLE001, Tier-2
        log.warning("knowledge: doc read failed: %s", exc)
    for path, source in ((".claude/soul.md", "soul"), ("CONTEXT.md", "context")):
        try:
            rows += _gh_text(path, source)
        except Exception as exc:  # noqa: BLE001
            log.warning("knowledge: gh fetch %s failed: %s", path, exc)
    try:
        rows += _gh_issues()
    except Exception as exc:  # noqa: BLE001
        log.warning("knowledge: gh issues failed: %s", exc)
    try:
        rows += _memory_rows()
    except Exception as exc:  # noqa: BLE001, Tier-2: memory read must not sink the index
        log.warning("knowledge: memory read failed: %s", exc)
    return rows


# ── build / freshness / search ───────────────────────────────────────────
def rebuild(sources: list[Source] | None = None) -> int:
    """Rebuild the whole index from `sources` (default: collect live). Returns
    the row count. Replaces the previous index atomically-ish (delete+insert
    in one transaction)."""
    rows = collect_sources() if sources is None else sources
    with get_connection() as conn:
        _ensure_tables(conn)
        conn.execute("DELETE FROM knowledge_fts")
        conn.executemany("INSERT INTO knowledge_fts (source, ref, title, body) VALUES (?, ?, ?, ?)", rows)
        conn.execute("INSERT INTO knowledge_meta (k, v) VALUES ('last_indexed_at', ?) "
                     "ON CONFLICT(k) DO UPDATE SET v = excluded.v", (utcnow_iso(),))
        conn.commit()
    return len(rows)


def _seconds_since_index() -> float | None:
    with get_connection() as conn:
        _ensure_tables(conn)
        row = conn.execute("SELECT v FROM knowledge_meta WHERE k = 'last_indexed_at'").fetchone()
    if not row:
        return None
    from datetime import datetime, timezone
    then = datetime.fromisoformat(row["v"])
    return (datetime.now(timezone.utc) - then).total_seconds()


def ensure_fresh(max_age_s: int = _FRESH_MAX_AGE_S) -> None:
    """Rebuild the index if it has never been built or is older than
    `max_age_s`, so a search is always current with near-zero effort. A
    rebuild fault is swallowed: the last good index stays searchable."""
    age = _seconds_since_index()
    if age is not None and age < max_age_s:
        return
    try:
        count = rebuild()
        log.info("knowledge: reindexed %d rows", count)
    except Exception as exc:  # noqa: BLE001, Tier-2: keep the last good index
        log.warning("knowledge: reindex failed, keeping last index: %s", exc)


def start_reindexer(interval_s: int = _FRESH_MAX_AGE_S) -> None:
    """Start the background reindex daemon: build the index once at cold start,
    then keep it fresh every `interval_s`. This is why `search()` no longer
    rebuilds inline, a rebuild does gh calls and stalled the chat turn that
    happened to trip the staleness check. The daemon keeps the index warm off
    the request path. Daemon thread, Tier-2 (a rebuild fault is swallowed by
    `ensure_fresh`); safe to call once from the container entrypoint."""
    def _loop() -> None:
        while True:
            ensure_fresh(max_age_s=0)  # force a rebuild each tick, keep last on fault
            time.sleep(interval_s)

    threading.Thread(target=_loop, name="knowledge-reindexer", daemon=True).start()


#: Words too ordinary to tell one row from another. English and Dutch, because
#: a team may write its backlog in Dutch and a Dutch title would otherwise match
#: on `van`. Function words only, on purpose: no domain word belongs here,
#: because a word on this list can never carry an answer, and the index is not
#: the place to decide that `gate` or `close` says nothing. Kept here rather than
#: imported from the repository index (`.claude/index/`), because that reads a
#: git checkout, which the assistant's container does not have.
_STOP = frozenset("""
about after again all also always an and any are as at be been before being but
by can cannot did do does doing done down each even ever every few for from get
got had has have how if in into is it its just like made make many may me more
most much must my no nor not now of off on once one only or other our out over
own per same she so some such than that the their them then there these they
this those to too under until up us use used very was way we were what when
where which while who why will with would you your
aan af al als bij dan dat de deze die dit door dus een en er ge geen had heb
hebben heeft het hier hij hoe ik in is je kan kon kunnen maar me meer met mijn
moet na naar niet nog nu of om onder ons ook op over te tot toch uit van veel
voor waar wanneer want was wat we weer wel werd wie wij wil worden wordt zal ze
zij zijn zo zou
""".split())


def _content_words(query: str) -> list[str]:
    """The words of a question that can tell one row from another.

    Stop words go, and so do single letters. A question that is nothing but
    stop words keeps them, because a caller who asked for `the` deserves an
    honest search for `the` rather than a silent empty answer.
    """
    words = [word.lower() for word in re.split(r"\W+", query) if word]
    kept = [word for word in words if len(word) > 1 and word not in _STOP]
    return kept or words


def _fts_match(query: str) -> str:
    """A safe FTS5 MATCH from a free-text query: quote each content word (which
    kills FTS operators) and OR them for recall.

    Stop words are dropped first. Without that, "how does the deploy gate work"
    became `"how" OR "does" OR "the" OR "deploy" OR "gate" OR "work"`, so every
    row carrying `the` was a candidate, bm25 returned the six least bad, and a
    row that agreed with one ordinary word arrived looking exactly like a row
    that answered the question.
    """
    return " OR ".join(f'"{word}"' for word in _content_words(query))


def _matched_on(row, wanted: list[str]) -> list[str]:
    """Which of the question's words this row actually carries.

    Whole words only, in the title or the body, which is what FTS5 matched on
    in the first place (its unicode61 tokenizer does not stem), so this agrees
    with the search rather than second-guessing it.
    """
    haystack = f"{row['title']} {row['body']}".lower()
    present = set(re.split(r"\W+", haystack))
    return [word for word in wanted if word in present]


def _offered(matched: list[str], wanted: list[str], title: str) -> bool:
    """Whether a row is worth handing back at all, given what it matched.

    Three ways through, and a row needs one of them: it agreed with two or more
    of the question's words, since two words agreeing is not a coincidence; the
    question had one word to give, so one match is the whole of what was asked;
    or the row's title IS the question, which is never an accident.

    Everything else is a row sharing one ordinary word with a longer question,
    and returning nothing is the right answer there. Without this rule a
    question like "connection pooling" would return an unrelated row that
    happens to share the word "connections", carrying the same confidence as
    a right answer.
    """
    if not matched:
        return False
    if len(matched) >= 2 or len(wanted) == 1:
        return True
    return title.strip().lower() == " ".join(wanted)


def _index_age() -> str:
    """How old the index is, in words, for the header of an answer. A knowledge
    hit with no age reads with the authority of a fresh one; the age was
    already computed for `ensure_fresh` and never shown to the reader."""
    age = _seconds_since_index()
    if age is None:
        return "the index has never been built"
    if age < 120:
        return "index rebuilt just now"
    if age < 7200:
        return f"index rebuilt {int(age // 60)} min ago"
    return f"index rebuilt {age / 3600:.1f} h ago"


def search(query: str, limit: int = 6) -> str:
    """Top knowledge hits for `query`, as a plain block (source, ref, snippet).
    Reads the index the background reindexer keeps warm (`start_reindexer`); it
    does NOT rebuild inline, so a chat turn never stalls on a gh-heavy reindex.
    Empty-but-honest when nothing matches (or before the first build).

    Every row says which of the question's words it matched, and the header
    says how old the index is, so a row carrying one word out of four is
    self-evidently weak instead of arriving as an answer.
    """
    wanted = _content_words(query)
    match = _fts_match(query)
    if not match:
        return "knowledge: empty query."
    with get_connection() as conn:
        _ensure_tables(conn)
        try:
            rows = conn.execute(
                "SELECT source, ref, title, body, "
                "snippet(knowledge_fts, 3, '', '', ' … ', 14) AS snip "
                "FROM knowledge_fts WHERE knowledge_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, limit),
            ).fetchall()
        except Exception as exc:  # noqa: BLE001, Tier-2: a bad query never crashes the loop
            return f"knowledge search error: {type(exc).__name__}"
    kept = [(row, _matched_on(row, wanted)) for row in rows]
    kept = [pair for pair in kept if _offered(pair[1], wanted, pair[0]["title"])]
    if not kept:
        return f"knowledge: no hits for {query!r} ({_index_age()})."
    lines = [f"KNOWLEDGE HITS for {query!r} ({_index_age()}):"]
    for row, matched in kept:
        lines.append(
            f"[{row['source']}] {row['title']} (matched {', '.join(matched)}): {row['snip']}"
        )
    return "\n".join(lines)
