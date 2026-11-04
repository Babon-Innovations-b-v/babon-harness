#!/usr/bin/env bash
# ip-reattach.sh: keep the media public IP on the one node of the media pool
# role. Run every minute by the media-ip-reattach CronJob (./ip-reattach.yaml)
# on alpine/k8s (kubectl, curl, python3, bash).
#
# WHY: the provider reserves no public IP per pool. A media node replaced by
# autoheal, an upgrade or a fallback pool is a new server with a new dynamic
# address, while DNS (signaling.DOMAIN, recording.DOMAIN) and Janus's
# --nat-1-1 name MEDIA_PUBLIC_IP. Until the IP is back, calls carry no media.
#
# BEHAVIOUR
#   - exactly one Ready node carries MEDIA_NODE_LABEL, else exit 1 (zero:
#     nothing to attach to; two or more: refuse to guess). A NotReady one is
#     not counted: a dead node's Node object can linger beside its
#     replacement and must not block the move.
#   - its providerID must be scaleway://instance/<MEDIA_ZONE>/<server-id>,
#     else exit 1: a flexible IP is zonal and cannot cross zones.
#   - IP already on that server: say so and exit 0, nothing written.
#   - otherwise attach it (PATCH the IP's server), read it back, and exit 1
#     unless the IP now names that server.
#
# FAILURE POLICY: fail loud (set -euo pipefail). A failed run is a failed Job;
# the next minute's run retries. Nothing is swallowed.
set -euo pipefail

MEDIA_PUBLIC_IP="${MEDIA_PUBLIC_IP:?MEDIA_PUBLIC_IP must name the public IP}"
MEDIA_NODE_LABEL="${MEDIA_NODE_LABEL:?MEDIA_NODE_LABEL must name the media role label, key=value}"
MEDIA_ZONE="${MEDIA_ZONE:?MEDIA_ZONE must name the IP zone}"
MEDIA_IP_SECRET_KEY="${MEDIA_IP_SECRET_KEY:?MEDIA_IP_SECRET_KEY must hold an API key allowed to attach the IP}"
SCW_API_URL="${SCW_API_URL:-https://api.scaleway.com}"
ip_url="$SCW_API_URL/instance/v1/zones/$MEDIA_ZONE/ips/$MEDIA_PUBLIC_IP"

log() { printf '[media-ip-reattach] %s\n' "$*"; }

# One "name providerID" line per labelled node whose Ready condition is True.
nodes=$(kubectl get nodes -l "$MEDIA_NODE_LABEL" \
          -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.providerID}{" "}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' \
        | awk '$3 == "True" {print $1, $2}')
count=$(printf '%s' "$nodes" | grep -c . || true)
if [ "$count" -ne 1 ]; then
    log "expected exactly 1 Ready node with label $MEDIA_NODE_LABEL, found $count; not attaching"
    exit 1
fi

node_name=${nodes%% *}
provider_id=$(printf '%s' "${nodes#* }" | tr -d '\n')
prefix="scaleway://instance/$MEDIA_ZONE/"
case "$provider_id" in
    "$prefix"?*) server_id=${provider_id#"$prefix"} ;;
    *)
        log "node $node_name providerID '$provider_id' is not a server in $MEDIA_ZONE; not attaching"
        exit 1
        ;;
esac

# The server the IP is attached to now, or empty when it is detached.
current_server() {
    curl -fsS -H "X-Auth-Token: $MEDIA_IP_SECRET_KEY" "$ip_url" \
      | python3 -c 'import sys,json;print(((json.load(sys.stdin).get("ip") or {}).get("server") or {}).get("id") or "")'
}

before=$(current_server)
if [ "$before" = "$server_id" ]; then
    log "$MEDIA_PUBLIC_IP already on $node_name ($server_id)"
    exit 0
fi

log "attaching $MEDIA_PUBLIC_IP to $node_name ($server_id), was on '${before:-nothing}'"
curl -fsS -X PATCH -H "X-Auth-Token: $MEDIA_IP_SECRET_KEY" -H "Content-Type: application/json" \
    -d "{\"server\": \"$server_id\"}" "$ip_url" >/dev/null

after=$(current_server)
if [ "$after" != "$server_id" ]; then
    log "attach returned but $MEDIA_PUBLIC_IP is on '${after:-nothing}', not $server_id"
    exit 1
fi
log "$MEDIA_PUBLIC_IP now on $node_name ($server_id)"
