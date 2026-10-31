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
import posixpath
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
        home = posixpath.dirname(fragment.relative_to(repo).as_posix())
        watched = [home, *extra]
        if any(_under(path, prefix) for path in paths for prefix in watched):
            selected.extend(service for service in services if service not in selected)
    return selected


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
