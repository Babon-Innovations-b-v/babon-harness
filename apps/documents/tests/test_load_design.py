"""load_design: tokens.css parsing and company.yaml reading (pure python)."""
from __future__ import annotations

import pytest

from documents.load_design import load_company, load_design, parse_css_tokens


def test_parses_all_contract_tokens(design_dir):
    tokens, _ = load_design(design_dir)
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


def test_values_are_trimmed_and_complete():
    tokens = parse_css_tokens(
        ":root { --color-primary:  #123456 ; --space: 12px; }"
    )
    assert tokens["color-primary"] == "#123456"
    assert tokens["space"] == "12px"


def test_commented_out_declarations_are_ignored():
    tokens = parse_css_tokens(
        ":root { /* --color-primary: #dead00; */ --color-primary: #123456; }"
    )
    assert tokens == {"color-primary": "#123456"}


def test_multivalue_tokens_survive():
    tokens = parse_css_tokens(
        ':root { --font-body: "Helvetica", "Arial", sans-serif; }'
    )
    assert tokens["font-body"] == '"Helvetica", "Arial", sans-serif'


def test_company_colors_override_color_tokens(design_dir):
    company_path = design_dir / "company.yaml"
    company_path.write_text(
        company_path.read_text(encoding="utf-8").replace(
            "'#1f3a5f'", "'#0000ff'"
        ),
        encoding="utf-8",
    )
    tokens, company = load_design(design_dir)
    assert company["colors"]["primary"] == "#0000ff"
    assert tokens["color-primary"] == "#0000ff"


def test_company_yaml_must_be_a_mapping(tmp_path):
    bad = tmp_path / "company.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_company(bad)
