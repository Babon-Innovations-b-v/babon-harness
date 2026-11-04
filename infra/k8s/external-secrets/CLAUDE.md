# infra/k8s/external-secrets/

The ClusterSecretStore `vault`: the External Secrets operator reads the vault (one Scaleway Secret Manager secret) through it, for every namespace allowed in its `conditions`.

- **The operator itself is a Helm chart**, installed by `infra/cluster/create-cluster.sh` at the version pinned there (`ESO_CHART_VERSION`). Its CRDs must exist before this directory applies.
- **The store's key is Secret `vault-reader`** (keys `access-key`, `secret-key`) in this namespace, copied by `create-cluster.sh --vault-env` from `ESO_ACCESS_KEY` and `ESO_SECRET_KEY` in the vault. It is never in a file here. Its IAM application may only read secrets in `SCW_PROJECT_ID`; widening it hands every allowed namespace the whole project.
- **A `name:` ref resolves inside `SCW_PROJECT_ID` only.** A secret in another project needs an `id:` ref. Do not repoint `projectId` to fix one ref: every ExternalSecret in the cluster resolves against it.
- Rotation is by hand: a new key in the vault, rerun `create-cluster.sh --apply --vault-env <file>`, then delete the old key.
