"""Agenda tool group, the assistant's hands on the team agenda.

The calendars live on the owner's file cloud's CalDAV (Nextcloud, at
AGENDA_BASE_URL). The assistant signs in as its own account, AGENDA_USER,
with an app password, AGENDA_APP_PASSWORD, both from the vault. Which
calendars it reads, and the optional shared team calendar, are settings
(`calendars.py`).

Modules (tool grammar NAME/DEFINITION/execute; caldav.py is the shared
transport like kubectl/k8s.py is for the kubectl group):

    caldav.py        stdlib urllib CalDAV client + minimal iCalendar
                     parse/build (no extra image deps)
    agenda_view.py   read tool, upcoming team calendar events
    agenda_act.py    write tool, add, move or remove an event; kill
                     switch ASSISTANT_AGENDA_WRITE, audited in
                     state.assistant_actions. Rescheduling is `move`, which
                     rewrites an event in place: remove-then-add left a
                     duplicate whenever the removal named the wrong
                     event

FAILURE POLICY: per tools/ doctrine, execute() faults are returned as
text by the registry's defended catch; the write path is Tier-1 about
its audit row (recorded before the mutation is reported done).
"""
