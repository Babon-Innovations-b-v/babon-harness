# infra/cluster/pool_fallbacks/

Which empty pools stand in for each pool role when the provider is out of a machine type, and the cluster autoscaler's priority order over them. Tier S, stdlib only, reads nothing live. The only caller is `infra/cluster/create-cluster.sh`, which does the provider and `kubectl` work.

```
python3 -m infra.cluster.pool_fallbacks --pools
<live pool list JSON> | python3 -m infra.cluster.pool_fallbacks --priorities
<live pool list JSON> | python3 -m infra.cluster.pool_fallbacks --fallback-actions
```

- Settings come from the environment (`set -a; . config/harness.env`); the functions take them as a mapping, so a test passes made-up settings.
- Order within a role: the preferred type in the home zone, the other types there, then the preferred type in the other zones, then the rest. A role with one zone in `POOL_<ROLE>_ZONES` never leaves it.
- Names: the preferred pool is the role name; a fallback is `<role>-<type>-<zone>`, lowercased type. Renaming a fallback makes the script create a new one and leave the old one.
- Weights: ten per rank below the deepest role's depth, so rank 0 is highest in every role; `.*` at 1 below all.
- Test: `tests/`, one function over parametrized synthetic cases; row in `tools/test_register/_rows.py`.
