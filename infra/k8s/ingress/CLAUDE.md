# infra/k8s/ingress/

Caddy behind the cloud load balancer (Service `caddy`, type LoadBalancer) and oauth2-proxy (Service `oauth2-proxy:4180`). Routing rules live in `infra/caddy/` and its overlay; this directory only runs them.

- **`Caddyfile` here is generated and git-ignored.** Edit `infra/caddy/Caddyfile`; `infra/cluster/apply.sh` renders it (`python3 -m infra.caddy.cluster_caddyfile`). A new upstream needs its row in `infra/caddy/cluster_caddyfile/_upstreams.py`, or the render exits 2.
- **The load balancer's annotations are the provider's**, every value from `INGRESS_LB_*` in the settings. Do not drop `proxy-protocol-v2` or the Caddyfile's `servers` block alone: without both, Nextcloud throttles every user as one address.
- **Reserve the IP before the first apply** (`INGRESS_LB_IP_ID`); apply.sh skips this area until then.
- **Do not scale Caddy past one or run it here and on a compose box with DNS on both**: the certificates on `caddy-data` diverge, and copy them in (migration recipe in `../CLAUDE.md`, volumes `caddy_data` and `caddy_config`) before DNS moves, or every ACME challenge fails at once.
- The push webhook (`deploy.` `/hooks/*`) dials `deploy-webhook.deploy:9000`, the deploy loop's receiver; its piece creates that Service.
