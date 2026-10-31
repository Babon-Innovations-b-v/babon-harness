"""Pins where a dashboard learns who is signed in.

Caddy's oauth2_auth snippet hands the identity over as Remote-User and
Remote-Email. get_user must prefer the stable account id, fall back to
the email, and never raise.
"""
from __future__ import annotations

from dashkit.core import get_user


def test_remote_user_wins_over_email() -> None:
    headers = {"Remote-User": "alice", "Remote-Email": "alice@example.com"}
    assert get_user(headers) == "alice"


def test_email_used_when_user_missing() -> None:
    assert get_user({"Remote-Email": "bob@example.com"}) == "bob@example.com"


def test_no_headers_is_anonymous() -> None:
    assert get_user({}) == "anonymous"
    assert get_user(None) == "anonymous"


def test_blank_header_is_anonymous() -> None:
    assert get_user({"Remote-User": "   "}) == "anonymous"


def test_basic_auth_header_is_not_an_identity() -> None:
    # The legacy Basic path is gone: a client-sent Authorization header
    # must not be read as a signed-in user.
    assert get_user({"Authorization": "Basic YWxpY2U6cHc="}) == "anonymous"
