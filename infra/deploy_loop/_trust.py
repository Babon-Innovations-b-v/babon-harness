"""Which commit the lane's own verdicts let the cycle ship without testing again.

The lane (`infra/auto-deploy/commit_gate/`) judges every commit on its own tree. The
cycle may ship commit N on those verdicts alone when every commit from the
bookmark up to N is accounted for, oldest first:

    green, replayed, this tree ......... covered
    green, batch:<sha>, this tree ...... covered, never the head: the batch
                                         was verified on a later commit's
                                         tree (`commit_gate/batch.sh`)
    no verdict, selector says `none` ... covered (no test can reach it)
    red, this tree ..................... covered only once a later commit that
                                         reverts it is itself covered
    anything else ...................... the walk stops here

The stop is named, because only one kind is worth waiting for:

    unanswered    no verdict yet: the lane may still be running it
    unreplayed    a green whose break replay did not finish
    other_tree    a line about another sha or tree, or one that cannot be read
    unlicensed    narrowing is not licensed and the verdict ran less than `full`

UNLICENSED. Narrowing is licensed only while the nightly full audit
is fresh and has found no selection miss; step 20 says which. Without the
licence a narrowed green proves nothing about the tests it left out, so only a
`full` green counts and `none` from the selector covers nothing.

N is the newest covered commit with no red left open beneath it. Why that is
enough: a test that passed on commit k's tree and fails on N's needs some later
commit j that changed what it imports, and j's own selection then picked that
test, so j was red. That is the rule narrowing already rests on.

`replayed` is the word only a green whose break replay also passed carries, so
a verdict from a lane that ran the suite alone is not trusted. Every unknown
stops the walk: an unreadable line, another sha, another tree, a selector that
could not answer. Stopping ships less, never more, and the cycle then gates
the range itself, as it always has.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

GREEN_WORD = "replayed"
#: What a commit a green batch covered carries instead.
BATCH_WORD = "batch:"
#: How far past the bookmark the walk looks, the 50 nearest it, the same clamp
#: `steps/20-changes.sh` keeps so the jump never outruns the status doors' window.
WALK_LIMIT = 50

#: What a commit reverts: git's own line, or the eject's `Auto-Eject:` trailer,
#: which is the only one an eject revert carries. Read as git's line alone, an
#: ejected red would stay open beneath every later commit, and the walk would
#: ship nothing until the bookmark had passed it.
_REVERTS = re.compile(r"^(?:This reverts commit|Auto-Eject:) ([0-9a-f]{40})", re.MULTILINE)


@dataclass(frozen=True)
class Commit:
    """One commit after the bookmark, as the walk sees it."""

    sha: str
    tree: str
    verdict: str
    reverts: str = ""


@dataclass(frozen=True)
class Trust:
    """The walk's answer: `head` is '' when nothing may ship untested."""

    head: str
    reason: str
    stopped_at: str = ""


def _own_word(commit: Commit, licensed: bool = True) -> str:
    """`green`, `red`, or the stop reason for a verdict line about this commit."""
    fields = commit.verdict.split()
    if not fields:
        return "unanswered"
    if len(fields) < 6 or fields[0] != commit.sha or fields[5] != commit.tree:
        return "other_tree"
    if fields[1] == "red":
        return "red"
    if fields[1] != "green":
        return "other_tree"
    if fields[4] != GREEN_WORD and not fields[4].startswith(BATCH_WORD):
        return "unreplayed"
    if not licensed and fields[2] != "full":
        return "unlicensed"
    return "batch" if fields[4].startswith(BATCH_WORD) else "green"


def trusted_head(commits: Iterable[Commit], scope_is_none: Callable[[Commit], bool],
                 licensed: bool = True) -> Trust:
    """Walk `commits` oldest first and name the newest one that may ship untested."""
    head = ""
    open_reds: set[str] = set()
    for commit in commits:
        word = _own_word(commit, licensed)
        if word == "red":
            open_reds.add(commit.sha)
            continue
        if word == "batch":
            open_reds.discard(commit.reverts)
            continue
        if word != "green":
            if not licensed:
                return Trust(head, "unlicensed", commit.sha)
            if not scope_is_none(commit):
                return Trust(head, word, commit.sha)
        open_reds.discard(commit.reverts)
        if not open_reds:
            head = commit.sha
    if open_reds:
        return Trust(head, "red", sorted(open_reds)[0])
    return Trust(head, "all" if head else "empty")


def first_parent_commits(repo: str, bookmark: str, tip: str, verdicts: Path) -> list[Commit]:
    """The commits after `bookmark` up to `tip`, oldest first, each with its verdict line."""
    shown = subprocess.run(
        ["git", "-C", repo, "log", "--first-parent", "--reverse",
         "--format=%H%x00%T%x00%B%x1e", f"{bookmark}..{tip}"],
        capture_output=True, text=True, check=True, timeout=60,
    ).stdout
    commits = []
    for record in shown.split("\x1e"):
        parts = record.strip("\n").split("\x00")
        if len(parts) < 3 or not parts[0]:
            continue
        sha, tree, body = parts[0].strip(), parts[1], parts[2]
        try:
            verdict = (verdicts / sha).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            verdict = ""
        found = _REVERTS.search(body)
        commits.append(Commit(sha, tree, verdict, found.group(1) if found else ""))
    return commits[:WALK_LIMIT]


def selector_says_none(repo: str, commit: Commit, cache: Path | None) -> bool:
    """Whether the gate's selector reaches no test from this commit's own diff.

    Asked the way the lane asks it (`<sha>^..<sha>`), with the selector in
    `repo`. Only a clean `none` is yes; a crash, a timeout or any other word is
    no. The answer is kept per (sha, tree) in `cache`, since a commit is asked
    again every cycle until it ships.
    """
    remembered = cache / commit.sha if cache else None
    if remembered is not None:
        try:
            word, tree = remembered.read_text(encoding="utf-8").split()
            if tree == commit.tree:
                return word == "none"
        except (OSError, UnicodeDecodeError, ValueError):
            pass
    word = _ask_selector(repo, commit.sha)
    if remembered is not None and word:
        try:
            remembered.parent.mkdir(parents=True, exist_ok=True)
            remembered.write_text(f"{word} {commit.tree}\n", encoding="utf-8")
        except OSError:
            pass
    return word == "none"


def _ask_selector(repo: str, sha: str) -> str:
    """The selector's scope word for one commit's diff, '' when it could not answer."""
    with tempfile.TemporaryDirectory(prefix="trust-scope-") as work:
        changed = Path(work) / "changed"
        try:
            diff = subprocess.run(
                ["git", "-C", repo, "-c", "core.quotePath=false", "diff", "--name-only",
                 "--no-renames", f"{sha}^", sha],
                capture_output=True, text=True, check=True, timeout=60,
            ).stdout
            changed.write_text(diff, encoding="utf-8")
            answer = subprocess.run(
                ["python3", "-m", "tools.gate_scope", "--changed-file", str(changed),
                 "--repo", repo, "--out-paths", str(Path(work) / "paths"),
                 "--out-json", str(Path(work) / "scope.json")],
                cwd=repo, capture_output=True, text=True, timeout=120,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
    word = answer.stdout.strip()
    return word if answer.returncode == 0 and word in ("none", "selected", "full") else ""
