---
name: audit-function-purposes
description: LLM-driven audit of every Python function for the "single purpose" rule (CLAUDE.md). Walks every tracked Python function, judges single | multi | uncertain with one-line reasoning. Outputs a ranked report, multi-purpose fns first. Use when user says "audit function purposes" / "find god functions" / runs the skill mid-refactor or before a decomposition pass. Read-only, emits a report, never refactors.
---

# Audit function purposes

Walks every Python function in scope, judges single-purpose adherence per the rule in `CLAUDE.md`:

> One function, one purpose: Functions doing >1 thing must be split. If the docstring needs "and" between concerns, split it.

Outputs a ranked markdown report at `tmp/audit-function-purposes-<sha>.md`. Read-only, never refactors. Decompositions are separate slices.

## Quick start

```bash
bash .claude/skills/audit-function-purposes/scripts/enumerate.sh
```

The enumerator script lists every candidate fn (path:line, name, length). The agent then reads each candidate and produces verdicts in batches; the final report aggregates them.

## Process

### 1. Enumerate (mechanical)

`scripts/enumerate.sh` uses Python `ast` to list every `def` in scope:

- **Scope**: every tracked `*.py` in the repo. A repo with no Python has nothing to audit here: say so and stop.
- **Exclude**: `**/tests/**`, `**/migrations/**`, `**/__pycache__/**`, `**/.venv/**`, and vendored third-party code (`vendor/`, `third_party/`, any `*_libs/`), which is frozen and not ours to decompose.
- **Output**: `tmp/_audit-function-purposes/candidates.tsv`, `path\tline\tend_line\tlength\tname`.

Sort by length descending. The fattest functions are the most likely violators; agent reads top-N first.

### 2. Judge (LLM)

For each candidate, the agent reads the function source and emits one verdict:

- **single**: the fn does one thing. Even if long, the length is from one cohesive concern (e.g., a long state machine, a single SQL builder).
- **multi**: the fn does ≥2 distinct things. Each should be its own fn. Examples: "fetch X AND validate Y", "render UI AND mutate state", "parse input AND emit side effects AND format output".
- **uncertain**: the fn is borderline (e.g., orchestrator with helpers; could go either way).

One-line reason per verdict. No prose. The agent decides per-fn, not per-file.

#### Length is a heuristic, not a verdict

Long ≠ multi-purpose. A 300-line state machine that decodes one protocol is **single**. A 30-line fn that fetches data, validates it, AND writes a response is **multi**. The agent judges concerns, not lines.

### 3. Report

Output at `tmp/audit-function-purposes-<HEAD-sha>.md`:

```markdown
# Function-purpose audit, <SHA>, <date>

Scope: every tracked *.py
Total fns scanned: 487
Multi-purpose: 12  |  Uncertain: 8  |  Single: 467

## Multi-purpose (decomposition candidates, ranked by fn length)

| Rank | File | Line | Fn | Length | Concerns | Why split |
|---:|---|---:|---|---:|---|---|
| 1 | src/worker.py | 168 | `_run_job` | 241 | parse, resolve, invoke, upload, status, ack | each concern owns its own seam |
| 2 | src/panels/main.py | 88 | `render_doc_panel` | 187 | fetch, hydrate, render | view is not the data layer |
| ... |

## Uncertain (borderline, flag for human review)

...

## Single-purpose (clean), N fns, not listed
```

Re-runs are stable: same tree → same output (modulo ordering ties).

## Out of scope

- Decomposition itself (a separate slice).
- TypeScript / bash function audits (Python only for now; add later if value clear).
- Tests, migrations, vendored libs.
- Cyclomatic complexity / branch counting (heuristic too coarse; the rule is semantic).

## Failure modes

- **Empty scope**: nothing to audit (e.g., wrong tree shape detected). Emits report with `Nothing in scope.`
- **Module parse errors**: a `.py` file fails `ast.parse`. Logged to `tmp/_audit-function-purposes/parse-errors.txt`; the rest of the audit continues.
