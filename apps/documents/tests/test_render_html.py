"""render_html: jinja2 rendering of the invoice template (pure python,
no weasyprint needed)."""
from __future__ import annotations

from documents.load_design import load_design
from documents.render_html import render_html


def _render_sample(design_dir, sample_invoice_data, **overrides):
    data = {**sample_invoice_data, **overrides}
    tokens, company = load_design(design_dir)
    return render_html("invoice", data, tokens, company)


def test_design_tokens_reach_the_html_as_css_variables(
    design_dir, sample_invoice_data
):
    html = _render_sample(design_dir, sample_invoice_data)
    assert ":root {" in html
    assert "--color-primary: #1f3a5f;" in html
    assert "--font-heading:" in html


def test_invoice_fields_and_company_block_render(
    design_dir, sample_invoice_data
):
    html = _render_sample(design_dir, sample_invoice_data)
    assert "INV-2026-0042" in html
    assert "Example Customer Ltd" in html
    assert "Example B.V." in html
    assert "NL00BANK0123456789" in html


def test_totals_are_computed_from_line_items(design_dir, sample_invoice_data):
    # 1 x 3200.00 + 3 x 95.00 = 3485.00; VAT 21% = 731.85; total 4216.85
    html = _render_sample(design_dir, sample_invoice_data)
    assert "3,485.00" in html
    assert "731.85" in html
    assert "4,216.85" in html


def test_vat_percent_defaults_to_21(design_dir, sample_invoice_data):
    data = dict(sample_invoice_data)
    data.pop("vat_percent", None)
    html = _render_sample(design_dir, data)
    assert "21%" in html


def test_english_labels_by_default(design_dir, sample_invoice_data):
    html = _render_sample(design_dir, sample_invoice_data)
    assert "Invoice" in html
    assert "Subtotal" in html
    assert "Total" in html


def test_labels_mapping_switches_language(design_dir, sample_invoice_data):
    html = _render_sample(
        design_dir,
        sample_invoice_data,
        labels={"invoice": "Factuur", "subtotal": "Subtotaal", "vat": "BTW"},
    )
    assert "Factuur" in html
    assert "Subtotaal" in html
    assert "BTW 21%" in html
    # Keys not overridden keep their English defaults.
    assert "Bill to" in html


def test_empty_company_leaves_no_dangling_separators(
    design_dir, sample_invoice_data
):
    # design/company.yaml ships with every field "" until onboarding fills
    # it; the company block and footer must drop empty lines cleanly.
    from documents.load_design import load_tokens

    tokens = load_tokens(design_dir / "tokens.css")
    empty_company = {key: "" for key in (
        "name", "tagline", "legal_form", "address", "postal_code", "city",
        "country", "email", "phone", "website", "registration_number",
        "vat_number", "iban", "bank_name", "director", "logo",
    )} | {"colors": {"primary": "", "accent": ""}}
    html = render_html("invoice", sample_invoice_data, tokens, empty_company)
    assert "Reg. no." not in html
    assert "IBAN" not in html
    assert "in the name of" not in html


def test_data_values_are_html_escaped(design_dir, sample_invoice_data):
    html = _render_sample(
        design_dir,
        sample_invoice_data,
        notes="<script>alert('x')</script>",
    )
    assert "<script>" not in html
