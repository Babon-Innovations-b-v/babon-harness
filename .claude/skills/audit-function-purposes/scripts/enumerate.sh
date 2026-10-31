#!/usr/bin/env bash
# Enumerate every Python function in scope. Outputs path\tline\tend\tlength\tname,
# sorted by length descending. Agent then reads top-N candidates and judges them
# per SKILL.md.

set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
SHA="$(git -C "$REPO" rev-parse --short HEAD)"
OUT_DIR="$REPO/tmp/_audit-function-purposes"
mkdir -p "$OUT_DIR"

# ── Scope ────────────────────────────────────────────────────────────────────
# What git tracks, not a hard-coded layout: a repo spawned from the template has no
# fixed directory shape, and a guessed scope silently audits nothing.
PY_COUNT="$(git -C "$REPO" ls-files '*.py' | grep -c . || true)"
if [ "$PY_COUNT" -eq 0 ]; then
    echo "no python tracked in this repo; nothing to audit"
    exit 0
fi

CANDIDATES="$OUT_DIR/candidates.tsv"
PARSE_ERRORS="$OUT_DIR/parse-errors.txt"
: > "$CANDIDATES"
: > "$PARSE_ERRORS"

# ── AST walk via standalone helper ───────────────────────────────────────────
HELPER="$OUT_DIR/_walk.py"
cat > "$HELPER" <<'PYEOF'
import ast
import os
import sys

repo, candidates_path, errors_path = sys.argv[1:4]
files = sys.argv[4:]

with open(candidates_path, "a") as out, open(errors_path, "a") as err:
    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            tree = ast.parse(source, filename=path)
        except (SyntaxError, OSError) as exc:
            err.write(f"{path}\t{exc}\n")
            continue

        rel = os.path.relpath(path, repo)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            start = node.lineno
            end = node.end_lineno or start
            length = end - start + 1
            out.write(f"{rel}\t{start}\t{end}\t{length}\t{node.name}\n")
PYEOF

git -C "$REPO" ls-files -z '*.py' \
    | tr '\0' '\n' \
    | grep -vE '(^|/)(tests|migrations|vendor|third_party|[^/]*_libs|__pycache__|\.venv|node_modules)/' \
    | sed "s|^|$REPO/|" \
    | tr '\n' '\0' \
    | xargs -0 -r python3 "$HELPER" "$REPO" "$CANDIDATES" "$PARSE_ERRORS"

rm -f "$HELPER"

# ── Sort by length descending ────────────────────────────────────────────────
sort -t$'\t' -k4 -rn "$CANDIDATES" -o "$CANDIDATES"

TOTAL=$(wc -l < "$CANDIDATES" | tr -d ' ')
ERRORS=$(wc -l < "$PARSE_ERRORS" | tr -d ' ')

echo "scope: every tracked *.py ($PY_COUNT files)"
echo "candidates: $TOTAL fns"
echo "parse errors: $ERRORS files"
echo ""
echo "top 20 by length:"
head -20 "$CANDIDATES" | awk -F'\t' '{printf "  %4s  %s:%s  %s\n", $4, $1, $2, $5}'
echo ""
echo "full list: $CANDIDATES"
echo "next: agent reads candidates top-down, emits verdicts per SKILL.md."
echo "final report: $REPO/tmp/audit-function-purposes-${SHA}.md"
