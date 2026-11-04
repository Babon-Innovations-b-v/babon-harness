"""Whose fault a red gate is, sorted from what a re-run and the last good tree said.

Tier S sealed seam (workflow/module-standard). Module map:

  `_triage.py`   the rule: a red is the commit's, a test's or the box's
  `__main__.py`  the same rule from the shell, JSON in, lines out

Nothing ever holds the deploy queue: a commit's red is reverted and handed
back, a test's red quarantines that test and the deploy goes on, and a run
that could not happen is run again.
"""
from __future__ import annotations

from ._triage import COMMIT, FLIPPED, OLD, SETUP, TEST, Triage, triage

__all__ = ["COMMIT", "FLIPPED", "OLD", "SETUP", "TEST", "Triage", "triage"]
