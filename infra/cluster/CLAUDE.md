# infra/cluster/

Creates or adopts the managed Kubernetes cluster and its node pools from `config/harness.env`, and applies `infra/k8s/` on it. Bible: `infra/platform`, section "The cluster".

```
cluster/
  create-cluster.sh   read-only plan by default; --apply creates or adopts, writes CLUSTER_ID back
  apply.sh            renders infra/k8s/ from the settings and applies it (--dry-run: client only)
  pool_fallbacks/     the pools of every role and the autoscaler's priority order (Python, stdlib)
```

```
infra/cluster/create-cluster.sh                                   # plan, changes nothing
infra/cluster/create-cluster.sh --apply --vault-env <vault copy>  # do it
```

## Rules

- **Plan first.** Without `--apply` the script only reads; run it and read the plan before `--apply`. A pool costs from the moment it has a node, and the root disk size is fixed at creation.
- **Pods select a pool role, never a pool name.** Every pool of a role carries the label `POOL_ROLE_LABEL=<role>` and the role's taint; the provider sets the pool-name label itself, so only the shared role label lets a pod land on a fallback.
- **The expander's ConfigMap matches pool ids**, and a pool's id is new on every create, so the script rebuilds `kube-system/cluster-autoscaler-priority-expander` after any create. Never hand-edit it. `.*` at priority 1 keeps a pool no role names usable: the expander never uses a node group no regex matches.
- **An existing pool is never resized, retyped or retainted here.** The provider cannot change a pool's root disk; an empty fallback on the wrong disk is recreated, one with nodes is left and logged. Changing a preferred pool's shape is a new pool under a new name, set first in `POOL_<ROLE>_TYPES`, then the old one drained by a person.
- **A pod bound to a zonal volume can only follow to fallbacks in its home zone.** The other zones help stateless pods.
- **Every pool's max together counts against the provider's node limit** for the cluster; a create past it is refused.
- `CLUSTER_ID` and `SCW_PROJECT_ID` are written back into the settings file by `--apply`; copy them into the vault in the next vault version.
- The cluster create, the Helm install and the secret copy have not been run end to end from this repository; the plan has been run against an existing cluster.
