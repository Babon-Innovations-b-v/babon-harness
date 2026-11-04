# infra/k8s/

The cluster foundation as kustomize: one directory per namespace or area, each with its own overlay. Bible: `infra/platform`, section "The cluster".

```
k8s/
  external-secrets/  the namespace and the ClusterSecretStore `vault`
  vault-secret/      a kustomize Component: ExternalSecret harness-env (the whole vault as one file)
  deploy/            the deploy loop's namespace and PriorityClass deploy-loop
  apps/              the apps' namespace
  monitoring/        the monitoring namespace
  media/             the media namespace
```

## Rules

- **Apply through `infra/cluster/apply.sh`, never `kubectl apply -k`.** The manifests name `${SCW_REGION}`, `${SCW_PROJECT_ID}` and `${VAULT_SECRET_NAME}`; the script fills them from `config/harness.env` and refuses any other `${...}`. A new placeholder is added to the script's list in the same commit.
- **No id, name, region or secret is written into a manifest.** It comes from the settings or the vault.
- **Pushing to `main` does not apply anything here yet.** A person or onboarding runs `infra/cluster/apply.sh`; the deploy loop takes it over in a later piece.
- **A namespace that reads the vault** includes `../vault-secret` and is named in the store's `conditions` in `external-secrets/cluster-secret-store.yaml`, in the same commit. Without the second it gets "not allowed" from the store.
- **A pod selects a pool role** with the node label `POOL_ROLE_LABEL=<role>` and tolerates the role's taint; never `k8s.scaleway.com/pool-name`, or it can never land on a fallback pool (`infra/cluster/CLAUDE.md`).
- No root `kustomization.yaml`: the script walks the directories, so a new area is a new directory.
- Check without a cluster: `infra/cluster/apply.sh --render <settings file>` prints every area rendered. `--dry-run` is a client dry run and needs a reachable cluster, because kubectl asks it which kinds exist.
