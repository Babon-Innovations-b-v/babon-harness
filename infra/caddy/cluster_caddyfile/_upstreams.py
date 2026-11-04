"""Every upstream the compose Caddyfile dials, and the cluster Service it becomes.

OWNS: the one table from a compose upstream (`<service>:<port>` on the compose
network) to `<service>.<namespace>.svc.cluster.local:<port>`.

DOES NOT OWN: rewriting the file (`_render.py`) or the Services themselves,
which live in `infra/k8s/<namespace>/`. `deploy-webhook` in namespace `deploy`
is the deploy loop's push receiver; the deploy loop's own piece creates it.

One entry is not one to one: `host.docker.internal:{$WEBHOOK_PORT:9000}` was
the webhook listener on the compose host; in the cluster it is the receiver's
Service.
"""
from __future__ import annotations

CLUSTER_UPSTREAMS: dict[str, str] = {
    "website:80": "website.website.svc.cluster.local:80",
    "nextcloud:80": "nextcloud.nextcloud.svc.cluster.local:80",
    "oauth2-proxy:4180": "oauth2-proxy.ingress.svc.cluster.local:4180",
    "notulen:8000": "notulen.notulen-app.svc.cluster.local:8000",
    "host.docker.internal:{$WEBHOOK_PORT:9000}": "deploy-webhook.deploy.svc.cluster.local:9000",
}
