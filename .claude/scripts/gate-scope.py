#!/usr/bin/env python3
"""Decide whether a change needs the project's tests at all, before the gate runs them.

A spawned project starts with the part every project can use: a change that touches only
documents and working notes runs nothing, and anything else runs everything. When the full run
gets slow, grow this into a graph that picks only the suites a change can reach (see
`tools/gate_scope/` in this repository for a grown one, and the infra/deploy chapter of the bible).

The rules, which a grown version keeps:
- Unknown means full. A path this file does not recognise, no origin/main to compare with,
  `--full`, GATE_FULL=1, or a run on CI: everything runs.
- CI always runs everything. It is the net under whatever a scoped local run skips.
- Only documents changed: nothing runs.

Run: python3 .claude/scripts/gate-scope.py [--full]
Prints MODE none|full, then WHY lines saying why. The gate reads the MODE line.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Documents and the working notes around them: nothing a build or a test reads. A project that
# keeps real inputs under one of these (a docs site that is built, say) takes it out of here.
DOC_PREFIXES = (".claude/", "docs/", ".github/ISSUE_TEMPLATE/")
DOC_SUFFIXES = (".md",)
DOC_NAMES = ("LICENSE", ".gitignore", ".gitattributes", ".mcp.json")
# The harness's own code under .claude/: the hooks, the scripts, the index and the settings that
# wire them run in every session, and their tests are part of the gate.
CODE_PREFIXES = (".claude/hooks/", ".claude/scripts/", ".claude/index/", ".claude/settings.json")


def git_lines(*args):
    """One git command's output as lines, or None when git refuses (no origin/main, say)."""
    run = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    return run.stdout.splitlines() if run.returncode == 0 else None


def changed_paths():
    """Every path this change touches against origin/main, or None with nothing to compare."""
    base = git_lines("merge-base", "origin/main", "HEAD")
    if not base:
        return None
    paths = set(git_lines("diff", "--name-only", base[0]) or [])
    paths.update(git_lines("diff", "--name-only", "HEAD") or [])
    paths.update(git_lines("ls-files", "--others", "--exclude-standard") or [])
    return paths


def is_document(path):
    """True for a path no build or test reads."""
    if path.startswith(CODE_PREFIXES) and not path.endswith(DOC_SUFFIXES):
        return False
    return path.startswith(DOC_PREFIXES) or path.endswith(DOC_SUFFIXES) or path in DOC_NAMES


def forced_reason(argv):
    """Why everything runs regardless of the change, or an empty string."""
    if "--full" in argv or os.environ.get("GATE_FULL") == "1":
        return "asked for the full gate"
    if os.environ.get("CI"):
        return "running on CI, which always runs everything"
    return ""


def plan(changed, forced):
    """The decision as (mode, reasons)."""
    if forced:
        return "full", [forced]
    if changed is None:
        return "full", ["no origin/main to compare with"]
    code = sorted(path for path in changed if not is_document(path))
    if not code:
        return "none", ["only documents changed"]
    return "full", [f"{len(code)} changed files are not documents, first {code[0]}"]


def main(argv):
    mode, reasons = plan(changed_paths(), forced_reason(argv))
    print(f"MODE {mode}")
    for reason in reasons:
        print(f"WHY {reason}")


if __name__ == "__main__":
    main(sys.argv[1:])
