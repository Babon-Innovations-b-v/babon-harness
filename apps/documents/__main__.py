"""CLI for the documents package.

Usage:
    uv run python -m documents <type> --data <file.yaml> --out <file.pdf>
    uv run python -m documents <type> --sample --out <file.pdf>

<type> names a directory under apps/documents/templates/ (e.g. invoice).
--sample renders the type's bundled sample-data.yaml instead of --data.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from documents.load_design import load_design
from documents.make_pdf import make_pdf
from documents.render_html import TEMPLATES_DIR, render_html

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DESIGN_DIR = REPO_ROOT / "design"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m documents",
        description=(
            "Render a branded PDF document from a YAML data file and a "
            "jinja2 template, styled by the design system in design/."
        ),
    )
    parser.add_argument(
        "type",
        help="document type: a directory under apps/documents/templates/ "
        "(e.g. invoice)",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--data", type=Path, help="YAML data file for the document"
    )
    source.add_argument(
        "--sample",
        action="store_true",
        help="render the type's bundled sample-data.yaml",
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="output PDF path"
    )
    parser.add_argument(
        "--design",
        type=Path,
        default=DEFAULT_DESIGN_DIR,
        help="design directory holding tokens.css + company.yaml "
        "(default: design/ at the repo root)",
    )
    return parser


def _resolve_data_path(args: argparse.Namespace) -> Path:
    if args.sample:
        return TEMPLATES_DIR / args.type / "sample-data.yaml"
    return args.data


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    data_path = _resolve_data_path(args)
    if not data_path.is_file():
        print(f"error: data file not found: {data_path}", file=sys.stderr)
        return 2
    if not (args.design / "tokens.css").is_file():
        print(
            f"error: design directory not found or incomplete: {args.design} "
            "(expected tokens.css + company.yaml; pass --design to override)",
            file=sys.stderr,
        )
        return 2

    data = yaml.safe_load(data_path.read_text(encoding="utf-8")) or {}
    tokens, company = load_design(args.design)
    html = render_html(args.type, data, tokens, company)
    make_pdf(html, args.out, base_url=args.design)
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
