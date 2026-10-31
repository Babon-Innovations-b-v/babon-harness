"""The sweep, pure, testable pass over the registry.

`run_sweep()` iterates `registry.REGISTRY`, runs each component's check,
persists the outcome via `state.component_status.record_check`, and
RETURNS the list of `Transition`s (component, group, old_status,
new_status, detail) this pass produced. A component that went down then
becomes a ping in the notify pen, one per component, and the pen is what
reaches the phone.

THIS MODULE HAS NO SEND PATH OF ITS OWN, AND THAT IS THE POINT. Calling
`notify.send_signal` directly, which inside the container is signal-cli
direct, would be a second private line to the same phone with none of the
pen's brakes on it. No rate limit, no dedup key, no cooldown, no quiet hours,
no story gap, and nothing that could tell a person "this is the fourth time".
Everything goes in the pen
(`state.enqueue_ping`), and `core/notify_flush.py` owns muting, dedup,
the story gap, the unheard-critical floor and the shape of the page.
Keep it that way: no module in this package sends on its own.

Two things the sweep gave up in that move, both deliberate:

  The digest's PROSE. A page is selected, not composed (the house rules
  11), so no model-authored text reaches Signal on any road. The digest
  still runs, as a JUDGE and nothing else: it is the only thing in this
  system that can tell a pod restarting because a deploy just landed from
  one that broke, because it has `gh_commits` and `gh_changed_files` and
  the pen's own model gets typed fields and no tools at all. It says page
  or it says silent; what it wrote is logged, not shipped.

  RECOVERIES. There is no recovery ping in this system and no `recovered`
  relation in the page vocabulary, so a down->up flip would have to be
  rendered by templates written for failures. It is not queued at all.
  "Did it come back" is answered by the `stack_status` chat tool, which
  reads the same `component_status` rows on demand.

Flap suppression: a poll component flips to `down` only once
`consecutive_fails >= DOWN_THRESHOLD`; below that it stays at its prior
status (so a single missed check never pages). Recovery is first `up`
after `down`. `unknown` is its own resting state, it neither counts
toward the down threshold nor pages (a check that can't run
authoritatively must not fake a page).

A check that RAISES is caught here and classified `down` (active kinds)
or left to the check's own degrade, the sweep itself never crashes on a
bad component.

FAILURE POLICY: two tiers. The `state.component_status` writes are
Tier-1 (a failed status write propagates, the monitor must not lie).
The reporting is Tier-2: a digest fault or a pen write that fails is
logged and swallowed, because a brain or a pen outage must never stop the
sweep or block the next component. Degrade, never drop: a digest that
RAISES means nothing judged the batch, which is not a reason to lose it,
so those pings go to the pen unjudged and the pen decides. A ping the pen
would not take is written as a dead letter (`outbound.record_delivery`),
which is what `monitor/dead_letters.py` watches.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from apps.assistant.core import outbound, state
from apps.assistant.core.monitor import checks, digest, registry
from apps.assistant.core.monitor.component import (
    DOWN,
    KIND_HEARTBEAT,
    UNKNOWN,
    UP,
    CheckResult,
    Component,
)
from apps.assistant.core.monitor.limits import (
    DOWN_THRESHOLD,
    STILL_DOWN_REPAGE_EVERY,
)
from apps.assistant.core.state.component_status import (
    STATUS_DOWN,
    STATUS_PENDING,
    STATUS_UNKNOWN,
    STATUS_UP,
)

log = logging.getLogger("openclaw.monitor.sweep")

# What the pen rows this module writes are stamped with. `source` is the
# sender's name in the audit and in the flusher's log lines; the marker in
# front of the subject is the only per-ping severity anything records
# (`state.severity_of_subject`).
#
# `error`, not `critical`, and the difference is a real one. Critical arms the
# pen's unheard floor, which sends a page a batch was judged not to need, and
# it takes the subject out of reach of the recurring filer. What this module
# knows is that it could not reach something three times running. That is worth
# a person's attention and it is not the same claim as the deploy gate's, which
# knows its own verdict.
PING_SOURCE = "stack-monitor"
_SEVERITY_MARKER = "❌"

# What a digest silence is filed under.
#
# The fingerprint says which component was silenced and says, by its prefix,
# that this is not an Alertmanager arrival: a replay of the recordings reads
# the `monitor:` family as a silence belonging to no road, so these rows do not
# re-enter a replay as phantom pages.
#
# The decision is what keeps the row out of the readers. `state.unheard_silences`
# counts `decision='silent'` and this is not that word; `dead_letters_after`
# wants `dead_letter=1`; `last_pen_page_at`, `pen_subject_delivered` and the
# recurring filer all want a name beginning `pen flush (`. And the two readers
# that paste audit rows into a model's prompt exclude it by this exact value,
# which is why it is TAKEN from the declared vocabulary rather than spelled
# again here: `state.SILENCE_DECISIONS` holds it, in the file named after the
# table, and this module now writes the word that file excludes rather than a
# copy of it that can drift out from under the exclusion.
SILENCE_FINGERPRINT_PREFIX = "monitor:"
SILENCE_DECISION = state.SILENCE_DIGEST


@dataclass(frozen=True)
class Transition:
    component: str
    group: str
    old_status: str
    new_status: str
    detail: str


def run_sweep() -> list[Transition]:
    """Run one full pass: check every component, persist, report what went
    down to the notify pen, return the transitions."""
    _forget_components_nobody_sweeps()
    transitions: list[Transition] = []
    for component in registry.REGISTRY:
        transition = _sweep_one(component)
        if transition is not None:
            transitions.append(transition)
    _report(transitions)
    return transitions


def _forget_components_nobody_sweeps() -> None:
    """Drop status rows for components that are no longer in the registry.

    A removed component would otherwise keep its last row for good.
    `state.component_status.get_all` has no WHERE clause and the
    `stack_status` chat tool renders every row it gets, so components cut from
    the registry would go on answering "is everything alive" with readings
    frozen on the morning they stopped being checked, UP or NOT UP.

    The staleness line `stack_status` prints cannot catch this: it takes the
    newest stamp across the whole table, and the components still being swept
    keep that fresh however old the orphans are.

    Runs at the top of the sweep because the sweep is the one thing that knows
    what the stack is this minute. Tier-2: a prune that fails is logged and the
    sweep goes on, because a stale row is worse than nothing but it is not
    worth losing a pass over.
    """
    try:
        dropped = state.component_status.forget_all_but(
            [component.name for component in registry.REGISTRY]
        )
    except Exception as exc:  # noqa: BLE001, Tier-2: a prune is not the sweep
        log.warning("could not prune unswept components (swallowed): %s", exc)
        return
    if dropped:
        log.info("forgot %d component rows nobody sweeps any more", dropped)


def _sweep_one(component: Component) -> Transition | None:
    """Check one component, compute its new status with flap suppression,
    persist, and return the transition (or None if status is unchanged).

    A raising check is caught and classified `down` so one bad component
    can never crash the sweep (Tier-2 for the check; the status write
    itself stays Tier-1 loud)."""
    prior = state.component_status.get_one(component.name)
    old_status = (prior or {}).get("status", STATUS_PENDING)
    prior_fails = int((prior or {}).get("consecutive_fails", 0))

    result = _run_check(component, prior)
    new_status, new_fails, ok = _classify(result, old_status, prior_fails)

    state.component_status.record_check(
        component=component.name,
        status=new_status,
        ok=ok,
        detail=result.detail,
        consecutive_fails=new_fails,
        # A push-only component's liveness is its SENDER's timestamp. Stamping
        # it here would make the heartbeat check read its own previous answer,
        # so a push-only watch could never go down.
        stamp_last_ok=component.kind != KIND_HEARTBEAT,
    )

    if new_status == old_status:
        # A component that stays down produces no transition, and the
        # digest only ever sees transitions. So one flip earned one look,
        # and whatever that look decided stood for as long as the thing
        # stayed broken. Raise it again on a fixed count of failed checks
        # so a stuck component gets re-judged instead of being silent by
        # default. The detail says how long, because that is exactly the
        # fact that turns "a deploy just landed" into "a deploy is stuck".
        if (
            new_status == STATUS_DOWN
            and new_fails
            and new_fails % STILL_DOWN_REPAGE_EVERY == 0
        ):
            return Transition(
                component=component.name,
                group=component.group,
                old_status=STATUS_DOWN,
                new_status=STATUS_DOWN,
                detail=f"still down after {new_fails} checks: {result.detail}",
            )
        return None
    return Transition(
        component=component.name,
        group=component.group,
        old_status=old_status,
        new_status=new_status,
        detail=result.detail,
    )


def _run_check(component: Component, prior: dict | None) -> CheckResult:
    """Dispatch the check, catching any raise into a `down` CheckResult.

    The check modules already handle their own transport failures; this
    is the last-resort guard for an unexpected bug, keeping the sweep
    alive (Tier-2)."""
    try:
        return checks.run_check(component, prior)
    except Exception as exc:  # noqa: BLE001, Tier-2 guard, never crash the sweep
        log.warning("check raised for %s: %s", component.name, exc)
        return CheckResult(DOWN, f"check raised: {type(exc).__name__}: {exc}")


def _classify(
    result: CheckResult, old_status: str, prior_fails: int
) -> tuple[str, int, bool]:
    """Map a CheckResult + prior state to (new_status, new_fails, ok).

    - UP      → status up, fails reset, ok=True (stamps last_ok_at).
    - UNKNOWN → status unknown, fails reset (unknown is not a miss), ok=False.
    - DOWN    → bump fails; flip to `down` only at the DOWN_THRESHOLD,
                otherwise hold the prior status (flap suppression).
    """
    if result.classification == UP:
        return STATUS_UP, 0, True
    if result.classification == UNKNOWN:
        return STATUS_UNKNOWN, 0, False

    # DOWN classification, accumulate toward the threshold.
    new_fails = prior_fails + 1
    if new_fails >= DOWN_THRESHOLD:
        return STATUS_DOWN, new_fails, False
    # Sub-threshold: hold the prior status so a flap doesn't transition.
    # A fresh component with no prior status holds `pending` until it
    # either passes (up) or crosses the threshold (down).
    held = old_status if old_status in (STATUS_UP, STATUS_DOWN, STATUS_UNKNOWN) else STATUS_PENDING
    return held, new_fails, False


def _report(transitions: list[Transition]) -> None:
    """Put this sweep's down components in the notify pen, once the digest
    has said they are worth a person's attention (Tier-2).

    Two gates, in order. The page-worthiness gate is unchanged: a component
    with page_on_down=False (the best-effort externals) never gets past it,
    so a third party having a bad afternoon is still not a stack page. What
    survives is a down-flip, or the hourly re-raise of something that is
    still down; a recovery is not reported at all (module docstring).

    Then the digest judges the batch as a whole, which is where a deploy
    restart is separated from an outage. It writes nothing that ships, and
    when it says silent it now writes one audit row per component instead of
    returning empty-handed (`_record_digest_silence`).

    The page-worthiness gate is deliberately NOT recorded that way. A
    `page_on_down=False` component is a standing configuration statement, made
    once in the registry and true of every sweep, not a judgement made about
    this batch: the externals (anthropic, github) are declared
    unpageable in `registry.REGISTRY`, so "was this silenced" is answered by
    reading that file rather than by counting rows, and a row per sweep would
    add volume without adding a fact. The digest is the opposite: a model, a
    different answer each time, and nothing else recording what it decided.

    One pen row per component, not one per sweep: the pen batches by
    itself, and a row per subject is what gives the flusher a history to
    count ("ping 4 on this subject"), a mute to match, and the recurring
    filer something to put on the board."""
    page_on_down = {component.name: component.page_on_down for component in registry.REGISTRY}
    pageworthy = [
        transition
        for transition in transitions
        if page_on_down.get(transition.component, False)
        and transition.new_status == STATUS_DOWN
    ]
    if not pageworthy:
        return
    if not _judged_worth_saying(pageworthy):
        _record_digest_silence(pageworthy)
        return
    for transition in pageworthy:
        _queue_ping(transition)


def _record_digest_silence(transitions: list[Transition]) -> None:
    """One audit row per down component the digest decided not to say (Tier-2).

    THE HOLE THIS FILLS. `_judged_worth_saying` is a MODEL
    deciding that a batch of components that are genuinely down is not worth a
    person's attention, and it sits one layer BEFORE the pen: no ping is
    written, so none of the pen's floors apply, none of its audit rows exist and
    nothing downstream can tell this batch from a sweep in which nothing broke.
    It is the same defect class `notify_flush._unheard_critical` guards
    against, critical flushes judged noise; that one at least leaves rows to
    count afterwards, and this one would leave nothing at all.

    The DOWN itself is not lost, it is in `component_status` (Tier-1, written
    before this runs). What was missing is the judgement, so that is what the
    row records: `severity` stays `info` because this row is bookkeeping and a
    critical stamp would read as a page that went out, and `status` stays
    `firing` because the component is down and saying otherwise here would be
    the lie the row exists to prevent.

    One row per component rather than one per batch, matching `_queue_ping`: the
    pen counts per subject, so a silence has to be countable against the same
    key. Rows land only on a down-flip or on the hourly re-raise, never once per
    sweep, because those are the only transitions that reach this function.

    Tier-2 for the same reason every write on this path is: a sweep that cannot
    file its bookkeeping still has to run the next component.
    """
    for transition in transitions:
        try:
            state.record_alert(
                fingerprint=f"{SILENCE_FINGERPRINT_PREFIX}{transition.component}",
                name=f"digest silenced: {transition.component} down"[:200],
                severity="info",
                status="firing",
                decision=SILENCE_DECISION,
                reason="digest-judged-not-worth-saying",
                signal_sent=False,
                dead_letter=False,
            )
        except Exception as exc:  # noqa: BLE001, Tier-2: never stop the sweep
            log.error(
                "digest silence not recorded (swallowed) for %s: %s",
                transition.component,
                exc,
            )


def _judged_worth_saying(transitions: list[Transition]) -> bool:
    """Ask the digest whether this batch is a real problem or deploy churn.

    True unless the digest came back SILENT. Its message is logged rather
    than shipped: the page is rendered from the pen row by
    `core/page_render.py`, so prose written here would never reach anyone.

    Tier-2, and degrade-never-drop: a digest that raises leaves the batch
    unjudged, which is not the same as judged harmless, so the pings go to
    the pen and the pen decides."""
    try:
        finding = digest.digest_transitions(transitions)
    except Exception as exc:  # noqa: BLE001, Tier-2: a digest fault must not stop the sweep
        log.error("monitor digest raised (swallowed, batch still queued): %s", exc)
        return True
    if finding is None:
        return False
    log.info("monitor digest judged the batch page-worthy: %s", finding)
    return True


def _queue_ping(transition: Transition) -> None:
    """Drop one down component in the notify pen (Tier-2).

    The subject is the news and it is what a reader sees: the pen's lead
    sentence is the subject plus the time it was observed. The body is the
    monitor's own facts only, in labelled lines the pen's parser reads. No
    model prose goes in it: a body that quoted a log tail would be read as
    a cut window and the page would say the sender truncated itself.

    A pen write that fails loses the page, so it is recorded as a dead
    letter rather than only logged. That is the row `monitor/dead_letters`
    watches, and a log line is not a watch."""
    subject = f"{_SEVERITY_MARKER} stack component down: {transition.component}"
    body = "\n".join(
        (
            f"Component: {transition.component}",
            f"Group: {transition.group}",
            f"Detail: {transition.detail}",
        )
    )
    try:
        state.enqueue_ping(subject, body, PING_SOURCE)
    except Exception as exc:  # noqa: BLE001, Tier-2: a pen fault must not stop the sweep
        log.error("monitor ping not queued (swallowed): %s: %s", subject, exc)
        outbound.record_delivery("monitor-page", subject, False)
