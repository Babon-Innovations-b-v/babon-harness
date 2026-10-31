# One language on the engineering surface

**Status:** accepted

Everything on the engineering surface is written in English: code comments and docstrings, `docs/`,
ADRs, `docs/bible.md`, `CONTEXT.md` prose, everything under `.claude/`, GitHub issues, PRD bodies,
issue comments, commit messages, and every reply and artifact an agent produces in this repo.

The reason is that mixed-language prose in one repo makes search unreliable and makes an agent
guess which language a given file wants, which it gets wrong roughly as often as it gets it right.
One language removes the guess.

The exception is content whose reader needs another language: user-facing copy in the product's own
locale, and documents written for a reader who does not work in English. The rule governs comments
and prose; it never governs identifiers, routes, or directory names, which stay whatever they
already are.

The test for a document: English by default, another language only if its reader needs it.
