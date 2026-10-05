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
  - `contract_type` and `status` are String(32) columns (widened from 16 by
    migration 0004, D-09, F-403: TRADIFI_PERPETUAL is 17 characters and
    TRADING_CANCEL_ONLY 19). SQLite ignores the width and PostgreSQL rejects an
    overflow only at flush, so the width is checked here, derived from the
    model, and an overlong universe row raises instead of being truncated
    (fail closed, T-13-30).

This module is the only writer of `symbol_metadata` (`refresh_symbol_metadata`) and its
point-in-time reader for the backtest (`read_constraint_history`, Phase 14 D-17); other
consumers pin `metadata_observed_at_utc <= dataset_date` to reconstruct the rules in force
at any historical backtest point.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session
from src.adapters.binance_usdm import SymbolFilters
from src.db.models import SymbolMetadata


def _text_column_length(column_name: str) -> int:
    length = getattr(SymbolMetadata.__table__.c[column_name].type, "length", None)
    if not isinstance(length, int) or length <= 0:
        raise RuntimeError(f"symbol_metadata.{column_name} must be a bounded String column")
    return length


# Width of the `symbol_metadata.contract_type` and `.status` columns, derived from the
# model (the stricter of the two if they ever diverge). A longer value is never truncated.
METADATA_TEXT_MAX_LEN = min(_text_column_length("contract_type"), _text_column_length("status"))


class MetadataWidthError(ValueError):
    """A universe row's text field is wider than its bounded String column.

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
    selected = [f for f in filters if universe_set is None or f.symbol in universe_set]
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


def read_constraint_history(session: Session, symbols: Iterable[str]) -> list[dict[str, str]]:
    """Return every `symbol_metadata` version of `symbols` as case-input constraint rows (D-17).

    Each row has the shape `src.backtest.constraints.parse_constraint_row` parses: `symbol`,
    `metadata_observed_at_utc` (ISO-8601 UTC), and `price_tick_size`, `quantity_step_size`,
    `min_quantity`, `min_notional` as plain-notation Decimal text (no exponent, no trailing
    zeros). Rows are sorted by `(symbol, observed_at)`; the engine picks the version in force
    at each bar close, so the whole history is returned, not a snapshot.

    The query is an ORM `select` with bound parameters. A timestamp read back without a zone
    (SQLite in tests; PostgreSQL TIMESTAMPTZ is always aware) is the stored UTC value.

    Raises:
        ValueError: `symbols` is empty, or a requested symbol has no row (fail closed: the
            engine cannot size a trade without constraints).
    """
    wanted = sorted(set(symbols))
    if not wanted:
        raise ValueError("symbols must not be empty")
    statement = (
        select(
            SymbolMetadata.symbol,
            SymbolMetadata.metadata_observed_at_utc,
            SymbolMetadata.price_tick_size,
            SymbolMetadata.quantity_step_size,
            SymbolMetadata.min_quantity,
            SymbolMetadata.min_notional,
        )
        .where(SymbolMetadata.symbol.in_(wanted))
        .order_by(SymbolMetadata.symbol, SymbolMetadata.metadata_observed_at_utc)
    )
    found: list[tuple[str, datetime, dict[str, str]]] = []
    for symbol, observed, tick, step, min_qty, min_notional in session.execute(statement):
        observed_utc = (
            observed.replace(tzinfo=UTC) if observed.tzinfo is None else observed.astimezone(UTC)
        )
        found.append(
            (
                symbol,
                observed_utc,
                {
                    "symbol": symbol,
                    "metadata_observed_at_utc": observed_utc.isoformat(),
                    "price_tick_size": _plain_decimal(tick),
                    "quantity_step_size": _plain_decimal(step),
                    "min_quantity": _plain_decimal(min_qty),
                    "min_notional": _plain_decimal(min_notional),
                },
            )
        )
    present = {symbol for symbol, _, _ in found}
    missing = [symbol for symbol in wanted if symbol not in present]
    if missing:
        raise ValueError(f"symbol_metadata has no row for {missing}; refusing to run unsized")
    found.sort(key=lambda item: (item[0], item[1]))
    return [row for _, _, row in found]


def _plain_decimal(value: Decimal) -> str:
    """Plain-notation text of a stored Decimal, without the column scale padding."""
    return format(value.normalize(), "f")
