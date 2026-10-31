"""Render a document type's jinja2 template with data, design tokens and
company info.

Design tokens reach the template as CSS custom properties injected in a
<style> block (the `design_style` variable), so template CSS just uses
var(--color-primary), var(--font-body), and friends.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

TEMPLATES_DIR = Path(__file__).parent / "templates"


def format_money(value: float) -> str:
    """Format an amount as 1,234.56 (currency symbol lives in the template)."""
    return f"{value:,.2f}"


def tokens_to_style(tokens: dict[str, str]) -> str:
    """Build the <style> block that exposes design tokens as CSS variables."""
    declarations = "\n".join(
        f"    --{name}: {value};" for name, value in tokens.items()
    )
    return f"<style>\n  :root {{\n{declarations}\n  }}\n</style>"


def render_html(
    doc_type: str,
    data: dict,
    tokens: dict[str, str],
    company: dict,
    templates_dir: Path = TEMPLATES_DIR,
) -> str:
    """Render templates/<doc_type>/template.html to an HTML string.

    The template sees:
    - data: the document's data file, unchanged
    - company: the company block from company.yaml
    - labels: data["labels"] if present (templates carry English defaults
      via jinja's |default filter, so any language works)
    - design_style: the <style> block with the design tokens
    """
    env = Environment(loader=FileSystemLoader(templates_dir), autoescape=True)
    env.filters["money"] = format_money
    template = env.get_template(f"{doc_type}/template.html")
    return template.render(
        data=data,
        company=company,
        labels=data.get("labels") or {},
        design_style=Markup(tokens_to_style(tokens)),
    )
