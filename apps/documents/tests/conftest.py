"""Shared fixtures: a stub design directory matching the design/ contract.

design/tokens.css and design/company.yaml are authored separately; tests
code against the contract with local stub copies so they never depend on
the real files existing or on their exact values.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

STUB_TOKENS_CSS = """\
/* Test stub of design/tokens.css; same contract, throwaway values. */
:root {
  --color-primary: #1f3a5f;
  --color-accent: #2d85aa;
  --color-ink: #22242a;
  --color-paper: #ffffff;
  --color-muted: #6b7280;
  --color-line: #e2e5ea;
  --font-body: "Helvetica", "Arial", sans-serif;
  --font-heading: "Georgia", serif;
  --radius: 6px;
  --space: 12px;
  --shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
}
"""

STUB_COMPANY = {
    "name": "Example B.V.",
    "tagline": "Example tagline",
    "legal_form": "B.V.",
    "address": "Example Street 1",
    "postal_code": "0000 AA",
    "city": "Example City",
    "country": "Exampleland",
    "email": "hello@example.com",
    "phone": "+00 000 000 000",
    "website": "https://example.com",
    "registration_number": "00000000",
    "vat_number": "XX000000000B00",
    "iban": "NL00BANK0123456789",
    "bank_name": "Example Bank",
    "director": "Alex Example",
    "logo": "",
    "colors": {"primary": "#1f3a5f", "accent": "#2d85aa"},
}


@pytest.fixture
def design_dir(tmp_path: Path) -> Path:
    """A throwaway design directory with the contract's two files."""
    stub = tmp_path / "design"
    stub.mkdir()
    (stub / "tokens.css").write_text(STUB_TOKENS_CSS, encoding="utf-8")
    (stub / "company.yaml").write_text(
        yaml.safe_dump(STUB_COMPANY, allow_unicode=True), encoding="utf-8"
    )
    return stub


@pytest.fixture
def sample_invoice_data() -> dict:
    """The bundled invoice sample-data.yaml, parsed."""
    sample_path = (
        Path(__file__).resolve().parents[1]
        / "templates"
        / "invoice"
        / "sample-data.yaml"
    )
    return yaml.safe_load(sample_path.read_text(encoding="utf-8"))
