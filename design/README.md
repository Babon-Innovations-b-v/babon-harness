# design/

A design system is one place where your company's look and details live, so every page and document matches without anyone copying colors around.

## What lives here

| File | Job |
|---|---|
| `tokens.css` | The values: colors, fonts, text sizes, spacing, shadows. Starts as a neutral placeholder palette. |
| `base.css` | The rules: how plain HTML (headings, links, paragraphs) uses those values, plus `.lead`, `.muted`, `.eyebrow`. |
| `index.css` | The one entry point. It loads the two files above in order. |
| `company.yaml` | Your company profile: name, address, registration number, bank details, brand colors. |

## The one-import rule

Every surface imports `design/index.css` and nothing else from here. The website (`apps/website/`) and the dashboards (`lib/dashkit/`) link it; document templates (`apps/documents/`) read the same tokens. Keep the variable names (`--color-*`, `--font-*`): those surfaces reference them by name, so a renamed variable silently drops out of them. Change a color in `tokens.css` and everything updates together.

## How it gets filled

Onboarding fills `company.yaml` from your answers, or from documents you drop in `business/`. If you pick brand colors, onboarding writes them into both `company.yaml` and `tokens.css` (they must stay in sync).

## Restyling later

Just ask Claude in plain words:

- "make everything warmer"
- "use my logo's green as the accent color"
- "bigger headings, more white space"

Claude edits `tokens.css`; every page and document follows.

## Adding a custom font

Put the font file (`.woff2`) in this folder and ask Claude to wire it up. A comment in `tokens.css` says where the `@font-face` block goes and which stacks to put the font name in front of. Until then the system font stack is used: fast and fine-looking on every device.
