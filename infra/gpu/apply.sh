#!/usr/bin/env bash
# Put everything the notulen GPU tier needs into the cluster, idempotently.
#
#   KUBECONFIG=<admin kubeconfig> infra/gpu/apply.sh [path/to/harness.env]
#
# The env file defaults to $HARNESS_ROOT/harness.env (the vault copy the deploy
# cycle pulls, mode 600). From it this script creates, in $GPU_NAMESPACE:
#   - the namespace, the dashboard's service account and its Role (k8s/)
#   - the notulen-gpu-warmup PriorityClass (k8s/priorityclass.yaml)
#   - Secret notulen-worker-secrets: DB_URL (from DB_URL_OPS), ANTHROPIC_API_KEY,
#     S3_ACCESS_KEY, S3_SECRET_KEY, and HF_TOKEN when the vault has one
#   - ConfigMap notulen-worker-config: S3_ENDPOINT, S3_REGION, S3_BUCKET,
#     NOTULEN_LANGUAGE, NOTULEN_MODEL
#   - Secret registry-pull: pull access to the private Scaleway registry
#
# Credentials only ever go into Secrets; the Job reads them by secretKeyRef.
# No manifest in this repository holds a credential. The registry pull key is
# SCW_REGISTRY_PULL_KEY and it is required: make an API key limited to registry
# read for it. Your scw CLI profile's own secret key is never used, because it
# would put an admin credential into a cluster Secret.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ENV_FILE="${1:-${HARNESS_ROOT:-/opt/harness}/harness.env}"
[ -r "$ENV_FILE" ] || { echo "ERROR: cannot read $ENV_FILE" >&2; exit 1; }

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

PULL_KEY="${SCW_REGISTRY_PULL_KEY:-}"
[ -n "$PULL_KEY" ] || {
    echo "ERROR: SCW_REGISTRY_PULL_KEY is empty. Set it in the vault to an API key limited to registry read." >&2
    exit 1
}

: "${GPU_NAMESPACE:=notulen}"
: "${S3_REGION:=${SCW_REGION:-fr-par}}"
: "${S3_ENDPOINT:=https://s3.${S3_REGION}.scw.cloud}"
for required in DB_URL_OPS ANTHROPIC_API_KEY S3_ACCESS_KEY S3_SECRET_KEY S3_BUCKET; do
    if [ -z "${!required:-}" ]; then
        echo "ERROR: $required is empty in $ENV_FILE; the GPU worker cannot run without it" >&2
        exit 1
    fi
done
export GPU_NAMESPACE

render() { python3 -c 'import os,sys; sys.stdout.write(os.path.expandvars(sys.stdin.read()))' < "$1"; }

echo "==> Namespace, service account and RBAC in ${GPU_NAMESPACE}"
render "$HERE/k8s/namespace.yaml" | kubectl apply -f -
render "$HERE/k8s/rbac.yaml" | kubectl apply -f -
kubectl apply -f "$HERE/k8s/priorityclass.yaml"

SECRETS=$(mktemp)
chmod 600 "$SECRETS"
trap 'rm -f "$SECRETS"' EXIT
{
    printf 'DB_URL=%s\n' "$DB_URL_OPS"
    printf 'ANTHROPIC_API_KEY=%s\n' "$ANTHROPIC_API_KEY"
    printf 'S3_ACCESS_KEY=%s\n' "$S3_ACCESS_KEY"
    printf 'S3_SECRET_KEY=%s\n' "$S3_SECRET_KEY"
    if [ -n "${HF_TOKEN:-}" ]; then printf 'HF_TOKEN=%s\n' "$HF_TOKEN"; fi
} > "$SECRETS"

echo "==> Secret notulen-worker-secrets"
kubectl -n "$GPU_NAMESPACE" create secret generic notulen-worker-secrets \
    --from-env-file="$SECRETS" --dry-run=client -o yaml | kubectl apply -f -

echo "==> ConfigMap notulen-worker-config"
kubectl -n "$GPU_NAMESPACE" create configmap notulen-worker-config \
    --from-literal=S3_ENDPOINT="$S3_ENDPOINT" \
    --from-literal=S3_REGION="$S3_REGION" \
    --from-literal=S3_BUCKET="$S3_BUCKET" \
    --from-literal=NOTULEN_LANGUAGE="${NOTULEN_LANGUAGE:-}" \
    --from-literal=NOTULEN_MODEL="${NOTULEN_MODEL:-claude-sonnet-4-6}" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "==> Secret registry-pull"
kubectl -n "$GPU_NAMESPACE" create secret docker-registry registry-pull \
    --docker-server="rg.${SCW_REGION:-fr-par}.scw.cloud" \
    --docker-username=nologin \
    --docker-password="$PULL_KEY" \
    --dry-run=client -o yaml | kubectl apply -f -

echo "==> Done. Next: infra/gpu/make-dashboard-kubeconfig.sh for KUBECONFIG_B64."
