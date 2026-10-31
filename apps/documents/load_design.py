"""Load the design system: tokens.css custom properties and company.yaml.

The design directory (design/ at the repo root) is the single source of the
house style. tokens.css declares CSS custom properties (--color-primary,
--font-body, ...); company.yaml holds the company block (name, address,
registration numbers, brand colors).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_CSS_TOKEN_RE = re.compile(r"--([\w-]+)\s*:\s*([^;}]+)")


def parse_css_tokens(css_text: str) -> dict[str, str]:
    """Extract CSS custom properties from a stylesheet.

    Returns a dict keyed by property name without the leading dashes
    (e.g. "color-primary"). Comments are stripped first so commented-out
    declarations are ignored.
    """
    without_comments = _CSS_COMMENT_RE.sub("", css_text)
    return {
        name: value.strip()
        for name, value in _CSS_TOKEN_RE.findall(without_comments)
    }


def load_tokens(tokens_path: Path) -> dict[str, str]:
    """Read a tokens.css file into a {token-name: value} dict."""
    return parse_css_tokens(tokens_path.read_text(encoding="utf-8"))


def load_company(company_path: Path) -> dict:
    """Read company.yaml into a dict; the file must contain a YAML mapping."""
    loaded = yaml.safe_load(company_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{company_path} must contain a YAML mapping")
    return loaded


def _apply_company_colors(tokens: dict[str, str], company: dict) -> None:
    """Let company.yaml colors{primary,accent} override the color tokens."""
    colors = company.get("colors") or {}
    for key in ("primary", "accent"):
        value = colors.get(key)
        if value:
            tokens[f"color-{key}"] = str(value)


def load_design(design_dir: Path) -> tuple[dict[str, str], dict]:
    """Read a design directory; returns (tokens, company)."""
    tokens = load_tokens(design_dir / "tokens.css")
    company = load_company(design_dir / "company.yaml")
    _apply_company_colors(tokens, company)
    return tokens, company
