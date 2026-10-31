"""Shared hard limits of the two LLM loops, declared once.

Both `core.triage` and `core.chat` bound their Anthropic tool-use loop
and cap their outbound Signal text; these are the single source of
truth for those bounds (campaign rule: one home per duplicated
constant).

FAILURE POLICY: constants only, nothing to fail.
"""
from __future__ import annotations

# Hard cap on one Signal message. Signal itself handles long messages, so
# this is generous, small caps chop answers into many fragments split
# mid-sentence, which reads badly on a phone. Overflow is either truncated
# (triage draft) or split into follow-up messages at whitespace boundaries
# (chat answer, see core/chat._split_answer), never mid-word.
SIGNAL_MAX_CHARS = 1500

# Hard cap on LLM tool-use iterations per alert triage. Also bounds the
# per-call psycopg2/k8s connections the tools may open (see overlay gotcha:
# no connection pooling). Triage is a focused decision on one alert, so it
# stays tight.
LLM_MAX_ITERATIONS = 10

# Chat gets a deeper cap than triage: a real ask ("get to the bottom of these
# alerts and file it if it's a bug") is a multi-step investigation, probe,
# recover from a wrong column guess, cross-check, then act, and 10 turns
# starves it just before it can conclude and write. Same reasoning as the
# patrol cap below; the daily budget cap is the real backstop.
CHAT_MAX_ITERATIONS = 18

# The patrol pass (core/patrol) runs a few times a day: it works the open
# worklist and takes one look around for slow-burn issues. Fewer tool calls
# than the weekly deep survey but more than a single chat turn. Bounded; the
# daily budget cap is the real backstop.
PATROL_MAX_ITERATIONS = 16

# How long a delivered page keeps later pages on its still-firing fingerprint
# out (core/page_hold), and the window the triage prompt tells the model about,
# so the two cannot drift. Long enough to fold Alertmanager's four-hourly
# re-sends into one page, short enough that a fault which never resolves can
# still reach the phone twice a day.
REPAGE_AFTER_HOURS = 12
