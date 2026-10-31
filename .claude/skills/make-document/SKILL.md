---
name: make-document
description: Produce a business document (invoice, quote, letter, any paper with the company's name on it) in the owner's house style as a PDF, and optionally email it after explicit approval. Use when the user asks for an invoice, a quote, an offer, a letter, or any document to send to someone.
---

# Make a document

The user is not a developer. They want a finished PDF that looks like their company, and maybe want it emailed. Facts come from them and from `design/company.yaml`; nothing official is ever invented.

## 1. Company profile first

Read `design/company.yaml`. If it is empty or missing the fields this document needs (name, address, registration or VAT number, IBAN for an invoice), offer to fill it first: one short interview, only the missing fields, in plain words. Write the answers into `design/company.yaml`. Never guess official numbers; a field they do not know stays empty and the document is made without it, saying so.

## 2. Pick or create the template

Templates live in `apps/documents/`, one directory per document type.

- Type exists (only `invoice` ships; check `apps/documents/templates/`): use it.
- New type (a quote, a letter, a reminder, a receipt): copy the invoice template directory, adapt the layout and fields to the new type, and keep all styling through `var(--...)` custom properties from `design/tokens.css`. No hard-coded colors or fonts; the house style lives in the tokens.

## 3. Get the content, conversationally

Ask for what the document needs, a few questions in plain words: who is it for, what lines or paragraphs go on it, amounts, dates. Then write the data file (a small `.yaml`).

Hard rules while collecting:

- **Never invent invoice numbers.** Ask what their numbering looks like, or increment from their previous invoices (check `business/` and earlier data files) and confirm the number with them.
- **Amounts are always echoed back** before generating: play back every amount, the VAT treatment, and the total, and get a confirmation. A typo in an amount is the one error that really hurts.

## 4. Generate and show

```
uv run python -m documents <type> --data <data-file>.yaml --out <output>.pdf
```

(`--sample` renders a template with sample data, useful when building a new type.)

SHOW the result: give them the file path, have them open the PDF, and iterate until they are happy. Wrong logo size, missing line, different wording: fix, regenerate, show again. Do not move on until they say it is right.

## 5. Sending, only after an explicit yes

Only when they have approved the exact file, offer to email it. Never send a version they have not seen.

**First time** (no `TEM_FROM` in `config/harness.env` yet), set up sending:

1. `scw tem domain create` with their DOMAIN, print the DNS records Scaleway asks for (add them where the domain lives; on a Scaleway-registered domain add them yourself with `scw dns record`), and wait for verification. This can take a while; offer to check back.
2. Once verified, set `TEM_PROJECT_ID`, `TEM_REGION`, and `TEM_FROM` (like `noreply@<their domain>`) in `config/harness.env`, and the same three in the vault (update pattern in `.claude/skills/onboard/phases.md`). They are settings, not secrets. The sending credential is the Scaleway secret key, which `send_document.py` reads from the laptop's scw CLI config, never from a file in the repo.

**Every time**: confirm the recipient address and the exact file out loud, get the yes, then send:

```
python infra/email/send_document.py --to <recipient> --subject "<subject>" \
  --body "<short plain message>" --attach <output>.pdf
```

Confirm delivery: the script prints the message id when the API accepts it; relay that in one plain sentence. If it fails, read the error (it explains itself) and fix before retrying.

## Safety rules

- Never send without explicit approval of the exact file.
- Never invent invoice numbers; ask, or increment from their records and confirm.
- Always echo amounts back before generating.
- Never guess official numbers (registration, VAT, IBAN); empty stays empty.
