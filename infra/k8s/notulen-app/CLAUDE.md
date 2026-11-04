# infra/k8s/notulen-app/

The notulen dashboard (Service `notulen:8000`, claim `notulen-sessions`, subPath `notulen_sessions`). App rules: `apps/notulen/CLAUDE.md`.

- **Not namespace `notulen`**: the GPU tier's Jobs and RBAC own `GPU_NAMESPACE` (default `notulen`, `infra/gpu`).
- **`DB_URL` is built in the pod** from the three `POSTGRES_*` keys, as compose built it; a password with URL characters breaks it in both.
- One replica, `Recreate`: live sessions are appended to one ReadWriteOnce claim.
