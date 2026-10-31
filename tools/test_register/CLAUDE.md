# tools/test_register/

One row per test in this repository. `_rows.py` is the data; everything else
reads it. Public names: `ROWS`, `Row`, `Break`, `check`, `replay`, `touched_by`,
`triggers_for`, `uncovered`, `modules_in`, `scaffold`. Module test:
`tests/test_a_test_that_cannot_fail_is_caught_by_its_own_break.py`.

## Rules

- **Never write a row by hand.** `python3 -m tools.test_register --new <module>
  --says "<invariant>"` writes the test file and its row together. A test with
  no row is refused by `--check`, at commit time and again in the deploy gate.
- **Stdlib only, system `python3`.** `tools/gate_scope` imports this on the
  deploy machine before any venv exists. A third-party import here breaks the
  gate's scope decision.
- **Absolute imports across the package boundary.** `gate_scope/select.py`
  says `from tools.test_register import ...`, not `from ..test_register`:
  pytest can load `gate_scope` as a top-level package, and a relative import
  then fails with "beyond top-level package".
- **A break edits a source file, never the test.** `check` refuses it.
- **`runs_when` is globs, never bare prefixes.** Too wide is worse than none: a
  row whose trigger matches everything runs on every commit, and `scope none`
  stops existing.
- **Nothing here runs on a timer.** Replay runs on the rows a commit touches,
  at commit time and again in the gate, so a finding always belongs to a commit.

## Gotchas

- **A skipped run is not proof.** pytest exits 0 when every test in a file
  skips, so the replay reads the summary and returns `unproven`, never `green`.
- **A row's break anchor must appear exactly once** in its file. Two matches is
  refused rather than guessed at.
