#!/bin/bash
# Step 80: install the repository's systemd units, and remove the ones it no
# longer has.
#
# Every `*.service` and `*.timer` in a `systemd/` directory one level below
# apps/, infra/ or lib/ (apps/<name>/systemd/, infra/<name>/systemd/) is
# rendered for this box (harness_render_unit: HARNESS_ROOT and the deploy user)
# and copied into /etc/systemd/system when it differs. Timers are enabled and
# started; a service with an [Install] section is enabled.
#
# "Ours" is what this step installed, recorded in $STATE_DIR/installed-units,
# never a name pattern: a unit that was in that list and is no longer in the
# repository is disabled and removed, and a unit the owner installed by hand is
# never touched.
#
# Read from the verified tree, never the clone, and only on a green gate: a
# unit is code that runs on a timer, so an unverified one does not get
# installed. Timers found disabled are re-enabled every cycle, so `systemctl
# disable` is undone within two minutes; switch a job off in the repository.
#
# FAILURE POLICY: best-effort. A unit that cannot be installed is logged and the
# rest go on; nothing here blocks a deploy. An empty unit set aborts the sweep,
# because it would read every installed unit as an orphan.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"
UNIT_SUDO="${UNIT_SUDO-sudo -n}"
UNIT_MANIFEST="$STATE_DIR/installed-units"

_repo_units() {
    find "$1"/apps "$1"/infra "$1"/lib -mindepth 3 -maxdepth 3 -type f -path '*/systemd/*' \
        \( -name '*.service' -o -name '*.timer' \) 2>/dev/null | sort
}

_install_units() {
    local tree="${VERIFIED_TREE:-}" src name rendered changed=0 units=() names=() installed=()
    local enabled active
    if [ "${gate_red:-0}" -ne 0 ] || [ -z "$tree" ] || [ ! -d "$tree" ]; then
        log "[units] no verified tree this cycle; units are left as they are"
        return 0
    fi
    mapfile -t units < <(_repo_units "$tree")
    if [ "${#units[@]}" -eq 0 ]; then
        log "[units] the tree carries no units at all; refusing to sweep (it would remove every one)"
        return 0
    fi
    for src in "${units[@]}"; do
        name="$(basename "$src")"
        names+=("$name")
        rendered="$(harness_render_unit "$src")"
        if [ -f "$UNIT_DIR/$name" ] && [ "$rendered" = "$(cat "$UNIT_DIR/$name" 2>/dev/null)" ]; then
            continue
        fi
        if printf '%s\n' "$rendered" | $UNIT_SUDO tee "$UNIT_DIR/$name" > /dev/null 2>>"$LOG"; then
            installed+=("$name")
            changed=1
        else
            log "[units] could not install $name"
        fi
    done

    # Remove what this step installed earlier and the repository no longer has.
    if [ -r "$UNIT_MANIFEST" ]; then
        while IFS= read -r name; do
            [ -n "$name" ] || continue
            case " ${names[*]} " in *" $name "*) continue ;; esac
            $UNIT_SUDO systemctl disable --now "$name" >> "$LOG" 2>&1 || true
            $UNIT_SUDO rm -f "$UNIT_DIR/$name" >> "$LOG" 2>&1 || true
            changed=1
            log "[units] removed $name: the repository no longer has it"
        done < "$UNIT_MANIFEST"
    fi
    printf '%s\n' "${names[@]}" > "$UNIT_MANIFEST.tmp" 2>/dev/null && mv -f "$UNIT_MANIFEST.tmp" "$UNIT_MANIFEST" 2>/dev/null || true

    [ "$changed" -eq 1 ] && { $UNIT_SUDO systemctl daemon-reload >> "$LOG" 2>&1 || true; }
    [ "${#installed[@]}" -gt 0 ] && log "[units] installed or refreshed: ${installed[*]}"

    for name in "${names[@]}"; do
        case "$name" in
            *@.service|*@.timer) continue ;;
            *.timer)
                enabled=$(systemctl is-enabled "$name" 2>/dev/null || true)
                active=$(systemctl is-active "$name" 2>/dev/null || true)
                if [ "$enabled" != "enabled" ] || [ "$active" != "active" ]; then
                    $UNIT_SUDO systemctl enable --now "$name" >> "$LOG" 2>&1 \
                        && log "[units] enabled and started $name" \
                        || log "[units] could not enable $name"
                fi ;;
            *.service)
                case " ${installed[*]} " in *" $name "*) ;; *) continue ;; esac
                if grep -q '^\[Install\]' "$UNIT_DIR/$name" 2>/dev/null; then
                    $UNIT_SUDO systemctl enable "$name" >> "$LOG" 2>&1 || true
                    # A long-running service picks up its new unit by restarting.
                    if grep -q '^Type=simple' "$UNIT_DIR/$name" 2>/dev/null \
                            || ! grep -q '^Type=' "$UNIT_DIR/$name" 2>/dev/null; then
                        $UNIT_SUDO systemctl restart "$name" >> "$LOG" 2>&1 || true
                    fi
                fi ;;
        esac
    done
    return 0
}

_install_units || log "[units] step aborted unexpectedly (deploy unaffected)"

# The webhook reads its HMAC secret from the vault cache at start, so a new
# vault version restarts it.
if [ "${ENV_CHANGED:-false}" = true ]; then
    $UNIT_SUDO systemctl try-restart harness-webhook.service >> "$LOG" 2>&1 || true
fi
