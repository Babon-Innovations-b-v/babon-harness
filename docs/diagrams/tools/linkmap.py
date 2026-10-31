#!/usr/bin/env python3
"""Keep docs/bible.md and the served diagrams pointing at each other.

One source of truth: the diamond markers written into the bible's section
bodies. A marker looks like

    [◈](diagrams/stack/deploy.html#focus=gate)

with the address of the published site in front when ``BIBLE_BASE_URL`` is
set (``https://docs.example.org/diagrams/...``), and it says "this sentence is about that box". From those markers this tool

- writes every page's `<page>.links.json` (node -> chapter + section), which
  is what puts the "bible: chapter § section" line into the box popup, so the
  popup always points at the section that actually talks about the box;
- regenerates `docs/diagrams/tools/linkmap.md`, the readable index of both
  directions;
- validates the pair: a marker must name a box that exists, every box must be
  claimed by exactly one marker, and every module link must open a page that
  was actually built;
- validates the shape of the set itself, because the way a reader moves through
  it is not visible from any one page: every page hangs under one a level out,
  the back button of every delivered page lands on a page that links down to
  it, and nothing is reachable only sideways;
- validates that the set is not merely well shaped but current: the popup is
  baked into each .html at delivery, so a page not re-delivered after a sidecar
  edit serves text and bible links that have been superseded, and a bible
  sentence rewritten under a box leaves nobody having checked that the box
  still matches it.

`--restamp page#box ...` records that those boxes have been read against their
new sentences and their new code, by copying the live sentence back into the
spec. It changes no drawing and no bible text; all it moves is the record of who
looked. Name the boxes you actually read: a bare `--restamp` stamps every one,
which signs off drawings somebody else's commit drifted and nobody opened.

An empty set is a clean set: with no page drawn yet the tool checks the bible's
markers (there must be none) and exits 0.

Exit 0 = clean (links + index rewritten); exit 2 = validation errors printed.
A hook (.claude/hooks/local/linkmap_sync.py) runs it whenever bible.md or
docs/diagrams/ changes. Pages whose links.json changed are listed on stdout:
re-deliver those with docs/diagrams/tools/deliver.sh so the popups catch up.
"""
import hashlib
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DIAGRAMS = ROOT / "docs" / "diagrams"
# Sources and sidecars sit under data/, mirroring the served page layout, so
# only the .html files live in the directory the bible image copies.
DATA = DIAGRAMS / "data"
# The facts each page was drawn from, including the bible sentence its author
# proposed for every box. build_free.py owns the naming; spec_for inverts it.
SPECS = DIAGRAMS / "specs"
BIBLE = ROOT / "docs" / "bible.md"
# The top page. Every other page is found by clicking down from it.
PAGES = ("stack",)
#: Where the published docs/ tree lives, from the owner's config/harness.env.
#: Empty means relative links: a marker is written ``diagrams/<page>.html`` from
#: docs/bible.md, and a popup reaches the bible relative to its own page.
SITE = os.environ.get("BIBLE_BASE_URL", "").rstrip("/")
# Read either form, so a marker written before the address was set, or after it
# changed, is still recognised; MARKER_PREFIX is the form this tool writes.
MARKER = re.compile(r"\[◈\]\((?:[^()\s]*/)?diagrams/([\w/-]+)\.html#focus=([\w-]+)\)")
MARKER_PREFIX = f"{SITE}/diagrams/" if SITE else "diagrams/"

# Where a reader starts. The top pages hang off nothing, which is what makes
# them tops: in the developer set they are the four in the nav bar on every
# page, and a set brings its own. Everything else has to be found by clicking
# down from one of them.
TOPS = set(PAGES)
# A set is a second family of diagrams with its own top page and its own
# reader: directory -> the page that family starts from.
SET_TOPS = {top.rpartition("/")[0]: top for top in PAGES if "/" in top}
# Pages that hang off nothing on purpose, and why. An entry here is a decision
# someone made; a page missing from here and claimed by nothing is an accident,
# which is the whole point of writing the deliberate ones down.
UNLINKED: dict[str, str] = {}
# The zoom-out button strip-chrome.py writes into every delivered page. Read
# from the .html rather than recomputed here: the delivered page is what the
# reader clicks, so a page left behind by a change to up_target is caught
# instead of being agreed with.
UP_LINK = re.compile(r'<a id="chrome-up"[^>]*? href="([^"]+)"')
# The words on that button: the parent's title, baked in at delivery. Renaming a
# page therefore leaves every page under it saying the old name until it is
# re-delivered.
UP_TEXT = re.compile(r'<a id="chrome-up".*?</span>([^<]*)</a>', re.S)
# The popup payload strip-chrome.py bakes into a delivered page. The diagram
# tests match on the same anchor, so the two read the same thing.
BAKED = re.compile(r"var NOTES = (\{.*?\});\n", re.S)


def slug(text):
    text = re.sub(r"[^a-z0-9\s-]", "", text.lower())
    return re.sub(r"[\s-]+", "-", text).strip("-")


def bible_url(chapter, section=None, page_dir=None):
    """Where a popup sends a reader: the bible heading that explains the box.

    The anchor is the heading slug a markdown renderer gives it, so
    ``## architecture/system-context`` is ``#architecturesystem-context``. With
    ``BIBLE_BASE_URL`` set the link is absolute; without it the link is relative
    to the delivered page in ``page_dir``, which sits under docs/diagrams/.
    """
    anchor = slug(section or chapter)
    if SITE:
        return f"{SITE}/bible.md#{anchor}"
    depth = 1
    if page_dir is not None:
        try:
            depth += len(pathlib.Path(page_dir).resolve().relative_to(DIAGRAMS).parts)
        except ValueError:
            pass
    return f"{'../' * depth}bible.md#{anchor}"


def parse_bible():
    """Chapters, their sections, and where every marker sits."""
    chapters = {}
    chapter = section = None
    for number, line in enumerate(BIBLE.read_text().splitlines(), start=1):
        if line.startswith("## "):
            chapter, section = line[3:].strip(), None
            chapters[chapter] = {"sections": [], "markers": []}
        elif line.startswith("### ") and chapter:
            section = line[4:].strip()
            chapters[chapter]["sections"].append(section)
        if chapter:
            for page, node in MARKER.findall(line):
                chapters[chapter]["markers"].append(
                    {"page": page, "node": node, "section": section, "line": number})
    return chapters


def page_dirs(page):
    """A page name -> (where its sidecars sit, where its .html sits).

    The only place the data/ mirror is worked out. A page is named by its
    served path without the suffix ("stack", "stack/deploy"),
    so the same relative parent addresses both trees.
    """
    rel = pathlib.PurePosixPath(page)
    return DATA / rel.parent, DIAGRAMS / rel.parent


def load_page(page):
    data_dir, page_dir = page_dirs(page)
    stem = pathlib.PurePosixPath(page).name
    source = data_dir / f"{stem}.workflow.json"
    if not source.exists():
        source = data_dir / f"{stem}.architecture.json"
    data = json.loads(source.read_text())
    nodes = {n["id"]: n["label"] for n in data.get("nodes") or data["components"]}
    modules_path = data_dir / f"{stem}.modules.json"
    modules = json.loads(modules_path.read_text()) if modules_path.exists() else {}
    # None, not {}, so "this page has no notes sidecar" stays different from
    # "its sidecar is empty": the first expects no popup block in the .html,
    # the second expects an empty one.
    notes_path = data_dir / f"{stem}.notes.json"
    notes = json.loads(notes_path.read_text()) if notes_path.exists() else None
    code_path = data_dir / f"{stem}.code.json"
    code = json.loads(code_path.read_text()) if code_path.exists() else {}
    return {"nodes": nodes, "links": {}, "modules": modules, "notes": notes,
            "code": code, "data": data_dir, "dir": page_dir, "stem": stem}


def stems_in(data_dir):
    """Every page stem that has a drawing source in this data directory."""
    stems = []
    for suffix in (".workflow.json", ".architecture.json"):
        stems += [source.name[: -len(suffix)] for source in sorted(data_dir.glob(f"*{suffix}"))]
    return stems


def load_pages():
    pages = {}
    set_names = set()
    for page in PAGES:
        parent, _, stem = page.rpartition("/")
        data_dir = page_dirs(page)[0]
        if not stems_in(data_dir) or stem not in stems_in(data_dir):
            continue  # not drawn yet: an empty set is a clean set
        if parent:
            set_names.add(parent)
        pages[page] = load_page(page)
        # module sub-diagrams live in a dir named after the parent page
        subdir = page_dirs(page)[0] / stem
        if subdir.is_dir():
            for name in stems_in(subdir):
                pages[f"{page}/{name}"] = load_page(f"{page}/{name}")
    # inside a set directory the deeper pages sit flat beside the top page, the
    # way the stack's group pages do, so every source in there is a page
    for set_name in set_names:
        for name in stems_in(DATA / set_name):
            pages.setdefault(f"{set_name}/{name}", load_page(f"{set_name}/{name}"))
    return pages


def collect_links(chapters, pages):
    """node -> {chapter, section} for every marker, plus the errors found."""
    errors = []
    claimed = {}
    for chapter, info in chapters.items():
        for mark in info["markers"]:
            page, node = mark["page"], mark["node"]
            where = f"bible.md:{mark['line']}"
            if page not in pages:
                errors.append(f"{where}: marker names unknown page '{page}'")
                continue
            if node not in pages[page]["nodes"]:
                errors.append(f"{where}: marker names unknown box '{page}#{node}'")
                continue
            if not mark["section"]:
                errors.append(f"{where}: marker for '{page}#{node}' sits outside any section")
                continue
            key = (page, node)
            if key in claimed:
                errors.append(
                    f"{where}: '{page}#{node}' already claimed at bible.md:{claimed[key]['line']}")
                continue
            claimed[key] = {"chapter": chapter, "section": mark["section"], "line": mark["line"]}
    return claimed, errors


def missing_markers(pages, claimed):
    errors = []
    for page, info in pages.items():
        loose = [node for node in info["nodes"] if (page, node) not in claimed]
        if loose:
            errors.append(f"{page}: boxes no bible sentence claims: {sorted(loose)}")
    return errors


def dead_modules(pages):
    errors = []
    for page, info in pages.items():
        for node, href in info["modules"].items():
            if node not in info["nodes"]:
                errors.append(f"{page}.modules.json: unknown node id '{node}'")
                continue
            if not (info["dir"] / href.split("#")[0]).exists():
                errors.append(f"{page}.modules.json {node}: '{href}' does not exist")
    return errors


def dead_code(pages):
    """Boxes naming code that is not in the checkout.

    A box may say which files it draws. Nothing can work that out on its own:
    a box id rarely matches exactly one file name, so a guess is wrong more
    often than it is right. An authored path is the only kind that is right.

    An authored path also rots, because files get renamed. This is what stops
    it. The rule is the same one
    dead_modules applies to a link down: what is named has to exist, and the
    person who renames the file is the person told about it.

    Only paths, never line numbers. A line number would be wrong within a week
    and would teach everybody to ignore the check.
    """
    errors = []
    for page, info in sorted(pages.items()):
        for node, paths in sorted(info["code"].items()):
            if node not in info["nodes"]:
                errors.append(f"{page}.code.json: unknown node id '{node}'")
                continue
            for path in paths:
                if not (ROOT / path).exists():
                    errors.append(
                        f"{page}.code.json {node}: '{path}' is not in the checkout")
    return errors


def resolve(page, href):
    """The page a module link opens, named the way `pages` names it.

    A link is written relative to the page that carries it, so the stack page's
    "stack/api.html" and group-app's "api.html" have to come out as the one
    page they both open: stack/api.
    """
    parts = list(pathlib.PurePosixPath(page).parent.parts)
    for part in pathlib.PurePosixPath(href.split("#")[0]).parts:
        if part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    target = "/".join(parts)
    return target[: -len(".html")] if target.endswith(".html") else target


def click_downs(pages):
    """(what each page opens, what opens each page), both keyed by page name.

    Links to something that is not a drawn page are left out on purpose: a link
    to nothing at all is dead_modules' finding, and one to a hand-written page
    like a set index or a moved-notice is not a way down into the set.
    """
    opens = {page: set() for page in pages}
    opened_by = {page: set() for page in pages}
    for page, info in pages.items():
        for href in info["modules"].values():
            target = resolve(page, href)
            if target in pages and target != page:
                opens[page].add(target)
                opened_by[target].add(page)
    return opens, opened_by


def set_of(page):
    """The set directory a page lives in, or None for the developer set."""
    parent = page.rpartition("/")[0]
    return parent if parent in SET_TOPS else None


def is_home(page, claim):
    """True when `claim` is a page this one may hang off.

    The stack set is a tree of varying depth: the map, one page per box on it,
    and a leaf only where a part holds more than six things. So a home is any
    other page of the set that links down to this one, with the map as the
    root.

    A set draws one level, so any other page of that set is above a page of it.
    """
    if set_of(page):
        return claim != page and set_of(claim) == set_of(page)
    return claim != page and (claim == "stack" or claim.startswith("stack/"))


def homeless_pages(pages, opened_by):
    """Every page hangs under one a level out; name the ones that hang under none.

    A module page is claimed by a group page, or by the stack page itself for
    the couple of services it draws directly. A group page is claimed by the
    stack page or by the group it sits inside. A page in a set has one level
    above it, so any other page of that set is a home. A page nothing claims is
    not in the set, it is only next to it: nobody reading downwards ever
    arrives, and it rots unread until someone remembers the link.
    """
    errors = []
    for page in sorted(pages):
        if page in TOPS or page in UNLINKED:
            continue
        claims = opened_by[page]
        if set_of(page):
            missing = f"no other page of the {set_of(page)} set claims it"
        else:
            missing = "no page above it in the stack set links down to it"
        if not any(is_home(page, claim) for claim in claims):
            beside = f", only sideways from {' '.join(sorted(claims))}" if claims else ""
            errors.append(f"{page}: homeless, {missing}{beside}")
    return errors


def way_back(pages):
    """The zoom-out button lands on the page that opens it, one level out.

    Read out of the delivered .html, not recomputed from strip-chrome.py's
    up_target, so the two cannot drift: what the reader clicks is what is
    checked. A button that lands where the reader could not have come from is
    worse than no button, because from a sibling the way up to the stack is
    gone.
    """
    errors = []
    for page, info in sorted(pages.items()):
        html = info["dir"] / f"{info['stem']}.html"
        if not html.exists() or page in TOPS:
            continue  # not delivered yet, or a top page with nothing above it
        match = UP_LINK.search(html.read_text())
        if not match:
            errors.append(f"{page}.html: no zoom-out button, re-run strip-chrome.py")
            continue
        href = match.group(1)
        if not (info["dir"] / href.split("#")[0]).exists():
            errors.append(f"{page}.html: zoom-out to '{href}' does not exist")
            continue
        target = resolve(page, href)
        if target.rpartition("/")[2] == "index":
            continue  # a set index lists every page of its set, drawn or not
        if target not in pages:
            errors.append(f"{page}.html: zoom-out to '{href}', which is not a drawn page")
            continue
        boxes = [node for node, href_down in pages[target]["modules"].items()
                 if resolve(target, href_down) == page]
        if not boxes:
            errors.append(f"{page}.html: zoom-out to '{target}', which never links down to it")
            continue
        if not is_home(page, target):
            # a sibling that links you for context is not a way out
            errors.append(f"{page}.html: zoom-out to '{target}', which is beside it, "
                          f"not one level out")
            continue
        focus = href.partition("#focus=")[2]
        if focus and focus not in boxes:
            errors.append(f"{page}.html: zoom-out lands on '{target}#{focus}', but the box "
                          f"that opens this page is {sorted(boxes)}")
            continue
        said = UP_TEXT.search(html.read_text())
        spec = spec_for(target)
        if not (said and spec):
            continue
        real = json.loads(spec.read_text()).get("title")
        if real and said.group(1).strip() != real:
            errors.append(f"{page}.html: zoom-out is labelled '{said.group(1).strip()}', but "
                          f"'{target}' is called '{real}' now; re-deliver this page")
    return errors


def stranded_pages(pages, opens):
    """Everything is found by clicking down from a top page; say what is not.

    The walk starts at the tops, follows only the links down, and whatever it
    never reaches exists without being part of anything: linked from a sibling
    or from an index, remembered by whoever built it, read by nobody else.
    """
    seen = set()
    walk = [page for page in TOPS if page in pages]
    while walk:
        page = walk.pop()
        if page in seen:
            continue
        seen.add(page)
        walk += sorted(opens[page])
    return [f"{page}: stranded, no click down from "
            f"{SET_TOPS.get(set_of(page), 'stack')}.html reaches it"
            for page in sorted(pages) if page not in seen and page not in UNLINKED]


def spec_for(page):
    """The spec a page was drawn from, or None when it has none.

    build_free.py owns this naming: the spec of page ``stack/deploy`` is
    ``specs/stack/deploy.json``. Inverted here so a page can find the file that
    drew it.
    """
    path = SPECS / f"{page}.json"
    return path if path.exists() else None


def code_fingerprint(paths):
    """One short hash over the files a box says it draws.

    Whole files, never line ranges, for the reason `dead_code` gives about
    line numbers: a range is wrong within a week. Sorted so the answer does
    not depend on the order somebody listed the paths in, and a path that has
    gone contributes nothing rather than raising, because `dead_code` already
    reports that with a better message.
    """
    digest = hashlib.sha256()
    for path in sorted(paths):
        target = ROOT / path
        if target.is_dir():
            # A box may name a package rather than a file. The relative path
            # goes into the hash beside the bytes, so a file added, removed or
            # renamed inside it drifts the box too: for a directory that is
            # most of what "the code changed" means.
            for child in sorted(target.rglob("*")):
                if child.is_file() and "__pycache__" not in child.parts:
                    digest.update(str(child.relative_to(ROOT)).encode())
                    digest.update(child.read_bytes())
        elif target.is_file():
            digest.update(target.read_bytes())
    return digest.hexdigest()[:12]


def drifted_code(pages):
    """Boxes whose CODE moved after the box was drawn.

    This is the half the set was missing, and it is the half that actually
    rots. `restated_claims` catches a bible sentence rewritten under a box,
    and `dead_code` catches a path that has gone. Neither of them says
    anything in the ordinary case: somebody changes what the code DOES and
    touches neither the drawing nor the sentence, so every check stays quiet
    and the picture drifts away from the thing it draws with nothing to show
    for it while the set reports itself clean.

    The rule is `restated_claims`' rule, pointed the other way. The spec keeps
    the fingerprint of the code as it stood when the box was drawn; when the
    code changes, somebody is asked whether the drawing still matches it.
    Whether it does is a judgement no checker can make, and that judgement is
    exactly what this hands back to a person, at the moment they change the
    code rather than months later.

    A box with paths and no fingerprint is an ERROR rather than a skip. A
    check that quietly passes when its record is absent can be switched off by
    deleting a field, which is the same as not having it.

    What `code_seen` records is the reference point, not an audit: "this is
    the code as it stood when somebody last stamped this box". The first stamp
    on an existing box is therefore a baseline rather than a claim that all of
    it was re-read, and the value starts on the change AFTER it. Said plainly
    because the bible half of this file means the stronger thing by the same
    word, and the two should not be confused.

    It is bounded by being opt-in: only a box that names its code in
    `<page>.code.json` is covered. That is the ceiling on how noisy it can be, and widening it is a decision about
    which boxes are worth this, not a decision about the check.
    """
    errors = []
    for page, info in sorted(pages.items()):
        for node, paths in sorted(info["code"].items()):
            if node not in info["nodes"]:
                continue  # dead_code already reports the unknown id
            spec_path = spec_for(page)
            if spec_path is None:
                continue
            spec = json.loads(spec_path.read_text())
            node_spec = (spec.get("nodes") or {}).get(node) or {}
            was = str(node_spec.get("code_seen") or "")
            now = code_fingerprint(paths)
            if not was:
                errors.append(
                    f"{page}#{node}: draws {', '.join(sorted(paths))} but has never "
                    f"been stamped against it. Read the box against that code, "
                    f"then restamp.")
                continue
            if was != now:
                errors.append(
                    f"{page}#{node}: the code this box draws changed "
                    f"({', '.join(sorted(paths))}). Re-read the box against it, "
                    f"then restamp.")
    return errors


def claimed_sentence(page, node):
    """The bible sentence the spec proposed for this box when it was drawn."""
    path = spec_for(page)
    if path is None:
        return ""
    spec = json.loads(path.read_text())
    node_spec = (spec.get("nodes") or {}).get(node) or {}
    return str(node_spec.get("bible") or "").strip()


def restated_claims(claimed):
    """Boxes whose claiming sentence was rewritten after the box was drawn.

    The marker only says which sentence claims which box. It keeps saying that
    while the sentence underneath it is rewritten, so the pair the author
    agreed on comes apart with nothing to show for it: a validator proves a
    chapter exists and never that it says what the box claims.

    The spec each page was drawn from keeps the sentence its author proposed.
    That is not a second source of truth, the bible is: it is a record of what
    the box was agreed to mean, so that when the sentence changes, somebody is
    asked whether the drawing still matches it. What cannot be checked
    mechanically is whether the new sentence and the box still say the same
    thing, and that is exactly the judgment this hands back to a person, at the
    moment they make the edit rather than months later.

    Rewriting a sentence is therefore not an error to be avoided; leaving the
    box unexamined afterwards is. `linkmap.py --restamp` records the answer.
    """
    lines = BIBLE.read_text().splitlines()
    errors = []
    for (page, node), claim in sorted(claimed.items()):
        was = claimed_sentence(page, node)
        if not was:
            continue  # a box whose spec proposed no sentence has nothing to drift
        now = lines[claim["line"] - 1]
        if was in now:
            continue
        errors.append(
            f"{page}#{node}: the sentence claiming this box was rewritten "
            f"(bible.md:{claim['line']}). Re-read the box against it, then "
            f"restamp. Now: {now.strip()[:150]}")
    return errors


def restamp(claimed, only=()):
    """Record that each drifted box has been read against its new sentence.

    Writes the live sentence back into the spec, without the marker, which is
    the shape draw_module wrote in the first place. It changes no drawing and
    no bible text: all it does is move the record of "somebody looked" forward,
    so the next rewrite is visible again.

    `only` narrows it to the named `page#box` boxes; see `restamp_code`.
    """
    lines = BIBLE.read_text().splitlines()
    done = []
    for (page, node), claim in sorted(claimed.items()):
        if only and f"{page}#{node}" not in only:
            continue
        was = claimed_sentence(page, node)
        now = lines[claim["line"] - 1]
        if not was or was in now:
            continue
        path = spec_for(page)
        spec = json.loads(path.read_text())
        node_spec = (spec.get("nodes") or {}).get(node)
        if not isinstance(node_spec, dict):
            continue  # the spec no longer draws this box; the drawing is the fault
        node_spec["bible"] = sentence_of(now, page, node)
        # The same shape the diagram MCP's write_spec writes, so a
        # restamped file is byte-identical to a redrawn one apart from the text.
        path.write_text(json.dumps(spec, indent=1) + "\n")
        done.append(f"{page}#{node}")
    return done


def restamp_code(pages, only=()):
    """Record that each box has been read against the code it draws.

    The other half of `restamp`, kept separate because it answers a different
    question and runs over a different set: every box that NAMES code, not
    every box whose sentence moved.

    `only` narrows it to the named `page#box` boxes, and naming them is the
    honest form of this command. A bare `--restamp` says "I have read every
    drifted drawing", and one person rarely has.
    """
    done = []
    for page, info in sorted(pages.items()):
        for node, paths in sorted(info["code"].items()):
            if node not in info["nodes"]:
                continue
            if only and f"{page}#{node}" not in only:
                continue
            path = spec_for(page)
            if path is None:
                continue
            spec = json.loads(path.read_text())
            node_spec = (spec.get("nodes") or {}).get(node)
            if not isinstance(node_spec, dict):
                continue  # the spec no longer draws this box
            now = code_fingerprint(paths)
            if node_spec.get("code_seen") == now:
                continue
            node_spec["code_seen"] = now
            path.write_text(json.dumps(spec, indent=1) + "\n")
            done.append(f"{page}#{node}")
    return done


def sentence_of(line, page, node):
    """The claiming sentence on a bible line: the text ending at its marker.

    A marker is written directly after the sentence it claims, so the sentence
    is what sits between the previous marker (or the start of the line) and
    this one. Leading list numbering and bold run-ins stay: they are part of
    what the reader sees, and stripping them would be this tool having an
    opinion about the bible's prose.
    """
    hit = next((found for found in MARKER.finditer(line)
                if found.groups() == (page, node)), None)
    head = line[: hit.start()] if hit else line
    # Cut on the previous marker, not on the previous ")": an ordinary markdown
    # link earlier in the sentence ends in one too, and cutting there would
    # hand back half a sentence. Markers sitting directly against ours claim
    # the same sentence we do, so they are stepped over rather than cut on: a
    # blank record is a box this check would then never look at again.
    while True:
        previous = list(MARKER.finditer(head))
        if not previous:
            break
        last = previous[-1]
        if head[last.end():].strip():
            head = head[last.end():]
            break
        head = head[: last.start()]
    return head.strip()


def plan_links(pages, claimed):
    """Work out every page's node -> chapter+section, without writing anything.

    Split out of write_links so the delivery check can compare a served page
    against what the markers say today, including in a run that ends in errors
    and writes nothing. The two used to be one function, which made "is this
    page behind its sidecar" answerable only after the sidecar had already been
    rewritten.
    """
    for _page, info in pages.items():
        links = {node: {"chapter": claim["chapter"], "section": claim["section"]}
                 for (claim_page, node), claim in claimed.items() if claim_page == _page}
        info["links"] = dict(sorted(links.items()))


def node_notes(notes, links, modules, page_dir, stem):
    """The {node: entry} popup payload a delivered page carries.

    The one definition of that payload. strip-chrome.py bakes it into the
    .html; stale_deliveries() rebuilds it from the sidecars and compares. Two
    copies of this logic would be a hand-maintained join between the baker and
    the checker, which is the exact kind of drift the checker exists to catch.

    Keys are short because they ship inside every page: t is the note, u and l
    the bible link and its label, m the page the box opens.
    """
    payload = {}
    module_dir = page_dir / stem
    for node, text in notes.items():
        entry = {"t": text}
        link = links.get(node)
        if link:
            entry["u"] = bible_url(link["chapter"], link.get("section"), page_dir)
            entry["l"] = link["chapter"] + (f" § {link['section']}" if link.get("section") else "")
        if node in modules:
            entry["m"] = modules[node]
        elif (module_dir / f"{node}.html").exists():
            entry["m"] = f"{stem}/{node}.html"
        payload[node] = entry
    return payload


def stale_deliveries(pages):
    """Served pages that no longer say what their sidecars say.

    The popup is baked into the .html at delivery, so every sidecar edit leaves
    the served page stale until someone re-delivers it, so this checks for
    that on every run rather than once, when the links.json moves. The bible
    link is the half that sends a reader somewhere wrong rather than merely
    showing them something old.
    """
    errors = []
    for page, info in sorted(pages.items()):
        html = info["dir"] / f"{info['stem']}.html"
        if info["notes"] is None or not html.exists():
            continue  # nothing is baked into it, or it is not delivered yet
        match = BAKED.search(html.read_text())
        if not match:
            errors.append(f"{page}.html: no popup block, re-run strip-chrome.py")
            continue
        try:
            shown = json.loads(match.group(1))
        except json.JSONDecodeError as broken:
            errors.append(f"{page}.html: the popup block does not parse ({broken})")
            continue
        want = node_notes(info["notes"], info["links"], info["modules"],
                          info["dir"], info["stem"])
        behind = [node for node in sorted(set(want) | set(shown))
                  if shown.get(node) != want.get(node)]
        if behind:
            errors.append(
                f"{page}.html: behind its sidecars on {' '.join(behind)}; re-deliver it with "
                f"docs/diagrams/tools/strip-chrome.py")
    return errors


def write_links(pages, claimed):
    """Rewrite every links.json from the plan. Returns the pages that moved."""
    changed = []
    for page, info in pages.items():
        path = info["data"] / f"{info['stem']}.links.json"
        body = json.dumps(info["links"], indent=1, sort_keys=True) + "\n"
        if not path.exists() or path.read_text() != body:
            path.write_text(body)
            changed.append(page)
    return changed


def index_page(page):
    """A page's address as written in linkmap.md, which sits in tools/."""
    return f"{SITE}/diagrams/{page}.html" if SITE else f"../{page}.html"


def index_bible(heading):
    """A bible heading's address as written in linkmap.md."""
    return f"{SITE}/bible.md#{slug(heading)}" if SITE else f"../../bible.md#{slug(heading)}"


def write_index(chapters, pages):
    lines = [
        "# Link map: bible <-> diagrams",
        "",
        "Auto-generated by `docs/diagrams/tools/linkmap.py` from the ◈ markers in",
        "`docs/bible.md`; a hook regenerates it when the bible or the diagrams",
        "change. Do not edit by hand.",
        "",
        "## Diagram box -> bible",
        "",
        "| Page | Box | Bible |",
        "|---|---|---|",
    ]
    ordered = [p for p in PAGES if p in pages] + sorted(p for p in pages if p not in PAGES)
    for page in ordered:
        info = pages[page]
        for node in info["nodes"]:
            link = info["links"].get(node)
            if not link:
                lines.append(f"| {page} | `{node}` | (none) |")
                continue
            target = f"{link['chapter']} § {link['section']}"
            lines.append(
                f"| {page} | [`{node}`]({index_page(page)}#focus={node})"
                f" | [{target}]({index_bible(link['section'] or link['chapter'])}) |")
    lines += ["", "## Bible section -> diagram boxes", "", "| Chapter | Section | Boxes |",
              "|---|---|---|"]
    for chapter, info in chapters.items():
        by_section = {}
        for mark in info["markers"]:
            by_section.setdefault(mark["section"], []).append(mark)
        for section, marks in by_section.items():
            cells = " · ".join(
                f"[{mark['page']}#{mark['node']}]"
                f"({index_page(mark['page'])}#focus={mark['node']})" for mark in marks)
            lines.append(f"| {chapter} | {section or '(top)'} | {cells} |")
    (HERE / "linkmap.md").write_text("\n".join(lines) + "\n")


def main(argv=()):
    chapters = parse_bible()
    pages = load_pages()
    claimed, errors = collect_links(chapters, pages)
    errors += missing_markers(pages, claimed)
    errors += dead_modules(pages)
    errors += dead_code(pages)
    opens, opened_by = click_downs(pages)
    errors += homeless_pages(pages, opened_by)
    errors += way_back(pages)
    errors += stranded_pages(pages, opens)
    if errors:
        for err in errors:
            print(f"linkmap: {err}", file=sys.stderr)
        return 2
    # Only once the markers check out are the links worth comparing a served
    # page against: one unclaimed box would make every page drawing it look
    # behind, and a cascade of wrong errors is how a checker gets ignored.
    if "--restamp" in argv:
        # Anything after `--restamp` names the boxes actually re-read, as
        # `page#box`. With none, every box is stamped, which is the old
        # behaviour and is only honest when one person has read them all.
        only = tuple(
            argument
            for argument in argv[argv.index("--restamp") + 1:]
            if not argument.startswith("-")
        )
        unknown = [
            box for box in only
            if box.rsplit("#", 1)[0] not in pages
        ]
        if unknown:
            print(f"linkmap: no such page for {' '.join(unknown)}", file=sys.stderr)
            return 2
        stamped = restamp(claimed, only) + restamp_code(pages, only)
        print(f"linkmap: restamped {len(stamped)} boxes"
              + (": " + " ".join(stamped) if stamped else ""))
    plan_links(pages, claimed)
    behind = stale_deliveries(pages) + restated_claims(claimed) + drifted_code(pages)
    changed = write_links(pages, claimed)
    write_index(chapters, pages)
    print(f"linkmap: ok, {len(claimed)} boxes claimed, index rewritten")
    if changed:
        print("linkmap: re-deliver these pages: " + " ".join(sorted(changed)))
    if behind:
        for err in behind:
            print(f"linkmap: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
