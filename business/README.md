# business/

The company's own documents live here: strategy, contracts, quotes, invoices,
registration papers, meeting minutes, anything the business runs on that is
not code. They sit in the repository next to the code, so the agent reads and
writes them with the same tools it uses for source, and a change to a document
is a commit like any other change.

The folder ships empty. This README holds every rule for it: the folders, the
register, the status markers and the business case template. No folder gets a
README of its own.

## Folders

| Folder | What goes in it |
|---|---|
| `01_strategy/` | plans, market notes, business cases |
| `02_finance/` | quotes, invoices, budgets, bank and tax papers |
| `03_legal/` | contracts, terms, privacy and security policy |
| `04_sales/` | customers, offers, marketing copy |
| `05_operations/` | how the company runs: suppliers, processes, the quality system |
| `06_company/` | registration papers, brand assets, team |
| `07_archive/` | superseded versions; never delete anything from it |
| `minutes/` | meeting minutes, written by the minutes app |

`minutes/` has no number because the minutes app writes to it by path:
`NOTULEN_TARGET_PATH` defaults to `business/minutes`. Rename the folder and
change that setting in the same commit. The app files each meeting as
`minutes/YYYY-MM/<who_attended>/YYYY-MM-DD.md`.

Naming: snake_case file names, no spaces; a `YYYY-MM` prefix for dated
documents; `_v1`, `_v2` only when two versions really live side by side. An
old version moves to `07_archive/` with its folder of origin as a prefix.

A fact that gets printed on a generated document (company name, address,
IBAN, registration numbers) belongs in `design/company.yaml`, not here. The
document templates read the profile and never read this folder.

No secrets, keys or passwords. Nothing in `.gitignore` covers `business/`, so a
credential here is a credential in your git history. Secrets belong in the
vault (`infra/secrets/`).

## It is committed, so check where it is pushed

What you put here is committed and pushed with everything else, and the server
keeps a clone of the repository. Before you copy in a signed contract, check
the repository is private:

```
gh repo view --json isPrivate,nameWithOwner
```

Deleting a file later does not remove it from history already pushed.

## The register

Every living document has one row in the register below, added or changed in
the same commit as the document. A document that is not in the register does
not exist for a reader. A bundle of similar files (a year of invoices) gets one
row saying what is in it. `minutes/` is registered as one row with status
`AUTO`; the minutes app does not touch this file.

| Document | Status | Description |
|---|---|---|
| `business/README.md` | CURRENT | This file: folders, register, statuses, case template |

## Status markers

| Status | Meaning |
|---|---|
| `DRAFT` | created, not yet approved |
| `IN PROGRESS` | actively being worked on |
| `CURRENT` | approved and up to date |
| `SIGNED` | a signed contract document |
| `CONFIDENTIAL` | do not share outside the team |
| `AUTO` | written by a machine, such as the minutes |
| `STUB` | only a heading, content still missing |
| `MISSING` | must exist, is not there yet |
| `SUPERSEDED` | replaced, kept only as a trace |
| `ARCHIVE` / `REFERENCE` | an old version, or outside reference material |

Approval: a name and a date at the foot of a document means it is approved.
Add them only when the content is correct and the responsible person agrees;
until then it stays `DRAFT`. An open question is not filled in with a guess:
mark it `TODO` and track it as an issue. A status change updates the register
in the same commit.

## The business case template

A business case is one counterparty or one decision about money, in six
sections. Two rules hold for every case:

1. **The fact rule.** Every figure has a source: a quote, a contract, an
   invoice, a published price. A figure without one is marked `(unverified)`
   or `(inferred)` in the same sentence, every time.
2. **The clean-body rule.** The body states the case as it stands today. What
   changed, what was corrected and what was dropped lives only in the
   changelog appendix.

A section that does not apply says so in one line; it is never silently left
out. Copy this skeleton into `01_strategy/` and fill it in:

```
---
status: DRAFT
type: business-case
last_updated: YYYY-MM-DD
issue: N
---

# [Counterparty or subject]

| | |
|---|---|
| Owner | [name] |
| Status | [one line, present tense] |

## 1. The deal
[What we sell or get, to or from whom, for how much, by when.]

## 2. Where it stands
[Present state, one line per fact, each with its proof: a mail, an issue, a minute.]

## 3. Why now
[The sourced dates that force the timing.]

## 4. The money
| Flow | Amount | Our cost | We keep |
|---|---|---|---|
| | | | |
Break-even: [figure, once]. Or: this table cannot be written yet because [missing inputs].

## 5. What could kill it
| Risk | Weight |
|---|---|
| | |

## 6. Next step
[One action, one owner, one hard date.]

---

## Appendix: assumptions
| Assumption | Value | Confidence | Source |
|---|---|---|---|
| | | published / inferred / unverified | |

## Appendix: changelog
- YYYY-MM-DD: [what changed and why, newest first.]

---
Prepared by [initials, date] · Reviewed by [initials, date] · Approved by [initials, date]
```

Cost in the money table is what it costs you to deliver, never your price.
