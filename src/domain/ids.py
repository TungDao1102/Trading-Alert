"""Content-hash ID constructors (Phase 3, plan 03-01).

Per D-03: SignalId = hash(strategyId + strategyVersion + parameterSetId
+ symbol + source_timeframe + source_candle_close_utc + setup
fingerprint). Plan/order IDs derive from their parent signal hash plus
a fixed discriminator.

The fingerprint is an opaque canonical-JSON string so Phase 4 can
widen it without changing the ID scheme.
"""

from __future__ import annotations

from datetime import datetime

from .canonical import sha256_hex


def make_signal_id(
    *,
    strategy_id: str,
    strategy_version: str,
    parameter_set_id: str,
    symbol: str,
    source_timeframe: str,
    source_candle_close_utc: datetime,
    setup_fingerprint: str,
) -> str:
    """Return the content-hash SignalId for the given identity tuple.

    D-03 binding superset: strategyId + strategyVersion + parameterSetId
    + symbol + source_timeframe + source_candle_close_utc +
    setup_fingerprint. `strategy_id` is required: two strategies sharing
    version/id/symbol/time/close/fingerprint must not collide.
    """
    return sha256_hex(
        {
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "parameter_set_id": parameter_set_id,
            "symbol": symbol,
            "source_timeframe": source_timeframe,
            "source_candle_close_utc": source_candle_close_utc,
            "setup_fingerprint": setup_fingerprint,
        }
    )


def derive_child_id(parent_signal_id: str, discriminator: str) -> str:
    """Derive a child ID (plan/order) from a parent signal hash.

    Plan/order IDs: parent hash + fixed discriminator
    (e.g. "trade_plan:v1", "order:entry").
    """
    return sha256_hex(
        {
            "parent_signal_id": parent_signal_id,
            "discriminator": discriminator,
        }
    )
