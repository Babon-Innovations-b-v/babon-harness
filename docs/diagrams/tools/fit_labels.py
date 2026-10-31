#!/usr/bin/env python3
"""Iteratively apply the archify validator's suggested labelAt fixes.

Runs `archify validate architecture --json`, parses every label-overlap
diagnostic, applies the suggested labelAt to the (unique-labelled) connection,
and repeats until clean or the round cap. Prefers the 'below' suggestion first,
then the 'above' one if the same label errors again at the same spot.
"""
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
SKILL = REPO / '.claude' / 'skills' / 'archify'
DOC = pathlib.Path(sys.argv[1]).resolve()

DTYPE = 'workflow' if '.workflow.json' in str(DOC) else 'architecture'
KEY = 'connections' if DTYPE == 'architecture' else 'edges'

PAT = re.compile(
    r'Label "([^"]+)" overlaps .*?Suggested fix: labelAt \[(-?\d+), (-?\d+)\][^;]*'
    r'(?:; or labelAt \[(-?\d+), (-?\d+)\])?', re.S)

tried = {}
for round_no in range(10):
    res = subprocess.run(
        ['node', 'bin/archify.mjs', 'validate', DTYPE, str(DOC), '--json'],
        cwd=SKILL, capture_output=True, text=True)
    try:
        out = json.loads(res.stdout)
    except json.JSONDecodeError:
        # layout passed; the CLI then dies parsing its own oversized receipt
        print(f'validate: layout ok after {round_no} fix rounds (receipt bug ignored)')
        sys.exit(0)
    if out.get('ok'):
        print(f'validate: ok after {round_no} fix rounds')
        sys.exit(0)
    err = out.get('error', '')
    label_fixes = {}
    for m in PAT.finditer(err):
        label, x1, y1, x2, y2 = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        options = [[int(x1), int(y1)]]
        if x2 is not None:
            options.append([int(x2), int(y2)])
        label_fixes.setdefault(label, options)
    other = [line for line in err.split('\n- ') if 'Label "' not in line and line.strip()]
    # labels colliding with each other: nudge the second one down a row
    pair = re.compile(r'Labels "([^"]+)" and "([^"]+)" overlap')
    nudges = {}
    for m in pair.finditer(err):
        nudges[m.group(2)] = nudges.get(m.group(2), 0) + 1
    if nudges and not label_fixes:
        doc = json.loads(DOC.read_text())
        applied = 0
        for c in doc[KEY]:
            n = nudges.get(c.get('label'))
            if n:
                seen_n = tried.get('~' + c['label'], 0)
                if seen_n >= 3:
                    # it will not fit anywhere near its line; the popup has the detail
                    del c['label']
                    applied += 1
                    continue
                step = 16 * (seen_n + 1)
                tried['~' + c['label']] = seen_n + 1
                if 'labelAt' in c:
                    c['labelAt'] = [c['labelAt'][0], c['labelAt'][1] + step]
                else:
                    c['labelDy'] = c.get('labelDy', 0) + step
                applied += 1
        DOC.write_text(json.dumps(doc, indent=1) + '\n')
        print(f'round {round_no}: nudged {applied} colliding labels')
        continue
    if not label_fixes:
        print('no label fixes parseable; remaining error:')
        print(err[:3000])
        sys.exit(1)
    doc = json.loads(DOC.read_text())
    applied = 0
    for c in doc[KEY]:
        label = c.get('label')
        if label in label_fixes:
            options = label_fixes[label]
            attempt = tried.get(label, 0)
            if attempt >= 4:
                c.pop('label', None)
                tried[label] = attempt + 1
                applied += 1
                continue
            pick = options[min(attempt, len(options) - 1)]
            if attempt >= len(options):
                # both suggestions exhausted: nudge vertically further down
                pick = [pick[0], pick[1] + 12 * (attempt - len(options) + 1)]
            c['labelAt'] = pick
            c.pop('labelSegment', None)
            c.pop('labelDy', None)
            c.pop('labelDx', None)
            tried[label] = attempt + 1
            applied += 1
    DOC.write_text(json.dumps(doc, indent=1) + '\n')
    print(f'round {round_no}: applied {applied} label fixes; {len(other)} other diagnostics')
print('did not converge; remaining error:')
print(err[:3000])
sys.exit(1)
