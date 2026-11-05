#!/usr/bin/env bash
# Apply the cluster foundation in infra/k8s/: every area directory, rendered
# from the settings.
#
#   infra/cluster/apply.sh [--render | --dry-run] [path/to/harness.env]
#
# Each directory under infra/k8s/ with a kustomization.yaml is one area; a
# kustomize Component (vault-secret, system-pool) is included by the areas and
# skipped here. `kubectl kustomize` builds an area (files outside it allowed,
# so postgres can read infra/nextcloud/postgres-init.sh), then the settings in
# PLACEHOLDERS below are filled in. Any other ${...} left in the output stops
# the run before anything is sent. The cluster Caddyfile is rendered into
# infra/k8s/ingress/ first (python3 -m infra.caddy.cluster_caddyfile), and the
# ingress area is skipped while INGRESS_LB_IP_ID is empty, so no load balancer
# is made on a throwaway address. The media area is skipped while
# MEDIA_PUBLIC_IP is empty, so no media node bills while calls are off. The
# deploy area (the deploy loop) is skipped while DEPLOY_CYCLE_IMAGE is empty.
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
: "${POOL_ROLE_LABEL:=harness/role}"
: "${IMAGE_REGISTRY_HOST:=rg.${SCW_REGION}.scw.cloud}"
: "${IMAGE_REGISTRY:=${IMAGE_REGISTRY_HOST}/${SCW_REGISTRY:-}}"
zones=${CLUSTER_ZONES:-}
: "${INGRESS_LB_ZONE:=${zones%%,*}}"
: "${INGRESS_LB_TYPE:=LB-S}"
: "${INGRESS_LB_IP_ID:=}"
: "${BACKUP_SNAPSHOT_CLASS:=scw-snapshot}"
: "${BACKUP_KEEP:=7}"
: "${ASSISTANT_TIMEZONE:=UTC}"
: "${MEDIA_PUBLIC_IP:=}"
: "${MEDIA_IMAGE_TAG:=}"
: "${DEPLOY_CYCLE_IMAGE:=}"
# The deploy-cycle image rolls itself (infra/deploy_loop/_cycle_image.py): once
# its guard has promoted one, ConfigMap deploy-cycle-image names it as `good`,
# and an apply that put the settings' older image back would start a trial of
# that one. Only when applying to a cluster that has the ConfigMap.
if [ "$mode" = apply ] && [ -n "$DEPLOY_CYCLE_IMAGE" ]; then
    promoted=$(kubectl -n deploy get configmap deploy-cycle-image -o 'jsonpath={.data.good}' 2>/dev/null || true)
    [ -n "$promoted" ] && DEPLOY_CYCLE_IMAGE="$promoted"
fi
if [ -z "${DEPLOY_REPO_URL:-}" ]; then
    DEPLOY_REPO_URL=$(python3 -c 'import json, sys; repo = json.load(open(sys.argv[1])).get("repo", ""); print(f"https://github.com/{repo}.git" if repo else "")' "$REPO/.claude/project.json")
fi
# The gate image the tree pins, for the warm gate nodes to hold; the cycle
# image (which every gate node pulls anyway) until one is pinned.
GATE_IMAGE=$(python3 -c 'import sys; sys.path.insert(0, sys.argv[2]); from infra.deploy_loop._gate_job import pinned_gate_image; print(pinned_gate_image(open(sys.argv[1]).read()))' "$REPO/infra/gate-image/pin" "$REPO")
: "${GATE_IMAGE:=$DEPLOY_CYCLE_IMAGE}"
# The warm gate floor (infra/cluster/pool_fallbacks/_warm.py): the working, idle
# and current counts, then the up and down cron lines. The Deployment gets the
# current count, the same the CronJobs would set, so an apply never fights them.
# No floor: both CronJobs suspended on a dummy schedule, no warm node.
warm=$(cd "$REPO" && python3 -m infra.cluster.pool_fallbacks --warm)
{ read -r GATE_WARM_NODES GATE_IDLE_NODES GATE_WARM_NOW; read -r GATE_WARM_UP; read -r GATE_WARM_DOWN; } <<< "$warm" || true
GATE_WARM_SUSPEND=false
if [ "$GATE_WARM_NODES" = 0 ]; then
    GATE_WARM_SUSPEND=true GATE_WARM_UP="0 0 1 1 *" GATE_WARM_DOWN="0 0 1 1 *"
fi
media_zones=${POOL_MEDIA_ZONES:-$zones}
: "${MEDIA_ZONE:=${media_zones%%,*}}"
# Every setting a manifest may name as ${KEY}; a new one is added here.
PLACEHOLDERS="SCW_REGION SCW_PROJECT_ID VAULT_SECRET_NAME POOL_ROLE_LABEL IMAGE_REGISTRY_HOST IMAGE_REGISTRY INGRESS_LB_ZONE INGRESS_LB_TYPE INGRESS_LB_IP_ID BACKUP_SNAPSHOT_CLASS BACKUP_KEEP ASSISTANT_TIMEZONE MEDIA_PUBLIC_IP MEDIA_ZONE MEDIA_IMAGE_TAG DEPLOY_CYCLE_IMAGE DEPLOY_REPO_URL GATE_IMAGE GATE_WARM_NODES GATE_IDLE_NODES GATE_WARM_UP GATE_WARM_DOWN GATE_WARM_SUSPEND GATE_WARM_NOW"
# shellcheck disable=SC2086
export PLACEHOLDERS $PLACEHOLDERS

render() {
    python3 -c '
import os, re, sys
text = sys.stdin.read()
for key in os.environ["PLACEHOLDERS"].split():
    text = text.replace("${" + key + "}", os.environ[key])
left = sorted(set(re.findall(r"\$\{[A-Za-z_]+\}", text)))
if left:
    sys.exit("ERROR: no setting fills " + ", ".join(left))
sys.stdout.write(text)
'
}

apply_args=(apply -f -)
[ "$mode" != dry-run ] || apply_args=(apply --dry-run=client --validate=false -f -)

(cd "$REPO" && python3 -m infra.caddy.cluster_caddyfile >&2)

for area in "$REPO"/infra/k8s/*/; do
    [ -f "$area/kustomization.yaml" ] || continue
    if grep -q '^kind: Component' "$area/kustomization.yaml"; then
        continue
    fi
    if [ "$mode" != render ] && [ "$(basename "$area")" = ingress ] && [ -z "$INGRESS_LB_IP_ID" ]; then
        echo "==> ingress skipped: INGRESS_LB_IP_ID is empty (reserve an IP first)" >&2
        continue
    fi
    if [ "$mode" != render ] && [ "$(basename "$area")" = media ]; then
        if [ -z "$MEDIA_PUBLIC_IP" ]; then
            echo "==> media skipped: MEDIA_PUBLIC_IP is empty (video calls are off)" >&2
            continue
        fi
        [ -n "$MEDIA_IMAGE_TAG" ] || { echo "ERROR: MEDIA_PUBLIC_IP is set but MEDIA_IMAGE_TAG is empty (infra/media/CLAUDE.md)" >&2; exit 1; }
    fi
    if [ "$mode" != render ] && [ "$(basename "$area")" = deploy ] && [ -z "$DEPLOY_CYCLE_IMAGE" ]; then
        echo "==> deploy skipped: DEPLOY_CYCLE_IMAGE is empty (build infra/deploy_loop/image first)" >&2
        continue
    fi
    echo "==> $(basename "$area")" >&2
    if [ "$mode" = render ]; then
        printf -- '---\n'
        kubectl kustomize --load-restrictor LoadRestrictionsNone "$area" | render
    else
        kubectl kustomize --load-restrictor LoadRestrictionsNone "$area" | render | kubectl "${apply_args[@]}"
    fi
done
