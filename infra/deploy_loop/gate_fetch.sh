#!/bin/bash
# Init container of a gate Job: commit GATE_SHA checked out at GATE_TREE as a
# git repository whose HEAD is that commit, the shape steps/35-export.sh gives
# the cycle's export (tests run git against the root).
#
# A full clone of main into the Job's own volume, never blobless or shallow
# (_gate_job.py says why). When GATE_SHA is not on main, GATE_REF (a pull
# request's merge ref) or the sha itself is fetched under refs/gate/. The token
# file is optional: a public repository clones without one. It is read through
# a credential helper, never put in the environment or in the tree's config.
#
# FAILURE POLICY: any failure exits non-zero, which the cycle reads as 125,
# AMBER: the gate could not start, nothing ships, the next tick retries.
set -u
: "${GATE_SHA:?}" "${GATE_TREE:?}" "${GATE_REPO_URL:?}"
token_file="${GATE_TOKEN_FILE:-}"

mkdir -p "$GATE_TREE" && cd "$GATE_TREE" || exit 1
git init -q || exit 1
git remote add origin "$GATE_REPO_URL" || exit 1
if [ -n "$token_file" ] && [ -s "$token_file" ]; then
    git config credential.helper "!f() { echo username=x-access-token; echo password=\$(cat $token_file); }; f" || exit 1
fi
timeout "${GATE_FETCH_SECONDS:-600}" git fetch -q origin "+refs/heads/main:refs/remotes/origin/main" || {
    echo "[gate-fetch] fetch of main from $GATE_REPO_URL failed"; exit 1; }
if ! git cat-file -e "$GATE_SHA^{commit}" 2>/dev/null; then
    timeout "${GATE_FETCH_SECONDS:-600}" git fetch -q origin "+${GATE_REF:-$GATE_SHA}:refs/gate/wanted" || {
        echo "[gate-fetch] fetch of ${GATE_REF:-$GATE_SHA} failed"; exit 1; }
fi
git checkout -q --detach "$GATE_SHA" || { echo "[gate-fetch] checkout of $GATE_SHA failed"; exit 1; }
git config --unset credential.helper 2>/dev/null
git remote remove origin || exit 1
echo "[gate-fetch] $GATE_SHA checked out at $GATE_TREE"
