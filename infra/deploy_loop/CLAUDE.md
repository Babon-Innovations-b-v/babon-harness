# infra/deploy_loop/

The deploy loop's cluster half: the questions the cycle asks Kubernetes, as pure functions, and the one CLI (`python3 -m infra.deploy_loop <verb>`) that asks them. Tier S, stdlib only, run with the cycle image's system python before any venv exists. Bash caller: `../auto-deploy/steps/cluster.sh`. Manifests: `../k8s/deploy/`. Image: `image/`. Bible: `infra/deploy`.

| File | Owns |
|---|---|
| `_receiver.py` | the push receiver: HMAC + `refs/heads/main`, then a Job from every idle CronJob in `DEPLOY_RECEIVER_CRONJOBS` |
| `_gate_job.py`, `gate_fetch.sh`, `gate_run.sh` | one gate Job: a full clone in its own emptyDir, the gated tree's pinned gate image, pytest then the break replay in one pod |
| `_outcome.py` | a Job and its pod read as the exit code `40-gate.sh` classifies |
| `_bookmark.py` | what ConfigMap `deploy-bookmark` may hold |
| `_pins.py` | which objects run another tag of an image just built |
| `_images.py` | the stack's own images and the compose service that builds each |
| `cycle_entry.sh` | the CronJob's command: clone if missing, run `auto-deploy.sh` |

## Do not

- Never map a Job fault to 0 to 5. Those are pytest's answers and 1 is the one the eject acts on; a deadline, an eviction, an OOM, an unpullable image or a failed fetch stay 124/125/137 (amber). `DeadlineExceeded` is asked before the container's exit code on purpose.
- Never give a gate Job a shared volume. Owning none is what lets Jobs run on any gate node in any zone, so the pools, not slots, bound how many run at once.
- Never fetch blobless or shallow, and never put the read token in env or in the run container. The run is `env -i` and must stay off the API and the network for git objects.
- Never read a missing `sha` key as "no bookmark": the cycle would gate the tip of main. Missing = refused; `""` = none yet.
- `gate_run.sh`'s `env -i` list must match `tools/gate_scope/audit_full_run.sh`'s; the gate_scope test compares them.
- `gate_fetch.sh` and `gate_run.sh` travel in each Job from the clone, every `$` doubled; `cycle_entry.sh` and `_receiver.py` ship only with a new `deploy-cycle` image tag.

Test: `tests/test_the_deploy_loop_asks_the_cluster_only_what_the_cycle_may_act_*.py`, this module's one test; a new rule is a new case in it.
