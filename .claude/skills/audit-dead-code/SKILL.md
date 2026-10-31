---
name: audit-dead-code
description: Hybrid mechanical+LLM dead-code audit. Runs vulture (Python), ts-prune (TS), shellcheck SC2034 (bash unused vars), then resolves false positives with an LLM pass over import sites. Use when user says "audit dead code" / "find unused code" / runs the skill mid-refactor; or after a deletion sweep to verify nothing leaked back. Read-only, emits a report, never deletes.
---

# Audit dead code

Three mechanical detectors + one LLM resolver. Outputs a markdown report at `tmp/audit-dead-code-<sha>.md` with three sections: `## Dead`, `## Live`, `## Uncertain`.

The skill is read-only. Deletions are a separate slice (the user reviews the `Dead` section + grep-confirms callers + commits).

## Quick start

```bash
bash .claude/skills/audit-dead-code/scripts/run.sh
```

Output path is printed at the end. Re-runs on the same tree produce the same output (modulo `tmp/` filename SHA).

## Process

### 1. Mechanical pass

### Ask the index first, when the repo has one

If root `CLAUDE.md` names `codebase-memory-mcp` (or the repo otherwise has its index), run this
BEFORE the mechanical tools. It is the query the tool's own README puts forward for dead code, with
the exclusions a real tree needs; add any vendored directory of this repo the same way:

```
MATCH (f)
WHERE f.label IN ['Function','Class']
  AND f.is_test = 'false' AND f.is_entry_point = 'false'
  AND NOT f.file_path CONTAINS 'node_modules'
  AND NOT f.file_path CONTAINS '/vendor/'
  AND NOT f.file_path CONTAINS '/tests/'
  AND NOT f.file_path CONTAINS '/build/'
  AND (f.file_path ENDS WITH '.py' OR f.file_path ENDS WITH '.ts'
    OR f.file_path ENDS WITH '.tsx' OR f.file_path ENDS WITH '.js'
    OR f.file_path ENDS WITH '.mjs' OR f.file_path ENDS WITH '.sh')
  AND NOT EXISTS { (f)<-[:CALLS]-() }
  AND NOT EXISTS { (f)<-[:USAGE]-() }
  AND NOT EXISTS { (f)<-[:CALL_REFERENCE]-() }
  AND NOT EXISTS { (f)<-[:TESTS]-() }
  AND NOT EXISTS { (f)<-[:IMPORTS]-() }
  AND NOT EXISTS { (f)<-[:DECORATES]-() }
  AND NOT EXISTS { (f)<-[:INHERITS]-() }
  AND NOT EXISTS { (f)<-[:OVERRIDE]-() }
RETURN f.label, f.file_path, f.name
```

Add `AND f.file_path STARTS WITH '<tree>/'` to narrow it to what you are auditing. In a framework
project, also exclude the paths the framework dispatches by name (management commands, route
modules), or the class half of the answer is mostly framework entry points.

**It is a candidate list, exactly like `vulture`'s, and it decides nothing.** Some rows are
live through a name the import graph cannot see, and a `grep -w` on the function's name
collides on anything generic, so a quick grep is not proof either way. Settling a specific row means reading it.

**Check what the index holds before quoting a number from it.** If the index also walked worktree
copies of the repo, every count is inflated and nothing announces it:
`MATCH (n) WHERE n.file_path CONTAINS 'worktrees' RETURN count(n)` should read zero before any
measurement is written down.

**Ask it for `Class` too, and never for `Method`.** A method's class is usually reachable, so the
method rows are wall-to-wall `get`, `post` and `put` that a framework calls by name.

**Every exclusion is one class of false positive, and dropping any of them brings that class
back.** Without `is_test` every test function is dead, because pytest collects them and never calls
them. Without `CALL_REFERENCE` a function passed as a value (`set_defaults(func=cmd_download)`,
`map(_try_float, row)`) is dead. `is_entry_point` covers a `main` nothing calls. `IMPORTS`,
`DECORATES`, `INHERITS` and `OVERRIDE` each remove a real false positive: an imported symbol, a
decorated function, an overriding method or an inherited class is used by what reaches it.

**Ask what was indexed before believing a zero.** Every row is a negative claim, and a negative
claim over a scope the indexer skipped is a gap, not a finding:

```
codebase-memory-mcp cli check_index_coverage --project <project> --scopes <tree>
```

Read `metadata.generation_matches` and the `entries` list. No recorded issue does not prove
completeness.

**What it cannot see is the blind spot vulture has too**: a name a framework or a registry
dispatches. `pytest_configure` survives every filter because pytest calls it by name; so does a
re-export in a package `__init__.py` and every entry in a registry keyed by string. It finds the
dead code nothing references by name, which is most of it but not the part a string reaches.

### Then the mechanical tools


Three tools run in parallel; outputs land in `tmp/_audit-mechanical/`:

| Tool | Scope | Catches |
|---|---|---|
| `vulture` | every tracked `*.py` | unused functions, classes, vars, imports, attributes |
| `ts-prune` | every directory with its own `package.json` | unused TypeScript exports |
| `shellcheck -i SC2034` | every tracked `*.sh` | unused bash variables |

**Excluded by default**: vendored third-party code (`vendor/`, `third_party/`, any `*_libs/`), `tests/`, generated code (migrations), `.venv/`, `node_modules/`, and build output.

**If the project is none of these languages** (a Java or Go repo, say), the mechanical pass has nothing to run. Say so plainly and stop; do not substitute a hand-rolled scan and present it as the same thing.

Vulture confidence threshold: `--min-confidence 80` (default). Below that → too noisy.

### 2. LLM resolve pass

For every flagged symbol, gather:

- The symbol's source file + line range.
- `grep -rn` results across the repo (callers, string references, dynamic dispatch hints), and the repo's index tool for the importers of the symbol's file when root `CLAUDE.md` names one.
- Decorator context (`@register_*`, `@app.route`, `@pytest.fixture`).
- Per-framework allow-list signals (a framework's registry strings, a plugin manifest, a settings list that names classes by string).

Importers prove a symbol is reachable, never that it is used: a file with no importers makes every symbol in it a candidate, not a verdict. A string-named import (a framework settings list naming a dotted path) is a real edge, so check for one before calling a module unreferenced. When the index has call edges, ask it who calls the symbol; `search_graph` finds the definition and `search_code` reads the source around it, which is how a `ts-prune` flag gets resolved too.

Prompt (per symbol): "is this dead, live, or uncertain?" with the gathered context. Verdict + one-line reasoning per item.

LLM keeps three buckets:
- **Dead**: confirmed no callers, no string refs, no framework dispatch. Safe to delete.
- **Live**: caller found (the mechanical tool was wrong). Don't delete.
- **Uncertain**: ambiguous (dynamic dispatch, runtime registration, MCP). Human eyeball needed.

### 3. Report

Output at `tmp/audit-dead-code-<HEAD-sha>.md`:

```markdown
# Dead-code audit, <SHA>, <date>

## Dead (N items, safe to delete)
- `src/api/foo.py:42`: `def _unused_helper()`, no callers, no string refs.

## Live (N false positives, leave alone)
- `src/panels/main.py:88`: `register_renderer`, flagged by vulture; called through a registry by name.

## Uncertain (N items, human review)
- `src/registry.py:201`: `LegacyExtractor`, referenced in a `getattr` lookup; cannot prove dead or alive.
```

Re-runs are stable: same tree → same output.

## Common false-positive patterns (LLM allow-list)

The resolver should NOT mark these as dead:
- Framework lifecycle hooks invoked by the framework, not by an import.
- Anything registered by string name in a registry or plugin manifest.
- Pytest `conftest.py` fixtures, referenced by name in test signatures.
- Symbols re-exported in `__init__.py` and referenced as strings elsewhere.
- Route handlers declared by decorator.
- Migrations, applied by name, never imported.

## Failure modes

- **Tool missing**: `vulture` is taken through `uv run --with vulture` when it is not on PATH; `shellcheck` missing skips the bash pass with an install hint.
- **No flagged items**: emits report with empty sections + a `Nothing flagged, clean tree.` note.
- **Nothing in scope**: the repo has no Python, TypeScript or bash. Report that, and do not improvise a replacement pass.

## Out of scope

- Deletion. The skill never modifies code, only reports.
- Test coverage gaps. A different question, and a different tool.
