"""Pin gate-scope's decisions: documents run nothing, anything else and every doubt run all.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

Run: python3 -m pytest .claude/scripts/tests/
"""
from __future__ import annotations

import inspect
import pytest


# From gate scope.

import importlib.util


import pathlib


_SPEC = importlib.util.spec_from_file_location(
    "gate_scope", pathlib.Path(__file__).resolve().parent.parent / "gate-scope.py"
)


gate_scope = importlib.util.module_from_spec(_SPEC)


_SPEC.loader.exec_module(gate_scope)


def _documents_alone_run_nothing():
    changed = {"CONTEXT.md", "docs/bible.md", "src/CLAUDE.md", ".claude/skills/grill/SKILL.md"}
    assert gate_scope.plan(changed, "")[0] == "none"


def _one_file_that_is_not_a_document_runs_everything():
    assert gate_scope.plan({"docs/bible.md", "src/app.py"}, "")[0] == "full"


def _nothing_to_compare_with_runs_everything():
    assert gate_scope.plan(None, "")[0] == "full"


def _asking_runs_everything_even_for_documents():
    assert gate_scope.plan({"README.md"}, gate_scope.forced_reason(["--full"]))[0] == "full"


def _ci_runs_everything(monkeypatch):
    monkeypatch.setenv("CI", "true")
    assert gate_scope.forced_reason([]) != ""


def _a_quiet_local_run_is_not_forced(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GATE_FULL", raising=False)
    assert gate_scope.forced_reason([]) == ""


def _the_harness_code_under_dot_claude_runs_everything():
    for path in (".claude/hooks/md_guard.py", ".claude/index/server.py", ".claude/settings.json"):
        assert gate_scope.plan({path}, "")[0] == "full", path


_REAP_SPEC = importlib.util.spec_from_file_location(
    "worktree_reap", pathlib.Path(__file__).resolve().parent.parent / "worktree-reap.py"
)


worktree_reap = importlib.util.module_from_spec(_REAP_SPEC)


_REAP_SPEC.loader.exec_module(worktree_reap)


def _a_worktree_a_live_process_uses_is_held_from_the_reaper(tmp_path, monkeypatch):
    """A process whose working folder, open file or command line is inside a worktree holds it; others hold none."""
    worktrees = tmp_path / "worktrees"
    for name in ("w1", "w2", "w3", "idle"):
        (worktrees / name).mkdir(parents=True)
    proc = tmp_path / "proc"
    (proc / "10" / "fd").mkdir(parents=True)
    (proc / "10" / "cwd").symlink_to(worktrees / "w1" / "src")
    (proc / "10" / "fd" / "3").symlink_to(worktrees / "w2" / "log.txt")
    (proc / "11").mkdir()
    (proc / "11" / "cmdline").write_bytes(b"python3\0" + str(worktrees / "w3" / "run.py").encode() + b"\0")
    (proc / "12").mkdir()
    (proc / "12" / "cwd").symlink_to(tmp_path)
    monkeypatch.setattr(worktree_reap, "PROC", proc)
    assert worktree_reap.held_by_processes(worktrees) == {"w1", "w2", "w3"}


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
    *_cases(_documents_alone_run_nothing),
    *_cases(_one_file_that_is_not_a_document_runs_everything),
    *_cases(_nothing_to_compare_with_runs_everything),
    *_cases(_asking_runs_everything_even_for_documents),
    *_cases(_ci_runs_everything),
    *_cases(_a_quiet_local_run_is_not_forced),
    *_cases(_the_harness_code_under_dot_claude_runs_everything),
    *_cases(_a_worktree_a_live_process_uses_is_held_from_the_reaper),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_gate_scope(scenario, given, uses, request):
    """Pin gate-scope's decisions: documents run nothing, anything else and every doubt run all: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
