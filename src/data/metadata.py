"""Versioned symbol metadata refresh (DATA-03 / D-05).

Refreshes the `symbol_metadata` table from live `exchangeInfo`. The PK is
`(symbol, metadata_observed_at_utc)` so every refresh INSERTs a new row —
never UPDATEs an existing one (RESEARCH §Pattern 4, versioned metadata).

Wire-format rules enforced here:

  - Filter numeric strings parse through `Decimal(str(...))` at the adapter
    boundary (already in `src/adapters/binance_usdm.py`) and reach this
    module as `Decimal` values. NO `float(...)` call appears on the path.
  - Observed-at is supplied by the caller; `datetime.now(UTC)` is the
    fallback for production callers and the injected clock for tests.
  - Optional `universe` parameter restricts which symbols are inserted.
    Useful for the live-5 V1 bootstrap (D-01). Symbols not in the
    universe are silently skipped — they do NOT cause a failure.

This module is the only writer of `symbol_metadata`; downstream consumers
pin `metadata_observed_at_utc <= dataset_date` to reconstruct the rules
in force at any historical backtest point.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session
from src.adapters.binance_usdm import SymbolFilters
from src.db.models import SymbolMetadata

if TYPE_CHECKING:
    pass


def refresh_symbol_metadata(
    session: Session,
    filters: Sequence[SymbolFilters],
    *,
    observed_at: datetime | None = None,
    universe: Iterable[str] | None = None,
) -> int:
    """Insert one new version row per filter, optionally restricted to a universe.

    Args:
        session: SQLAlchemy sync session. The caller owns the transaction
            boundary — this function commits before returning so the rows
            are durable (a second call inside the same session sees the
            just-inserted rows).
        filters: ExchangeInfo projections (one per symbol) from the adapter.
        observed_at: PK timestamp for the version. `None` means now (UTC).
        universe: Optional set of symbols to insert. Anything outside this
            set is silently skipped (no error). `None` inserts everything.

    Returns:
        Number of rows inserted (i.e. `len(filters)` after universe
        filtering).
    """
    when = observed_at if observed_at is not None else datetime.now(UTC)
    universe_set = set(universe) if universe is not None else None
    inserted = 0
    for f in filters:
        if universe_set is not None and f.symbol not in universe_set:
            continue
        session.add(
            SymbolMetadata(
                symbol=f.symbol,
                metadata_observed_at_utc=when,
                status=f.status,
                contract_type=f.contract_type,
                onboard_time_utc=f.onboard_time_utc,
                price_tick_size=f.price_tick_size,
                quantity_step_size=f.quantity_step_size,
                min_quantity=f.min_quantity,
                max_quantity=f.max_quantity,
                min_notional=f.min_notional,
                notional_constraints_json=f.notional_constraints_json,
                order_capabilities_json=f.order_capabilities_json,
                position_mode_snapshot_json=f.position_mode_snapshot_json,
                base_asset=f.base_asset,
                quote_asset=f.quote_asset,
                margin_asset=f.margin_asset,
            )
        )
        inserted += 1
    # Commit so the new versions are durable before the caller proceeds.
    # RESEARCH §Pattern 4: never UPDATE existing rows — versioned INSERT only.
    session.commit()
    return inserted
