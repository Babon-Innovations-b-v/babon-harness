#!/bin/bash
# The command of the deploy loop's two CronJobs: make sure the clone exists,
# then run the loop from it.
#
#   cycle_entry.sh         CronJob deploy-cycle: infra/auto-deploy/auto-deploy.sh
#   cycle_entry.sh lane    CronJob commit-gate: move the clone to origin/main,
#                          then infra/auto-deploy/commit_gate/cluster_lane.sh
#
# The clone lives on the pod's own volume at $HARNESS_ROOT/repo. The cycle's
# step 15 fast-forwards its clone under the cycle's lock, so nothing here pulls
# for it; the lane's clone has no other writer, so the lane resets it to
# origin/main itself. A clone that is missing (a fresh volume) is made from
# DEPLOY_REPO_URL, with the read token from Secret deploy-git-read when the
# repository is private.
#
# FAILURE POLICY: a clone that cannot be made or moved exits 1, so the Job
# fails and the CronJob's failed-Jobs history shows it; the next tick tries
# again.
set -u
: "${HARNESS_ROOT:?}" "${DEPLOY_REPO_URL:?}"
clone="$HARNESS_ROOT/repo"
token_file="${DEPLOY_GIT_TOKEN_FILE:-/var/run/deploy/git/token}"

if [ ! -d "$clone/.git" ]; then
    mkdir -p "$HARNESS_ROOT" || exit 1
    rm -rf "$clone.partial"
    helper=()
    [ -s "$token_file" ] && helper=(-c "credential.helper=!f() { echo username=x-access-token; echo password=\$(cat $token_file); }; f")
    git "${helper[@]}" clone -q "$DEPLOY_REPO_URL" "$clone.partial" || { echo "cycle_entry: clone of $DEPLOY_REPO_URL failed"; exit 1; }
    if [ "${#helper[@]}" -gt 0 ]; then
        git -C "$clone.partial" config credential.helper "${helper[1]#credential.helper=}" || exit 1
    fi
    mv "$clone.partial" "$clone" || exit 1
fi
if [ "${1:-}" = "lane" ]; then
    git -C "$clone" fetch -q --prune origin main || { echo "cycle_entry: fetch of origin/main failed"; exit 1; }
    git -C "$clone" reset -q --hard origin/main || exit 1
    exec bash "$clone/infra/auto-deploy/commit_gate/cluster_lane.sh"
fi
exec bash "$clone/infra/auto-deploy/auto-deploy.sh"
