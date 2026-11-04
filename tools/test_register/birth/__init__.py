"""A test's birth: written with its row, refused if it reads anything live, run sealed.

The acts that happen once, when a test first enters the tree: `scaffold` writes
the test file and its register row together; `live_reads` names every place a
new test's source reads the live machine, the wall clock or the network instead
of its own synthetic ground truth; `sealed_run` runs the test files a commit
adds or changes in the pinned gate image with the network off and a fake
clock, through `sealed_argv`; `read_pin` and `pin_drift` read that pin and say
when the image's inputs moved past the commit it was built from.
"""
from __future__ import annotations

from ._pin import PIN, Pin, pin_drift, read_pin
from ._run import CANNOT, sealed_argv, sealed_run
from ._scaffold import TEMPLATE, scaffold
from ._scan import live_reads

__all__ = ["CANNOT", "PIN", "TEMPLATE", "Pin", "live_reads", "pin_drift", "read_pin", "scaffold",
           "sealed_argv", "sealed_run"]
