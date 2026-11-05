#!/bin/bash
# Build the stack images ONE commit changes, from that commit's own tree, and
# push nothing.
#
#   commit_gate/build_images.sh <sha> <tree>
#
# Exit 0 built (or nothing to build), 1 a build the COMMIT broke, 2 a build the
# BUILDER broke (steps/build_verdict.sh decides which), 3 could not tell what to
# build. run_one.sh runs it after a green suite: a commit whose image will not
# build is then red before it reaches the queue, on the road a failing test
# takes.
#
# Which images: the same two answers step 50 asks, read out of the tree being
# built so the rule is the commit's own: compose_fragments.py names the changed
# services, `python3 -m infra.deploy_loop stack-images` says which of them are
# the stack's own and from which context and Dockerfile. Each is built through
# the cycle's BuildKit daemon (BUILDKIT_HOST) with `--output type=cacheonly`:
# nothing is tagged or pushed, because step 50 reuses nothing and a tag pushed
# for a commit later ejected would be a lie. The layers stay in the daemon's
# cache, so the cycle's own build of the same tree is a cache hit.

set -u
SELF="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="${STATE_DIR:-/var/lib/harness}"
SHA="${1:-}"
TREE="${2:-}"
log() { printf '[%s] [commit-gate build %s] %s\n' "$(date -Iseconds)" "${SHA:0:12}" "$*" >&2; }

if [ -z "$SHA" ] || [ -z "$TREE" ] || [ ! -d "$TREE" ]; then
    log "usage: build_images.sh <sha> <tree>"
    exit 3
fi
CHANGED_FILE="${COMMIT_GATE_CHANGED_FILE:-$TREE/.commit-gate-changed}"

declare -A CONTEXT_OF DOCKERFILE_OF
while read -r name context dockerfile; do
    [ -n "$name" ] || continue
    CONTEXT_OF[$name]="$context"
    DOCKERFILE_OF[$name]="$dockerfile"
done < <(cd "$TREE" && python3 -m infra.deploy_loop stack-images "$TREE" 2>/dev/null)
if ! SERVICES="$(python3 "$TREE/infra/auto-deploy/compose_fragments.py" --repo "$TREE" --changed-file "$CHANGED_FILE")"; then
    log "could not read which services this commit changes"
    exit 3
fi
[ "$SERVICES" = "all" ] && SERVICES="$(printf '%s\n' "${!CONTEXT_OF[@]}")"
WANTED=()
while IFS= read -r svc; do
    [ -n "$svc" ] && [ -n "${CONTEXT_OF[$svc]+set}" ] && WANTED+=("$svc")
done <<< "$SERVICES"
[ "${#WANTED[@]}" -gt 0 ] || { log "no stack image changed, so there is nothing to build"; exit 0; }
if [ -z "${BUILDKIT_HOST:-}" ] || ! command -v buildctl > /dev/null 2>&1; then
    log "no BuildKit daemon to build with; leaving this commit's images to the cycle"
    exit 2
fi

# shellcheck disable=SC1091
if ! . "$SELF/../steps/build_verdict.sh" 2>/dev/null; then
    _build_fault_kind() { printf 'box'; return 0; }
fi

status=0
for svc in "${WANTED[@]}"; do
    build_log="$TREE/.commit-gate-build-$svc.log"
    if [ "${CONTEXT_OF[$svc]}" = "-" ] || [ "${DOCKERFILE_OF[$svc]}" = "-" ]; then
        printf 'no compose service builds the stack image %s\n' "$svc" > "$build_log"
        log "$svc has no compose service to build it, which is this commit's to fix"
        status=1
        break
    fi
    log "building $svc"
    if ! buildctl build --frontend dockerfile.v0 \
            --local "context=$TREE/${CONTEXT_OF[$svc]}" \
            --local "dockerfile=$TREE/$(dirname "${DOCKERFILE_OF[$svc]}")" \
            --opt "filename=$(basename "${DOCKERFILE_OF[$svc]}")" \
            --opt "build-arg:GIT_SHA=$SHA" \
            --output type=cacheonly > "$build_log" 2>&1; then
        mkdir -p "$STATE_DIR/gate-build-tails" 2>/dev/null
        tail -40 "$build_log" > "$STATE_DIR/gate-build-tails/$SHA" 2>/dev/null || true
        if [ "$(_build_fault_kind "$build_log")" = "commit" ]; then
            log "$svc did not build, and the fault is this commit's"
            status=1
        else
            log "$svc did not build, and the fault is the builder's"
            [ "$status" -eq 1 ] || status=2
        fi
        break
    fi
done
exit "$status"
