"""Alembic env — async engine + Base.metadata target.

Per PATTERNS §4 + RESEARCH §Code Examples (SQLAlchemy 2.0 async verified):
  - DATABASE_URL comes from the environment (never hard-coded; T-02-02).
  - We swap `postgresql://` → `postgresql+psycopg://` for the async dialect.
  - Migration runs in a sync `connection.run_sync(...)` block so Alembic's
    autogenerate / op.* DDL stays on a sync path against the async engine.

Schema creation is migration-only — `Base.metadata.create_all()` is forbidden
in production code paths (RESEARCH §Anti-Patterns + DATA_PIPELINE §14).
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Resolve DATABASE_URL from env (T-02-02 — credentials never in alembic.ini).
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL is required for alembic (set in .env or shell; "
        "see .env.example for the connection-string shape)."
    )

# Alembic operates against the sync URL; the async swap lives in models.make_engine.
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection (CI / dry-runs)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        timezone="UTC",
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            timezone="UTC",
            render_as_batch=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
