"""A document renders from its design to HTML and to a real PDF.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

render_html: jinja2 rendering of the invoice template (pure python,
no weasyprint needed).

load_design: tokens.css parsing and company.yaml reading (pure python).

make_pdf: real weasyprint render of the sample invoice, plus the
missing-system-libraries error message.

weasyprint needs system libraries (pango, harfbuzz, fontconfig). When it
cannot import, the render tests skip with a clear reason instead of failing;
the error message test below runs everywhere.
"""
from __future__ import annotations

import inspect


# From render html.

from documents.load_design import load_design


from documents.render_html import render_html


def _render_sample(design_dir, sample_invoice_data, **overrides):
    data = {**sample_invoice_data, **overrides}
    tokens, company = load_design(design_dir)
    return render_html("invoice", data, tokens, company)


def _design_tokens_reach_the_html_as_css_variables(
    design_dir, sample_invoice_data
):
    html = _render_sample(design_dir, sample_invoice_data)
    assert ":root {" in html
    assert "--color-primary: #1f3a5f;" in html
    assert "--font-heading:" in html


def _invoice_fields_and_company_block_render(
    design_dir, sample_invoice_data
):
    html = _render_sample(design_dir, sample_invoice_data)
    assert "INV-2026-0042" in html
    assert "Example Customer Ltd" in html
    assert "Example B.V." in html
    assert "NL00BANK0123456789" in html


def _totals_are_computed_from_line_items(design_dir, sample_invoice_data):
    # 1 x 3200.00 + 3 x 95.00 = 3485.00; VAT 21% = 731.85; total 4216.85
    html = _render_sample(design_dir, sample_invoice_data)
    assert "3,485.00" in html
    assert "731.85" in html
    assert "4,216.85" in html


def _vat_percent_defaults_to_21(design_dir, sample_invoice_data):
    data = dict(sample_invoice_data)
    data.pop("vat_percent", None)
    html = _render_sample(design_dir, data)
    assert "21%" in html


def _english_labels_by_default(design_dir, sample_invoice_data):
    html = _render_sample(design_dir, sample_invoice_data)
    assert "Invoice" in html
    assert "Subtotal" in html
    assert "Total" in html


def _labels_mapping_switches_language(design_dir, sample_invoice_data):
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


def _empty_company_leaves_no_dangling_separators(
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


def _data_values_are_html_escaped(design_dir, sample_invoice_data):
    html = _render_sample(
        design_dir,
        sample_invoice_data,
        notes="<script>alert('x')</script>",
    )
    assert "<script>" not in html

# From load design.

import pytest


from documents.load_design import load_company, load_design as load_design_2, parse_css_tokens


def _parses_all_contract_tokens(design_dir):
    tokens, _ = load_design_2(design_dir)
    for name in (
        "color-primary",
        "color-accent",
        "color-ink",
        "color-paper",
        "color-muted",
        "color-line",
        "font-body",
        "font-heading",
        "radius",
        "space",
        "shadow",
    ):
        assert name in tokens, f"missing token {name}"


def _values_are_trimmed_and_complete():
    tokens = parse_css_tokens(
        ":root { --color-primary:  #123456 ; --space: 12px; }"
    )
    assert tokens["color-primary"] == "#123456"
    assert tokens["space"] == "12px"


def _commented_out_declarations_are_ignored():
    tokens = parse_css_tokens(
        ":root { /* --color-primary: #dead00; */ --color-primary: #123456; }"
    )
    assert tokens == {"color-primary": "#123456"}


def _multivalue_tokens_survive():
    tokens = parse_css_tokens(
        ':root { --font-body: "Helvetica", "Arial", sans-serif; }'
    )
    assert tokens["font-body"] == '"Helvetica", "Arial", sans-serif'


def _company_colors_override_color_tokens(design_dir):
    company_path = design_dir / "company.yaml"
    company_path.write_text(
        company_path.read_text(encoding="utf-8").replace(
            "'#1f3a5f'", "'#0000ff'"
        ),
        encoding="utf-8",
    )
    tokens, company = load_design_2(design_dir)
    assert company["colors"]["primary"] == "#0000ff"
    assert tokens["color-primary"] == "#0000ff"


def _company_yaml_must_be_a_mapping(tmp_path):
    bad = tmp_path / "company.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_company(bad)

# From pdf invoice.

import sys


from documents.make_pdf import make_pdf


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


def _sample_invoice_renders_to_a_real_pdf(
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


def _missing_weasyprint_raises_named_apt_packages(
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


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_design_tokens_reach_the_html_as_css_variables),
    *_cases(_invoice_fields_and_company_block_render),
    *_cases(_totals_are_computed_from_line_items),
    *_cases(_vat_percent_defaults_to_21),
    *_cases(_english_labels_by_default),
    *_cases(_labels_mapping_switches_language),
    *_cases(_empty_company_leaves_no_dangling_separators),
    *_cases(_data_values_are_html_escaped),
    *_cases(_parses_all_contract_tokens),
    *_cases(_values_are_trimmed_and_complete),
    *_cases(_commented_out_declarations_are_ignored),
    *_cases(_multivalue_tokens_survive),
    *_cases(_company_colors_override_color_tokens),
    *_cases(_company_yaml_must_be_a_mapping),
    *_cases(_sample_invoice_renders_to_a_real_pdf, marks=(needs_render_stack,)),
    *_cases(_missing_weasyprint_raises_named_apt_packages),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_document_renders_from_its_design_to_html_and_to_a_real_pdf(scenario, given, uses, request):
    """A document renders from its design to HTML and to a real PDF: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
