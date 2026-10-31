# infra/gpu

The optional GPU tier for notulen: the worker image, the cluster objects it needs, and the scripts that build and wire them. Without it (`GPU_ENABLED=0`, the default) notulen transcribes on the server's CPU. Bible: `infra/gpu`.

```
gpu/
  Dockerfile                     the worker image (public pytorch base; worker.py + template)
  build-worker.sh                build and push from a temporary Scaleway instance; --patch for a worker.py-only change
  pick-gpu.sh                    first GPU node type with stock, cheapest first, across zones
  apply.sh                       namespace, RBAC, PriorityClass, worker Secret, ConfigMap, registry pull Secret
  make-dashboard-kubeconfig.sh   the dashboard's kubeconfig (KUBECONFIG_B64)
  k8s/                           namespace.yaml, rbac.yaml, priorityclass.yaml (${GPU_NAMESPACE} filled by the scripts)
```

## Turning it on, in order

1. Create a Kapsule cluster with one GPU pool named `$GPU_POOL` (`pick-gpu.sh` for zone and type), autoscale 0 to 1 or 2, taint `workload=notulen:NoSchedule`. A second pool in another zone goes in `GPU_POOL` as a comma list.
2. `infra/gpu/build-worker.sh v1`; put the printed reference in `NOTULEN_WORKER_IMAGE`.
3. Set `POSTGRES_BIND_ADDRESS=0.0.0.0` and `DB_URL_OPS` (the worker writes its row from the cluster), then `infra/gpu/apply.sh`.
4. `infra/gpu/make-dashboard-kubeconfig.sh | base64 -w0` into `KUBECONFIG_B64` in the vault, `GPU_ENABLED=1`, redeploy.

## Rules

- **No credential in any manifest here.** `apply.sh` builds the Secrets from the vault copy at deploy time; nothing secret is committed.
- **The dashboard's service account may only manage Jobs and Pods in `$GPU_NAMESPACE`.** Do not widen `rbac.yaml` to cluster scope.
- **`HF_TOKEN` is a build secret and an optional runtime key.** Without it the image and the worker run without speaker labels.
- **Opening Postgres to the internet is the price of this tier**: the password is the only guard on 5432 once `POSTGRES_BIND_ADDRESS=0.0.0.0`. Use a long one.
- **A wedged GPU node bills all night.** The autoscaler removes an idle node after about 10 minutes; check `kubectl get nodes` when a bill looks wrong.
- The NVIDIA driver version is set on the cluster by the provider's GPU operator, not here. A node that comes up without `nvidia.com/gpu` means a driver that does not build against the node kernel; check the `nvidia-driver-daemonset` logs.
