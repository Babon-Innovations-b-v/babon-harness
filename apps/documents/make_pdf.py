"""Turn rendered HTML into a PDF with weasyprint."""
from __future__ import annotations

from pathlib import Path

# Debian and Ubuntu package names for the shared libraries weasyprint opens
# through ctypes at import time: pango, pangoft2, harfbuzz, fontconfig and
# gobject (weasyprint/text/ffi.py). gobject lives in the glib package and
# arrives as a dependency of pango; glib's own package name changed in the
# 64-bit time_t transition (libglib2.0-0 became libglib2.0-0t64), so naming it
# here would break the install line on some distributions. Cairo and gdk-pixbuf
# were needed by weasyprint 52 and earlier; the current version does not load
# them.
_APT_PACKAGES = (
    "libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfontconfig1"
)


def make_pdf(html: str, out_path: Path, base_url: Path | str | None = None) -> None:
    """Write `html` to `out_path` as a PDF.

    `base_url` resolves relative URLs in the HTML (e.g. the company logo);
    pass the design directory so `logo: logo.svg` in company.yaml works.

    weasyprint needs system libraries (pango, harfbuzz, fontconfig). If they
    are missing the import fails at call time and we raise a clear message
    naming the apt packages instead of a bare OSError.
    """
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "weasyprint could not be imported, usually because its system "
            "libraries are missing. Install them with: "
            f"sudo apt-get install -y {_APT_PACKAGES}"
        ) from exc
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html, base_url=str(base_url) if base_url else None).write_pdf(
        out_path
    )
