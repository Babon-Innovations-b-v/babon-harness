# GPU worker for the notulen pipeline: pyannote diarization, whisper-large-v3
# transcription, Claude minutes. Built by infra/gpu/build-worker.sh from the
# repository root as build context.
#
# Base: PyTorch's official public image, so torch, CUDA and cuDNN already
# agree with each other.
#
# Speaker labels are optional. With a Hugging Face read token that has
# accepted the terms of pyannote/speaker-diarization-3.1 and
# pyannote/segmentation-3.0, the build bakes those models in; the token is a
# BuildKit secret and never lands in a layer. Without one the image still
# transcribes, without speaker labels. At runtime the worker diarizes only
# when HF_TOKEN is present in its Secret.
#
#   DOCKER_BUILDKIT=1 docker build -f infra/gpu/Dockerfile \
#       --secret id=hf_token,src=<file with the token> -t <image> .

FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/models/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# pyannote 3.3.2 is the last 3.x and uses soundfile, not torchcodec.
# huggingface-hub<1.0 because pyannote 3.3.2 still passes use_auth_token.
# The constraints file pins every transitive dependency to a known-good build.
COPY apps/notulen/shared/worker_constraints.txt /tmp/constraints.txt
RUN pip install --no-cache-dir -c /tmp/constraints.txt \
        pyannote.audio==3.3.2 \
        matplotlib \
        "huggingface-hub<1.0" \
        faster-whisper==1.2.1 \
        anthropic \
        boto3 \
        "psycopg[binary]>=3.2"

RUN python -c "from pyannote.audio import Pipeline; from faster_whisper import WhisperModel; print('imports OK')"

# Bake whisper large-v3 (the runtime loads it again as float16 on the GPU and
# reuses this cache).
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3', compute_type='int8')"

# Bake the gated pyannote models when a token is given; skip quietly when not.
RUN --mount=type=secret,id=hf_token,required=false \
    if [ -s /run/secrets/hf_token ]; then \
        HF_TOKEN="$(cat /run/secrets/hf_token)" python -c "import os; from pyannote.audio import Pipeline; Pipeline.from_pretrained('pyannote/speaker-diarization-3.1', use_auth_token=os.environ['HF_TOKEN'])"; \
    else \
        echo "no hf_token secret: building without speaker label models"; \
    fi

# The pod runs as uid 1000 (gpu_jobs.worker_security_context); the model cache
# must be readable and its lock files writable by that user.
RUN chmod -R a+rwX /opt/models

WORKDIR /app
COPY apps/notulen/entrypoints/worker.py /app/notulen_worker.py
COPY apps/notulen/inputs/notulen_template.md /app/notulen_template.md

ENTRYPOINT ["python", "/app/notulen_worker.py"]
