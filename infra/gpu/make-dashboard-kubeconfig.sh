#!/usr/bin/env bash
# Mint the kubeconfig the notulen dashboard uses to submit GPU jobs.
#
# Why this exists: the kubeconfig `scw k8s kubeconfig get` returns
# authenticates through the scw command itself (an "exec plugin"). Inside the
# notulen container there is no scw, so every request would arrive anonymous
# and be refused. This prints a self-contained kubeconfig with the static token
# of the notulen-dashboard service account, which may only manage
# transcription Jobs and GPU placeholder Pods in $GPU_NAMESPACE
# (k8s/rbac.yaml, applied by infra/gpu/apply.sh).
#
# Usage (an admin kubeconfig must be active):
#   KUBECONFIG=<admin kubeconfig> infra/gpu/make-dashboard-kubeconfig.sh > dashboard-kubeconfig.yaml
#   base64 -w0 dashboard-kubeconfig.yaml   -> KUBECONFIG_B64 in the vault
#
# Idempotent: safe to run again; it reuses everything that already exists.
set -euo pipefail

NS="${GPU_NAMESPACE:-notulen}"
SA=notulen-dashboard
HERE=$(cd "$(dirname "$0")" && pwd)

log() { printf '[dashboard-kubeconfig] %s\n' "$*" >&2; }

export GPU_NAMESPACE="$NS"
render() { python3 -c 'import os,sys; sys.stdout.write(os.path.expandvars(sys.stdin.read()))' < "$1"; }
render "$HERE/k8s/namespace.yaml" | kubectl apply -f - >&2
render "$HERE/k8s/rbac.yaml" | kubectl apply -f - >&2

# The token is filled in asynchronously; wait for it.
TOKEN=""
for _ in $(seq 1 20); do
    TOKEN=$(kubectl -n "$NS" get secret "$SA-token" -o jsonpath='{.data.token}' 2>/dev/null | base64 -d || true)
    [ -n "$TOKEN" ] && break
    sleep 2
done
[ -n "$TOKEN" ] || { log "token never appeared on secret $SA-token"; exit 1; }

SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
CA=$(kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')

log "service account $NS/$SA ready; kubeconfig on stdout"
cat <<KUBECONFIG
apiVersion: v1
kind: Config
clusters:
- name: harness-gpu
  cluster:
    server: $SERVER
    certificate-authority-data: $CA
contexts:
- name: harness-gpu
  context: {cluster: harness-gpu, namespace: $NS, user: $SA}
current-context: harness-gpu
users:
- name: $SA
  user:
    token: $TOKEN
KUBECONFIG
