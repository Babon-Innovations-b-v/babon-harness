"""The diagram tools work on a fresh repository and refuse what a machine can see.

WHAT IS CHECKED. Three promises a new owner relies on before drawing anything.
The link map passes on an empty set, so a fresh clone is clean rather than red.
The MCP tools import and answer without the ``mcp`` library, which only
``server.py`` needs, so their logic runs on the standard library. And
``page_faults`` refuses a page that cannot be told (no slides) or whose edge
names a box the page never placed, before anything is written.

HOW THE EXPECTED ANSWER IS DERIVED. The broken page is built here by hand with
one known defect each, so the expected fault is the one that was planted.
"""
from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_MCP = _REPO / "docs" / "diagrams" / "mcp"


def _tool(name: str):
    if str(_MCP) not in sys.path:
        sys.path.insert(0, str(_MCP))
    return importlib.import_module(name)


def _good_page() -> tuple[dict, dict]:
    nodes = {
        box: {"type": "backend", "label": box.title(), "sublabel": "a box",
              "note": "What it does.", "bible": f"The {box} does a thing."}
        for box in ("door", "gate", "store")
    }
    spec = {"title": "A page", "subtitle": "one line",
            "legend": {"backend": "a service", "edge-default": "a call"},
            "nodes": nodes,
            "slides": [{"label": "the door", "add": ["door"]},
                       {"label": "the gate", "add": ["gate", "door-gate"]},
                       {"label": "the store", "add": ["store", "gate-store"]}]}
    layout = {"canvas": [900, 520],
              "boxes": {"door": [40, 60], "gate": [280, 60], "store": [520, 60]},
              "edges": [["door", "gate", ""], ["gate", "store", ""]]}
    return spec, layout


def test_the_link_map_is_clean_on_an_empty_set(tmp_path: Path) -> None:
    copy = tmp_path / "repo"
    shutil.copytree(_REPO / "docs/diagrams/tools", copy / "docs/diagrams/tools")
    (copy / "docs/bible.md").write_text("# Book\n\n## workflow/loop\n\nNo drawing yet.\n")
    done = subprocess.run([sys.executable, "docs/diagrams/tools/linkmap.py"],
                          cwd=copy, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert "0 boxes claimed" in done.stdout


def test_the_tools_import_without_the_mcp_library() -> None:
    for name in ("draw_module", "link_module", "check_diagrams"):
        assert callable(getattr(_tool(name), name))


def test_a_page_with_no_faults_comes_back_empty() -> None:
    spec, layout = _good_page()
    assert _tool("page_faults").page_faults(spec, layout) == []


def test_a_page_that_cannot_be_told_is_refused() -> None:
    spec, layout = _good_page()
    spec.pop("slides")
    faults = _tool("page_faults").page_faults(spec, layout)
    assert any("slide" in fault for fault in faults), faults


def test_an_edge_to_a_box_never_placed_is_refused() -> None:
    spec, layout = _good_page()
    layout["edges"].append(["store", "nowhere", ""])
    faults = _tool("page_faults").page_faults(spec, layout)
    assert any("nowhere" in fault for fault in faults), faults
