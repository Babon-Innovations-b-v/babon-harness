# tools/test_register/

One row per test in this repository. `_rows.py` is the data; everything else
reads it. Public names are `__all__` in `__init__.py`: the rows and the check,
the levels (`module_groups`, `level_of`), the quarantine (`with_quarantine`,
`gate_quarantines`, `left_out`, `owner_login`, `quarantine_issue`) and the
birth (`scaffold`, `live_reads`, `sealed_argv`, `read_pin`, `pin_drift`). Module
test, one function over parametrized cases:
`tests/test_a_test_that_cannot_fail_is_caught_by_its_own_break.py`.

## Rules

- **Never write a row by hand.** `python3 -m tools.test_register --new <module>
  --says "<invariant>"` writes the test file and its row together. A test with
  no row is refused by `--check`, at commit time and again in the deploy gate.
- **Stdlib only, system `python3`.** `tools/gate_scope` imports it before any
  venv exists.
- **Absolute imports across the package boundary** (`from tools.test_register
  import ...`): pytest can load `gate_scope` as a top-level package, and a
  relative import then fails with "beyond top-level package".
- **A break edits a source file, never the test.** `check` refuses it.
- **`runs_when` is globs, never bare prefixes.** A row whose trigger matches
  everything runs on every commit, and `scope none` stops existing.
- **Nothing here runs on a timer.** Replay runs on the rows a commit touches,
  so a finding always belongs to a commit.
- **One test per module and per module group, one test function per file.**
  `--check` refuses a level with no test, a second row for one level and a
  second `test_*` function in a file. The debt lists in `_debt.py` only shrink
  (`UNTESTED_DEBT`: delete the entry with the level's new test); a new check
  is a parametrized case of the level's one test.
- **Only the gate writes a row's `quarantined=` line.** The gate believes only
  a line on main that `GATE_AUTHOR_EMAIL` added; `--check --base --author`
  refuses one any other author adds. The owner (`people` name or login, else
  the project owner, `.claude/project.json`) deletes it with the fix. No time
  limit. `left_out` drops a quarantined file, ignores one under a selected
  directory, and says `emptied` only when it removed every selected path.
- **A new test is sealed.** `--check --base` refuses a python test this change
  gives its first row when `live_reads` finds it reading the live machine, the
  wall clock or the network; the hook then runs it in the gate image
  (`--sealed-run`, exit 99 = this box could not, never a verdict). The gate's
  own `--check` has no `--base`, so an old test never holds the queue.

## Gotchas

- **A skipped run is not proof.** pytest exits 0 when every test in a file
  skips, so the replay reads the summary and returns `unproven`, never `green`.
- **A row's break anchor must appear exactly once** in its file.
- **Changing `_modules.py` or `_groups.py` moves levels and shards**: rerun
  `--check`. `--shards` keys a selection by innermost module group.
- **`--workers N` replays on hard-linked copies**: `replay` unlinks a file
  before breaking it, and a `green` from a copy is replayed again in the tree
  before it refuses anything. A replay that crashed exits 3, never 1.
