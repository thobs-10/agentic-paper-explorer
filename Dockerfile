# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.9-python3.12-bookworm-slim AS deps

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Only lock metadata lands here, so dependency layers stay cached when source changes.
COPY pyproject.toml uv.lock README.md ./

FROM deps AS deps-backend
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --extra backend

FROM deps AS deps-ingestion
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --extra ingestion

FROM deps AS deps-frontend
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --extra frontend


FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/home/app/.cache/huggingface

# The cache path must exist and be app-owned in the image, otherwise Docker
# creates the named volume mount point as root and downloads fail.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /home/app/.cache/huggingface \
    && chown -R app:app /home/app/.cache

WORKDIR /app
USER app


FROM runtime AS backend

COPY --from=deps-backend --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src ./src

EXPOSE 8000
CMD ["uvicorn", "agentic_paper_explorer.backend.api.router:app", \
    "--host", "0.0.0.0", "--port", "8000"]


FROM runtime AS ingestion

COPY --from=deps-ingestion --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src ./src

EXPOSE 8001
CMD ["uvicorn", "agentic_paper_explorer.ingestion.api.router:app", \
    "--host", "0.0.0.0", "--port", "8001"]


FROM runtime AS frontend

COPY --from=deps-frontend --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src ./src

EXPOSE 8501
CMD ["streamlit", "run", "src/agentic_paper_explorer/frontend/app.py", \
    "--server.address", "0.0.0.0", \
    "--server.port", "8501", \
    "--server.headless", "true"]
