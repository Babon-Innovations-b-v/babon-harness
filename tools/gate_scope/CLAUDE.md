# tools/gate_scope/

Decides which tests one commit can reach, for the deploy gate. Sealed seam:
`decide` and `Decision` are the only public names. `infra/auto-deploy/steps/20-changes.sh`
asks, `steps/40-gate.sh` obeys, `commit_gate/run_one.sh` asks the commit's own
copy, and `audit_full_run.sh` (harness-gate-audit.timer, nightly) is the
unselected run whose green stamp licenses narrowing at all. Module test:
`tests/test_the_gate_runs_every_test_a_change_can_break_on_a_fresh_graph_in_the_environment_the_audit_checks.py`.

## Rules

- **Unknown means full.** An unrecognised path, an unparseable or vanished
  `.py`, an unreadable `--ignore` list: all `full`. Never `none`, never an
  exception. Failing toward more testing is the whole safety argument.
- **The triggers live in the register**, `runs_when` on each row of
  `tools/test_register`. Import it absolutely (`from tools.test_register import
  ...`): pytest can load this package as top-level, and a relative import then
  fails.
- **The selection holds test files and directories only.** A source file handed
  to pytest is imported as a test module, which can abort the run (rc 2, red).
- **`.claude/` follows `.claude/scripts/gate-scope.py`**: code under hooks,
  scripts, index and settings.json; everything else there is a document. A test
  compares the two classifiers.
- **Stdlib only, system `python3`.** The scope is decided before any venv
  exists, and must not break along with the environment it verifies.
- **The `--ignore` list is read out of `40-gate.sh`, never restated**, here, in
  the audit and in the verifying lane.

## Gotchas

- **A new test needs its register row in the SAME commit**:
  `python3 -m tools.test_register --new <module> --says "<invariant>"` writes
  both. A floor test with no row runs on every commit and `scope none` becomes
  unreachable.
- **A conftest is scanned for read verbs as SUBSTRINGS, comments included.** A
  root conftest merely mentioning `subprocess` or `open(` puts the whole suite on
  the floor.
