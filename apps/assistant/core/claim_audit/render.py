"""The week's audit as text a person reads once and acts on, or does not.

Not a page and not a nudge. It goes to Nextcloud Talk on a Monday morning, so
it is written for somebody with coffee rather than for somebody holding a phone
at two in the morning: the count first, then the rules that fired, then the
sentences under each, so a reader can stop after the first line on a clean week.

It carries two more sections and one disclaimer: what
share of what the assistant sent carries its readings, per road; what arrived that
nobody was ever told about, held pages counted separately because a held page is
the brake working; and what the report does NOT look for, because ten rules
borrowed from the live guards means a defect of an unruled kind produces zero
findings, and a reader who has not been told reads that as a clean week.

Grouped by RULE and not by message, deliberately. Five findings under one rule
is a rule to tighten or a habit to break; five findings across five rules on
one message is one bad message. The first is worth a change and the second is
worth a shrug, and a report grouped by message hides which one you have.

FAILURE POLICY: pure. It formats what it is handed and reads nothing.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

from collections import defaultdict

from apps.assistant.core.claim_audit.coverage import Coverage
from apps.assistant.core.claim_audit.silence import Silence
from apps.assistant.core.claim_audit.week import Judged

# How many example sentences to print under one rule. Enough to see a pattern,
# few enough that a bad week does not produce a wall nobody reads.
MAX_EXAMPLES = 5

# How much of a sentence to print. A whole pen page under every finding would
# bury the finding.
MAX_SENTENCE_CHARS = 160


def report(
    judged: tuple[Judged, ...],
    since_iso: str,
    until_iso: str,
    coverage: Coverage | None = None,
    silence: Silence | None = None,
) -> str:
    """The whole report, headline first, then the two counts, then the limits.

    `coverage` and `silence` are optional so a caller that only wants the claim
    half (a test, a backfill over history) still gets a valid report. The route
    always passes both: what the assistant said checked, plus what the assistant did not say
    counted, is the complete weekly picture and each half without the other
    reads better than the week was.
    """
    flagged = [one for one in judged if one.findings]
    total = sum(len(one.findings) for one in flagged)
    sections = [_headline(len(judged), len(flagged), total, since_iso, until_iso)]
    if judged and flagged:
        sections.append(_findings(flagged))
    if judged:
        # No coverage line under an empty window. "Every message in this window
        # had its readings recorded" is true of no messages and reads as
        # reassurance, which is the opposite of what an empty window means.
        sections.append(_coverage(judged))
    if coverage is not None:
        sections.append(_per_road(coverage))
    if silence is not None:
        sections.append(_silence(silence))
    sections.append(_limits())
    return "\n\n".join(sections)


def _findings(flagged: list[Judged]) -> str:
    """The rules that fired, busiest first, with examples under each."""
    blocks = []
    for rule, entries in _by_rule(flagged):
        lines = [f"{rule} ({len(entries)})", f"  {entries[0][1].says}"]
        for one, finding in entries[:MAX_EXAMPLES]:
            lines.append(f"  {one.loop} {one.said_at}: {_shortened(finding.sentence)}")
        if len(entries) > MAX_EXAMPLES:
            lines.append(f"  and {len(entries) - MAX_EXAMPLES} more")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _per_road(coverage: Coverage) -> str:
    """Readings per road: the exact blind total, then the split, then the gaps.

    The total and the split are printed as two different things ON PURPOSE and
    the line says so. The total is every message that reached a phone, replies
    included, off `chat_turns`, which carries no road. The split counts delivery
    rows, which four roads never write. Printing one number would flatter
    whichever road keeps the best records.
    """
    lines = [
        "READINGS, PER ROAD.",
        (
            f"  {coverage.messages_sent} message(s) reached a phone in this "
            "window in total, counted without roads (`chat_turns`), replies "
            "included. The split below counts delivery rows and does NOT add "
            "up to that total."
        ),
    ]
    for share in coverage.shares:
        if share.share is None:
            lines.append(
                f"  {share.road}: no messages sent in this window, so no "
                f"share. {share.recorded} message(s) recorded."
            )
            continue
        lines.append(
            f"  {share.road}: {share.with_readings} of {share.sent} sent "
            f"message(s) carry their readings ({share.share * 100:.0f}%)."
        )
    if coverage.unseen:
        lines.append("  Roads no share can be computed for, and why:")
        for road in coverage.unseen:
            seen = (
                f"{road.sent} delivery row(s), {road.recorded} recorded"
                if road.sent is not None
                else f"{road.recorded} recorded, no delivery rows"
            )
            lines.append(f"    {road.road} ({seen}): {road.why}")
    return "\n".join(lines)


def _silence(silence: Silence) -> str:
    """What arrived, what nobody heard, and what is waiting on purpose."""
    lines = [
        "SILENCE.",
        (
            f"  Subjects that arrived in this window: {silence.subjects}. "
            f"Never delivered about: {len(silence.unheard)}, of which "
            f"{len(silence.unheard_critical)} could be critical."
        ),
    ]
    if silence.unheard_critical:
        lines.append("  Possibly critical and unheard:")
        for name in silence.unheard_critical[:MAX_EXAMPLES]:
            lines.append(f"    {_shortened(name)}")
        if len(silence.unheard_critical) > MAX_EXAMPLES:
            extra = len(silence.unheard_critical) - MAX_EXAMPLES
            lines.append(f"    and {extra} more")
    lines.append(
        f"  {silence.held} message(s) are held right now and not lost "
        f"({silence.held_pages} written page(s), {silence.held_pings} unread "
        "ping(s)). A held page is the brake working, not a fault."
    )
    lines.append(
        f"  Counts taken at {silence.at}, in one pass over the three tables."
    )
    lines.append(
        "  These are DECISIONS THE POD MADE, never arrivals at Alertmanager. A "
        "null receiver, an inhibit rule, an operator silence, a group_wait "
        "fold, a refused bearer and a malformed body all leave no row at all, "
        "so a night the webhook was broken reads here as a quiet night."
    )
    return "\n".join(lines)


def _limits() -> str:
    """What this report does not look for, said before anyone reads a zero.

    The checker runs ten rules and they are deliberately the same ten the live
    guards use, so a defect of a kind nobody wrote a rule for produces no
    finding at all. A reader who has not been told this reads a zero-finding
    week as a clean week, which is the one conclusion the report cannot support.
    """
    lines = ["WHAT THIS REPORT DOES NOT LOOK FOR."]
    lines.append(
        "  The ten rules above are the ten the live guards already use, so a "
        "kind of mistake nobody has written a rule for produces no finding "
        "here. A week with nothing in it is a week nothing KNOWN went wrong in."
    )
    lines.append(
        "  Not looked for at all: whether a message was worth sending; whether "
        "it was written in the reader's language; whether the tool it read was "
        "itself telling the truth; whether the right person got it; and what "
        f"{ASSISTANT_NAME} chose not to say beyond the silence count above."
    )
    return "\n".join(lines)


def _headline(messages: int, flagged: int, findings: int, since: str, until: str) -> str:
    """The one line that has to be true even if nobody reads further."""
    if not messages:
        return f"No messages recorded between {since} and {until}."
    return (
        f"{findings} finding(s) in {flagged} of {messages} message(s) sent "
        f"between {since} and {until}."
    )


def _coverage(judged: tuple[Judged, ...]) -> str:
    """What the run could not check, said out loud.

    The same reasoning as `evidence.unchecked_footer`: every rule above fires on
    something a message SAYS, so a message with no readings behind it passes all
    of the evidence-taking ones by having nothing to check against. Left unsaid,
    a week of messages recorded before the readings shipped reads as a clean
    week.
    """
    blind = [one for one in judged if not one.readings]
    if not blind:
        return "Every message in this window had its readings recorded."
    return (
        f"{len(blind)} of {len(judged)} message(s) had no readings recorded, so "
        "only the text-only rules could run on them. A message sent before the "
        "recording shipped has none and never will."
    )


def _by_rule(flagged: list[Judged]) -> list[tuple[str, list]]:
    """Findings grouped under their rule, the busiest rule first."""
    grouped: dict[str, list] = defaultdict(list)
    for one in flagged:
        for finding in one.findings:
            grouped[finding.rule].append((one, finding))
    return sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))


def _shortened(sentence: str) -> str:
    """One sentence on one line, bounded."""
    flat = " ".join(sentence.split())
    if len(flat) <= MAX_SENTENCE_CHARS:
        return flat
    return flat[:MAX_SENTENCE_CHARS] + " ..."
