"""The roads: every path by which the assistant puts a message in front of a person.

WHY THIS FILE EXISTS. The coverage question is "what share
of unprompted messages carry the readings behind them, per road", and without
this file the word "road" has three definitions, none of them written down and
none of them agreeing:

  * `outbound.remember_readings(loop, ...)` stores the beat's readings under
    the loop name `patrol`
  * `outbound.record_delivery(kind, ...)` stamps that same message `beat`
  * a replay of the recordings maps `delivery:beat` back to a road called `beat`

So a coverage number computed on the obvious join would report the beat road
as having recorded nothing at all, which is false: it records every message,
under another name. A number that wrong in the flattering direction is worse than no
number, because the road it clears is the one that needed looking at.

WHAT A ROAD DECLARES. Its loop name (what `remember_readings` writes), its
delivery kind (what `record_delivery` stamps), whether it starts a conversation
rather than answering one, and, when it cannot be counted, the sentence saying
why. That last field is the point of the file rather than a footnote: the claim audit
asks for a share per road AND for every road below the bar to name its reason in
writing, and a reason that lives in a person's head is a reason that is gone by
the next audit.

THIS FILE DECIDES NOTHING AND ROUTES NOTHING. It is a register, read by the
coverage count and by anything else that needs the roads in one list. Adding a
row here does not create a road, and a road that ships without a row is a gap
the register cannot see. Keep the two in agreement by reading the writers in
this package rather than by trusting this list, in BOTH directions: a loop name declared here
with no writer behind it is as wrong as a writer with no row.

A ROAD WITH NO DENOMINATOR IS DECLARED, NOT OMITTED. Four roads write no
delivery row of any kind, so nothing says how many messages they sent and no
share can be computed for them. They are in the list with `delivery_kind=None`
and a reason, because a coverage report that silently drops the roads it cannot
measure reports a higher number over a smaller population and calls it progress.

FAILURE POLICY: pure data and pure lookups. No I/O, no state, nothing to fail.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Road:
    """One path from the assistant to a person, and what it records about itself."""

    name: str
    loop: str | None
    delivery_kind: str | None
    unprompted: bool
    why_uncounted: str


#: Every road, declared once. `loop` is the name its readings rows carry and
#: None when it records none; `delivery_kind` is the name its delivery rows
#: carry and None when it writes none; `why_uncounted` is empty exactly when
#: both are present, which is the only case a share can be computed for.
ROADS: tuple[Road, ...] = (
    Road(
        name="chat",
        loop="chat",
        delivery_kind=None,
        unprompted=False,
        why_uncounted=(
            "a reply writes no delivery row: `chat-reply` is declared in "
            "`outbound.DELIVERY_KINDS` and has never had a call site, so the "
            "count of chat messages comes from `chat_turns` and not from the "
            "audit table"
        ),
    ),
    Road(
        name="beat",
        loop="patrol",
        delivery_kind="beat",
        unprompted=True,
        why_uncounted="",
    ),
    Road(
        name="morning",
        loop="morning",
        delivery_kind="morning",
        unprompted=True,
        why_uncounted="",
    ),
    Road(
        name="pen",
        loop="pen",
        delivery_kind=None,
        unprompted=True,
        why_uncounted=(
            "the pen sends its own message and writes a `pen flush (...)` audit "
            "row instead of a delivery row, so its denominator is that row and "
            "not `record_delivery`"
        ),
    ),
    Road(
        name="alertmanager",
        loop="triage",
        delivery_kind=None,
        unprompted=True,
        why_uncounted=(
            "triage records its readings once per pass, silences included, "
            "while `page_hold` packs several passes into one `page` "
            "delivery row, so the two counts are of different things and no "
            "share joins them"
        ),
    ),
    Road(
        name="advisor",
        loop="advisor",
        delivery_kind=None,
        unprompted=True,
        why_uncounted=(
            "the advisor sends through the same `_send_beat` seam as patrol and "
            "its delivery row is therefore stamped `beat` too, so nothing in the "
            "audit table tells a Monday advisory note from an afternoon patrol "
            "line; giving it `beat` here would divide two numerators by one "
            "denominator and report both roads wrong"
        ),
    ),
    Road(
        name="security",
        loop=None,
        delivery_kind=None,
        unprompted=True,
        why_uncounted=(
            "the security page sends through `shared.signal` directly and "
            "records neither readings nor a delivery row, so nothing says how "
            "many it sent or what it read"
        ),
    ),
    Road(
        name="meeting",
        loop=None,
        delivery_kind=None,
        unprompted=True,
        why_uncounted=(
            "a meeting reminder is deterministic, has no model in its path and "
            "reads no tools, so there is nothing for a claim checker to check; "
            "it is declared so the register stays a complete list of what "
            "reaches a phone"
        ),
    ),
    Road(
        name="teammate",
        loop=None,
        delivery_kind=None,
        unprompted=True,
        why_uncounted=(
            "a teammate message is relayed on a person's instruction rather "
            "than composed by a beat, and it records neither readings nor a "
            "delivery row"
        ),
    ),
)


def by_name(name: str) -> Road | None:
    """The declared road called `name`, or None when nothing declares it."""
    for road in ROADS:
        if road.name == name:
            return road
    return None


def road_of_loop(loop: str) -> str | None:
    """The road whose readings rows carry `loop`, or None when none does.

    The join the coverage count needs and the one that was wrong: `patrol` is
    the loop name and `beat` is the road, and reading either as the other
    silently reports the wrong road as unrecorded.
    """
    for road in ROADS:
        if road.loop == loop:
            return road.name
    return None


def loops() -> tuple[str, ...]:
    """Every loop name a road records its readings under, in declared order."""
    return tuple(road.loop for road in ROADS if road.loop is not None)


def unprompted_roads() -> tuple[Road, ...]:
    """The roads that start a conversation rather than answering one.

    The population the claim audit measures. A reply is not in it: a message a person
    asked for is judged by the person who asked, in the moment, which is the
    one review this whole effort is not trying to replace.
    """
    return tuple(road for road in ROADS if road.unprompted)


def countable_roads() -> tuple[Road, ...]:
    """The roads a share can honestly be computed for.

    Both ends present: a loop name saying what was recorded and a delivery kind
    saying how many went out. Everything else is reported by name with its
    reason rather than folded into a denominator that flatters it.
    """
    return tuple(
        road
        for road in ROADS
        if road.loop is not None and road.delivery_kind is not None
    )
