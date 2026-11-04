# infra/k8s/vault-secret/

A kustomize Component, not an area: the ExternalSecret `harness-env`, which writes the whole vault into Secret `harness-env`, key `harness.env`, as the same `KEY=value` text `infra/secrets/pull-env.sh` writes on a server.

- **Include it, do not apply it.** A namespace's `kustomization.yaml` lists `../vault-secret` under `components`; its `namespace:` decides where the Secret lands. `infra/cluster/apply.sh` skips a directory whose kustomization is `kind: Component`.
- **A pod reads it as a mounted file**, never as a key copied inline into a manifest.
- It refreshes every 5 minutes; a pushed vault version reaches a mounted file within that, and a pod that reads its environment only at start needs a restart.
