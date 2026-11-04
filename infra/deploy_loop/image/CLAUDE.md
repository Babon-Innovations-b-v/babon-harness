# infra/deploy_loop/image/

The `deploy-cycle` image: the deploy cycle's CronJob, every gate Job's fetch container and the push receiver. Build from the repository root: `docker build -f infra/deploy_loop/image/Dockerfile -t <registry>/deploy-cycle:vN .`, push, set `DEPLOY_CYCLE_IMAGE` in `config/harness.env`, re-apply.

- **Tag `:vN`, never reused, never `:latest`.** A node that kept an old copy of a reused tag runs old scripts.
- **Of ours, only `infra/deploy_loop`.** The cycle runs every step from its clone at the commit it deploys; a step baked in here would go stale. `Dockerfile.dockerignore` is deny by default: a new `COPY` needs its `!` line.
- **No secret at build time.** Everything arrives from the vault Secrets at runtime.
- Rebuild when `cycle_entry.sh`, `_receiver.py` or a tool version here changes; `gate_fetch.sh` and `gate_run.sh` travel inside each Job from the clone and need no rebuild.
