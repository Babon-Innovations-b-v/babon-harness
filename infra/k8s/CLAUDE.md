# infra/k8s/

The cluster as kustomize: one directory per namespace, each with its own overlay, plus two Components the namespaces include. Bible: `infra/platform`, section "The cluster".

```
k8s/
  external-secrets/   the ClusterSecretStore `vault`
  vault-secret/       Component: harness-env, harness-keys, registry-pull
  system-pool/        Component: every workload on the system pool role
  ingress/            Caddy behind the load balancer, oauth2-proxy
  postgres/           the one database server
  nextcloud/          Nextcloud and its cron
  assistant/          the door, signal-cli, the speech model
  assistant-gateway/  the OpenClaw gateway, alone
  notulen-app/        the notulen dashboard
  website/            the public website
  backups/            nightly snapshots of every labelled claim
  media/              video calls on the media pool role, its IP re-attach
  deploy/ monitoring/ namespaces later pieces fill
```

## Rules

- **Apply through `infra/cluster/apply.sh`, never `kubectl apply -k`.** It renders the cluster Caddyfile, fills every `${KEY}` in its `PLACEHOLDERS` from `config/harness.env` and refuses any other. A new placeholder joins that list in the same commit.
- **No id, name, region or secret in a manifest.** Settings or the vault.
- **One workload per namespace.** An exec or RBAC grant cannot be pinned to one pod, so whatever gets one reaches everything beside it. A namespace that reads the vault includes `../vault-secret` and is named in the store's `conditions` (`external-secrets/cluster-secret-store.yaml`) in the same commit.
- **A pod selects a pool role through `../system-pool`**, never `k8s.scaleway.com/pool-name` (`infra/cluster/CLAUDE.md`).
- **The stack's own images carry the tag `set-by-deploy-loop`.** The deploy loop sets each by digest with `kubectl set image`; a re-apply puts the placeholder back, so re-apply only through the loop once it runs.
- **One writer per ReadWriteOnce claim**: one replica, `Recreate`, and a second process on the same data is a second container in the pod, never a second Deployment.
- **A claim that holds state carries `harness/backup: "true"`**; a cache leaves it off. Every mount uses a `subPath` named after its compose volume.
- **Sizes and resource requests are starting points, not measured.** Raise a claim with `kubectl edit pvc`; it cannot shrink.
- Check without a cluster: `infra/cluster/apply.sh --render <settings file>`.

## Moving a compose volume into its claim (once per volume, by hand)

Nothing has run this. Per volume, with the compose service `<svc>`, volume `harness_<vol>`, claim `<pvc>` in namespace `<ns>`, Deployment `<deploy>`:

1. `kubectl -n <ns> scale deploy/<deploy> --replicas=0`, and `docker compose stop <svc>` on the server.
2. Start a helper on the claim: `kubectl -n <ns> run copy --image=alpine:3 --restart=Never --overrides='{"spec":{"containers":[{"name":"copy","image":"alpine:3","command":["sleep","3600"],"volumeMounts":[{"name":"d","mountPath":"/d"}]}],"volumes":[{"name":"d","persistentVolumeClaim":{"claimName":"<pvc>"}}]}}'`.
3. Copy it whole: `docker run --rm -v harness_<vol>:/v alpine:3 tar -C /v -cf - . | kubectl -n <ns> exec -i copy -- sh -c 'mkdir -p /d/<vol> && tar -C /d/<vol> -xpf -'`.
4. Verify both sides print the same two lines: `find . -type f | wc -l` and `find . -type f -exec sha256sum {} + | sort -k2 | sha256sum`, run in `/v` and in `/d/<vol>`. Different: stop here.
5. `kubectl -n <ns> delete pod copy`, scale back to 1, and keep the compose volume until the pod serves.
