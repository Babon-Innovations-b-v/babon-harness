# infra/k8s/vault-secret/

A kustomize Component, not an area. Three ExternalSecrets, each landing in the namespace that includes it:

| Secret | What it holds |
|---|---|
| `harness-env` | the whole vault as one file, key `harness.env`, the same `KEY=value` text `infra/secrets/pull-env.sh` writes on a server |
| `harness-keys` | one key per non-empty vault setting, compose's `${KEY:-default}` defaults filled in |
| `registry-pull` | the pull secret for the stack's own images, from `SCW_REGISTRY_PULL_KEY` |

- **Include it, do not apply it.** A namespace's `kustomization.yaml` lists `../vault-secret` under `components`; its `namespace:` decides where the Secrets land. `infra/cluster/apply.sh` skips a directory whose kustomization is `kind: Component`.
- **A container names each key it reads** with `secretKeyRef` on `harness-keys`, `optional: true`, mirroring its compose service's `environment:`. Never `envFrom` the whole Secret, and never a value copied inline into a manifest.
- **A compose default lives in the `dict` in `keys-externalsecret.yaml`**, nowhere else. A new `${KEY:-default}` in a compose file that moves to the cluster adds its line there.
- **An empty vault value is left out**, so the key is unset in the pod and the app's own default applies, not an empty string.
- They refresh every 5 minutes (`registry-pull` hourly); a pod reads its environment only at start, so a changed value needs a restart.
