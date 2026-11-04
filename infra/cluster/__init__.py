"""The cluster foundation: the node pools, their stock fallbacks, and the scripts that create them.

Nothing is imported here on purpose: `create-cluster.sh` and `apply.sh` are
shell, and `pool_fallbacks` is its own package with its own seam.
"""
