# gate: the one environment the deploy gate's test runs use.
#
# Readers, one image, pinned by digest in `pin` beside this file:
#   - the commit hook, which runs the test files a commit adds or changes in it
#     with the network off and a fake clock (tools/test_register --sealed-run)
#   - the gate's own test runs, once the deploy loop reads the same pin
#
# What is in it and why:
#   python 3.12, the interpreter the lock asks for, on PATH as python3
#   the locked environment at /opt/gate-env: `uv sync --frozen --all-packages
#     --all-extras --all-groups`, with its uv cache at /opt/uv-cache hardlinked
#     in the same layer, so an offline re-sync can build the editable workspace
#     members against whatever tree is mounted
#   git, jq, flock (util-linux) and libfaketime, the tools tests run
#   uv, pinned
#   No script of the harness's own: the workspace members are copied only so
#     the environment can be built, and every run re-syncs them from the
#     mounted tree. No kubectl, scw, gh or docker: a test that needs one reads
#     the live machine, which is what this image exists to refuse.
#
# Build and push only with infra/gate-image/build.sh, which builds from a clean
# export of one commit, pushes a unique tag and writes the digest and the
# commit it was built from into `pin`.
FROM python:3.12.11-slim-bookworm

ARG GIT_SHA=unknown
LABEL org.opencontainers.image.revision="${GIT_SHA}"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates git jq util-linux procps coreutils faketime \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /usr/local/bin/

# The gate runs as 1000; the commit hook runs as whoever commits, so the
# repository is anybody's and git must not refuse it as "dubious ownership".
RUN groupadd -g 1000 gate \
    && useradd -u 1000 -g 1000 -m -d /home/gate -s /bin/bash gate \
    && chmod 1777 /home/gate \
    && git config --system safe.directory '*' \
    && mkdir -p /opt/gate-env /opt/uv-cache /opt/gate-src \
    && chown 1000:1000 /opt/gate-env /opt/uv-cache /opt/gate-src

ENV UV_CACHE_DIR=/opt/uv-cache \
    UV_LINK_MODE=hardlink \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/gate-env \
    GATE_ENV=/opt/gate-env

USER gate
WORKDIR /opt/gate-src
COPY --chown=1000:1000 pyproject.toml uv.lock /opt/gate-src/
COPY --chown=1000:1000 lib/dashkit /opt/gate-src/lib/dashkit
COPY --chown=1000:1000 apps/documents /opt/gate-src/apps/documents
COPY --chown=1000:1000 infra/gpu-jobs /opt/gate-src/infra/gpu-jobs
# Writable by every uid in the same layer (the files are hardlinked, so this
# costs no copy): the commit hook runs as whoever commits, and its offline
# re-sync writes the editable members into this environment.
RUN uv sync --frozen --all-packages --all-extras --all-groups \
    && /opt/gate-env/bin/python -c "import pytest, dashkit" \
    && chmod -R a+rwX /opt/gate-env /opt/uv-cache

ENV HOME=/home/gate
