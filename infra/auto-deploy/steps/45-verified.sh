#!/bin/bash
# Step 45: promote the export the gate just passed to $VERIFIED_ROOT/<sha>, a
# tree that OUTLIVES the cycle (step 90 removes $BUILD_TREE).
#
# For anything that bind-mounts code rather than baking it into an image: such
# a service should mount $VERIFIED_ROOT/<sha>, never the clone, which moves at
# every push, and never $BUILD_TREE, which is gone when the cycle ends. Never on
# a red gate. The promotion is a hardlink farm (`cp -al`), so it costs no disk
# and must stay on the build tree's filesystem.
#
# The sweep keeps the newest VERIFIED_KEEP trees plus anything a container
# still mounts; a docker that does not answer sweeps nothing.
#
# FAILURE POLICY: best-effort and quiet, never blocks a deploy.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

_sweep_verified_trees() {
    local in_use container_ids trees=() tree index=0
    [ -d "$VERIFIED_ROOT" ] || return 0
    container_ids=$(docker ps -a -q 2>/dev/null) || { log "[verified] docker did not answer; sweeping nothing"; return 0; }
    in_use=$(printf '%s\n' "$container_ids" \
        | xargs -r docker inspect --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' 2>/dev/null | sort -u)
    while IFS= read -r tree; do
        [ -d "$tree" ] && trees+=("$tree")
    done < <(ls -1dt "$VERIFIED_ROOT"/* 2>/dev/null)
    for tree in ${trees[@]+"${trees[@]}"}; do
        index=$((index + 1))
        [ "$index" -le "$VERIFIED_KEEP" ] && continue
        if printf '%s\n' "$in_use" | awk -v prefix="$tree" 'index($0, prefix "/") == 1 || $0 == prefix { hit = 1 } END { exit !hit }'; then
            continue
        fi
        rm -rf "$tree" 2>/dev/null && log "[verified] swept ${tree##*/}; nothing mounts it"
    done
    return 0
}

_promote_verified_tree() {
    local target="$VERIFIED_ROOT/$NEW_SHA"
    mkdir -p "$VERIFIED_ROOT" 2>/dev/null || return 1
    if [ -d "$target" ]; then
        VERIFIED_TREE="$target"
        return 0
    fi
    rm -rf "${target:?}.partial" 2>/dev/null
    if cp -al "$BUILD_TREE" "$target.partial" 2>>"$LOG" && mv -T "$target.partial" "$target" 2>>"$LOG"; then
        VERIFIED_TREE="$target"
        log "[verified] ${NEW_SHA:0:8} promoted to $target"
        return 0
    fi
    rm -rf "${target:?}.partial" 2>/dev/null
    log "[verified] could not promote $BUILD_TREE; anything mounting a verified tree keeps its old one"
    return 1
}

if [ "${gate_red:-0}" -eq 0 ] && [ -n "${BUILD_TREE:-}" ] && [ -d "${BUILD_TREE:-}" ]; then
    _promote_verified_tree || true
fi
_sweep_verified_trees || true
