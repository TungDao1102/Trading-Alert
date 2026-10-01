"""Domain + registry mirror — Phase 3 (plan 03-04, DOMN-01/DOMN-02 storage half).

Re-creates the seven domain tables in `src/db/models.py` (single source
of schema truth; the autogenerate `op.create_table(...)` calls match
`Mapped[...]` columns 1:1).

Conventions (same as 0001_baseline.py):
  - All timestamps TIMESTAMPTZ (UTC).
  - Money / qty / tick / step / notional NUMERIC(38, 18) (no float anywhere;
    DATA_MODEL §5 + ENGINEERING_PRINCIPLES).
  - No `create_all()` in prod paths — this migration is the only schema-authority.
  - JSON-as-TEXT for portable, PG-version-agnostic metadata blobs.
  - PKs are content-hash IDs (D-03); no auto-increment anywhere.
  - Nullable columns ONLY for "transition never happened" timestamps (D-11).

Revision ID: 0002_domain_registry
Revises: 0001_baseline
Create Date: 2026-09-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002_domain_registry"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- signals (Phase 3, plan 03-01) -------------------------------
    op.create_table(
        "signals",
        sa.Column("signal_id", sa.String(length=128), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("parameter_set_id", sa.String(length=64), nullable=False),
        sa.Column("parameter_set_hash", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("setup_type", sa.String(length=64), nullable=False),
        sa.Column("source_timeframe", sa.String(length=8), nullable=False),
        sa.Column("source_candle_close_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("signal_id"),
    )
    op.create_index(
        "ix_signals_symbol_close",
        "signals",
        ["symbol", "source_candle_close_utc"],
        unique=False,
    )
    op.create_index(
        "ix_signals_parameter_set",
        "signals",
        ["parameter_set_id", "parameter_set_hash"],
        unique=False,
    )

    # ---------- trade_plans (Phase 3, plan 03-04) ---------------------------
    op.create_table(
        "trade_plans",
        sa.Column("trade_plan_id", sa.String(length=128), nullable=False),
        sa.Column("signal_id", sa.String(length=128), nullable=False),
        sa.Column("trade_plan_version", sa.String(length=32), nullable=False),
        sa.Column("entry_model", sa.String(length=32), nullable=False),
        sa.Column("entry_min_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("entry_max_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("stop_loss_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("take_profit_json", sa.String(), nullable=False),
        sa.Column("invalidation_rule_json", sa.String(), nullable=False),
        sa.Column("expiry_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_rr_json", sa.String(), nullable=False),
        sa.Column("risk_rate", sa.Numeric(38, 18), nullable=False),
        sa.Column("risk_budget", sa.Numeric(38, 18), nullable=False),
        sa.Column("suggested_quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("quantity_before_rounding", sa.Numeric(38, 18), nullable=False),
        sa.Column("quantity_after_rounding", sa.Numeric(38, 18), nullable=False),
        sa.Column("quantization_decision", sa.String(length=32), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("trade_plan_id"),
    )
    op.create_index("ix_trade_plans_signal_id", "trade_plans", ["signal_id"], unique=False)

    # ---------- approvals (Phase 3, plan 03-04) -----------------------------
    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.String(length=128), nullable=False),
        sa.Column("trade_plan_id", sa.String(length=128), nullable=False),
        sa.Column("signal_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("approval_token_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acted_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("telegram_message_id", sa.String(length=64), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("approval_id"),
    )
    op.create_index("ix_approvals_trade_plan_id", "approvals", ["trade_plan_id"], unique=False)
    op.create_index("ix_approvals_signal_id", "approvals", ["signal_id"], unique=False)

    # ---------- orders (Phase 3, plan 03-04) --------------------------------
    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(length=128), nullable=False),
        sa.Column("trade_plan_id", sa.String(length=128), nullable=True),
        sa.Column("position_id", sa.String(length=128), nullable=True),
        sa.Column("parent_order_id", sa.String(length=128), nullable=True),
        sa.Column("order_role", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("position_side", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=32), nullable=False),
        sa.Column("time_in_force", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("price", sa.Numeric(38, 18), nullable=True),
        sa.Column("stop_price", sa.Numeric(38, 18), nullable=True),
        sa.Column("close_position", sa.Boolean(), nullable=False),
        sa.Column("reduce_only", sa.Boolean(), nullable=False),
        sa.Column("client_order_id", sa.String(length=64), nullable=True),
        sa.Column("exchange_order_id", sa.String(length=64), nullable=True),
        sa.Column("algo_client_id", sa.String(length=64), nullable=True),
        sa.Column("exchange_status", sa.String(length=32), nullable=False),
        sa.Column("local_status", sa.String(length=16), nullable=False),
        sa.Column("submitted_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canceled_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("order_id"),
    )
    op.create_index("ix_orders_trade_plan_id", "orders", ["trade_plan_id"], unique=False)
    op.create_index("ix_orders_position_id", "orders", ["position_id"], unique=False)
    op.create_index(
        "ix_orders_symbol_submitted",
        "orders",
        ["symbol", "submitted_at_utc"],
        unique=False,
    )

    # ---------- fills (Phase 3, plan 03-04) ---------------------------------
    op.create_table(
        "fills",
        sa.Column("fill_id", sa.String(length=128), nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=False),
        sa.Column("exchange_trade_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("position_side", sa.String(length=8), nullable=False),
        sa.Column("fill_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("fill_quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("quote_quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("commission", sa.Numeric(38, 18), nullable=False),
        sa.Column("commission_asset", sa.String(length=16), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(38, 18), nullable=False),
        sa.Column("fill_time_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_maker", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("fill_id"),
        sa.UniqueConstraint("order_id", "exchange_trade_id", name="uq_fills_order_trade"),
    )
    op.create_index("ix_fills_order_id", "fills", ["order_id"], unique=False)
    op.create_index("ix_fills_symbol_time", "fills", ["symbol", "fill_time_utc"], unique=False)

    # ---------- positions (Phase 3, plan 03-04) ------------------------------
    op.create_table(
        "positions",
        sa.Column("position_id", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("position_side", sa.String(length=8), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("entry_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("break_even_price", sa.Numeric(38, 18), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(38, 18), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(38, 18), nullable=False),
        sa.Column("opened_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("position_id"),
    )
    op.create_index(
        "ix_positions_symbol_status",
        "positions",
        ["symbol", "status"],
        unique=False,
    )

    # ---------- journal_events (Phase 3, plan 03-04) ------------------------
    op.create_table(
        "journal_events",
        sa.Column("journal_event_id", sa.String(length=128), nullable=False),
        sa.Column("occurred_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("signal_id", sa.String(length=128), nullable=True),
        sa.Column("trade_plan_id", sa.String(length=128), nullable=True),
        sa.Column("approval_id", sa.String(length=128), nullable=True),
        sa.Column("order_id", sa.String(length=128), nullable=True),
        sa.Column("position_id", sa.String(length=128), nullable=True),
        sa.Column("payload_json", sa.String(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("journal_event_id"),
    )
    op.create_index(
        "ix_journal_events_correlation",
        "journal_events",
        ["correlation_id"],
        unique=False,
    )
    op.create_index(
        "ix_journal_events_occurred",
        "journal_events",
        ["occurred_at_utc"],
        unique=False,
    )


def downgrade() -> None:
    # Reverse order of creation.
    op.drop_index("ix_journal_events_occurred", table_name="journal_events")
    op.drop_index("ix_journal_events_correlation", table_name="journal_events")
    op.drop_table("journal_events")

    op.drop_index("ix_positions_symbol_status", table_name="positions")
    op.drop_table("positions")

    op.drop_index("ix_fills_symbol_time", table_name="fills")
    op.drop_index("ix_fills_order_id", table_name="fills")
    op.drop_table("fills")

    op.drop_index("ix_orders_symbol_submitted", table_name="orders")
    op.drop_index("ix_orders_position_id", table_name="orders")
    op.drop_index("ix_orders_trade_plan_id", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_approvals_signal_id", table_name="approvals")
    op.drop_index("ix_approvals_trade_plan_id", table_name="approvals")
    op.drop_table("approvals")

    op.drop_index("ix_trade_plans_signal_id", table_name="trade_plans")
    op.drop_table("trade_plans")

    op.drop_index("ix_signals_parameter_set", table_name="signals")
    op.drop_index("ix_signals_symbol_close", table_name="signals")
    op.drop_table("signals")
