#!/usr/bin/env bash
# apply.sh: put the assistant's own judgment in front of the OpenClaw gateway.
#
# WHAT. The gateway builds its system prompt from four bootstrap files in its
# workspace: AGENTS.md, SOUL.md, USER.md and IDENTITY.md. This renders all four
# from the LIVE modules in the `assistant` container (which holds the
# principles and person rules in its state database), writes them into the
# gateway's workspace volume, applies the config fragment
# (`gateway_config_patch.json`, filled by `fragment.py`) and declares the two
# scheduled reports (`gateway_automations.json`, through
# `apply_automations.py`).
#
# WHO CALLS IT. The deploy loop's step 68, from the repository root, after the
# containers are up and only when the verification gate is green: both halves
# put repository content in front of a model that talks to people, and stale
# prose is the cheaper failure. It also runs by hand:
#
#   COMPOSE="docker compose --env-file /opt/harness/harness.env" \
#       apps/assistant/workspace/apply.sh
#
# Environment:
#   COMPOSE       the compose command, default `docker compose`
#   GATE_RED      1 = do nothing (the caller's verdict)
#   TEXTFILE_DIR  node-exporter textfile directory for the outcome gauge;
#                 unset = no gauge
#
# FAILURE POLICY: Tier-2 best-effort, and it never fails the caller: it exits 0
# and prints one outcome word. Nothing is written until all four files have
# arrived non-empty, so a half-rendered prompt never reaches the model.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
read -r -a compose <<< "${COMPOSE:-docker compose}"
workspace_dir="/home/node/.openclaw/workspace"
files="AGENTS.md SOUL.md USER.md IDENTITY.md"
outcome=""
changed=0
staged="$(mktemp -d -t assistant-workspace-XXXX)"
trap 'rm -rf "$staged"' EXIT

log() { echo "[assistant-workspace] $*"; }

render() {
    # One call, so the four files, the fragment and the reports come from one
    # render and cannot straddle a restart.
    timeout 120 "${compose[@]}" exec -T assistant \
        python -m apps.assistant.workspace > "$staged/render.json" 2> "$staged/render.err"
}

stage() {
    # Split the render into one file per name; non-zero unless every name
    # arrived with content.
    python3 - "$staged" "$files" <<'PY'
import json, pathlib, sys
staged = pathlib.Path(sys.argv[1])
wanted = sys.argv[2].split()
try:
    rendered = json.loads((staged / "render.json").read_text(encoding="utf-8"))
except Exception:
    sys.exit(1)
texts = rendered.get("files") or {}
if sorted(texts) != sorted(wanted):
    sys.exit(1)
for name in wanted:
    text = texts[name]
    if not isinstance(text, str) or not text.strip():
        sys.exit(1)
    (staged / name).write_text(text, encoding="utf-8")
(staged / "gateway_config_patch.json").write_text(json.dumps(rendered["config_patch"], indent=2), encoding="utf-8")
(staged / "gateway_automations.json").write_text(json.dumps(rendered["automations"], indent=2), encoding="utf-8")
PY
}

install_files() {
    # Written by the gateway's own user inside its container, then moved, so
    # the model never reads a half-written prompt and every file is readable
    # by the uid the gateway runs as.
    local name before after
    for name in $files; do
        before=$("${compose[@]}" exec -T gateway sh -c "sha256sum $workspace_dir/$name 2>/dev/null" | cut -d' ' -f1)
        "${compose[@]}" exec -T gateway sh -c \
            "cat > $workspace_dir/.$name.new && chmod 644 $workspace_dir/.$name.new && mv $workspace_dir/.$name.new $workspace_dir/$name" \
            < "$staged/$name" || return 1
        after=$("${compose[@]}" exec -T gateway sh -c "sha256sum $workspace_dir/$name" | cut -d' ' -f1)
        if [ "$before" != "$after" ]; then
            changed=$((changed + 1))
            log "$name changed"
        fi
    done
}

apply_config() {
    # Dry run first, always: a fragment written against a schema this gateway
    # has moved past is refused before it can touch the config a person talks
    # to the assistant through. Upstream validates before it writes and keeps
    # the last good config, so a refused patch leaves the running one intact.
    if ! timeout 60 "${compose[@]}" exec -T gateway openclaw config patch --stdin --dry-run \
            < "$staged/gateway_config_patch.json"; then
        log "WARN: the config fragment does not validate against this gateway; nothing applied"
        return 1
    fi
    timeout 60 "${compose[@]}" exec -T gateway openclaw config patch --stdin \
        < "$staged/gateway_config_patch.json"
}

apply_automations() {
    # Re-declared every run, no marker: upstream treats the declaration key as
    # the job's identity, so an unchanged job is a no-op, and a marker would
    # hide a job somebody removed by hand.
    "${compose[@]}" cp "$here/apply_automations.py" gateway:/tmp/apply_automations.py >/dev/null \
        && "${compose[@]}" cp "$staged/gateway_automations.json" gateway:/tmp/gateway_automations.json >/dev/null \
        && timeout 120 "${compose[@]}" exec -T gateway python3 /tmp/apply_automations.py
}

report() {
    # 1 synced, 0 tried and failed, -1 not attempted. Alert on the value, never
    # on the age: this only runs on a deploying cycle.
    [ -n "${TEXTFILE_DIR:-}" ] && [ -d "$TEXTFILE_DIR" ] || return 0
    local value=0
    case "$outcome" in
        synced) value=1 ;;
        gate_red|"") value=-1 ;;
    esac
    {
        echo "# HELP harness_assistant_workspace_synced Did this deploy put the assistant's current prompt files and config in front of the gateway: 1 yes, 0 tried and did not, -1 not attempted."
        echo "# TYPE harness_assistant_workspace_synced gauge"
        echo "harness_assistant_workspace_synced $value"
    } > "$TEXTFILE_DIR/.assistant_workspace.prom.$$" \
        && mv "$TEXTFILE_DIR/.assistant_workspace.prom.$$" "$TEXTFILE_DIR/assistant_workspace.prom"
}

main() {
    if [ "${GATE_RED:-0}" = "1" ]; then
        outcome="gate_red"
        log "verification gate red: the gateway keeps the prose it has"
        return
    fi
    if ! render || [ ! -s "$staged/render.json" ]; then
        if grep -q WorkspaceTooLong "$staged/render.err" 2>/dev/null; then outcome="too_long"; else outcome="render_failed"; fi
        log "WARN: the assistant rendered nothing ($outcome): $(tail -1 "$staged/render.err" 2>/dev/null)"
        return
    fi
    if ! stage; then
        outcome="incomplete_render"
        log "WARN: the render did not carry all of $files; nothing written"
        return
    fi
    if ! install_files; then
        outcome="write_failed"
        log "WARN: could not write into the gateway's workspace; some files may be older than others"
        return
    fi
    local config_ok=1 automations_ok=1
    apply_config || config_ok=0
    apply_automations || automations_ok=0
    if [ "$config_ok" -eq 0 ]; then
        outcome="config_refused"
    elif [ "$automations_ok" -eq 0 ]; then
        outcome="automations_refused"
    else
        outcome="synced"
    fi
    log "$changed of 4 files changed ($outcome)"
}

main
report
echo "$outcome"
exit 0
