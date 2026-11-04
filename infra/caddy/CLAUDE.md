# infra/caddy/

The HTTPS front door. `Caddyfile` routes every host; `compose.yml` runs Caddy and is included from the root `docker-compose.yml`.

## Rules

- **A private subdomain needs three things**: `import oauth2_auth` inside its catch-all `handle`, a separate `handle @oauth2_path` (`/oauth2/*` straight to `oauth2-proxy:4180`) ahead of it, and its name in `SSO_SUBDOMAINS` followed by `infra/nextcloud/oidc-setup.sh`. Miss the last one and login fails with "redirect URI not accepted".
- **`(oauth2_auth)` strips client-sent `Remote-User` and `Remote-Email`** before asking oauth2-proxy. Keep that: dashkit trusts those headers.
- **Paths that skip the login** (`/healthz`, `/api/talk/webhook`, `deploy.` `/hooks/*`) must be authenticated by the app itself (HMAC) or return nothing private.
- **`/api/internal/*` answers 404 at the edge.** Do not proxy it.
- **Nextcloud cookie rewrites stay `header_down` inside `reverse_proxy`.** A site-level `header` block runs before the upstream `Set-Cookie` exists and silently does nothing.
- **Paths in `compose.yml` are relative to this directory** (compose `include` semantics), so the config mount is `./`.
- Validate before pushing: `docker run --rm -e DOMAIN=example.org -e ACME_EMAIL=a@example.org -v "$PWD/infra/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.11.7 caddy validate --config /etc/caddy/Caddyfile`.
- **The cluster renders its own copy** (`cluster_caddyfile/`, written by `infra/cluster/apply.sh` into `infra/k8s/ingress/`): every upstream above needs its row in `cluster_caddyfile/_upstreams.py`, or the render refuses.
