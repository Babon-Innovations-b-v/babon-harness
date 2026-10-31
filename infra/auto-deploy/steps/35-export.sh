#!/bin/bash
# Step 35: export NEW_SHA with `git archive` into $BUILD_TREE, once. That tree
# is what the gate verifies and what every image is built from; never the
# clone, which the webhook can move at any moment.
#
# The export is made a git repository of its own (init, alternates pointing at
# the clone's objects, HEAD at NEW_SHA), because tests shell out to git against
# the repository root, and a tree answering `git rev-parse HEAD` with another
# commit is a confident wrong answer.
#
# FAILURE POLICY: no export means nothing is verified and nothing ships: step 40
# turns an empty BUILD_TREE into a red `no_export`. It NEVER falls back to the
# clone. It refuses below AUTO_DEPLOY_BUILD_MIN_FREE_MB.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

_publish_export_as_repo() {
    local target="$1" objects
    objects="$( cd "$REPO" && cd "$(git rev-parse --git-common-dir 2>/dev/null)" && pwd )/objects"
    [ -d "$objects" ] || return 1
    git -C "$target" init -q \
        && printf '%s\n' "$objects" > "$target/.git/objects/info/alternates" \
        && git -C "$target" update-ref HEAD "$NEW_SHA" \
        && git -C "$target" read-tree HEAD
}

export_verified_tree() {
    local target="$BUILD_TREE_ROOT/$NEW_SHA" free_mb rcs
    mkdir -p "$BUILD_TREE_ROOT" 2>/dev/null
    # Swept on entry: a killed cycle cannot sweep on its way out.
    rm -rf "${BUILD_TREE_ROOT:?}"/* 2>/dev/null
    free_mb=$(df --output=avail -m "$BUILD_TREE_ROOT" 2>/dev/null | tail -1 | tr -d ' ')
    case "$free_mb" in ''|*[!0-9]*) free_mb=0 ;; esac
    if [ "$free_mb" -lt "$BUILD_TREE_MIN_FREE_MB" ]; then
        log "[tree] only ${free_mb} MB free at $BUILD_TREE_ROOT (floor ${BUILD_TREE_MIN_FREE_MB} MB); no export, nothing ships"
        fire_alert_once "build-tree-disk" "$NEW_SHA" \
            "auto-deploy: no room to export the tree to verify" \
            "$BUILD_TREE_ROOT has ${free_mb} MB free, below the ${BUILD_TREE_MIN_FREE_MB} MB floor, so nothing was verified or built for ${NEW_SHA:0:12}. The bookmark stays put and the next cycle retries. Free disk on the server." \
            --wakes-somebody
        return 1
    fi
    mkdir -p "$target" 2>/dev/null || return 1
    ( git -C "$REPO" archive --format=tar "$NEW_SHA" ) 2>>"$LOG" | tar -x -C "$target" 2>>"$LOG"
    rcs=("${PIPESTATUS[@]}")
    if [ "${rcs[0]}" -ne 0 ] || [ "${rcs[1]}" -ne 0 ]; then
        log "[tree] export of ${NEW_SHA:0:8} failed (git archive rc=${rcs[0]}, tar rc=${rcs[1]})"
        rm -rf "$target" 2>/dev/null
        return 1
    fi
    if ! _publish_export_as_repo "$target"; then
        log "[tree] could not make $target a git repository; nothing is verified this cycle"
        rm -rf "$target" 2>/dev/null
        return 1
    fi
    BUILD_TREE="$target"
    log "[tree] exported ${NEW_SHA:0:8} to $target"
    return 0
}

if [ "${env_only:-false}" = true ]; then
    log "[tree] only the vault changed; no export"
else
    export_verified_tree || true
fi
