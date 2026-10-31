Budget: the deploy gate everything ships through. The status vocabulary, the gate's three verdicts and the eject's hand-back rule exist nowhere else and bind every file below.

# infra/auto-deploy/

The deploy loop. `auto-deploy.sh` sources `steps/NN-*.sh` in one shell, every
two minutes (`systemd/harness-auto-deploy.timer`) and on every push
(`infra/webhook/trigger-deploy.sh`). `commit_gate/` verifies queued commits
ahead of it; `branch_gate/` verifies the eject's hand-backs. First-time setup:
`sudo infra/auto-deploy/install.sh`. Bible chapter: `infra/deploy` in `docs/bible.md`.

## Rules

- **One commit per cycle.** Step 20 takes the newest commit past the bookmark
  with a green verdict for its exact tree, otherwise the next one. Never HEAD,
  never a batch: a red on a batch names no commit.
- **The gate fails closed.** Red (rc 1 to 5, no register row, a test that
  survives its own break) and amber (rc 124/126/127/137, uv sync failed) both
  ship nothing. Only rc 0 and rc 1 are cached; amber is never cached, never
  ejects, and three in a row alert. Scope `none` posts no `vm/gate`.
- **Statuses**: `vm/gate`, `vm/build`, `vm/boot`, `vm/deploy` (and
  `vm/branch-gate` on hand-backs). `failure` = ran and said no; `error` = could
  not form an opinion. Never collapse `error` into either other word. Never post
  a `pending` the same cycle cannot resolve.
- **The export, never the clone.** The gate tests `$BUILD_TREE` (a `git
  archive` of the commit), images build from `$VERIFIED_TREE`, compose starts
  from `$VERIFIED_TREE`. The webhook moves the clone at any moment.
- **A new step goes in the explicit source list** in `auto-deploy.sh`; a test
  checks the list against `steps/`. `doors.sh`, `eject_body.sh` and
  `build_verdict.sh` are not steps and must never be sourced as one.
- **The eject ships OFF** (`EJECT_ENABLED=0`). Off decides nothing: no claim, no
  revert, no issue; step 90 alerts that a red holds the queue. Armed, it takes
  back ONE commit (restore or lift, never a wider range) and hands it back on a
  branch `auto-eject/<sha12>` with a draft pull request.
- **Never press merge on a hand-back pull request.** Its first commit is the
  tree the gate refused, and the gate judges every commit against its own tree,
  so a merge puts a permanently red commit on main and freezes the bookmark.
  Fix it on the branch, then squash it onto main as ONE commit with
  `Closes #<the PR>` in the message; landing on main is what re-tests it.
- **A test and the change that makes it pass go in one commit.** A commit whose
  own tree fails its own test is red for ever.

## Don't

- `*.timer` must never `Requires=` its service: stop propagates and the timer
  dies silently. The activation link is `[Timer] Unit=`.
- Never `uv sync` into the clone's `.venv` from a step: the gate's environment
  is `$GATE_VENV_ROOT/<sha>`, a sibling of the export.
- Never hand-edit `/etc/systemd/system/harness-*`: step 80 rewrites units from
  the repository, and removes those it installed that the repository dropped.
- A compose fragment must not bind-mount a git-ignored file by a relative path:
  the stack runs from the verified tree, which only holds tracked files. Use
  `$HARNESS_ROOT/...` for runtime files.
