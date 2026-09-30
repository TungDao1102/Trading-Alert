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
    Callers pass one (D-29): the backfill CLI always passes its resolved
    research universe, so exotic contract types outside it (for example
    `TRADIFI_PERPETUAL`, 17 characters) never reach the table. Symbols not
    in the universe are silently skipped — they do NOT cause a failure.
  - Delisted and non-TRADING universe symbols (SETTLING, PENDING_TRADING,
    ...) present in exchangeInfo are inserted as ordinary versioned rows
    with their status preserved (D-10); history is never updated in place.
  - `contract_type` and `status` are String(16) columns. SQLite ignores the
    width and PostgreSQL rejects an overflow only at flush, so the width is
    checked here and an overlong universe row raises instead of being
    truncated (fail closed, T-13-30). No column is widened (no migration).

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

# Width of the `symbol_metadata.contract_type` and `.status` columns
# (String(16), src/db/models.py). A longer value is never truncated.
METADATA_TEXT_MAX_LEN = 16


class MetadataWidthError(ValueError):
    """A universe row's text field is wider than its String(16) column.

    The message names the symbol, field and length only, never a value that
    could be mistaken for a credential, so callers may print it.
    """


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
            set is silently skipped (no error). `None` inserts everything;
            callers should pass one (D-29).

    Returns:
        Number of rows inserted (i.e. `len(filters)` after universe
        filtering).

    Raises:
        MetadataWidthError: a selected row's `contract_type` or `status` is
            longer than `METADATA_TEXT_MAX_LEN`; nothing is inserted.
    """
    when = observed_at if observed_at is not None else datetime.now(UTC)
    universe_set = set(universe) if universe is not None else None
    selected = [
        f for f in filters if universe_set is None or f.symbol in universe_set
    ]
    # Validate every selected row BEFORE any session.add so a violation leaves
    # nothing pending: roll back and raise, never truncate (fail closed).
    for f in selected:
        for field_name, text in (("contract_type", f.contract_type), ("status", f.status)):
            if len(text) > METADATA_TEXT_MAX_LEN:
                session.rollback()
                raise MetadataWidthError(
                    f"{f.symbol}: {field_name} is {len(text)} characters, longer than "
                    f"the {METADATA_TEXT_MAX_LEN}-character column; refusing to truncate"
                )
    inserted = 0
    for f in selected:
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
