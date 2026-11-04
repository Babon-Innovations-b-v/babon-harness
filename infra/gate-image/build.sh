#!/usr/bin/env bash
# Build the gate image from one commit, push it, and pin it by digest.
#
#   infra/gate-image/build.sh [<ref>]        # default HEAD
#
# What it does, in order:
#   1. exports <ref> with `git archive` into a scratch directory, so nothing
#      uncommitted ends up in the image;
#   2. builds infra/gate-image/Dockerfile from that export, tagged
#      <repository>:git-<sha12> (a tag is never reused);
#   3. checks the image with the network off: pytest and the workspace import;
#   4. pushes it and writes `pin` beside this file: the digest reference and a
#      `# built from: <sha>` line. Commit `pin` in the same commit as whatever
#      needed the build; the commit hook refuses a pin the registry lacks.
#
# Settings (config/harness.env, read when present; the environment wins):
#   GATE_IMAGE_REPOSITORY   where the image is pushed. Empty = the gate
#                           repository in the registry namespace,
#                           rg.<SCW_REGION>.scw.cloud/<SCW_REGISTRY>/gate.
#
# FAILURE POLICY: any failed step stops the script before `pin` is written, so
# a pin only ever names an image that was built, checked and pushed.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
REF="${1:-HEAD}"
if [ -f "$REPO/config/harness.env" ]; then
    # shellcheck disable=SC1091
    preset_repository="${GATE_IMAGE_REPOSITORY:-}"
    set -a; . "$REPO/config/harness.env"; set +a
    [ -n "$preset_repository" ] && GATE_IMAGE_REPOSITORY="$preset_repository"
fi
if [ -z "${GATE_IMAGE_REPOSITORY:-}" ]; then
    if [ -z "${SCW_REGISTRY:-}" ] || [ -z "${SCW_REGION:-}" ]; then
        echo "build.sh: set GATE_IMAGE_REPOSITORY, or SCW_REGISTRY and SCW_REGION, in config/harness.env" >&2
        exit 2
    fi
    GATE_IMAGE_REPOSITORY="rg.${SCW_REGION}.scw.cloud/${SCW_REGISTRY}/gate"
fi

sha=$(git -C "$REPO" rev-parse --verify "$REF^{commit}")
tag="$GATE_IMAGE_REPOSITORY:git-${sha:0:12}"
export_dir=$(mktemp -d)
trap 'rm -rf "$export_dir"' EXIT
git -C "$REPO" archive "$sha" | tar -x -C "$export_dir"

echo "==> building $tag from $sha"
DOCKER_BUILDKIT=1 docker build -f "$export_dir/infra/gate-image/Dockerfile" \
    --build-arg GIT_SHA="$sha" -t "$tag" "$export_dir"

echo "==> checking it with the network off"
docker run --rm --network none "$tag" /opt/gate-env/bin/python -c "import pytest, dashkit, documents"

echo "==> pushing"
docker push -q "$tag" >/dev/null
reference=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$tag" \
    | grep -F "$GATE_IMAGE_REPOSITORY@sha256:" | head -n 1)
[ -n "$reference" ] || { echo "build.sh: pushed, but no digest came back for $tag" >&2; exit 1; }

cat > "$REPO/infra/gate-image/pin" <<PIN
# The gate image the commit hook's sealed run uses, by digest. Written only by
# infra/gate-image/build.sh; the last line is the reference, and it names an
# image only when it carries @sha256:.
# built from: $sha
$reference
PIN
echo "$reference"
