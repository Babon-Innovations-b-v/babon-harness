# Work on `main` only

**Status:** accepted

Every change lands directly on `main`. No feature branches, no pull requests for ordinary work, no
long-lived integration branch.

The reason is that this is a small repo with one or two people and an agent working in it, and the
review a PR buys is review nobody was going to do. What a PR actually adds here is a queue: work
that is finished sitting unmerged, a second place to look for the current state of the code, and a
branch name to remember. The cost of the alternative is real but bounded: a bad commit on `main` is
one revert away, and there is no deployment behind it that a revert cannot reach.

This is durable authorization for automated sessions too, including background jobs, which
otherwise default to "push a branch and open a draft PR, never push main". That default is
overridden in this repo; the root `CLAUDE.md` states it so a fresh session reads it before acting.

Two things do not change: a push is still the moment work becomes visible to everyone, so the tests
run before the push and not after; and a genuinely risky change is still worth a branch, by
judgment, not by process.
