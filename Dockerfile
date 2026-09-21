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
# Watermark-freshness probe: exit 0 iff every universe symbol has an OI
# watermark updated within 2x cadence, so a wedged poll loop surfaces as
# unhealthy instead of reporting healthy forever.
HEALTHCHECK --interval=60s --timeout=15s --start-period=90s --retries=3 \
    CMD python -m src.data.collector --healthcheck || exit 1

CMD ["uv", "run", "python", "-m", "src.data.collector"]
