#!/bin/bash
# deliver.sh <arch.json> <out.html> : validate-fix, render, check, install, strip
# The source is a build sidecar under docs/diagrams/data/; the .html it writes is
# the only thing that goes into the served page tree.
set -e
SRC=$(readlink -f "$1"); OUT=$(readlink -f "$2" 2>/dev/null || echo "$PWD/$2"); HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
SKILL="$REPO/.claude/skills/archify"
case "$SRC" in *.workflow.json) TYPE=workflow;; *) TYPE=architecture;; esac
python3 "$HERE/fit_labels.py" "$SRC" >/dev/null
TMPH=$(mktemp /tmp/archify-XXXX.html)
(cd "$SKILL" && node bin/archify.mjs render "$TYPE" "$SRC" "$TMPH" --quality standard >/dev/null 2>&1)
(cd "$SKILL" && node bin/archify.mjs check "$TMPH" > "$TMPH.json" 2>/dev/null)
python3 -c "
import json,sys
d=json.load(open('$TMPH.json'))
sys.exit(0 if d.get('ok') else 1)"
mv "$TMPH" "$OUT"
# a page is delivered when it changes, so the day it was delivered is the day it
# last changed. The byline is DIAGRAM_AUTHORS, from config/harness.env.
python3 "$HERE/strip-chrome.py" "$OUT" "${DIAGRAM_AUTHORS:-Drawn with Claude}" "$(date +%F)" >/dev/null
echo "built: $OUT"
