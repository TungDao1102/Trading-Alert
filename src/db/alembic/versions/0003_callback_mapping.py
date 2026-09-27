"""Short→full id mapping table — Phase 8 (plan 08-02, D-02).

Adds the `short_id_mapping` table that reverses the deterministic
sha256-prefix short id emitted in Telegram `callback_data` (Phase-7
sender) back to the full `signal_id` + `trade_plan_id` pair needed
by the binding-gate replay path. The receiver persists this row in
the SAME transaction as the Approval row transition (atomic write;
never in a separate commit).

Retention contract: rows live until their approval is decided and
past expiry, then a scheduled purge deletes mappings whose approval
is decided/expired. No FK to `trade_plans` (the mapping must survive
plan supersede for audit replay); the `(signal_id, trade_plan_id)`
unique guard rejects a divergent re-binding of an already-mapped
pair so re-plans fail closed instead of silently rebinding.

Conventions (same as 0001_baseline.py + 0002_domain_registry.py):
  - All timestamps TIMESTAMPTZ (UTC).
  - PK is a content-hash / deterministic id; no auto-increment
    anywhere (D-03).
  - Nullable columns ONLY for "transition never happened" timestamps
    (D-11); this table has no nullable columns.
  - Single source of schema truth lives in `src/db/models.py`; the
    `op.create_table(...)` call mirrors `Mapped[...]` columns 1:1.

Revision ID: 0003_callback_mapping
Revises: 0002_domain_registry
Create Date: 2026-09-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_callback_mapping"
down_revision = "0002_domain_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "short_id_mapping",
        sa.Column("short_id", sa.String(length=32), nullable=False),
        sa.Column("signal_id", sa.String(length=128), nullable=False),
        sa.Column("trade_plan_id", sa.String(length=128), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("short_id"),
    )
    op.create_index(
        "ix_short_id_mapping_signal_id",
        "short_id_mapping",
        ["signal_id"],
        unique=False,
    )
    op.create_index(
        "ix_short_id_mapping_trade_plan_id",
        "short_id_mapping",
        ["trade_plan_id"],
        unique=False,
    )
    op.create_index(
        "uq_short_id_mapping_signal_trade_plan",
        "short_id_mapping",
        ["signal_id", "trade_plan_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_short_id_mapping_signal_trade_plan", table_name="short_id_mapping")
    op.drop_index("ix_short_id_mapping_trade_plan_id", table_name="short_id_mapping")
    op.drop_index("ix_short_id_mapping_signal_id", table_name="short_id_mapping")
    op.drop_table("short_id_mapping")
