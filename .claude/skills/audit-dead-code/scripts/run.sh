#!/usr/bin/env bash
# Mechanical dead-code audit: vulture (Python) + ts-prune (TS) + shellcheck SC2034 (bash).
# Outputs intermediate findings under tmp/_audit-mechanical/. The LLM resolve pass
# is performed separately by the agent (see SKILL.md).
#
# Scope comes from what git tracks, not from a hard-coded layout: a repo spawned from
# the template has no fixed directory shape, and a scope list that guesses one silently
# audits nothing.

set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
SHA="$(git -C "$REPO" rev-parse --short HEAD)"
OUT_DIR="$REPO/tmp/_audit-mechanical"
mkdir -p "$OUT_DIR"

count_tracked() { git -C "$REPO" ls-files "$1" | grep -c . || true; }

PY_COUNT="$(count_tracked '*.py')"
TS_COUNT="$(count_tracked '*.ts')"
SH_COUNT="$(count_tracked '*.sh')"
echo "tracked: ${PY_COUNT} python, ${TS_COUNT} typescript, ${SH_COUNT} bash"

# ── 1. Python (vulture) ──────────────────────────────────────────────────────
PY_OUT="$OUT_DIR/python.txt"
if [ "$PY_COUNT" -gt 0 ]; then
    echo "running vulture..."
    {
        # vulture from PATH, else a throwaway one through uv, so no install step is needed.
        if command -v vulture >/dev/null 2>&1; then VULTURE=(vulture); else VULTURE=(uv run --with vulture vulture); fi
        "${VULTURE[@]}" \
            --min-confidence 80 \
            --exclude '**/.venv/**,**/node_modules/**,**/vendor/**,**/third_party/**,**/*_libs/**,**/migrations/**,**/tests/**,**/build/**,**/dist/**,**/.claude/worktrees/**' \
            "$REPO" 2>&1 || true
    } > "$PY_OUT"
else
    echo "no python tracked; skipping vulture"
    echo "(no python in this repo)" > "$PY_OUT"
fi
echo "  -> $PY_OUT ($(wc -l < "$PY_OUT") lines)"

# ── 2. TypeScript (ts-prune), once per package ───────────────────────────────
TS_OUT="$OUT_DIR/typescript.txt"
if [ "$TS_COUNT" -gt 0 ]; then
    echo "running ts-prune..."
    {
        while IFS= read -r manifest; do
            package_dir="$REPO/$(dirname "$manifest")"
            [ -f "$package_dir/tsconfig.json" ] || continue
            echo "# $manifest"
            (cd "$package_dir" && npx --yes ts-prune 2>&1 || true)
        done < <(git -C "$REPO" ls-files '*package.json' | grep -v node_modules)
    } > "$TS_OUT"
else
    echo "no typescript tracked; skipping ts-prune"
    echo "(no typescript in this repo)" > "$TS_OUT"
fi
echo "  -> $TS_OUT ($(wc -l < "$TS_OUT") lines)"

# ── 3. Bash (shellcheck SC2034) ──────────────────────────────────────────────
SH_OUT="$OUT_DIR/bash.txt"
if [ "$SH_COUNT" -eq 0 ]; then
    echo "no bash tracked; skipping shellcheck"
    echo "(no bash in this repo)" > "$SH_OUT"
elif command -v shellcheck >/dev/null 2>&1; then
    echo "running shellcheck SC2034..."
    {
        git -C "$REPO" ls-files -z '*.sh' \
            | xargs -0 -r -I{} shellcheck --include=SC2034 --format=tty "$REPO/{}" 2>&1 || true
    } > "$SH_OUT"
else
    echo "shellcheck not installed, skipping bash pass (install: apt-get install shellcheck)"
    echo "(shellcheck not installed; bash pass skipped)" > "$SH_OUT"
fi
echo "  -> $SH_OUT ($(wc -l < "$SH_OUT") lines)"

# ── Summary ──────────────────────────────────────────────────────────────────
SUMMARY="$OUT_DIR/summary.md"
{
    echo "# Mechanical dead-code findings - $SHA"
    echo ""
    echo "tracked: ${PY_COUNT} python, ${TS_COUNT} typescript, ${SH_COUNT} bash"
    echo ""
    echo "## Python (vulture)"
    echo ""
    echo '```'
    cat "$PY_OUT"
    echo '```'
    echo ""
    echo "## TypeScript (ts-prune)"
    echo ""
    echo '```'
    cat "$TS_OUT"
    echo '```'
    echo ""
    echo "## Bash (shellcheck SC2034)"
    echo ""
    echo '```'
    cat "$SH_OUT"
    echo '```'
} > "$SUMMARY"

echo ""
echo "-- mechanical pass done --"
echo "summary: $SUMMARY"
echo ""
echo "next: agent runs the LLM resolve pass per SKILL.md - reads each flagged"
echo "symbol's import sites and assigns Dead | Live | Uncertain verdict."
echo "final report goes to: $REPO/tmp/audit-dead-code-${SHA}.md"
