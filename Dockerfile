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

# Application code + migration config (alembic upgrades run in-container).
COPY src ./src
COPY scripts ./scripts
COPY alembic.ini ./

# Never run the collector as root; the app writes /app/data/* (raw store
# + backup bundles), so the data dir is owned by the runtime user.
RUN useradd -m appuser && mkdir -p /app/data && chown -R appuser /app
USER appuser

# Healthcheck for the collector/backfill image; entrypoints are docker-compose
# overrides per service (Phase 2 single image, multiple entrypoints).
# Importing the collector proves the runtime + dependencies load; a dead
# loop surfaces via watermark freshness checks outside the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import src.data.collector" || exit 1

CMD ["uv", "run", "python", "-m", "src.data.collector"]
