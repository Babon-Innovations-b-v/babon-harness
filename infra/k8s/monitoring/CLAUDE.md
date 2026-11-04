# infra/k8s/monitoring/

The namespace Prometheus, Alertmanager and the alert relay move into in a later piece, with the vault Secret `harness-env`. Today they run from `infra/observability/` on the server; its overlay has the rules.

- Paging secrets come from the mounted `harness-env` Secret, never inline.
