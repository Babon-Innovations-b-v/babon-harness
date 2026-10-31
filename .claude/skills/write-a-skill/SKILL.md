---
name: write-a-skill
description: Create or edit agent skills with proper invocation choice, information hierarchy, and leading words. Use when user wants to create, write, improve, or debug a skill in this repo.
---

# Writing Skills

A skill exists to wrangle determinism out of a stochastic system. **Predictability**, the agent taking the same *process* every run, not producing the same output, is the root virtue; every rule below serves it. Full definitions of the bold terms: [`GLOSSARY.md`](GLOSSARY.md) (vendored from [Pocock skills](https://github.com/mattpocock/skills)).

## Process

1. **Gather requirements**: task/domain, use cases, scripts or instructions only, reference material, invocation choice (below).
2. **Draft**: `SKILL.md` ≤100 lines; extra reference files when content outgrows it; scripts for deterministic operations.
3. **Review with user**: cases covered, anything unclear, checklist below.

## Invocation: model-invoked or user-invoked

- **Model-invoked** (default here): keeps a `description`, so the agent and other skills can reach it. Costs **context load**: the description sits in the window every turn.
- **User-invoked** (`disable-model-invocation: true`): only the human typing `/<name>` can fire it, and no other skill can. Zero context load, but the human must remember it exists (**cognitive load**).

Pick model-invocation only when the agent or another skill must reach it on its own (grill → wayfinder is the house example). If it only ever fires by hand, make it user-invoked.

## Writing the description

The description does two jobs: state what the skill is, and list the **branches** that trigger it. Every word is context load, so prune hard:

- **Front-load the skill's leading word**; the description is where it does its invocation work.
- **One trigger per branch.** Synonyms renaming the same branch are duplication; collapse them.
- Cut identity already in the body; keep triggers plus any "when another skill needs…" clause.
- Max 1024 chars, third person: first sentence what it does, second "Use when [triggers]".

Good: the `diagnose` description (loop named, distinct triggers). Bad: "Helps with debugging."

## Information hierarchy

Two content types, mixing freely: **steps** (ordered actions) and **reference** (rules and facts consulted on demand). Place each on the ladder:

1. **In-skill step**: ends on a checkable **completion criterion** ("every modified model accounted for", not "produce a list"); vague criteria invite premature completion.
2. **In-skill reference**: a flat peer-set of rules is fine, not a smell.
3. **External reference**: pushed to a linked file, loaded when its **context pointer** fires. The pointer's *wording* decides how reliably the agent reaches it.

**Progressive disclosure** is the move down the ladder: inline what every branch needs, push behind a pointer what only some branches reach. Keep a concept's definition, rules, and caveats under one heading (co-location).

## Leading words

A **leading word** is a compact concept already in the model's pretraining that the agent thinks with (*fog of war*, *frontier*, *tracer bullet*, *red*). It anchors execution in the body and invocation in the description. Hunt for restatements a leading word retires: "fast, deterministic, low-overhead" → a *tight* loop; "a loop you believe in" → the loop goes *red*. Fewer tokens and a sharper hook.

## When to add scripts

Deterministic operation, code that would be regenerated repeatedly, or errors needing explicit handling. Scripts save tokens and beat generated code on reliability.

## House rules

- Exploration skills reference [`../DOMAIN-AWARENESS.md`](../DOMAIN-AWARENESS.md) before exploring code.
- Skill bodies don't duplicate bible content; link chapters via the map in root `CLAUDE.md`.
- Producer skills (writing to bible / glossary / ADRs) follow the inline-write triggers in `grill`.
- Use CONTEXT.md vocabulary; a new domain term goes into CONTEXT.md first.

## Review checklist (failure modes)

- [ ] Description: triggers present, one per branch, leading word front-loaded
- [ ] `SKILL.md` ≤100 lines; reference disclosed one level deep
- [ ] Completion criteria checkable (**premature completion** defence; split the sequence only if a criterion is irreducibly fuzzy *and* the rush is observed)
- [ ] Each meaning in one place (**duplication**), every line still relevant (**sediment**), no path carrying another branch's baggage (**sprawl**)
- [ ] Every sentence passes the **no-op** test: does it change behaviour vs the default? Delete failing sentences whole; fix weak steering with a stronger word (*relentless*), not more prose
- [ ] Prohibitions rephrased positively where possible (**negation** backfires); keep only hard guardrails, paired with what to do instead
- [ ] No time-sensitive info
