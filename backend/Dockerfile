# Production image for the task-scheduler backend.
# Uses uv for dependency install (matches local dev), then runs Alembic
# migrations on container start before launching uvicorn.

FROM python:3.13-slim AS base

# uv: fast Python package manager. Install via the static binary so we don't
# pull pip / setuptools in the build.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# System deps for CBC solver (PuLP bundles a binary but apt-get build tools
# help when the wheel falls back to source build on some arch).
RUN apt-get update && apt-get install -y --no-install-recommends \
        coinor-cbc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (cached when only app code changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy the rest of the source.
COPY . .

# Install the project itself.
RUN uv sync --frozen

# SQLite lives on a mounted volume — see fly.toml.
RUN mkdir -p /mnt/data

EXPOSE 8080

# On boot: run migrations against the volume DB, then start uvicorn on the
# Fly-assigned port.
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8080"]
