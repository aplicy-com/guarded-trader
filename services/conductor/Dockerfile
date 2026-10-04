# syntax=docker/dockerfile:1
# Base images pinned to specific tags (docs/04-architecture/security.md).
FROM ghcr.io/astral-sh/uv:0.11.31 AS uv

FROM python:3.12.15-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first (cached layer), exactly as locked.
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12.15-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/app/.venv/bin:$PATH"
RUN groupadd --gid 10001 conductor \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin conductor \
 && install -d -o conductor -g conductor -m 0750 /data
WORKDIR /app
COPY --from=build --chown=root:root /app/.venv /app/.venv
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root migrations ./migrations
USER conductor
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
# Migrate, then serve. `exec` so uvicorn is PID 1 and gets SIGTERM.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn conductor.main:app_factory --factory --host 0.0.0.0 --port 8000"]
