#!/bin/bash
# Whose fault a failed image build was: the commit's, or this box's.
#
# NOT A STEP. It defines one function and a list, runs nothing, and ends in
# `true` because the cycle may have `set -e` on. Sourced by 10-prelude.sh and by
# ../commit_gate/build_images.sh, so the rule exists in one copy.
#
#   _build_fault_kind <build log>   prints `commit` or `box`
#
# `box` is any failure a different commit could not have avoided: no disk, an
# unreachable registry, a dead daemon, a damaged layer store, a killed build, a
# docker without the compose plugin.
# It holds the bookmark and alerts, and reverts nothing, so a broken build cache
# never hands back an innocent commit. `commit` is everything else (a Dockerfile
# that does not parse, a COPY of a file that is gone, a failing RUN): that can
# be ejected like a failing test. An unreadable log is `box`: the answer that
# cannot revert anybody on the strength of a file nobody could read.

BUILD_BOX_FAULT_SIGNS="${BUILD_BOX_FAULT_SIGNS:-$(cat <<'SIGNS'
no space left on device
blob not found
failed to extract layer
failed to register layer
Cannot connect to the Docker daemon
error getting credentials
unauthorized: authentication required
toomanyrequests
Client.Timeout exceeded
i/o timeout
TLS handshake timeout
temporary failure in name resolution
no such host
connection refused
connection reset by peer
unexpected status: 5
502 Bad Gateway
503 Service Unavailable
504 Gateway
signal: killed
cannot allocate memory
context deadline exceeded
context canceled
invalid tar header
unexpected EOF
input/output error
read-only file system
unknown shorthand flag
is not a docker command
SIGNS
)}"

_build_fault_kind() {
    local log_file="${1:-}" sign
    if [ -z "$log_file" ] || [ ! -r "$log_file" ]; then
        printf 'box'
        return 0
    fi
    while IFS= read -r sign; do
        [ -n "$sign" ] || continue
        if grep -q -F -i -e "$sign" "$log_file" 2>/dev/null; then
            printf 'box'
            return 0
        fi
    done <<< "$BUILD_BOX_FAULT_SIGNS"
    printf 'commit'
    return 0
}

true
