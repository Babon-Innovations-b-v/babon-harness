# docs/diagrams/mcp/CLAUDE.md

The `diagram` MCP server: `draw_module`, `link_module`, `check_diagrams`, one file each. Plain scripts imported flat, not a package; run as `python3 docs/diagrams/mcp/server.py`. Every verdict about the set is deferred to `docs/diagrams/tools/linkmap.py`; this directory holds no diagram logic of its own.

## The trap: it writes to the checkout it was started in

`runtime.py` sets `REPO` from this file's own location, and `.mcp.json` starts the server from the shared checkout. So every spec, sidecar and page it writes lands in the **shared checkout**, whichever worktree called it. From a worktree, copy the drawn files across before committing, then clean the shared checkout.

## Where a page's files go

Four places, and a page is only whole when all four agree: the spec pair `docs/diagrams/specs/stack/<name>.json` plus `<name>.layout.json`, the build sidecars `docs/diagrams/data/stack/<name>.*.json`, and the delivered page `docs/diagrams/stack/<name>.html`. Re-render with `docs/diagrams/tools/deliver.sh`. The top page is `stack` and sits in `docs/diagrams/` itself.

## Settings

`BIBLE_BASE_URL` (where docs/ is published; empty means relative links) and `DIAGRAM_AUTHORS` (the byline), both from `config/harness.env`.

## Don't

- Don't hand-edit a delivered `.html`; change the spec and redraw.
- Don't leave a drawn box without a bible sentence carrying its `◈` marker. `linkmap.py` fails on an unclaimed box, and that failure is the point.
- Don't import `mcp` anywhere but `server.py`; the tools and their tests run on the standard library.
