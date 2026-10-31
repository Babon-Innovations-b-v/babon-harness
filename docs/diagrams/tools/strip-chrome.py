#!/usr/bin/env python3
"""Post-process a delivered archify HTML for serving.

- Hides the viewer chrome (toolbar, guided-views bar) and the node popup's
  graph-stat noise (type chips, id, reach counters).
- Replaces the subtitle with authors + last-updated.
- Adds the zoom-out button one level up, the nav pill to the stack page, the
  slide walker for a page that has steps, and caption colours that match their
  line.
- If a sidecar <name>.notes.json exists ({nodeId: text}), injects those
  texts into the node popup so clicking a node shows a real explanation.

Every sidecar it reads lives under docs/diagrams/data/, which mirrors the
served page layout; the served tree holds nothing but .html.

Usage: python3 docs/diagrams/tools/strip-chrome.py <file.html> "<authors>" <YYYY-MM-DD>
Re-run after every `archify deliver`; delivery regenerates the page.
"""
import json
import pathlib
import re
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
DIAGRAMS = TOOLS.parent
DATA = DIAGRAMS / "data"

MARKER = "diagram:strip-chrome"
CSS = (
    f"<style>/* {MARKER} */"
    ".toolbar,.guided-views,.cards,.footer{display:none!important}"
    ".header{margin-top:8px}"
    "#focus-passport-meta,#focus-reach,#focus-summary{display:none!important}"
    "@media (min-width:1000px){.focus-chip{width:min(30rem,calc(100% - 13rem))!important}}"
    "</style>"
)

# A caption belongs to its line, so it is that line's colour. The renderer gives
# every caption one of two text colours and the lines three, so a reader would
# otherwise have to work out which line the words belong to. Every page gets this, not only the ones we draw by
# hand: the caption takes the stroke of the path with the same edge id.
LABEL_COLOUR_JS = """<script>/* diagram:edge-label-colour */(function () {
  var svg = document.querySelector('.diagram-container svg');
  if (!svg) return;
  var strokes = {};
  svg.querySelectorAll('path[data-edge-id]').forEach(function (line) {
    strokes[line.getAttribute('data-edge-id')] = getComputedStyle(line).stroke;
  });
  svg.querySelectorAll('g[data-edge-id]').forEach(function (caption) {
    var stroke = strokes[caption.getAttribute('data-edge-id')];
    if (!stroke) return;
    caption.querySelectorAll('text').forEach(function (words) {
      words.style.fill = stroke;
    });
  });
})();</script>"""

SLIDES_MARKER = "diagram:slides"
# A drawn page is a reference; a told page is a story, and the difference is
# that a story only ever has one thing on it. These steps draw the page a piece
# at a time from the sidecar the builder writes, so the tangle a finished map
# always has never arrives at once. The whole drawing stays one arrow away.
SLIDES_CSS = (
    f"<style>/* {SLIDES_MARKER} */"
    "#chrome-slides{display:flex;align-items:baseline;gap:14px;margin:6px 0 2px;"
    "font:500 12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}"
    "#chrome-slides button{font:inherit;color:inherit;background:none;cursor:pointer;"
    "border:1px solid currentColor;border-radius:999px;padding:1px 9px;opacity:.55}"
    "#chrome-slides button:hover{opacity:1}"
    "#chrome-slides button[disabled]{opacity:.16;cursor:default}"
    "#chrome-slide-count{opacity:.5;letter-spacing:.06em;white-space:nowrap}"
    "#chrome-slide-label{font-weight:700;white-space:nowrap}"
    "#chrome-slide-note{opacity:.72}"
    "#chrome-slide-all{margin-left:auto;white-space:nowrap}"
    ".diagram-container svg [data-node-id],.diagram-container svg [data-edge-id],"
    ".diagram-container svg [data-composition-frame-kind],"
    ".diagram-container svg .chrome-region-label{transition:opacity .25s ease}"
    "</style>"
)

SLIDES_JS = """<script>/* diagram:slides-player */(function () {
  var DATA = __SLIDES__;
  var steps = DATA.steps || [];
  var svg = document.querySelector('.diagram-container svg');
  var header = document.querySelector('.header');
  if (!steps.length || !svg || !header) return;
  var seat = 'chrome-step:' + location.pathname;

  var frames = svg.querySelectorAll('[data-composition-frame-kind="region"]');
  frames.forEach(function (frame) {
    var label = frame.nextElementSibling;
    if (label && label.tagName.toLowerCase() === 'text') label.classList.add('chrome-region-label');
  });

  // A line is drawn once both its ends are on the page, unless a later step
  // claims it: a line that is the whole point of a step waits for that step.
  var claimed = {};
  steps.forEach(function (step, index) {
    (step.add || []).forEach(function (id) { claimed[id] = index; });
  });

  var shownBy = function (index) {
    var on = {};
    for (var k = 0; k <= index; k++) {
      (steps[k].add || []).forEach(function (id) { on[id] = true; });
    }
    return on;
  };

  var paint = function (index) {
    var whole = index < 0 || index >= steps.length;
    var on = whole ? {} : shownBy(index);
    var shows = function (id, from, to) {
      if (whole || on[id]) return true;
      if (!from) return false;
      if (claimed[id] !== undefined) return false;
      return !!(on[from] && on[to]);
    };
    var set = function (element, lit) {
      element.style.opacity = lit ? '' : '0';
      element.style.pointerEvents = lit ? '' : 'none';
    };
    svg.querySelectorAll('[data-node-id]').forEach(function (node) {
      set(node, shows(node.getAttribute('data-node-id')));
    });
    svg.querySelectorAll('[data-edge-id]').forEach(function (edge) {
      set(edge, shows(edge.getAttribute('data-edge-id'),
                      edge.getAttribute('data-edge-from'),
                      edge.getAttribute('data-edge-to')));
    });
    frames.forEach(function (frame, position) {
      var wraps = (DATA.regions || [])[position] || [];
      // the frame is what a step about the owner is about, so it arrives with the
      // first box inside it rather than waiting for the last
      var lit = whole || wraps.some(function (id) { return on[id]; });
      var label = frame.nextElementSibling;
      frame.style.opacity = lit ? '' : '0';
      if (label) label.style.opacity = lit ? '' : '0';
    });
  };

  var bar = document.createElement('div');
  bar.id = 'chrome-slides';
  bar.innerHTML =
    '<button id="chrome-slide-prev" type="button" title="Back (left arrow)">&#8592;</button>' +
    '<button id="chrome-slide-next" type="button" title="Forward (right arrow)">&#8594;</button>' +
    '<span id="chrome-slide-count"></span><span id="chrome-slide-label"></span>' +
    '<span id="chrome-slide-note"></span>' +
    '<button id="chrome-slide-all" type="button" title="The whole drawing (escape)">show all</button>';
  header.appendChild(bar);

  var prev = bar.querySelector('#chrome-slide-prev');
  var next = bar.querySelector('#chrome-slide-next');
  var all = bar.querySelector('#chrome-slide-all');
  var count = bar.querySelector('#chrome-slide-count');
  var label = bar.querySelector('#chrome-slide-label');
  var note = bar.querySelector('#chrome-slide-note');

  // -1 is the whole page, and it is the only state outside the story: forward
  // from it starts at the first step and forward from the last returns to it, so
  // an arrow is never dead
  var at = -1;
  var go = function (index) {
    at = index < -1 ? steps.length - 1 : (index >= steps.length ? -1 : index);
    var telling = at >= 0;
    count.textContent = telling ? (at + 1) + ' / ' + steps.length : '';
    label.textContent = telling ? steps[at].label : 'The whole page';
    note.textContent = telling ? (steps[at].note || '') : 'Walk through it with the arrow keys.';
    all.hidden = !telling;
    paint(at);
    try {
      // arriving back from a box's own page, the hash is that box: leave it alone
      // so the viewer still opens what the reader clicked
      if (location.hash.indexOf('#focus=') !== 0) {
        history.replaceState(null, '', telling ? '#step=' + (at + 1) : location.pathname);
      }
      sessionStorage.setItem(seat, String(at));
    } catch (error) {}
  };

  prev.addEventListener('click', function () { go(at - 1); });
  next.addEventListener('click', function () { go(at + 1); });
  all.addEventListener('click', function () { go(-1); });
  document.addEventListener('keydown', function (event) {
    var tag = (event.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || event.metaKey || event.ctrlKey) return;
    if (event.key === 'ArrowRight' || event.key === 'PageDown') { go(at + 1); event.preventDefault(); }
    if (event.key === 'ArrowLeft' || event.key === 'PageUp') { go(at - 1); event.preventDefault(); }
    if (event.key === 'Escape') { go(-1); }
  });

  // going into a box's own page and coming back should not lose your place
  var deep = /#step=(\\d+)/.exec(location.hash || '');
  var kept = null;
  try { kept = sessionStorage.getItem(seat); } catch (error) {}
  go(deep ? parseInt(deep[1], 10) - 1 : (kept === null ? -1 : parseInt(kept, 10)));
})();</script>"""

NAV_PAGES = [
    ("stack", "The stack"),
]

NAV_HTML = (
    '<style>/* diagram:nav */'
    "#chrome-nav{position:fixed;top:10px;right:12px;z-index:9999;display:flex;gap:10px;"
    "font:600 11.5px/1 system-ui,sans-serif;opacity:.85}"
    "#chrome-nav a{color:inherit;text-decoration:none;padding:5px 9px;border:1px solid currentColor;"
    "border-radius:999px;opacity:.6}#chrome-nav a:hover{opacity:1}"
    "#chrome-nav a.chrome-here{opacity:1;pointer-events:none}"
    "</style><nav id=\"chrome-nav\">{links}</nav>"
)


UP_HTML = (
    '<style>/* diagram:up */'
    "#chrome-up{display:inline-flex;align-items:center;gap:6px;margin-right:12px;"
    "font:600 11.5px/1 system-ui,sans-serif;color:inherit;text-decoration:none;"
    "padding:5px 10px;border:1px solid currentColor;border-radius:999px;opacity:.55}"
    "#chrome-up:hover{opacity:1}"
    "#chrome-up .chrome-up-arrow{font-size:13px;line-height:1}"
    "</style>"
)


def data_dir(html_path):
    """Where a served page's build sidecars sit.

    The only place the data/ mirror is worked out: data/ repeats the served
    layout, so a page at stack/api.html reads data/stack/api.*.json.
    """
    return DATA / html_path.resolve().parent.relative_to(DIAGRAMS)


def sidecar(html_path, suffix):
    """One named sidecar of a served page, e.g. sidecar(page, '.notes.json')."""
    return data_dir(html_path) / (html_path.stem + suffix)


def up_target(html_path, diagrams_root):
    """The page one level out, and the box on it this page hangs off.

    A page under stack/ zooms out to a group page that links down to it, or to
    the stack page itself when no group does. The stack page is the top and
    has nothing above it. Returns (href, label) or None.
    """
    stem = html_path.stem
    if html_path.parent == diagrams_root:
        return None

    def title_of(source):
        if source.exists():
            return json.loads(source.read_text())["meta"].get("title")
        return None

    parent_data = data_dir(html_path)
    top = DATA / "stack.modules.json"
    stack_title = title_of(DATA / "stack.architecture.json") or "The stack"
    is_group = stem.startswith("group-")
    if is_group and top.exists():
        for node, href in json.loads(top.read_text()).items():
            if href.split("/")[-1] == f"{stem}.html":
                return f"../stack.html#focus={node}", stack_title
    # A module page zooms out to a GROUP that holds it, never sideways to a
    # sibling module that happens to link it for context: from a sibling the
    # way back up to the stack is gone.
    module_files = sorted(
        path for path in parent_data.glob("group-*.modules.json")
        if path.name != f"{stem}.modules.json"
    )
    for modules_path in module_files:
        modules = json.loads(modules_path.read_text())
        candidates = [node for node, href in modules.items() if href.split("#")[0] == f"{stem}.html"]
        if not candidates:
            continue
        # several boxes may open the same page; land on the one that names it
        candidates.sort(key=lambda node: (node != stem, node not in stem and stem not in node, node))
        parent_stem = modules_path.name[: -len(".modules.json")]
        label = title_of(parent_data / f"{parent_stem}.architecture.json") or "Back"
        return f"{parent_stem}.html#focus={candidates[0]}", label
    if top.exists():
        for node, href in json.loads(top.read_text()).items():
            if href.split("/")[-1] == f"{stem}.html":
                return f"../stack.html#focus={node}", stack_title
    # a page nothing draws is homeless, which linkmap.py says out loud; until
    # it is given a home the stack is still the way out
    return "../stack.html", stack_title


def up_block(html_path, diagrams_root):
    target = up_target(html_path, diagrams_root)
    if not target:
        return ""
    href, label = target
    return (UP_HTML + f'<a id="chrome-up" href="{href}" title="one level out">'
            f'<span class="chrome-up-arrow">&#8598;</span>{label}</a>')


def nav_block(stem, rel=""):
    links = "".join(
        f'<a href="{rel}{page}.html"{" class=\"chrome-here\"" if page == stem and not rel else ""}>{title}</a>'
        for page, title in NAV_PAGES
    )
    return NAV_HTML.replace("{links}", links)


PRESENT_JS = (
    "<script>/* diagram:present-default */try{"
    "if(new URLSearchParams(location.search).get('present')!=='0')"
    "{document.documentElement.setAttribute('data-present','true')}"
    "}catch(e){}</script>"
)

NOTES_JS = r"""<script>/* diagram:node-notes */(function () {
  var NOTES = __NOTES__;
  var idEl = document.getElementById('focus-id');
  var meta = document.getElementById('focus-passport-meta');
  if (!idEl || !meta) return;
  var note = document.createElement('p');
  note.id = 'chrome-note';
  note.style.cssText = 'margin:10px 0 0;font-size:13.5px;line-height:1.6;' +
    'max-width:100%;white-space:normal;color:inherit;opacity:.88';
  // A note is written in the shape the redraw brief fixes: a name line, prose,
  // then a bolded "Watch out". Rendering it as plain text showed the asterisks.
  var esc = function (raw) {
    return raw.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  };
  var render = function (raw) {
    return esc(raw).split(/\n\s*\n/).map(function (para) {
      return '<span style="display:block;margin:0 0 9px">' +
        para.replace(/\n/g, '<br>')
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/`([^`]+)`/g,
              '<code style="font-size:.92em;font-family:ui-monospace,monospace">$1</code>') +
        '</span>';
    }).join('');
  };
  var ref = document.createElement('a');
  ref.id = 'chrome-note-ref';
  ref.target = '_blank';
  ref.rel = 'noopener';
  ref.style.cssText = 'display:inline-block;margin:7px 12px 0 0;font-size:11.5px;' +
    'color:inherit;opacity:.65;text-decoration:underline';
  var mod = document.createElement('a');
  mod.id = 'chrome-note-mod';
  mod.style.cssText = 'display:none;margin:7px 0 0;font-size:11.5px;font-weight:700;' +
    'color:inherit;opacity:.8;text-decoration:none;border:1px solid currentColor;' +
    'border-radius:999px;padding:2px 10px';
  meta.parentNode.insertBefore(note, meta.nextSibling);
  meta.parentNode.insertBefore(ref, note.nextSibling);
  meta.parentNode.insertBefore(mod, ref.nextSibling);
  var sync = function () {
    var entry = NOTES[(idEl.textContent || '').trim()] || {};
    note.innerHTML = entry.t ? render(entry.t) : '';
    note.hidden = !entry.t;
    if (entry.u) {
      ref.href = entry.u;
      ref.textContent = 'bible: ' + entry.l;
      ref.style.display = 'inline-block';
    } else {
      ref.style.display = 'none';
      ref.removeAttribute('href');
      ref.textContent = '';
    }
    if (entry.m) {
      mod.href = entry.m;
      mod.textContent = __MODLABEL__;
      mod.style.display = 'inline-block';
    } else {
      mod.style.display = 'none';
      mod.removeAttribute('href');
      mod.textContent = '';
    }
  };
  new MutationObserver(sync).observe(idEl, { childList: true, characterData: true, subtree: true });
  sync();
})();</script>"""


def main(path, authors, date):
    html_path = pathlib.Path(path).resolve()
    diagrams_root = DIAGRAMS
    rel = "../" if html_path.parent != diagrams_root else ""
    text = html_path.read_text()
    if MARKER not in text:
        text = text.replace("</head>", CSS + "</head>", 1)
    if "diagram:present-default" not in text:
        text = text.replace("</head>", PRESENT_JS + "</head>", 1)
    text = re.sub(r"<script>/\* diagram:edge-label-colour \*/.*?</script>", "", text, flags=re.S)
    text = text.replace("</body>", LABEL_COLOUR_JS + "</body>", 1)
    # only a page the builder wrote steps for can be told; the rest stay still
    text = re.sub(rf"<style>/\* {SLIDES_MARKER} \*/.*?</style>", "", text, flags=re.S)
    text = re.sub(r"<script>/\* diagram:slides-player \*/.*?</script>", "", text, flags=re.S)
    slides_path = sidecar(html_path, ".slides.json")
    if slides_path.exists():
        text = text.replace("</head>", SLIDES_CSS + "</head>", 1)
        text = text.replace(
            "</body>",
            SLIDES_JS.replace("__SLIDES__", json.dumps(json.loads(slides_path.read_text())))
            + "</body>",
            1,
        )
    text = re.sub(
        r'(<p class="subtitle">)[^<]*(</p>)',
        rf"\g<1>{authors} · last updated {date}\g<2>",
        text,
        count=1,
    )
    # rewritten every run, so adding a page to NAV_PAGES reaches every page
    text = re.sub(r'<style>/\* diagram:nav \*/.*?</nav>', "", text, flags=re.S)
    text = text.replace("</body>", nav_block(html_path.stem, rel) + "</body>", 1)
    # zoom out: sits left of the page title, so a reader can climb back up
    # without going through the browser's own back button
    text = re.sub(r'<style>/\* diagram:up \*/.*?</a>', "", text, flags=re.S)
    up = up_block(html_path, diagrams_root)
    if up:
        text = text.replace('<div class="header-row">', '<div class="header-row">' + up, 1)
    notes_path = sidecar(html_path, ".notes.json")
    text = re.sub(r"<script>/\* diagram:node-notes \*/.*?</script>", "", text, flags=re.S)
    if notes_path.exists():
        sys.path.insert(0, str(TOOLS))
        # The payload is defined once, next to the checker that reads it back
        # out of the delivered page. Baking one shape here and checking another
        # there is the drift this pair exists to catch.
        from linkmap import node_notes

        notes = json.loads(notes_path.read_text())
        links_path = sidecar(html_path, ".links.json")
        links = json.loads(links_path.read_text()) if links_path.exists() else {}
        modules_path = sidecar(html_path, ".modules.json")
        modules = json.loads(modules_path.read_text()) if modules_path.exists() else {}
        payload = node_notes(notes, links, modules, html_path.parent, html_path.stem)
        script = (NOTES_JS.replace("__NOTES__", json.dumps(payload))
                  .replace("__MODLABEL__", json.dumps("open the module map →")))
        text = text.replace("</body>", script + "</body>", 1)
    html_path.write_text(text)
    print(f"patched: {path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
