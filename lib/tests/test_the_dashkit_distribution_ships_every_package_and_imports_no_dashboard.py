"""The dashkit distribution ships every package and imports no dashboard.

WHAT IT PINS. How the library under `lib/` reaches the dashboards: `dashkit` is
installed as a distribution, and setuptools installs only the packages its
`pyproject.toml` lists, so a subpackage left off the list imports in a test and
is missing in every image. And the boundary the package declares: a library,
never an application, so nothing in it imports `apps` or `infra`.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each package is
named below by hand, one case each, and the answer is that the list names it.
The boundary case reads every module's imports with `ast` and expects none
that start with `apps` or `infra`.

ONE FUNCTION. This group's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row drops
`dashkit.ai` from the list, so the ai case fails.

GUARDS. One test per module group (#1210), 2026-11-05.
"""
from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

DASHKIT = Path(__file__).resolve().parents[1] / "dashkit"

CASES = [
    pytest.param("dashkit", id="the-top-package"),
    pytest.param("dashkit.ai", id="ai"),
    pytest.param("dashkit.core", id="core"),
    pytest.param("dashkit.core.audit", id="audit"),
    pytest.param("dashkit.core.sync", id="sync"),
    pytest.param(None, id="no-module-imports-a-dashboard"),
]


def _dashboard_imports() -> list[str]:
    """Every `apps.*` or `infra.*` import in the library's own modules."""
    found = []
    for path in sorted(DASHKIT.rglob("*.py")):
        if "tests" in path.relative_to(DASHKIT).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            found += [f"{path.name}: {name}" for name in names if name.split(".")[0] in ("apps", "infra")]
    return found


@pytest.mark.parametrize("package", CASES)
def test_the_dashkit_distribution_ships_every_package_and_imports_no_dashboard(package: str | None) -> None:
    """The named package is listed, and no module of the library imports a dashboard."""
    if package is None:
        assert _dashboard_imports() == []
        return
    listed = tomllib.loads((DASHKIT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["packages"]
    assert package in listed
