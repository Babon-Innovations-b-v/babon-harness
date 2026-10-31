"""Team-coordination write tools.

Chat-only, like `agenda_act`/`github_act`: wired into `core.chat` with the
requester as `actor`, never in the shared read-only registry. One module
per tool (NAME/DEFINITION/execute).

- `message_teammate`, the assistant sends a Signal message to a named teammate,
  attributed to whoever asked, so planning + preparation reach the team
  over the channel they already use (no email;).
"""
