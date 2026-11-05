# infra/k8s/deploy/

The deploy loop in namespace `deploy`: CronJob `deploy-cycle` (`cycle.yaml`), the push receiver `deploy-webhook` (`receiver.yaml`), the image builder `buildkitd` (`buildkitd.yaml`), the cycle's volume `deploy-state` and ConfigMap `deploy-bookmark` (`state.yaml`), the Secrets `registry-push` and `deploy-git-read` (`secrets.yaml`), RBAC, the PriorityClass `deploy-loop`, the verifying lane CronJob `commit-gate` with its PVC `commit-gate-work`, ConfigMap `commit-gate-verdicts` and Role (`commit-gate.yaml`), and the image guard CronJob `deploy-cycle-image-guard` with ConfigMap `deploy-cycle-image` (`cycle-image-guard.yaml`). Gate Jobs are made by the cycle (`infra/deploy_loop/_gate_job.py`), never applied from here. `infra/cluster/apply.sh` skips this area while `DEPLOY_CYCLE_IMAGE` is empty.

- **`deploy-loop` has `preemptionPolicy: Never`.** Its pods are scheduled first and evicted last, but never evict anything to get a place. Do not switch it to preempt.
- **Never put `data:` in the bookmark ConfigMap.** The next apply would move the bookmark. Seeding it is in `infra/auto-deploy/CLAUDE.md`.
- **Nor in `commit-gate-verdicts` or `deploy-cycle-image`.** The lane writes the first, the cycle and the guard the second; data here would hand the cycle verdicts nobody ran, or put an old image back.
- **`commit-gate` and the guard hold a Role, never cluster-admin.** The lane's token is mounted at `/var/run/harness/kube` only, for `cluster_lane.sh`'s kubeconfig.
- **The guard moves every object here running the `deploy-cycle` repository.** `infra/cluster/apply.sh` renders its recorded `good` image instead of the settings', so an apply starts no trial of an older one.
- **`deploy-cycle` holds cluster-admin** because step 80 applies all of `infra/k8s`. Its token is in the cycle pod only; gate Jobs set `automountServiceAccountToken: false`. The receiver may only read CronJobs and Jobs here and create a Job.
- **Never start a cycle by hand while one runs** (`kubectl -n deploy get jobs`): the receiver checks, a hand does not.
- **buildkitd speaks plain TCP**: keep its NetworkPolicy. Its GC (`maxUsedSpace` 40GB) is fitted to its 50Gi claim; change both together, then `kubectl -n deploy rollout restart deploy/buildkitd`. Never delete a `<image>:buildcache` tag by hand.
- **buildkitd and the gate Jobs select the `gate` pool role; the cycle and the receiver the `system` role.** buildkitd carries `safe-to-evict: "false"`, so the autoscaler never takes the builder's node back.
- **Warm gate nodes are pods, not a pool size** (`gate-warm.yaml`): Deployment `gate-warm` holds one pause pod per gate node (anti-affinity, safe-to-evict false) whose init container pulls the pinned gate image; CronJobs `gate-warm-up`/`-down` scale it at the edges of `WORKING_HOURS`, and an apply sets the count for that minute. Change the hours in `config/harness.env`, never the CronJobs.
- Sizes and requests are starting points, not measured.

## First start (by hand, once)

1. Vault: `DEPLOY_WEBHOOK_SECRET`, `DEPLOY_STATUS_TOKEN`, `SCW_REGISTRY_PUSH_KEY`, and `DEPLOY_GIT_READ_TOKEN` for a private repository.
2. Build and pin the gate image (`infra/gate-image/build.sh`, commit the pin), build and push the cycle image (`infra/deploy_loop/image/CLAUDE.md`), set `DEPLOY_CYCLE_IMAGE`.
3. `infra/cluster/apply.sh`, then seed the bookmark.
4. Point the repository's push webhook at `https://deploy.<DOMAIN>/hooks/deploy` with the same secret.

Stop: `kubectl -n deploy patch cronjob deploy-cycle -p '{"spec":{"suspend":true}}'` and scale `deploy-webhook` to 0. Stop the lane alone: suspend CronJob `commit-gate`; the cycle then gates every commit itself.
