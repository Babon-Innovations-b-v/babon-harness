"""Which compose services one commit changes, read from the compose fragments.

    python3 infra/auto-deploy/compose_fragments.py --repo <tree> --changed-file <file>

prints one service name per line, or the single word `all`.

THE LAYOUT IT READS. The root `docker-compose.yml` `include:`s one fragment per
component, a `compose.yml` in that component's directory (`apps/website/`,
`infra/caddy/`, ...). A fragment owns the services it declares, and a change
anywhere in the fragment's directory rebuilds and restarts exactly those. A
fragment whose image also reads files elsewhere (a build context that climbs to
the repository root, say) names those paths in a top-level `x-deploy-paths:`
list, and a change under any of them counts too:

    x-deploy-paths:
      - design/

A service with a `build:` block is narrower than its fragment: it changes only
when a changed path is one its image is built from, read off its Dockerfile.
That is the Dockerfile itself, the ignore file the build reads
(`<Dockerfile>.dockerignore` beside it, else the context's `.dockerignore`),
any path a `COPY` or `ADD` source covers that the ignore file leaves in, the
fragment's own `compose.yml`, or an `x-deploy-paths` entry. So a test or a doc
in the fragment's directory rebuilds nothing, and a file the image copies from
elsewhere rebuilds it. A deleted file counts, because the check is the path
against the rules, not a listing of the tree. When the Dockerfile cannot be
read, the service falls back to the fragment's directory.

`all` is printed when the root `docker-compose.yml` changed, or a path under
`config/`: those can change any service, and `docker compose up -d` without a
service list recreates exactly the ones whose configuration moved.

WHY NOT `docker compose config`. It needs every variable the fragments name
already set, and step 20 asks before the vault is necessarily complete. Reading
the files is enough: a service is a key two spaces in under the top-level
`services:`, which is the one shape every fragment here is written in.

FAILURE POLICY: a fragment that cannot be read contributes nothing, and the run
exits 0 with whatever it could say; an unreadable changed-file exits 2, and the
caller then rebuilds everything. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import shlex
import sys
from pathlib import Path

#: Changes under these always mean "every service may have changed".
ALL_SERVICES_PATHS = ("docker-compose.yml", "config/")

#: Where fragments live: one directory below each of these.
FRAGMENT_PARENTS = ("apps", "infra", "lib")


def fragments(repo: Path) -> list[Path]:
    """Every component compose fragment in the tree, sorted."""
    found: list[Path] = []
    for parent in FRAGMENT_PARENTS:
        found.extend(sorted((repo / parent).glob("*/compose.yml")))
    return found


def read_fragment(text: str) -> tuple[list[str], list[str]]:
    """The services a fragment declares, and its `x-deploy-paths` entries."""
    services: list[str] = []
    extra: list[str] = []
    section = ""
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        if not line.startswith(" "):
            section = line.rstrip(":").strip()
            continue
        if section == "services" and line.startswith("  ") and not line.startswith("   ") \
                and line.rstrip().endswith(":"):
            services.append(line.strip().rstrip(":").strip("\"'"))
        elif section == "x-deploy-paths" and line.strip().startswith("- "):
            extra.append(line.strip()[2:].strip().strip("\"'"))
    return services, extra


def read_builds(text: str) -> dict[str, tuple[str, str]]:
    """Each service's `build:` context and dockerfile, as written; a service with no build is absent."""
    builds: dict[str, tuple[str, str]] = {}
    section, service, in_build = "", "", False
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            section, service, in_build = line.rstrip(":").strip(), "", False
        elif section != "services":
            continue
        elif indent == 2 and line.endswith(":"):
            service, in_build = line.strip().rstrip(":").strip("\"'"), False
        elif indent == 4:
            in_build = line.strip() == "build:"
            if in_build:
                builds[service] = (".", "Dockerfile")
            elif line.strip().startswith("build:"):
                builds[service] = (line.strip()[len("build:"):].strip().strip("\"'"), "Dockerfile")
        elif indent == 6 and in_build and service:
            key, _, value = line.strip().partition(":")
            context, dockerfile = builds[service]
            value = value.strip().strip("\"'")
            if key == "context":
                builds[service] = (value, dockerfile)
            elif key == "dockerfile":
                builds[service] = (context, value)
    return builds


_COPY = re.compile(r"^\s*(COPY|ADD)\s+(.*)$", re.IGNORECASE)
_REMOTE = re.compile(r"^(https?://|git@|git://)")


def _instructions(dockerfile_text: str) -> list[str]:
    """Each Dockerfile instruction as one line, continuations joined, comments dropped."""
    joined, pending = [], ""
    for raw in dockerfile_text.splitlines():
        stripped = raw.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1] + " "
            continue
        joined.append(pending + stripped)
        pending = ""
    if pending:
        joined.append(pending)
    return joined


def copy_sources(dockerfile_text: str) -> list[str]:
    """The context paths every `COPY`/`ADD` reads; `--from` stages and URLs read none."""
    sources = []
    for line in _instructions(dockerfile_text):
        found = _COPY.match(line)
        if not found or found.group(2).strip().startswith("<<"):
            continue
        rest = found.group(2).strip()
        words = json.loads(rest) if rest.startswith("[") else shlex.split(rest)
        if any(word.startswith("--from") for word in words):
            continue
        paths = [word for word in words if not word.startswith("--")][:-1]
        sources.extend(_clean(path) for path in paths if not _REMOTE.match(path))
    return sources


def _clean(pattern: str) -> str:
    """Docker's cleaning of a pattern: leading slash and `./` segments removed."""
    return "/".join(part for part in pattern.strip().split("/") if part not in ("", "."))


def _glob(pattern: str) -> re.Pattern:
    """A Docker path pattern (`*`, `?`, `[...]`, `**`) as one anchored regex."""
    out, index = [], 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
            continue
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        char = pattern[index]
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[" and pattern.find("]", index) > 0:
            close = pattern.find("]", index)
            body = pattern[index + 1:close]
            out.append("[" + ("^" + body[1:] if body.startswith("!") else body) + "]")
            index = close
        else:
            out.append(re.escape(char))
        index += 1
    return re.compile("".join(out) + r"\Z")


def _covers(rule: re.Pattern, path: str) -> bool:
    """True when `rule` matches `path` or a directory above it."""
    parts = path.split("/")
    return any(rule.match("/".join(parts[:depth])) for depth in range(1, len(parts) + 1))


def _ignored(ignore_text: str, path: str) -> bool:
    """Whether the ignore file leaves `path` out: the last line covering it wins."""
    ignored = False
    for raw in ignore_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pattern = _clean(line.lstrip("!"))
        if pattern and _covers(_glob(pattern), path):
            ignored = not line.startswith("!")
    return ignored


def image_reads(repo: Path, home: str, context: str, dockerfile: str, path: str) -> bool:
    """Whether the image built from `context`/`dockerfile` (relative to `home`) reads `path`.

    Raises OSError when the Dockerfile cannot be read; the caller then falls
    back to the fragment's directory.
    """
    context_dir = posixpath.normpath(posixpath.join(home, context))
    dockerfile_path = posixpath.normpath(posixpath.join(context_dir, dockerfile))
    text = (repo / dockerfile_path).read_text(encoding="utf-8")
    beside = f"{dockerfile_path}.dockerignore"
    ignore_path = beside if (repo / beside).is_file() else posixpath.join(context_dir, ".dockerignore")
    if path in (dockerfile_path, posixpath.normpath(ignore_path)):
        return True
    inside = path if context_dir == "." else (path[len(context_dir) + 1:] if _under(path, context_dir) else None)
    if not inside:
        return False
    ignore_text = (repo / ignore_path).read_text(encoding="utf-8") if (repo / ignore_path).is_file() else ""
    if _ignored(ignore_text, inside):
        return False
    return any(not source or _covers(_glob(source), inside) for source in copy_sources(text))


def _under(path: str, prefix: str) -> bool:
    """True when `path` is `prefix` or sits below it."""
    prefix = prefix.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def changed_services(repo: Path, changed: list[str]) -> list[str]:
    """The services to rebuild for these changed paths, or `["all"]`."""
    paths = [path.strip() for path in changed if path.strip()]
    for path in paths:
        for marker in ALL_SERVICES_PATHS:
            if path == marker or (marker.endswith("/") and path.startswith(marker)):
                return ["all"]
    selected: list[str] = []
    for fragment in fragments(repo):
        try:
            services, extra = read_fragment(fragment.read_text(encoding="utf-8"))
        except OSError:
            continue
        own = fragment.relative_to(repo).as_posix()
        home = posixpath.dirname(own)
        builds = read_builds(fragment.read_text(encoding="utf-8"))
        for service in services:
            if service not in selected and _service_changed(repo, home, own, extra, builds.get(service), paths):
                selected.append(service)
    return selected


def _service_changed(repo: Path, home: str, own: str, extra: list[str],
                     build: tuple[str, str] | None, paths: list[str]) -> bool:
    """Whether one service of a fragment changed: by its image's inputs, else by the fragment's directory."""
    if any(path == own or _under(path, prefix) for path in paths for prefix in extra):
        return True
    if build is not None:
        try:
            return any(image_reads(repo, home, build[0], build[1], path) for path in paths)
        except OSError:
            pass
    return any(_under(path, home) for path in paths)


def main(argv: list[str] | None = None) -> int:
    """Print the services one commit changes. Exit 2 when the input is unreadable."""
    parser = argparse.ArgumentParser(prog="compose_fragments")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--changed-file", required=True)
    args = parser.parse_args(argv)
    try:
        changed = Path(args.changed_file).read_text(encoding="utf-8").splitlines()
    except OSError as failure:
        print(f"compose_fragments: {failure}", file=sys.stderr)
        return 2
    for service in changed_services(Path(args.repo), changed):
        print(service)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
