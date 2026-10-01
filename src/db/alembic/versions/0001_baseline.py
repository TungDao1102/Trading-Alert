"""Baseline migration — Phase 2 operational schema.

Re-creates the four tables in `src/db/models.py` (single source of schema
truth; the autogenerate `op.create_table(...)` calls match `Mapped[...]`
columns 1:1).

Conventions:
  - All timestamps TIMESTAMPTZ (UTC).
  - Money / qty / tick / step / notional NUMERIC(38, 18) (no float anywhere;
    DATA_MODEL §5 + ENGINEERING_PRINCIPLES).
  - No `create_all()` in prod paths — this migration is the only schema-authority.
  - JSON-as-TEXT for portable, PG-version-agnostic metadata blobs.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "symbol_metadata",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("metadata_observed_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("contract_type", sa.String(length=16), nullable=False),
        sa.Column("onboard_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price_tick_size", sa.Numeric(38, 18), nullable=False),
        sa.Column("quantity_step_size", sa.Numeric(38, 18), nullable=False),
        sa.Column("min_quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("max_quantity", sa.Numeric(38, 18), nullable=True),
        sa.Column("min_notional", sa.Numeric(38, 18), nullable=False),
        sa.Column("notional_constraints_json", sa.String(), nullable=False),
        sa.Column("order_capabilities_json", sa.String(), nullable=False),
        sa.Column("position_mode_snapshot_json", sa.String(), nullable=False),
        sa.Column("base_asset", sa.String(length=16), nullable=False),
        sa.Column("quote_asset", sa.String(length=16), nullable=False),
        sa.Column("margin_asset", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "metadata_observed_at_utc"),
    )
    op.create_index(
        "ix_symbol_metadata_observed",
        "symbol_metadata",
        ["symbol", "metadata_observed_at_utc"],
        unique=False,
    )

    op.create_table(
        "collector_watermarks",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("data_class", sa.String(length=16), nullable=False),
        sa.Column("last_tick_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "data_class"),
    )

    op.create_table(
        # NOTE: `symbol` is NOT NULL — tick-wide gaps use the "__TICK__"
        # sentinel (see TICK_WIDE_SYMBOL in src/db/models.py). PostgreSQL
        # rejects NULL in PK columns; the baseline is edited in place
        # because it has not shipped to a prod database yet.
        "collector_gaps",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("data_class", sa.String(length=16), nullable=False),
        sa.Column("expected_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=False),
        sa.Column("recorded_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "data_class", "expected_utc"),
    )
    op.create_index(
        "ix_collector_gaps_class_expected",
        "collector_gaps",
        ["data_class", "expected_utc"],
        unique=False,
    )

    op.create_table(
        "coverage_windows",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("interval", sa.String(length=8), nullable=False),
        sa.Column("historical_data_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("historical_data_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("onboard_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_history_json", sa.String(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "interval"),
    )


def downgrade() -> None:
    op.drop_table("coverage_windows")
    op.drop_index("ix_collector_gaps_class_expected", table_name="collector_gaps")
    op.drop_table("collector_gaps")
    op.drop_table("collector_watermarks")
    op.drop_index("ix_symbol_metadata_observed", table_name="symbol_metadata")
    op.drop_table("symbol_metadata")
