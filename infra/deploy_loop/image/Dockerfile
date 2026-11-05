# deploy-cycle: the image of the deploy loop's own pods.
#
# Readers: CronJob deploy-cycle (cycle_entry.sh, then the steps from the clone),
# every gate Job's fetch init container (git), and the push receiver
# (python3 -m infra.deploy_loop receive). A gate Job's run container is the
# gate image the gated commit pins (infra/gate-image), never this one.
#
# What is in it: python 3.12 for the steps' helpers, git, jq, curl, flock,
# kubectl and buildctl (the BuildKit client; the daemon is Deployment
# buildkitd), uv. Of ours only infra/deploy_loop, which the receiver and the
# cycle's first start need before any clone exists; the cycle runs every step
# from its clone at the commit it deploys.
#
# Build from the repository root, tag :vN (never reused, never :latest):
#   docker build -f infra/deploy_loop/image/Dockerfile -t <registry>/deploy-cycle:v1 .
# and set DEPLOY_CYCLE_IMAGE in config/harness.env to the pushed reference.
FROM python:3.12.11-slim-bookworm

ARG KUBECTL_VERSION=v1.34.1
ARG BUILDKIT_VERSION=v0.23.2

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git jq util-linux procps coreutils tar gzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /usr/local/bin/kubectl \
        "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
    && chmod +x /usr/local/bin/kubectl \
    && curl -fsSL "https://github.com/moby/buildkit/releases/download/${BUILDKIT_VERSION}/buildkit-${BUILDKIT_VERSION}.linux-amd64.tar.gz" \
        | tar -xz -C /usr/local bin/buildctl

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /usr/local/bin/

RUN groupadd -g 1000 deploy \
    && useradd -u 1000 -g 1000 -m -d /home/deploy -s /bin/bash deploy \
    && git config --system safe.directory '*'

WORKDIR /app
COPY infra/deploy_loop /app/infra/deploy_loop
USER deploy
ENV HOME=/home/deploy PYTHONPATH=/app
