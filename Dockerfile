FROM python:3.13-slim-bookworm

# Install uv via the official installer; never pip-install uv (RESEARCH §toolchain).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Install runtime deps first so iterative code edits reuse cached layers.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Application code
COPY src ./src
COPY scripts ./scripts

# Healthcheck for the collector/backfill image; entrypoints are docker-compose
# overrides per service (Phase 2 single image, multiple entrypoints).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

CMD ["uv", "run", "python", "-m", "src.data.collector"]
