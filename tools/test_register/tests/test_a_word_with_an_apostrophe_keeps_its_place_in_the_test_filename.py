"""A word with an apostrophe in the --says sentence survives into the filename.

WHAT IT PINS. `tools.test_register.scaffold`, at the public seam the
`--new` command calls: the path of the test file it writes.

The filename keeps only words made of letters and digits. "widget's" is not
one, so without the apostrophe rule it would vanish whole and a sentence about
"the widget's own label" would produce `test_the_own_label.py`, a name that
says something other than the invariant. The apostrophe is dropped from inside
the word and the word stays: "widgets".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Written out by
hand from the rule: every word of the sentence, lowercased, apostrophes
removed, joined by underscores. Both the straight and the typographic
apostrophe are covered, since either arrives from a pasted sentence.

WHAT IT WAS PROVED AGAINST. Its register row puts back the filter that dropped
any word not purely alphanumeric before the apostrophe was stripped.

GUARDS. Readable test filenames.
"""
from __future__ import annotations

from pathlib import Path

from tools.test_register import scaffold

_ROWS = "tools/test_register/_rows.py"
_EMPTY_REGISTER = "from ._row import Break, Row\n\nROWS = (\n)\n"


def _repo(tmp_path: Path, module: str) -> Path:
    """A scratch repository holding one module and an empty register."""
    (tmp_path / module).mkdir(parents=True)
    (tmp_path / module / "__init__.py").write_text('"""A module."""\n', encoding="utf-8")
    rows = tmp_path / _ROWS
    rows.parent.mkdir(parents=True, exist_ok=True)
    rows.write_text(_EMPTY_REGISTER, encoding="utf-8")
    return tmp_path


def test_a_word_with_an_apostrophe_keeps_its_place_in_the_test_filename(tmp_path: Path) -> None:
    """Straight and typographic apostrophes are removed and the word is kept."""
    repo = _repo(tmp_path, "widgets")

    straight, _ = scaffold("widgets", "the widget's own label", repo)
    curly, _ = scaffold("widgets", "a door’s hinge turns", repo)

    assert straight == "widgets/tests/test_the_widgets_own_label.py"
    assert curly == "widgets/tests/test_a_doors_hinge_turns.py"
