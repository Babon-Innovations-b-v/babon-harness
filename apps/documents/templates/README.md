# Document templates

Each directory here is a document type in the house style:

```
templates/<type>/template.html      jinja2 template (A4, print CSS)
templates/<type>/sample-data.yaml   worked example, renders as-is
```

Render one:

```
uv run python -m documents <type> --data your-data.yaml --out out.pdf
uv run python -m documents <type> --sample --out out.pdf
```

## Adding a new type

1. Copy an existing template directory (`invoice/` is the reference) to
   `templates/<new-type>/`.
2. Adapt `template.html` and `sample-data.yaml` to the new document. The
   easiest way: ask Claude to adapt the copy ("turn the invoice template
   into a quote"). Claude builds new types on request: quote, letter,
   report, whatever you describe.
3. Keep the styling on design tokens. Template CSS only uses
   `var(--color-primary)`, `var(--font-body)`, and the other custom
   properties from `design/tokens.css`; the design system does the styling,
   so every document type automatically matches the house style. Company
   details (name, address, IBAN, registration numbers) come from
   `design/company.yaml` as the `company` variable.
4. Field labels: write English defaults with jinja's `default` filter
   (`{{ labels.total | default("Total") }}`) and let the data file's
   optional `labels:` mapping override them, so one template serves any
   language.
5. Check the result with `--sample` before using real data.
