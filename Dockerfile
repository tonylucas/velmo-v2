FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TOKENIZERS_PARALLELISM=false \
    ANONYMIZED_TELEMETRY=False \
    HF_HUB_OFFLINE=0

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY eval ./eval
COPY kb ./kb
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts

RUN uv sync --no-dev --extra demo --extra llm --extra vector --extra obs

# Bake the embedding model into the image so runtime never contacts HuggingFace.
# Requires the HuggingFace Hub reachable DURING BUILD (one-shot).
RUN uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"

# From here on, embeddings load from the baked cache, fully offline.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# Stamp the released version into the image. The build context carries no `.git`,
# so `git describe` cannot answer at runtime; this is what lets the running
# container report which release it actually is. Declared last so changing it
# never invalidates the expensive layers above.
ARG VELMO_VERSION=dev
ENV VELMO_VERSION=${VELMO_VERSION}

EXPOSE 8000
ENTRYPOINT ["bash", "scripts/serve.sh"]
