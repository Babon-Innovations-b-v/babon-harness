#!/bin/bash
# Step 20: choose the ONE commit this cycle ships, diff it against the bookmark,
# set what it touches, and decide how much of the suite the gate runs.
#
# ONE COMMIT PER CYCLE. The commit is the TRUSTED HEAD when there is one: the
# newest commit up to which every commit past the bookmark has its own verdict
# from the verifying lane (`python3 -m infra.deploy_loop trusted-head`, whose
# docstring carries the rule); step 40 then runs no pytest for it. Otherwise
# the newest one past the bookmark that already holds a green verdict for its
# exact tree, and otherwise the NEXT commit after the bookmark.
# Never HEAD, never a batch: a red on a batch names no commit, so nothing could
# be handed back for it. A jumped range is gated at the union scope and reverts
# nothing (`not_isolated`).
#
# Publishes, once, for steps 40, 88 and 90: OLD_SHA, NEW_SHA, CHANGED,
# queue_depth (commits waiting behind NEW_SHA), bookmark_depth (commits past the
# bookmark: the freeze), build_head_source, build_head_jumped,
# gate_range_isolated, and the gate's scope variables.
#
# FAILURE POLICY: fail loud (exit 1) when the clone has no HEAD. The scope
# selector fails toward MORE testing: any answer it cannot give is `full`.
#
# Sourced by auto-deploy.sh; shares its shell. Not executable on its own.

mkdir -p "$STATE_DIR"
cd "$REPO" || { log "FATAL: cannot cd $REPO"; exit 1; }

OLD_SHA=$(cat "$LAST_SHA_FILE" 2>/dev/null || echo "")
HEAD_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
if [ -z "$HEAD_SHA" ]; then
    log "FATAL: cannot resolve HEAD"
    exit 1
fi

# A bookmark that is not an ancestor of HEAD (a force-push, a restored clone) is
# treated as no bookmark: the tip ships, rather than a commit from the middle of
# a history nobody is on.
bookmark_usable=0
if [ -n "$OLD_SHA" ] && git cat-file -e "${OLD_SHA}^{commit}" 2>/dev/null; then
    if git merge-base --is-ancestor "$OLD_SHA" "$HEAD_SHA" 2>/dev/null; then
        bookmark_usable=1
    else
        log "the bookmark ${OLD_SHA:0:8} is not an ancestor of HEAD ${HEAD_SHA:0:8}; taking the tip"
        OLD_SHA=""
    fi
else
    OLD_SHA=""
fi

# The newest commit past the bookmark with a green verdict for its CURRENT tree.
# While build-head-red names this bookmark, the commits inside the range that
# went red are skipped; after BUILD_HEAD_RED_GIVE_UP range reds against one
# bookmark the jump is given up and the single next commit is gated, and the
# marker lapses after BUILD_HEAD_RED_TTL, so it can never become a permanent ban
# exactly where the bookmark cannot move by itself.
_verified_build_head() {
    local candidates candidate tree_now
    local held_bookmark="" held_head="" held_at="" held_reason="" held_count="" held_skip=""
    local r_sha r_verdict r_scope r_at r_reason r_tree
    [ "${BUILD_HEAD_FOLLOWS_VERDICTS:-1}" = "1" ] || return 1
    [ -n "$OLD_SHA" ] || return 1
    if [ -r "$BUILD_HEAD_RED_FILE" ]; then
        read -r held_bookmark held_head held_at held_reason held_count < "$BUILD_HEAD_RED_FILE" || true
    fi
    : "$held_reason"
    case "$held_at" in "" | *[!0-9]*) held_at=0 ;; esac
    case "$held_count" in "" | *[!0-9]*) held_count=1 ;; esac
    if [ "$held_bookmark" = "$OLD_SHA" ] && [ -n "$held_head" ] \
            && [ $(( $(date +%s) - held_at )) -lt "${BUILD_HEAD_RED_TTL:-3600}" ] \
            && git cat-file -e "${held_head}^{commit}" 2>/dev/null; then
        [ "$held_count" -ge "${BUILD_HEAD_RED_GIVE_UP:-2}" ] && return 1
        held_skip="$held_head"
    fi
    # The 50 nearest the bookmark, newest first, so a jump cannot outrun the
    # status doors' own 50-commit window.
    candidates=$(git rev-list --first-parent "${OLD_SHA}..${HEAD_SHA}" 2>/dev/null | tail -50)
    for candidate in $candidates; do
        [ -r "$GATE_VERDICT_DIR/$candidate" ] || continue
        r_sha=""; r_verdict=""; r_scope=""; r_at=""; r_reason=""; r_tree=""
        read -r r_sha r_verdict r_scope r_at r_reason r_tree < "$GATE_VERDICT_DIR/$candidate" 2>/dev/null || true
        [ "$r_sha" = "$candidate" ] && [ "$r_verdict" = "green" ] && [ -n "$r_tree" ] || continue
        # A batch member was verified on a later commit's tree, never its own.
        case "$r_reason" in batch:*) continue ;; esac
        tree_now=$(git rev-parse "${candidate}^{tree}" 2>/dev/null || echo "")
        [ "$r_tree" = "$tree_now" ] || continue
        if [ -n "$held_skip" ] && git merge-base --is-ancestor "$candidate" "$held_skip" 2>/dev/null; then
            continue
        fi
        printf '%s' "$candidate"
        return 0
    done
    return 1
}

build_head_source="next"
if [ -n "${RELEASE_FORCE:-}" ]; then
    NEW_SHA="$HEAD_SHA"
    build_head_source="release_force"
elif [ "$bookmark_usable" = "1" ]; then
    NEW_SHA=$(_verified_build_head) || NEW_SHA=""
    if [ -n "$NEW_SHA" ]; then
        build_head_source="verified"
    else
        NEW_SHA=$(git rev-list --reverse --first-parent "${OLD_SHA}..${HEAD_SHA}" 2>/dev/null | head -1)
        [ -n "$NEW_SHA" ] || NEW_SHA="$HEAD_SHA"
    fi
else
    NEW_SHA="$HEAD_SHA"
    build_head_source="no_baseline"
fi

# THE NARROWING LICENCE, read once for both its readers: the trust walk below
# and the scope selection further down. Prints why narrowing is NOT licensed,
# nothing when it is: a proven selection miss, or no green unselected audit in
# 48 hours (a stamp dated in the future counts as none).
_narrowing_unlicensed_why() {
    local now="$1" at age
    if [ -f "$STATE_DIR/gate-selection-miss" ]; then
        echo "a nightly audit proved a selection miss; full gate until $STATE_DIR/gate-selection-miss is removed by hand"
        return 0
    fi
    at=$(cat "$STATE_DIR/last-full-audit-ok" 2>/dev/null || echo 0)
    case "$at" in ''|*[!0-9]*) at=0 ;; esac
    age=$(( now - at ))
    if [ "$at" -eq 0 ] || [ "$age" -gt 172800 ] || [ "$age" -lt 0 ]; then
        echo "no successful unselected audit in 48h; full gate until the unselected audit goes green"
    fi
    return 0
}
narrowing_unlicensed="$(_narrowing_unlicensed_why "$(date +%s)")"

# The trust walk. BUILD_HEAD_TRUSTS_LANE=0 is shadow: logged, not acted on.
trust_head=""
trust_reason=""
trust_stop=""
if [ "$bookmark_usable" = "1" ] && [ -z "${RELEASE_FORCE:-}" ] && [ "$OLD_SHA" != "$HEAD_SHA" ]; then
    read -r trust_head trust_reason trust_stop < <( cd "$REPO" && timeout 300 \
        python3 -m infra.deploy_loop trusted-head --repo "$REPO" \
        --bookmark "$OLD_SHA" --head "$HEAD_SHA" --verdicts "$GATE_VERDICT_DIR" \
        --scope-cache "$STATE_DIR/trust-scope" ${narrowing_unlicensed:+--unlicensed} 2>>"$LOG" ) || true
    [ "$trust_head" = "-" ] && trust_head=""
    [ "$trust_stop" = "-" ] && trust_stop=""
    log "[trust] the lane's verdicts alone ship ${trust_head:-nothing} (${trust_reason:-no_answer}${trust_stop:+ at ${trust_stop:0:8}})"
    if [ "${BUILD_HEAD_TRUSTS_LANE:-1}" = "1" ] && [ -n "$trust_head" ]; then
        NEW_SHA="$trust_head"
        build_head_source="trusted"
    fi
fi

queue_depth=$(git rev-list --count --first-parent "${NEW_SHA}..${HEAD_SHA}" 2>/dev/null || echo 0)
case "$queue_depth" in "" | *[!0-9]*) queue_depth=0 ;; esac
bookmark_depth=0
if [ -n "$OLD_SHA" ]; then
    bookmark_depth=$(git rev-list --count --first-parent "${OLD_SHA}..${HEAD_SHA}" 2>/dev/null || echo 0)
    case "$bookmark_depth" in "" | *[!0-9]*) bookmark_depth=0 ;; esac
fi
build_head_jumped=0
if [ -n "$OLD_SHA" ] && [ "$OLD_SHA" != "$NEW_SHA" ]; then
    build_head_jumped=$(git rev-list --count --first-parent "${OLD_SHA}..${NEW_SHA}" 2>/dev/null || echo 1)
    case "$build_head_jumped" in "" | *[!0-9]*) build_head_jumped=1 ;; esac
    build_head_jumped=$(( build_head_jumped - 1 ))
fi

# Isolated means the range is exactly one commit sitting on the bookmark: the
# only shape whose red names a commit, and so the only one the eject may act on.
gate_range_isolated=0
if [ -n "$OLD_SHA" ] && [ -z "${RELEASE_FORCE:-}" ] \
        && [ "$(git rev-parse --verify --quiet "${NEW_SHA}^" 2>/dev/null)" = "$OLD_SHA" ]; then
    gate_range_isolated=1
fi

if [ "$OLD_SHA" = "$NEW_SHA" ] && [ -z "${RELEASE_FORCE:-}" ] && [ "$ENV_CHANGED" != true ]; then
    log "no change since $NEW_SHA"
    exit 0
fi
log "change detected: ${OLD_SHA:0:8} -> ${NEW_SHA:0:8} (source $build_head_source, $queue_depth waiting behind it)"

if [ -n "${RELEASE_FORCE:-}" ] || [ -z "$OLD_SHA" ]; then
    CHANGED=$(git ls-tree -r --name-only "$NEW_SHA")
    log "no usable prior commit (or a forced release); treating every path as changed"
else
    CHANGED=$(git -c core.quotePath=false diff --name-only --no-renames "$OLD_SHA" "$NEW_SHA")
fi

# ── What the commit touches ─────────────────────────────────────────────────
# Which compose services to rebuild is decided in step 50, from the exported
# tree. Here only whether anything deployable moved at all, so step 40 can tell
# a documents-only commit from one that ships something.
caddy_changed=false
manifests_changed=false
assistant_workspace_changed=false
vm_runs_changed_code=false
compose_changed=false
while IFS= read -r path; do
    [ -n "$path" ] || continue
    case "$path" in
        infra/caddy/*) caddy_changed=true ;;
    esac
    case "$path" in
        infra/k8s/*|infra/cluster/*|infra/caddy/*) manifests_changed=true ;;
    esac
    case "$path" in
        apps/assistant/*) assistant_workspace_changed=true ;;
    esac
    case "$path" in
        *.md) ;;
        *.py|*.sh) vm_runs_changed_code=true ;;
    esac
    case "$path" in
        *.md) ;;
        docker-compose.yml|*/compose.yml|*/Dockerfile|*/Dockerfile.*|apps/*|infra/*|lib/*|design/*)
            compose_changed=true ;;
    esac
done <<< "$CHANGED"
log "touches: compose=$compose_changed caddy=$caddy_changed manifests=$manifests_changed assistant=$assistant_workspace_changed code=$vm_runs_changed_code env=$ENV_CHANGED"

# ── The gate's scope ────────────────────────────────────────────────────────
# The ONE place it is decided. Narrowing is licensed only while the nightly
# unselected audit (tools/gate_scope/audit_full_run.sh) is alive: no green audit
# in 48 hours, or one proven miss, pins the gate to the full suite.
gate_scope="full"
gate_paths_file="$STATE_DIR/gate-selected-paths"
gate_scope_json="$STATE_DIR/gate-scope.json"
: > "$gate_paths_file"
printf '%s\n' "$CHANGED" > "$STATE_DIR/gate-changed-paths"

env_only=false
if [ "$OLD_SHA" = "$NEW_SHA" ]; then
    # Only the vault changed. The commit was verified when it shipped.
    env_only=true
    gate_scope="none"
    log "[scope] no new commit, only a new vault version: nothing to verify"
elif [ -n "$narrowing_unlicensed" ]; then
    log "[scope] $narrowing_unlicensed"
else
    scope_word=$(cd "$REPO" && python3 -m tools.gate_scope \
        --changed-file "$STATE_DIR/gate-changed-paths" --repo "$REPO" \
        --out-paths "$gate_paths_file" --out-json "$gate_scope_json" 2>> "$LOG")
    case "$scope_word" in
        none|selected|full) gate_scope="$scope_word" ;;
        *)
            : > "$gate_paths_file"
            log "[scope] the selector returned '${scope_word:-<nothing>}'; falling back to the full gate"
            fire_alert_once "gate-selector" "$NEW_SHA" \
                "auto-deploy: the test selector failed" \
                "python3 -m tools.gate_scope gave no scope at ${NEW_SHA:0:12}. The gate ran FULL, so nothing shipped unverified, but the selector is broken. Log: $LOG" ;;
    esac
fi
gate_selected_count=$(wc -l < "$gate_paths_file" | tr -d ' ')
log "[scope] gate_scope=$gate_scope selected_paths=$gate_selected_count"
