#!/bin/bash
# The deploy-cycle image's own smoke test, run inside a freshly built image
# before anything names it: by the cycle as a pod (steps/cluster.sh,
# cluster_ship_cycle_image). Exit 0 only when every tool the steps call answers
# and the baked entrypoints load.
#
# FAILURE POLICY: fail loud; the first check that says no ends it, named on
# stderr.
set -eu
fail() { echo "image-smoke: $*" >&2; exit 1; }
test "$(id -u)" != 0 || fail "runs as root"
for tool in kubectl buildctl uv jq git flock curl python3; do
    command -v "$tool" >/dev/null || fail "$tool is not on PATH"
done
kubectl version --client >/dev/null || fail "kubectl does not answer"
buildctl --version >/dev/null || fail "buildctl does not answer"
cd /app
python3 -c "import infra.deploy_loop" || fail "system python3 cannot import infra.deploy_loop"
python3 -m infra.deploy_loop cycle-image-sum /app >/dev/null || fail "the guard's package does not run"
bash -n /app/infra/deploy_loop/cycle_entry.sh || fail "cycle_entry.sh does not parse"
echo "image-smoke: ok"
