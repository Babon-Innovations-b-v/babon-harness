# Notulen dashboard image. Build context is the REPOSITORY ROOT:
#   docker build -f apps/notulen/Dockerfile -t harness-notulen .
#
# Self-contained: Python, ffmpeg, the dashboard's dependencies, dashkit and
# gpu_jobs from this repository, and the CPU transcription path (the whisper
# extra), which is how every recording is transcribed while GPU_ENABLED=0.
FROM python:3.12-slim
WORKDIR /app

# ffmpeg transcodes, measures loudness and stitches recorder segments.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.30" \
        "psycopg[binary]>=3.2" \
        "anthropic>=0.92" \
        "pydantic>=2.7" \
        "requests>=2.32" \
        "boto3>=1.34" \
        "python-multipart>=0.0.9" \
        "kubernetes>=29" \
        "faster-whisper>=1.0"

# Bake the CPU whisper model so the first recording does not stall on a
# download. NOTULEN_CPU_MODEL at runtime must match this, or the container
# downloads the other size on first use.
ARG NOTULEN_CPU_MODEL=medium
ENV HF_HOME=/opt/models/huggingface
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${NOTULEN_CPU_MODEL}', compute_type='int8', device='cpu')" \
    && chmod -R a+rwX /opt/models

# Package layout mirrors the repository: uvicorn puts /app on sys.path, so
# `dashkit`, `gpu_jobs` and `apps.notulen...` resolve with no path tricks.
COPY lib/dashkit/ ./dashkit/
COPY infra/gpu-jobs/gpu_jobs/ ./gpu_jobs/
COPY apps/__init__.py ./apps/__init__.py
COPY apps/notulen/ ./apps/notulen/
RUN rm -rf ./apps/notulen/tests ./gpu_jobs/tests

# /tmp/notulen holds live recording sessions; compose mounts a volume there
# so a redeploy cannot wipe a meeting that is still being recorded.
RUN useradd --uid 1000 --create-home notulen \
    && mkdir -p /tmp/notulen && chown notulen /tmp/notulen
USER notulen

EXPOSE 8000
CMD ["uvicorn", "apps.notulen.app.entrypoints.main:app", "--host", "0.0.0.0", "--port", "8000"]
