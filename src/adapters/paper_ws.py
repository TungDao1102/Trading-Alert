"""Binance USDⓈ-M WebSocket Streams adapter for the paper loop (Phase 7, plan 07-01).

Per D-01 + RESEARCH §Pattern 1: this is the ONLY module in the project
allowed to import the `binance-sdk-derivatives-trading-usds-futures`
WebSocket Streams surface. The paper loop subscribes via this adapter
and receives frozen `Kline` instances — SDK response models never
leak into `src/paper/`.

Dataclass conventions mirror `src/adapters/binance_usdm.py`:
  - Prices / quantities are `Decimal` (no float for exchange-sensitive
    values per ENGINEERING_PRINCIPLES).
  - Timestamps are `datetime` with `tzinfo=UTC` (D-06).
  - All fields are `frozen=True` so an immutable value flows through
    the pipeline and cannot be accidentally mutated.

The adapter is constructible with an injected fake `ws_client` so unit
tests never touch the network. The fake client must expose
`kline_candlestick_streams(symbol, interval, id=None)` returning a
handle with `on_message(callback)` and `reconnect()` / `close()`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog
from binance_common.configuration import ConfigurationWebSocketStreams
from binance_sdk_derivatives_trading_usds_futures.websocket_streams import (
    DerivativesTradingUsdsFuturesWebSocketStreams,
)
from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.enums import (
    KlineCandlestickStreamsIntervalEnum,
)

log = structlog.get_logger()

# --------------------------------------------------------------------------- #
# Frozen domain dataclass — the public contract of the adapter.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Kline:
    """One kline row from a WS kline stream, normalized to project types.

    `close_time_utc <= now_utc` is the invariant callers MUST enforce
    before accepting a kline (RESEARCH §Pitfall 1 — never include the
    forming candle). `is_closed` is the WS `x` flag carried verbatim
    so the paper loop's double gate can short-circuit forming updates
    without re-parsing the wire payload.
    """

    symbol: str
    interval: str
    open_time_utc: datetime
    close_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trade_count: int
    is_closed: bool


# --------------------------------------------------------------------------- #
# Wire-format normalization.
# --------------------------------------------------------------------------- #


def _ms_to_utc(ms: int) -> datetime:
    """Convert a millisecond Unix epoch to a tz-aware UTC datetime.

    Exact timedelta arithmetic (WR-01) — never float division.
    """
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)


def _normalize_kline_payload(
    symbol: str,
    interval: str,
    payload: dict[str, Any],
) -> Kline:
    """Map a raw WS kline payload to a frozen `Kline`.

    The wire format uses Binance field names (t/T/o/h/l/c/v/n/x/q);
    the `Kline` uses the project's canonical field names. Decimal
    prices/quantities, UTC-aware datetimes.
    """
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=_ms_to_utc(int(payload["t"])),
        close_time_utc=_ms_to_utc(int(payload["T"])),
        open=Decimal(str(payload["o"])),
        high=Decimal(str(payload["h"])),
        low=Decimal(str(payload["l"])),
        close=Decimal(str(payload["c"])),
        volume=Decimal(str(payload["v"])),
        quote_volume=Decimal(str(payload.get("q", "0"))),
        trade_count=int(payload.get("n", 0)),
        is_closed=bool(payload.get("x", False)),
    )


# --------------------------------------------------------------------------- #
# Adapter — single owner of WS Streams imports.
# --------------------------------------------------------------------------- #


class PaperWsAdapter:
    """Project-owned wrapper around `DerivativesTradingUsdsFuturesWebSocketStreams`.

    Constructed without arguments → uses the default `prod` WS host.
    Tests inject a fake `ws_client` (any object exposing
    `kline_candlestick_streams(symbol, interval, id=None)` returning a
    handle with `on_message(callback)` and `reconnect()` / `close()`)
    so unit tests never touch the network.

    The adapter normalizes SDK response models to frozen `Kline`
    instances — SDK types never leak past the boundary.
    """

    def __init__(
        self,
        ws_client: DerivativesTradingUsdsFuturesWebSocketStreams | None = None,
        configuration: ConfigurationWebSocketStreams | None = None,
    ) -> None:
        if ws_client is not None:
            self._ws: DerivativesTradingUsdsFuturesWebSocketStreams = ws_client
        else:
            self._ws = DerivativesTradingUsdsFuturesWebSocketStreams(
                configuration or ConfigurationWebSocketStreams()
            )

    def subscribe(
        self,
        *,
        symbol: str,
        interval: str,
        on_kline: Callable[[Kline], None],
        stream_id: str | None = None,
    ) -> Any:
        """Subscribe to a kline stream and dispatch each event to `on_kline`.

        `symbol` is the lowercase Binance symbol (e.g. "btcusdt").
        `interval` is the canonical interval string (e.g. "1h", "4h").
        `on_kline` receives a frozen `Kline` per event.
        `stream_id` is an optional unique request ID.

        Returns the underlying SDK stream handle so callers can manage
        the subscription lifecycle (close, reconnect, etc.).
        """
        interval_enum = _interval_to_enum(interval)
        handle = self._ws.kline_candlestick_streams(
            symbol=symbol,
            interval=interval_enum,
            id=stream_id,
        )

        def _on_message(message: Any) -> None:
            # Hardened dispatch (CR-04): one malformed payload must
            # never propagate into the SDK dispatch thread and kill
            # the stream, and unknown envelopes must be logged, never
            # silently dropped.
            try:
                payload = _extract_kline_payload(message)
            except Exception as exc:
                log.warning(
                    "paper_ws.extract_failed",
                    error=repr(exc),
                    message_type=type(message).__name__,
                )
                return
            if payload is None:
                log.warning(
                    "paper_ws.unknown_envelope",
                    message_type=type(message).__name__,
                )
                return
            try:
                kline = _normalize_kline_payload(symbol, interval, payload)
            except (KeyError, TypeError, ValueError) as exc:
                log.warning(
                    "paper_ws.normalize_failed",
                    error=repr(exc),
                )
                return
            on_kline(kline)

        if hasattr(handle, "on_message"):
            handle.on_message(_on_message)
        else:
            # Fail loud (CR-04): returning a handle with no dispatch
            # registered is a silent dead subscription. The installed
            # SDK's RequestStreamHandle exposes on()/unsubscribe();
            # wiring dispatch onto it is pre-soak work — until then,
            # refuse loudly rather than stream into the void.
            log.error(
                "paper_ws.dispatch_unsupported",
                handle_type=type(handle).__name__,
            )
            raise RuntimeError(
                f"WS handle {type(handle).__name__} has no on_message; "
                "dispatch unwired (pre-soak wiring required)"
            )
        return handle

    def connect(self) -> Any:
        """Open the underlying WS connection (CR-04 connect path).

        Delegates to the SDK client's `create_connection()` entrypoint
        (verified on the installed
        `binance-sdk-derivatives-trading-usds-futures` streams client).
        Raises loudly when the client exposes no connection entrypoint.
        Full subscribe-against-live-connection smoke verification stays
        pre-soak work (the known BLOCKED gap) — this method makes the
        path explicit instead of absent.
        """
        for entry in ("create_connection", "init_connection", "connect"):
            factory = getattr(self._ws, entry, None)
            if callable(factory):
                return factory()
        log.error(
            "paper_ws.connect_unsupported",
            client_type=type(self._ws).__name__,
        )
        raise RuntimeError(f"WS client {type(self._ws).__name__} exposes no connection entrypoint")

    def reconnect(self, handle: Any) -> None:
        """Delegate reconnect to the SDK handle (fail-loud, CR-04)."""
        if hasattr(handle, "reconnect"):
            handle.reconnect()
        else:
            log.error(
                "paper_ws.reconnect_unsupported",
                handle_type=type(handle).__name__,
            )
            raise RuntimeError(
                f"WS handle {type(handle).__name__} has no reconnect; rotation impossible"
            )

    def schedule_reconnect(self, handle: Any) -> None:
        """Delegate schedule_reconnect to the SDK handle (fail-loud)."""
        if hasattr(handle, "schedule_reconnect"):
            handle.schedule_reconnect()
        else:
            log.error(
                "paper_ws.schedule_reconnect_unsupported",
                handle_type=type(handle).__name__,
            )
            raise RuntimeError(f"WS handle {type(handle).__name__} has no schedule_reconnect")

    def close(self, handle: Any) -> None:
        """Close the stream handle (fail-loud, CR-04)."""
        if hasattr(handle, "close"):
            handle.close()
        else:
            log.error(
                "paper_ws.close_unsupported",
                handle_type=type(handle).__name__,
            )
            raise RuntimeError(f"WS handle {type(handle).__name__} has no close")


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #


_INTERVAL_TO_ENUM: dict[str, KlineCandlestickStreamsIntervalEnum] = {
    "1m": KlineCandlestickStreamsIntervalEnum.INTERVAL_1m,
    "3m": KlineCandlestickStreamsIntervalEnum.INTERVAL_3m,
    "5m": KlineCandlestickStreamsIntervalEnum.INTERVAL_5m,
    "15m": KlineCandlestickStreamsIntervalEnum.INTERVAL_15m,
    "30m": KlineCandlestickStreamsIntervalEnum.INTERVAL_30m,
    "1h": KlineCandlestickStreamsIntervalEnum.INTERVAL_1h,
    "2h": KlineCandlestickStreamsIntervalEnum.INTERVAL_2h,
    "4h": KlineCandlestickStreamsIntervalEnum.INTERVAL_4h,
    "6h": KlineCandlestickStreamsIntervalEnum.INTERVAL_6h,
    "8h": KlineCandlestickStreamsIntervalEnum.INTERVAL_8h,
    "12h": KlineCandlestickStreamsIntervalEnum.INTERVAL_12h,
    "1d": KlineCandlestickStreamsIntervalEnum.INTERVAL_1d,
    "3d": KlineCandlestickStreamsIntervalEnum.INTERVAL_3d,
    "1w": KlineCandlestickStreamsIntervalEnum.INTERVAL_1w,
}


def _interval_to_enum(interval: str) -> KlineCandlestickStreamsIntervalEnum:
    """Map a canonical interval string to the SDK enum value."""
    enum_value = _INTERVAL_TO_ENUM.get(interval)
    if enum_value is None:
        raise ValueError(
            f"unsupported interval {interval!r}; supported: {sorted(_INTERVAL_TO_ENUM)}"
        )
    return enum_value


def _as_dict(value: Any) -> dict[str, Any] | None:
    """Coerce an SDK model to a plain dict, or None if impossible.

    The SDK may deliver response objects with attributes instead of
    raw dicts (CR-04) — support `dict` passthrough, `to_dict()` /
    `model_dump()` carriers, and `__dict__` attribute bags.
    """
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
        except Exception:
            return None
        return result if isinstance(result, dict) else None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            result = model_dump()
        except Exception:
            return None
        return result if isinstance(result, dict) else None
    bag = getattr(value, "__dict__", None)
    if isinstance(bag, dict) and bag:
        return dict(bag)
    return None


def _extract_kline_payload(message: Any) -> dict[str, Any] | None:
    """Extract the kline payload from a WS message.

    The SDK wraps kline events in a `{stream, data}` envelope; the
    `data` field carries the kline payload. This helper unwraps the
    envelope and returns the kline dict, or None if the message is
    not a kline event. Attribute-style SDK models are coerced via
    `_as_dict` so they are never silently dropped (CR-04). Bare
    kline-shaped dicts (wire fields, no envelope) are accepted; any
    other shape returns None and the caller logs the envelope type.
    """
    envelope = _as_dict(message)
    if envelope is None:
        return None
    if "data" in envelope:
        data_dict = _as_dict(envelope["data"])
        if data_dict is None:
            return None
        return _as_dict(data_dict.get("k"))
    if "k" in envelope:
        return _as_dict(envelope["k"])
    if "t" in envelope and "T" in envelope:
        return envelope
    return None


__all__ = ["Kline", "PaperWsAdapter"]
