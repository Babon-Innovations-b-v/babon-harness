# infra/k8s/system-pool/

A kustomize Component, not an area: it puts every Deployment, StatefulSet and CronJob of an area that lists it under `components` on the `system` pool role (node label `POOL_ROLE_LABEL=system`) and tolerates that role's taint.

- **Include it instead of writing a `nodeSelector`** in a manifest; the role is then decided in one place.
- It matches the default taint (`POOL_ROLE_LABEL=system:NoSchedule`). A `POOL_SYSTEM_TAINT=key=value` needs this toleration changed with it.
- A workload that belongs on another role (the gate's runs, media, GPU) does not include it.
