# infra/k8s/apps/

The namespace the stack's apps run in once they move into the cluster, with the vault Secret `harness-env`. Nothing runs here yet; the workloads arrive in a later piece.

- An app reads its settings and secrets from the mounted `harness-env` Secret, never from a key inline in its manifest.
- An app pod selects the `system` pool role unless it needs another (`infra/cluster/CLAUDE.md`).
