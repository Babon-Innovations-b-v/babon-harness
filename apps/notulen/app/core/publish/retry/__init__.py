"""Retry loop and stuck-detection helpers (``core/publish/retry/``).

Module map:
    git_writer_loop.py        : daemon loop: polls ``committing`` rows, calls finalize_commit
    finalize_commit.py        : the invariant: commit, then mark complete
    stuck_commits.py          : pure stuck-detection; caller passes ``now=``
    alert_stuck_committing.py : throttled ops page for stuck jobs; Tier-2 swallow
"""
