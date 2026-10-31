"""Tool surface for the LLM loops, the registry seam.

Read-only at launch. Adding any write tool
needs a new PRD + ADR.

Every tool module follows one grammar:
    NAME        the Anthropic tool name
    DEFINITION  the Anthropic `tools=[]` schema entry
    execute(tool_input) -> str   short text result the LLM consumes

Modules (grouped into subject subdirs):
    kubectl/k8s.py              shared in-cluster vs kubeconfig bootstrap
    kubectl/kubectl_get.py      pod/cronjob/deployment/service/node state
    kubectl/kubectl_describe.py full single-resource detail (why it's stuck)
    kubectl/kubectl_logs.py     pod log tail (traceback capture)
    kubectl/kubectl_events.py   recent namespace events (OOMKilled, BackOff)
    gh/gh_issue_view.py         issue body + comments (in-flight work check)
    gh/gh_issue_list.py         recent open issues (backlog scan)
    gh/gh_pr_view.py            PR body + comments (deploy correlation)
    gh/gh_commits.py            recent commits on a branch (what just landed)
    agenda/agenda_view.py       upcoming events on a calendar (Nextcloud CalDAV)
    agenda/agenda_availability.py free-busy across people's calendars
    agenda/person_away.py       who is away for a full day or more, and until when
    agenda/calendars.py         scope-key -> CalDAV path registry
    infra/db_query.py           SELECT-only read of the ops Postgres
    observability/loki_query.py LogQL query over a time range
    observability/prom_query.py PromQL instant query
    meta/stack_status.py        authoritative live stack-liveness view
    meta/my_actions.py          the assistant's own action log, queryable
    meta/submit.py              `submit_triage_decision` terminal tool (triage only)
    meta/text.py                shared tool-result truncation budget

FAILURE POLICY: Tier-2 defended swallow in `execute()`, a raising
tool returns its exception as text so the LLM can react (retry,
another tool, or `page-raw`). A tool fault must never abort the
triage/chat loop; the loops' own caps bound the damage. Unknown tool
names return text, not an exception, for the same reason.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from apps.assistant.core.tools.agenda import agenda_availability, agenda_view, person_away
from apps.assistant.core.tools.gh import gh_changed_files, gh_commits, gh_issue_list, gh_issue_view, gh_pr_view
from apps.assistant.core.tools.infra import db_query, run_shell
from apps.assistant.core.tools.kubectl import k8s as _k8s_mod, kubectl_describe, kubectl_events, kubectl_get, kubectl_logs
from apps.assistant.core.tools.meta import bible, deploy_status, knowledge_search, my_actions, readiness, repo_search, result, stack_status, submit, text as _text_mod, whats_changed
from apps.assistant.core.tools.observability import loki_query, prom_query
from apps.assistant.core.tools.kubectl.k8s import load_config_once
from apps.assistant.core.tools.meta.text import truncate

_agenda_view = agenda_view
_agenda_availability = agenda_availability
_person_away = person_away
_bible = bible
_deploy_status = deploy_status
_db_query = db_query
_gh_commits = gh_commits
_gh_changed_files = gh_changed_files
_gh_issue_list = gh_issue_list
_gh_issue_view = gh_issue_view
_gh_pr_view = gh_pr_view
_kubectl_describe = kubectl_describe
_kubectl_events = kubectl_events
_kubectl_get = kubectl_get
_kubectl_logs = kubectl_logs
_loki_query = loki_query
_prom_query = prom_query
_run_shell = run_shell
_stack_status = stack_status
_my_actions = my_actions
_whats_changed = whats_changed
_knowledge_search = knowledge_search
_repo_search = repo_search
_submit = submit

# Either shape: a tool may return plain text (coerced to OK) or a typed
# `ToolResult` when it needs to say it ran and failed.
ToolExecutor = Callable[[dict[str, Any]], "result.ToolResult | str"]

# `_submit` stays LAST: it's the triage terminal tool. The chat loop filters
# it out by name (`SUBMIT_NAME`); triage scans for it. Ordering keeps the
# investigation tools grouped before the terminal one in the catalogue.
_KUBECTL_MODULES = (_kubectl_get, _kubectl_describe, _kubectl_logs, _kubectl_events)

_TOOL_MODULES = tuple(
    module
    for module in (
        _kubectl_get,
        _kubectl_describe,
        _kubectl_logs,
        _kubectl_events,
        _gh_issue_view,
        _gh_issue_list,
        _gh_pr_view,
        _gh_commits,
        _gh_changed_files,
        _db_query,
        _run_shell,
        _loki_query,
        _prom_query,
        _agenda_view,
        _agenda_availability,
        _person_away,
        _stack_status,
        _my_actions,
        _bible,
        _deploy_status,
        _whats_changed,
        _knowledge_search,
        _repo_search,
        _submit,
    )
    # A box without a cluster gets no kubectl tools, and one without Loki no
    # loki_query: a tool that can only fail is noise in every prompt.
    if (module not in _KUBECTL_MODULES or _k8s_mod.cluster_configured())
    and (module is not _loki_query or os.environ.get("LOKI_URL", "").strip())
)

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    module.DEFINITION for module in _TOOL_MODULES
]

_DISPATCH: dict[str, ToolExecutor] = {
    module.NAME: module.execute for module in _TOOL_MODULES
}

SUBMIT_NAME = _submit.NAME


def investigation_definitions() -> list[dict[str, Any]]:
    """The read-only investigation surface: every read-only tool except the
    triage submit-tool. Shared by every loop that investigates (chat, patrol,
    advisor, monitor digest, security_judge) so the "surface minus submit"
    filter lives here once, not copy-pasted per loop."""
    return [definition for definition in TOOL_DEFINITIONS if definition["name"] != SUBMIT_NAME]


def readiness_table() -> list[readiness.Readiness]:
    """Live readiness for the whole registry."""
    return readiness.snapshot(_TOOL_MODULES)


def readiness_block() -> str:
    """The prompt block naming tools that cannot run, for the loops' spine."""
    return readiness.render(readiness_table())


def execute_typed(name: str, tool_input: dict[str, Any]) -> result.ToolResult:
    """Run a tool and report the outcome as data.

    Three outcomes that used to be one string: OK (it ran), FAILED (it ran and
    errored), UNAVAILABLE (it never ran, configuration missing). Guards and
    receipts consume this; `execute` renders it for the model.
    """
    executor = _DISPATCH.get(name)
    if executor is None:
        return result.failed(name, f"unknown tool: {name}")
    # A tool whose config is missing never runs, and the answer must not read
    # like an empty result, or an unset LOKI_URL reads as a quiet system and
    # sends diagnoses the wrong way.
    reason = readiness.unavailable_reason(readiness_table(), name)
    if reason is not None:
        return result.unavailable(
            name, f"{name} cannot run because its configuration is missing ({reason})"
        )
    try:
        return result.coerce(name, executor(tool_input))
    except Exception as exc:
        # Defended swallow (Tier-2): the fault comes back as data and the loop
        # decides what to do next; a bad tool must never kill the loop.
        return result.failed(name, f"{type(exc).__name__}: {exc}")


def execute(name: str, tool_input: dict[str, Any]) -> str:
    """The text the model consumes. Status and fetch time lead, data follows."""
    outcome = execute_typed(name, tool_input)
    # The submit tool is terminal control flow, not an observation: its return
    # is a token the triage loop reacts to, so it carries no status header and
    # no fetch time. (Triage matches on the tool_use block name, not this
    # string, but wrapping a control token as evidence would still be wrong.)
    if name == SUBMIT_NAME and outcome.ok:
        return outcome.data
    return result.render(outcome)


__all__ = [
    "SUBMIT_NAME",
    "TOOL_DEFINITIONS",
    "ToolExecutor",
    "investigation_definitions",
    "readiness",
    "readiness_block",
    "readiness_table",
    "result",
    "execute_typed",
    "agenda_view",
    "bible",
    "db_query",
    "deploy_status",
    "execute",
    "gh_commits",
    "gh_issue_list",
    "gh_issue_view",
    "gh_pr_view",
    "kubectl_describe",
    "kubectl_events",
    "kubectl_get",
    "kubectl_logs",
    "load_config_once",
    "loki_query",
    "person_away",
    "prom_query",
    "stack_status",
    "submit",
    "truncate",
]
