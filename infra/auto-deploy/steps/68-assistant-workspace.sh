#!/bin/bash
# Step 68: render the assistant's workspace (its doctrine, the reader profile
# and the gateway configuration) from the repository onto the server.
#
# The rendering itself belongs to the assistant and lives with it, in
# apps/assistant/workspace/apply.sh; this step only decides WHEN: once per
# deployed commit that touched apps/assistant, or when the vault changed, and
# never on a red gate. It runs from the verified tree, so what is rendered is
# what the gate passed.
#
# FAILURE POLICY: best-effort. A render that fails leaves yesterday's workspace
# in place, logs it and alerts once per commit; it never blocks a deploy.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

_assistant_workspace() {
    local tree="${VERIFIED_TREE:-$REPO}" apply
    apply="$tree/apps/assistant/workspace/apply.sh"
    [ "${gate_red:-0}" -eq 0 ] || return 0
    if [ "${assistant_workspace_changed:-false}" != true ] && [ "${ENV_CHANGED:-false}" != true ]; then
        return 0
    fi
    if [ ! -f "$apply" ]; then
        log "[assistant] $apply is not in this tree; no workspace to render"
        return 0
    fi
    if HARNESS_ROOT="$HARNESS_ROOT" HARNESS_ENV_FILE="$HARNESS_ENV_FILE" \
            bash "$apply" >> "$LOG" 2>&1; then
        log "[assistant] workspace rendered from ${NEW_SHA:0:8}"
    else
        log "[assistant] apply.sh failed; the previous workspace stays in place"
        fire_alert_once "assistant-workspace" "$NEW_SHA" \
            "auto-deploy: the assistant's workspace did not render" \
            "apps/assistant/workspace/apply.sh failed at ${NEW_SHA:0:12}, so the assistant keeps the workspace it had. Log: $LOG"
    fi
    return 0
}

_assistant_workspace || true
