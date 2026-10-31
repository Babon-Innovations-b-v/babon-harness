"""SPA shell routes: serve ``inputs/dashboard.html`` + ``inputs/dashboard.js``.

The recorder SPA itself lives in ``inputs/`` (the JS was extracted from the
inline ``<script>`` block); this module only serves the bytes.

FAILURE POLICY: nothing to swallow: a missing asset file is a deploy bug
and 500s loudly.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

router = APIRouter()

_INPUTS_DIR = Path(__file__).resolve().parent.parent / "inputs"

# no-store: iOS Safari and Chrome otherwise serve a cached SPA shell after a
# deploy, so the JS calls API routes that no longer exist. The assets are
# tiny; caching gains nothing.
_NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate"}


@router.get("/", response_class=HTMLResponse)
def _dashboard() -> HTMLResponse:
    return HTMLResponse(
        (_INPUTS_DIR / "dashboard.html").read_text(encoding="utf-8"),
        headers=_NO_STORE,
    )


@router.get("/dashboard.js")
def _dashboard_js() -> Response:
    return Response(
        content=(_INPUTS_DIR / "dashboard.js").read_text(encoding="utf-8"),
        media_type="text/javascript; charset=utf-8",
        headers=_NO_STORE,
    )
