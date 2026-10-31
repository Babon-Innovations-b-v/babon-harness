"""The overlay guard blocks an overlay growing past 500 words, and never a cut.

WHAT IS CHECKED. The guard's judgement: a per-area ``CLAUDE.md`` grown past
the budget with no ``Budget:`` line is refused, a shrinking one is let through
however heavy it still is, a written reason exempts it, and the repository-root
``CLAUDE.md`` is project instructions and never judged.

The guard is loaded by path because ``.claude/hooks/`` is not an importable
package.
"""

import importlib.util
import io
import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[3]
_GUARD = _ROOT / ".claude" / "hooks" / "local" / "overlay_guard.py"


def _load():
    assert _GUARD.exists(), f"the guard this test is about is missing: {_GUARD}"
    spec = importlib.util.spec_from_file_location("overlay_guard", _GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load()
BUDGET = guard.BUDGET_WORDS


def _decide(tmp_path, monkeypatch, relative: str, current: str, content: str) -> int:
    overlay = tmp_path / relative
    overlay.parent.mkdir(parents=True, exist_ok=True)
    overlay.write_text(current, encoding="utf-8")
    monkeypatch.setattr(guard, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": str(overlay), "content": content},
    })))
    return guard.main()


def _words(count: int) -> str:
    return " ".join(["word"] * count) + "\n"


def test_an_overlay_grown_past_the_budget_is_blocked(tmp_path, monkeypatch):
    assert _decide(tmp_path, monkeypatch, "apps/x/CLAUDE.md", _words(10), _words(BUDGET + 1)) == 2


def test_a_shrinking_overlay_is_allowed_however_heavy_it_still_is(tmp_path, monkeypatch):
    assert _decide(tmp_path, monkeypatch, "apps/x/CLAUDE.md",
                   _words(BUDGET * 3), _words(BUDGET * 2)) == 0


def test_a_budget_line_exempts_the_overlay(tmp_path, monkeypatch):
    content = "Budget: 900 words; every command here is load-bearing.\n" + _words(BUDGET + 1)
    assert _decide(tmp_path, monkeypatch, "apps/x/CLAUDE.md", _words(10), content) == 0


def test_the_root_file_is_not_an_overlay(tmp_path, monkeypatch):
    assert _decide(tmp_path, monkeypatch, "CLAUDE.md", _words(10), _words(BUDGET + 1)) == 0
