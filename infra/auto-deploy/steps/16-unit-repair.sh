#!/bin/bash
# Step 16: re-copy an installed unit whose `python3 -m <module>` no longer exists
# in the clone, because this commit moved the module.
#
# Step 80 reinstalls units, but only at the END of a cycle and only on a green
# gate. In between, a timer whose unit still names the old module fails every
# time it fires. This repairs only what is ALREADY broken: it installs, removes
# and enables nothing. Below 15 (or it repairs to a stale tree), above 20 (or it
# is skipped on the early-exit cycles, which are most of them).
#
# FAILURE POLICY: best-effort, returns 0, never blocks a deploy.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

UNIT_REPAIR_SYSTEM_DIR="${UNIT_REPAIR_SYSTEM_DIR:-/etc/systemd/system}"
UNIT_REPAIR_SUDO="${UNIT_REPAIR_SUDO-sudo -n}"
UNIT_MANIFEST="$STATE_DIR/installed-units"

# The module a unit runs with `python3 -m`, when the clone no longer holds it.
_unit_repair_module_missing() {
    local unit_file="$1" module path
    module="$(grep -m1 -oE '^ExecStart=.*python3?[[:space:]]+-m[[:space:]]+[A-Za-z0-9_.]+' "$unit_file" 2>/dev/null \
        | grep -oE '[A-Za-z0-9_.]+$')"
    [ -n "$module" ] || return 0
    path="${module//./\/}"
    [ -d "$REPO/$path" ] || [ -f "$REPO/$path.py" ] || printf '%s' "$module"
    return 0
}

_unit_repair_run() {
    local name src installed missing repaired=0 rendered
    [ -r "$UNIT_MANIFEST" ] || return 0
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        installed="$UNIT_REPAIR_SYSTEM_DIR/$name"
        [ -f "$installed" ] || continue
        missing="$(_unit_repair_module_missing "$installed")"
        [ -n "$missing" ] || continue
        src="$(find "$REPO" -path "$REPO/.claude" -prune -o -path '*/systemd/*' -name "$name" -print 2>/dev/null | head -1)"
        if [ -z "$src" ]; then
            log "[unit-repair] $name names $missing, which the clone does not hold, and the clone has no replacement; left for step 80"
            continue
        fi
        rendered="$(harness_render_unit "$src")"
        [ "$rendered" = "$(cat "$installed")" ] && continue
        if printf '%s\n' "$rendered" | $UNIT_REPAIR_SUDO tee "$installed" > /dev/null 2>&1; then
            repaired=$(( repaired + 1 ))
            log "[unit-repair] $name named $missing, which this commit moved; re-copied from the clone"
        fi
    done < "$UNIT_MANIFEST"
    if [ "$repaired" -gt 0 ]; then
        $UNIT_REPAIR_SUDO systemctl daemon-reload 2>/dev/null || true
    fi
    return 0
}

if [ "${UNIT_REPAIR_ENABLED:-1}" = "1" ]; then
    _unit_repair_run || log "[unit-repair] aborted unexpectedly (deploy unaffected)"
fi
