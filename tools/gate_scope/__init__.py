"""Decide which tests a commit can actually reach.

A deploy gate that runs every test on every commit spends most of its time on
commits whose only changes are documents, pages or config no test can reach.
This package answers one question for the gate: given the changed paths, which
tests could possibly be affected?

Sealed seam: `decide` and `Decision` are the only public names. Everything
else is an implementation detail of how the graph, the floor and the register
triggers are combined, and the shell must not depend on it.
"""
from __future__ import annotations

from .select import Decision, decide

__all__ = ["Decision", "decide"]
