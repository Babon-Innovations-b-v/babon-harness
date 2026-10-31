#!/usr/bin/env bash
# Make a freshly created session worktree runnable.
#
# One purpose: bring a worktree from "checked out" to "you can run the suite in
# it". Idempotent, safe to re-run, and it never touches another worktree.
#
#   bash .claude/scripts/worktree-setup.sh
#
# What it does:
#   1. points git at the repo's tracked hooks (core.hooksPath), so this
#      worktree runs its own copy of the torn-commit guard;
#   2. creates .venv when there is no pytest in it, with the full sync
#      (`--all-packages --all-extras --all-groups`); a plain `uv sync` leaves
#      out the groups the tests need, so it is never the right call here.
#
# It deliberately does NOT symlink .venv from the main checkout. A venv carries
# absolute editable mappings for the workspace packages, so a shared venv would
# import the main checkout's copy and a worktree editing one of them would test
# the wrong tree. See docs/bible.md, workflow/loop.
set -u

case "${1:-}" in
    "") ;;
    -h|--help)
        sed -n '2,20p' "$0"
        exit 0
        ;;
    *)
        echo "worktree-setup: unknown argument '$1'" >&2
        exit 2
        ;;
esac

root=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "worktree-setup: not inside a git working tree" >&2
    exit 2
}
cd "$root" || exit 2
echo "worktree-setup: $root"

# ── 1. The tracked git hooks ────────────────────────────────────────────────
# Relative on purpose: git runs a hook with the working-tree root as its cwd,
# so each worktree resolves .claude/hooks to its OWN checkout's guard.
#
# An ABSOLUTE path ending in /.claude/hooks is rewritten rather than left
# alone. Worktrees share one `.git/config`, so an absolute value points every
# worktree at whichever checkout it names.
common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
current=$(git config --get core.hooksPath 2>/dev/null || true)
case "$current" in
    "" | "$common/hooks" | .git/hooks | /*/.claude/hooks)
        git config core.hooksPath .claude/hooks
        echo "  hooks: core.hooksPath -> .claude/hooks (torn-commit guard armed)"
        ;;
    .claude/hooks)
        echo "  hooks: already .claude/hooks"
        ;;
    *)
        echo "  hooks: core.hooksPath is '$current'; left alone, and the" >&2
        echo "         torn-commit guard is NOT installed" >&2
        ;;
esac

# ── 2. The virtualenv ───────────────────────────────────────────────────────
if [ ! -f pyproject.toml ]; then
    echo "  venv: no pyproject.toml here, nothing to sync"
elif [ -x .venv/bin/pytest ]; then
    echo "  venv: .venv/bin/pytest is already here"
elif ! command -v uv >/dev/null 2>&1; then
    echo "  venv: uv is not on PATH; install it, then re-run" >&2
else
    echo "  venv: uv sync --all-packages --all-extras --all-groups (a few minutes)"
    uv sync --all-packages --all-extras --all-groups
fi

echo "worktree-setup: done. Push from here with 'git push origin HEAD:main'."
