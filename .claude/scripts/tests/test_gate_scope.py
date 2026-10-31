"""Pin gate-scope's decisions: documents run nothing, anything else and every doubt run all.

Run: python3 -m pytest .claude/scripts/tests/
"""

import importlib.util
import pathlib

_SPEC = importlib.util.spec_from_file_location(
    "gate_scope", pathlib.Path(__file__).resolve().parent.parent / "gate-scope.py"
)
gate_scope = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate_scope)


def test_documents_alone_run_nothing():
    changed = {"CONTEXT.md", "docs/bible.md", "src/CLAUDE.md", ".claude/skills/grill/SKILL.md"}
    assert gate_scope.plan(changed, "")[0] == "none"


def test_one_file_that_is_not_a_document_runs_everything():
    assert gate_scope.plan({"docs/bible.md", "src/app.py"}, "")[0] == "full"


def test_nothing_to_compare_with_runs_everything():
    assert gate_scope.plan(None, "")[0] == "full"


def test_asking_runs_everything_even_for_documents():
    assert gate_scope.plan({"README.md"}, gate_scope.forced_reason(["--full"]))[0] == "full"


def test_ci_runs_everything(monkeypatch):
    monkeypatch.setenv("CI", "true")
    assert gate_scope.forced_reason([]) != ""


def test_a_quiet_local_run_is_not_forced(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GATE_FULL", raising=False)
    assert gate_scope.forced_reason([]) == ""


def test_the_harness_code_under_dot_claude_runs_everything():
    for path in (".claude/hooks/md_guard.py", ".claude/index/server.py", ".claude/settings.json"):
        assert gate_scope.plan({path}, "")[0] == "full", path
