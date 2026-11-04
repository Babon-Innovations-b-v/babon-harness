"""A module or module group with a second test is refused, with the reason.

OWNS: the one-test-per-level rule as `--check` enforces it: one test per
module, one per module group, the full suite on top.

DOES NOT OWN: what a level is (`_level.py`), the known debt (`_debt.py`, handed
in by `__main__.py`).

WHO IS EXCUSED. A row on `DEBT`, and nothing else: the extra tests that were
already in the tree the day the rule arrived, listed once so main stayed green.
Folding them into one test per level deletes their entries; a debt entry whose
test is gone is refused, so the list can only shrink.

NO WRITTEN EXCUSE. A row's `note` excuses nothing. Sessions push straight to
main and nobody reads a reason in a diff, so an excuse that is written is an
excuse that is taken. A new check goes into the level's existing test.

Every other row is refused when another row tests the same level and that other
row is either unexcused too or on the debt list: a module that is already over
its one test does not get a fourth because its third was grandfathered.

VALIDATION IS DATA, like `_check.py`: sentences, never an exception.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence

from ._level import level_of
from ._row import Row


def second_tests(
    rows: Sequence[Row],
    modules: Collection[str],
    groups: Collection[str],
    debt_list: Sequence[tuple[str, str]] = (),
) -> tuple[str, ...]:
    """Every level with more than one unexcused test, and every stale debt entry.

    `debt_list` is `_debt.DEBT` when the real register is checked; a scratch
    register in a test passes its own.
    """
    debt = {test for _level, test in debt_list}
    by_level: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        by_level[level_of(row, modules, groups)].append(row)

    problems = []
    for level, tested in sorted(by_level.items()):
        fresh = [row.test for row in tested if row.test not in debt]
        owed = [row.test for row in tested if row.test in debt]
        if len(fresh) > 1 or (fresh and owed):
            problems.append(_refusal(level, fresh, owed))

    present = {row.test for row in rows}
    problems.extend(
        f"{test} is on the debt list in _debt.py but has no row any more: "
        f"delete its entry, the list only shrinks"
        for _level, test in debt_list
        if test not in present
    )
    return tuple(problems)


def _refusal(level: str, fresh: list[str], owed: list[str]) -> str:
    return (
        f"{level} would have {len(fresh) + len(owed)} tests "
        f"({', '.join(sorted(fresh + owed))}), and the rule is one per module and "
        f"one per module group. Fold the new checks into the test it "
        f"already has; a note does not excuse a second test."
    )
