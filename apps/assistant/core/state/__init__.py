"""SQLite-backed durable state for openclaw, the package seam.

One DB file at `/state/openclaw.db` (env-overridable via
`OPENCLAW_STATE_PATH`), one table-adapter module per table, following
the storage grammar (campaign blueprint §2.3: a table's read+write
callables live together in the file named after the table):

    conn.py         connection cache + schema bootstrap
    utcnow_iso.py   shared row-timestamp clock helper
    today_utc.py    shared day-bucket clock helper
    alerts.py       append-only audit of every alert + outcome
    dedup_window.py 5-min sliding window keyed by fingerprint
    suppression.py  operator-curated patterns we always silence
    budget_day.py   durable daily Anthropic spend counter
    chat_turns.py   per-sender Signal chat history
    component_status.py  live stack-liveness row per component
    pod_boots.py    one row per pod start, the restart history k8s drops
    journal.py      openclaw's durable notes-to-self
    weekly_compacts.py  weekly memory summaries
    reported_items.py   what the brief already said, so it cannot repeat
    message_evidence.py what the assistant read beside what the assistant said

Why SQLite and not Postgres: the deduper + budget state are pod-local,
single-writer, low-volume. A 5 Gi state volume handles years of audit rows. No
need to make the cluster Postgres a dep of triage. state volume is RWO so
single-replica Deployment is enforced by k8s. If we ever need
multi-replica, state moves to Postgres in a follow-up PRD.

FAILURE POLICY: Tier-1 fail-loud. Every read and write propagates
`sqlite3` errors to the caller, a failed audit/dedup/budget write must
fail the webhook request (Alertmanager retries) rather than silently
lose state (a known anti-pattern). There are no swallows in this
package.
"""
from __future__ import annotations

from apps.assistant.core.state.conn import (
    DEFAULT_DB_PATH,
    get_connection,
)
from apps.assistant.core.state.today_utc import today_utc
from apps.assistant.core.state.utcnow_iso import utcnow_iso
from apps.assistant.core.state.reset import reset_for_tests
from apps.assistant.core.state.filed_observations import (
    FILED_TTL_DAYS,
    clear_filed,
    filed_issue_for,
    last_decision_at,
    list_filed,
    record_filed,
)
from apps.assistant.core.state.alerts import (
    alerts_since,
    batch_row_name,
    dead_letters_after,
    delivery_counts_between,
    FOLDED_REPEATS,
    SEVERITY_MARKERS,
    SILENCE_DECISIONS,
    SILENCE_DIGEST,
    SILENCE_QUIET_BEAT,
    SubjectOutcome,
    is_batch_row_name,
    last_pen_page_at,
    louder,
    marked_severity,
    severity_of_subject,
    arrival_status_at,
    cleared_since,
    delivered_pages_since,
    delivered_this_episode,
    firing_paged_names,
    has_delivered,
    pen_subject_delivered,
    list_recent_alerts,
    max_alert_id,
    recent_alert_events,
    records_a_silence,
    subject_outcomes_between,
    subjects_in_row_name,
    record_alert,
    silences_since,
    unheard_silences,
)
from apps.assistant.core.state.budget_day import (
    budget_charge,
    budget_spend_today_eur,
)
from apps.assistant.core.state.chat_turns import (
    append_chat_turn,
    recent_chat_turns,
    turns_between,
)
from apps.assistant.core.state.journal import (
    add_note,
    all_notes,
    delete_note,
    notes_between,
    recent_notes,
)
from apps.assistant.core.state.notify_pen import (
    enqueue_ping,
    flushed_since as pings_flushed_since,
    last_flush_at,
    mark_flushed,
    pending_count as pending_ping_count,
    unflushed_pings,
)
from apps.assistant.core.state.security_events import (
    count_since,
    record_security_event,
    recent_security_events,
)
from apps.assistant.core.state import worklist
# Re-exported as the submodule (not its callables): `split_candidates`,
# `mark_reported`, `mark_answered` and friends read as generic verbs on their
# own; callers use `state.reported_items.split_candidates(...)`.
from apps.assistant.core.state import reported_items
from apps.assistant.core.state.assistant_actions import (
    actions_since,
    record_action,
    recent_actions,
)
from apps.assistant.core.state.page_cooldown import (
    clear as clear_page_cooldown,
    should_page,
)
from apps.assistant.core.state.page_hold import (
    add_cover as add_page_cover,
    dropped_since as dropped_pages_since,
    held_for_arrival,
    hold as hold_page,
    last_release_at,
    last_released_text,
    mark_dropped,
    mark_released,
    oldest_pending_age_seconds,
    pending as pending_pages,
    pending_count as pending_page_count,
    pending_for_key as pending_page_for_key,
    recent_held,
)
from apps.assistant.core.state.weekly_compacts import (
    add_compact,
    all_compacts,
    latest_week_end,
    list_compacts,
)
# Re-exported as the submodule (not its callables): its API names:
# `record_check`, `record_heartbeat`, `get_all`, `get_one`, are generic
# enough that flattening them into the seam would collide; callers use
# `state.component_status.record_check(...)`.
from apps.assistant.core.state import component_status
# Re-exported as the submodule (not its callables): `claim` / `vacuum_old`
# are generic names; callers use `state.meeting_reminders.claim(...)`.
from apps.assistant.core.state import meeting_reminders
# Re-exported as the submodule (not its callables): `starts_between` and
# `first_boot_at` only read as restart history next to the table name;
# callers use `state.pod_boots.record_boot(...)`.
from apps.assistant.core.state import pod_boots
# Re-exported as the submodule (not its callables): `record_said`,
# `record_input`, `said_between` and `vacuum_old` are generic verbs, and
# `vacuum_old` already exists on `meeting_reminders`; callers use
# `state.message_evidence.record_said(...)`.
from apps.assistant.core.state import message_evidence
from apps.assistant.core.state.dedup_window import (
    dedup_check_and_touch,
    vacuum_old_dedup_rows,
)
from apps.assistant.core.state.suppression import (
    add_suppression,
    is_suppressed,
    list_suppressions,
)
from apps.assistant.core.state.principles import (
    add_principle,
    delete_principle,
    list_principles,
)
from apps.assistant.core.state.person_rules import (
    add_person_rule,
    delete_person_rule,
    list_person_rules,
)
from apps.assistant.core.state.report_marker import (
    drop_retired_markers,
    get_report_marker,
    set_report_marker,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "add_compact",
    "add_note",
    "all_compacts",
    "all_notes",
    "add_person_rule",
    "add_principle",
    "delete_person_rule",
    "list_person_rules",
    "drop_retired_markers",
    "get_report_marker",
    "set_report_marker",
    "add_suppression",
    "append_chat_turn",
    "actions_since",
    "clear_page_cooldown",
    "count_since",
    "delete_note",
    "add_page_cover",
    "dropped_pages_since",
    "held_for_arrival",
    "hold_page",
    "last_release_at",
    "last_released_text",
    "mark_dropped",
    "mark_released",
    "oldest_pending_age_seconds",
    "pending_page_count",
    "pending_page_for_key",
    "pending_pages",
    "pending_ping_count",
    "recent_held",
    "should_page",
    "record_action",
    "recent_actions",
    "enqueue_ping",
    "pings_flushed_since",
    "last_flush_at",
    "last_pen_page_at",
    "marked_severity",
    "record_security_event",
    "recent_security_events",
    "latest_week_end",
    "list_compacts",
    "mark_flushed",
    "notes_between",
    "recent_notes",
    "turns_between",
    "unflushed_pings",
    "budget_charge",
    "budget_spend_today_eur",
    "component_status",
    "dedup_check_and_touch",
    "delete_principle",
    "get_connection",
    "is_suppressed",
    "list_principles",
    "FILED_TTL_DAYS",
    "alerts_since",
    "clear_filed",
    "filed_issue_for",
    "last_decision_at",
    "list_filed",
    "record_filed",
    "batch_row_name",
    "dead_letters_after",
    "delivery_counts_between",
    "FOLDED_REPEATS",
    "SEVERITY_MARKERS",
    "SILENCE_DECISIONS",
    "SILENCE_DIGEST",
    "SILENCE_QUIET_BEAT",
    "SubjectOutcome",
    "is_batch_row_name",
    "louder",
    "severity_of_subject",
    "arrival_status_at",
    "cleared_since",
    "delivered_pages_since",
    "delivered_this_episode",
    "firing_paged_names",
    "has_delivered",
    "pen_subject_delivered",
    "list_recent_alerts",
    "max_alert_id",
    "recent_alert_events",
    "records_a_silence",
    "subject_outcomes_between",
    "subjects_in_row_name",
    "silences_since",
    "unheard_silences",
    "list_suppressions",
    "meeting_reminders",
    "message_evidence",
    "pod_boots",
    "recent_chat_turns",
    "record_alert",
    "reported_items",
    "reset_for_tests",
    "today_utc",
    "utcnow_iso",
    "vacuum_old_dedup_rows",
    "worklist",
]
