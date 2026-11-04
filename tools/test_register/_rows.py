"""The register: one row per test in this repository.

OWNS: the rows. This file is data, and the only file anybody edits to add a
test to the register, which is why the `--new` command writes here.

DOES NOT OWN: what a row means (`_row.py`), what fires one (`_triggers.py`),
whether the tree agrees with it (`_check.py`), or whether a break still breaks
anything (`_replay.py`).

HOW TO ADD A ROW. Do not write one by hand:

    python3 -m tools.test_register --new <module> --says "<invariant>"

writes the test file and its row together, so a row cannot be forgotten. Fill
in the break, then prove it:

    python3 -m tools.test_register --replay <the test file>

A break that did not turn its test red does not belong in this file.
"""
from __future__ import annotations

from ._break import Break
from ._row import Row

#: Every test in the tree, sorted by path so a new row lands somewhere a reader
#: can find it.
ROWS: tuple[Row, ...] = (
    Row(
        test='.claude/hooks/tests/test_the_hooks_refuse_a_force_push_or_a_malformed_issue_and_a_push_waits_while_the_deploy_queue_is_long.py',
        pins=('.claude/hooks',),
        runs_when=(
            '.claude/hooks/**',
        ),
        proved_by=Break(
            file='.claude/hooks/issue_guard.py',
            old='    return any(token in ("--force", "--force-with-lease", "-f") or',
            new='    return any(token in ("--force",) or',
            why='a push with --force-with-lease or -f is no longer refused, so the force-push cases fail',
        ),
    ),
    Row(
        test='.claude/hooks/tests/test_the_local_guards_refuse_a_chapter_or_overlay_grown_past_its_budget_and_a_broken_drawn_marker_and_never_a_cut.py',
        pins=('.claude/hooks/local',),
        runs_when=(
            '.claude/hooks/local/linkmap_sync.py',
            'docs/diagrams/tools/**',
            '.claude/hooks/local/bible_guard.py',
            'docs/bible.md',
            'CLAUDE.md',
            '.claude/hooks/local/overlay_guard.py',
            '.claude/hooks/tests/test_the_local_guards_refuse_a_chapter_or_overlay_grown_past_its_budget_and_a_broken_drawn_marker_and_never_a_cut.py',
            '.claude/hooks/local/**',
        ),
        proved_by=Break(
            file='.claude/hooks/local/bible_guard.py',
            old='        if before is not None and words <= before.get(name, 0):',
            new='        if before is not None:',
            why='an edit that grows a chapter is let through, so the growth case fails',
        ),
    ),
    Row(
        test='.claude/index/tests/test_the_index_answers_only_from_the_pinned_build_and_a_finished_index_of_this_commit.py',
        pins=('.claude/index',),
        runs_when=(
            '.claude/index/**',
        ),
        proved_by=Break(
            file='.claude/index/cbm_pin.py',
            old='    if sha256_of(binary) != build.sha256:',
            new='    if False:',
            why='a binary whose hash is not the pinned one is accepted, so the pinned-build case fails',
        ),
    ),
    Row(
        test='docs/diagrams/tests/test_the_diagram_tools_answer_on_an_empty_set_and_refuse_a_broken_page.py',
        pins=('docs/diagrams',),
        runs_when=(
            'docs/diagrams/**',
        ),
        proved_by=Break(
            file='docs/diagrams/tools/linkmap.py',
            old='            continue  # not drawn yet: an empty set is a clean set',
            new='            pass',
            why='a page not drawn yet is read as broken, so the empty-set case fails',
        ),
    ),
    Row(
        test='tools/test_register/tests/test_a_test_that_cannot_fail_is_caught_by_its_own_break.py',
        pins=('tools/test_register',),
        runs_when=(
            'tools/test_register/**',
        ),
        proved_by=Break(
            file='tools/test_register/_replay.py',
            old='        return GREEN, (',
            new='        return RED, (',
            why='a test that passed with its own break applied is reported red, so the shape-only case gets red where it asserts green',
        ),
    ),
    Row(
        test='infra/observability/tests/test_the_textfile_collector_and_probe_targets_render_what_the_rules_read.py',
        pins=('infra/observability/node_textfile',),
        runs_when=(
            'infra/observability/**',
        ),
        proved_by=Break(
            file='infra/observability/node_textfile/collect.py',
            old='{1 if active == "failed" else 0}',
            new='{1 if active == "active" else 0}',
            why='a failed unit is published as 0, so the failed-unit case fails',
        ),
    ),
    Row(
        test='infra/webhook/tests/test_a_reset_that_lost_the_index_lock_pages_nobody.py',
        pins=('infra/webhook',),
        runs_when=(
            'infra/webhook/**',
        ),
        proved_by=Break(
            file='infra/webhook/trigger-deploy.sh',
            old='if [ -n "$reset_failed" ] && grep -qE \'index\\.lock|Another git process seems to be running\' "$reset_output"; then',
            new='if [ -n "$reset_failed" ] && grep -qE \'no such lock message\' "$reset_output"; then',
            why='a lost race is no longer recognised, so a reset that lost the index lock counts as a failed repair',
        ),
    ),
    Row(
        test='.claude/scripts/tests/test_gate_scope.py',
        pins=('.claude/scripts',),
        runs_when=(
            '.claude/scripts/**',
        ),
        proved_by=Break(
            file='.claude/scripts/gate-scope.py',
            old='DOC_SUFFIXES = (".md",)',
            new='DOC_SUFFIXES = (".mdx",)',
            why='a markdown file is no longer a document, so a documents-only change runs the suite',
        ),
    ),
    Row(
        test='apps/assistant/core/monitor/tests/test_a_deployment_scaled_to_zero_on_purpose_is_parked_not_down.py',
        pins=('apps/assistant/core/monitor',),
        runs_when=(
            'apps/assistant/core/monitor/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/monitor/checks/kubectl.py',
            old='    if deployment.spec.replicas == 0:',
            new='    if False:',
            why='a Deployment scaled to 0 falls through to the ready count and classifies down, so the parked test fails',
        ),
    ),
    Row(
        test='apps/assistant/core/state/tests/test_a_finding_that_says_the_same_thing_does_not_move_the_item.py',
        pins=('apps/assistant/core/state',),
        runs_when=(
            'apps/assistant/core/state/**',
            'apps/assistant/core/tools/meta/manage_worklist.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/state/worklist.py',
            old='        moved = row is None or reported_items.worklist_fingerprint(\n            "open", str(row["last_finding"] or "")\n        ) != reported_items.worklist_fingerprint("open", text)',
            new='        moved = row is None or str(row["last_finding"] or "") != text',
            why='the two findings are compared raw, so the reading stamp patrol puts at the front makes every pass look like movement and the item is rewritten on every pass',
        ),
    ),
    Row(
        test='apps/assistant/core/state/tests/test_a_look_into_nobody_has_answered_is_rendered_as_work_to_do_never_as_not_news.py',
        pins=('apps/assistant/core/state',),
        runs_when=(
            'apps/assistant/core/state/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/state/worklist.py',
            old='    if item["kind"] == "look_into":\n',
            new='    if item["kind"] == "look-into":\n',
            why="a look_into falls through to the kind-blind 'not news' label and gets no next-step clause",
        ),
    ),
    Row(
        test='apps/assistant/core/state/tests/test_a_mute_that_would_cover_a_critical_alert_is_refused.py',
        pins=('apps/assistant/core/state',),
        runs_when=(
            'apps/assistant/core/state/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/state/suppression.py',
            old='"SELECT DISTINCT name FROM alerts WHERE severity = \'critical\' "',
            new='"SELECT DISTINCT name FROM alerts WHERE 1=1 "',
            why='the severity filter goes, so every pattern matching any alert at all is refused and no flake can ever be muted',
        ),
    ),
    Row(
        test='apps/assistant/core/state/tests/test_the_worklist_shows_the_last_telling_and_never_own_claim_that_it_told_someone.py',
        pins=('apps/assistant/core/state',),
        runs_when=(
            'apps/assistant/core/state/**',
            'apps/assistant/core/tools/meta/manage_worklist.py',
            'apps/assistant/core/claims.py',
            'apps/assistant/core/journal.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/state/worklist.py',
            old='        finding = claims.without_told_claims(str(item["last_finding"] or ""), teammates)\n',
            new='        finding = str(item["last_finding"] or "")\n',
            why="the raw finding is shown again, so 'Already briefed the owner' reaches the block",
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_covering_page_triage_reads_off_the_awareness_rows_is_one_the_claim_gate_can_find.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/awareness.py',
            old='    return f" [{fingerprint}]"',
            new='    return f" [{fingerprint[:8]}]"',
            why='The awareness row prints an eight-character prefix, so the cover the model copies matches no delivery and `decision == "silent"` fails.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_critical_page_leaves_through_quiet_hours_and_the_morning_gate_while_a_warning_waits.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/page_hold.py',
            old='    return str(row.get("severity") or "").strip().lower() == "critical"',
            new='    return False',
            why='No held page counts as critical, so the critical never leaves at 02:00 or at 07:45.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_failing_signal_send_backs_off_instead_of_retrying_every_pass.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/page_hold.py',
            old='    if _outage.next_try_at is not None and moment < _outage.next_try_at:\n        return None\n',
            new='',
            why='The release retries on every 30-second pass again, so twenty minutes of outage is 41 sends and 41 not-delivered rows, and a longer outage writes hundreds of them.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_filed_mute_holds_for_every_spelling_of_its_subject.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/ping_facts.py',
            old='    return split_subject(subject)[1][:MUTE_KEY_CHARS].rstrip()',
            new='    return str(subject or "").strip()[:MUTE_KEY_CHARS]',
            why='The mute key goes back to the subject exactly as the sender wrote it, the old exact-string key: the card filed bare misses the red bannered ping, the old marked row is not found by the bare lookup, and the bare spelling of a subject that paged red is filed.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_held_page_that_is_no_longer_news_never_reaches_the_phone.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/page_hold.py',
            old='    waiting = _without_stale(_state.pending_pages(), moment)',
            new='    waiting = _state.pending_pages()',
            why='The release stops asking whether a held page is still news, so the page whose alert resolved reaches the phone and the second page of one firing episode does too.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_held_page_the_morning_brief_names_is_not_sent_again_and_one_it_leaves_out_still_is.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/page_hold.py',
            old='    return bool(parts) and all(\n',
            new='    return False and all(\n',
            why='no page ever counts as named by the brief, which is the older code: the page the brief listed reaches the phone a second time beside it.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_lifted_or_lapsed_mute_is_never_refiled_from_the_occurrences_it_already_decided.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/recurring_alerts.py',
            old='        days = [moment[:10] for moment in _undecided(subject, arrivals)]',
            new='        days = [moment[:10] for moment in arrivals]',
            why='The filer counts the whole fortnight again with no cutoff at the last decision, a refile: the lifted subject and the lapsed one are both filed a second time off the rows that produced the first card.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_page_never_ends_on_the_lead_in_of_a_fix_step_whose_command_was_stripped.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/signal_text.py',
            old="            out_lines.append(None)  # the model typing a command it can't run\n            continue",
            new="            continue  # the model typing a command it can't run",
            why='The strip drops a command line without marking where it was, so the lead-in survives and the page ends on `To un-stall it:` followed by `Then confirm`.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_page_never_hands_the_reader_a_unit_nobody_read_or_a_repair_nothing_backs.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
            'infra/observability/prometheus/rules/*.yml',
        ),
        proved_by=Break(
            file='apps/assistant/core/triage.py',
            old='        result = _handover_gate(\n            result, alert=alert, conversation=conversation, given=content, read_text=read_text\n        )\n',
            new='',
            why='Triage drafts skip the remedy and unit checks, the older road, so the fixture page keeps its invented unit and `len(pod.shown) == 2` fails.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_page_that_dropped_never_reads_as_sent_in_the_current_picture.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/awareness.py',
            old='                    f"{_page_outcome(row)}"\n',
            new='',
            why='The arrival row prints its intent alone, as it once did, so the dropped page reads "-> enrich" and `"dropped, never sent" in line` fails.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_pen_silence_names_the_card_or_suppression_that_held_it.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/notify_flush.py',
            old='        reason=why or f"{len(pings)} pings in one flush",',
            new='        reason=f"{len(pings)} pings in one flush",',
            why='The batch-silenced row goes back to counting pings, so it no longer names the filed cards or the suppression that held them, which is all the old rows could say.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_ping_a_closed_card_still_mutes_is_reported_in_the_brief_and_the_mute_is_not_lifted.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/closed_card_mutes.py',
            old='        if card_state == _CLOSED\n',
            new='        if card_state != _CLOSED\n',
            why="the open card is reported and both closed cards are hidden, which is a closed card's mute staying invisible.",
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_relayed_send_names_the_open_worklist_items_a_reply_could_answer_so_record_answer_gets_its_item_id.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
            'apps/assistant/watch/chat_relay.py',
        ),
        proved_by=Break(
            file='apps/assistant/watch/chat_relay.py',
            old='        f"{_open_items_line(send)}"',
            new='        ""',
            why='the note drops the open items line, so the chat sees no item id to record an answer against and the first case goes red',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_resolve_of_a_paged_alert_sends_an_all_clear_even_inside_the_dedup_window.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/triage.py',
            old='    if alert.status == "resolved":\n        return _all_clear(alert, same_cause or [])\n',
            new='',
            why='A resolve goes through the dedup window and the model again, the older triage, so the resolve four minutes after its page is a dedup-window hit and `result.decision != "silent"` fails.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_second_secret_scan_finding_is_a_new_commit_not_a_repeat.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/page_render.py',
            old='            and fact.finding_commit is None\n',
            new='',
            why='Escalation is licensed on the count alone again, so a second finding on another commit is called a repeat and test_a_second_finding_is_not_called_a_repeat\'s `not licenses_aspect(fact, "escalation")` fails.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_send_from_outside_the_recipients_session_is_in_the_relay_feed_once_with_the_number_that_keys_their_session.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/sent_feed.py',
            old='    "teammate-asked": "a message someone asked me to send",\n',
            new='',
            why='a message one person asked the assistant to send another is not relayed, so the feed holds two texts and the first case goes red',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_silence_that_names_its_cover_only_in_prose_is_asked_once_for_it_before_it_becomes_a_raw_page.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/triage.py',
            old='    candidates = _cover_candidates(alert)',
            new='    candidates = []',
            why='The gate stops asking for the cover and pages raw as soon as covered_by_fingerprint is empty, the older gate, so `len(pod.turns) == 2` fails on the fixture shape.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_standing_fault_paged_long_ago_is_paged_again_when_triage_drafts_a_new_page.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/page_hold.py',
            old='        recent = bool(said) and moment - _moment(said) < _REPAGE_AFTER',
            new='        recent = bool(said)',
            why='The episode drop loses its age limit again, so the draft an hour past the window the model is told is dropped like the one inside it, so a recurring page goes out far too rarely.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_teammate_message_about_a_worklist_item_reaches_the_relay_as_concerning_that_item.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
            'apps/assistant/watch/chat_relay.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/team/message_teammate.py',
            old='            worklist_items=tuple(int(item["id"]) for item in their_items),\n',
            new='',
            why='message_teammate no longer records the items with the chat turn, so the send reaches the relay concerning nothing',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_triage_page_never_cites_an_issue_or_a_past_incident_its_own_reads_did_not_back.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/claims.py',
            old='_ISSUE_REF_RE = re.compile(r"(?:#|\\b(?:issue|PRD|ticket)\\s+#?)(\\d{2,5})\\b", re.IGNORECASE)',
            new='_ISSUE_REF_RE = re.compile(r"#(\\d{2,5})\\b")',
            why='Only the "#42" form is a citation again, so "issue 42" passes every guard and `unread_issue_numbers(...) == [42]` fails.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_triage_pass_stores_what_it_read_beside_what_it_said_and_a_critical_silence_on_an_unread_stamp_pages.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/triage.py',
            old='    _outbound.remember_readings(\n        "triage", _what_was_said(final), readings, recipient=alert.fingerprint\n    )\n',
            new='',
            why='Triage stops storing what it read, the older pod, so no row carries the loop `triage` and `len(rows) == 1` fails.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_triage_silence_never_cites_a_page_its_fingerprint_never_delivered.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/triage.py',
            old='    log.warning("triage silence on %s claimed a page that never went out", alert.name)',
            new='    return final',
            why='The gate takes the model\'s word for a page it claims, which is the older triage, so gate-full-audit is silenced on textfile\'s delivery and `decision == "page-raw"` fails.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_triage_silence_reason_keeps_its_clock_times_and_its_counts_come_from_the_table.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/triage.py',
            old='    note = final.reason\n',
            new='    note = re.sub(r"\\s*~?\\b\\d{1,2}:\\d{2}(?::\\d{2})?\\b(?:\\s*UTC)?", "", final.reason).strip()\n',
            why='The claimed-time scrubber is back on the quoted reason, the gate as first shipped, so "at 19:14." becomes "at." and `"at 19:14." in pod.result.reason` fails.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_an_all_clear_says_when_the_alert_stopped_and_never_that_the_problem_is_gone.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/triage.py',
            old='        "away, so this does not say the problem is solved."\n',
            new='        "away. The page about it needs no action now."\n',
            why='The all-clear claims the problem needs no action again, so the `needs no action` pattern matches and the last assertion fails.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_the_weekly_compact_sees_the_commits_of_its_window_and_is_told_to_keep_a_hedge.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/compact.py',
            old='{"role": "user", "content": f"{dump}\\n\\n{_landed_since(start_iso)}"}',
            new='{"role": "user", "content": dump}',
            why="the summariser gets the notes without the window's commits, so the fix sha is not in front of it",
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_triage_names_the_worklist_item_a_page_concerns_only_from_the_open_items_its_prompt_shows_it.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/triage.py',
            old='    if open_items:\n        content += "\\n\\n" + open_items',
            new='    if open_items:\n        pass',
            why='the open items never reach the user turn, so the model cannot read item 36 and the page about it concerns nothing',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/gh/tests/test_a_gh_read_whose_gh_call_exits_non_zero_reaches_the_model_as_failed.py',
        pins=('apps/assistant/core/tools/gh',),
        runs_when=(
            'apps/assistant/core/tools/gh/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/gh/gh_issue_view.py',
            old='        return result.failed(NAME, f"gh issue view failed (rc={overview.returncode}): {overview.stderr.strip()}")',
            new='        return f"gh issue view failed (rc={overview.returncode}): {overview.stderr.strip()}"',
            why='gh_issue_view hands its failure back as a plain string again, so its answer is not a typed FAILED result and the isinstance assertion goes red',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/gh/tests/test_an_issue_or_pr_view_too_long_for_the_budget_keeps_its_newest_comment.py',
        pins=('apps/assistant/core/tools/gh',),
        runs_when=(
            'apps/assistant/core/tools/gh/**',
            'apps/assistant/core/tools/meta/text.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/meta/text.py',
            old='    kept_tail = _last_bytes(tail, room)',
            new='    kept_tail = _first_bytes(tail, room)',
            why='the cut keeps the oldest comments again, so the newest comment falls past the budget and the newest-kept assertion goes red',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/gh/tests/test_every_listed_issue_names_its_owner_and_the_filter_that_ran.py',
        pins=('apps/assistant/core/tools/gh',),
        runs_when=(
            'apps/assistant/core/tools/gh/**',
            'apps/assistant/core/changes.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/changes.py',
            old='"--json", "number,title,state,updatedAt,assignees",',
            new='"--json", "number,title,state,updatedAt",',
            why='the change feed stops asking gh for assignees, so the fixture issues come back with no owner and their rows read unassigned',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/gh/tests/test_every_teammate_can_work_the_whole_board_and_nothing_on_it_can_be_deleted.py',
        pins=('apps/assistant/core/tools/gh',),
        runs_when=(
            'apps/assistant/core/tools/gh/**',
            'apps/assistant/core/people.py',
            'apps/assistant/core/tools/write_guard.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/gh/github_act.py',
            old='    return any(name.lower() == wanted for name in people.names())\n',
            new='    return False\n',
            why='every teammate is refused by the writers list, so their request is no longer done',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/infra/tests/test_a_wrong_column_is_answered_with_the_real_columns_of_the_tables_the_query_names.py',
        pins=('apps/assistant/core/tools/infra',),
        runs_when=(
            'apps/assistant/core/tools/infra/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/infra/db_query.py',
            old='    return isinstance(exc, (psycopg2.errors.UndefinedColumn, psycopg2.errors.UndefinedTable))',
            new='    return isinstance(exc, psycopg2.errors.UndefinedTable)',
            why='With only a wrong table counted as a wrong name, a wrong column gets the bare psycopg2 text again, so the real-columns assertion goes red',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/meta/tests/test_a_memory_write_citing_a_sha_or_issue_no_reading_returned_is_refused.py',
        pins=('apps/assistant/core/tools/meta',),
        runs_when=(
            'apps/assistant/core/tools/meta/**',
            'apps/assistant/core/tools/write_tools.py',
            'apps/assistant/core/tools/team/message_teammate.py',
            'apps/assistant/core/claims.py',
            'apps/assistant/core/outbound.py',
            'apps/assistant/gates/mcp.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/meta/remember_note.py',
            old='    unbacked = unbacked_citation_refusal(note, evidence)\n',
            new='    unbacked = None\n',
            why='the stale sha 9abc1234 is stored in the journal, so the stale-sha replay goes red',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/meta/tests/test_a_page_held_by_quiet_hours_shows_in_as_waiting.py',
        pins=('apps/assistant/core/tools/meta',),
        runs_when=(
            'apps/assistant/core/tools/meta/**',
            'apps/assistant/core/state/notify_pen.py',
            'apps/assistant/core/state/page_hold.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/meta/my_actions.py',
            old='    waiting = _waiting(about)\n',
            new='    waiting = []\n',
            why='my_actions stops reading the pen and the hold queue, so a batch done held overnight answers no actions matching, and the chat could read that as a completion that never came.',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/meta/tests/test_a_question_answered_in_chat_and_recorded_is_not_asked_again.py',
        pins=('apps/assistant/core/tools/meta',),
        runs_when=(
            'apps/assistant/core/tools/meta/**',
            'apps/assistant/core/tools/team/**',
            'apps/assistant/core/tools/write_tools.py',
            'apps/assistant/core/tools/gateway_surface.py',
            'apps/assistant/core/state/reported_items.py',
            'apps/assistant/core/state/worklist.py',
            'apps/assistant/core/state/conn.py',
            'apps/assistant/workspace/capabilities.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/team/message_teammate.py',
            old='    answered = _answered_refusal(their_items, person)\n',
            new='    answered = None\n',
            why="message_teammate no longer reads the answered stamp, so next morning's catering 47 ask to the owner is sent after the owner answered",
        ),
    ),
    Row(
        test='apps/assistant/core/tools/meta/tests/test_a_report_window_opens_at_the_previous_scheduled_run_and_a_capped_list_says_it_is_capped.py',
        pins=('apps/assistant/core/tools/meta',),
        runs_when=(
            'apps/assistant/core/tools/meta/**',
            'apps/assistant/core/changes.py',
            'apps/assistant/workspace/gateway_automations.json',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/meta/whats_changed.py',
            old='    return _scheduled_runs_before(schedule, now, 2)[1].astimezone(timezone.utc)',
            new='    return _scheduled_runs_before(schedule, now, 2)[0].astimezone(timezone.utc)',
            why="the window opens at the latest scheduled run instead of the one before it, so Tuesday's brief looks back thirty seconds and the previous-run cases go red",
        ),
    ),
    Row(
        test='apps/assistant/core/tools/meta/tests/test_a_tool_string_naming_its_own_failure_is_typed_never_ok.py',
        pins=('apps/assistant/core/tools/meta',),
        runs_when=(
            'apps/assistant/core/tools/meta/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/meta/result.py',
            old='    lead = _own_failure_lead(tool).match(text.lstrip())',
            new='    lead = None',
            why="coerce wraps every plain string as OK again, so 'gh issue list failed' and 'db_query tool not configured' are typed OK and the failure cases go red",
        ),
    ),
    Row(
        test='apps/assistant/core/tools/meta/tests/test_counts_new_pods_apart_from_in_place_restarts_and_shows_the_window_before.py',
        pins=('apps/assistant/core/tools/meta',),
        runs_when=(
            'apps/assistant/core/tools/meta/**',
            'apps/assistant/core/state/pod_boots.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/meta/stack_status.py',
            old='    in_place = sum(1 for start in starts if start["in_place"])',
            new='    in_place = 0',
            why='every start counts as a new pod again, so this week reads 5 new and 0 in place and the split assertion goes red',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/meta/tests/test_stack_status_says_vm_containers_are_outside_its_count.py',
        pins=('apps/assistant/core/tools/meta',),
        runs_when=(
            'apps/assistant/core/tools/meta/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/meta/stack_status.py',
            old='    sections = [headline, _SCOPE] if not stale else [headline, _SCOPE, stale]',
            new='    sections = [headline] if not stale else [headline, stale]',
            why='the answer goes back to a bare ALL UP that reads as the whole stack, so the harness_container_up assertion goes red',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/observability/tests/test_a_metric_name_prometheus_does_not_know_is_not_read_as_empty.py',
        pins=('apps/assistant/core/tools/observability',),
        runs_when=(
            'apps/assistant/core/tools/observability/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/observability/prom_query.py',
            old='    unknown = [name for name in names if name not in known]',
            new='    unknown = []',
            why='the name check never finds an unknown metric, so a guessed name comes back as an OK empty vector and the refusal case goes red',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/observability/tests/test_a_wrong_metric_guess_is_pointed_at_the_metric_sharing_its_subject.py',
        pins=('apps/assistant/core/tools/observability',),
        runs_when=(
            'apps/assistant/core/tools/observability/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/observability/prom_query.py',
            old='    ranked = [candidate for _, _, candidate in shared] + spelled\n',
            new='    ranked = spelled\n',
            why='Spelling alone names the ops_secret metrics for the drill guess, the old hint.',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/team/tests/test_a_brief_cannot_say_nothing_is_broken_while_a_page_it_sent_is_still_firing.py',
        pins=('apps/assistant/core/tools/team',),
        runs_when=(
            'apps/assistant/core/tools/team/**',
            'apps/assistant/core/state/alerts.py',
            'apps/assistant/core/state/worklist.py',
            'apps/assistant/core/claims.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/team/message_teammate.py',
            old='    all_clear = _all_clear_refusal(message, _claims)\n',
            new='    all_clear = None\n',
            why='Without the check the fixture brief goes out over a page still firing, which is the older message_teammate.',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/team/tests/test_a_message_citing_an_issue_no_door_answer_or_carrying_tool_output_or_is_refused_and_never_sent.py',
        pins=('apps/assistant/core/tools/team',),
        runs_when=(
            'apps/assistant/core/tools/team/**',
            'apps/assistant/gates/mcp.py',
            'apps/assistant/core/outbound.py',
            'apps/assistant/core/claims.py',
            'apps/assistant/core/signal_text.py',
            'apps/assistant/core/state/message_evidence.py',
        ),
        proved_by=Break(
            file='apps/assistant/gates/mcp.py',
            old='            outcome.ok\n            and name != write_tools.MESSAGE_TEAMMATE\n',
            new='            not outcome.ok\n            and name != write_tools.MESSAGE_TEAMMATE\n',
            why='a door that keeps only its failed answers backs no issue, so the honest #47 message is refused',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/team/tests/test_a_message_over_the_word_cap_is_refused_and_never_sent.py',
        pins=('apps/assistant/core/tools/team',),
        runs_when=(
            'apps/assistant/core/tools/team/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/team/message_teammate.py',
            old='    words = len(message.split())',
            new='    words = len(message)',
            why='the cap counts characters instead of words, so a draft of 125 words is under a reading of 40 that was never the rule and the refusal never fires',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/team/tests/test_a_send_that_lists_a_worklist_item_is_counted_as_a_telling_of_it_even_when_it_names_no_issue_number.py',
        pins=('apps/assistant/core/tools/team',),
        runs_when=(
            'apps/assistant/core/tools/team/**',
            'apps/assistant/core/state/reported_items.py',
            'apps/assistant/core/state/worklist.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/team/message_teammate.py',
            old='        if int(item["id"]) in listed_ids\n        or mentioned & {\n',
            new='        if mentioned & {\n',
            why='the listed id no longer matches, so the chase is not counted and the ledger stays at 1',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/team/tests/test_a_worklist_item_named_by_its_bare_issue_number_is_still_recognised_as_already_told.py',
        pins=('apps/assistant/core/tools/team',),
        runs_when=(
            'apps/assistant/core/tools/team/**',
            'apps/assistant/core/state/reported_items.py',
            'apps/assistant/core/state/worklist.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/team/message_teammate.py',
            old='    mentioned |= {match.group(1) for match in _BARE_NUMBER_RE.finditer(message)}\n',
            new='',
            why="without the bare-number match 'catering 47' names no item, so the second ask is sent",
        ),
    ),
    Row(
        test='apps/assistant/core/tools/team/tests/test_an_item_already_told_and_unmoved_is_not_told_again.py',
        pins=('apps/assistant/core/tools/team',),
        runs_when=(
            'apps/assistant/core/tools/team/**',
            'apps/assistant/core/state/reported_items.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/team/message_teammate.py',
            old='    their_items = _their_items_in(person, message, _listed_ids(tool_input))',
            new='    their_items = _their_items_in(person, message, _listed_ids(tool_input))\n    _state.reported_items.mark_reported(_candidates_for(their_items))',
            why='the items are marked as told BEFORE the split instead of after the send, so the first telling is recorded and then refuses itself and nothing is ever sent',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/tests/test_the_door_tells_the_model_which_language_each_teammate_reads_where_it_writes_the_message.py',
        pins=('apps/assistant/core/tools',),
        runs_when=(
            'apps/assistant/core/tools/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/gateway_surface.py',
            old='        _with_recipient_languages(_with_requester(definition))\n',
            new='        _with_requester(definition)\n',
            why="the door serves message_teammate without the readers' languages, so 'the owner reads English' is missing and case one goes red",
        ),
    ),
    Row(
        test='apps/assistant/gates/tests/test_a_page_triage_ties_to_a_worklist_item_reaches_the_relay_feed_as_concerning_that_item.py',
        pins=('apps/assistant/gates',),
        runs_when=(
            'apps/assistant/gates/**',
            'apps/assistant/core/**',
            'apps/assistant/watch/chat_relay.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/page_hold.py',
            old='    _outbound.remember_sent("", text, worklist_items=_items_of(due, sent_ids))',
            new='    _outbound.remember_sent("", text)',
            why="the release no longer writes the held page's items onto the chat turn, so the page about item 36 reaches the relay concerning nothing",
        ),
    ),
    Row(
        test='apps/assistant/gates/tests/test_a_patrol_question_reaches_the_relay_feed_as_concerning_the_worklist_item_its_pass_opened.py',
        pins=('apps/assistant/gates',),
        runs_when=(
            'apps/assistant/gates/**',
            'apps/assistant/core/**',
            'apps/assistant/watch/chat_relay.py',
        ),
        proved_by=Break(
            file='apps/assistant/gates/app.py',
            old='            "", text, loop="patrol", worklist_items=line.worklist_items',
            new='            "", text, loop="patrol"',
            why='the route remembers the patrol line without its items, so the question reaches the relay concerning nothing',
        ),
    ),
    Row(
        test='apps/assistant/gates/tests/test_alerts_of_one_shared_scrape_path_in_an_envelope_are_triaged_once_held_as_one_page_and_all_read_delivered_when_it_lands.py',
        pins=('apps/assistant/gates', 'apps/assistant/core',),
        runs_when=(
            'apps/assistant/gates/**',
            'apps/assistant/core/triage.py',
            'apps/assistant/core/page_hold.py',
            'apps/assistant/core/state/page_hold.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/triage.py',
            old='    via = alert.labels.get(_SHARED_PATH_LABEL)',
            new='    via = None  # every alert its own cause',
            why='Grouping ignores the shared-path label, the older pod, so the tunnel envelope is seven model calls and seven held pages and `len(pod.calls) == 2` fails.',
        ),
    ),
    Row(
        test='apps/assistant/tests/test_a_calendar_receipt_says_what_the_server_did.py',
        pins=('apps/assistant',),
        runs_when=(
            'apps/assistant/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/agenda/agenda_act.py',
            old='            return cal, f"{uid}.ics", _own_event_etag(cal, uid)',
            new='            return cal, f"{uid}.ics", None',
            why='The direct-GET lookup hands back no etag again, so the move goes out as `If-Match: *`, the fake iCloud answers 412, and `test_a_move_of_assistants_own_icloud_event_quotes_its_real_etag_and_lands` fails on `answer.startswith("moved ")`.',
        ),
    ),
    Row(
        test='apps/assistant/tests/test_a_correction_can_take_the_call_link_off_a_meeting.py',
        pins=('apps/assistant',),
        runs_when=(
            'apps/assistant/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/agenda/caldav.py',
            old='        if name in removed or (name == "DURATION" and "DTEND" in wanted):',
            new='        if name == "DURATION" and "DTEND" in wanted:',
            why='The splice ignores its drop list, so the LOCATION line survives the update and `test_clearing_the_location_takes_the_call_link_off_and_nobody_is_reminded_with_it` fails on "the call link is still on the event".',
        ),
    ),
    Row(
        test='apps/assistant/tests/test_a_repeating_series_that_runs_out_is_named_in_the_agenda.py',
        pins=('apps/assistant',),
        runs_when=(
            'apps/assistant/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/agenda/agenda_view.py',
            old='    look_from = _shifted(start, -_SERIES_LOOK_BACK)',
            new='    look_from = start',
            why='Without the look back, a series that ended before the window is never read, so `test_a_series_that_ended_before_the_window_is_named` fails.',
        ),
    ),
    Row(
        test='apps/assistant/tests/test_agenda_view_never_lists_an_event_outside_the_window_it_was_asked_for.py',
        pins=('apps/assistant',),
        runs_when=(
            'apps/assistant/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/agenda/agenda_view.py',
            old='    return caldav.in_window(caldav.expand_all(events, start, end), start, end)',
            new='    return events',
            why="With `agenda_view` passing the server's answer through untouched, the yearly master is printed as 'Thu 22 Oct, all day' and `test_yesterdays_birthday_is_not_in_todays_agenda` fails.",
        ),
    ),
    Row(
        test='apps/assistant/tests/test_the_gateway_fragment_compacts_chat_early_and_keeps_native_memory_on_with_a_pinned_provider.py',
        pins=('apps/assistant/workspace',),
        runs_when=(
            'apps/assistant/workspace/**',
        ),
        proved_by=Break(
            file='apps/assistant/workspace/gateway_config_patch.json',
            old='"contextTokens": 100000',
            new='"contextTokens": 1000000',
            why="It puts the cap back at Opus 5's native 1M window, so compaction waits for 980k again and the trigger assertion fails.",
        ),
    ),
    Row(
        test='apps/assistant/tests/test_the_gateway_fragment_gives_each_signal_sender_their_own_session.py',
        pins=('apps/assistant',),
        runs_when=(
            'apps/assistant/**',
        ),
        proved_by=Break(
            file='apps/assistant/workspace/gateway_config_patch.json',
            old='    "dmScope": "per-channel-peer"',
            new='    "dmScope": "main"',
            why='the fragment puts every Signal DM back in one shared session, so the case goes red',
        ),
    ),
    Row(
        test='apps/assistant/watch/tests/test_every_relayed_send_is_queued_as_a_system_event_the_model_reads_because_chat_inject_alone_is_transcript_only.py',
        pins=('apps/assistant/watch',),
        runs_when=(
            'apps/assistant/watch/**',
        ),
        proved_by=Break(
            file='apps/assistant/watch/chat_relay.py',
            old='    return enqueue(key, text, run) and inject(key, text, run)',
            new='    return inject(key, text, run)',
            why='the relay only injects into the transcript, no system event is queued for the model, and the first case goes red',
        ),
    ),
    Row(
        test='apps/assistant/watch/tests/test_the_chat_relay_stays_quiet_through_a_pod_roll_and_still_pages_when_the_roll_or_the_relay_is_stuck.py',
        pins=('apps/assistant/watch',),
        runs_when=(
            'apps/assistant/watch/**',
        ),
        proved_by=Break(
            file='apps/assistant/watch/chat_relay.py',
            old='        limit = FAILS_BEFORE_LOUD_POD_NOT_SERVING if isinstance(exc, PodNotServing) else FAILS_BEFORE_LOUD',
            new='        limit = FAILS_BEFORE_LOUD',
            why='a pod not serving the feed gets the ten-minute limit again, so pass 5 of a roll pages and the first case goes red',
        ),
    ),
    Row(
        test='apps/assistant/watch/tests/test_the_relay_hands_each_send_to_its_recipients_own_session.py',
        pins=('apps/assistant/watch',),
        runs_when=(
            'apps/assistant/watch/**',
        ),
        proved_by=Break(
            file='apps/assistant/watch/chat_relay.py',
            old='    return f"{PEER_SESSION_PREFIX}{address}" if address else SHARED_SESSION_KEY',
            new='    return SHARED_SESSION_KEY',
            why="every note goes to the shared session, so no note reaches its recipient's key and the first case goes red",
        ),
    ),
    Row(
        test='apps/assistant/watch/tests/test_the_relay_injects_each_outside_send_once_naming_recipient_time_and_road_and_a_failed_inject_is_retried.py',
        pins=('apps/assistant/watch',),
        runs_when=(
            'apps/assistant/watch/**',
        ),
        proved_by=Break(
            file='apps/assistant/watch/chat_relay.py',
            old='            raise RuntimeError(f"send {send[\'id\']} to {send[\'recipient\']} was not injected; it is retried next pass")',
            new='            log.warning("send %s was not injected", send["id"])',
            why='a refused inject is logged and passed over, the cursor moves past it, and the page is never injected, so the first case goes red',
        ),
    ),
    Row(
        test='apps/assistant/workspace/tests/test_the_gateway_deny_list_never_takes_away_a_tool_the_door_the_journal_or_the_mail_box_serves.py',
        pins=('apps/assistant/workspace',),
        runs_when=(
            'apps/assistant/workspace/**',
            'apps/assistant/core/tools/**',
        ),
        proved_by=Break(
            file='apps/assistant/workspace/gateway_config_patch.json',
            old='      "apply_patch",\n',
            new='      "assistant-tools__*",\n      "apply_patch",\n',
            why="a glob over the door's server prefix joins the deny list, so every door tool is reported taken away",
        ),
    ),
    Row(
        test='apps/assistant/workspace/tests/test_the_gateway_is_told_to_save_a_mail_reply_with_draft_mail_only_when_draft_mail_is_wired_in.py',
        pins=('apps/assistant/workspace',),
        runs_when=(
            'apps/assistant/workspace/**',
        ),
        proved_by=Break(
            file='apps/assistant/workspace/capabilities.py',
            old='        "here as well as above."\n        + _draft_sentence(servers)',
            new='        "here as well as above."',
            why="the VM section names draft_mail and never says drafting the reply is the assistant's step, so the first case goes red",
        ),
    ),
    Row(
        test='apps/assistant/workspace/tests/test_the_morning_brief_never_calls_a_quiet_day_fine.py',
        pins=('apps/assistant/workspace',),
        runs_when=(
            'apps/assistant/workspace/**',
        ),
        proved_by=Break(
            file='apps/assistant/workspace/gateway_automations.json',
            old="If none of this applies, send exactly 'Nothing needs you today.'",
            new='If there is nothing, say so in one line: that is a good report, not a lazy one.',
            why="A free-form quiet-day line lets the brief claim a clear calendar over an event.",
        ),
    ),
    Row(
        test='apps/notulen/tests/test_a_notulen_gpu_job_kubernetes_failed_fails_its_and_a_running_or_finished_one_does_not.py',
        pins=('apps/notulen',),
        runs_when=(
            'apps/notulen/**',
        ),
        proved_by=Break(
            file='apps/notulen/app/core/sessions/dead_gpu_jobs.py',
            old='if job_id and cond.type == "Failed" and cond.status == "True":',
            new='if job_id and cond.type in ("Failed", "Complete") and cond.status == "True":',
            why='A finished Job reads as failed, so the watch would fail a meeting whose minutes are being committed, and `test_only_the_job_kubernetes_failed_is_reported_with_its_reason` gets the finished job id back beside the dead one.',
        ),
    ),
    Row(
        test='apps/notulen/tests/test_a_notulen_names_each_person_once_and_caps_the_speakers.py',
        pins=('apps/notulen',),
        runs_when=(
            'apps/notulen/**',
        ),
        proved_by=Break(
            file='apps/notulen/entrypoints/worker.py',
            old='        name for name, _ in sorted(spoken.items(), key=lambda pair: -pair[1])[:keep]',
            new='        name for name, _ in sorted(spoken.items(), key=lambda pair: pair[1])[:keep]',
            why='The fold keeps the voices that speak LEAST, so the two one-second strays survive and the two real speakers are handed to them, and `test_two_people_leave_two_voices_in_the_transcript` gets `stray-1`/`stray-2` where it asserts `A` and `B`.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_every_house_rule_reaches_assistants_voice.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/voice.py',
            old='{_house_rules()}',
            new='- Write plainly and keep it short.',
            why='the render stops reading .claude/soul.md and carries a paraphrase again, so every house rule is missing from it',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/meta/tests/test_lists_a_page_held_overnight_with_its_local_dropped_ones_too.py',
        pins=('apps/assistant/core/tools/meta',),
        runs_when=(
            'apps/assistant/core/tools/meta/**',
            'apps/assistant/core/state/page_hold.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/meta/my_actions.py',
            old='    dropped = _dropped(about)\n',
            new='    dropped = []\n',
            why='my_actions stops listing the pages dropped overnight, so the brief cannot say an outage ended in the night.',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/meta/tests/test_shows_a_message_assistant_sent_from_outside_the_in_its_own_once.py',
        pins=('apps/assistant/core/tools/meta',),
        runs_when=(
            'apps/assistant/core/tools/meta/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/meta/my_actions.py',
            old='        actions = actions + _sent_entries(team_messages)',
            new='        actions = actions + []',
            why="my_actions reads assistant_actions alone again, so the brief's later question is not in the answer and `test_a_question_sent_from_outside_the_chat_is_shown_in_its_own_words` goes red",
        ),
    ),
    Row(
        test='apps/assistant/core/tools/team/tests/test_a_question_asked_again_after_assistant_only_reworded_its_own_finding_is_refused.py',
        pins=('apps/assistant/core/tools/team',),
        runs_when=(
            'apps/assistant/core/tools/team/**',
            'apps/assistant/core/tools/meta/manage_worklist.py',
            'apps/assistant/core/state/reported_items.py',
            'apps/assistant/core/state/worklist.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/team/message_teammate.py',
            old='                "open", _title_issue_facts(str(item.get("title", "")))\n',
            new='                "open", str(item.get("last_finding") or "")\n',
            why="fingerprinted on the assistant's own reworded finding, every morning reads as news and the repeat asks are sent",
        ),
    ),
    Row(
        test='apps/assistant/core/tools/tests/test_the_tool_definitions_stay_under_the_prompt_budget_assistant_pays_on_every_call.py',
        pins=('apps/assistant/core/tools',),
        runs_when=(
            'apps/assistant/core/tools/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/gateway_surface.py',
            old='    return read_definitions() + write_definitions()\n',
            new='    return (read_definitions() + write_definitions()) * 2\n',
            why='every definition is served twice, so the catalogue goes over its character budget',
        ),
    ),
    Row(
        test='apps/assistant/gates/tests/test_a_write_nobody_asked_for_is_booked_to_assistant_and_never_borrows_the_rights.py',
        pins=('apps/assistant/gates',),
        runs_when=(
            'apps/assistant/gates/**',
            'apps/assistant/core/tools/write_tools.py',
            'apps/assistant/core/tools/team/message_teammate.py',
            'apps/assistant/core/tools/meta/manage_worklist.py',
        ),
        proved_by=Break(
            file='apps/assistant/gates/mcp.py',
            old='    write_tools.GITHUB_ACT,\n',
            new='',
            why='github_act leaves the tools the assistant may book to itself, so a board write under the assistant is refused and the reach case goes red',
        ),
    ),
    Row(
        test='apps/assistant/shared/tests/test_a_page_leaves_for_a_person_with_every_utc_time_written_on_local_on_both_sides_of_the_october_change.py',
        pins=('apps/assistant/shared',),
        runs_when=(
            'apps/assistant/shared/**',
        ),
        proved_by=Break(
            file='apps/assistant/shared/local_time.py',
            old='    local = moment.astimezone(zone)\n',
            new='    local = moment.astimezone(timezone(timedelta(hours=2), "CEST"))\n',
            why='The conversion uses the summer offset every day of the year, so a time after 25 October 2026 comes out an hour late and still says CEST, which the winter and change-day cases catch.',
        ),
    ),
    Row(
        test='apps/assistant/tests/test_a_message_assistant_cannot_back_never_reaches_a_phone.py',
        pins=('apps/assistant',),
        runs_when=(
            'apps/assistant/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/claims.py',
            old='        if landed >= _claimed_count(answer):',
            new='        if landed:',
            why='It drops the receipt COUNT from the write-claim guard back to "any backing write landed", so `unbacked_write_claim("Done, both removed.", [...], [agenda_act], ...)` returns None with one receipt and `test_one_receipt_cannot_back_a_claim_about_two_writes`\'s first assertion ("a claim about two removals passed on one successful write", asserting the nudge `is not None`) fails.',
        ),
    ),
    Row(
        test='apps/assistant/tests/test_a_scope_that_writes_to_the_team_calendar_is_held_to_the_team_calendar_rule.py',
        pins=('apps/assistant',),
        runs_when=(
            'apps/assistant/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/agenda/agenda_act.py',
            old='    return team is not None and scope.write is not None and scope.write.url == team.url',
            new='    return scope.name == calendars.TEAM_KEY',
            why='Judged by the scope\'s name again, a teammate\'s scope that writes to the team calendar takes the two-person add, so `test_a_two_person_add_on_a_scope_that_writes_to_the_team_calendar_is_refused` fails on "a two-person call reached the team calendar".',
        ),
    ),
    Row(
        test='apps/assistant/tests/test_a_title_assistant_writes_never_carries_an_html_entity.py',
        pins=('apps/assistant',),
        runs_when=(
            'apps/assistant/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/agenda/caldav.py',
            old='        html.unescape(value).replace(',
            new='        value.replace(',
            why="With the entity decoding gone from `ical_text`, the added and updated titles store 'the owner &amp\\; Sam' and `test_an_added_meeting_stores_the_ampersand_not_the_entity` fails.",
        ),
    ),
    Row(
        test='apps/assistant/workspace/tests/test_every_tool_the_gateway_config_wires_in_is_named_in_assistants_capability_block.py',
        pins=('apps/assistant/workspace',),
        runs_when=(
            'apps/assistant/workspace/**',
            'apps/assistant/core/tools/gateway_surface.py',
        ),
        proved_by=Break(
            file='apps/assistant/workspace/capabilities.py',
            old='    if servers:\n        sections.append(_vm_section(servers))\n',
            new='',
            why="Naming only the door's tools would tell the gateway's assistant it has no journal reader while journal_read sits in its tool list.",
        ),
    ),
    Row(
        test='apps/assistant/core/state/tests/test_a_worklist_item_a_person_asked_for_never_renders_as_not_news.py',
        pins=('apps/assistant/core/state',),
        runs_when=(
            'apps/assistant/core/state/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/state/worklist.py',
            old='    if item["kind"] == "look_into" or owner != "assistant":\n',
            new='    if item["kind"] == "look_into":\n',
            why='without the owner check an old item a person asked for reads as not news again',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/meta/tests/test_deploy_status_names_the_zone_of_every_time_it_prints.py',
        pins=('apps/assistant/core/tools/meta',),
        runs_when=(
            'apps/assistant/core/tools/meta/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/meta/deploy_status.py',
            old='"at": _utc_stamp(_parse_stamp(newest)),',
            new='"at": str(newest)[:16],',
            why='the newest time is cut to a bare clock, so a printed time carries no zone',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/observability/tests/test_a_vm_log_query_reads_the_shippers_data_source_and_says_which_box_and_container_each_line_came_from.py',
        pins=('apps/assistant/core/tools/observability',),
        runs_when=(
            'apps/assistant/core/tools/observability/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/observability/loki_query.py',
            old='f"{stamp} [{label}] {str(message).strip()}"',
            new='f"{stamp} {str(message).strip()}"',
            why='a line no longer says which box and container it came from',
        ),
    ),
    Row(
        test='apps/assistant/tests/test_the_gateway_fragment_pins_the_user_timezone.py',
        pins=('apps/assistant',),
        runs_when=(
            'apps/assistant/**',
        ),
        proved_by=Break(
            file='apps/assistant/workspace/gateway_config_patch.json',
            old='"userTimezone": "@ASSISTANT_TIMEZONE@",',
            new='"userTimezone": "UTC",',
            why='the gateway is back on UTC whatever the owner set, so the userTimezone assertion fails',
        ),
    ),
    Row(
        test='apps/assistant/workspace/tests/test_user_md_tells_the_gateway_each_teammates_pronouns_and_forbids_guessing.py',
        pins=('apps/assistant/workspace',),
        runs_when=(
            'apps/assistant/workspace/**',
            'apps/assistant/core/people.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/people.py',
            old='use their name or "\n        "neutral wording, never guess he or she."',
            new='use he/him or "\n        "neutral wording."',
            why='the block hands the gateway a guessed pronoun, so the no-guess assertions fail',
        ),
    ),
    Row(
        test='apps/notulen/tests/test_a_notulen_never_names_a_speaker_the_transcript_does_not_place.py',
        pins=('apps/notulen',),
        runs_when=(
            'apps/notulen/**',
        ),
        proved_by=Break(
            file='apps/notulen/entrypoints/worker.py',
            old='evidence keep the label itself everywhere ("Speaker 1", "Speaker 2"), including',
            new='evidence keep the label itself everywhere, including',
            why='the GPU worker loses the label to fall back on, so the twins disagree and the fallback assertion fails',
        ),
    ),
    Row(
        test='infra/gpu-jobs/gpu_jobs/tests/test_a_gpu_job_can_only_land_on_the_pool_it_is_meant_for.py',
        pins=('infra/gpu-jobs/gpu_jobs/config',),
        runs_when=(
            'infra/gpu-jobs/gpu_jobs/**',
        ),
        proved_by=Break(
            file='infra/gpu-jobs/gpu_jobs/config/notulen_pool.py',
            old='NOTULEN_POOL_TAINT_VALUE = "notulen"',
            new='NOTULEN_POOL_TAINT_VALUE = "test"',
            why='The notulen Job\'s toleration is built from this constant (creators/notulen_tolerations.py), so with "test" it no longer tolerates the notulen node\'s `workload=notulen` NoSchedule taint, `_where_it_can_land` returns `[]`, and `test_the_notulen_job_fits_the_notulen_pool_and_no_other`\'s `assert _where_it_can_land(pod) == ["notulen-gpu", "notulen-gpu-z1"]` fails.',
        ),
    ),
    Row(
        test='apps/assistant/core/tests/test_a_page_and_a_pen_message_are_remembered_on_the_same_local_clock_owner_read_them_on.py',
        pins=('apps/assistant/core',),
        runs_when=(
            'apps/assistant/core/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/page_hold.py',
            old='    text = _local_time.in_local_time(text, moment)\n',
            new='',
            why='the released page is sent and remembered in UTC, so the local-time assertion fails',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/team/tests/test_an_item_assistant_booked_to_itself_is_still_told_once_per_reader.py',
        pins=('apps/assistant/core/tools/team',),
        runs_when=(
            'apps/assistant/core/tools/team/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/team/message_teammate.py',
            old='in {person.strip().lower(), _ASSISTANT_OWNER}',
            new='in {person.strip().lower()}',
            why='an item the assistant booked to itself is never matched, so the repeat ask is sent',
        ),
    ),
    Row(
        test='apps/assistant/gates/tests/test_a_patrol_the_minutes_report_and_a_security_page_leave_on_local_and_the_chat_remembers_the_text_that_was_sent.py',
        pins=('apps/assistant/gates',),
        runs_when=(
            'apps/assistant/gates/**',
        ),
        proved_by=Break(
            file='apps/assistant/gates/app.py',
            old='text = local_time.in_local_time(line.text)',
            new='text = line.text',
            why='the patrol line is sent as the model wrote it, so the captured text still says UTC',
        ),
    ),
    Row(
        test='apps/assistant/tests/test_a_meeting_between_two_people_never_lands_on_the_team_calendar.py',
        pins=('apps/assistant',),
        runs_when=(
            'apps/assistant/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/agenda/agenda_act.py',
            old='if _writes_to_team_calendar(scope) and not tool_input.get("team_event"):',
            new='if _writes_to_team_calendar(scope) and tool_input.get("team_event") is False:',
            why='the team calendar check only fires on an explicit false, so a two-person call lands on the team calendar',
        ),
    ),
    Row(
        test='apps/assistant/workspace/tests/test_every_scheduled_report_books_its_writes_to_assistant.py',
        pins=('apps/assistant/workspace',),
        runs_when=(
            'apps/assistant/workspace/**',
        ),
        proved_by=Break(
            file='apps/assistant/workspace/gateway_automations.json',
            old='say so in one line. Pass worklist_items for every worklist item the message is about. Nobody asked for this run: every write it makes, the message included, takes requested_by \\"@ASSISTANT_NAME@\\"."',
            new='say so in one line. Pass worklist_items for every worklist item the message is about."',
            why="the morning brief no longer says its writes are the assistant's own, so the booking assertion fails",
        ),
    ),
    Row(
        test='apps/assistant/workspace/tests/test_the_fragment_fills_the_owners_settings_and_never_bakes_a_secret.py',
        pins=('apps/assistant/workspace',),
        runs_when=(
            'apps/assistant/workspace/**',
        ),
        proved_by=Break(
            file='apps/assistant/workspace/fragment.py',
            old='"ASSISTANT_TIMEZONE": (env.get("ASSISTANT_TIMEZONE") or "").strip() or "UTC",',
            new='"ASSISTANT_TIMEZONE": "UTC",',
            why="the owner's zone is ignored, so the settings assertion fails",
        ),
    ),
    Row(
        test='apps/documents/tests/test_load_design.py',
        pins=('apps/documents',),
        runs_when=(
            'apps/documents/**',
        ),
        proved_by=Break(
            file='apps/documents/load_design.py',
            old='        name: value.strip()',
            new='        name: value',
            why='token values keep the whitespace around them, so the trimmed-value case fails',
        ),
    ),
    Row(
        test='apps/documents/tests/test_render_html.py',
        pins=('apps/documents',),
        runs_when=(
            'apps/documents/**',
        ),
        proved_by=Break(
            file='apps/documents/render_html.py',
            old='f"    --{name}: {value};"',
            new='f"    {name}: {value};"',
            why='the tokens reach the HTML without their dashes, so they are not CSS variables',
        ),
    ),
    Row(
        test='apps/documents/tests/test_pdf_invoice.py',
        pins=('apps/documents',),
        runs_when=(
            'apps/documents/**',
        ),
        proved_by=Break(
            file='apps/documents/make_pdf.py',
            old='f"sudo apt-get install -y {_APT_PACKAGES}"',
            new='"sudo apt-get install -y the missing libraries"',
            why='the error no longer names the apt packages, so the missing-weasyprint case fails',
        ),
    ),
    Row(
        test='infra/observability/tests/test_an_alert_pages_once_through_the_assistant_or_signal_direct_and_a_silent_source_pages_after_its_deadline.py',
        pins=('infra/observability/alerts',),
        runs_when=(
            'infra/observability/**',
        ),
        proved_by=Break(
            file='infra/observability/alerts/notify.py',
            old='if direct or not os.environ.get("OPENCLAW_WEBHOOK_SECRET", "").strip():',
            new='if not os.environ.get("OPENCLAW_WEBHOOK_SECRET", "").strip():',
            why='a deadman page goes through the assistant it is reporting on, so the direct-road case fails',
        ),
    ),
    Row(
        test='infra/observability/tests/test_the_relay_hands_alerts_to_the_assistant_and_speaks_only_when_it_is_down.py',
        pins=('infra/observability/alert_relay',),
        runs_when=(
            'infra/observability/**',
        ),
        proved_by=Break(
            file='infra/observability/alert_relay/deduper.py',
            old='DEDUPE_WINDOW_S = 1800',
            new='DEDUPE_WINDOW_S = 0',
            why='a repeated group is sent again at once, so the half-hour case fails',
        ),
    ),
    Row(
        test="apps/notulen/tests/test_a_talk_webhook_whose_signature_does_not_match_the_bot_secret_is_refused.py",
        pins=("apps/notulen",),
        runs_when=(
            "apps/notulen/**",
        ),
        proved_by=Break(
            file="apps/notulen/app/entrypoints/talk_routes.py",
            old="secret.encode(), (random_header.encode() + raw_body), hashlib.sha256",
            new="secret.encode(), raw_body, hashlib.sha256",
            why="the correctly signed event is refused, so the first status assertion trips",
        ),
    ),
    Row(
        test="apps/notulen/tests/test_a_talk_call_that_is_not_recordable_yet_is_retried_without_paging_and_a_real_refusal_pages_once.py",
        pins=("apps/notulen",),
        runs_when=(
            "apps/notulen/**",
        ),
        proved_by=Break(
            file="apps/notulen/app/core/sessions/recording_guard.py",
            old='return isinstance(data, dict) and data.get("error") == "call"',
            new='return isinstance(data, dict) and data.get("error") == "not-the-race"',
            why="the race reads as a real error, so the first call pages and stops after one post",
        ),
    ),
    Row(
        test='infra/gpu-jobs/gpu_jobs/tests/test_a_notulen_job_waits_for_a_gpu_in_any_zone_without_a_deadline_and_its_pod_carries_no_credential_as_a_value.py',
        pins=('infra/gpu-jobs/gpu_jobs/creators',),
        runs_when=(
            'infra/gpu-jobs/gpu_jobs/**',
        ),
        proved_by=Break(
            file='infra/gpu-jobs/gpu_jobs/creators/create_notulen_job.py',
            old='            ttl_seconds_after_finished=300,  # clean up 5 min after done\n',
            new='            active_deadline_seconds=14400,\n            ttl_seconds_after_finished=300,  # clean up 5 min after done\n',
            why='The Job-level 4 h deadline comes back, the older manifest, so the Job\'s clock counts the wait for a GPU node and `"activeDeadlineSeconds" not in manifest["spec"]` fails.',
        ),
    ),
    Row(
        test="infra/media/tests/test_the_recorder_patch_swaps_the_sink_index_for_its_name_once_and_stops_when_upstream_moved_the_line.py",
        pins=("infra/media",),
        runs_when=(
            "infra/media/**",
        ),
        proved_by=Break(
            file="infra/media/patches/recording_pulse_sink_name.py",
            old='if "_pulseNameLookup" in src:',
            new='if "_pulseNameLookup" in src or True:',
            why="every file reads as already patched, so the upstream line survives the first run",
        ),
    ),
    Row(
        test='infra/auto-deploy/tests/test_a_commit_gate_run_refuses_a_commit_whose_suite_is_not_the_cycles.py',
        pins=('infra/auto-deploy/commit_gate',),
        runs_when=(
            'infra/auto-deploy/commit_gate/**',
            'infra/auto-deploy/tests/**',
        ),
        proved_by=Break(
            file='infra/auto-deploy/commit_gate/run_one.sh',
            old='TREE_IGNORES="$(git -C "$REPO" show "$SHA:$GATE_STEP_PATH" 2>/dev/null | _cg_ignore_flags)"',
            new='TREE_IGNORES="$(_cg_ignore_flags < "$REPO/$GATE_STEP_PATH" 2>/dev/null)"',
            why="the commit's list is read from the clone too, so the two never disagree and a run whose suite is not the cycle's goes on",
        ),
    ),
    Row(
        test='infra/auto-deploy/tests/test_a_deploy_cycle_runs_its_steps_once_in_order_and_every_gate_verdict_reaches_the_arm_and_the_alert_meant_for_it.py',
        pins=('infra/auto-deploy',),
        runs_when=(
            'infra/auto-deploy/compose_fragments.py',
            'infra/auto-deploy/tests/**',
            'infra/auto-deploy/steps/doors.sh',
            'infra/auto-deploy/notify.py',
            'infra/auto-deploy/steps/40-gate.sh',
            'infra/auto-deploy/steps/eject_body.sh',
            'infra/auto-deploy/auto-deploy.sh',
            'infra/auto-deploy/steps/**',
            'infra/auto-deploy/steps/80-units.sh',
            'infra/auto-deploy/**',
        ),
        proved_by=Break(
            file='infra/auto-deploy/steps/40-gate.sh',
            old='    elif [ "$gate_rc" -eq 5 ]; then',
            new='    elif [ "$gate_rc" -eq 55 ]; then',
            why='a run that collected nothing falls into the amber catch-all instead of being red, and the rc=5 case asserts red',
        ),
    ),
    Row(
        test="infra/cluster/pool_fallbacks/tests/test_each_pool_role_tries_its_preferred_pool_then_its_home_never_leaves_its_zone_and_a_pool_no_role_names_still_scales.py",
        pins=("infra/cluster/pool_fallbacks",),
        runs_when=(
        "infra/cluster/pool_fallbacks/**",
        ),
        proved_by=Break(
            file="infra/cluster/pool_fallbacks/_priorities.py",
            old="_STEP * (deepest - spec.rank)",
            new="_STEP * (spec.rank + 1)",
            why="a fallback outranks its preferred pool, so the expander order differs from the hand-written one",
        ),
    ),
    Row(
        test='lib/dashkit/core/tests/test_a_dashboard_serves_its_frontend_reads_the_sso_user_finds_its_database_and_quotes_only_allowed_identifiers.py',
        pins=('lib/dashkit',),
        runs_when=(
            'lib/dashkit/**',
        ),
        proved_by=Break(
            file='lib/dashkit/core/_frontend_static.py',
            old='not str(target).startswith(str(base))\n            or not target.is_file()',
            new='not target.is_file()',
            why='a path that climbs out of the static folder is served, so the traversal case fails',
        ),
    ),
    Row(
        test='tools/gate_scope/tests/test_the_gate_runs_every_test_a_change_can_break_on_a_fresh_graph_in_the_environment_the_audit_checks.py',
        pins=('tools/gate_scope',),
        runs_when=(
            'tools/gate_scope/**',
            '.claude/scripts/gate-scope.py',
            'infra/auto-deploy/steps/40-gate.sh',
        ),
        proved_by=Break(
            file='tools/gate_scope/_graph.py',
            old='                reached.add(importer)\n                frontier.append(importer)',
            new='                reached.add(importer)',
            why='the reverse closure is one hop deep instead of transitive, so a change to core/rules.py no longer selects the report suite that reaches it through report/render.py',
        ),
    ),
    Row(
        test="tools/red_triage/tests/test_a_red_is_the_commits_the_tests_or_the_boxs.py",
        pins=("tools/red_triage",),
        runs_when=(
            "tools/red_triage/**",
        ),
        proved_by=Break(
            file="tools/red_triage/_triage.py",
            old="    old = sorted(still & (good_failing or frozenset()) - new_files)",
            new="    old = sorted(still & (good_failing or frozenset()))",
            why="a test the commit changed reads as old and is quarantined, so the changed-test case fails",
        ),
    ),
)
