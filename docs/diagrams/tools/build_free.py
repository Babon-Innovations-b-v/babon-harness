#!/usr/bin/env python3
"""Lay a page out from hand-placed boxes and deliver it.

Every page shares a visual language, not a template: same renderer, same box
size, same boundary style, same legend. The shape of each page is chosen for
what that page has to say, and it lives in <name>.layout.json beside the facts:

    {"canvas": [1200, 760],
     "boxes": {"id": [x, y], ...},              # top-left corners
     "sizes": {"id": [w, h], ...},              # optional, defaults to 150x62
     "boundaries": [{"label": "...", "wraps": ["id", ...]}],
     "edges": [["from", "to", "label", {"variant": "dashed"}], ...]}

Labels, sublabels, notes and module links come from <name>.json, so the facts
live in one place and this file only says where things sit. Routing is worked
out here: straight where the grid allows, round the obstacle where it does not.
An edge may carry its own "fromSide", "toSide" and "via" to override that.
"""

import json
import pathlib
import subprocess
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
DIAGRAMS = TOOLS.parent
SPECS = DIAGRAMS / 'specs'
# Only the .html is served, so it is the only thing written into the page tree;
# the sidecars go to data/, which mirrors that tree one directory across.
DATA = DIAGRAMS / 'data'
# Pages named with a directory ("stack/deploy") build into that directory; the
# top page ("stack") builds into docs/diagrams/ itself, and any other bare name
# is a stack page.
OUT = DIAGRAMS / 'stack'
TOP = {'stack'}

MARGIN = 44
BOX_W, BOX_H = 150, 62
CELL_H, GUTTER = 300, 40


def blocked(x1, y1, x2, y2, boxes, sizes, skip):
    """True when the straight segment crosses a box that is not an endpoint."""
    lo_x, hi_x = sorted((x1, x2))
    lo_y, hi_y = sorted((y1, y2))
    for nid, (bx, by) in boxes.items():
        if nid in skip:
            continue
        bw, bh = sizes.get(nid, (BOX_W, BOX_H))
        if bx - 10 < hi_x and bx + bw + 10 > lo_x and by - 10 < hi_y and by + bh + 10 > lo_y:
            return True
    return False


def route(src, dst, boxes, sizes):
    """Sides and via points for one edge, straight where the placement allows."""
    sx, sy = boxes[src]
    dx, dy = boxes[dst]
    sw, sh = sizes.get(src, (BOX_W, BOX_H))
    dw, dh = sizes.get(dst, (BOX_W, BOX_H))
    scx, scy = sx + sw / 2, sy + sh / 2
    dcx, dcy = dx + dw / 2, dy + dh / 2
    skip = {src, dst}
    if abs(scy - dcy) < 4:
        if not blocked(sx + sw, scy, dx, scy, boxes, sizes, skip):
            return {'fromSide': 'right' if dx > sx else 'left',
                    'toSide': 'left' if dx > sx else 'right'}
        for lane in (sy - 26, sy + sh + 26):
            if not blocked(min(scx, dcx), lane, max(scx, dcx), lane, boxes, sizes, skip):
                side = 'top' if lane < sy else 'bottom'
                return {'fromSide': side, 'toSide': side, 'via': [[scx, lane], [dcx, lane]]}
    if abs(scx - dcx) < 4:
        if not blocked(scx, sy + sh, scx, dy, boxes, sizes, skip):
            return {'fromSide': 'bottom' if dy > sy else 'top',
                    'toSide': 'top' if dy > sy else 'bottom'}
        for lane in (sx - 26, sx + sw + 26):
            if not blocked(lane, min(scy, dcy), lane, max(scy, dcy), boxes, sizes, skip):
                side = 'left' if lane < sx else 'right'
                return {'fromSide': side, 'toSide': side, 'via': [[lane, scy], [lane, dcy]]}
    if not blocked(scx, scy, scx, dcy, boxes, sizes, skip) and \
            not blocked(scx, dcy, dx, dcy, boxes, sizes, skip):
        return {'fromSide': 'bottom' if dy > sy else 'top',
                'toSide': 'left' if dx > sx else 'right', 'via': [[scx, dcy]]}
    if not blocked(sx + sw, scy, dcx, scy, boxes, sizes, skip) and \
            not blocked(dcx, scy, dcx, dy, boxes, sizes, skip):
        return {'fromSide': 'right' if dx > sx else 'left',
                'toSide': 'top' if dy > sy else 'bottom', 'via': [[dcx, scy]]}
    # go round: pick a free horizontal lane and step out to it from both ends
    for lane in (max(sy, dy) + max(sh, dh) + 30, min(sy, dy) - 30,
                 max(sy, dy) + max(sh, dh) + 70, min(sy, dy) - 70):
        if blocked(min(scx, dcx), lane, max(scx, dcx), lane, boxes, sizes, skip):
            continue
        tail = [[dcx, lane]]
        side_to = 'bottom' if lane > dy else 'top'
        if blocked(dcx, min(dcy, lane), dcx, max(dcy, lane), boxes, sizes, skip):
            for stub, side in ((dx - 26, 'left'), (dx + dw + 26, 'right')):
                if not blocked(stub, min(dcy, lane), stub, max(dcy, lane), boxes, sizes, skip):
                    tail, side_to = [[stub, lane], [stub, dcy]], side
                    break
        if not blocked(scx, scy, scx, lane, boxes, sizes, skip):
            return {'fromSide': 'bottom' if lane > sy else 'top', 'toSide': side_to,
                    'via': [[scx, lane]] + tail}
        for stub, side in ((sx - 26, 'left'), (sx + sw + 26, 'right')):
            if not blocked(stub, min(scy, lane), stub, max(scy, lane), boxes, sizes, skip):
                return {'fromSide': side, 'toSide': side_to,
                        'via': [[stub, scy], [stub, lane]] + tail}
    return {}


def build(name):
    rel = pathlib.PurePosixPath(name)
    if str(rel.parent) != '.':
        out = DIAGRAMS / rel.parent
    elif rel.name in TOP:
        out = DIAGRAMS
    else:
        out = OUT
    # the one place the data/ mirror is worked out
    data = DATA / out.relative_to(DIAGRAMS)
    data.mkdir(parents=True, exist_ok=True)
    name = rel.name
    spec = json.loads((SPECS / f'{rel}.json').read_text())
    layout = json.loads((SPECS / f'{rel}.layout.json').read_text())
    nodes, sizes = spec['nodes'], {k: tuple(v) for k, v in layout.get('sizes', {}).items()}
    boxes = {nid: tuple(pos) for nid, pos in layout['boxes'].items()}

    components = [{
        'id': nid,
        'type': nodes[nid]['type'],
        'label': nodes[nid]['label'],
        'sublabel': nodes[nid]['sublabel'],
        'pos': list(pos),
        'size': list(sizes.get(nid, (BOX_W, BOX_H))),
    } for nid, pos in boxes.items()]

    connections = []
    for edge in layout['edges']:
        if edge[0] not in boxes or edge[1] not in boxes:
            continue
        conn = {'id': f'{edge[0]}-{edge[1]}', 'from': edge[0], 'to': edge[1]}
        if len(edge) > 2 and edge[2]:
            conn['label'] = edge[2]
        opts = edge[3] if len(edge) > 3 and isinstance(edge[3], dict) else {}
        conn.update({k: v for k, v in opts.items() if k == 'variant'})
        if any(k in opts for k in ('via', 'fromSide', 'toSide')):
            conn.update({k: v for k, v in opts.items() if k in ('via', 'fromSide', 'toSide', 'labelAt')})
        else:
            conn.update(route(edge[0], edge[1], boxes, sizes))
        connections.append(conn)

    doc = {
        'schema_version': 1,
        'diagram_type': 'architecture',
        'meta': {
            'title': spec['title'],
            'subtitle': spec['subtitle'],
            'visual_preset': 'editorial',
            'quality_profile': 'standard',
            'viewBox': layout['canvas'],
            'legend': {'mode': 'auto',
                       'entries': {k: {'label': v} for k, v in spec['legend'].items()}},
        },
        'components': components,
        'connections': connections,
    }
    if layout.get('boundaries'):
        doc['boundaries'] = [{'kind': 'region', 'label': b['label'], 'wraps': b['wraps']}
                             for b in layout['boundaries']]
    src = data / f"{name}.architecture.json"
    src.write_text(json.dumps(doc, indent=1) + '\n')
    (data / f"{name}.notes.json").write_text(json.dumps(
        {nid: nodes[nid]['note'] for nid in boxes}, indent=1, sort_keys=True) + '\n')
    (data / f"{name}.modules.json").write_text(json.dumps(
        {nid: nodes[nid]['module'] for nid in boxes if nodes[nid].get('module')},
        indent=1, sort_keys=True) + '\n')
    # What each box draws, when its author said. Optional, and empty for the
    # boxes that are a person, a timer, an outside service or a way of
    # working. Nothing can derive this: a box id rarely matches exactly one
    # file name, so a guess is wrong more often than it is right and wrong with
    # a citation attached. Written as a sidecar because linkmap and the
    # repository index both read data/ and neither reads specs/.
    (data / f"{name}.code.json").write_text(json.dumps(
        {nid: nodes[nid]['code'] for nid in boxes if nodes[nid].get('code')},
        indent=1, sort_keys=True) + '\n')
    slides_path = data / f"{name}.slides.json"
    if spec.get('slides'):
        # A page that can be told: each step names what arrives, and the regions
        # come along with the boxes they wrap, so the reader is never shown a
        # frame around nothing.
        slides_path.write_text(json.dumps({
            'steps': [{**step, 'add': [i for i in step['add']
                                       if i in boxes or '-' in i]}
                      for step in spec['slides']],
            'regions': [b['wraps'] for b in layout.get('boundaries', [])],
        }, indent=1, ensure_ascii=False) + '\n')
    elif slides_path.exists():
        slides_path.unlink()
    done = subprocess.run([str(TOOLS / 'deliver.sh'), str(src), str(out / f"{name}.html")],
                          capture_output=True, text=True)
    print(done.stdout.strip() or done.stderr.strip()[-1400:])
    return done.returncode == 0


if __name__ == '__main__':
    ok = all([build(n) for n in sys.argv[1:]])
    sys.exit(0 if ok else 1)
