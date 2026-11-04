# infra/k8s/media/

The call and recording stack on the `media` pool role, and the job that keeps its public IP on the node. What the stack is and how to turn it on: `infra/media/CLAUDE.md`. `infra/cluster/apply.sh` skips this area while `MEDIA_PUBLIC_IP` is empty, so no media node bills while calls are off.

```
media/
  media-stack.yaml       Deployment media-stack (caddy, nats, janus, signaling, recording), claims
  janus-transports.yaml  Janus's WebSocket API on loopback, its HTTP API off
  ip-reattach.yaml       CronJob media-ip-reattach, its ServiceAccount and node-read role
  ip-reattach.sh         what the CronJob runs; test in tests/
```

## Rules

- **One replica, `Recreate`, `hostNetwork: true`.** Two pods cannot both bind the host's 80, 443 and UDP range, and both claims are ReadWriteOnce.
- **Only Caddy's 80/443 and Janus's UDP range listen off loopback.** The node sits on the cluster's private network, which no security group filters. NATS binds loopback by its args, Janus by `janus-transports.yaml`, signaling and the recorder by their templates. A new service on the node binds loopback the same way.
- **Keep `--ice-enforce-list` equal to `--nat-1-1`.** A node has several addresses, `--nat-1-1` labels every candidate with the public IP, and a packet to that IP reaches only the socket bound to it; without the list every candidate but one is dead. A new UDP service needs the same care.
- **`wait-for-media-ip` holds the pod until the IP is on a node interface.** A pod stuck in Init means the IP is not attached: read the last `media-ip-reattach` Job.
- **The CronJob runs on the system role, never the media node**, so it still runs when the media node is the one that came back without its IP. This area does not include `../system-pool`, so that role is written in `ip-reattach.yaml`.
- **The re-attach refuses to guess**: no Ready media node, two of them, a node outside `MEDIA_ZONE` (a flexible IP is zonal) or a providerID with no server all fail the Job and move nothing. When the IP is already on the node it writes nothing.
- **Both claims carry `harness/backup: "true"`**: Caddy's certificates (a lost one is a fresh issuance against the CA's rate limit) and recordings Talk has not fetched yet. The volume zone is the media role's home zone, so the pod only follows to fallbacks there.
- **A rotated `TALK_*` secret needs a pod restart, which drops calls in progress.** The configs are rendered once, by `render-config`, at pod start.
- `MEDIA_IP_SECRET_KEY` is an API key allowed to manage Instances in `SCW_PROJECT_ID`. Every pod in this namespace can read `harness-keys`, as everywhere the vault is included.
