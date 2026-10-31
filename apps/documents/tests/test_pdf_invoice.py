"""make_pdf: real weasyprint render of the sample invoice, plus the
missing-system-libraries error message.

weasyprint needs system libraries (pango, harfbuzz, fontconfig). When it
cannot import, the render tests skip with a clear reason instead of failing;
the error message test below runs everywhere.
"""
from __future__ import annotations

import sys

import pytest

from documents.load_design import load_design
from documents.make_pdf import make_pdf
from documents.render_html import render_html

try:
    import weasyprint  # noqa: F401
    WEASYPRINT_SKIP = None
except (ImportError, OSError) as exc:
    WEASYPRINT_SKIP = (
        f"weasyprint unavailable ({exc}); install system libraries with: "
        "sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 "
        "libharfbuzz0b libfontconfig1"
    )

try:
    import pypdf
    PYPDF_SKIP = None
except ImportError as exc:
    PYPDF_SKIP = f"pypdf unavailable ({exc}); it is a dev-only dependency"

needs_render_stack = pytest.mark.skipif(
    bool(WEASYPRINT_SKIP or PYPDF_SKIP), reason=WEASYPRINT_SKIP or PYPDF_SKIP or ""
)


@needs_render_stack
def test_sample_invoice_renders_to_a_real_pdf(
    tmp_path, design_dir, sample_invoice_data
):
    tokens, company = load_design(design_dir)
    html = render_html("invoice", sample_invoice_data, tokens, company)
    out = tmp_path / "invoice.pdf"
    make_pdf(html, out, base_url=design_dir)

    assert out.stat().st_size > 1000
    reader = pypdf.PdfReader(out)
    text = "".join(page.extract_text() for page in reader.pages)
    compact = "".join(text.split())
    assert "INV-2026-0042" in compact
    assert "4,216.85" in compact  # grand total incl. 21% VAT


def test_missing_weasyprint_raises_named_apt_packages(
    monkeypatch, tmp_path
):
    # Simulate the missing-system-libraries case: with sys.modules[name]
    # set to None, `from weasyprint import HTML` raises ImportError.
    monkeypatch.setitem(sys.modules, "weasyprint", None)
    with pytest.raises(RuntimeError) as excinfo:
        make_pdf("<html></html>", tmp_path / "x.pdf")
    message = str(excinfo.value)
    for package in (
        "libpango-1.0-0",
        "libpangoft2-1.0-0",
        "libharfbuzz0b",
        "libfontconfig1",
    ):
        assert package in message
