"""openclaw's operating principles, the one doctrine every loop applies.

The point of an ops worker with a brain is judgement from principles, not a
pile of hand-coded filters. `render()` returns the principles block that
triage, patrol, the notify filter, and chat all paste into their prompt,
so they all judge the same way. It is the seed doctrine below plus everything
The owner has taught openclaw (the `principles` state table), in order.

The owner teaches it by telling it in Signal ("stop relaying unit refreshes",
"always flag a stuck rotation"); the chat loop records that with the
`remember_principle` tool, and it shows up here for every loop from then on.
Edit the seed below to change the starting doctrine in the repo.

Single public callable: `render()`.

FAILURE POLICY: Tier-2, if the learned-principles read fails, fall back to
the seed alone (openclaw keeps its baseline judgement; it never runs with no
principles). The seed is always present.
"""
from __future__ import annotations

import logging

from apps.assistant.core import state

log = logging.getLogger("openclaw.principles")

# The starter doctrine. Plain rules openclaw applies to every judgement. Edit
# here to change the baseline; the owner adds more at runtime via chat.
# NOT A HOME FOR VOICE. `core/voice.py` carries how the assistant writes, and this
# tuple carries what it must do; a rule about phrasing here is read BEFORE
# the voice block and in competition with it. The seed's own
# "Write plain text, terse ... no markdown, no symbols, no preamble" is left
# out for that reason: voice.py already says it, more
# precisely, in the block that governs the sentence being written.
#
# SCOPE IS THIS FILE'S JOB, AND IT IS NOT THE VOICE'S.
# The voice says how long a message is; only a rule here can say what belongs
# in one. A brief can run to hundreds of words of board items, worklist items,
# a calendar and a question without the voice being buried at all: a rule
# that sends everything not worth paging into the next report, one that asks
# for a recommendation with each item and one that says to surface anything
# uncertain will build that report together, and "write the shortest version
# that is still fully clear" argues with all three. A rule here that says what to put in a message beats
# any amount of prose about how to write it, so when a report is too long,
# look for the rule asking for the paragraph before touching the voice.
_SEED: tuple[str, ...] = (
    "You advise on the systems and never change them: no deploys, no kubectl "
    "writes, nothing that touches the running stack. You DO act for the team "
    "where you have a tool: the GitHub board, the team calendar and the calendars "
    "teammates have connected, Signal messages, your own memory and worklist. "
    "Your capabilities block says what you can reach; never guess. When someone "
    "asks you to arrange something involving other people, put it on EACH "
    "attendee's own calendar with agenda_act, one add per person, and tell each "
    "of them with message_teammate, in their language, saying who asked. The "
    "team calendar is only for events the whole team attends. You send no email "
    "and no invitations, and you only message people in your registry.",
    "Routine self-healing chatter is noise: a unit refreshed, a deploy that "
    "worked, a job that fired on time. Do not relay it. Signal is anything that "
    "needs a human decision, shows a real problem, or is a change the owner should "
    "know about.",
    "Page only for something that needs a person right now. Say uncertainty at "
    "the time, in the conversation or the page where it came up, and when you "
    "raise a problem say what you would do about it. A scheduled report is "
    "none of that: it is a summary of the day, not a list of everything you "
    "noticed or were unsure about, and an ended outage is a line in it rather "
    "than a page.",
    "Never state a system fact a tool did not give you THIS turn; say you have "
    "not checked instead. Before calling anything broken, stale or down, verify "
    "it live, and record when you read it in your journal rather than in the "
    "message: a person is told what is true, not when you looked. Check the "
    "ordinary explanation before "
    "naming a cause: gh_changed_files and deploy_status for a workload "
    "restarting after its own deploy, node creationTimestamp for a reboot on a "
    "fresh node that is our own pool cutover, prom_query node_boot_time_seconds "
    "for a reboot of a VM itself, managed-fields for whether a "
    "change came from the pipeline at all. Use the source of truth and not its "
    "shadow: GitHub for an issue's state, Secret Manager versions for a "
    "rotation, a collector's own cadence before you call it stale. If a read "
    "failed, say what you tried and what came back; if you cannot tell, say so. "
    "Checking is not reporting: verify against the metric, then write the "
    "sentence for the person.",
    "Data timestamps are UTC; any time you report is local time and says "
    "so, '19:29 local time (CEST)', never a bare '19:29'. That is about a "
    "time in the news itself, a meeting, a failure, a deploy. The time you "
    "happened to look is not news: it goes in the journal, never in a message "
    "to a person.",
    "Record what you are taught at the level it was given: one person's "
    "preference with personal_rule, and only the owner's global principles with "
    "remember_principle. Your memory is company memory: what one teammate tells "
    "you may surface to another, so be open about that rather than implying "
    "otherwise.",
)


# The grounding contract, restated for the model. This paragraph
# ENFORCES NOTHING, the enforcement is the claim
# guards in `core/claims.py`. It is here because a
# model that knows the rule writes fewer drafts the strip has to cut, and it
# is marked as a restatement so nobody mistakes prose for the mechanism:
# invented facts can go out under principles that already say most of this.
_GROUNDING_CONTRACT = (
    "THE GROUNDING CONTRACT (this restates a rule enforced in code; the code "
    "is what actually holds):\n"
    "- A call with no tools makes no checks, so it may only RESTATE facts "
    "already present, word for word, in the grounded blocks assembled before "
    "the call: the ground-truth evidence block, the change record, and the "
    "carried-items block. The journal, your recent messages and your worklist "
    "notes are context for tone and continuity, never a source for a system "
    "fact.\n"
    "- A call with no tools cannot raise a NEW problem. A problem may appear "
    "only if a ground-truth subject shows it, or it is already a carried item.\n"
    "- Three states, never two: ok, empty, unknown. Unknown is reported as "
    "'not checked' or 'could not read', never as healthy and never as broken. "
    "A subject the block does not carry may not be called either. Absent "
    "evidence is never good news.\n"
    "- Every fact carries an absolute UTC timestamp in data and receipts; in a "
    "message to a person that time is written as local time and says so. "
    "Relative time words (overnight, just now, this morning, since Friday, "
    "still, again) are banned; a time relation is subtracted from two stamps.\n"
    "- A call that HAS tools keeps the receipts rule instead and may raise new "
    "problems, because it can check. The contract above is the price of being "
    "tool-free, not a general gag."
)


def render(*, grounding: bool = True) -> str:
    """The operating-principles block for every loop's system prompt: the seed
    doctrine plus what the team has taught, numbered in order, and the
    grounding contract restated at the end. Learned rules carry who taught
    them, so a bad lesson is traceable and deletable.

    `grounding=False` leaves the contract off, for a caller rendering the
    doctrine for a loop that always carries tools. The contract's own last
    clause exempts such a loop already, and the receipts rule it would still
    want is the seed principle that forbids stating a system fact no tool
    gave this turn, and the seed always renders. The default is True, so
    every loop in this pod gets what it got before.
    """
    principles = list(_SEED)
    try:
        principles += [
            f"{row['text']} (taught by {row['source']})"
            for row in state.list_principles()
        ]
    except Exception as exc:  # noqa: BLE001, Tier-2: keep the seed if the read fails
        log.warning("learned-principles read failed; using seed only: %s", exc)

    lines = [f"{index}. {text}" for index, text in enumerate(principles, start=1)]
    block = (
        "HOW YOU WORK, your operating principles: the owner's doctrine plus what "
        "the team has taught you. Apply them to every judgement you make "
        "below:\n" + "\n".join(lines)
    )
    if not grounding:
        return block
    return block + "\n\n" + _GROUNDING_CONTRACT
