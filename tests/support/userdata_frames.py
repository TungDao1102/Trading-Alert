"""Synthetic user-data stream frames (Phase 18, plan 18-03).

Every frame built here is SYNTHETIC: it was written by hand from the field
set and the Python types of the installed SDK models
(`binance_sdk_derivatives_trading_usds_futures/websocket_streams/models/`,
read as files, never executed against Binance). It is NOT captured Binance
data. Strings carry money, quantities and prices; ints carry ids and
millisecond times; bools carry flags, exactly as the SDK `Strict*` types
declare them. Recorded demo frames (plan 18-21) replace or complement these.

The JSON file form of these frames and their provenance README are written by
plan 18-24 from these builders.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

FRAME_LABEL = "SYNTHETIC_FROM_SDK_MODEL"


class _Omit:
    """Sentinel type: an override with this value removes the key from the frame."""

    def __repr__(self) -> str:
        return "OMIT"


OMIT: Any = _Omit()

# Synthetic times (milliseconds since the Unix epoch). Not taken from any capture.
SYNTHETIC_EVENT_TIME_MS = 1_760_000_000_123
SYNTHETIC_TRANSACTION_TIME_MS = 1_760_000_000_120
SYNTHETIC_TRADE_TIME_MS = 1_760_000_000_119


def _apply(base: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overrides.items():
        if value is OMIT:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def order_trade_update_frame(
    *, event_overrides: Mapping[str, Any] | None = None, **order_overrides: Any
) -> dict[str, Any]:
    """A complete synthetic ORDER_TRADE_UPDATE frame (a TRADE, partially filled).

    Keyword overrides replace keys of the `o` object (`OMIT` removes one);
    `event_overrides` replaces top-level keys (`e`, `E`, `T`, `o`).

    The default omits the conditional `o` keys the SDK model documents as
    pushed only in some cases: `M` (AMENDMENT only), `AP` and `cr` (trailing
    stop only) and `er` (expiry reason).
    """
    order: dict[str, Any] = {
        "s": "BTCUSDT",
        "c": "synthetic-entry-0001",
        "S": "BUY",
        "o": "LIMIT",
        "f": "GTC",
        "q": "0.010",
        "p": "60000.00",
        "ap": "60000.00",
        "sp": "0",
        "x": "TRADE",
        "X": "PARTIALLY_FILLED",
        "i": 8_000_000_001,
        "l": "0.004",
        "z": "0.004",
        "L": "60000.00",
        "N": "USDT",
        "n": "0.09600000",
        "T": SYNTHETIC_TRADE_TIME_MS,
        "t": 900_000_001,
        "b": "0",
        "a": "0",
        "m": False,
        "R": False,
        "wt": "CONTRACT_PRICE",
        "ot": "LIMIT",
        "ps": "BOTH",
        "cp": False,
        "pP": False,
        "si": 0,
        "ss": 0,
        "rp": "0",
        "V": "EXPIRE_TAKER",
        "pm": "NONE",
        "gtd": 0,
    }
    frame: dict[str, Any] = {
        "e": "ORDER_TRADE_UPDATE",
        "E": SYNTHETIC_EVENT_TIME_MS,
        "T": SYNTHETIC_TRANSACTION_TIME_MS,
        "o": _apply(order, order_overrides),
    }
    return _apply(frame, event_overrides or {})


__all__ = [
    "FRAME_LABEL",
    "OMIT",
    "SYNTHETIC_EVENT_TIME_MS",
    "SYNTHETIC_TRADE_TIME_MS",
    "SYNTHETIC_TRANSACTION_TIME_MS",
    "order_trade_update_frame",
]
