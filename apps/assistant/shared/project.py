"""The GitHub repository this assistant works on, and the people on it.

Read from `repo`, `owner`, `people`, `areas`, `area_label_prefix` and
`backlog_prd` in the repository's `.claude/project.json` (filled by
`.claude/scripts/setup-github.py`), which the image carries at
`/app/.claude/project.json`. `GITHUB_REPO` in the environment wins, so a
test or a second deployment can point elsewhere without editing the file.

FAILURE POLICY: never raises. With neither source the value is the
placeholder `owner/repo`, and every GitHub read then fails loudly at the
`gh` call with a message naming the repository it tried, which is how an
unconfigured box shows itself.
"""
from __future__ import annotations

import json
import os
import pathlib

_PLACEHOLDER = "owner/repo"


def _project_json() -> pathlib.Path:
    explicit = os.environ.get("HARNESS_PROJECT_JSON", "").strip()
    if explicit:
        return pathlib.Path(explicit)
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".claude" / "project.json"
        if candidate.is_file():
            return candidate
    return pathlib.Path("/app/.claude/project.json")


def _load() -> dict:
    try:
        data = json.loads(_project_json().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


_DATA = _load()


def _read_repo() -> str:
    explicit = os.environ.get("GITHUB_REPO", "").strip()
    if explicit:
        return explicit
    repo = str(_DATA.get("repo") or "").strip()
    return repo or _PLACEHOLDER


def _people() -> dict[str, str]:
    raw = _DATA.get("people") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(name).strip(): str(login).strip() for name, login in raw.items() if str(login).strip()}


GITHUB_REPO: str = _read_repo()
GITHUB_OWNER, _, GITHUB_NAME = GITHUB_REPO.partition("/")
#: The repository owner's GitHub login, the assignee of last resort.
OWNER_LOGIN: str = str(_DATA.get("owner") or "").strip() or GITHUB_OWNER
#: Display name -> GitHub login, as `setup-github.py` writes it.
PEOPLE: dict[str, str] = _people()
#: The board's area labels are `AREA_LABEL_PREFIX + area`.
AREA_LABEL_PREFIX: str = str(_DATA.get("area_label_prefix") or "area:")
AREAS: tuple[str, ...] = tuple(str(area) for area in (_DATA.get("areas") or []) if str(area).strip())
#: The standing backlog issue loose work nests under, or None.
BACKLOG_PRD: int | None = int(_DATA["backlog_prd"]) if str(_DATA.get("backlog_prd") or "").isdigit() else None

__all__ = [
    "AREAS",
    "AREA_LABEL_PREFIX",
    "BACKLOG_PRD",
    "GITHUB_NAME",
    "GITHUB_OWNER",
    "GITHUB_REPO",
    "OWNER_LOGIN",
    "PEOPLE",
]
