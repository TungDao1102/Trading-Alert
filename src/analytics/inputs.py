"""Backtest input normalization (Phase 10, plan 10-01, D-02).

`normalize_backtest` converts Phase-6 `TradeRecord`s into `TradeOutcome`s.
Risk-rejected plans (`outcome_kind == "REJECT"`) become `NoTradeRecord`s and are
never `TradeOutcome`s. Nothing is imputed: missing fields stay None and are
counted downstream as INCOMPLETE.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from src.analytics.types import (
    AnalyticsInputError,
    BacktestNormalization,
    EvidenceKind,
    NoTradeRecord,
    OutcomeContext,
    TradeOutcome,
)
from src.backtest.simulator import TradeRecord
from src.backtest.validator import TradeRecordInvariantError, validate_trade_record


def normalize_backtest(
    trades: Sequence[TradeRecord],
    contexts: Mapping[str, OutcomeContext] | None = None,
) -> BacktestNormalization:
    """Normalize TradeRecords (sorted by trade_id) into outcomes and NO_TRADE rejects.

    Every record passes the shared temporal validator first (D-23, F-804). No data window
    is known here, so only the window-independent invariants run; a violation is re-raised
    as `AnalyticsInputError` chained from `TradeRecordInvariantError`.
    """
    context_by_id: Mapping[str, OutcomeContext] = contexts if contexts is not None else {}
    outcomes: list[TradeOutcome] = []
    rejects: list[NoTradeRecord] = []
    seen: set[str] = set()
    for trade in sorted(trades, key=lambda record: record.trade_id):
        if trade.trade_id in seen:
            raise AnalyticsInputError(f"duplicate trade_id {trade.trade_id!r}")
        seen.add(trade.trade_id)
        try:
            validate_trade_record(trade)
        except TradeRecordInvariantError as error:
            raise AnalyticsInputError(
                f"trade {trade.trade_id!r} violates a record invariant: {error}"
            ) from error
        if trade.outcome_kind == "REJECT":
            rejects.append(
                NoTradeRecord(
                    evidence=EvidenceKind.BACKTEST,
                    symbol=trade.symbol,
                    reason_code=trade.reason_code,
                    source_id=trade.trade_id,
                )
            )
            continue
        context = context_by_id.get(trade.trade_id)
        outcomes.append(
            TradeOutcome(
                evidence=EvidenceKind.BACKTEST,
                trade_id=trade.trade_id,
                signal_id=trade.signal_id,
                strategy_version=trade.strategy_version,
                parameter_set_hash=trade.parameter_set_hash,
                symbol=trade.symbol,
                direction=trade.direction,
                entry_kind=trade.entry_kind,
                entry_price=trade.entry_price,
                entry_time_utc=trade.entry_time_utc,
                exit_kind=trade.exit_kind,
                exit_price=trade.exit_price,
                exit_time_utc=trade.exit_time_utc,
                quantity=trade.quantity,
                realized_pnl=trade.realized_pnl,
                realized_risk=trade.realized_risk,
                fallback_applied=trade.fallback_applied,
                intended_entry_price=None if context is None else context.intended_entry_price,
                regime=None if context is None else context.regime,
                vol_regime=None if context is None else context.vol_regime,
                coverage_note=trade.coverage_note,
            )
        )
    return BacktestNormalization(outcomes=tuple(outcomes), rejects=tuple(rejects))
