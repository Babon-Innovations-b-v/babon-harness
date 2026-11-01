#!/usr/bin/env bash
# provision.sh: create the media box, its firewall and Docker. Run on the laptop
# with `scw` configured (`scw init`). One-shot, not a deploy step.
#
# Idempotent by name: a second run finds the existing security group and
# server instead of making new ones. Reversible: `scw instance server terminate
# <id> with-ip=true with-block=true` and `scw instance security-group delete <id>`.
#
# FAILURE POLICY: fail-loud (`set -euo pipefail`). A partial failure stops and
# is read, never swallowed.
set -euo pipefail

ZONE="${MEDIA_ZONE:-fr-par-1}"
SG_NAME="${MEDIA_SG_NAME:-harness-media-sg}"
SERVER_NAME="${MEDIA_SERVER_NAME:-harness-media}"
INSTANCE_TYPE="${MEDIA_INSTANCE_TYPE:-PRO2-XS}"   # 4 vCPU, 16 GB: the recorder runs a browser
IMAGE="${MEDIA_IMAGE:-ubuntu_jammy}"
ROOT_VOLUME="${MEDIA_ROOT_VOLUME:-sbs:40GB}"      # images plus recording temp files

log() { printf '[media-provision] %s\n' "$*"; }
first_id() { python3 -c 'import sys,json;d=json.load(sys.stdin);print(d[0]["id"] if d else "")'; }

add_rule() {  # add_rule <sg> <protocol> <from> [<to>]
    local args=(security-group-id="$1" protocol="$2" direction=inbound action=accept
                ip-range=0.0.0.0/0 dest-port-from="$3" zone="$ZONE")
    [ -n "${4:-}" ] && args+=(dest-port-to="$4")
    scw instance security-group create-rule "${args[@]}" >/dev/null
}

# 1) The firewall: inbound DROP by default (a project's default security group
#    accepts everything, never use it), SSH, HTTPS, and the media UDP range.
sg_id=$(scw instance security-group list name="$SG_NAME" zone="$ZONE" -o json | first_id)
if [ -z "$sg_id" ]; then
    log "creating security group $SG_NAME"
    sg_id=$(scw instance security-group create name="$SG_NAME" \
              description="media box: SSH, HTTPS, Janus UDP 20000-40000" \
              inbound-default-policy=drop outbound-default-policy=accept zone="$ZONE" -o json \
              | python3 -c 'import sys,json;print(json.load(sys.stdin)["security_group"]["id"])')
    add_rule "$sg_id" TCP 22
    add_rule "$sg_id" TCP 80
    add_rule "$sg_id" TCP 443
    add_rule "$sg_id" UDP 20000 40000
    log "security group $sg_id created"
else
    log "security group $SG_NAME already exists: $sg_id"
fi

# 2) The server, on that firewall, with its own public IP.
server_id=$(scw instance server list name="$SERVER_NAME" zone="$ZONE" -o json | first_id)
if [ -z "$server_id" ]; then
    log "creating $SERVER_NAME ($INSTANCE_TYPE, $IMAGE)"
    server_id=$(scw instance server create type="$INSTANCE_TYPE" image="$IMAGE" name="$SERVER_NAME" \
                  ip=new security-group-id="$sg_id" root-volume="$ROOT_VOLUME" zone="$ZONE" -w -o json \
                  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
else
    log "$SERVER_NAME already exists: $server_id"
fi

ip=$(scw instance server get "$server_id" zone="$ZONE" -o json \
       | python3 -c 'import sys,json;s=json.load(sys.stdin);print((s.get("public_ip") or {}).get("address",""))')
[ -n "$ip" ] || { log "no public IP on $server_id"; exit 1; }

# 3) Docker. Scaleway injects the project's SSH keys, so root login works.
log "installing docker on $ip (skipped when present)"
ssh -o StrictHostKeyChecking=accept-new "root@$ip" \
    'command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh' >/dev/null
ssh "root@$ip" 'docker --version && docker compose version'

log "done. MEDIA_PUBLIC_IP=$ip"
log "next: DNS A records signaling.<domain> and recording.<domain> -> $ip, then deploy.sh"
