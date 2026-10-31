"""Pins the SQL identifier gate every dashkit table-name seam runs.

dashkit interpolates ``{domain}_*`` table names into DDL/DML f-strings;
this allowlist is the only thing between a caller-supplied domain and
SQL injection. Own-module test, so it may import
the private gate directly.
"""
from __future__ import annotations

import pytest

from dashkit.core import validate_table_name


def test_plain_snake_case_passes() -> None:
    validate_table_name("notulen_activity")
    validate_table_name("_private")


@pytest.mark.parametrize("bad", [
    "Notulen",            # uppercase
    "1activity",          # leading digit
    "a-b",                # dash
    'x"; DROP TABLE y;',  # injection shape
    "",                   # empty
    "a b",                # whitespace
])
def test_non_identifier_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_table_name(bad)
