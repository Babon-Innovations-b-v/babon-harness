# apps/assistant/core/tools/

The tool registry. Every tool module has `NAME`, `DEFINITION` and `execute(tool_input)`. `gateway_surface.py` decides what the MCP door serves; `write_tools.py` holds the writes.

- **A tool that can only fail is not registered.** kubectl tools need a kubeconfig or an in-cluster account; `loki_query` needs `LOKI_URL`.
- **Unavailable is not empty.** A tool whose configuration is missing answers unavailable, naming the variable.
- Every write runs through `write_guard`: kill switch, token, audit row before the result.
- The door's tool definitions are paid for on every call; a test pins their size. Keep descriptions short.
