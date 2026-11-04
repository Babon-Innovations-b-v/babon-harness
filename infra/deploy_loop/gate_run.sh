#!/bin/bash
# Run container of a gate Job, in the gate image the gated commit pins.
#
#   1. re-point the image's environment (/opt/gate-env) at this tree: offline
#      from the image's own uv cache first, then online when the tree's lock is
#      not the one the image was built from. Both failing exits 126 (AMBER).
#   2. write the commit's changed paths (GATE_CHANGED_PATHS) to a file
#   3. run pytest with the arguments given, under a clean `env -i`, inside
#      GATE_SECONDS, in the tree
#   4. when pytest exited 0 and there are changed paths, replay the breaks of
#      the register rows the commit touches in this same pod, print its report
#      prefixed `@@replay@@ ` and its code as `@@replay-rc@@ N`
#
# The clean environment is the gate's: keep it identical to the one
# tools/gate_scope/audit_full_run.sh uses, or the audit stops being evidence.
#
# FAILURE POLICY: exit with pytest's own code, which IS the gate's verdict. A
# fault of this script is never 0 to 5.
set -u
: "${GATE_TREE:?}"
cd "$GATE_TREE" || exit 126

if ! UV_OFFLINE=1 uv sync --frozen --all-packages --all-extras --all-groups -q >/tmp/sync.log 2>&1; then
    echo "[gate-run] the image's environment would not re-sync offline; syncing this tree's lock online"
    if ! uv sync --frozen --all-packages --all-extras --all-groups -q >>/tmp/sync.log 2>&1; then
        tail -n 40 /tmp/sync.log
        echo "[gate-run] uv sync failed; the gate has no environment to run in"
        exit 126
    fi
fi

changed=/tmp/gate-changed-paths
printf '%s' "${GATE_CHANGED_PATHS:-}" > "$changed" || exit 126

env -i \
    HOME=/home/gate \
    PATH="/usr/local/bin:/usr/bin:/bin" \
    LANG=C.UTF-8 \
    PYTHONPATH="$GATE_TREE" \
    timeout "${GATE_SECONDS:-1200}" /opt/gate-env/bin/pytest "$@"
rc=$?

if [ "$rc" -eq 0 ] && [ -s "$changed" ] && [ -d "$GATE_TREE/tools/test_register" ]; then
    env -i \
        HOME=/home/gate \
        PATH="/usr/local/bin:/usr/bin:/bin" \
        LANG=C.UTF-8 \
        PYTHONPATH="$GATE_TREE" \
        timeout 900 /opt/gate-env/bin/python -m tools.test_register --changed-file "$changed" \
        --workers "${GATE_REPLAY_WORKERS:-1}" --repo "$GATE_TREE" 2>&1 | sed 's/^/@@replay@@ /'
    echo "@@replay-rc@@ ${PIPESTATUS[0]}"
fi
exit "$rc"
