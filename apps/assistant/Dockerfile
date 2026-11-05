# The assistant's door: the FastAPI gates, the triage and patrol loops, and
# the MCP tool door the OpenClaw gateway calls. Built by compose with the
# repository root as context (`apps/assistant/compose.yml`).
FROM python:3.12-slim
WORKDIR /app

# gh CLI for the GitHub read and write tools, and a handful of read-only
# investigation binaries for run_shell (DNS, HTTP GET, reachability, TLS).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
        dnsutils netcat-openbsd iputils-ping openssl wget \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && apt-get purge -y --auto-remove gnupg \
    && rm -rf /var/lib/apt/lists/*

# mcp is pinned as the root pyproject pins it (dependency group mcp-tools), so
# the image and the test run resolve the same library.
RUN pip install --no-cache-dir \
    fastapi \
    'uvicorn[standard]' \
    anthropic \
    kubernetes \
    psycopg2-binary \
    'mcp>=1.26,<2'

# kubectl, for the chat relay CronJob that runs the gateway's CLI with
# `kubectl exec` (infra/k8s/assistant/schedule.yaml). Static binary.
COPY --from=alpine/k8s:1.35.8 /usr/bin/kubectl /usr/local/bin/kubectl

COPY apps/__init__.py apps/__init__.py
COPY apps/assistant/ apps/assistant/
# What the assistant reads about the system it serves: the bible and the
# ADRs for the bible and knowledge_search tools, the house voice SOUL.md is
# rendered from, the repository settings (`repo`, `people`, `areas`), and the
# written documents repo_search searches.
COPY docs/ docs/
COPY business/ business/
COPY CONTEXT.md README.md ./
COPY .claude/soul.md .claude/project.json .claude/

# Which commit this image was built from, so stack_status can contradict a
# deployer reporting on its own deploys.
ARG GIT_SHA=unknown
ENV OPENCLAW_BUILD_SHA=$GIT_SHA \
    OPENCLAW_BIBLE_PATH=/app/docs/bible.md \
    OPENCLAW_DOCS_ROOT=/app/docs \
    REPO_ROOT=/app \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# One worker: the SQLite state is single-writer.
CMD ["python", "-m", "apps.assistant.entrypoints.serve"]
