"""Fakes for the symbol configuration guard tests (Phase 22, plan 22-11).

* ``StatefulConfigSdk`` stands in for the SDK ``rest_api`` object of the REAL
  ``BinanceUsdmAdapter``. It holds one symbol configuration (initially the recorded Demo
  fixture: CROSSED, leverage 20, isAutoAddMargin false, maxNotionalValue 20000000, demo-observed,
  not mainnet) and serves ``symbol_configuration``, ``change_margin_type`` and
  ``change_initial_leverage`` like the exchange would: a change updates the state, a scripted
  exception replaces an answer, a method in ``no_change`` answers 200 without changing anything,
  and every call is recorded in order. Any other SDK method name raises ``AttributeError``.
* ``ScriptedConfigAdapter`` stands in for the guard's ``SymbolConfigPort`` directly: per call it
  pops one scripted snapshot / outcome, so a test can script the exact read sequence (for
  example a race with a manual change). Any attribute that is not one of the three port methods
  raises ``AttributeError`` (the guard calls nothing else).

TEST_ONLY helpers; nothing here is a project value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from src.adapters.binance_ratelimit_gate import RestRateLimitGate
from src.adapters.binance_usdm import BinanceUsdmAdapter, SymbolConfigSnapshot

from tests.support.limits import test_only_signed_call_policy
from tests.support.phase22_fixtures import load_symbol_config

SYMBOL = "BTCUSDT"
_GATE_START = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)

READ = "symbol_configuration"
MARGIN_POST = "change_margin_type"
LEVERAGE_POST = "change_initial_leverage"


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class StatefulConfigSdk:
    """A stateful fake of the three SDK configuration methods; see the module docstring."""

    def __init__(
        self,
        *,
        symbol: str = SYMBOL,
        margin_type: str = "CROSSED",
        leverage: int = 20,
        auto_add: bool = False,
        max_notional: str = "20000000",
        max_notional_by_leverage: dict[int, str] | None = None,
    ) -> None:
        self.symbol = symbol
        self.margin_type = margin_type
        self.leverage = leverage
        self.auto_add = auto_add
        self.max_notional = max_notional
        # Demo, 2026-10-24 (R-1): after the change to x5 the answer carried 100000000.
        self._max_notional_by_leverage = (
            {5: "100000000"} if max_notional_by_leverage is None else max_notional_by_leverage
        )
        self.calls: list[str] = []
        self.margin_type_args: list[str] = []
        self.leverage_args: list[int] = []
        self.errors: dict[str, list[BaseException | None]] = {}
        self.no_change: set[str] = set()
        self.read_script: list[BaseException | SimpleNamespace | None] = []

    @classmethod
    def from_recorded(cls) -> StatefulConfigSdk:
        (row,) = load_symbol_config()
        return cls(
            symbol=row["symbol"],
            margin_type=row["marginType"],
            leverage=row["leverage"],
            auto_add=row["isAutoAddMargin"],
            max_notional=row["maxNotionalValue"],
        )

    def count(self, name: str) -> int:
        return self.calls.count(name)

    def _row(self) -> SimpleNamespace:
        return SimpleNamespace(
            symbol=self.symbol,
            margin_type=self.margin_type,
            leverage=self.leverage,
            is_auto_add_margin=self.auto_add,
            max_notional_value=self.max_notional,
        )

    def _scripted_error(self, name: str) -> BaseException | None:
        queue = self.errors.get(name)
        return queue.pop(0) if queue else None

    def symbol_configuration(self, **kwargs: Any) -> _Response:
        self.calls.append(READ)
        if self.read_script:
            scripted = self.read_script.pop(0)
            if isinstance(scripted, BaseException):
                raise scripted
            if scripted is not None:
                return _Response([scripted])
        error = self._scripted_error(READ)
        if error is not None:
            raise error
        return _Response([self._row()])

    def change_margin_type(self, **kwargs: Any) -> _Response:
        self.calls.append(MARGIN_POST)
        value = kwargs["margin_type"]
        self.margin_type_args.append(str(getattr(value, "value", value)))
        error = self._scripted_error(MARGIN_POST)
        if error is not None:
            raise error
        if MARGIN_POST not in self.no_change:
            self.margin_type = self.margin_type_args[-1]
        return _Response(SimpleNamespace(code=200, msg="success"))

    def change_initial_leverage(self, **kwargs: Any) -> _Response:
        self.calls.append(LEVERAGE_POST)
        self.leverage_args.append(kwargs["leverage"])
        error = self._scripted_error(LEVERAGE_POST)
        if error is not None:
            raise error
        if LEVERAGE_POST not in self.no_change:
            self.leverage = self.leverage_args[-1]
            self.max_notional = self._max_notional_by_leverage.get(self.leverage, self.max_notional)
        return _Response(SimpleNamespace(leverage=self.leverage))


def build_config_adapter(sdk: StatefulConfigSdk) -> BinanceUsdmAdapter:
    """The real adapter (TEST_ONLY policy and shared gate) over ``sdk``."""
    gate = RestRateLimitGate(
        policy=test_only_signed_call_policy().rate_limit, clock=lambda: _GATE_START
    )
    return BinanceUsdmAdapter(
        sdk_client=SimpleNamespace(rest_api=sdk),  # type: ignore[arg-type]
        rest_gate=gate,
        signed_call_policy=test_only_signed_call_policy(),
    )


def snapshot(
    *,
    margin_type: Any = "CROSSED",
    leverage: Any = 20,
    auto_add: Any = False,
    max_notional: Decimal = Decimal("20000000"),
    symbol: str = SYMBOL,
) -> SymbolConfigSnapshot:
    """A plain snapshot; the dataclass does not validate, so a test can build a bad one."""
    return SymbolConfigSnapshot(
        symbol=symbol,
        margin_type=margin_type,
        leverage=leverage,
        is_auto_add_margin=auto_add,
        max_notional_value=max_notional,
    )


class ScriptedConfigAdapter:
    """Scripted ``SymbolConfigPort``: ``reads`` and the two outcome queues are popped per call.

    A read entry is a snapshot or an exception (raised). An outcome entry is ``None`` (the POST
    answers) or an exception (raised). An empty queue is a test bug and raises AssertionError.
    ``calls`` records the order, ``margin_args`` / ``leverage_args`` the arguments of the POSTs.
    """

    def __init__(
        self,
        *,
        reads: list[Any],
        margin_outcomes: list[BaseException | None] | None = None,
        leverage_outcomes: list[BaseException | None] | None = None,
    ) -> None:
        self._reads = list(reads)
        self._margin = list(margin_outcomes or [])
        self._leverage = list(leverage_outcomes or [])
        self.calls: list[str] = []
        self.margin_args: list[tuple[str, str]] = []
        self.leverage_args: list[tuple[str, int]] = []

    def count(self, name: str) -> int:
        return self.calls.count(name)

    async def symbol_config_snapshot(self, *, symbol: str) -> Any:
        self.calls.append(READ)
        if not self._reads:
            raise AssertionError("no scripted read left")
        value = self._reads.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    async def change_margin_type(self, *, symbol: str, margin_type: str) -> None:
        self.calls.append(MARGIN_POST)
        self.margin_args.append((symbol, margin_type))
        outcome = self._margin.pop(0) if self._margin else None
        if outcome is not None:
            raise outcome

    async def change_initial_leverage(self, *, symbol: str, leverage: int) -> None:
        self.calls.append(LEVERAGE_POST)
        self.leverage_args.append((symbol, leverage))
        outcome = self._leverage.pop(0) if self._leverage else None
        if outcome is not None:
            raise outcome


__all__ = [
    "LEVERAGE_POST",
    "MARGIN_POST",
    "READ",
    "SYMBOL",
    "ScriptedConfigAdapter",
    "StatefulConfigSdk",
    "build_config_adapter",
    "snapshot",
]
