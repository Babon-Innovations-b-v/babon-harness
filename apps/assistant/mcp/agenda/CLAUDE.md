# apps/assistant/mcp/agenda/

A CalDAV MCP server for the owner's file cloud calendars: list, read, find free slots, create, update, delete.

- Settings: `AGENDA_BASE_URL`, `AGENDA_USER`, `AGENDA_APP_PASSWORD`; `AGENDA_CALENDARS` narrows the list.
- Keep `python -m apps.assistant.mcp.agenda.server` working; `.mcp.json` names it.
- An event is fetched by its deterministic `{uid}.ics` URL, because some servers refuse a query by UID.
- `runtime.ensure_client()` is the test seam: patch `runtime._client`, never a tool.
