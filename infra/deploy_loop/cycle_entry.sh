#!/bin/bash
# The deploy-cycle CronJob's command: make sure the cycle's clone exists, then
# run infra/auto-deploy/auto-deploy.sh from it.
#
# The clone lives on the state volume at $HARNESS_ROOT/repo and is the
# repository the cycle deploys; step 15 fast-forwards it under the cycle's
# lock, so nothing here pulls. A clone that is missing (a fresh volume) is made
# from DEPLOY_REPO_URL, with the read token from Secret deploy-git-read when
# the repository is private.
#
# FAILURE POLICY: a clone that cannot be made exits 1, so the Job fails and
# the CronJob's failed-Jobs history shows it; the next tick tries again.
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
exec bash "$clone/infra/auto-deploy/auto-deploy.sh"
