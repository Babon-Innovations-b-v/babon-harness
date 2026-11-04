#!/usr/bin/env bash
# Create, or adopt, the cluster and its pools from the settings, then lay the
# foundation in infra/k8s/ on it.
#
#   infra/cluster/create-cluster.sh [--apply] [--vault-env FILE] [path/to/harness.env]
#
# Without --apply it only reads: it checks the tools and the scw login, finds
# the cluster named CLUSTER_NAME in SCW_REGION, and prints every change it
# would make. With --apply, in order:
#   1. the cluster: adopted when one of that name exists, else created with the
#      first role's preferred pool and the autoscaler's `priority` expander;
#      CLUSTER_ID and SCW_PROJECT_ID are written back into the settings file;
#   2. every pool `python3 -m infra.cluster.pool_fallbacks --pools` lists:
#      a missing preferred pool is created (a refusal stops the run), a
#      fallback is created, kept, or recreated while empty when its root disk is
#      wrong; a fallback the provider refuses (no stock of that type in that
#      zone) is logged and the rest go on;
#   3. the expander's ConfigMap, from the pool ids as they now exist;
#   4. the External Secrets operator (Helm chart, pinned below), its key from
#      ESO_ACCESS_KEY and ESO_SECRET_KEY in the vault copy (--vault-env), and
#      infra/cluster/apply.sh.
# Each step reads the live state first, so a run that died halfway resumes.
# An existing pool's size, type or taints are never changed here.
#
# Prices and boot times of node types are not measured here; the provider's
# price list is the source.
#
# FAILURE POLICY: fail loud (set -euo pipefail); every scw call waits (-w) and
# a failed one stops the run, except a fallback the provider refuses.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
cd "$REPO"
ESO_CHART_VERSION=2.2.0

apply=0
vault_env=""
while [ $# -gt 0 ]; do
    case "$1" in
        --apply) apply=1 ;;
        --vault-env) vault_env="${2:?--vault-env needs a file}"; shift ;;
        -*) echo "usage: $0 [--apply] [--vault-env FILE] [harness.env]" >&2; exit 2 ;;
        *) break ;;
    esac
    shift
done
ENV_FILE="${1:-$REPO/config/harness.env}"
[ -r "$ENV_FILE" ] || { echo "ERROR: cannot read $ENV_FILE; copy config/harness.env.example first" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
REGION="${SCW_REGION:?SCW_REGION is empty in $ENV_FILE}"
# scw reads SCW_REGION from the environment and warns that it is deprecated; every call here passes region= itself.
export -n SCW_REGION
: "${CLUSTER_NAME:?CLUSTER_NAME is empty in $ENV_FILE}"

log() { printf '[create-cluster] %s\n' "$*"; }
would() { log "$([ "$apply" -eq 1 ] && echo doing || echo would): $*"; }

# ---- read-only checks -------------------------------------------------------
check_tools() {
    local tool missing=0
    for tool in scw kubectl helm python3; do
        command -v "$tool" >/dev/null 2>&1 || { log "missing tool: $tool"; missing=1; }
    done
    [ "$missing" -eq 0 ] || exit 1
    scw account project list -o json >/dev/null \
        || { log "scw cannot list projects; run scw init"; exit 1; }
}

# The id of the cluster named exactly CLUSTER_NAME (scw name filters match substrings), or empty.
find_cluster() {
    scw k8s cluster list region="$REGION" name="$CLUSTER_NAME" -o json \
        | python3 -c 'import sys,json;n=sys.argv[1];print(next((c["id"] for c in json.load(sys.stdin) if c["name"]==n),""))' "$CLUSTER_NAME"
}

# Replace the line KEY= in the settings file with KEY=value.
write_setting() {
    python3 - "$ENV_FILE" "$1" "$2" <<'PY'
import re, sys
path, key, value = sys.argv[1:]
text = open(path).read()
line = f"{key}={value}"
text, count = re.subn(rf"^{key}=.*$", line, text, flags=re.M)
open(path, "w").write(text if count else text.rstrip("\n") + "\n" + line + "\n")
PY
    log "$1=$2 written to $ENV_FILE"
}

# The newest Kubernetes version the provider offers, unless the settings pin one.
k8s_version() {
    if [ -n "${CLUSTER_K8S_VERSION:-}" ]; then echo "$CLUSTER_K8S_VERSION"; return; fi
    scw k8s version list region="$REGION" -o json | python3 -c '
import json, sys
names = [v["name"] for v in json.load(sys.stdin)]
print(max(names, key=lambda name: tuple(int(part) for part in name.split("."))))'
}

# One line per pool: name role rank node_type zone min max disk shared_sg labels-and-taints args.
pool_lines() {
    python3 -m infra.cluster.pool_fallbacks --pools | python3 -c '
import json, sys
for spec in json.load(sys.stdin):
    args = [f"labels.{key}={value}" for key, value in spec["labels"]]
    args += [f"taints.{index}.key={key} taints.{index}.value={value} taints.{index}.effect={effect}"
             for index, (key, value, effect) in enumerate(spec["taints"])]
    print(spec["name"], spec["role"], spec["rank"], spec["node_type"], spec["zone"], spec["min_size"],
          spec["max_size"], spec["root_volume_size"], int(spec["shared_security_group"]), " ".join(args))
'
}

# ---- 1. the cluster ----------------------------------------------------------
create_cluster() {
    local first version name _role _rank type zone min max disk _sg args
    first=$(pool_lines | awk '$3==0 {print; exit}')
    read -r name _role _rank type zone min max disk _sg args <<<"$first"
    version=$(k8s_version)
    would "create cluster $CLUSTER_NAME (Kubernetes $version) with pool $name: $type in $zone, $min..$max, $disk root, expander priority"
    [ "$apply" -eq 1 ] || return 0
    # shellcheck disable=SC2086  # $args is a word list on purpose
    scw k8s cluster create region="$REGION" name="$CLUSTER_NAME" type=kapsule version="$version" \
        cni=cilium autoscaler-config.expander=priority \
        pools.0.name="$name" pools.0.node-type="$type" pools.0.zone="$zone" pools.0.size="$((min > 0 ? min : 1))" \
        pools.0.min-size="$min" pools.0.max-size="$max" pools.0.autoscaling=true pools.0.autohealing=true \
        pools.0.root-volume-size="$disk" $(printf '%s' "$args" | sed 's/\(^\| \)/\1pools.0./g') -w >/dev/null
}

record_cluster() {
    local cluster_id="$1" project_id
    project_id=$(scw k8s cluster get "$cluster_id" region="$REGION" -o json | python3 -c 'import sys,json;print(json.load(sys.stdin)["project_id"])')
    [ "${CLUSTER_ID:-}" = "$cluster_id" ] || write_setting CLUSTER_ID "$cluster_id"
    [ "${SCW_PROJECT_ID:-}" = "$project_id" ] || write_setting SCW_PROJECT_ID "$project_id"
    CLUSTER_ID="$cluster_id"
    SCW_PROJECT_ID="$project_id"
}

# ---- 2. the pools -------------------------------------------------------------
live_pools() { scw k8s pool list cluster-id="$CLUSTER_ID" region="$REGION" -o json; }

# Field $2 of the pool named $1 in the JSON on stdin, or empty.
pool_field() {
    python3 -c 'import sys,json;n,f=sys.argv[1],sys.argv[2];p=next((p for p in json.load(sys.stdin) if p["name"]==n),None);print((p or {}).get(f,""))' "$1" "$2"
}

create_pool() {  # name type zone size min max disk args [security-group-id=...]
    local name="$1" type="$2" zone="$3" size="$4" min="$5" max="$6" disk="$7" args="$8" sg="${9:-}"
    # shellcheck disable=SC2086  # $args and $sg are word lists on purpose
    scw k8s pool create cluster-id="$CLUSTER_ID" region="$REGION" name="$name" node-type="$type" zone="$zone" \
        size="$size" min-size="$min" max-size="$max" autoscaling=true autohealing=true \
        root-volume-size="$disk" $args $sg -w >/dev/null
}

ensure_preferred_pools() {
    local pools_json name role rank type zone min max disk sg args
    pools_json=$(live_pools)
    while read -r name role rank type zone min max disk sg args; do
        [ "$rank" -eq 0 ] || continue
        if [ -n "$(printf '%s' "$pools_json" | pool_field "$name" id)" ]; then
            log "$name: exists (role $role)"
            continue
        fi
        would "create $name: $type in $zone, $min..$max, $disk root, role $role"
        [ "$apply" -eq 0 ] || create_pool "$name" "$type" "$zone" "$min" "$min" "$max" "$disk" "$args"
    done < <(pool_lines)
}

ensure_fallback_pools() {
    local pools_json actions name role rank type zone min max disk same_sg args action sg preferred
    pools_json=$(live_pools)
    actions=$(printf '%s' "$pools_json" | python3 -m infra.cluster.pool_fallbacks --fallback-actions)
    while read -r name role rank type zone min max disk same_sg args; do
        [ "$rank" -gt 0 ] || continue
        action=$(printf '%s\n' "$actions" | awk -v n="$name" '$1==n {print $2}')
        case "$action" in
            ok) log "$name: exists"; continue ;;
            has-nodes) log "$name: root disk is not $disk but it has nodes; drain it, then rerun"; continue ;;
            create) ;;
            recreate)
                would "delete the empty $name (root disk is not $disk) and create it again"
                [ "$apply" -eq 0 ] || scw k8s pool delete "$(printf '%s' "$pools_json" | pool_field "$name" id)" region="$REGION" -w >/dev/null ;;
            *) log "$name: no action for it ('$action')"; exit 2 ;;
        esac
        sg=""
        if [ "$same_sg" -eq 1 ]; then
            preferred=$(pool_lines | awk -v r="$role" '$2==r && $3==0 {print $1}')
            sg="security-group-id=$(printf '%s' "$pools_json" | pool_field "$preferred" security_group_id)"
        fi
        would "create fallback $name: $type in $zone, 0..$max, $disk root, role $role, rank $rank"
        [ "$apply" -eq 1 ] || continue
        create_pool "$name" "$type" "$zone" 0 0 "$max" "$disk" "$args" "$sg" \
            || log "$name: the provider refused $type in $zone; read the error above, the other pools go on"
    done < <(pool_lines)
}

# ---- 3. the expander ------------------------------------------------------------
apply_priorities() {
    local configmap
    configmap=$(live_pools | python3 -m infra.cluster.pool_fallbacks --priorities)
    log "priority expander order:"
    printf '%s' "$configmap" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["priorities"])' | sed 's/^/  /'
    [ "$apply" -eq 0 ] || printf '%s' "$configmap" | kubectl apply -f - >/dev/null
}

ensure_priority_expander() {
    local expander
    expander=$(scw k8s cluster get "$CLUSTER_ID" region="$REGION" -o json \
        | python3 -c 'import sys,json;print(json.load(sys.stdin)["autoscaler_config"]["expander"])')
    [ "$expander" != "priority" ] || return 0
    would "switch the autoscaler expander from $expander to priority"
    [ "$apply" -eq 0 ] || scw k8s cluster update "$CLUSTER_ID" region="$REGION" autoscaler-config.expander=priority -w >/dev/null
}

# ---- 4. secrets and the foundation ------------------------------------------------
install_external_secrets() {
    would "install the External Secrets operator, chart $ESO_CHART_VERSION"
    [ "$apply" -eq 1 ] || return 0
    helm upgrade --install external-secrets external-secrets --repo https://charts.external-secrets.io \
        --version "$ESO_CHART_VERSION" --namespace external-secrets --create-namespace \
        --set installCRDs=true --wait >/dev/null
}

store_vault_reader() {
    local access secret
    [ -n "$vault_env" ] || { log "no --vault-env: the secret store's key (ESO_ACCESS_KEY) is not copied"; return 0; }
    access=$(set -a; . "$vault_env"; printf '%s' "${ESO_ACCESS_KEY:-}")
    secret=$(set -a; . "$vault_env"; printf '%s' "${ESO_SECRET_KEY:-}")
    [ -n "$access" ] && [ -n "$secret" ] || { log "ESO_ACCESS_KEY or ESO_SECRET_KEY is empty in $vault_env"; exit 1; }
    would "write Secret external-secrets/vault-reader from the vault copy"
    [ "$apply" -eq 1 ] || return 0
    kubectl -n external-secrets create secret generic vault-reader \
        --from-file=access-key=<(printf '%s' "$access") --from-file=secret-key=<(printf '%s' "$secret") \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null
}

# ---- run ----------------------------------------------------------------------------
check_tools
cluster_id=$(find_cluster)
if [ -n "${CLUSTER_ID:-}" ] && [ -n "$cluster_id" ] && [ "$CLUSTER_ID" != "$cluster_id" ]; then
    log "CLUSTER_ID=$CLUSTER_ID but the cluster named $CLUSTER_NAME is $cluster_id; fix the settings first"
    exit 1
fi
if [ -z "$cluster_id" ]; then
    create_cluster
    [ "$apply" -eq 1 ] || { log "plan only: the pools follow once the cluster exists (pass --apply)"; exit 0; }
    cluster_id=$(find_cluster)
else
    log "cluster $CLUSTER_NAME exists ($cluster_id): adopted"
fi
[ "$apply" -eq 0 ] || record_cluster "$cluster_id"
CLUSTER_ID="$cluster_id"

KUBECONFIG=$(mktemp)
export KUBECONFIG
trap 'rm -f "$KUBECONFIG"' EXIT
scw k8s kubeconfig get "$CLUSTER_ID" region="$REGION" > "$KUBECONFIG"

ensure_preferred_pools
ensure_fallback_pools
ensure_priority_expander
apply_priorities
install_external_secrets
store_vault_reader
if [ "$apply" -eq 1 ]; then
    bash "$REPO/infra/cluster/apply.sh" "$ENV_FILE"
else
    bash "$REPO/infra/cluster/apply.sh" --dry-run "$ENV_FILE"
fi
log "done. Check: kubectl get nodes -L ${POOL_ROLE_LABEL:-harness/role}"
