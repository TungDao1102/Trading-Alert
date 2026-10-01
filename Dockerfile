# Deployment image (13.1, D-05 to D-07).
#
# Every base is pinned by exact tag plus index digest (a deliberate, reviewed bump; see the
# pin table in docs/operations/RUNBOOK.md), and no `# syntax=` directive is used because it
# would pull an unpinned frontend image. Dependencies install only from uv.lock.
#
# Targets:
#   runtime  collector / paper / live (one image, different commands)
#   ops      runtime plus the backup/restore/cutover toolbox (added below)

# uv binary only; never pip-install uv. Pinned to the same version CI uses.
FROM ghcr.io/astral-sh/uv:0.12.21@sha256:a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711 AS uvbin

FROM python:3.13.15-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS runtime

COPY --from=uvbin /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install runtime deps first so iterative code edits reuse cached layers.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Application code + migration config (alembic upgrades run in-container).
COPY src ./src
COPY scripts ./scripts
COPY alembic.ini ./
# Operational collect list (D-01, D-02, D-24): the collector reads its symbols
# from docs/research/universe/collect-list-v1.toml relative to /app.
COPY docs/research/universe ./docs/research/universe

# Never run as root. Fixed numeric UID so named-volume ownership is predictable on every
# host. The volume mount points are created and owned here, BEFORE first use: a named
# volume copies the ownership of an existing image directory on first mount, whereas a
# mount point the image does not contain is created root-owned and unwritable by the
# runtime user (research finding 4).
RUN useradd --uid 10001 --create-home appuser \
    && mkdir -p /app/data/raw /app/data/backup /app/logs \
    && chown -R 10001:10001 /app
USER 10001

# Collector probe: exit 0 iff every universe symbol has an OI watermark updated within 2x
# cadence, so a wedged poll loop surfaces as unhealthy instead of reporting healthy forever.
# Exec form with the venv interpreter: bare `python` on PATH is the base interpreter, which
# has none of the venv packages (F-705). The long start period covers the first tick on a
# fresh database, which has no watermark yet. Docker never restarts an unhealthy container,
# so this is informational. paper and live override or disable it per service (D-06).
HEALTHCHECK --interval=60s --timeout=15s --start-period=6m --retries=3 \
    CMD ["/app/.venv/bin/python", "-m", "src.data.collector", "--healthcheck"]

# Exec form, venv interpreter, no `uv run` at runtime (it would re-resolve and may sync).
CMD ["/app/.venv/bin/python", "-m", "src.data.collector"]
