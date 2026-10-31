"""The MCP tool door: the assistant's tools, over the wire, on somebody's behalf.

The assistant's tools were reachable only from inside this pod: the Anthropic loops in
`core/` called `tools.execute_typed` directly, so a second agent (the OpenClaw
gateway on the deploy VM) could see the company's kubectl, GitHub,
Loki, Prometheus, agenda and ops-database view only by having the loops
re-implemented around it. This module serves that same registry over MCP
streamable-http at `POST /mcp` on the app in `app.py`, so the tools have one
home and one definition and a second caller costs a config entry rather than a
second copy.

It serves the write tools as well as the read-only half, because without
them the assistant on Signal cannot book a meeting, message a teammate or
remember a correction. The house rules
want a decision per write tool on the LLM surface; that decision is the owner's and it
is made. `core/tools/gateway_surface.py` holds it, so the prompt block in
`workspace/capabilities.py` and this catalogue cannot describe different doors.

WHO ASKED, and this is the hard half. `write_tools.dispatch` takes an `Actor`.
Inside the container that is free: a Signal message carries a verified sender, so the
chat loop knows whose write it is. This door has ONE bearer and ONE caller, so
an MCP call carries no requester at all, and two things depend on there being
one: `github_act` takes a board write only from someone the people registry
holds, and every audit row is meant to say who asked. A fixed actor would stamp
every write with one person's name. So every write tool served here carries an
added required argument naming the person, and the door resolves it here.

RESOLVED BY NAME, and only by name, on the evidence in `core/people.py`. That
registry is keyed by Signal number or `uuid:<id>` and looks a person up by key
(`identify`, `identify_by_number`); by NAME it answers `names()`, `style_for`,
`language_for` and `number_for`, and none of them can hand back a UUID. There
is no name-to-UUID lookup to write either, because a UUID is the STRONG
identity the registry keeps precisely so a reassignable number cannot inherit a
teammate's profile, and deriving one from a name a model typed would
manufacture exactly the strength it exists to protect. So the `Actor` gets the
registry's own spelling of the name and `uuid=None`, which is what the in-container
patrol actor already does; `github_act` matches the registry on name, so every
teammate authorizes and a name the registry does not hold does not.

RECORDED HERE, not left to the tools. Five of the nine write their own audit
row; the four that only touch the assistant's own SQLite (`manage_worklist`,
`remember_note`, `remember_principle`, `personal_rule`) write none, because
the house rules left the assistant's self-artefacts ungated while the only way to reach them
was a verified Signal sender. That reason does not cross this door, so the door
writes its own row for EVERY write it drives, before it drives it: kind
`door_write`, actor the resolved person, the arguments in `detail`. A call
whose row cannot be written is not dispatched. So the two rows a
`message_teammate` leaves are not duplication, they are the request and the
effect, and `my_actions` can answer "what came in over the door" at all.

THE RESIDUAL, plainly, and it is two things rather than one. The model on the
other side can name any person the registry holds. This bounds a lie to the
team and it records it: an unknown name is refused before dispatch with nothing
written, and a known name goes into `state.assistant_actions` next to what was
done, so a write attributed to the wrong person is visible afterwards. It does
not PREVENT one. Preventing it needs the requester to arrive as something the
gateway verified rather than something the model wrote, which the MCP protocol
gives no place for today.

And naming a person is not only attribution, it is the person-driven branch of
the tools. `message_teammate` holds quiet hours only for the assistant's OWN initiative
(actor "assistant"), and `agenda_act` refuses to remove an event it did not create
only for that same actor. A call that names a person gets neither hold.

THE ASSISTANT ITSELF, as a requester, for the writes nobody asked for. When
the door held only humans, the morning brief, the advisor and
every worklist item the assistant opened itself would have to be booked to a
person, and the model would name someone who did not ask because "assistant"
was refused. So `requested_by: "the assistant"` is now
accepted for the tools in `_SELF_PROVENANCE_TOOLS` alone. For most of them the
actor "assistant" can only add a hold (quiet hours, the remove-only-my-own rule) or
change whose name a row of the assistant's own state carries. `github_act` is
among them because the assistant has full write access to the board, since
without it it cannot help: the in-container patrol writes the board as
"assistant", and the gateway's brief, advisor and chat may too. Every action that tool has can be undone and is audited, and
`ASSISTANT_GITHUB_WRITE` still turns it off. Every other write is refused under that
name before dispatch: `create_video_call` and the two
instruction-rewriting tools stay person-only. It is still a claim the model
makes, and the record is only as honest as that claim; what changed is that an
honest claim can now be recorded at all.
`ASSISTANT_DOOR_WRITE=0` is the lever if any of this turns out otherwise.

What it owns: the MCP protocol seam. The catalogue handed to a client, the
bearer check in front of it, resolving the requester to an `Actor`, keeping the
blocking tool call off the event loop, and the mapping to MCP's `isError`.

What it does NOT own. The tools, their schemas and their kill switches live in
`core/tools/` and are taken verbatim; which of them the door serves is
`core/tools/gateway_surface.py`'s. The wording of a result is
`core/tools/meta/result.py`'s. Whether a write actually landed is the tool's
own sentence, which travels verbatim. The truncation budget is
`core/tools/meta/text.py`'s. Who may hold the bearer is `shared/auth.py`'s.
Routing `/mcp` onto the app is `app.py`'s.

Single public callable: `assistant_mcp_door()`; `McpDoor` is its return type and
rides with it.

A FACTORY, NOT A SINGLETON, and this is load-bearing.
`StreamableHTTPSessionManager.run()` raises `RuntimeError(".run() can only be
called once per instance")` on a second entry and sets its task group back to
None on exit (mcp 1.29.0, `streamable_http_manager.py`). One door per process
is therefore one door per LIFETIME, so a test or a harness that wants a second
lifespan builds a second door.

FAILURE POLICY: fail-closed at the bearer and fail-closed on identity, Tier-2
behind both. A missing or wrong bearer is a 401 before the body is read. A
request that arrives before the lifespan has started the session manager is a
503 that says so, rather than the library's `RuntimeError: Task group is not
initialized`. A write call that names nobody, or names somebody the people
registry does not hold, or whose audit row cannot be written, is refused before
`dispatch` is reached, so nothing is written. Past that, every tool fault comes
back as TEXT with `isError` set: a schema violation, a tool that raised, a tool
whose configuration is missing, a write the tool itself refused. This is
because the door shares a process with `/health` and the alertmanager webhook
that pages a human, and no MCP call may take that process down. An unset
`OPENCLAW_WEBHOOK_SECRET` still raises out of `shared.auth` (its fail-loud
policy, unchanged here).
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import contextlib
import functools
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import anyio
import anyio.to_thread
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.datastructures import Headers

from apps.assistant.core import outbound, people, tools
from apps.assistant.core.tools import gateway_surface, write_guard, write_tools
from apps.assistant.core.tools.team import message_teammate
from apps.assistant.shared import auth

# The MCP server name a client sees. Matches the id the gateway registers it
# under in `mcp.servers` so a log line on either side names the same thing.
_SERVER_NAME = "assistant-tools"

# How many tool executions may run at once behind this door.
#
# Two, and the number is the container's, not the protocol's. `execute_typed` blocks
# (subprocess, psycopg2, urllib), so every accepted call holds a worker thread
# inside a container that also serves `/health` and the
# alertmanager webhook. Before this door the container ran ONE investigation at a
# time, driven by its own loops. Two keeps a second caller from serialising
# behind the first without letting an agent that likes parallel tool calls turn
# the container into a fork bomb of kubectl processes. Raise it only together with
# a CPU limit on the `assistant` service in `apps/assistant/compose.yml`.
_MAX_CONCURRENT_TOOL_CALLS = 2

# The door's own ceiling on one tool call, in seconds.
#
# A backstop, not a routine path: `run_shell` stops itself at 20 s and the HTTP
# tools carry their own timeouts, so 45 s is only reached by a tool that has
# genuinely wedged. It sits under the gateway's own 60 s request timeout, so
# the caller gets our sentence rather than its own, and far under the liveness
# budget (30 s x 5 failures = 150 s before k8s restarts the container).
_TOOL_CALL_TIMEOUT_S = 45.0

# The loop name a write through this door is recorded under.
#
# "chat", and it is not a placeholder. `Actor.loop` says which of the assistant's roads
# a write came off (`core/roads.py`): a beat is "patrol", a conversation is
# "chat". Every call here is made on behalf of a person who asked for it, in a
# conversation that person is having, which is what "chat" means. That is the
# door's CONTRACT and nothing enforces it: the door cannot tell a call the
# gateway made mid-conversation from one it made on a timer of its own, which
# is the second half of the residual in the module docstring. A new name would
# also be a road nothing declares.
_DOOR_LOOP = "chat"

# The name a call gives when nobody asked: the assistant itself. Compared
# case-insensitively, and recorded as the in-container self-actor's spelling.
_SELF_REQUESTER = "assistant"

# The writes the assistant may book to itself over the door, and only these.
# For most, actor "assistant" grants nothing a person would not get: quiet hours
# and the remove-only-my-own rule are holds, and the worklist and notes are
# the assistant's own state. `github_act` is here because the assistant has
# full board write access; every action it has is
# reversible and audited, and ASSISTANT_GITHUB_WRITE is its kill switch.
# `create_video_call` and the two instruction-rewriting tools
# stay person-only. Adding a name here is a decision about authority: read
# what that tool does for actor "assistant" first.
_SELF_PROVENANCE_TOOLS = frozenset({
    write_tools.MANAGE_WORKLIST,
    write_tools.REMEMBER_NOTE,
    write_tools.MESSAGE_TEAMMATE,
    write_tools.AGENDA_ACT,
    write_tools.GITHUB_ACT,
})

# The audit `kind` every door-driven write is recorded under, whether or not
# the tool records one of its own. It is deliberately not one of the tools'
# kinds: this row says a write was ASKED FOR over the door and by whom, and the
# tool's own row (when it has one) says what actually happened.
_DOOR_AUDIT_KIND = "door_write"

# What a write tool's own answer looks like when it REFUSED rather than ran.
#
# Two shapes and each has exactly one producer: `write_guard.refuse` builds the
# first for every kill switch and every bounded-audience check, and
# `message_teammate` builds the second for its five pre-send checks. This is
# the whole of the door's isError verdict for a write, and `was_success` is not
# used for it: that table only knows the sentences a LANDED write opens with,
# so a read-shaped action ("your personal rules: ...", "worklist is empty",
# "removed rule 2.") comes back False from it and was being reported to the
# gateway as a failure the caller is told not to trust. The in-container loops never
# did that (they pass such a result through untouched), and a refusal is
# still answered because the tool's own words travel in the text either way. A
# test pins both prefixes against the code that produces them.
_REFUSAL_PREFIXES = ("refused:", "not sent:")

# Handed to the client on `initialize`. The three statuses are the point: a
# tool that could not run must never be read as a tool that found nothing,
# which is the mistake the claim audit exists to stop, and this is the first time
# those results cross a process boundary.
_INSTRUCTIONS = (
    f"{ASSISTANT_NAME}'s tools, served from the assistant container. Most of them only observe. "
    "The ones that change something (the agenda, the GitHub board, a Signal "
    f"message to a teammate, {ASSISTANT_NAME}'s own memory) each require a "
    f"`{gateway_surface.REQUESTER_ARGUMENT}` argument naming the person who "
    f"asked you for it, spelled as the people registry spells it, or '{ASSISTANT_NAME}' "
    "when nobody asked and you are acting on your own; a name it does not "
    "hold is refused and nothing is written, and every one of them is logged "
    "under that name before it runs.\n"
    "A write tool says in its own words whether it did the thing. Never report "
    "an action as done unless its answer says so.\n"
    "Each result opens with its status and the time it was taken. OK means "
    "the tool ran, and an OK result saying nothing matched means it genuinely "
    "found nothing. FAILED means the tool ran and errored, so it is not "
    "evidence about the thing you asked about. UNAVAILABLE means the tool "
    "never ran because its configuration is missing; it is not an empty "
    "result, and the answer names what is unset. A tool that is unavailable "
    "right now says so at the front of its description."
)


@dataclass(frozen=True)
class McpDoor:
    """One door: the ASGI app to route, and the lifespan that must wrap it.

    Single use. The lifespan cannot be entered twice (see the module
    docstring); build another door instead.
    """

    asgi_app: Any
    lifespan: Callable[[Any], Any]


def assistant_mcp_door() -> McpDoor:
    """Build a fresh MCP door over the surface `gateway_surface.py` decided on.

    That surface is the read-only investigation tools plus, unless
    `ASSISTANT_DOOR_WRITE=0`, the nine write tools, each of which must name the
    person who asked (see the module docstring).
    """
    server = Server(_SERVER_NAME, instructions=_INSTRUCTIONS)
    limiter = anyio.CapacityLimiter(_MAX_CONCURRENT_TOOL_CALLS)

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return _catalogue()

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        if gateway_surface.is_served_write_tool(name):
            outcome = await _write_on_behalf_of(name, arguments, limiter)
        elif write_tools.is_write_tool(name):
            outcome = _not_served(name)
        else:
            outcome = await _run_off_the_event_loop(name, arguments, limiter)
        answer = tools.truncate(tools.result.render(outcome))
        # Every OK answer is kept as evidence: `message_teammate`
        # refuses a message citing an issue no answer of the last half hour
        # held. A send's own answer is not evidence of anything it said, and
        # neither is a write that only repeats its input.
        if (
            outcome.ok
            and name != write_tools.MESSAGE_TEAMMATE
            and not write_tools.echoes_its_input(name, arguments)
        ):
            await anyio.to_thread.run_sync(
                outbound.remember_door_reading,
                name,
                _without_requester(arguments),
                outbound.READING_OK,
                answer,
            )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=answer)],
            isError=not outcome.ok,
        )

    manager = StreamableHTTPSessionManager(
        app=server,
        # Plain JSON rather than SSE: the hop to this pod is a reverse proxy
        # and a `kubectl port-forward`, and a long-lived event stream over
        # those is a way to wedge the same hop the alert POST takes.
        #
        # This setting governs the POST reply ONLY. The library's other stream
        # is opened by a GET, which it answers with a standalone event stream
        # whatever this says, so the no-stream promise is only kept while the
        # route in `app.py` is bound to POST. Change one, read the other.
        json_response=True,
        # A fresh transport per request, so a gateway restart needs no session
        # recovery and nothing about a caller is remembered between calls.
        stateless=True,
        # DNS-rebinding protection off. It defends a browser origin; this door
        # takes no cookies and is reached by a server holding a bearer, and
        # leaving it on 421s every request whose Host is not one the library
        # guessed (the container IP from a probe, `testserver` from the harness).
        security_settings=None,
    )
    door = _BearerGatedDoor(manager)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Any) -> AsyncIterator[None]:
        async with manager.run():
            door.mark_open()
            try:
                yield
            finally:
                door.mark_closed()

    return McpDoor(asgi_app=door, lifespan=lifespan)


class _BearerGatedDoor:
    """The ASGI callable routed at `/mcp`: bearer first, then the protocol."""

    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self._manager = manager
        self._open = False

    def mark_open(self) -> None:
        """Record that the lifespan has started the session manager."""
        self._open = True

    def mark_closed(self) -> None:
        """Record that the lifespan has torn the session manager down."""
        self._open = False

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        # The header is read out of the scope, so an unauthenticated caller is
        # refused without the body ever being pulled off the socket.
        if not auth.verify(Headers(scope=scope).get("authorization")):
            await _refuse(send, 401, "unauthorized")
            return
        if not self._open:
            await _refuse(
                send,
                503,
                "the MCP door is not running: this app was started without its "
                "lifespan, so the session manager was never entered",
            )
            return
        await self._manager.handle_request(scope, receive, send)


def _catalogue() -> list[types.Tool]:
    """Every tool the door serves, its schema verbatim, marked if it cannot run.

    Read fresh on every `tools/list` rather than built once at import: the container
    picks up a secret without a rebuild, so a tool can become available while
    the process lives.

    An unavailable tool stays LISTED. Dropping it tells the model the assistant has no
    log tool at all, which is the same wrong conclusion an issue is about,
    arrived at from the other side.

    The readiness table covers the read registry only; a write tool declares no
    `REQUIRES` and is gated by its own kill switch at execution time, so it
    lists plainly here and says no in its answer when the switch is off.
    """
    table = tools.readiness_table()
    catalogue: list[types.Tool] = []
    for definition in gateway_surface.served_definitions():
        name = definition["name"]
        catalogue.append(
            types.Tool(
                name=name,
                description=_describe(
                    definition["description"],
                    tools.readiness.unavailable_reason(table, name),
                ),
                inputSchema=definition["input_schema"],
            )
        )
    return catalogue


def _describe(description: str, unavailable_reason: str | None) -> str:
    """The tool's own description, with its readiness in front of it if bad."""
    if unavailable_reason is None:
        return description
    return (
        f"UNAVAILABLE RIGHT NOW ({unavailable_reason}). Calling it answers with "
        f"what is missing, not with data, and that answer is not evidence about "
        f"the thing you asked. {description}"
    )


async def _write_on_behalf_of(
    name: str, arguments: dict[str, Any], limiter: anyio.CapacityLimiter
) -> tools.result.ToolResult:
    """Run one write tool as the person the call names, or refuse before it.

    The identity check is fail-closed and happens here, on the event loop, so a
    call that cannot say whose write it is never reaches `dispatch` at all: no
    kill switch is read, no audit row is written and no board, calendar or
    phone is touched.
    """
    claimed = _claimed_requester(arguments)
    if not claimed:
        return tools.result.failed(
            name,
            f"this call names nobody: {gateway_surface.REQUESTER_ARGUMENT} is "
            "empty. Every write is recorded against the person who asked for "
            "it, so say who that is and call it again. Nothing was written.",
        )
    if claimed.lower() in (_SELF_REQUESTER, ASSISTANT_NAME.lower()):
        return await _write_as_assistant(name, arguments, limiter)
    person = _registry_name(claimed)
    if person is None:
        return tools.result.failed(
            name,
            f"my people registry holds nobody called {claimed!r}, so I cannot "
            "record this write against them or check what they may do. Ask "
            "The owner to add them (SIGNAL_PEOPLE), or name the person as the "
            "registry spells them. Nothing was written.",
        )
    tool_input = _without_requester(arguments)
    actor = write_tools.Actor(
        name=person, uuid=None, loop=_DOOR_LOOP, evidence=outbound.door_excerpts
    )
    return await _dispatch_off_the_event_loop(name, tool_input, actor, limiter)


async def _write_as_assistant(
    name: str, arguments: dict[str, Any], limiter: anyio.CapacityLimiter
) -> tools.result.ToolResult:
    """Run one write booked to the assistant itself, or refuse it if that tool is
    person-only (`_SELF_PROVENANCE_TOOLS` says which and why)."""
    if name not in _SELF_PROVENANCE_TOOLS:
        return tools.result.failed(
            name,
            f"{name} needs the person who asked for it: on my own I may only "
            "keep my worklist and notes, message a teammate, change the "
            "agenda, or work the GitHub board. If somebody asked, name them; "
            "if nobody did, do not do it. Nothing was written.",
        )
    actor = write_tools.Actor(
        name=_SELF_REQUESTER, uuid=None, loop=_DOOR_LOOP, evidence=outbound.door_excerpts
    )
    return await _dispatch_off_the_event_loop(
        name, _without_requester(arguments), actor, limiter
    )


def _without_requester(arguments: dict[str, Any]) -> dict[str, Any]:
    """The call's arguments minus the door's own `requested_by`."""
    return {
        key: value
        for key, value in arguments.items()
        if key != gateway_surface.REQUESTER_ARGUMENT
    }


def _claimed_requester(arguments: dict[str, Any]) -> str:
    """The person's name this call carries, stripped; empty when it carries none.

    The schema marks the argument required, so the library refuses a call that
    omits it before this is reached. An empty string satisfies that schema,
    which is why the door reads it itself as well.
    """
    return str(arguments.get(gateway_surface.REQUESTER_ARGUMENT) or "").strip()


def _registry_name(claimed: str) -> str | None:
    """The people registry's own spelling of `claimed`, or None if it holds
    nobody by that name (case-insensitive, as every other name lookup there is).

    The registry's spelling rather than the caller's, because that string is
    what the audit row records, and it should not depend on how a model typed
    a name.
    """
    wanted = claimed.strip().lower()
    return next((name for name in people.names() if name.lower() == wanted), None)


async def _dispatch_off_the_event_loop(
    name: str,
    tool_input: dict[str, Any],
    actor: write_tools.Actor,
    limiter: anyio.CapacityLimiter,
) -> tools.result.ToolResult:
    """Run one blocking write in a worker thread, under the same bound as a read.

    The same `abandon_on_cancel=True` as the read path, so the timeout can
    actually fire, with one difference in what the caller is told: an abandoned
    write may still land, so its timeout says so instead of reading like a
    write that did not happen.
    """
    def _run() -> tools.result.ToolResult:
        return _write_outcome(name, tool_input, actor)

    try:
        with anyio.fail_after(_TOOL_CALL_TIMEOUT_S):
            return await anyio.to_thread.run_sync(
                _run, abandon_on_cancel=True, limiter=limiter
            )
    except TimeoutError:
        return tools.result.failed(
            name,
            f"no answer within {_TOOL_CALL_TIMEOUT_S:.0f}s, so the MCP door gave "
            "up on it. It may or may not have gone through; check my action log "
            "with my_actions before doing it again.",
        )


def _not_served(name: str) -> tools.result.ToolResult:
    """The answer to a write tool this door knows and does not offer."""
    return tools.result.failed(
        name,
        f"{name} is a write tool and this door is not serving its write half "
        f"right now ({gateway_surface.DOOR_WRITE_ENV} is off, or this tool was "
        "not one of the ones decided on). Nothing was written, and nobody was "
        "asked; say plainly that you cannot do it.",
    )


def _write_outcome(
    name: str, tool_input: dict[str, Any], actor: write_tools.Actor
) -> tools.result.ToolResult:
    """One write tool's answer, recorded against its requester first. Blocking.

    The order is the point. The row naming who asked is written BEFORE the tool
    runs, so a write this pod could not record is a write this pod does not
    make; four of the nine record nothing themselves, and for those this row is
    the only trace there is.
    """
    try:
        _record_the_request(name, tool_input, actor)
    except Exception as exc:  # noqa: BLE001 - Tier-2: a fault is an answer
        return tools.result.failed(
            name,
            f"I could not write this down before doing it "
            f"({type(exc).__name__}: {exc}), so I did not do it. Every write "
            "over this door is recorded against the person who asked first. "
            "Nothing was written.",
        )
    _start_a_fresh_turn(name)
    return _dispatched_outcome(name, tool_input, actor)


def _record_the_request(
    name: str, tool_input: dict[str, Any], actor: write_tools.Actor
) -> None:
    """Log this door call in `state.assistant_actions`, under the person who asked.

    `write_guard.audit` is Tier-1 and propagates, which is what the caller
    above is counting on: an unrecordable write must not happen.
    """
    write_guard.audit(
        _DOOR_AUDIT_KIND,
        f"{name} over the MCP door",
        f"asked for by {actor.name}",
        actor=actor.name,
        detail=str(tool_input),
    )


def _start_a_fresh_turn(name: str) -> None:
    """Clear the per-turn gates the tool being dispatched keeps between calls.

    One MCP call is one turn on this door: it arrives on its own, with its own
    requester, and nothing carries over to the next one. `message_teammate`
    refuses a recipient at most once per turn for writing in the wrong language
    and the flag behind that is module-global, cleared by each loop that
    can drive the tool at the top of its turn. Without
    this line the door is the one driver that never clears it, so its first
    refusal for a recipient would be its last for the life of the container and an
    identical resend of the same wrong-language draft would go out.
    """
    if name == write_tools.MESSAGE_TEAMMATE:
        message_teammate.reset_language_gate()


def _dispatched_outcome(
    name: str, tool_input: dict[str, Any], actor: write_tools.Actor
) -> tools.result.ToolResult:
    """One write tool's plain-text answer, as a typed outcome. Blocking.

    FAILED means the tool did not run, raised, or said no: the two refusal
    shapes in `_REFUSAL_PREFIXES` are the only "said no" there is, and each has
    one producer. Everything else is OK with the tool's own sentence carried
    verbatim, which is how the in-container loops treat the same strings; a write
    that did not land says so in that sentence, and the protection is that
    sentence rather than a status the door invents over it.
    """
    try:
        answer = write_tools.dispatch(name, tool_input, actor)
    except Exception as exc:  # noqa: BLE001 - Tier-2: a fault is an answer
        return tools.result.failed(name, f"{type(exc).__name__}: {exc}")
    if answer is None:
        return tools.result.failed(name, f"unknown tool: {name}")
    if answer.lstrip().lower().startswith(_REFUSAL_PREFIXES):
        return tools.result.failed(name, answer)
    return tools.result.ok(name, answer)


async def _run_off_the_event_loop(
    name: str, arguments: dict[str, Any], limiter: anyio.CapacityLimiter
) -> tools.result.ToolResult:
    """Run one blocking tool in a worker thread, bounded and time-boxed.

    `abandon_on_cancel=True` so the timeout can actually fire: without it anyio
    holds the cancellation until the thread returns, which is exactly the case
    the timeout exists for. The abandoned thread runs on to its own timeout,
    but its slot in the limiter is released the moment we give up on it, so a
    single wedged tool cannot close the door behind it.
    """
    try:
        with anyio.fail_after(_TOOL_CALL_TIMEOUT_S):
            return await anyio.to_thread.run_sync(
                functools.partial(tools.execute_typed, name, arguments),
                abandon_on_cancel=True,
                limiter=limiter,
            )
    except TimeoutError:
        return tools.result.failed(
            name,
            f"no answer within {_TOOL_CALL_TIMEOUT_S:.0f}s, so the MCP door gave up on it",
        )


async def _refuse(send: Any, status: int, detail: str) -> None:
    """Answer a request the protocol never gets to see."""
    body = f'{{"detail": "{detail}"}}'.encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
