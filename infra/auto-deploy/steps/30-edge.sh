#!/bin/bash
# Step 30: validate the commit's Caddyfile before anything ships it.
#
# Caddy is the front door: one broken Caddyfile takes HTTPS down for every site
# at once. infra/caddy/compose.yml mounts infra/caddy from the tree the stack
# runs from, so a Caddyfile reaches Caddy when step 50 recreates the caddy
# service from the verified tree. This step asks the RUNNING Caddy to validate
# the commit's file first (`caddy validate`, read from stdin, so nothing on disk
# changes), and a file that does not parse sets `caddy_invalid=1`: step 50 then
# leaves Caddy on its old config and records the failure as the commit's, which
# the eject can hand back.
#
# FAILURE POLICY: best-effort. No running Caddy (a first install) validates
# nothing, and the boot check in step 50 is the net: a Caddy that will not start
# on the new file is rolled back to the old one.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

caddy_invalid=0

caddy_validate() {
    local cid
    cid=$(docker ps -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
        --filter "label=com.docker.compose.service=caddy" 2>/dev/null | head -1)
    if [ -z "$cid" ]; then
        log "[caddy] no running caddy container in project $COMPOSE_PROJECT; the boot check in step 50 is the net"
        return 0
    fi
    if git -C "$REPO" show "$NEW_SHA:infra/caddy/Caddyfile" 2>/dev/null \
            | docker exec -i "$cid" caddy validate --adapter caddyfile --config /dev/stdin >> "$LOG" 2>&1; then
        log "[caddy] the Caddyfile at ${NEW_SHA:0:8} validates"
        return 0
    fi
    caddy_invalid=1
    log "[caddy] validate FAILED at ${NEW_SHA:0:8}; Caddy keeps its current config"
    fire_alert_once "caddy-invalid" "$NEW_SHA" \
        "auto-deploy: the Caddyfile does not validate" \
        "infra/caddy/Caddyfile at ${NEW_SHA:0:12} does not parse, so it was not loaded. The previous config is still serving. Fix it and push again. Log: $LOG"
    return 0
}

if [ "${caddy_changed:-false}" = true ]; then
    caddy_validate || true
fi
