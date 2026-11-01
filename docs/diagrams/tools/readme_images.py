#!/usr/bin/env python3
"""Render the README's pictures of the diagram pages, dark and light.

The served pages are laid out wide for a screen. GitHub scales a README image
to its 840 px column, so a wide page shrinks until its text cannot be read.
Each README picture therefore has its own narrow layout in
specs/readme/<page>.layout.json, with the same boxes, regions and edges as the
page; the labels and notes still come from specs/<page>.json, and nothing in
data/ or the served tree is touched.

    python3 docs/diagrams/tools/readme_images.py stack stack/loop

writes docs/diagrams/images/<name>-dark.png and <name>-light.png, where <name>
is the page's last path part. Needs `node` for archify and the Python
`playwright` package with a Chromium it can launch (PLAYWRIGHT_CHROMIUM names
the executable when the bundled one does not start).
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from build_free import BOX_H, BOX_W, SPECS, route  # noqa: E402

SKILL_DIR = TOOLS.parents[2] / '.claude' / 'skills' / 'archify'

IMAGES = TOOLS.parent / 'images'
THEMES = ('dark', 'light')
# Pixels per layout unit in the picture, so a 680-unit layout is 1360 px wide.
EXPORT_SCALE = 2


def architecture_doc(page):
    """The archify document for one page's README layout."""
    spec = json.loads((SPECS / f'{page}.json').read_text())
    layout = json.loads((SPECS / 'readme' / f'{pathlib.PurePosixPath(page).name}.layout.json').read_text())
    nodes = spec['nodes']
    sizes = {k: tuple(v) for k, v in layout.get('sizes', {}).items()}
    boxes = {nid: tuple(pos) for nid, pos in layout['boxes'].items()}
    components = [{
        'id': nid, 'type': nodes[nid]['type'], 'label': nodes[nid]['label'],
        'sublabel': nodes[nid]['sublabel'], 'pos': list(pos),
        'size': list(sizes.get(nid, (BOX_W, BOX_H))),
    } for nid, pos in boxes.items()]
    connections = []
    for edge in layout['edges']:
        conn = {'id': f'{edge[0]}-{edge[1]}', 'from': edge[0], 'to': edge[1]}
        if len(edge) > 2 and edge[2]:
            conn['label'] = edge[2]
        opts = edge[3] if len(edge) > 3 else {}
        conn.update({k: v for k, v in opts.items() if k == 'variant'})
        if any(k in opts for k in ('via', 'fromSide', 'toSide')):
            conn.update({k: v for k, v in opts.items() if k in ('via', 'fromSide', 'toSide', 'labelAt')})
        else:
            conn.update(route(edge[0], edge[1], boxes, sizes))
            if 'labelAt' in opts:
                conn['labelAt'] = opts['labelAt']
        connections.append(conn)
    legend = {**spec['legend'], **layout.get('legend', {})}
    return {
        'schema_version': 1,
        'diagram_type': 'architecture',
        'meta': {
            'title': spec['title'], 'subtitle': spec['subtitle'],
            'visual_preset': 'editorial', 'quality_profile': 'standard',
            'viewBox': layout['canvas'],
            'legend': {'mode': 'auto', 'entries': {k: {'label': v} for k, v in legend.items()}},
        },
        'components': components,
        'connections': connections,
        'boundaries': [{'kind': 'region', 'label': b['label'], 'wraps': b['wraps']}
                       for b in layout.get('boundaries', [])],
    }


def render_html(page, workdir):
    """Validate, fit labels and render one page's README layout to HTML."""
    src = workdir / 'readme.architecture.json'
    src.write_text(json.dumps(architecture_doc(page), indent=1) + '\n')
    subprocess.run([sys.executable, str(TOOLS / 'fit_labels.py'), str(src)], check=False)
    html = workdir / 'readme.html'
    subprocess.run(['node', 'bin/archify.mjs', 'render', 'architecture', str(src), str(html),
                    '--quality', 'standard'], cwd=SKILL_DIR, check=True, capture_output=True)
    return html


def export_svg(html, out):
    """Save the page's own SVG export, which carries both themes."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM'))
        page = browser.new_page(accept_downloads=True)
        page.goto(html.as_uri())
        page.click('#btn-export')
        with page.expect_download() as download:
            page.click('#export-menu [data-format="svg"]')
        download.value.save_as(out)
        browser.close()


def raster(svg, canvas, theme, out):
    """Draw the exported SVG in one theme at EXPORT_SCALE pixels per unit."""
    from playwright.sync_api import sync_playwright
    width, height = canvas
    with sync_playwright() as play:
        browser = play.chromium.launch(executable_path=os.environ.get('PLAYWRIGHT_CHROMIUM'))
        page = browser.new_page(viewport={'width': width, 'height': height},
                                device_scale_factor=EXPORT_SCALE, color_scheme=theme)
        page.goto(svg.as_uri())
        page.screenshot(path=out)
        browser.close()


def main(pages):
    IMAGES.mkdir(exist_ok=True)
    for page in pages:
        name = pathlib.PurePosixPath(page).name
        canvas = json.loads((SPECS / 'readme' / f'{name}.layout.json').read_text())['canvas']
        with tempfile.TemporaryDirectory() as tmp:
            svg = pathlib.Path(tmp) / 'readme.svg'
            export_svg(render_html(page, pathlib.Path(tmp)), svg)
            for theme in THEMES:
                out = IMAGES / f'{name}-{theme}.png'
                raster(svg, canvas, theme, out)
                print(f'wrote {out}')


if __name__ == '__main__':
    main(sys.argv[1:])
