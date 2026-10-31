---
name: tdd
description: Test-driven development with red-green-refactor loop. Use when user wants to build features or fix bugs using TDD, mentions "red-green-refactor", wants integration tests, or asks for test-first development.
---

# Test-Driven Development

## Philosophy

**Core principle**: Tests should verify behavior through public interfaces, not implementation details. Code can change entirely; tests shouldn't.

**Good tests** are integration-style: they exercise real code paths through public APIs. They describe _what_ the system does, not _how_ it does it. A good test reads like a specification - "user can checkout with valid cart" tells you exactly what capability exists. These tests survive refactors because they don't care about internal structure.

**Bad tests** are coupled to implementation. They mock internal collaborators, test private methods, or verify through external means (like querying a database directly instead of using the interface). The warning sign: your test breaks when you refactor, but behavior hasn't changed. If you rename an internal function and tests fail, those tests were testing implementation, not behavior.

See [tests.md](tests.md) for examples and [mocking.md](mocking.md) for mocking guidelines.

## Anti-Pattern: Horizontal Slices

**DO NOT write all tests first, then all implementation.** This is "horizontal slicing" - treating RED as "write all tests" and GREEN as "write all code."

This produces **crap tests**:

- Tests written in bulk test _imagined_ behavior, not _actual_ behavior
- You end up testing the _shape_ of things (data structures, function signatures) rather than user-facing behavior
- Tests become insensitive to real changes - they pass when behavior breaks, fail when behavior is fine
- You outrun your headlights, committing to test structure before understanding the implementation

**Correct approach**: Vertical slices via tracer bullets. One test → one implementation → repeat. Each test responds to what you learned from the previous cycle. Because you just wrote the code, you know exactly what behavior matters and how to verify it.

```
WRONG (horizontal):
  RED:   test1, test2, test3, test4, test5
  GREEN: impl1, impl2, impl3, impl4, impl5

RIGHT (vertical):
  RED→GREEN: test1→impl1
  RED→GREEN: test2→impl2
  RED→GREEN: test3→impl3
  ...
```

## Workflow

### 1. Planning

Before exploring the codebase, follow [../DOMAIN-AWARENESS.md](../DOMAIN-AWARENESS.md). Test names and interface vocabulary should match `CONTEXT.md`.

Before writing any code:

- [ ] Confirm with user what interface changes are needed
- [ ] Confirm with user which behaviors to test (prioritize)
- [ ] Identify opportunities for deep modules, a small interface over a deep implementation: the bar is [`docs/bible.md#workflowmodule-standard`](../../../docs/bible.md#workflowmodule-standard), the vocabulary is [`codebase-design`](../codebase-design/SKILL.md)
- [ ] Design interfaces for testability: accept dependencies instead of creating them ([`docs/bible.md#workflowmodule-standard`](../../../docs/bible.md#workflowmodule-standard)), return results instead of mutating, and keep the surface small. To explore two designs in parallel first, see [DESIGN-IT-TWICE.md](../codebase-design/DESIGN-IT-TWICE.md)
- [ ] List the behaviors to test (not implementation steps)
- [ ] Get user approval on the plan

Ask: "What should the public interface look like? Which behaviors are most important to test?"

**You can't test everything.** Confirm with the user exactly which behaviors matter most. Focus testing effort on critical paths and complex logic, not every possible edge case.

### 2. Tracer Bullet

Write ONE test that confirms ONE thing about the system:

```
RED:   Write test for first behavior → test fails
GREEN: Write minimal code to pass → test passes
```

This is your tracer bullet - proves the path works end-to-end.

### 3. Incremental Loop

For each remaining behavior:

```
RED:   Write next test → fails
GREEN: Minimal code to pass → passes
```

Rules:

- One test at a time
- Only enough code to pass current test
- Don't anticipate future tests
- Keep tests focused on observable behavior

### 4. Refactor

After all tests pass, look for refactor candidates:

- [ ] Extract duplication into a function or class
- [ ] Break long methods into private helpers, keeping the tests on the public interface
- [ ] Deepen or combine shallow modules, moving complexity behind simple interfaces (see [DEEPENING.md](../codebase-design/DEEPENING.md))
- [ ] Move logic to where the data lives, and replace primitive obsession with value objects
- [ ] Apply SOLID principles where natural
- [ ] Consider what the new code reveals about existing code
- [ ] Run tests after each refactor step

**Never refactor while RED.** Get to GREEN first.

## Project notes

- **Test at the highest useful seam.** The boundary that carries the project's core behaviour is where the load-bearing tests belong. Tests below it are for awkward internals, not for coverage.
- **Pin the numbers that would move silently.** A threshold, a tolerance, a format version: a regression there is invisible without a test that fails when it moves.
- **Test the interface that propagates failures**, never the shallow module it replaced.

<Replace this section with the project's own seams once they exist. An honest empty section beats an invented one.>

## Checklist Per Cycle

```
[ ] Test describes behavior, not implementation
[ ] Test uses public interface only
[ ] Test would survive internal refactor
[ ] Code is minimal for this test
[ ] No speculative features added
```
