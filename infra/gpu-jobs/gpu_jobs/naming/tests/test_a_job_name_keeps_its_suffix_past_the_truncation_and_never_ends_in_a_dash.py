"""A Job name keeps its suffix past the truncation and never ends in a dash.

WHAT IT PINS. `gpu_jobs.naming.job_name`, the one grammar every creator and
every caller that later looks a Job up must agree on:
`{prefix}-{seed[:seed_chars]}[-{suffix}]`, lowercased, no trailing dash.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each name below
is cut and joined by hand from the made-up prefix and seed: count the seed's
characters, keep the first `seed_chars`, lowercase, drop a dash the cut left
at the end, then append the suffix. A suffix folded into the seed would be cut
off again for a long seed, so the long-seed case is the one that matters.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row stops
stripping the trailing dash, so the case whose cut ends on a dash fails.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import pytest

from gpu_jobs.naming.job_name import job_name

CASES = [
    pytest.param("notulen", "ABCDEF123456", 6, "", "notulen-abcdef", id="cut-and-lowercased"),
    pytest.param("notulen", "abcde-fgh", 6, "", "notulen-abcde", id="a-cut-ending-on-a-dash-loses-it"),
    pytest.param("notulen", "short", 20, "", "notulen-short", id="a-short-seed-is-whole"),
    pytest.param(
        "notulen", "0123456789abcdefghijKLMNOP", 20, "Part2",
        "notulen-0123456789abcdefghij-part2", id="the-suffix-survives-a-long-seed",
    ),
]


@pytest.mark.parametrize("prefix, seed, seed_chars, suffix, expected", CASES)
def test_a_job_name_keeps_its_suffix_past_the_truncation_and_never_ends_in_a_dash(
        prefix: str, seed: str, seed_chars: int, suffix: str, expected: str) -> None:
    """The mangled name is the hand-cut one."""
    assert job_name(prefix, seed, seed_chars=seed_chars, suffix=suffix) == expected
