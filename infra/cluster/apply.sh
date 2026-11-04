#!/usr/bin/env bash
# Apply the cluster foundation in infra/k8s/: every area directory, rendered
# from the settings.
#
#   infra/cluster/apply.sh [--render | --dry-run] [path/to/harness.env]
#
# Each directory under infra/k8s/ with a kustomization.yaml is one area; a
# kustomize Component (infra/k8s/vault-secret) is included by the areas and
# skipped here. `kubectl kustomize` builds an area, then the three settings the
# manifests name (SCW_REGION, SCW_PROJECT_ID, VAULT_SECRET_NAME) are filled in.
# Any other ${...} left in the output stops the run before anything is sent.
# --render prints the rendered manifests and needs no cluster. --dry-run
# sends them to the current cluster as a client dry run (kubectl needs the
# cluster to know the kinds), which changes nothing.
#
# FAILURE POLICY: fail loud (set -euo pipefail). A missing setting or a
# rejected manifest stops the run; the areas already applied stay applied.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
mode=apply
case "${1:-}" in
    --render) mode=render; shift ;;
    --dry-run) mode=dry-run; shift ;;
esac
ENV_FILE="${1:-$REPO/config/harness.env}"
[ -r "$ENV_FILE" ] || { echo "ERROR: cannot read $ENV_FILE" >&2; exit 1; }

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
: "${VAULT_SECRET_NAME:=harness-env}"
for required in SCW_REGION SCW_PROJECT_ID; do
    [ -n "${!required:-}" ] || { echo "ERROR: $required is empty in $ENV_FILE" >&2; exit 1; }
done
export SCW_REGION SCW_PROJECT_ID VAULT_SECRET_NAME

render() {
    python3 -c '
import os, re, sys
text = sys.stdin.read()
for key in ("SCW_REGION", "SCW_PROJECT_ID", "VAULT_SECRET_NAME"):
    text = text.replace("${" + key + "}", os.environ[key])
left = sorted(set(re.findall(r"\$\{[A-Za-z_]+\}", text)))
if left:
    sys.exit("ERROR: no setting fills " + ", ".join(left))
sys.stdout.write(text)
'
}

apply_args=(apply -f -)
[ "$mode" != dry-run ] || apply_args=(apply --dry-run=client --validate=false -f -)

for area in "$REPO"/infra/k8s/*/; do
    [ -f "$area/kustomization.yaml" ] || continue
    if grep -q '^kind: Component' "$area/kustomization.yaml"; then
        continue
    fi
    echo "==> $(basename "$area")" >&2
    if [ "$mode" = render ]; then
        printf -- '---\n'
        kubectl kustomize "$area" | render
    else
        kubectl kustomize "$area" | render | kubectl "${apply_args[@]}"
    fi
done
