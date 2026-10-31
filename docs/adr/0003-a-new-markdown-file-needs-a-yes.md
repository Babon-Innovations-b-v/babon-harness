# A new markdown file needs the owner's go-ahead

**Status:** accepted

Creating a `.md` file anywhere in this repo requires asking the owner first, and taking no for an
answer. Editing an existing one is free.

Documentation is the one artifact an agent can produce without limit and without anyone noticing:
a session ends, a summary file lands, nobody reads it, and the next session reads it as if it were
true. The failure is not that the file is wrong on the day it is written. It is that nothing keeps
it current, so it becomes a confident, stale answer sitting next to the real one. A repo with forty
markdown files has no source of truth; it has forty candidates.

So every markdown file here is living: someone reads it, it has one clear purpose, and it is kept
current. What would have been a new file goes into an existing one, into a `docs/bible.md` chapter,
or as a comment on the issue it belongs to. Generated pages render to a path outside the repo.

**ADRs are covered by this rule.** A decision goes on the issue where it was made, and into its
bible chapter when it is load-bearing. An ADR is a one-line offer ("want this as an ADR?") and is
written only after a yes. A dozen ADRs written in a fortnight is the same problem from the other
end: nobody can hold the set in their head, so nobody consults it.

**Per-directory `CLAUDE.md` overlays are the one standing exception.** An overlay is the mechanism
that loads a directory's rules, so a new code directory without one is a gap rather than a
document, and asking about each one is friction with nobody on the other end.

`.claude/hooks/md_guard.py` blocks the creation routes (the `Write` tool, a shell redirect, `tee`,
`touch`, and `cp` with a markdown destination). A rename is not a creation and stays allowed. The
guard fails open on anything it cannot parse: it must never wedge a legitimate call.
