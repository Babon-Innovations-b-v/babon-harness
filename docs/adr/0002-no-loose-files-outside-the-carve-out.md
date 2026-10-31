# No loose files outside the carve-out

**Status:** accepted

Every directory in this repo contains subdirectories only, plus the framework-required files named
in the carve-out below. Anything else loose moves into a named subdirectory.

The rule exists because a directory is the cheapest boundary a codebase has, and loose files are
how that boundary rots. A directory with twenty files in it has stopped telling a reader anything;
the reader has to open files to learn what lives where, which is the work the directory was meant
to save. Every repo that got hard to navigate got there one convenient loose file at a time, and
each one looked harmless.

The carve-out is for files a framework or tool requires to sit at an exact path, where moving them
breaks the tool. It is not for files that are merely conventional.

## Carve-out

- `__init__.py`
- `conftest.py`
- `pyproject.toml`
- `uv.lock`
- `package.json`
- `package-lock.json`
- `Dockerfile*`
- `.dockerignore`
- `docker-compose.yml`
- `compose.yml`
- `Caddyfile`
- `README.md`
- `CLAUDE.md`
- `CONTEXT.md`
- `LICENSE`
- `THIRD_PARTY_NOTICES.md`
- `docs/bible.md`

`Dockerfile*` covers a named Dockerfile beside the default one. `compose.yml` is a component's
fragment of the stack, which the root `docker-compose.yml` includes; the deploy loop finds a
service's folder by it.

The list is append-only by ADR amendment: a new entry is an edit to this file and to root
`CLAUDE.md`, which keeps its own copy so a session reads the rule without opening the ADR. The two
copies are checked against each other by `python3 docs/adr/tools/check_index.py`, so they cannot
drift silently.

Dotfiles at the repository root (`.gitignore`, `.gitattributes`, `.mcp.json` and the like) sit
outside this rule: they are configuration the tool locates by name, and they are invisible in an
ordinary listing, which is the harm the rule is aimed at.
