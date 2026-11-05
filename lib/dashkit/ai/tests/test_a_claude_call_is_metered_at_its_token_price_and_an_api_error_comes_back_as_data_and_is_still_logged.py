"""A Claude call is metered at its token price, and an API error comes back as data and is still logged.

WHAT IT PINS. `dashkit.ai.call_claude`, the one metering seam every dashboard's
model call goes through: the answer carries the tokens and their cost, a fenced
JSON answer is parsed when asked for, an API error is returned as
`{"error": ...}` rather than raised, and every call, failed or not, hands one
row to the `{domain}_ai_calls` log. The Anthropic client and the log writer are
replaced by recorders, so nothing leaves the box.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The cost is
worked out by hand from the published Sonnet price the module states, $3 per
million input tokens and $15 per million output: 2,000 in and 400 out is
0.006 + 0.006 = $0.012. The JSON is written inside a markdown fence, and the
parsed value is the object written there.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row prices
output tokens at the input rate, so the cost case fails.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import anthropic
import pytest

call_module = importlib.import_module("dashkit.ai.call_claude")

FENCED = 'Here it is:\n```json\n{"actions": 2, "owner": "sam"}\n```'

CASES = [
    pytest.param("answer", "cost_estimate", 0.012, id="metered-at-the-token-price"),
    pytest.param("answer", "parsed", {"actions": 2, "owner": "sam"}, id="fenced-json-parsed"),
    pytest.param("log", "success", True, id="a-good-call-is-logged"),
    pytest.param("log", "table", "notulen_ai_calls", id="logged-to-the-domains-table"),
    pytest.param("error-answer", "error", "api_error", id="an-api-error-is-data"),
    pytest.param("error-log", "success", False, id="a-failed-call-is-still-logged"),
]


class _Messages:
    def __init__(self, fail: bool) -> None:
        self.fail = fail

    def create(self, **_request) -> SimpleNamespace:
        if self.fail:
            raise anthropic.APIError("upstream refused", request=None, body=None)
        return SimpleNamespace(
            content=[SimpleNamespace(text=FENCED)],
            usage=SimpleNamespace(input_tokens=2000, output_tokens=400),
        )


@pytest.mark.parametrize("where, field, expected", CASES)
def test_a_claude_call_is_metered_at_its_token_price_and_an_api_error_comes_back_as_data_and_is_still_logged(
        where: str, field: str, expected: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """The named field of the answer or of the logged row is the hand-derived value."""
    fail = where.startswith("error")
    logged: list[dict] = []
    monkeypatch.setattr(
        call_module.anthropic, "Anthropic", lambda: SimpleNamespace(messages=_Messages(fail)),
    )
    monkeypatch.setattr(
        call_module, "log_ai_call",
        lambda conn, table, **row: logged.append({"table": table, **row}),
    )
    answer = call_module.call_claude(
        "You structure minutes.", "Two actions for Sam.",
        ai_calls_table="notulen_ai_calls", expect_json=True,
    )
    assert len(logged) == 1
    seen = logged[0] if where.endswith("log") else answer
    assert seen[field] == expected
