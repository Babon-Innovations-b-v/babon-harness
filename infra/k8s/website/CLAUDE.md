# infra/k8s/website/

The public website (Service `website:80`), two stateless replicas. Content rules: `apps/website/`.

- It reads no vault key; the vault component is here for `registry-pull` only.
