#!/bin/bash
# Build the images ONE commit changes, from that commit's own tree, and push
# nothing.
#
#   commit_gate/build_images.sh <sha> <tree>
#
# Exit 0 built (or nothing to build), 1 a build the COMMIT broke, 2 a build this
# BOX broke (steps/build_verdict.sh decides which), 3 could not tell what to
# build. run_one.sh runs it after a green suite: a commit whose image will not
# build is then red before it reaches the queue, on the road a failing test
# takes.
#
# Which services: infra/auto-deploy/compose_fragments.py, read out of the tree
# being built, so the rule is the commit's own. Built under a throwaway compose
# project (harness-gate-<sha12>) so nothing the live stack runs is retagged, and
# the images are removed afterwards; the layers stay in docker's cache, so the
# cycle's own build of the same tree is a cache hit.

set -u
SELF="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="${STATE_DIR:-/var/lib/harness}"
HARNESS_ROOT="${HARNESS_ROOT:-/opt/harness}"
HARNESS_ENV_FILE="${HARNESS_ENV_FILE:-$HARNESS_ROOT/harness.env}"
COMMIT_GATE_BUILD_MIN_FREE_MB="${COMMIT_GATE_BUILD_MIN_FREE_MB:-8192}"
SHA="${1:-}"
TREE="${2:-}"
log() { printf '[%s] [commit-gate build %s] %s\n' "$(date -Iseconds)" "${SHA:0:12}" "$*" >&2; }

if [ -z "$SHA" ] || [ -z "$TREE" ] || [ ! -d "$TREE" ]; then
    log "usage: build_images.sh <sha> <tree>"
    exit 3
fi
[ -f "$TREE/docker-compose.yml" ] || { log "no docker-compose.yml in this tree; nothing to build"; exit 0; }
CHANGED_FILE="${COMMIT_GATE_CHANGED_FILE:-$TREE/.commit-gate-changed}"
PROJECT="harness-gate-${SHA:0:12}"

_compose() {
    docker compose -p "$PROJECT" --env-file "$HARNESS_ENV_FILE" \
        --project-directory "$TREE" -f "$TREE/docker-compose.yml" "$@"
}

if ! SERVICES="$(python3 "$TREE/infra/auto-deploy/compose_fragments.py" --repo "$TREE" --changed-file "$CHANGED_FILE")"; then
    log "could not read which services this commit changes"
    exit 3
fi
[ -n "$SERVICES" ] || { log "no compose service changed, so there is no image to build"; exit 0; }
if [ "$SERVICES" = "all" ]; then
    SERVICES="$(_compose config --services 2>/dev/null)" || { log "docker compose could not read the tree's configuration"; exit 3; }
fi

root=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || printf '')
if [ -n "$root" ]; then
    free_mb=$(df -Pm "$root" 2>/dev/null | awk 'NR==2 {print $4}')
    case "$free_mb" in
        "" | *[!0-9]*) ;;
        *) if [ "$free_mb" -lt "$COMMIT_GATE_BUILD_MIN_FREE_MB" ]; then
               log "only ${free_mb} MB free where docker writes; leaving this commit's images to the cycle"
               exit 2
           fi ;;
    esac
fi

# shellcheck disable=SC1091
if ! . "$SELF/../steps/build_verdict.sh" 2>/dev/null; then
    _build_fault_kind() { printf 'box'; return 0; }
fi

status=0
while IFS= read -r svc; do
    [ -n "$svc" ] || continue
    build_log="$TREE/.commit-gate-build-$svc.log"
    log "building $svc"
    if ! _compose build --build-arg "GIT_SHA=$SHA" "$svc" > "$build_log" 2>&1; then
        mkdir -p "$STATE_DIR/gate-build-tails" 2>/dev/null
        tail -40 "$build_log" > "$STATE_DIR/gate-build-tails/$SHA" 2>/dev/null || true
        if [ "$(_build_fault_kind "$build_log")" = "commit" ]; then
            log "$svc did not build, and the fault is this commit's"
            status=1
        else
            log "$svc did not build, and the fault is this box's"
            [ "$status" -eq 1 ] || status=2
        fi
        break
    fi
done <<< "$SERVICES"

# Remove the throwaway tags; the layers stay cached.
_compose config --images 2>/dev/null | while IFS= read -r image; do
    case "$image" in "$PROJECT"-*) docker image rm -f "$image" >/dev/null 2>&1 || true ;; esac
done
exit "$status"
