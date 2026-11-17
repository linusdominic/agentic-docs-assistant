FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8080

WORKDIR /app

# Dependencies first, so this layer is reused when only the source changes.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Bake the embedding model into the image so a cold start does not download it.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

COPY src ./src
COPY knowledge_base ./knowledge_base
RUN uv sync --frozen --no-dev

RUN useradd --create-home app && chown -R app /app/.cache
USER app

EXPOSE 8080
# Cloud Run sets PORT; the shell form lets uvicorn pick it up.
CMD ["sh", "-c", "uvicorn docs_agent.main:app --host 0.0.0.0 --port ${PORT}"]
