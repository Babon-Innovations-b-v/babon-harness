#!/bin/bash
# Step 80: apply the manifests. When the commit changed infra/k8s/,
# infra/cluster/ or infra/caddy/, run infra/cluster/apply.sh from the VERIFIED
# tree with the vault's settings, then put every stack image back on its last
# good digest (an apply resets each to the placeholder tag set-by-deploy-loop).
#
# apply.sh renders the cluster Caddyfile from infra/caddy/Caddyfile and refuses
# any ${KEY} it has no setting for, so a Caddy change ships here too.
#
# Only on a green gate, and only from the verified tree: a manifest is code
# the cluster runs, so an unverified one is never applied.
#
# FAILURE POLICY: a refused apply is recorded in FAILED_SERVICES as
# `manifests`, the bookmark holds, and step 90 says why. Whose fault it was is
# steps/build_verdict.sh's rule on the apply's log: a manifest the API server
# rejects is the commit's (it can be ejected), an unreachable API server is
# the box's.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

_apply_manifests() {
    local tree="${VERIFIED_TREE:-}" apply_log="$STATE_DIR/build-logs/manifests.log" fault
    [ "${gate_red:-0}" -eq 0 ] || return 0
    ${manifests_changed:-false} || return 0
    if [ -z "$tree" ] || [ ! -x "$tree/infra/cluster/apply.sh" ]; then
        log "[manifests] no verified tree with infra/cluster/apply.sh; nothing applied, the next cycle retries"
        ship_abandoned=1
        return 0
    fi
    tree_is_pinned "before the apply" || { ship_abandoned=1; return 0; }
    mkdir -p "$STATE_DIR/build-logs" 2>/dev/null
    if "$tree/infra/cluster/apply.sh" "$HARNESS_ENV_FILE" > "$apply_log" 2>&1; then
        log "[manifests] applied infra/k8s from ${NEW_SHA:0:12}"
        cluster_repin_images
        return 0
    fi
    fault=$(_build_fault_kind "$apply_log")
    FAILED_SERVICES+=(manifests)
    BUILD_FAILED_SERVICES+=(manifests)
    if [ "$fault" = "commit" ]; then
        BUILD_RED_SERVICES+=(manifests)
        log "[manifests] the apply was refused, and the fault is this commit's (log: $apply_log)"
    else
        log "[manifests] the apply could not reach the cluster; the fault is the box's (log: $apply_log)"
    fi
    cluster_repin_images
    return 0
}

_apply_manifests || log "[manifests] step aborted unexpectedly; the bookmark holds"
