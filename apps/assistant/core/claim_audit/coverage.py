"""What share of what the assistant sent carries the readings behind it, per road.

The claim audit asks for one number: the share of unprompted messages that carry their
readings, above 95%, with every road below the bar naming why in writing. This
module answers it, and it answers with TWO numbers rather than one, because one
number here is a lie with a percent sign on it.

THE DENOMINATOR IS THE HARD PART AND THIS FILE IS HONEST ABOUT IT. There is no
exact per-road count of messages sent anywhere in the container:

  * `chat_turns` is the only COMPLETE record of what reached a phone, and it
    carries no road at all: `outbound.remember_sent` writes every outbound
    message under the one pinned recipient key, so a reply and a two-in-the-
    morning page are the same shape of row.
  * `alerts` is road-aware and INCOMPLETE, in a different way per road: one row
    per fingerprint on the alertmanager road, one per batch on the pen road,
    one per message on beat and morning, and nothing at all for chat, security,
    meeting reminders and teammate messages.

So the output is an exact road-blind total AND a per-road split, and the split
names the roads it cannot see instead of dropping them. Anyone who prints one
number prints a number that flatters whichever road happens to have the most
rows; a report whose denominator is only the roads that keep good records
reports a higher share over a smaller population and calls that progress.

THE JOIN GOES THROUGH `core.roads` AND NOWHERE ELSE. The beat road stores its
readings under the loop name "patrol" while its delivery rows say "beat", so the
obvious join would report that road as having recorded nothing at all, which
is false in the flattering direction: it records every message, under the
other name.

A ROAD WITH NO MESSAGES HAS NO SHARE, not a perfect one. `share` is None when
the road sent nothing in the window, because 0 of 0 rendered as 100% is the
single easiest way to report a dead road as a healthy one.

WHAT THE BEAT DENOMINATOR ACTUALLY HOLDS. The advisor sends through the same
`_send_beat` seam as patrol, so its delivery rows are stamped `beat` too and
this road's count includes them while its readings live under a loop of their
own. That is why `roads.advisor.why_uncounted` exists and why the report prints
it: the beat share is a floor, not an exact figure, and it errs toward looking
worse than it is rather than better.

FAILURE POLICY: Tier-1 fail-loud, like the reads under it. A window that could
not be read must never come back as a coverage of zero or of one.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.assistant.core import roads, state


@dataclass(frozen=True)
class RoadShare:
    """One road a share can honestly be computed for."""

    road: str
    sent: int
    with_readings: int
    recorded: int

    @property
    def share(self) -> float | None:
        """`with_readings / sent`, or None when the road sent nothing.

        None and not 1.0. A road that sent nothing has not achieved perfect
        coverage, it has produced no evidence either way, and a report that
        cannot tell those apart clears a dead road every week it stays dead.
        """
        if self.sent <= 0:
            return None
        return self.with_readings / self.sent


@dataclass(frozen=True)
class UnseenRoad:
    """One road no share can be computed for, and the sentence saying why.

    `sent` and `recorded` are whatever half the road does record, so a reader
    can see that "uncounted" is not the same as "silent": the alertmanager road
    and the pen have readings and no delivery count they can be joined to, and
    security, meeting and teammate messages have neither.
    """

    road: str
    why: str
    sent: int | None
    recorded: int


@dataclass(frozen=True)
class Coverage:
    """One window's coverage: the exact blind total, then the per-road split."""

    messages_sent: int
    shares: tuple[RoadShare, ...]
    unseen: tuple[UnseenRoad, ...]


def between(since_iso: str, until_iso: str) -> Coverage:
    """Coverage for the window, computed from the three records that exist.

    `messages_sent` is EVERY message that reached the phone, replies included,
    counted road-blind off `chat_turns`. It is deliberately not the sum of the
    per-road counts below and must never be rendered as though it were: the two
    answer different questions from different tables, and the gap between them
    is the size of what nothing records, which is the number worth seeing.
    """
    deliveries = state.delivery_counts_between(since_iso, until_iso)
    recorded, backed = _readings_per_loop(since_iso, until_iso)
    shares: list[RoadShare] = []
    unseen: list[UnseenRoad] = []
    for road in roads.unprompted_roads():
        if road.loop is not None and road.delivery_kind is not None:
            shares.append(
                RoadShare(
                    road=road.name,
                    sent=deliveries.get(road.delivery_kind, 0),
                    with_readings=backed.get(road.loop, 0),
                    recorded=recorded.get(road.loop, 0),
                )
            )
            continue
        unseen.append(
            UnseenRoad(
                road=road.name,
                why=road.why_uncounted,
                sent=(
                    deliveries.get(road.delivery_kind, 0)
                    if road.delivery_kind is not None
                    else None
                ),
                recorded=recorded.get(road.loop, 0) if road.loop is not None else 0,
            )
        )
    return Coverage(
        messages_sent=_messages_sent(since_iso, until_iso),
        shares=tuple(shares),
        unseen=tuple(unseen),
    )


def _messages_sent(since_iso: str, until_iso: str) -> int:
    """Every message that reached a phone in the window, road-blind.

    `chat_turns` holds one `assistant` row per delivered outbound message and
    one per chat reply, and `outbound.remember_sent` is the only writer of the
    first kind, so this is the one complete count in the container. What it cannot do
    is say which road any of them came down.
    """
    return sum(
        1
        for turn in state.turns_between(since_iso, until_iso)
        if turn.get("role") == "assistant"
    )


def _readings_per_loop(
    since_iso: str, until_iso: str
) -> tuple[dict[str, int], dict[str, int]]:
    """Messages recorded per loop name, and how many of those carry readings.

    Keyed by LOOP and never by road: `roads.road_of_loop` is the only thing that
    knows "patrol" is the beat road, and doing that translation here rather than
    at the caller is what keeps the beat from reading as a road that recorded
    nothing.
    """
    recorded: dict[str, int] = {}
    backed: dict[str, int] = {}
    for row in state.message_evidence.said_between(since_iso, until_iso):
        loop = str(row.get("loop") or "")
        if roads.road_of_loop(loop) is None:
            continue
        recorded[loop] = recorded.get(loop, 0) + 1
        if row.get("readings"):
            backed[loop] = backed.get(loop, 0) + 1
    return recorded, backed
