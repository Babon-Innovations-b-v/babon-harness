#!/usr/bin/env python3
"""PreToolUse guard: keep bare issues, a broken issue tree and destructive git off the main line.

Reads the Claude Code PreToolUse payload on stdin (``{tool_name, tool_input, ...}``) and blocks:

1. Destructive git via Bash (``git push --force``, ``-f``, ``--force-with-lease``, a ``+`` refspec, ``git reset
   --hard``). The repository works on ``main`` only, so a force-push rewrites the one branch every clone is on.
   Matched on shell tokens, so a force pattern quoted inside a commit message never trips it.
2. A bare issue creation (``gh issue create`` or ``mcp__github__create_issue``): every issue needs an assignee and
   ``PRD`` or a category (``bug``/``enhancement``), plus an area label (``<area_label_prefix><area>``) when
   ``.claude/project.json`` lists ``areas``. An issue with no assignee is invisible on the board, where the backlog
   lives. The to-prd and triage skills fill these in, so only hand-rolled creations are blocked.
3. A new issue's body carrying rot: a ``.md`` line-number citation (``x.md line N``, ``L N``, ``:N``; prose line
   numbers rot within hours, code refs like ``file.py:123`` stay allowed), a cited path under one of the project's
   ``cited_paths_must_exist`` prefixes that does not exist in the tree, and an issue in an area listed under
   ``area_first_line`` that lacks the bold line that area requires.
4. A creation that breaks the issue tree's shape. The board is a forest: PRD-labelled roots, three layers at most,
   one root per subject. A ``PRD`` label together with a ``## Parent`` section is refused, and a new PRD must carry a
   ``## Root check`` section that names any open root already covering its subject. See ``_check_prd_root``.

Every repo-specific value (repo slug, area prefix and names, standing backlog PRDs, body rules) comes from
``.claude/project.json`` beside the hooks; nothing is hard-coded here. Only creations are checked, never edits.

FAILURE POLICY: fail-open. Any parse error, unknown shape, or unrelated call exits 0 (allow): a crashing guard must
never wedge a tool call. Exit 2 + stderr is the only block path (the harness feeds stderr back as the block reason).
"""

import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import time

_CATEGORIES = ("PRD", "bug", "enhancement")
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / ".claude" / "project.json"
_DEFAULT_AREA_PREFIX = "area:"

# .md only: prose line numbers rot within hours. Code `file.py:123` references stay allowed, they are the house
# citation format for code.
_LINE_NUMBER_REF = re.compile(r"\.md`?\s*(?::\d+|\(?(?:L|line\s+|regel\s+)\d+)", re.IGNORECASE)
_GH_FLAGS = {"--label": "label", "-l": "label", "--assignee": "assignee", "-a": "assignee",
             "--body": "body", "-b": "body", "--body-file": "body_file", "-F": "body_file",
             "--title": "title", "-t": "title"}

_ISSUE_HELP = (
    "BLOCKED: bare issue creation.\n"
    "Every issue needs an assignee and either PRD (epic) or a category "
    "(bug/enhancement){area_rule}.\n"
    "Missing: {missing}.\n"
    "Route through the skills instead of a raw create: /to-prd (a PRD or a sub-issue "
    "under one), or /triage. They fill labels and assignee for you.\n"
    "Or re-run adding: --assignee <login> --label <PRD|bug|enhancement>{area_hint}.\n"
    "(CLAUDE.md: every issue gets an assignee at creation; triage state lives in labels.)"
)


def _config():
    """The parsed .claude/project.json, or {} when it is missing or unreadable."""
    try:
        return json.loads(_CONFIG_PATH.read_text()) or {}
    except Exception:
        return {}


def _areas(config):
    """The area names the project lists, or [] when it has none."""
    return [str(area) for area in config.get("areas") or []]


def _area_prefix(config):
    """The label prefix an area label carries (``area:`` unless the project says otherwise)."""
    return str(config.get("area_label_prefix") or _DEFAULT_AREA_PREFIX)


def _block(message):
    print(message, file=sys.stderr)
    sys.exit(2)


def _missing(labels, has_assignee, config):
    """What a would-be issue is missing, as human phrases."""
    joined = " ".join(labels)
    missing = [] if has_assignee else ["assignee"]
    areas, prefix = _areas(config), _area_prefix(config)
    if areas and not re.search(rf"{re.escape(prefix)}({'|'.join(re.escape(area) for area in areas)})\b", joined):
        missing.append(f"an {prefix}<x> label")
    if not any(re.search(rf"(^|[\s,]){re.escape(category)}($|[\s,])", joined) for category in _CATEGORIES):
        missing.append("a PRD or bug/enhancement label")
    return missing


def _check_labels(labels, has_assignee, config):
    """Block a new issue that lacks an assignee, a category or (when the project has areas) an area label."""
    missing = _missing(labels, has_assignee, config)
    if not missing:
        return
    areas, prefix = _areas(config), _area_prefix(config)
    rule = f", and one {prefix}<x> label" if areas else ""
    hint = f" --label {prefix}<{'|'.join(areas)}>" if areas else ""
    _block(_ISSUE_HELP.format(missing=", ".join(missing), area_rule=rule, area_hint=hint))


def _check_dead_paths(body, config):
    """Block a body citing a path under a ``cited_paths_must_exist`` prefix that the tree does not hold."""
    for prefix in config.get("cited_paths_must_exist") or []:
        pattern = re.compile(re.escape(str(prefix)) + r"[\w\-./]+\.\w{2,4}")
        dead = sorted(path for path in set(pattern.findall(body)) if not (_REPO_ROOT / path).exists())
        if dead:
            _block(f"BLOCKED: issue body cites {prefix} paths that do not exist on main:\n  " + "\n  ".join(dead)
                   + "\nPaths move when the docs restructure; cite the path as it is in the tree right now "
                   "(check with ls), or drop the citation.")


def _check_line_numbers(body):
    """Block a body citing a markdown file by line number."""
    line_refs = _LINE_NUMBER_REF.findall(body)
    if line_refs:
        _block("BLOCKED: issue body cites file line numbers (" + ", ".join(ref.strip() for ref in line_refs[:3])
               + "). Line numbers in prose rot within hours; cite a section heading or a quoted phrase instead.")


def _check_area_first_line(body, labels, config):
    """Block an issue in an area that requires a bold first line (``area_first_line``) when the body lacks it."""
    joined = " ".join(labels)
    prefix = _area_prefix(config)
    for area, rule in (config.get("area_first_line") or {}).items():
        if not re.search(rf"{re.escape(prefix)}{re.escape(str(area))}\b", joined):
            continue
        label = str(rule.get("label") or "")
        if label and not re.search(rf"(?im)^\s*>?\s*\*\*{re.escape(label)}:?\*\*", body):
            _block(f"BLOCKED: an issue labelled {prefix}{area} must open with the **{label}:** line, so every {area} "
                   f"effort is tied to what it serves.\nAdd as the first body line: "
                   + str(rule.get("example") or f"**{label}:** <link>"))


def _check_issue_body(body, labels, config):
    """Block a new-issue body carrying rot: dead cited paths, line-number citations, or a missing area line."""
    if not body:
        return
    _check_dead_paths(body, config)
    _check_line_numbers(body)
    _check_area_first_line(body, labels, config)


# --- the issue tree: PRDs on top, three layers deep, one root per subject ----
#
# A root carries the PRD label, its children carry bug/enhancement, and nothing goes deeper than three layers. Two
# mistakes break that shape and neither shows until someone reads the board: a second root for a subject that
# already has one, and a PRD label on a nested issue. Both are made at creation, so both are checked here.

_PARENT_SECTION = re.compile(r"(?im)^[ \t]*#{2,3}[ \t]+Parent\b")
_ROOT_CHECK_SECTION = re.compile(r"(?im)^[ \t]*#{2,3}[ \t]+Root check\b")
_HEADING = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]+")
_ISSUE_REF = re.compile(r"#(\d+)")

# Cached open-issue index, shared by every worktree (git common dir), so the guard costs one GraphQL call per half
# hour rather than one per creation.
_ROOTS_CACHE_NAME = "issue-guard-roots.json"
_ROOTS_TTL_SECONDS = 1800
_ROOTS_FETCH_TIMEOUT = 3.5

# Words that say nothing about a PRD's subject. A shared "deploy" between two titles means they are the same effort;
# a shared "make" means nothing. The repository's own name is added at run time.
_TITLE_NOISE = frozenset("""
about after again against already also always another anything around because
before behind being below between beyond both cannot could does doing done
down each else even ever every from fully further getting given gives goes going
hard have having here into itself just keep keeps kept know known least less
like made make makes making many more most much must need needs never next none
nothing only onto other others ought over own past rather really same shall
should since some still such take taken takes than that their them then there
these they thing things this those three thus together took toward under until
upon used uses using very what when where which while whole whom will with
within without would your
issue issues task tasks epic epics prd prds backlog loose small work works
""".split())


def _catch_all_roots(config):
    """The standing backlog PRDs: they hold small tasks on every subject, so they would match any new PRD, and
    "nest it under that root" is the wrong advice for a workstream. They are never the answer."""
    numbers = {int(number) for number in config.get("standing_prds") or []}
    if config.get("backlog_prd"):
        numbers.add(int(config["backlog_prd"]))
    return numbers


def _noise(config):
    """Title words that carry no subject: the fixed list plus the repository's own name."""
    repo = str(config.get("repo") or "")
    return _TITLE_NOISE | set(re.findall(r"[a-z0-9]+", repo.lower()))


def _body_section(body, pattern):
    """Return the text under the heading `pattern` matches, or None if absent."""
    match = pattern.search(body or "")
    if not match:
        return None
    rest = body[match.end():]
    following = _HEADING.search(rest)
    return rest[: following.start()] if following else rest


def _declared_parent(body):
    """The issue number a body's `## Parent` section names, or None."""
    section = _body_section(body, _PARENT_SECTION)
    if section is None:
        return None
    found = _ISSUE_REF.search(section)
    return int(found.group(1)) if found else None


def _title_tokens(title, noise):
    """Subject words of a title: lowercase, 4+ characters, noise dropped."""
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {word for word in words if len(word) >= 4 and word not in noise}


def _git_common_dir():
    """The repository's shared git dir, so every worktree reads one cache."""
    result = subprocess.run(["git", "-C", str(_REPO_ROOT), "rev-parse", "--git-common-dir"],
                            capture_output=True, text=True, timeout=3)
    if result.returncode != 0:
        raise OSError(result.stderr.strip()[:120])
    return (_REPO_ROOT / result.stdout.strip()).resolve()


_ROOTS_QUERY = """
query($cursor:String,$owner:String!,$name:String!){repository(owner:$owner,name:$name){
 issues(states:OPEN,first:100,after:$cursor){
  pageInfo{hasNextPage endCursor}
  nodes{number title parent{number} labels(first:20){nodes{name}}}}}}
"""


def _fetch_open_issues(config):
    owner, name = str(config["repo"]).split("/")
    result = subprocess.run(["gh", "api", "graphql", "-f", "query=" + _ROOTS_QUERY,
                             "-f", "owner=" + owner, "-f", "name=" + name],
                            capture_output=True, text=True, timeout=_ROOTS_FETCH_TIMEOUT)
    if result.returncode != 0:
        raise OSError(result.stderr.strip()[:120])
    page = json.loads(result.stdout)["data"]["repository"]["issues"]
    return [{"number": node["number"], "title": node["title"], "parent": (node["parent"] or {}).get("number"),
             "labels": [label["name"] for label in node["labels"]["nodes"]]} for node in page["nodes"]]


def _load_open_issues(config):
    """Every open issue, from the env seam, the cache, or GitHub, in that order; None when none of them answers.

    The env seam (``ISSUE_GUARD_ROOTS``, a JSON file) is the test's way in and the only way to run this check
    without a network."""
    seam = os.environ.get("ISSUE_GUARD_ROOTS")
    if seam:
        try:
            return json.loads(pathlib.Path(seam).read_text())
        except Exception:
            return None
    try:
        cache = _git_common_dir() / _ROOTS_CACHE_NAME
    except Exception:
        return None
    try:
        if cache.exists() and time.time() - cache.stat().st_mtime < _ROOTS_TTL_SECONDS:
            return json.loads(cache.read_text())
    except Exception:
        pass
    try:
        issues = _fetch_open_issues(config)
    except Exception:
        return None
    try:
        cache.write_text(json.dumps(issues))
    except OSError:
        pass  # a read-only git dir costs a refetch, nothing more
    return issues


def _open_roots(config):
    """Open PRD roots, each with the subject words of its own and its children's titles. Returns [] on any failure:
    the guard's other checks still hold, and a network hiccup must never wedge a creation (fail-open policy)."""
    issues = _load_open_issues(config)
    if not issues:
        return []
    noise, catch_all = _noise(config), _catch_all_roots(config)
    children = {}
    for issue in issues:
        if issue["parent"] is not None:
            children.setdefault(issue["parent"], []).append(issue)
    roots = []
    for issue in issues:
        if issue["parent"] is not None or "PRD" not in issue["labels"] or issue["number"] in catch_all:
            continue
        # A root's subject also lives in its children's titles: a root titled by a code name would otherwise not
        # match a second root on the same subject.
        words = _title_tokens(issue["title"], noise)
        for child in children.get(issue["number"], []):
            words |= _title_tokens(child["title"], noise)
        roots.append({"number": issue["number"], "title": issue["title"], "words": words})
    return roots


def _root_list(roots):
    return "\n".join(f"  #{root['number']} {root['title'][:72]}" for root in roots)


def _check_prd_root(title, body, labels, config):
    """Block the two ways a creation breaks the tree's shape: a PRD is a root, so it never carries a parent, and a
    subject that already has a root does not get a second one."""
    if not any(label.strip() == "PRD" for label in labels):
        return
    parent = _declared_parent(body)
    if parent is not None:
        _block(f"BLOCKED: this issue names #{parent} as its parent and carries the PRD label. A PRD is a root; a "
               "nested issue carries bug or enhancement.\nEither drop the PRD label and keep it nested, or drop "
               "the ## Parent section and create it as a real root.")
    roots = _open_roots(config)
    root_check = _body_section(body, _ROOT_CHECK_SECTION)
    if root_check is None:
        _block("BLOCKED: a new PRD is a new root on the board, so it has to say which roots it checked first. Add a "
               "`## Root check` section to the body naming the open roots you looked at and why this is not one of "
               "them.\n" + ("Open PRD roots right now:\n" + _root_list(roots) if roots else
                            "(could not read the open roots; name what you checked anyway)"))
    named = {int(number) for number in _ISSUE_REF.findall(root_check)}
    words = _title_tokens(title, _noise(config))
    overlapping = [root for root in roots if root["number"] not in named and words & root["words"]]
    if overlapping:
        overlapping.sort(key=lambda root: len(words & root["words"]), reverse=True)
        lines = "\n".join(f"  #{root['number']} {root['title'][:64]}  (shares: "
                          + ", ".join(sorted(words & root["words"])[:4]) + ")" for root in overlapping[:3])
        _block("BLOCKED: an open root already covers this subject, and the ## Root check section does not mention "
               "it:\n" + lines + "\nNest this under that root as a sub-issue (drop the PRD label, add a ## Parent "
               "section), or name the number in ## Root check with one line on why it is a separate root.")


def _check_new_issue(title, labels, has_assignee, body):
    """Every check a new issue goes through, in the order a person fixes them."""
    config = _config()
    _check_labels(labels, has_assignee, config)
    _check_issue_body(body, labels, config)
    _check_prd_root(title, body, labels, config)


def _is_gh_issue_create(tokens):
    """True only for adjacent ``issue`` ``create`` tokens after ``gh``. Token-based on purpose: a regex would block
    ``gh issue close --comment "...create..."``; a quoted argument is one token, so it never matches."""
    if "gh" not in tokens:
        return False
    return any(tokens[index:index + 2] == ["issue", "create"] for index in range(tokens.index("gh") + 1, len(tokens)))


def _gh_issue_fields(tokens):
    """The title, labels, whether an assignee is given, and the body of a ``gh issue create`` command."""
    title, labels, has_assignee, body = "", [], False, ""
    index = 0
    while index < len(tokens):
        key, _, inline = tokens[index].partition("=")
        value = inline or (tokens[index + 1] if index + 1 < len(tokens) else "")
        field = _GH_FLAGS.get(key)
        if field == "body_file" and value in ("", "-"):
            field = None
        index += 2 if field and value and not inline else 1
        if field == "label":
            labels.extend(part.strip() for part in value.split(",") if part.strip())
        elif field == "assignee":
            has_assignee = has_assignee or bool(value.strip())
        elif field == "body":
            body = value
        elif field == "title":
            title = value
        elif field == "body_file":
            try:
                body = pathlib.Path(value).read_text()
            except OSError:
                pass  # fail-open: an unreadable body file must not wedge the call
    return title, labels, has_assignee, body


def _check_gh_issue_create(command):
    """Guard a Bash ``gh issue create``; any other command passes."""
    if not re.search(r"\bgh\b", command):
        return
    tokens = shlex.split(command)  # may raise on odd quoting -> fail open
    if _is_gh_issue_create(tokens):
        _check_new_issue(*_gh_issue_fields(tokens))


def _check_mcp_create_issue(tool_input):
    """Guard the mcp__github__create_issue tool call."""
    labels = tool_input.get("labels") or []
    assignees = tool_input.get("assignees") or tool_input.get("assignee") or []
    labels = [labels] if isinstance(labels, str) else labels
    _check_new_issue(str(tool_input.get("title") or ""), [str(label) for label in labels], bool(assignees),
                     str(tool_input.get("body") or ""))


def _is_destructive_git(command):
    """True if ``command`` runs a history-destroying git op. Matches tokens, not substrings, so a force pattern
    quoted inside a commit message does not trip it; quoting shlex cannot parse falls open."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if "git" not in tokens:
        return False
    if "reset" in tokens and "--hard" in tokens:
        return True
    if "push" not in tokens:
        return False
    # a refspec whose source starts with '+' (git push origin +main:main) force-updates the remote
    return any(token in ("--force", "--force-with-lease", "-f") or re.match(r"\+[^\s:]+:", token) for token in tokens)


def main():
    payload = json.loads(sys.stdin.read())
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    if tool_name == "mcp__github__create_issue":
        _check_mcp_create_issue(tool_input)
    elif tool_name == "Bash":
        command = tool_input.get("command", "")
        if _is_destructive_git(command):
            _block("BLOCKED: destructive git operation requires explicit user approval.")
        _check_gh_issue_create(command)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)  # fail-open: never wedge a tool call on an input shape the guard did not expect
