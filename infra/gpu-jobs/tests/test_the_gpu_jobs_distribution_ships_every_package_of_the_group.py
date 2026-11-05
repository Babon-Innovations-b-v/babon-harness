"""The gpu-jobs distribution ships every package of the group.

WHAT IT PINS. How the group's modules reach the notulen app and its worker:
`infra/gpu-jobs` is installed as the `gpu-jobs` distribution, and setuptools
installs only the packages `pyproject.toml` lists. A module left off that list
imports from the source tree in a test and is missing in every image, so the
first Job of the day fails on an ImportError nobody saw.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each package
this group holds is named below by hand, one case each: the five modules the
register counts under `gpu_jobs` and the top package. The answer for each is
whether the list names it, which must be yes, and the list must name nothing
that is not a package directory.

ONE FUNCTION. This group's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row drops
`gpu_jobs.naming` from the list, so the naming case fails.

GUARDS. One test per module group (#1210), 2026-11-05.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

GROUP = Path(__file__).resolve().parents[1]

CASES = [
    pytest.param("gpu_jobs", id="the-top-package"),
    pytest.param("gpu_jobs.cluster", id="cluster"),
    pytest.param("gpu_jobs.config", id="config"),
    pytest.param("gpu_jobs.creators", id="creators"),
    pytest.param("gpu_jobs.naming", id="naming"),
    pytest.param("gpu_jobs.security", id="security"),
    pytest.param(None, id="nothing-listed-that-is-not-a-package"),
]


@pytest.mark.parametrize("package", CASES)
def test_the_gpu_jobs_distribution_ships_every_package_of_the_group(package: str | None) -> None:
    """The named package is listed, and every listed name is a package directory."""
    listed = tomllib.loads((GROUP / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["packages"]
    if package is None:
        assert [name for name in listed if not (GROUP / name.replace(".", "/") / "__init__.py").is_file()] == []
    else:
        assert package in listed
