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
        test='apps/notulen/tests/test_a_talk_webhook_whose_signature_does_not_match_the_bot_secret_is_refused.py',
        pins=('apps/notulen/app',),
        runs_when=(
            'apps/notulen/**',
        ),
        proved_by=Break(
            file="apps/notulen/app/entrypoints/talk_routes.py",
            old="secret.encode(), (random_header.encode() + raw_body), hashlib.sha256",
            new="secret.encode(), raw_body, hashlib.sha256",
            why="the correctly signed event is refused, so the first status assertion trips",
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
        pins=('infra/observability',),
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
        test='apps/assistant/core/state/tests/test_the_worklist_renders_open_work_as_work_never_as_not_news_moves_only_on_news_and_refuses_a_mute_over_a_critical_alert.py',
        pins=('apps/assistant/core/state',),
        runs_when=(
            'apps/assistant/core/state/**',
            'apps/assistant/core/tools/meta/manage_worklist.py',
            'apps/assistant/core/claims.py',
            'apps/assistant/core/journal.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/state/worklist.py',
            old='        moved = row is None or reported_items.worklist_fingerprint(\n            "open", str(row["last_finding"] or "")\n        ) != reported_items.worklist_fingerprint("open", text)',
            new='        moved = row is None or str(row["last_finding"] or "") != text',
            why='the two findings are compared raw, so the reading stamp patrol puts at the front makes every pass look like movement and the item is rewritten on every pass',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/gh/tests/test_a_gh_read_reaches_the_model_whole_or_as_failed_names_owner_and_filter_and_deletes_nothing.py',
        pins=('apps/assistant/core/tools/gh',),
        runs_when=(
            'apps/assistant/core/tools/gh/**',
            'apps/assistant/core/tools/meta/text.py',
            'apps/assistant/core/changes.py',
            'apps/assistant/core/people.py',
            'apps/assistant/core/tools/write_guard.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/gh/gh_issue_view.py',
            old='        return result.failed(NAME, f"gh issue view failed (rc={overview.returncode}): {overview.stderr.strip()}")',
            new='        return f"gh issue view failed (rc={overview.returncode}): {overview.stderr.strip()}"',
            why='gh_issue_view hands its failure back as a plain string again, so its answer is not a typed FAILED result and the isinstance assertion goes red',
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
        test='apps/assistant/core/tools/meta/tests/test_a_status_or_report_tool_says_what_it_could_not_read_names_each_times_zone_and_shows_held_and_dropped_pages.py',
        pins=('apps/assistant/core/tools/meta',),
        runs_when=(
            'apps/assistant/core/tools/meta/**',
            'apps/assistant/core/tools/write_tools.py',
            'apps/assistant/core/tools/team/message_teammate.py',
            'apps/assistant/core/claims.py',
            'apps/assistant/core/outbound.py',
            'apps/assistant/gates/mcp.py',
            'apps/assistant/core/state/notify_pen.py',
            'apps/assistant/core/state/page_hold.py',
            'apps/assistant/core/tools/team/**',
            'apps/assistant/core/tools/gateway_surface.py',
            'apps/assistant/core/state/reported_items.py',
            'apps/assistant/core/state/worklist.py',
            'apps/assistant/core/state/conn.py',
            'apps/assistant/workspace/capabilities.py',
            'apps/assistant/core/changes.py',
            'apps/assistant/workspace/gateway_automations.json',
            'apps/assistant/core/state/pod_boots.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/meta/result.py',
            old='    lead = _own_failure_lead(tool).match(text.lstrip())',
            new='    lead = None',
            why="coerce wraps every plain string as OK again, so 'gh issue list failed' and 'db_query tool not configured' are typed OK and the failure cases go red",
        ),
    ),
    Row(
        test='apps/assistant/core/tools/observability/tests/test_a_metric_or_log_query_is_never_read_as_empty_by_mistake_and_says_where_each_line_came_from.py',
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
        test='apps/assistant/core/tools/team/tests/test_a_message_to_a_teammate_tells_each_item_once_per_reader_stays_under_the_cap_and_carries_only_what_a_reading_backs.py',
        pins=('apps/assistant/core/tools/team',),
        runs_when=(
            'apps/assistant/core/tools/team/**',
            'apps/assistant/core/state/alerts.py',
            'apps/assistant/core/state/worklist.py',
            'apps/assistant/core/claims.py',
            'apps/assistant/gates/mcp.py',
            'apps/assistant/core/outbound.py',
            'apps/assistant/core/signal_text.py',
            'apps/assistant/core/state/message_evidence.py',
            'apps/assistant/core/tools/meta/manage_worklist.py',
            'apps/assistant/core/state/reported_items.py',
            'apps/assistant/core/**',
            'apps/assistant/watch/chat_relay.py',
        ),
        proved_by=Break(
            file='apps/assistant/core/tools/team/message_teammate.py',
            old='    words = len(message.split())',
            new='    words = len(message)',
            why='the cap counts characters instead of words, so a draft of 125 words is under a reading of 40 that was never the rule and the refusal never fires',
        ),
    ),
    Row(
        test='apps/assistant/core/tools/tests/test_the_tool_definitions_stay_under_the_prompt_budget_and_the_door_names_each_teammates_language.py',
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
        test='apps/assistant/workspace/tests/test_the_gateway_config_fills_the_owners_settings_wires_every_tool_it_names_and_never_bakes_a_secret.py',
        pins=('apps/assistant/workspace',),
        runs_when=(
            'apps/assistant/workspace/**',
            'apps/assistant/core/tools/gateway_surface.py',
            'apps/assistant/core/tools/**',
            'apps/assistant/core/people.py',
            'apps/assistant/**',
        ),
        proved_by=Break(
            file='apps/assistant/workspace/fragment.py',
            old='"ASSISTANT_TIMEZONE": (env.get("ASSISTANT_TIMEZONE") or "").strip() or "UTC",',
            new='"ASSISTANT_TIMEZONE": "UTC",',
            why="the owner's zone is ignored, so the settings assertion fails",
        ),
    ),
    Row(
        test='apps/documents/tests/test_a_document_renders_from_its_design_to_html_and_to_a_real_pdf.py',
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
        test='apps/assistant/tests/test_a_page_reaches_a_person_only_as_news_backed_by_the_assistants_own_reads_on_their_local_clock_and_every_send_is_relayed_once.py',
        pins=('apps/assistant',),
        runs_when=(
            'apps/assistant/core/**',
            'infra/observability/prometheus/rules/*.yml',
            'apps/assistant/gates/**',
            'apps/assistant/watch/chat_relay.py',
            'apps/assistant/core/triage.py',
            'apps/assistant/core/page_hold.py',
            'apps/assistant/core/state/page_hold.py',
            'apps/assistant/core/tools/write_tools.py',
            'apps/assistant/core/tools/team/message_teammate.py',
            'apps/assistant/core/tools/meta/manage_worklist.py',
            'apps/assistant/shared/**',
            'apps/assistant/**',
        ),
        proved_by=Break(
            file='apps/assistant/core/awareness.py',
            old='    return f" [{fingerprint}]"',
            new='    return f" [{fingerprint[:8]}]"',
            why='The awareness row prints an eight-character prefix, so the cover the model copies matches no delivery and `decision == "silent"` fails.',
        ),
    ),
    Row(
        test='apps/assistant/tests/test_the_agenda_lists_only_its_window_keeps_two_person_meetings_off_the_team_calendar_and_says_what_the_server_did.py',
        pins=('apps/assistant/core/tools/agenda',),
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
        test='apps/assistant/watch/tests/test_the_relay_hands_each_outside_send_once_to_its_recipients_own_session_as_an_event_the_model_reads_and_stays_quiet_through_a_pod_roll.py',
        pins=('apps/assistant/watch',),
        runs_when=(
            'apps/assistant/watch/**',
            'apps/assistant/core/**',
            'apps/assistant/watch/chat_relay.py',
        ),
        proved_by=Break(
            file='apps/assistant/watch/chat_relay.py',
            old='    return f"{PEER_SESSION_PREFIX}{address}" if address else SHARED_SESSION_KEY',
            new='    return SHARED_SESSION_KEY',
            why="every note goes to the shared session, so no note reaches its recipient's key and the first case goes red",
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
        test='apps/notulen/tests/test_a_notulen_names_each_person_once_caps_the_speakers_and_never_names_one_the_transcript_does_not_place.py',
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
        test='apps/notulen/tests/test_a_notulen_session_retries_a_call_not_recordable_yet_and_fails_only_the_job_kubernetes_failed.py',
        pins=('apps/notulen/app/core/sessions',),
        runs_when=(
            'apps/notulen/**',
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
            'infra/deploy_loop/gate_run.sh',
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
    Row(
        test="infra/gpu-jobs/gpu_jobs/tests/test_a_notulen_job_carries_the_name_the_naming_grammar_the_hardened_contexts_and_the_cluster_namespace.py",
        pins=("infra/gpu-jobs/gpu_jobs",),
        runs_when=(
        "infra/gpu-jobs/gpu_jobs/**",
        ),
        proved_by=Break(
            file="infra/gpu-jobs/gpu_jobs/security/worker_security_context.py",
            old='capabilities=client.V1Capabilities(drop=["ALL"]),',
            new='capabilities=client.V1Capabilities(drop=[]),',
            why="the worker container keeps every capability, so the container-context case fails",
        ),
    ),
    Row(
        test="apps/assistant/mcp/agenda/tests/test_an_event_the_agenda_tools_create_is_listed_back_with_every_field_it_was_given.py",
        pins=("apps/assistant/mcp/agenda/ical", "apps/assistant/mcp/agenda/tools"),
        runs_when=(
        "apps/assistant/mcp/agenda/**",
        ),
        proved_by=Break(
            file="apps/assistant/mcp/agenda/ical/build_vcal.py",
            old="    if event.location:",
            new="    if event.location and False:",
            why="the location never reaches the calendar text, so the location case fails",
        ),
    ),
    Row(
        test="apps/notulen/app/core/publish/tests/test_a_commit_that_lands_marks_the_job_complete_with_its_url_and_path_and_one_that_fails_leaves_it_to_retry.py",
        pins=("apps/notulen/app/core/publish/github", "apps/notulen/app/core/publish/retry"),
        runs_when=(
        "apps/notulen/app/core/publish/**",
        ),
        proved_by=Break(
            file="apps/notulen/app/core/publish/retry/finalize_commit.py",
            old="        output_path=committed.path,",
            new="        output_path=committed.url,",
            why="the job records the commit URL as its path, so the two landed cases fail",
        ),
    ),
    Row(
        test="tools/gate_scope/tests/test_a_change_only_a_register_row_names_selects_that_rows_test_and_nothing_else.py",
        pins=("tools/gate_scope", "tools/test_register"),
        runs_when=(
            "tools/gate_scope/**",
            "tools/test_register/**",
        ),
        proved_by=Break(
            file="tools/gate_scope/select.py",
            old="        and any(_fires(path, glob) for path in paths for glob in row.runs_when)",
            new="        and False",
            why="no row's trigger ever selects its test, so the two matched cases select nothing",
        ),
    ),
    Row(
        test="infra/caddy/cluster_caddyfile/tests/test_the_cluster_caddyfile_dials_a_cluster_service_for_every_compose_upstream_and_refuses_one_it_has_no_service_for.py",
        pins=("infra/caddy/cluster_caddyfile",),
        runs_when=(
        "infra/caddy/cluster_caddyfile/**",
        ),
        proved_by=Break(
            file="infra/caddy/cluster_caddyfile/_render.py",
            old='match.group("lead") + upstreams[upstream] + match.group("rest")',
            new='match.group("lead") + upstream + match.group("rest")',
            why="the rewrite keeps the compose upstream, so the rendered file differs from the hand-written one",
        ),
    ),
    Row(
        test="infra/k8s/media/tests/test_the_media_public_ip_is_attached_only_to_the_one_ready_node_of_the_media_and_never_moved_when_it_is_already_there.py",
        pins=("infra/k8s/media",),
        runs_when=(
            "infra/k8s/media/**",
        ),
        proved_by=Break(
            file="infra/k8s/media/ip-reattach.sh",
            old='if [ "$count" -ne 1 ]; then',
            new='if [ "$count" -lt 1 ]; then',
            why="two Ready media nodes reach the move, which the two-node case says never happens",
        ),
    ),
    Row(
        test="infra/deploy_loop/tests/test_the_deploy_loop_asks_the_cluster_only_what_the_cycle_may_act_a_signed_push_to_main_starts_each_idle_loop_cronjob_a_gate_job_runs_the_gated_commit_in_its_own_pinned_image_on_a_clone_of_its_and_a_job_fault_never_reads_as_a_test_verdict.py",
        pins=("infra/deploy_loop",),
        runs_when=(
            "infra/deploy_loop/**",
        ),
        proved_by=Break(
            file="infra/deploy_loop/_outcome.py",
            old='if failed is not None and failed.get("reason") == "DeadlineExceeded":',
            new='if failed is not None and failed.get("reason") == "Deadline":',
            why="a Job the deadline killed reads as its container's exit code, so the deadline case gets 0 instead of 124",
        ),
    ),
    Row(
        test="apps/assistant/core/claim_audit/tests/test_a_sent_message_is_judged_only_against_the_readings_that_answered_and_a_number_no_read_returned_is_a_finding.py",
        pins=("apps/assistant/core/claim_audit",),
        runs_when=(
        "apps/assistant/core/claim_audit/**",
        ),
        proved_by=Break(
            file="apps/assistant/core/claim_audit/check.py",
            old='        for reading in readings\n        if str(reading.get("outcome", "")) == READ_OK\n    )',
            new="        for reading in readings\n    )",
            why="an unavailable reading counts as evidence, so the unavailable case finds no fabricated number",
        ),
    ),
    Row(
        test="apps/assistant/core/knowledge/tests/test_a_knowledge_search_returns_the_rows_that_answer_the_question_and_never_a_row_sharing_one_ordinary_word.py",
        pins=("apps/assistant/core/knowledge",),
        runs_when=(
        "apps/assistant/core/knowledge/**",
        ),
        proved_by=Break(
            file="apps/assistant/core/knowledge/index.py",
            old="    if len(matched) >= 2 or len(wanted) == 1:",
            new="    if matched:",
            why="a row matching one word of a longer question is offered, so the two-rows case returns both",
        ),
    ),
    Row(
        test="apps/assistant/core/monitor/checks/tests/test_a_check_is_dispatched_by_its_kind_and_a_heartbeat_is_up_only_inside_its_window_and_unknown_before_its_first_beat.py",
        pins=("apps/assistant/core/monitor/checks",),
        runs_when=(
        "apps/assistant/core/monitor/checks/**",
        ),
        proved_by=Break(
            file="apps/assistant/core/monitor/checks/heartbeat.py",
            old="    if seen >= cutoff:",
            new="    if seen <= cutoff:",
            why="the window is turned around, so the fresh beat reads down and the overdue one up",
        ),
    ),
    Row(
        test="apps/assistant/core/notulen/tests/test_the_minutes_yield_every_action_row_and_decision_as_written_and_nothing_from_the_template_placeholders.py",
        pins=("apps/assistant/core/notulen",),
        runs_when=(
        "apps/assistant/core/notulen/**",
        ),
        proved_by=Break(
            file="apps/assistant/core/notulen/parse_minutes.py",
            old='        if not text or text.lower() in {"actie", "action"}:',
            new='        if text.lower() in {"actie", "action"}:',
            why="a row with a name and no action becomes an action, so the action-row case fails",
        ),
    ),
    Row(
        test="apps/assistant/core/tools/kubectl/tests/test_kubectl_get_summarises_pods_by_readiness_and_restarts_in_the_default_namespace_and_reads_no_kind_it_does_not_list.py",
        pins=("apps/assistant/core/tools/kubectl",),
        runs_when=(
        "apps/assistant/core/tools/kubectl/**",
        ),
        proved_by=Break(
            file="apps/assistant/core/tools/kubectl/kubectl_get.py",
            old='"ready": all(',
            new='"ready": any(',
            why="a pod with one ready container reads ready, so the pod summary cases fail",
        ),
    ),
    Row(
        test="apps/assistant/shared/budget/tests/test_the_budget_trips_once_the_days_charges_reach_the_cap_and_a_malformed_cap_is_refused.py",
        pins=("apps/assistant/shared/budget",),
        runs_when=(
        "apps/assistant/shared/budget/**",
        ),
        proved_by=Break(
            file="apps/assistant/shared/budget/is_tripped.py",
            old="return _state.budget_spend_today_eur() >= cap_eur()",
            new="return _state.budget_spend_today_eur() > cap_eur()",
            why="spend exactly on the cap does not trip, so the on-the-cap and zero-cap cases fail",
        ),
    ),
    Row(
        test="apps/assistant/watch/claim_audit/tests/test_the_weekly_audit_posts_to_talk_unless_the_week_was_clean_and_exits_loud_only_when_the_report_reached_nobody.py",
        pins=("apps/assistant/watch/claim_audit",),
        runs_when=(
        "apps/assistant/watch/claim_audit/**",
        ),
        proved_by=Break(
            file="apps/assistant/watch/claim_audit/watch.py",
            old="    if audit.findings == 0 and audit.messages:",
            new="    if audit.findings == 0:",
            why="a week with no messages is taken for a clean one, so the empty week is never posted",
        ),
    ),
    Row(
        test="apps/assistant/core/tools/tests/test_the_catalogue_offers_the_kubectl_tools_exactly_when_a_cluster_is_configured.py",
        pins=("apps/assistant/core/tools", "apps/assistant/core/tools/kubectl",),
        runs_when=(
        "apps/assistant/core/tools/**",
        ),
        proved_by=Break(
            file="apps/assistant/core/tools/__init__.py",
            old="_k8s_mod.cluster_configured())",
            new="True)",
            why="the kubectl tools are offered on every box, so the no-cluster cases offer them",
        ),
    ),
)
