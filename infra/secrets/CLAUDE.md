# infra/secrets/

The vault: one Scaleway Secret Manager secret (`VAULT_SECRET_NAME`, default `harness-env`) holding the full environment. `push-env.sh` (laptop, scw CLI) adds a version; `pull-env.sh` (server, every deploy cycle) writes it to `$HARNESS_ROOT/harness.env`, mode 600.

## Rules

- **No project, organization or secret ids in code.** The laptop side uses the scw CLI's own config; the server side reads `$HARNESS_ROOT/scw-secrets.env` (`SCW_SECRET_KEY`, `SCW_REGION`, optional `VAULT_SECRET_ID`), written once by onboarding and never committed.
- **`pull-env.sh` never fails the deploy.** On any error it keeps the existing cache and exits 0 with a warning. Keep that: a Secret Manager blip must not take the stack down.
- **Both scripts refuse content without a `DOMAIN=` line**, so a wrong file never becomes the environment.
- **Never print the content.** `data=@file` keeps it off the command line.
- The list of keys is `config/harness.env.example` plus `config/vault.env.example`; add a new key to one of those in the same commit that reads it.
