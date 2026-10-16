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
    stop only) and `er` (expiry reason). It carries `cp` and `pP` (bools) and
    `gtd` (int) because the event keeps them (decisions/18-DEC-D01, amend);
    pass `AP="..."` and `cr="..."` (decimal text) for a trailing-stop frame.
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


# A synthetic, obviously fake listenKey. It is NOT a credential and was never
# issued by Binance; the tests use it to prove that no listenKey value ever
# reaches an event, an anomaly or a repr.
SYNTHETIC_LISTEN_KEY = "SYNTHETIC-DUMMY-LISTEN-KEY-not-a-credential-0000"


def algo_update_frame(
    *, event_overrides: Mapping[str, Any] | None = None, **algo_overrides: Any
) -> dict[str, Any]:
    """A complete synthetic ALGO_UPDATE frame (a STOP_MARKET conditional, status NEW).

    Field set and Python types follow `algo_update_o.py` (SDK 17.4.0): `aid`,
    `tt` and `gtd` are ints; `cp`, `pP`, `R` and `ia` are bools; everything
    else is text. `ai` is the empty string before the trigger (SDK `StrictStr`
    "Order Id"); `ap`, `aq` and `act` are omitted because the SDK documents
    them as "only display when order is triggered"; `rm` ("Algo order failed
    reason") is omitted because this default is not a rejection (an empty
    optional text is a FIELD_VALIDATION anomaly, decisions/18-DEC-D01 Q5;
    whether Binance sends `rm: ""` is UNVERIFIED). Keyword overrides replace
    keys of the `o` object (`OMIT` removes one); `event_overrides` replaces
    top-level keys.
    """
    algo: dict[str, Any] = {
        "caid": "synthetic-sl-0001",
        "aid": 7_000_000_001,
        "at": "CONDITIONAL",
        "o": "STOP_MARKET",
        "s": "BTCUSDT",
        "S": "SELL",
        "ps": "BOTH",
        "f": "GTC",
        "q": "0.010",
        "X": "NEW",
        "ai": "",
        "tp": "58000.00",
        "p": "0",
        "V": "EXPIRE_MAKER",
        "wt": "MARK_PRICE",
        "pm": "NONE",
        "cp": False,
        "pP": False,
        "R": True,
        "tt": 0,
        "gtd": 0,
        "ia": False,
    }
    frame: dict[str, Any] = {
        "e": "ALGO_UPDATE",
        "T": SYNTHETIC_TRANSACTION_TIME_MS,
        "E": SYNTHETIC_EVENT_TIME_MS,
        "o": _apply(algo, algo_overrides),
    }
    return _apply(frame, event_overrides or {})


def balance_row(**overrides: Any) -> dict[str, Any]:
    """One synthetic `a.B` row of ACCOUNT_UPDATE (`account_update_ab_inner.py`: all text)."""
    row: dict[str, Any] = {
        "a": "USDT",
        "wb": "1000.12345678",
        "cw": "1000.12345678",
        "bc": "0",
    }
    return _apply(row, overrides)


def position_row(**overrides: Any) -> dict[str, Any]:
    """One synthetic `a.P` row of ACCOUNT_UPDATE (`account_update_ap_inner.py`: all text).

    The default is a short position, so `pa` is negative (signed).
    """
    row: dict[str, Any] = {
        "s": "BTCUSDT",
        "pa": "-0.010",
        "ep": "60000.00",
        "bep": "60024.00",
        "cr": "0",
        "up": "1.20000000",
        "mt": "cross",
        "iw": "0",
        "ps": "BOTH",
    }
    return _apply(row, overrides)


def account_update_frame(
    *, event_overrides: Mapping[str, Any] | None = None, **account_overrides: Any
) -> dict[str, Any]:
    """A complete synthetic ACCOUNT_UPDATE frame (reason ORDER, one balance and one position row).

    Keyword overrides replace keys of the `a` object (`m`, `B`, `P`, `S`;
    `OMIT` removes one); build rows with `balance_row` and `position_row`.
    The default carries no `S` (the SDK documents it for FUNDING_FEE only).
    """
    account: dict[str, Any] = {
        "m": "ORDER",
        "B": [balance_row()],
        "P": [position_row()],
    }
    frame: dict[str, Any] = {
        "e": "ACCOUNT_UPDATE",
        "E": SYNTHETIC_EVENT_TIME_MS,
        "T": SYNTHETIC_TRANSACTION_TIME_MS,
        "a": _apply(account, account_overrides),
    }
    return _apply(frame, event_overrides or {})


def listen_key_expired_frame(**event_overrides: Any) -> dict[str, Any]:
    """A synthetic listenKeyExpired frame carrying the DUMMY key `SYNTHETIC_LISTEN_KEY`.

    The SDK model (`listen_key_expired.py`) has `E` and `listenKey`; the key
    here is a synthetic placeholder, never a real credential.
    """
    frame: dict[str, Any] = {
        "e": "listenKeyExpired",
        "E": SYNTHETIC_EVENT_TIME_MS,
        "listenKey": SYNTHETIC_LISTEN_KEY,
    }
    return _apply(frame, event_overrides)


def account_config_update_frame(**event_overrides: Any) -> dict[str, Any]:
    """A synthetic ACCOUNT_CONFIG_UPDATE frame (a leverage change: `ac.s`, `ac.l` int).

    For a Multi-Assets mode change pass `ac=OMIT, ai={"j": True}`
    (`account_config_update_ai.py`: `j` is a bool).
    """
    frame: dict[str, Any] = {
        "e": "ACCOUNT_CONFIG_UPDATE",
        "E": SYNTHETIC_EVENT_TIME_MS,
        "T": SYNTHETIC_TRANSACTION_TIME_MS,
        "ac": {"s": "BTCUSDT", "l": 5},
    }
    return _apply(frame, event_overrides)


def trade_lite_frame(**event_overrides: Any) -> dict[str, Any]:
    """A synthetic TRADE_LITE frame (`trade_lite.py`); the project ignores this event."""
    frame: dict[str, Any] = {
        "e": "TRADE_LITE",
        "E": SYNTHETIC_EVENT_TIME_MS,
        "T": SYNTHETIC_TRANSACTION_TIME_MS,
        "s": "BTCUSDT",
        "q": "0.010",
        "p": "60000.00",
        "m": False,
        "c": "synthetic-entry-0001",
        "S": "BUY",
        "L": "60000.00",
        "l": "0.004",
        "t": 900_000_001,
        "i": 8_000_000_001,
    }
    return _apply(frame, event_overrides)


def strategy_update_frame(**event_overrides: Any) -> dict[str, Any]:
    """A synthetic STRATEGY_UPDATE frame (`strategy_update_su.py`); ignored by the project."""
    frame: dict[str, Any] = {
        "e": "STRATEGY_UPDATE",
        "T": SYNTHETIC_TRANSACTION_TIME_MS,
        "E": SYNTHETIC_EVENT_TIME_MS,
        "su": {
            "si": 1,
            "st": "GRID",
            "ss": "NEW",
            "s": "BTCUSDT",
            "ut": SYNTHETIC_TRANSACTION_TIME_MS,
            "c": 8001,
        },
    }
    return _apply(frame, event_overrides)


def grid_update_frame(**event_overrides: Any) -> dict[str, Any]:
    """A synthetic GRID_UPDATE frame (`grid_update_gu.py`); ignored by the project."""
    frame: dict[str, Any] = {
        "e": "GRID_UPDATE",
        "T": SYNTHETIC_TRANSACTION_TIME_MS,
        "E": SYNTHETIC_EVENT_TIME_MS,
        "gu": {
            "si": 1,
            "st": "GRID",
            "ss": "WORKING",
            "s": "BTCUSDT",
            "r": "0",
            "up": "0",
            "uq": "0",
            "uf": "0",
            "mp": "0",
            "ut": SYNTHETIC_TRANSACTION_TIME_MS,
        },
    }
    return _apply(frame, event_overrides)


def margin_call_frame(**event_overrides: Any) -> dict[str, Any]:
    """A synthetic MARGIN_CALL frame (`margin_call.py`); unhandled until Phase 22."""
    frame: dict[str, Any] = {
        "e": "MARGIN_CALL",
        "E": SYNTHETIC_EVENT_TIME_MS,
        "cw": "3.16812045",
        "p": [
            {
                "s": "BTCUSDT",
                "ps": "BOTH",
                "pa": "-0.010",
                "mt": "CROSSED",
                "iw": "0",
                "mp": "61000.00",
                "up": "-10.00",
                "mm": "2.44",
            }
        ],
    }
    return _apply(frame, event_overrides)


def conditional_order_trigger_reject_frame(**event_overrides: Any) -> dict[str, Any]:
    """A synthetic CONDITIONAL_ORDER_TRIGGER_REJECT frame (deprecated event type)."""
    frame: dict[str, Any] = {
        "e": "CONDITIONAL_ORDER_TRIGGER_REJECT",
        "E": SYNTHETIC_EVENT_TIME_MS,
        "T": SYNTHETIC_TRANSACTION_TIME_MS,
        "or": {"s": "BTCUSDT", "i": 8_000_000_001, "r": "Synthetic reject reason"},
    }
    return _apply(frame, event_overrides)


__all__ = [
    "FRAME_LABEL",
    "OMIT",
    "SYNTHETIC_EVENT_TIME_MS",
    "SYNTHETIC_LISTEN_KEY",
    "SYNTHETIC_TRADE_TIME_MS",
    "SYNTHETIC_TRANSACTION_TIME_MS",
    "account_config_update_frame",
    "account_update_frame",
    "algo_update_frame",
    "balance_row",
    "conditional_order_trigger_reject_frame",
    "grid_update_frame",
    "listen_key_expired_frame",
    "margin_call_frame",
    "order_trade_update_frame",
    "position_row",
    "strategy_update_frame",
    "trade_lite_frame",
]
