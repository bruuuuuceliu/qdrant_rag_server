# syntax=docker/dockerfile:1
#
# Single runtime image for every RAG service. Compose overrides the command per
# service (`python -m <service>.worker`), keeping the broker-first topology
# identical to local. The image runs as an unprivileged user; secrets are never
# baked in (see .dockerignore).
#
# Build:
#   docker build -t qdrant-rag-server:latest .
#
# Optional build args:
#   INSTALL_CPU_ONLY_TORCH=1   install CPU-only torch (much smaller) instead of
#                              the default CUDA wheel from PyPI.
#   EMBEDDING_MODEL=<model>    pre-download the embedding model into the image
#                              cache so workers start offline.
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/rag/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/home/rag/.cache/huggingface/sentence_transformers \
    RAG_EMBEDDING_MODEL_CACHE_DIR=/home/rag/.cache/huggingface

# Runtime system libraries: torch CPU inference needs libgomp; curl is used by
# compose health checks against /healthz + /readyz.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home --home /home/rag rag

WORKDIR /app

COPY --chown=rag:rag . /app

# Optional CPU-only torch. Keep before `pip install .` so the CUDA wheel is not
# re-resolved when the package install runs.
ARG INSTALL_CPU_ONLY_TORCH=0
RUN if [ "$INSTALL_CPU_ONLY_TORCH" = "1" ]; then \
        python -m pip install --index-url https://download.pytorch.org/whl/cpu \
            --no-cache-dir torch; \
    fi

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir .

# Optional embedding-model pre-cache (see ops runbook §5 for the model choice).
ARG EMBEDDING_MODEL=""
RUN if [ -n "$EMBEDDING_MODEL" ]; then \
        python -c "import os; from sentence_transformers import SentenceTransformer; SentenceTransformer(os.environ['EMBEDDING_MODEL'], device='cpu')"; \
    fi

RUN mkdir -p /var/lib/rag && chown rag:rag /var/lib/rag \
    && mkdir -p /backup/rag && chown rag:rag /backup/rag

# Fresh named volumes mounted at /var/lib/rag and /backup/rag inherit this
# directory ownership (rag, uid 10001) so the unprivileged workers can write
# durable state (SQLite DBs, storage, response cache, placement registry) and
# the backup service can write snapshots.
VOLUME /var/lib/rag
VOLUME /backup/rag

RUN chown -R rag:rag /app /home/rag

USER rag

# Public manager gRPC API + the per-service ops (health/metrics) port range.
EXPOSE 50051 9001-9012

# Default command is the manager; production compose overrides per service.
CMD ["python", "-m", "manager_service.worker"]
