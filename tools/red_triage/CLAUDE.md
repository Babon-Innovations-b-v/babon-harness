# tools/red_triage/

**Tier S sealed seam.** Whose fault one red gate run is: the commit's, a test's
or the box's. Public names: `triage`, `Triage`, `COMMIT`, `TEST`, `SETUP`,
`FLIPPED`, `OLD`. Module test, one function over parametrized cases, in
`tests/`. Bible: `infra/deploy`.

## Rules

- **Nothing ever holds the queue.** A red is a WRONG COMMIT (reverted on main
  and handed back at once, as the eject does) or a WRONG TEST (the failing test
  also fails on the last good tree, or the same commit passes it on a re-run):
  that test is quarantined with no time limit and the deploy goes on. Do not add
  a third answer that waits for a person.
- **A test the commit added or changed is never OLD.** The last good tree runs
  other code for it; only a flip can quarantine it. The caller passes those
  files in `new_files`.
- **A run that could not happen is `setup`**, never a revert and never a
  quarantine: no evidence either way.
- **Pure, stdlib, system `python3`.** The gate step runs it before any venv
  exists; it reads JSON on stdin and does no I/O of its own.
