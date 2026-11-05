# infra/deploy_loop/image/

The `deploy-cycle` image: the deploy cycle's and the lane's CronJobs, the image guard, every gate Job's fetch container and the push receiver. The first one is built by hand from the repository root: `docker build -f infra/deploy_loop/image/Dockerfile -t <registry>/deploy-cycle:v1 .`, push, set `DEPLOY_CYCLE_IMAGE` in `config/harness.env`, apply. After that the cycle rebuilds it itself (step 50, `cluster_ship_cycle_image`): whenever a shipped tree's `infra/deploy_loop` differs from the image in use, it builds `deploy-cycle:git-<sha12>`, runs `smoke.sh` in it, and tries it on CronJob `deploy-cycle` alone until CronJob `deploy-cycle-image-guard` promotes it or rolls it back.

- **Never reuse a tag, never `:latest`.** A node that kept an old copy of a reused tag runs old scripts. The cycle pins by digest.
- **Of ours, only `infra/deploy_loop`.** The cycle runs every step from its clone at the commit it deploys; a step baked in here would go stale. `Dockerfile.dockerignore` is deny by default: a new `COPY` needs its `!` line, and a new path baked in needs adding to `BAKED` in `../_cycle_image.py`, or a change to it never rebuilds the image.
- **`smoke.sh` is the only thing between a build and a trial.** A tool the steps start calling goes on its list.
- **No secret at build time.** Everything arrives from the vault Secrets at runtime.
