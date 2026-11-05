Budget: the deploy gate everything ships through. The status vocabulary, the gate's three verdicts and the eject's hand-back rule exist nowhere else and bind every file below.

# infra/auto-deploy/

The deploy loop's steps. `auto-deploy.sh` sources `steps/NN-*.sh` in one shell,
in the cycle pod of CronJob `deploy-cycle` (`infra/k8s/deploy/`), every two
minutes and on every push (the receiver, `infra/deploy_loop/`). Every call to
the cluster is in `steps/cluster.sh`. `commit_gate/` is the verifying lane,
CronJob `commit-gate` (`cluster_lane.sh`, its own clone on PVC
`commit-gate-work`); its verdicts reach the cycle only through ConfigMap
`commit-gate-verdicts` (step 18). `branch_gate/` (hand-backs) is not in the
cluster yet. Bible: `infra/deploy`.

## Rules

- **One commit per cycle.** Step 20 takes the trusted head
  (`deploy_loop trusted-head`: every commit up to it judged by the lane on its
  own tree) and step 40 runs no pytest for it; otherwise the newest commit with
  a green verdict for its exact tree, otherwise the next one. Never HEAD of an
  unjudged range: a red on it names no commit.
- **The lane's words.** Only a green with reason `replayed` (its break replay
  passed) counts for the trusted head. A `batch:<sha12>` green was verified on
  a later commit's tree: never the head, never a step-40 cache hit. A red batch
  writes nothing; `batch.sh` halves it. Keep `EJECT_RUN_ENABLED=1` in the
  CronJob: the cycle jumps past a red only the lane saw.
- **The gate fails closed.** Red (rc 1 to 5, no register row, a test that
  survives its own break) and amber (rc 124 timeout, 125 a gate Job that could
  not start or was evicted, 126/127, 137) both ship nothing. Only rc 0 and rc 1
  are cached; amber is never cached, never ejects, and three in a row alert.
  Scope `none` posts no `vm/gate`.
- **A gate Job runs in the image the GATED tree's `infra/gate-image/pin`
  names**, by digest. A pin with no digest is 125 for every commit: build and
  pin the gate image before the loop goes live.
- **Statuses**: `vm/gate`, `vm/build`, `vm/boot`, `vm/deploy` (and
  `vm/branch-gate` on hand-backs). The names stayed when the loop moved off the
  server: the watchdog and the branch gate read them, and only the owner
  renames them. `failure` = ran and said no; `error` = could not form an
  opinion. Never collapse `error` into either other word.
- **The export, never the clone.** Images build from `$VERIFIED_TREE` and step
  80 applies from it; the gate Job fetches the commit itself.
- **The lane never touches the cycle's volume, nor the cycle the lane's.**
  `lane_drawers.py unpack` never replaces a file the cycle holds; the lane's
  `run_one.sh` reads only `40-gate.sh` out of its clone (a test checks it).
- **The bookmark is ConfigMap `deploy-bookmark`**, read into
  `$STATE_DIR/last-deployed-sha` by step 10 and written back by
  `cluster_bookmark_push` wherever that file moves. A ConfigMap without a `sha`
  key stops every cycle: seed it once with
  `kubectl -n deploy patch configmap deploy-bookmark --type merge -p '{"data":{"sha":"<last live sha>"}}'`
  (or `""` on a fresh install, which gates from the first commit).
- **A new step goes in the explicit source list** in `auto-deploy.sh`; a test
  checks the list against `steps/`. `doors.sh`, `cluster.sh`, `eject_body.sh`,
  `build_verdict.sh` and `red_triage.sh` are not steps and must never be
  sourced as one.
- **A red is sorted before it is believed** (`steps/red_triage.sh`, the rule in
  `tools/red_triage`). Its failing files run again in a fresh gate Job and on
  the bookmark's tree: a flip or an old failure is quarantined on main as
  `GATE_AUTHOR_EMAIL` (empty: left out of this run only) and the suite runs
  again without it; the commit's red goes to the eject. A red naming no file
  runs once more. Never let a triage answer turn a red green by itself.
- **The shipped config arms the eject** (`EJECT_ENABLED=1`). Unset or `0`
  decides nothing: no claim, no revert, no issue; step 90 alerts that a red
  holds the queue. Armed, it takes back ONE commit and hands it back on
  `auto-eject/<sha12>` with a draft pull request.
- **Never press merge on a hand-back pull request.** Its first commit is the
  tree the gate refused. Fix it on the branch, then squash it onto main as ONE
  commit with `Closes #<the PR>` in the message.
- **A test and the change that makes it pass go in one commit.**

## Don't

- Never `kubectl apply -k` by hand while the loop runs: the stack images go
  back to the placeholder tag `set-by-deploy-loop` until the next cycle that
  changes a manifest re-pins them. Apply through a commit.
- Never map a gate Job's fault to 0 to 5 (`infra/deploy_loop/_outcome.py`).
- `compose_fragments.py` decides which stack images a commit changes: a stack
  image is a compose service with a `build:` block whose name a manifest uses
  with the placeholder tag, and it changes only when a path its Dockerfile
  copies (after its ignore file), the Dockerfile, the ignore file or its
  fragment changed. A new `COPY` from outside the fragment needs nothing else.
- Step 68 (the assistant's workspace) still renders on the cycle's own volume;
  the gateway in the cluster does not read it yet.
