"""A change rebuilds the services of the fragment it belongs to, and no others.

WHAT IT PINS. `infra/auto-deploy/compose_fragments.py`, which step 50 and the
verifying lane both ask which compose services one commit changes.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. A small tree is
written by hand: two fragments, each declaring its services, one of them also
watching `design/` through `x-deploy-paths`. Which services a path must select
follows from the layout rule in the module's docstring, read off the tree
written here, never from an earlier answer.

WHAT IT WAS PROVED AGAINST. Matching a changed path against the fragment's
directory without the trailing separator, so `apps/web` also claims
`apps/website`.

GUARDS. Step 50 restarts only what a commit changed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE = Path(__file__).resolve().parents[1] / "compose_fragments.py"


def _load():
    spec = importlib.util.spec_from_file_location("compose_fragments", _MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(tmp_path: Path) -> Path:
    (tmp_path / "apps/website").mkdir(parents=True)
    (tmp_path / "apps/website/compose.yml").write_text(
        "# the site\n"
        "x-deploy-paths:\n"
        "  - design/\n"
        "services:\n"
        "  website:\n"
        "    build:\n"
        "      context: ../..\n"
        "    healthcheck:\n"
        "      test: [\"CMD\", \"true\"]\n",
        encoding="utf-8",
    )
    (tmp_path / "apps/web").mkdir(parents=True)
    (tmp_path / "apps/web/compose.yml").write_text(
        "services:\n  web:\n    image: nginx\n  web-worker:\n    image: nginx\n"
        "volumes:\n  data:\n",
        encoding="utf-8",
    )
    return tmp_path


def test_a_change_inside_a_fragment_selects_its_services_only(tmp_path: Path) -> None:
    module = _load()
    repo = _tree(tmp_path)
    assert module.changed_services(repo, ["apps/website/Dockerfile"]) == ["website"]
    assert module.changed_services(repo, ["apps/web/nginx.conf"]) == ["web", "web-worker"]


def test_a_watched_path_outside_the_fragment_selects_it(tmp_path: Path) -> None:
    module = _load()
    assert module.changed_services(_tree(tmp_path), ["design/tokens.css"]) == ["website"]


def test_the_root_compose_file_or_config_selects_everything(tmp_path: Path) -> None:
    module = _load()
    repo = _tree(tmp_path)
    assert module.changed_services(repo, ["docker-compose.yml"]) == ["all"]
    assert module.changed_services(repo, ["config/harness.env.example"]) == ["all"]


def test_a_path_no_fragment_owns_selects_nothing(tmp_path: Path) -> None:
    module = _load()
    assert module.changed_services(_tree(tmp_path), ["docs/bible.md", "tools/x.py"]) == []
