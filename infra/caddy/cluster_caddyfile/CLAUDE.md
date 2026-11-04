# infra/caddy/cluster_caddyfile/

Tier S, stdlib only: renders `infra/caddy/Caddyfile` into the cluster's (`infra/k8s/ingress/Caddyfile`, git-ignored), rewriting each `reverse_proxy` and `forward_auth` upstream to a cluster Service and adding the PROXY protocol `servers` block to the global options. `infra/cluster/apply.sh` runs it before every apply, so the cluster copy is never stale.

```
python3 -m infra.caddy.cluster_caddyfile [--out PATH]   # exit 2: an upstream has no row
```

- **A new upstream in the Caddyfile needs its row in `_upstreams.py`** in the same commit. Never make the render skip one.
- Test: `tests/`, one function over parametrized synthetic cases; row in `tools/test_register/_rows.py`.
