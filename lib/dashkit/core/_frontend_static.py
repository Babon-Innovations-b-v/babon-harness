"""Shared-frontend static route (internal to dashkit.core.app_factory).

Serves ``dashkit/frontend/`` (api.js, base.css, ...) at
``/static/dashkit/{filename:path}`` so per-dashboard ``main.py`` modules
never wire their own static handler.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

# Map suffix to media type for the frontend static endpoint.
_FRONTEND_MEDIA = {
    ".js": "application/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


def _find_dashkit_frontend() -> Path:
    """Return the ``dashkit/frontend`` directory.

    The frontend ships inside the package (``dashkit/frontend/``, one
    level above this module). The lookup also walks ancestors looking
    for a ``dashkit/frontend/`` so a copied-in source tree works too.
    """
    here = Path(__file__).resolve().parent
    primary = here / "frontend"
    if primary.is_dir():
        return primary
    for ancestor in here.parents:
        probe = ancestor / "dashkit" / "frontend"
        if probe.is_dir():
            return probe
    raise RuntimeError("dashkit/frontend not found")


def _make_frontend_router(frontend_dir: Path | None = None) -> APIRouter:
    """Build the ``/static/dashkit/{filename:path}`` static-asset router."""
    base = (frontend_dir or _find_dashkit_frontend()).resolve()
    router = APIRouter()

    @router.get("/static/dashkit/{filename:path}")
    def dashkit_static(filename: str):
        target = (base / filename).resolve()
        # Path-traversal guard: refuse anything that escapes the
        # frontend root, regardless of how the request was crafted.
        if (
            not str(target).startswith(str(base))
            or not target.is_file()
        ):
            raise HTTPException(status_code=404, detail="not found")
        media = _FRONTEND_MEDIA.get(
            target.suffix.lower(), "application/octet-stream",
        )
        # Text-ish payloads are served as decoded strings to keep the
        # historical content-type behaviour (the dashboards expect a
        # `text/...` or `application/javascript` response with utf-8).
        if media.startswith("text/") or media in (
            "application/javascript", "application/json", "image/svg+xml",
        ):
            return Response(
                content=target.read_text(encoding="utf-8"),
                media_type=media,
            )
        return Response(
            content=target.read_bytes(),
            media_type=media,
        )

    return router
