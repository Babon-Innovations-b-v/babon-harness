"""Document generation: branded PDFs (an invoice ships; add a type per template) rendered
from a YAML data file and a jinja2 template, styled by the design system in
design/ (tokens.css + company.yaml).

CLI: uv run python -m documents <type> --data <file.yaml> --out <file.pdf>
"""
