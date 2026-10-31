"""The one test for `apps/assistant`: the guards between a draft and
somebody's phone must catch the message that would be wrong, and leave the
honest one alone.

WHY THIS FILE IS THE WHOLE MODULE'S TEST. The assistant is built on OpenClaw,
and and nearly everything it does ends as one Signal message on a
person's phone. Every way this module can hurt anyone is a wrong
message: a calendar booking it never made, reported as done; a note
written to a teammate delivered to the owner; a wall of text sent as
one message; a deploy sha in place of news. The thing that WRITES
those messages is a call to Anthropic and cannot be tested here. Everything
standing between it and the phone can: the guards are pure text predicates
with no I/O, each with one stated rule you can apply by hand to a candidate
message and know the verdict before running anything.

WHAT AN INDEPENDENT ANSWER MEANS HERE. A case is a candidate message plus the
turn it was drafted in, and the expected verdict comes from the guard's rule,
never from a recorded output. "A draft claiming a write is allowed through only
if a matching write tool succeeded this turn" decides both halves of the
receipts cases without running anything: no receipt must nudge, the receipt
must pass, and one receipt cannot back a claim about two writes. "A patrol line
has one destination" decides the addressing cases the same way.

THE LAST PART ASSERTS PROPERTIES INSTEAD. The splitter's answer is checked
against a greedy word-packer written out here rather than imported, plus the
two things that hold for any correct splitter whatever the cap is set to: no
piece may exceed the cap, and the words must come back in order with none lost
and none cut in half. That is the failure worth catching, because the fix for
an over-long message must never become a truncated one.

NOT COVERED, deliberately: nothing here sends, and nothing here asks the model
anything. Whether a nudge actually changes what the model writes next, and
whether signal-cli then delivers it, are questions for a live run against a real
Signal account. This file is the deterministic half.
"""
from __future__ import annotations

from apps.assistant.shared.zone import LOCAL_ZONE, LOCAL_ZONE_NAME

from apps.assistant.shared.name import ASSISTANT_NAME

import importlib
import re

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apps.assistant.core import claims, patrol
from apps.assistant.core.limits import SIGNAL_MAX_CHARS
from apps.assistant.core.signal_text import split_for_signal

# The write tools a chat turn declares. Written out as the plain strings the
# LLM surface publishes rather than imported from `core.tools.write_tools`,
# so the expectations below stand on the tool's NAME, which is the contract,
# and not on a constant the guard also reads.
CALENDAR_TOOL = "agenda_act"
CHAT_WRITE_TOOLS = {"agenda_act", "message_teammate", "github_act"}

# The people registry, in the exact `SIGNAL_PEOPLE` grammar the container's secret
# uses: `uuid:<id>=Name:role:+E164`. This is configuration the module reads
# from the environment on every call, not a stand-in for any code under test.
PEOPLE = (
    "uuid:alex-uuid=Alex:dev:+15550100001,"
    "uuid:sam-uuid=Sam:dev:+15550100015,"
    "uuid:robin-uuid=Robin:legal"
)
ALEX_PHONE = "+15550100001"
SAM_PHONE = "+15550100015"
NOBODYS_PHONE = "+15550100016"

# A line addressed to a teammate, of the kind the patrol gate must not put on
# the owner's phone.
THE_MISADDRESSED_LINE = (
    "Sam, het verslag staat klaar in de repo. "
    "Wil je er even naar kijken?"
)
# The same teammate, spoken ABOUT rather than TO. This is what a patrol note is
# FOR, so a guard that holds this one has silenced the beat.
A_LINE_ABOUT_SAM = (
    "Sam pushed a fix to the deploy gate this morning and the cycle is green "
    "again."
)


@pytest.fixture
def registry(monkeypatch):
    """Point the people registry and the pinned recipient at a known team.

    Returns a setter so a case can move the phone the line is going to, which
    is the only variable the addressing rule turns on.
    """
    monkeypatch.setenv("SIGNAL_PEOPLE", PEOPLE)
    monkeypatch.setenv("SIGNAL_ALLOWLIST", "")

    def deliver_to(number: str) -> None:
        monkeypatch.setenv("SIGNAL_RECIPIENT", number)

    deliver_to(ALEX_PHONE)
    return deliver_to


# ── Confabulation: a write the assistant says it made ──────────────────────────────


def test_a_booking_assistant_never_made_is_caught_before_it_is_confirmed() -> None:
    """Ask for a calendar event, draft "done", call no tool: that must nudge.

    The rule needs no recorded output to apply: the person asked for a write,
    the draft says the write happened, and no `agenda_act` succeeded this turn,
    so the draft is a lie and the guard must say which tool would have made it
    true. The user-visible failure is a meeting nobody is coming to.
    """
    request = ["can you put a sync with Sam in my calendar tomorrow at 10:00?"]
    draft = "Done, set for tomorrow at 10:00."

    nudge = claims.unbacked_write_claim(draft, request, [], CHAT_WRITE_TOOLS)

    assert nudge is not None, "a booking claimed with no successful write passed"
    assert CALENDAR_TOOL in nudge, (
        f"the nudge does not name the tool that would make the claim true: {nudge!r}"
    )


def test_the_same_confirmation_passes_once_the_write_really_landed() -> None:
    """The honest half, and the half that keeps the guard usable.

    Byte-identical draft, byte-identical request, one successful `agenda_act`
    receipt: the claim is now backed and nothing may be nudged. A guard that
    fires here accuses the assistant of inventing work it actually did, which is
    what a widened claim regex does to every landed calendar move.

    The second half is the read-only surface: patrol carries no calendar tool,
    and a loop is never nudged about a tool it does not have.
    """
    request = ["can you put a sync with Sam in my calendar tomorrow at 10:00?"]
    draft = "Done, set for tomorrow at 10:00."

    assert (
        claims.unbacked_write_claim(draft, request, [CALENDAR_TOOL], CHAT_WRITE_TOOLS)
        is None
    ), "a claim backed by a successful write was nudged anyway"
    assert (
        claims.unbacked_write_claim(draft, request, [], {"github_act"}) is None
    ), "a loop with no calendar tool was nudged about the calendar"


def test_one_receipt_cannot_back_a_claim_about_two_writes() -> None:
    """"Done, both removed." with one successful call is still a lie.

    Counting is the whole point: one write landed, the draft claims two, so one
    of the two events is still in the calendar and the person has been told it
    is gone. Two receipts back it and
    must pass, which is the same fixture proving the count is what is read and
    not the word "both".
    """
    request = ["can you remove both events from my agenda tomorrow?"]
    draft = "Done, both removed."

    assert (
        claims.unbacked_write_claim(draft, request, [CALENDAR_TOOL], CHAT_WRITE_TOOLS)
        is not None
    ), "a claim about two removals passed on one successful write"
    assert (
        claims.unbacked_write_claim(
            draft, request, [CALENDAR_TOOL, CALENDAR_TOOL], CHAT_WRITE_TOOLS
        )
        is None
    ), "two successful writes did not back a claim about two"


# ── Misdelivery: one person's message on another person's phone ────────────


def test_a_line_written_to_one_teammate_is_held_back_from_another_phone(
    registry,
) -> None:
    """the original message, and the two lines that must NOT be held.

    A patrol pass writes free text with one destination, so the name at the
    front of it routes nothing. Addressed to a teammate and going to the owner's phone,
    the line must be held and the addressee named. Delivered to a teammate's own
    phone the same words are correct and must pass. And a line ABOUT a teammate going
    to the owner is a patrol note doing its job: holding that one would silence the
    beat, which is a worse failure than the one being fixed.
    """
    assert patrol.misaddressed_to(THE_MISADDRESSED_LINE) == "Sam", (
        "a line opening 'Sam,' was cleared for Alex's phone"
    )
    assert patrol.misaddressed_to(A_LINE_ABOUT_SAM) is None, (
        "a note ABOUT a teammate was held, so the beat has been silenced"
    )

    registry(SAM_PHONE)
    assert patrol.misaddressed_to(THE_MISADDRESSED_LINE) is None, (
        "a line to Sam was held on the way to Sam"
    )


def test_a_recipient_the_registry_cannot_place_counts_as_the_wrong_reader(
    registry,
) -> None:
    """An addressee nobody confirmed is not a confirmed one.

    The pinned number belongs to no registry entry, so nothing establishes that
    the person being addressed is the person holding the phone. Holding the
    line costs a beat; sending it costs one teammate's message landing on
    another teammate's phone, which is what this guard exists for.
    """
    registry(NOBODYS_PHONE)

    assert patrol.misaddressed_to(THE_MISADDRESSED_LINE) == "Sam", (
        "an unresolvable recipient was treated as the addressee"
    )


# ── Plumbing: true, and not news ───────────────────────────────────────────


def test_a_deploy_sha_in_a_message_is_caught_as_assistants_own_bookkeeping() -> None:
    """A commit sha is something the assistant knows and nobody acts on.

    The rule is about the READER, not about truth: a sha, a routing decision or
    a component count are all correct and none of them is anything a person on
    a phone does something about. The second draft is the same news said in the
    reader's terms and must pass untouched, because a guard that can suppress a
    real report is a bug.
    """
    assert (
        claims.own_plumbing("The deploy of 3f9a1c2 landed on the box at 09:02.")
        is not None
    ), "a deploy sha went out as news"
    assert (
        claims.own_plumbing(
            "The nightly backup did not run last night, the unit failed at 02:00."
        )
        is None
    ), "a real report was flagged as plumbing"


# ── The cap: long is split, never truncated ────────────────────────────────


def _pack_by_hand(words: list[str], limit: int) -> list[str]:
    """A greedy word-packer, written out here on purpose.

    Six lines of the plain definition ("break only at whitespace, fit as many
    words as the cap allows") rather than a call into `signal_text`. Building
    the expectation with the code under test would make this self-consistency,
    which is what the deleted suite was made of.

    One tie is left undefined: a piece landing on EXACTLY the cap. The fixtures
    below use words of one length chosen so no piece can, so the two
    implementations cannot disagree over a case neither of them decides.
    """
    pieces: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else current + " " + word
        if len(candidate) <= limit:
            current = candidate
        else:
            pieces.append(current)
            current = word
    pieces.append(current)
    return pieces


def test_a_long_message_is_split_to_fit_and_loses_not_one_word() -> None:
    """Over the cap, a message goes out in pieces that fit, with all of it.

    Without a cap an autonomous beat can put a note of over two
    thousand characters out as one message. The fix has a
    failure mode of its own that is worse than the bug: a splitter that trims to
    fit drops the ask at the end of the note, and nobody would see it go
    missing. So all three hold here, every piece within the cap, the packing
    the plain greedy rule produces, and every word back in its original order.

    The words themselves carry nothing; the fixture is a length, built from
    nine-character words so no piece can land exactly on the cap.
    """
    words = [f"word{index:05d}" for index in range(380)]
    message = " ".join(words)
    assert len(message) > 2180, "the fixture is too short to need splitting"

    pieces = split_for_signal(message)
    by_hand = _pack_by_hand(words, SIGNAL_MAX_CHARS)

    # A vacuous pass would be the worst outcome here: it would read as the cap
    # holding while nothing was ever split.
    assert len(by_hand) >= 3, (
        f"the cap ({SIGNAL_MAX_CHARS}) no longer splits this message at all"
    )
    assert max(len(piece) for piece in pieces) <= SIGNAL_MAX_CHARS, (
        "a piece longer than the cap was handed to the sender"
    )
    assert " ".join(pieces).split() == words, (
        "the split lost, reordered or cut a word; a trimmed message is worse "
        "than a long one"
    )
    assert pieces == by_hand, (
        "the split does not pack greedily at whitespace: "
        f"{[len(piece) for piece in pieces]} against {[len(piece) for piece in by_hand]}"
    )


def test_a_message_that_already_fits_goes_out_as_one_piece() -> None:
    """The normal case, and the other half of the cap.

    Almost every message the assistant sends is short. Splitting one of those into
    fragments reads as a stutter on a phone, so a message under the cap must
    come back whole, as a single piece, with only its surrounding whitespace
    gone.
    """
    note = "The backup ran at 02:00 and finished clean."

    assert split_for_signal(f"  {note}\n") == [note]


# ---------------------------------------------------------------------------
# The morning gate: one night of pings, one morning message.
#
# This section reaches for a temp SQLite file, which the header above says the
# rest of this file does not. The widening is deliberate and it is the smallest
# one available: the invariant is about WHEN a queue lets something go, and a
# queue with no state is not the thing under test. Nothing here sends, asks a
# model, or touches the container's real database; the send seam is replaced with a
# list so "reached a phone" is a number this file can count.
#
# The shape these cases are drawn from: the overnight hold works and no
# ping reaches the phone, then several composers each take their own turn
# within the hour, the first of them before the report it belonged in.
# ---------------------------------------------------------------------------

_LOCAL_TZ = LOCAL_ZONE


def _at(hour: int, minute: int, day: int = 31) -> datetime:
    """One instant, local. Aware, because every gate under
    test converts to its own zone and a naive one would read as UTC, which is
    the two-hour slip that would move a 02:00 page into the afternoon."""
    return datetime(2026, 8, day, hour, minute, tzinfo=_LOCAL_TZ)


@pytest.fixture()
def phone(tmp_path, monkeypatch) -> list[str]:
    """A fresh queue and a list standing in for the phone.

    Only the outermost seam is replaced: the Signal send. The gates, the fold,
    the pacing and the bookkeeping all run for real, because they are what
    decides whether a morning is one message or four.
    """
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.delenv("ASSISTANT_QUIET_HOURS", raising=False)
    monkeypatch.delenv("ASSISTANT_MORNING_GATE_UNTIL", raising=False)
    # No wait for the weekday brief: these cases pin the gate's clock,
    # and the brief carrying the night is pinned on its own.
    monkeypatch.setenv("ASSISTANT_BRIEF_WAIT_MINUTES", "0")
    from apps.assistant.core import page_hold

    landed: list[str] = []
    monkeypatch.setattr(
        page_hold._signal_dispatch, "send", lambda subject, body: landed.append(body) or True
    )
    return landed


def test_a_night_of_pings_and_a_held_beat_reach_the_phone_as_one_message(phone) -> None:
    """The case this whole change exists for.

    A page written in the small hours and a beat written before breakfast: two
    composers, one message, not two sends, one when quiet hours end and one
    whenever the beat happens to fire.
    """
    from apps.assistant.core import page_hold, state

    state.hold_page("the night: 24 pings, the deploy queue is red", road="pen",
                    now=_at(2, 0).isoformat())
    # The old first message: the moment quiet hours end, and nothing may leave.
    assert page_hold.release(_at(7, 30)) is None
    page_hold.hold_beat("the deploy pipeline is gate-red this morning", subject="patrol")
    assert page_hold.release(_at(7, 45)) is None

    assert page_hold.release(_at(8, 0)) is not None

    assert len(phone) == 1
    message = phone[0]
    assert "24 pings" in message
    assert "gate-red" in message


def test_a_patrol_finding_in_the_night_is_held_and_arrives_in_the_morning(
    phone, monkeypatch
) -> None:
    """An overnight finding, from the pass that finds it to the phone.

    A patrol that DROPS a line written inside quiet hours gives an overnight
    finding two possible fates, both wrong: the condition clears before
    morning and nobody is ever told, or it is still findable and the next pass
    reports it as present news about a container that has long been up again.

    The pass staying silent at night is not the bug and is not changed here.
    Everything except the model and the tool surface runs for real, because the
    thing under test is which road the finding takes.
    """
    from types import SimpleNamespace

    from apps.assistant.core import outbound, page_hold, state

    finding = "assistant-whisper stopped answering at 23:06"
    # Night for the pass, which asks with no moment, and for the 02:30 release;
    # morning for the 08:00 one. `page_hold` imports the same module, so a flat
    # True here would hold the morning too and the test would pin nothing.
    monkeypatch.setattr(
        patrol._quiet_hours, "quiet_now", lambda *a, **k: not a or a[0].hour < 8
    )
    monkeypatch.setattr(patrol._self_context, "render", lambda *a, **k: "system")
    monkeypatch.setattr(patrol, "_patrol_tool_definitions", lambda: [])
    monkeypatch.setattr(
        patrol._brain,
        "run",
        lambda **kwargs: SimpleNamespace(
            finished=True,
            status="finished",
            response=SimpleNamespace(
                content=[SimpleNamespace(type="text", text=finding)]
            ),
        ),
    )

    # Nothing leaves at night, which was always right.
    assert patrol.patrol() is None
    assert page_hold.release(_at(2, 30)) is None

    assert page_hold.release(_at(8, 0)) is not None
    assert len(phone) == 1, "the morning was not one message"
    message = phone[0]
    assert finding in message, (
        "the overnight finding never reached the phone at all, which is the "
        "half of this failure nobody would ever have noticed"
    )
    assert re.search(r"Overnight, \d\d:\d\d:", message), (
        "a night reading reached the morning with no hour on it; that missing "
        "hour is what let it read as present news"
    )

    reasons = [row["reason"] for row in state.list_recent_alerts()]
    assert "quiet-hours-held" in reasons, "the audit row does not say it was held"
    assert "quiet-hours" not in reasons, (
        "the held finding is still recorded under the word that means lost"
    )
    assert "quiet-hours-held" in outbound.QUIET_REASONS, (
        "the reason is outside the closed vocabulary, so nobody can count it"
    )


def test_a_night_nobody_reports_on_still_reaches_the_phone(phone) -> None:
    """The clock is the whole rule, and the reason it is not optional.

    It was the backstop under an issue, for a brief that runs Monday to Friday
    while this queue fills every day. No brief runs on a Saturday, so the
    deadline is what opens it. Without one a Saturday night would wait until
    Monday, which is a silence dressed as calm.
    """
    from apps.assistant.core import page_hold, state

    state.hold_page("a saturday night page", road="pen", now=_at(2, 0, day=29).isoformat())
    assert page_hold.release(_at(7, 30, day=29)) is None
    assert page_hold.release(_at(7, 59, day=29)) is None
    assert page_hold.release(_at(8, 0, day=29)) is not None
    assert len(phone) == 1


def test_the_morning_gate_holds_nothing_outside_the_morning(phone) -> None:
    """An afternoon page leaves on the afternoon's rules.

    The gate is a stretch of clock, not a mode. Getting this wrong would hold
    every page all day, which is the same silent failure as holding the night
    for ever, just louder.
    """
    from apps.assistant.core import page_hold, state

    state.hold_page("an afternoon page", road="pen", now=_at(14, 0).isoformat())
    assert page_hold.release(_at(14, 0)) is not None


def test_nothing_is_marked_sent_when_the_send_failed(phone, monkeypatch) -> None:
    """A page marked released that never arrived is the quiet failure this
    queue exists to make impossible, so a refused send keeps every row."""
    from apps.assistant.core import page_hold, state

    monkeypatch.setattr(page_hold._signal_dispatch, "send", lambda subject, body: False)
    # The failure's backoff lives in this throwaway, not in the next test.
    monkeypatch.setattr(page_hold, "_outage", page_hold._SendOutage())
    state.hold_page("a page nobody received", road="pen", now=_at(2, 0).isoformat())

    assert page_hold.release(_at(8, 0)) is None
    assert state.pending_page_count() == 1


def test_the_pen_queues_its_night_page_instead_of_sending_it_at_half_seven(
    phone,
) -> None:
    """The pen's night page, on the road that produces it.

    The pen composes and sends on its own road, outside the shared brake, so
    a page it sends at 07:30 is untouched by everything else here unless it
    asks the gate the same question, which is what this pins. Inside the
    morning window it queues; outside it, it still sends on its own pacing,
    because a brake in front of a road that already paces itself is the second
    brake `page_hold` refuses to be.
    """
    from apps.assistant.core import notify_flush, page_hold, state

    assert notify_flush._morning_gate_shut(_at(7, 35)) is True
    assert notify_flush._morning_gate_shut(_at(14, 0)) is False

    notify_flush._hold_for_the_brief("the night: 24 pings, the deploy queue is red", [])
    assert page_hold.release(_at(7, 35)) is None, "the queued page must wait"
    assert not phone

    assert page_hold.release(_at(8, 0)) is not None
    assert len(phone) == 1
    assert "24 pings" in phone[0]

    # The clock opened it, and nothing is left behind.
    assert state.pending_page_count() == 0


# ---------------------------------------------------------------------------
# What a page reads like. An unreadable page that says little is four
# separate defects, and each of these pins one of them.
#
# The example batch: a collector unit failed at 05:30 local, and an audit
# unit plus the audit's own report both arrived at 04:40.
# ---------------------------------------------------------------------------

_TEXTFILE = "❌ [the project] systemd unit failed: example-collector.service"
_GATE_AUDIT = "🟡 [the project] gate audit: the unselected suite is red"
_GATE_UNIT = "❌ [the project] systemd unit failed: example-audit.service"


def _ping(ping_id: int, subject: str, when: str, unit: str | None = None) -> dict:
    body = f"Host: harness-internal\nUnit: {unit}\n" if unit else "A body."
    return {
        "id": ping_id, "subject": subject, "body": body, "source": "notify",
        "received_at": when, "facts": '{"exit_code": 2}',
    }


def _page(pings: list[dict], *, lead: int, aspect: str, also=(), seen: int = 1,
          language: str = "en") -> str:
    from apps.assistant.core import page_render, ping_facts

    facts = ping_facts.bundle(pings, history_of=lambda _s: {"seen_count": seen})
    selection = page_render.Selection(
        verdict="page", lead=lead, aspect=aspect, also=tuple(also)
    )
    return page_render.render(selection, facts, language=language)


def test_a_page_says_the_time_and_not_the_date_it_is_read_on() -> None:
    """A stamp on a page about this morning, read this morning.

    Not the full date and two clocks on every sentence:
    "2026-06-02 05:30 local (03:30 UTC)", three times in one page.
    """
    page = _page(
        [_ping(3, _TEXTFILE, "2026-06-02T03:30:19+00:00", "example-collector.service")],
        lead=3, aspect="failure",
    )
    assert "05:30" in page
    assert "2026-06-02" not in page
    assert "UTC" not in page


def test_a_stamp_from_another_day_keeps_its_date() -> None:
    """The date goes only where the reader can supply it. Yesterday cannot be
    read off a page delivered today, so it is written."""
    page = _page(
        [_ping(3, _TEXTFILE, "2026-05-31T03:30:19+00:00", "example-collector.service")],
        lead=3, aspect="failure",
    )
    assert "31 May" in page
    assert LOCAL_ZONE_NAME.split("/")[-1] in page, "a dated stamp names the zone it is on"


def test_a_count_is_said_in_words_or_not_at_all() -> None:
    """"Ping 2 on this subject" is this system counting its own rows out loud.

    A reader wants to know whether it is new or a repeat, so the count is a
    word, and it is only said from the second time on.
    """
    repeat = _page(
        [_ping(3, _TEXTFILE, "2026-06-02T03:30:19+00:00", "example-collector.service")],
        lead=3, aspect="escalation", seen=2,
    )
    assert "Second time on this subject" in repeat
    assert "Ping 2" not in repeat

    first = _page(
        [_ping(3, _TEXTFILE, "2026-06-02T03:30:19+00:00", "example-collector.service")],
        lead=3, aspect="first_seen", seen=1,
    )
    assert "time on this subject" not in first


def test_the_unit_is_not_said_twice_when_the_subject_already_names_it() -> None:
    """The defect that made the page read as its own echo.

    A `unit_failed` sender puts the unit in its subject, so the page said
    "systemd unit failed: example-collector.service ... unit
    example-collector.service". The host is not in the subject and survives.
    """
    page = _page(
        [_ping(3, _TEXTFILE, "2026-06-02T03:30:19+00:00", "example-collector.service")],
        lead=3, aspect="failure",
    )
    assert page.count("example-collector.service") == 1
    assert "harness-internal" in page, "the host is not a repeat and stays"


def test_two_pings_arriving_together_are_one_sentence() -> None:
    """Riders sharing a moment said once, with both subjects named.

    Not "Also in this batch: ..." twice, each with its own copy of the same
    stamp. Neither subject may be lost to the fold: a page never drops
    a ping to save a repetition.
    """
    page = _page(
        [
            _ping(3, _TEXTFILE, "2026-06-02T03:30:19+00:00", "example-collector.service"),
            _ping(1, _GATE_AUDIT, "2026-06-02T02:40:26+00:00"),
            _ping(2, _GATE_UNIT, "2026-06-02T02:40:26+00:00", "example-audit.service"),
        ],
        lead=3, aspect="failure",
        also=((1, "also_firing"), (2, "also_firing")),
    )
    assert page.count("Also") == 1
    assert page.count("04:40") == 1
    assert "the unselected suite is red" in page
    assert "example-audit.service" in page


def test_riders_at_different_moments_are_not_folded_together() -> None:
    """The fold is about one moment. Two riders that arrived an hour apart are
    two facts, and merging them would put one of them at the wrong time."""
    page = _page(
        [
            _ping(3, _TEXTFILE, "2026-06-02T03:30:19+00:00", "example-collector.service"),
            _ping(1, _GATE_AUDIT, "2026-06-02T02:40:26+00:00"),
            _ping(2, _GATE_UNIT, "2026-06-02T01:10:00+00:00", "example-audit.service"),
        ],
        lead=3, aspect="failure",
        also=((1, "also_firing"), (2, "also_firing")),
    )
    assert "04:40" in page and "03:10" in page
# ── Filing a meeting on the board ────────────────────────────────
# The assistant writes to the board without asking now: the send button on the
# dashboard is the team's approval. So the guards worth having are the two
# that bound what a wrong reading can cost, and both are decidable by hand.

#: The action items table and decisions list of a meeting written to the
#: template, plus the empty row the template ships with.
_REAL_MINUTES = """\
# Meeting: Website relaunch, intake

## Discussed

### 1. Background
- Not a decision and not an action; this section must contribute nothing.

## Decisions

1. The relaunch goes live after the content review.
2. Robin checks the hosting quote with the supplier.
3. A fixed review window is planned for the copy.
4. Licences for the photos are bought under the standard agreement.

---

## Action items

| Action | Who | Deadline |
|---|---|---|
| Send the supplier the link to the brief | Jordan | End of day |
| Fill in the brief through the link Jordan sent | Supplier | Before the kick-off |
| Mail the supplier the kick-off details | Alex | End of day |
| | | |

## Next meeting

**Date**: to be planned
"""


def test_how_many_issues_a_meeting_opens_is_read_and_not_judged() -> None:
    """Three action points and four decisions, counted by eye off the table.

    This is the number that decides how much a meeting writes to the board,
    so it is deliberately not the model's to choose: `parse_minutes` reads
    the template the project controls and the model is handed the result. The
    known answer is the document above, which anybody can count.

    The empty row matters as much as the full ones. The template ships with
    one, every meeting with fewer action points than the writer expected
    leaves one, and an empty row that became an issue would be a card with no
    title assigned to somebody. The bullet under `## Discussed` matters for
    the mirror reason: a discussion point is not a decision, and a parser
    that swept the whole document would turn every meeting into a backlog.
    """
    from apps.assistant.core.notulen import parse_minutes

    minutes = parse_minutes(_REAL_MINUTES, title="Website relaunch", meeting_date="2026-08-25")

    assert [action.who for action in minutes.actions] == ["Jordan", "Supplier", "Alex"], (
        "the action items table has three rows with an action in them; the "
        "fourth is the template's empty row and is not an issue"
    )
    assert minutes.actions[0].deadline == "End of day"
    assert len(minutes.decisions) == 4, (
        f"four numbered decisions, got {len(minutes.decisions)}: "
        f"{minutes.decisions}"
    )
    assert not any("Not a decision" in decision for decision in minutes.decisions), (
        "a bullet under Discussed is discussion, not a decision; sweeping the "
        "whole document would put every meeting's talk on the board"
    )
    assert not minutes.is_empty


def test_a_meeting_can_only_land_on_something_that_is_open() -> None:
    """the assistant picks a parent from a list; it cannot type a number.

    It may open a new root when a meeting introduces a subject the board has
    no root for, which is the whole reason this is not gated behind a human.
    The cost of that freedom is bounded here: the tool's `parent` enum is 0
    (meaning "a new root") plus the open ROOTS, so a hallucinated number, a
    closed issue, or nesting under a child to make a fourth layer are not
    outcomes this path has. A decision may be commented onto any open issue,
    root or not, because a comment changes no structure.
    """
    from apps.assistant.core.notulen import Candidate, parse_minutes
    from apps.assistant.core.notulen.decide_placements import tool_definition

    minutes = parse_minutes(_REAL_MINUTES, title="Website relaunch", meeting_date="2026-08-25")
    board = [
        Candidate(53, "A deploy system nobody has to watch", "dev", True, False),
        Candidate(54, "notulen: edit the minutes", "dev", False, True),
        Candidate(151, "Dev-backlog", "dev", True, False),
    ]

    schema = tool_definition(minutes, board)["input_schema"]["properties"]
    parents = schema["actions"]["items"]["properties"]["parent"]["enum"]
    commentable = schema["comments"]["items"]["properties"]["issue"]["enum"]

    assert set(parents) == {0, 53, 151}, (
        f"parents offered were {parents}; #54 has a parent already, so "
        "nesting under it would make a fourth layer the board does not show"
    )
    assert set(commentable) == {53, 54, 151}
    # And it cannot open more cards than the meeting has action points.
    assert schema["actions"]["maxItems"] == 3
    assert schema["comments"]["maxItems"] == 4
    # Nor invent a department or an assignee.
    assert schema["actions"]["items"]["properties"]["assignee"]["enum"] == [
        "Alex", "Sam", "Robin", "Kim",
    ]


def test_assistant_cannot_open_a_root_without_saying_what_it_checked() -> None:
    """A new root PRD needs its root check, in the container as well as in Claude.

    The root-check rule exists because a session can read its own prompt as a
    new workstream and open a second root for a subject that already has one.
    `.claude/hooks/issue_guard.py` enforces the root
    check on the Claude path and cannot run in this pod, and
    the assistant opens roots off its own bat when a meeting introduces a subject.
    So the same refusal lives in the tool, and it fires before any `gh` call.

    A PRD nested under a parent is not a root, and a plain issue never was.
    """
    from apps.assistant.core.tools.gh import github_act

    labels = ["PRD", "area:dev"]
    assert github_act._missing_root_check(labels, None, "## Goal\nSomething."), (
        "a root PRD with no root check must be refused; the repository "
        "refuses it on the other side anyway"
    )
    assert not github_act._missing_root_check(
        labels, None, "## Root check\nChecked #53; it covers deploys.\n\n## Goal\nx"
    )
    assert not github_act._missing_root_check(labels, 1, "## Goal\nx"), (
        "a PRD with a parent is not a root"
    )
    assert not github_act._missing_root_check(
        ["enhancement", "area:dev"], 151, "just a task"
    )


def test_work_the_board_already_carries_is_not_opened_a_second_time() -> None:
    """A weekly meeting must not buy a new card for the same task every week.

    This is the failure mode that turns a board into a pile, and it is not
    hypothetical: a recurring meeting carries the same action point until it
    is done, and a meeting often agrees to something already tracked. There
    are two halves to stopping it, and only the second is checkable here.

    The model's half is a question it is asked first, with `already` to answer
    it in: an open issue that IS this action point. The Python half is that
    setting it writes a comment and opens nothing at all, so a wrong answer
    costs a comment on the wrong issue rather than a duplicate card with an
    owner. What is checked below is that second half plus the closure of the
    field, because a number the model made up would be a comment on somebody
    else's work.
    """
    from apps.assistant.core.notulen import Candidate, parse_minutes
    # Every deep-module file here is named after its one public callable
    # and the seam re-exports that callable, so the package attribute
    # `file_minutes` IS the function and a plain import gets the wrong
    # object. Reaching the module means asking importlib for it.
    filing = importlib.import_module(
        "apps.assistant.core.notulen.file_minutes"
    )
    from apps.assistant.core.notulen.decide_placements import (
        Placements,
        tool_definition,
    )

    minutes = parse_minutes(_REAL_MINUTES, title="Website relaunch", meeting_date="2026-08-25")
    board = [
        Candidate(53, "A deploy system nobody has to watch", "dev", True, False),
        Candidate(54, "notulen: edit the minutes", "dev", False, True),
    ]

    # Any open issue may be named as the one already carrying the work, root
    # or not, because work lives on children far more often than on roots.
    schema = tool_definition(minutes, board)["input_schema"]["properties"]
    already = schema["actions"]["items"]["properties"]["already"]
    assert already["enum"] == [None, 53, 54], (
        f"already offered {already['enum']}; it has to be closed over the open "
        "board, or a made-up number becomes a comment on somebody else's issue"
    )

    calls = []

    def _fake_execute(tool_input, actor="assistant"):
        calls.append(tool_input)
        return "done: https://github.com/owner/repo/issues/4242"

    plan = Placements(
        actions=[
            {"already": 54},
            {
                "title": "Send the assignment link", "body": "Jordan sends the supplier the link.",
                "parent": 53, "area": "dev", "assignee": "Alex",
            },
        ],
        comments=[],
        new_root=None,
    )
    filed = filing.Filed()
    real_execute = filing.github_act.execute
    filing.github_act.execute = _fake_execute
    try:
        filing._open_actions(plan, None, "https://example.invalid/minutes.md", filed)
    finally:
        filing.github_act.execute = real_execute

    assert [call["action"] for call in calls] == ["comment", "create"], (
        f"the two action points produced {[c['action'] for c in calls]}; the "
        "one the board already carries must be commented, never opened again"
    )
    assert calls[0]["issue_number"] == 54
    assert filed.updated == [54], "an updated issue is counted apart from a new one"
    assert filed.issues == [4242]
    assert not filed.problems

    # And the report says which is which, because "opened six issues" about a
    # meeting that opened one is how a board stops being believed.
    report = filed.as_report("Website relaunch")
    assert "#4242" in report and "#54" in report
    assert "already on the board" in report


def test_an_action_point_that_is_neither_new_nor_known_is_left_off() -> None:
    """Nothing is required in the tool schema, so Python is the one that checks.

    An entry is one of two shapes: `already` alone, or a whole new issue. A
    half-filled one is a model mistake, and the cheap failure is a line in the
    report saying an action point was left off. The expensive one would be a
    card with no title on it, assigned to nobody, under a parent nobody chose.
    """
    # Every deep-module file here is named after its one public callable
    # and the seam re-exports that callable, so the package attribute
    # `file_minutes` IS the function and a plain import gets the wrong
    # object. Reaching the module means asking importlib for it.
    filing = importlib.import_module(
        "apps.assistant.core.notulen.file_minutes"
    )
    from apps.assistant.core.notulen.decide_placements import Placements

    calls = []
    real_execute = filing.github_act.execute
    filing.github_act.execute = lambda tool_input, actor="assistant": calls.append(tool_input)
    try:
        filed = filing.Filed()
        filing._open_actions(
            Placements(actions=[{"body": "half an answer"}], comments=[], new_root=None),
            None, "https://example.invalid/minutes.md", filed,
        )
    finally:
        filing.github_act.execute = real_execute

    assert calls == [], "a half-filled action point must reach GitHub as nothing"
    assert filed.issues == [] and filed.updated == []
    assert len(filed.problems) == 1 and "still" in filed.problems[0], (
        "the report has to say an action point was left off, and that the "
        "minutes still carry it"
    )


# ---------------------------------------------------------------------------
# The same question, twice.
#
# A teammate asks the assistant to arrange a call with the owner at 09:00. The
# assistant relays it, the owner answers with 10:00, the assistant books 10:00
# and tells the teammate. Putting the ORIGINAL 09:00 question to the owner
# again after that is the failure.
#
# The two messages below are a relay and its repeat, minutes apart. Both are
# good messages; the second is only wrong because the first exists. A check
# that reads one draft on its own cannot see the pair.
# ---------------------------------------------------------------------------

RELAY_FIRST = (
    "Sam asks whether you\'re up for a call tomorrow (Wednesday 2 Sep) at "
    "09:00. He\'s free then. If that works, I\'ll book it. This message is on "
    "Sam\'s request."
)
RELAY_AGAIN = (
    "Sam is asking whether you two can have a call tomorrow (Wednesday 2 Sep) "
    "at 09:00. This message is on Sam\'s request. Does that work for you?"
)
# A second message the same afternoon that is not the same message: a different
# time, and a different question.
RELAY_SOMETHING_NEW = (
    "Sam asks whether the Friday call can move to 14:00. This message is on "
    "Sam\'s request."
)


def _sent(text: str, at: str = "2026-06-02T14:49:47+00:00") -> dict:
    """One thing the assistant said to somebody, in the shape the chat store returns."""
    return {"role": "assistant", "text": text, "created_at": at}


def test_the_question_alex_had_already_answered_is_not_asked_again() -> None:
    """A relay and its repeat, in the order they would be sent."""
    refusal = claims.repeated_message(RELAY_AGAIN, [_sent(RELAY_FIRST)], "Alex")

    assert refusal is not None, "the second 09:00 relay has to be caught"
    assert "16:49" in refusal, (
        "the refusal has to say when the first one went out, in local time, "
        "or the model cannot tell the requester what already happened"
    )


def test_a_second_message_that_carries_something_new_still_goes() -> None:
    """The guard is about sameness, not about how many messages a subject may
    have. A different time and a different question is a different message, and
    refusing it would make this the guard somebody switches off."""
    assert claims.repeated_message(
        RELAY_SOMETHING_NEW, [_sent(RELAY_FIRST)], "Alex"
    ) is None


def test_a_message_too_short_to_judge_is_never_called_a_repeat() -> None:
    """Below three distinctive terms one shared word carries the whole
    fraction, so the guard says nothing rather than something arbitrary."""
    assert claims.repeated_message("Booked, 10:00.", [_sent(RELAY_FIRST)], "Alex") is None


def test_the_second_relay_never_reaches_the_phone(tmp_path, monkeypatch) -> None:
    """The wiring, not the predicate.

    The lesson of the attribution guard next to it is that a rule written in a
    docstring and checked nowhere is a rule the seam does not have. So this
    drives the real tool twice, with only the Signal send replaced, and counts
    what left the building.
    """
    from apps.assistant.core.tools.team import message_teammate

    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_TEAM_MESSAGE", "1")
    monkeypatch.setenv("SIGNAL_PEOPLE", PEOPLE)
    landed: list[str] = []
    monkeypatch.setattr(
        message_teammate._signal,
        "send",
        lambda subject, body, recipient=None: landed.append(body) or True,
    )

    first = message_teammate.execute(
        {"person": "Alex", "message": RELAY_FIRST}, actor="Sam"
    )
    again = message_teammate.execute(
        {"person": "Alex", "message": RELAY_AGAIN}, actor="Sam"
    )

    assert first == "messaged Alex."
    assert again.startswith("not sent:"), again
    assert landed == [RELAY_FIRST], "Alex\'s phone may only carry the one question"


def test_a_new_question_after_a_refusal_still_goes_out(tmp_path, monkeypatch) -> None:
    """The other half: one refusal must not close the thread for the evening."""
    from apps.assistant.core.tools.team import message_teammate

    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_TEAM_MESSAGE", "1")
    monkeypatch.setenv("SIGNAL_PEOPLE", PEOPLE)
    landed: list[str] = []
    monkeypatch.setattr(
        message_teammate._signal,
        "send",
        lambda subject, body, recipient=None: landed.append(body) or True,
    )

    message_teammate.execute({"person": "Alex", "message": RELAY_FIRST}, actor="Sam")
    message_teammate.execute({"person": "Alex", "message": RELAY_AGAIN}, actor="Sam")
    third = message_teammate.execute(
        {"person": "Alex", "message": RELAY_SOMETHING_NEW}, actor="Sam"
    )

    assert third == "messaged Alex."
    assert landed == [RELAY_FIRST, RELAY_SOMETHING_NEW]


def test_every_webhook_can_actually_reach_the_work_it_names() -> None:
    """A gate that imported the wrong object fails at the button, not at boot.

    A send-to-the-assistant button can answer 502 on its first real press:
    `from ...core.notulen import file_minutes as openclaw_notulen` followed
    by `openclaw_notulen.file_minutes(...)` fails. Every deep-module file in that package is named after its one public
    callable and the seam re-exports the callable, so that import hands back
    the function and asking it for `.file_minutes` is an AttributeError. It
    imports clean, it starts clean, and it raises the first time somebody
    uses it.

    The shape is general, so the check is: whatever a route calls as
    `<name>.<attr>(` has to be an attribute that exists and can be called.
    Import-time is the right place to find that, which is what this does.
    """
    import inspect
    import re

    from apps.assistant.gates import app

    source = inspect.getsource(app)
    # `filed = openclaw_notulen.file_minutes(` and its kind, inside the
    # route bodies rather than in the imports.
    called = set(
        re.findall(r"\b(openclaw_[a-z_]+)\.([a-z_]+)\(", source)
    )
    assert called, "no `openclaw_*.something(` call sites found; the check went blind"

    missing = []
    for name, attr in sorted(called):
        target = getattr(app, name, None)
        if target is None:
            missing.append(f"{name} is not imported at all")
        elif not callable(getattr(target, attr, None)):
            missing.append(
                f"{name}.{attr} is not callable ({type(target).__name__} "
                f"{getattr(target, '__name__', '')})"
            )
    assert not missing, (
        "a route names something it cannot call, so the request that reaches "
        "it fails and nothing before then does: " + "; ".join(missing)
    )


def test_the_board_is_read_in_pages_github_will_actually_serve() -> None:
    """A read that asks for too much files nothing.

    GitHub's GraphQL connections refuse anything over 100 per page, with an
    error rather than a short answer. The caller then does the right thing
    with the wrong input: no board to read means no parent can be chosen, so
    it refuses to guess and files nothing, and a whole meeting reaches the
    board as one apologetic sentence on Signal.

    So the page size has to be one GitHub serves, and the ceiling has to be
    reached by paging rather than by asking for it all at once. Both are read
    off the module, and the second is what stops somebody "fixing" this by
    raising the page size back up.
    """
    reader = importlib.import_module(
        "apps.assistant.core.notulen.candidate_issues"
    )

    assert reader._PAGE <= 100, (
        f"a page of {reader._PAGE} is refused outright by GitHub; the whole "
        "board then reads as unreadable and the meeting is filed nowhere"
    )
    assert reader._LIMIT > reader._PAGE, (
        "the ceiling is meant to be reached by following pages; a limit "
        "inside one page means the paging is decoration"
    )
    assert "after:$after" in reader._QUERY and "hasNextPage" in reader._QUERY, (
        "the query has to carry a cursor and be asked whether more remain, "
        "or the board silently stops at the first page"
    )


def test_only_a_root_is_offered_as_a_parent() -> None:
    """Read off real rows, because the shapes are what the board really has.

    A root is a PRD with no parent. Anything else is a child, and nesting
    under a child would make a fourth layer the board does not show. The
    filtering lives in the reader, so a candidate list that got it wrong would
    hand `decide_placements` a parent enum with children in it and the model
    would pick one sooner or later.
    """
    from apps.assistant.core.notulen.candidate_issues import Candidate

    rows = [
        {"number": 1, "title": "A root", "parent": None,
         "labels": {"nodes": [{"name": "PRD"}, {"name": "area:dev"}]}},
        {"number": 2, "title": "A child of it", "parent": {"number": 1},
         "labels": {"nodes": [{"name": "enhancement"}, {"name": "area:dev"}]}},
        {"number": 3, "title": "A PRD that got nested", "parent": {"number": 1},
         "labels": {"nodes": [{"name": "PRD"}]}},
    ]
    reader = importlib.import_module(
        "apps.assistant.core.notulen.candidate_issues"
    )

    built = [
        Candidate(
            number=int(row["number"]),
            title=row["title"],
            area=next(
                (label["name"].split(":", 1)[1] for label in row["labels"]["nodes"]
                 if label["name"].startswith("area:")), ""),
            is_root=("PRD" in [label["name"] for label in row["labels"]["nodes"]]
                     and not row.get("parent")),
            has_parent=bool(row.get("parent")),
        )
        for row in rows
    ]
    assert [c.number for c in built if c.is_root] == [1], (
        "only the PRD with no parent is a root; a PRD that drifted under a "
        "parent is not one, whatever its label says"
    )
    assert reader._PRD_LABEL == "PRD"


def test_a_choice_outside_what_was_offered_is_dropped_not_written() -> None:
    """The enums make a good answer likely; this makes a bad one harmless.

    A tool-schema enum is guidance to the model, not a rule the API enforces:
    a model can answer `parent: 52` for two action points when that issue is
    not a root, it carries `enhancement` and sits under another issue, so both
    cards would land as a fourth layer the board does not show. Enums without
    checking is the mistake
    `page_render` names out loud: the enums can only remove refusals, and the
    Python parse is the only enforcer.

    Every dropped item is named rather than quietly lost, because it is still
    in the minutes and the person who pressed the button has to be told.
    """
    from apps.assistant.core.notulen import Candidate
    from apps.assistant.core.notulen.decide_placements import (
        NEW_ROOT,
        _only_what_was_offered,
    )

    board = [
        Candidate(1, "Operations: suppliers and contracts", "finance", True, False),
        Candidate(52, "Supplier contracts", "finance", False, True),
    ]
    chosen = {
        "actions": [
            {"title": "Under a child", "body": "b", "parent": 52,
             "area": "finance", "assignee": "Alex"},
            {"title": "Under a root", "body": "b", "parent": 1,
             "area": "finance", "assignee": "Alex"},
            {"title": "A made-up parent", "body": "b", "parent": 999999,
             "area": "finance", "assignee": "Alex"},
            {"title": "A department that is not one", "body": "b", "parent": 1,
             "area": "marketing", "assignee": "Alex"},
            {"title": "Somebody who does not work here", "body": "b", "parent": 1,
             "area": "finance", "assignee": "Jordan"},
            {"already": 52},
            {"already": 999999},
            {"title": "A new root", "body": "b", "parent": NEW_ROOT,
             "area": "finance", "assignee": "Alex"},
        ],
        "comments": [{"issue": 52, "body": "x"}, {"issue": 999999, "body": "x"}],
        "new_root": {"title": "t", "goal": "g", "root_check": "c",
                     "area": "nonsense", "assignee": "Alex"},
    }

    kept = _only_what_was_offered(chosen, board)

    assert [action.get("title") for action in kept.actions] == [
        "Under a root", None, "A new root",
    ], (
        "only a root, an `already` that is open, and the new-root marker may "
        f"survive; got {[a.get('title') or a.get('already') for a in kept.actions]}"
    )
    assert kept.actions[1]["already"] == 52
    assert [comment["issue"] for comment in kept.comments] == [52]
    assert kept.new_root is None, "a root naming a department that does not exist"
    # Five refusals: the child parent, the made-up parent, the department, the
    # person, the closed `already`, the comment, and the root. Named, not lost.
    assert len(kept.refused) == 7, kept.refused
    assert any("#52" in line and "not one of the open roots" in line
               for line in kept.refused), kept.refused


def test_with_board_writes_off_a_meeting_files_nothing_and_says_so() -> None:
    """The kill switch has to reach the report, not just the write.

    `ASSISTANT_GITHUB_WRITE=0` makes `github_act` refuse every call, and refusals
    come back as text rather than exceptions. So the filing code has to read
    them: a run that opened nothing because writes are off must say that, or
    the person who pressed the button reads "put nothing on the board" and
    goes looking for a meeting with no action points in it.
    """
    filing = importlib.import_module(
        "apps.assistant.core.notulen.file_minutes"
    )
    from apps.assistant.core.notulen.decide_placements import Placements

    refusal = "refused: ASSISTANT_GITHUB_WRITE is off, so I can't change the board"
    real_execute = filing.github_act.execute
    filing.github_act.execute = lambda tool_input, actor="assistant": refusal
    try:
        filed = filing.Filed()
        plan = Placements(
            actions=[{"title": "A task", "body": "b", "parent": 53,
                      "area": "dev", "assignee": "Alex"}],
            comments=[{"issue": 53, "body": "a decision"}],
            new_root=None,
        )
        filing._open_actions(plan, None, "https://example.invalid/m.md", filed)
        filing._leave_comments(plan, "https://example.invalid/m.md", filed)
    finally:
        filing.github_act.execute = real_execute

    assert filed.issues == [] and filed.comments == [] and filed.updated == []
    assert len(filed.problems) == 2, filed.problems
    assert all("ASSISTANT_GITHUB_WRITE" in line for line in filed.problems), (
        "the report has to carry the reason it wrote nothing, or a switched-off "
        f"{ASSISTANT_NAME} reads exactly like a meeting with nothing in it: {filed.problems}"
    )

    # And the report itself says both halves out loud.
    report = filed.as_report("A meeting")
    assert "put nothing on the board" in report and "ASSISTANT_GITHUB_WRITE" in report


# ---------------------------------------------------------------------------
# A page a sender says cannot wait.
#
# The pen has four ways to send nothing: a filed board card, a human
# suppression, the quiet-hours hold, and the model judging the batch silent.
# All four are right for this road's usual traffic and all four were wrong for
# one sender. A page saying a commit was reverted off main is somebody's work
# handed back, and such pages can go unseen: fired late in the evening straight
# into the hold, or several in one day under a single repeated subject.
#
# `must_page` is the narrow way through. These cases pin both sides of it:
# what it lets past, and what it still does not.
# ---------------------------------------------------------------------------

_EJECT_SUBJECT = "\U0001f534 [the project] auto-deploy: a commit was reverted on main"


def _a_pen(monkeypatch, tmp_path):
    """A fresh pen, the quiet-hours default in force, and the phone as a list.

    Only the outermost seam is replaced, same as the morning-gate fixture
    above: the Signal send, and the model's verdict. Every gate between them
    runs for real, because the gates are what is under test.
    """
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.delenv("ASSISTANT_QUIET_HOURS", raising=False)
    from apps.assistant.core import notify_flush

    landed: list[str] = []
    monkeypatch.setattr(
        notify_flush.signal_dispatch,
        "send",
        lambda subject, body: landed.append(body) or True,
    )
    return notify_flush, landed


def _composes_to(monkeypatch, notify_flush, message: str | None) -> None:
    """Replace the model's verdict, and nothing else around it."""
    monkeypatch.setattr(
        notify_flush,
        "_compose",
        lambda pings, now: notify_flush._Decision(message=message, floor="the floor text"),
    )


def test_a_page_marked_as_one_that_cannot_wait_leaves_at_two_in_the_morning(
    monkeypatch, tmp_path
) -> None:
    """Quiet hours, and it goes out anyway.

    A commit being reverted off main is the one thing on this road where the
    reader loses something by hearing it at 07:30: their work is off main NOW
    and they are usually still at the keyboard.
    """
    from apps.assistant.core import state

    notify_flush, landed = _a_pen(monkeypatch, tmp_path)
    _composes_to(monkeypatch, notify_flush, "a commit was reverted on main")
    state.enqueue_ping(
        _EJECT_SUBJECT, "the gate rejected it", "auto-deploy",
        {"must_page": "yes", "blocks_deploy": "no"},
    )

    assert notify_flush.flush_pen(_at(2, 0)) == "a commit was reverted on main"
    assert landed == ["a commit was reverted on main"]


def test_the_same_night_without_the_mark_is_still_held(monkeypatch, tmp_path) -> None:
    """The hold is not weakened, it is stepped around by one marking.

    Without this case the one above would pass just as well if the hold had
    been deleted, and deleting it is the change nobody wants: without it one
    night can wake a person several times for things that heal by morning.
    """
    from apps.assistant.core import state

    notify_flush, landed = _a_pen(monkeypatch, tmp_path)
    _composes_to(monkeypatch, notify_flush, "the gate is red")
    state.enqueue_ping(
        "[the project] auto-deploy: gate red", "a test failed", "auto-deploy",
        {"blocks_deploy": "yes"},
    )

    assert notify_flush.flush_pen(_at(2, 0)) is None
    assert landed == []


def test_the_second_revert_of_the_day_is_not_silenced_as_a_repeat(
    monkeypatch, tmp_path
) -> None:
    """The model judged the batch silent, and this one still goes out.

    Deliberately the SECOND page under this subject inside the window, which is
    what makes it a test of the new clause rather than of the critical floor
    beside it: that floor rescues the first word about a critical subject and
    then, correctly, stops, because a repeat is usually not news. Several
    reverts can land under this one subject. They are not a repeat; each is
    a different person's commit taken off main.
    """
    from apps.assistant.core import state

    notify_flush, landed = _a_pen(monkeypatch, tmp_path)
    _composes_to(monkeypatch, notify_flush, None)
    # Already said once inside the window, so the critical floor stands down.
    monkeypatch.setattr(state, "pen_subject_delivered", lambda subject, since: True)
    state.enqueue_ping(
        _EJECT_SUBJECT, "the gate rejected it", "auto-deploy", {"must_page": "yes"},
    )

    assert notify_flush.flush_pen(_at(14, 0)) == "the floor text"
    assert landed == ["the floor text"]


def test_a_person_silencing_the_alert_still_wins(monkeypatch, tmp_path) -> None:
    """A sender does not get to argue with a human suppression.

    A filed card is housekeeping. This is somebody deciding they do not
    want to hear it, and a marking in a shell script does not overrule that.
    """
    from apps.assistant.core import state

    notify_flush, _landed = _a_pen(monkeypatch, tmp_path)
    monkeypatch.setattr(state, "filed_issue_for", lambda _subject: None)
    monkeypatch.setattr(state, "is_suppressed", lambda _subject: (True, "Alex muted it"))

    live, silenced = notify_flush._split_silenced(
        [{"id": 1, "subject": _EJECT_SUBJECT, "facts": {"must_page": "yes"}}]
    )
    assert not live and len(silenced) == 1


def test_only_the_senders_own_field_sets_the_flag() -> None:
    """A body that talks about paging does not set it.

    The flag changes what the road DOES, so it is read off the sender's marking
    and nowhere else. Anything that is not a clear yes reads as no, which is
    the direction that loses a page rather than waking somebody over a typo.
    """
    from apps.assistant.core import ping_facts

    assert ping_facts.must_page({"must_page": "yes"}) is True
    assert ping_facts.must_page({"must_page": True}) is True
    assert ping_facts.must_page({"must_page": "no"}) is False
    assert ping_facts.must_page({}) is False
    assert ping_facts.must_page(None) is False
    assert ping_facts.must_page("must_page: yes, this cannot wait") is False


def test_the_flag_never_reaches_the_model() -> None:
    """the assistant still writes the page; it just no longer decides whether to.

    Every other marked field describes the thing that happened and belongs in
    front of the model. This one is routing, and a model reading "the sender
    says this cannot wait" would be reading an instruction, not a fact.
    """
    from apps.assistant.core import ping_facts

    marking = {"must_page": "yes", "qualifier": "not an outage"}
    parsed = ping_facts.marked(ping_facts.parse(_EJECT_SUBJECT, "a body"), marking)
    assert parsed.must_page is True

    fact = ping_facts.PingFact(
        ping_id=1,
        kind="deploy",
        subject=_EJECT_SUBJECT,
        display_subject="auto-deploy: a commit was reverted on main",
        source="auto-deploy",
        severity="critical",
        observed_at="2026-09-04T20:00:00+00:00",
        parsed=parsed,
        body_complete=True,
        history=ping_facts.UNKNOWN_HISTORY,
    )
    block = ping_facts._fact_block(fact)
    assert "not an outage" in block
    assert "must_page" not in block and "cannot wait" not in block
