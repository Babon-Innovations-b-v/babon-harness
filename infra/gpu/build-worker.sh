#!/usr/bin/env bash
# Build and push the notulen GPU worker image from a temporary Scaleway
# instance in your region.
#
# Why a temporary instance: the image is big (PyTorch plus CUDA base, more
# than 10 GB). Building it on a laptop or pushing it over home internet fails
# often. A small cloud instance in the same region as the registry builds and
# pushes it in minutes, then gets deleted. Total cost: a few cents.
#
# Usage:
#   infra/gpu/build-worker.sh [tag]                  # full build, tag defaults to v1
#   infra/gpu/build-worker.sh --patch <base-tag> <tag>
#
# --patch rebuilds only the top layer: worker.py and the minutes template are
# copied onto an existing image (<base-tag>), which takes a minute instead of
# half an hour. Use it when only apps/notulen/entrypoints/worker.py or
# apps/notulen/inputs/notulen_template.md changed.
#
# Environment:
#   SCW_REGISTRY     registry namespace to push to (default: harness); created
#                    on first use, private
#   HF_TOKEN         optional Hugging Face read token; bakes the gated speaker
#                    label models into the image (see infra/gpu/Dockerfile)
#   FORCE_REBUILD=1  rebuild even when the tag already exists in the registry
#   BUILDER_TYPE     instance type for the build box (default PRO2-M)
#
# Prereqs: scw configured (access key, secret key, default region and zone)
# and an ssh key at ~/.ssh/id_ed25519 registered with Scaleway.
#
# The EXIT trap always deletes the build instance, even on failure.
# The last line of output on success is the pushed image reference: put it in
# NOTULEN_WORKER_IMAGE (config/harness.env and the vault).
set -euo pipefail

PATCH_BASE=""
if [ "${1:-}" = "--patch" ]; then
    [ $# -eq 3 ] || { echo "usage: $0 --patch <base-tag> <tag>" >&2; exit 1; }
    PATCH_BASE="$2"
    TAG="$3"
else
    TAG="${1:-v1}"
fi
BUILDER_TYPE="${BUILDER_TYPE:-PRO2-M}"
NAMESPACE="${SCW_REGISTRY:-harness}"

REGION=$(scw config get default-region)
ZONE=$(scw config get default-zone)
if [ -z "$REGION" ] || [ -z "$ZONE" ]; then
    echo "ERROR: scw has no default region or zone; run scw config set default-region=... default-zone=..." >&2
    exit 1
fi

REGISTRY="rg.${REGION}.scw.cloud"
IMAGE_REF="${REGISTRY}/${NAMESPACE}/notulen-worker:${TAG}"

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO_ROOT"

echo "==> Target image: $IMAGE_REF"

# --- Registry namespace, created once, reused after -------------------------
if scw registry namespace list region="$REGION" -o json \
        | python3 -c 'import sys,json; ns=json.load(sys.stdin) or []; sys.exit(0 if any(n.get("name")==sys.argv[1] for n in ns) else 1)' "$NAMESPACE"; then
    echo "==> Registry namespace ${NAMESPACE} already exists."
else
    echo "==> Creating registry namespace ${NAMESPACE} in ${REGION}..."
    scw registry namespace create name="$NAMESPACE" region="$REGION" is-public=false >/dev/null
fi

# --- Skip the whole build when the tag is already in the registry ------------
tag_exists() {
    local image_id
    image_id=$(scw registry image list name=notulen-worker region="$REGION" -o json \
        | python3 -c 'import sys,json; imgs=[i for i in (json.load(sys.stdin) or []) if i.get("name")=="notulen-worker"]; print(imgs[0]["id"] if imgs else "")')
    [ -n "$image_id" ] || return 1
    scw registry tag list image-id="$image_id" region="$REGION" -o json \
        | python3 -c 'import sys,json; tags=json.load(sys.stdin) or []; sys.exit(0 if any(t.get("name")==sys.argv[1] for t in tags) else 1)' "$TAG"
}

if [ "${FORCE_REBUILD:-0}" != "1" ] && tag_exists; then
    echo "==> Tag ${TAG} is already in the registry; nothing to build (set FORCE_REBUILD=1 to rebuild)."
    echo "$IMAGE_REF"
    exit 0
fi

# --- Bundle the repo (the build context) --------------------------------------
echo "==> Bundling the repo source..."
BUNDLE=$(mktemp -t harness-src-XXXXXX.tgz)
# Only what the worker image needs: no secrets, no business folder, no env files.
tar czf "$BUNDLE" \
    --exclude='__pycache__' --exclude='*.pyc' \
    infra/gpu/Dockerfile \
    apps/notulen/entrypoints/worker.py \
    apps/notulen/inputs/notulen_template.md \
    apps/notulen/shared/worker_constraints.txt
echo "    bundle: $(du -h "$BUNDLE" | awk '{print $1}')"

# --- Temporary build instance -------------------------------------------------
#
# The name is chosen, and the trap installed, BEFORE the instance exists. If
# `scw instance server create` starts a machine and then the command or its
# output parsing fails, the id never reaches this script, and a trap installed
# afterwards would have nothing to delete: a running instance with a 100 GB
# volume, billing, that nobody is looking for. The cleanup below therefore
# falls back to finding the instance by its name.
BUILDER_NAME="harness-builder-$(date +%s)"
INSTANCE_ID=""
CREATE_STARTED=false

cleanup() {
    if [ -z "$INSTANCE_ID" ]; then
        # No id: look the instance up by name, in case it was created and we
        # never learned its id.
        INSTANCE_ID=$(scw instance server list name="$BUILDER_NAME" zone="$ZONE" -o json 2>/dev/null \
            | python3 -c 'import sys,json; rows=json.load(sys.stdin) or []; print(rows[0]["id"] if rows else "")' 2>/dev/null || true)
        # Still nothing, after the create command had already been issued: the
        # lookup may itself have failed (no network, an unexpected scw answer),
        # so an instance may be running and billing under this name. Say so,
        # because this branch used to exit in silence, which reads exactly like
        # "nothing was created".
        if [ -z "$INSTANCE_ID" ] && [ "$CREATE_STARTED" = true ]; then
            echo "WARNING: no build instance named ${BUILDER_NAME} was found in ${ZONE}, but the create command had already run. If it started a machine, it is still billing. Check by hand: scw instance server list zone=${ZONE}, and terminate anything named ${BUILDER_NAME}." >&2
        fi
    fi
    if [ -z "$INSTANCE_ID" ]; then
        rm -f "$BUNDLE"
        return
    fi
    echo "==> Deleting build instance ${INSTANCE_ID} (${BUILDER_NAME})..."
    scw instance server terminate "$INSTANCE_ID" zone="$ZONE" with-ip=true with-block=true >/dev/null || \
        echo "WARNING: could not delete instance ${INSTANCE_ID} (${BUILDER_NAME}); it is still billing. Delete it by hand: scw instance server terminate ${INSTANCE_ID} zone=${ZONE} with-ip=true with-block=true" >&2
    rm -f "$BUNDLE"
}
trap cleanup EXIT

echo "==> Creating temporary build instance (${BUILDER_TYPE}, 100 GB, ${ZONE})..."
CREATE_STARTED=true
INSTANCE_ID=$(scw instance server create \
    name="$BUILDER_NAME" \
    type="$BUILDER_TYPE" \
    zone="$ZONE" \
    image=ubuntu_noble \
    root-volume=block:100G \
    ip=new \
    -o json | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "    instance: $INSTANCE_ID"

echo "==> Waiting for the instance's public IP..."
IP=""
for _attempt in $(seq 1 30); do
    IP=$(scw instance server get "$INSTANCE_ID" zone="$ZONE" -o json 2>/dev/null \
        | python3 -c '
import sys, json
data = json.load(sys.stdin)
ip = (data.get("public_ip") or {}).get("address")
if not ip:
    ips = data.get("public_ips") or []
    if ips:
        ip = ips[0].get("address", "")
print(ip or "")
' 2>/dev/null)
    [ -n "$IP" ] && break
    sleep 5
done
if [ -z "$IP" ]; then
    echo "ERROR: timed out waiting for the instance's public IP" >&2
    exit 1
fi
echo "    IP: $IP"

echo "==> Waiting for ssh..."
# accept-new is trust on first use: we accept whatever host key answers on this
# brand-new IP, because there is nowhere to look the real one up first. That is
# an accepted risk here and it is worth naming, because the registry login
# further down pipes a Scaleway secret key over this connection, so an attacker
# who could answer instead of the instance would get it. Scaleway does not
# publish an instance's host key over the API, so closing this properly means
# baking a key in with cloud-init user data at create time, not a flag change.
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 -o BatchMode=yes)
SSH_OK=0
for _attempt in $(seq 1 40); do
    if ssh "${SSH_OPTS[@]}" "root@$IP" true 2>/dev/null; then
        SSH_OK=1
        break
    fi
    sleep 5
done
if [ "$SSH_OK" != "1" ]; then
    echo "ERROR: timed out waiting for ssh on $IP" >&2
    exit 1
fi

echo "==> Installing Docker on the build instance..."
ssh "${SSH_OPTS[@]}" "root@$IP" \
    "command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh >/dev/null 2>&1; docker --version"

echo "==> Uploading the source bundle..."
scp "${SSH_OPTS[@]}" "$BUNDLE" "root@$IP:/root/harness-src.tgz"
ssh "${SSH_OPTS[@]}" "root@$IP" "mkdir -p /root/build && tar xzf /root/harness-src.tgz -C /root/build"

echo "==> Logging in to the registry (intra-region push)..."
scw config get secret-key \
    | ssh "${SSH_OPTS[@]}" "root@$IP" "docker login '$REGISTRY' -u nologin --password-stdin"

SECRET_ARGS=""
if [ -n "${HF_TOKEN:-}" ]; then
    echo "==> Hugging Face token found; speaker label models will be baked in."
    printf '%s' "$HF_TOKEN" \
        | ssh "${SSH_OPTS[@]}" "root@$IP" "cat > /root/hf-token && chmod 600 /root/hf-token"
    SECRET_ARGS="--secret id=hf_token,src=/root/hf-token"
else
    echo "==> No HF_TOKEN set; the image will transcribe without speaker labels (rebuild with HF_TOKEN to add them)."
fi

if [ -n "$PATCH_BASE" ]; then
    echo "==> Patching ${PATCH_BASE} with the current worker.py and template..."
    ssh "${SSH_OPTS[@]}" "root@$IP" "set -o pipefail; cd /root/build && printf '%s\n' \
        'FROM ${REGISTRY}/${NAMESPACE}/notulen-worker:${PATCH_BASE}' \
        'COPY apps/notulen/entrypoints/worker.py /app/notulen_worker.py' \
        'COPY apps/notulen/inputs/notulen_template.md /app/notulen_template.md' \
        > Dockerfile.patch && docker build -f Dockerfile.patch -t '$IMAGE_REF' . 2>&1 | tail -5"
else
    echo "==> Building the image on the instance (this is the long part, expect 15 to 30 minutes)..."
    ssh "${SSH_OPTS[@]}" "root@$IP" \
        "set -o pipefail; cd /root/build && DOCKER_BUILDKIT=1 docker build -f infra/gpu/Dockerfile $SECRET_ARGS -t '$IMAGE_REF' . 2>&1 | tail -5"
fi

echo "==> Pushing to the registry..."
ssh "${SSH_OPTS[@]}" "root@$IP" "set -o pipefail; docker push '$IMAGE_REF' 2>&1 | tail -3"

# Clean up now instead of at exit, so the pushed reference is the last line.
trap - EXIT
cleanup

echo "==> Done."
echo "$IMAGE_REF"
