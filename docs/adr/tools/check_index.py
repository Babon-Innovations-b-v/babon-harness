"""Fail when the ADR index stops telling the truth about the ADR files.

Every attempt to keep an index tidy by hand relies on someone maintaining a mirror, and mirrors
drift: a status says "accepted" in the index and "superseded" in the file, or two numbers get
handed out twice by parallel sessions that each read the highest number and incremented. A script
that fails beats a habit that slips.

Checks, in the order a reader would notice them:

1. every ``NNNN-*.md`` has exactly one row in the index, and every row points at a real file;
2. the status in the index matches the status line in the file (the file is authoritative);
3. no number is used twice, and no retired number has come back;
4. a superseded or reversed ADR sits in the Historical section, not in a live table;
5. the carve-out ADR's list and root ``CLAUDE.md``'s copy of it still agree.

Run: ``python3 docs/adr/tools/check_index.py``. Exits 1 and prints one line per problem.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ADR_DIR = Path(__file__).resolve().parent.parent
REPO = ADR_DIR.parent.parent
# Numbers deleted or never used. A retired number never comes back: every citation in
# the tree is a bare "ADR-NNNN", so reuse makes all of them ambiguous.
RETIRED: set[str] = set()
# The ADR whose carve-out list root CLAUDE.md mirrors (ADR-0002 in a fresh repo).
CARVE_OUT_ADR = "0002-no-loose-files-outside-the-carve-out.md"
STATUS_WORDS = ("accepted", "superseded", "reversed", "proposed")
HISTORICAL_HEADING = "### Historical"


def _status_word(text: str) -> str | None:
    """First recognised status word in a status line, or None when there is no status line."""
    for line in text.splitlines()[:12]:
        stripped = line.strip().lstrip("*_ ")
        if not stripped.lower().startswith("status"):
            continue
        after = stripped.split(":", 1)[1].lower() if ":" in stripped else ""
        for word in STATUS_WORDS:
            if word in after:
                return word
    return None


def _index_rows(index_text: str) -> dict[str, tuple[str, bool]]:
    """Map ADR number to (status cell, is_in_historical_section) for every table row."""
    rows: dict[str, tuple[str, bool]] = {}
    historical = False
    for line in index_text.splitlines():
        if line.startswith("###") or line.startswith("## "):
            historical = line.strip().startswith(HISTORICAL_HEADING)
        match = re.match(r"\|\s*\[(\d{4})\]\(([^)]+)\)\s*\|[^|]*\|\s*([^|]+?)\s*\|", line)
        if match:
            rows[match.group(1)] = (match.group(3).strip(), historical)
    return rows


def _carve_out_lists() -> tuple[set[str], set[str]]:
    """The framework-file names the carve-out ADR allows, and root CLAUDE.md's copy of the list."""
    pattern = re.compile(r"`([^`]+)`")
    adr = (ADR_DIR / CARVE_OUT_ADR).read_text()
    carve = adr.split("## Carve-out", 1)[1].split("append-only by ADR amendment", 1)[0]
    # Bullet lines only: the surrounding prose also uses backticks, and a filename mentioned in
    # an explanation is not an entry in the list.
    bullets = "\n".join(line for line in carve.splitlines() if line.lstrip().startswith("- "))
    claude = (REPO / "CLAUDE.md").read_text()
    # Only the parenthesised list itself; the sentences after it name other files (this script,
    # for one) that are prose, not carve-out entries.
    rule = claude.split("**No loose files outside the carve-out", 1)[1].split("Anything else loose", 1)[0]
    return set(pattern.findall(bullets)), set(pattern.findall(rule))


def check() -> list[str]:
    problems: list[str] = []
    index_text = (ADR_DIR / "0000-index.md").read_text()
    rows = _index_rows(index_text)

    files: dict[str, Path] = {}
    for path in sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")):
        if path.name.startswith("0000-"):
            continue  # the index is not an ADR
        number = path.name[:4]
        if number in files:
            problems.append(f"{number}: used twice ({files[number].name}, {path.name})")
            continue
        if number in RETIRED:
            problems.append(f"{number}: retired number is back in use ({path.name})")
        files[number] = path

    for number in sorted(set(files) - set(rows)):
        problems.append(f"{number}: no row in the index ({files[number].name})")
    for number in sorted(set(rows) - set(files)):
        problems.append(f"{number}: index row points at no file")

    for number in sorted(set(files) & set(rows)):
        cell, in_historical = rows[number]
        file_word = _status_word(files[number].read_text())
        cell_word = next((w for w in STATUS_WORDS if w in cell.lower()), None)
        if file_word is None:
            if cell_word != "accepted":
                problems.append(
                    f"{number}: file states no status, so the index must say accepted, not {cell!r}"
                )
        elif file_word != cell_word:
            problems.append(
                f"{number}: file says {file_word!r}, index says {cell_word!r} (the file wins)"
            )
        retired_status = (file_word or cell_word) in {"superseded", "reversed"}
        if retired_status and not in_historical:
            problems.append(f"{number}: {file_word or cell_word} but still listed in a live table")
        if not retired_status and in_historical:
            problems.append(f"{number}: listed under Historical but its status is not retired")

    adr_carve, claude_carve = _carve_out_lists()
    for name in sorted(adr_carve - claude_carve):
        problems.append(f"carve-out: {name} is in {CARVE_OUT_ADR} but not in root CLAUDE.md")
    for name in sorted(claude_carve - adr_carve):
        problems.append(f"carve-out: {name} is in root CLAUDE.md but not in {CARVE_OUT_ADR}")

    return problems


def main() -> int:
    problems = check()
    for problem in problems:
        print(problem)
    if problems:
        print(f"\n{len(problems)} problem(s). The ADR file is authoritative; fix the index to match.")
        return 1
    print(f"ADR index clean: {len(_index_rows((ADR_DIR / '0000-index.md').read_text()))} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
