"""A new test that reads the clock, the network or the machine is named at birth, and one reading only what it built is not.

WHAT IT PINS. `birth.live_reads`, the static half of the birth check `--check
--base` runs on every test a change gives its first row: one sentence per
place a test's source reads the wall clock, the network or the live box, with
its line, and nothing for a source that only reads what it built, even when a
docstring or a string names `/opt`, `time.time()` or `kubectl`.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each source is
a few made-up lines, and its expected sentences are written from the rules in
the module's docstring: the line each call sits on is counted by hand, and the
wording is the one the docstring's categories name.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row stops
recognising `urlopen`, so the case that fetches a URL is let through.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import pytest

from tools.test_register.birth import live_reads

CASES = [
    pytest.param('import time\nstarted = time.time()\n', ("line 2: time.time() reads the wall clock",),
                 id="the-wall-clock"),
    pytest.param('import time\nstamp = time.gmtime(0)\n', (), id="a-fixed-instant-is-not-the-clock"),
    pytest.param('import client\nbody = client.urlopen("https://example.org")\n',
                 ("line 2: urlopen() reads the network",), id="a-fetched-url"),
    pytest.param('import socket\n', ("line 1: imports socket, which reads the network",), id="a-network-module"),
    pytest.param('import subprocess\nsubprocess.run(["kubectl", "get", "pods"])\n',
                 ("line 2: runs kubectl, which reads this machine",), id="the-live-cluster"),
    pytest.param('import subprocess\nsubprocess.run([str(stub), "get", "pods"])\n', (),
                 id="a-stub-it-wrote-itself"),
    pytest.param('from pathlib import Path\ntext = Path("/etc/hostname").read_text()\n',
                 ("line 2: Path() reads /etc/hostname on this machine",), id="a-path-on-the-box"),
    pytest.param('"""Never call time.time() or read /opt here."""\nNOTE = "kubectl get pods"\n', (),
                 id="words-in-a-docstring-are-not-reads"),
    pytest.param('def broken(:\n', ("line 1: the file does not parse, so nothing shows it is sealed",),
                 id="a-file-that-does-not-parse"),
]


@pytest.mark.parametrize("source, expected", CASES)
def test_a_new_test_that_reads_the_clock_the_network_or_the_machine_is_named_at_birth_and_one_reading_only_what_it_built_is_not(
        source: str, expected: tuple) -> None:
    """The sentences named are the ones the rules give, line by line."""
    assert live_reads(source) == expected
