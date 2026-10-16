"""SDK-shaped fakes for the probe adapter tests (plan 18-12) and probe ports (plan 18-17).

The second half (plan 18-17) holds `FakeProbePort` and `RecordingProbePort`, project-level
ports of `scripts/demo_probe.py` that answer with `ProbeObservation` values, and a TEST_ONLY
probe limits writer.

`FakeProbeRest` has one method per installed SDK REST method name the probe adapter calls.
Each records the keyword arguments it received (and the thread it ran on), then returns a
scripted payload wrapped like the SDK's `ApiResponse` (`.data()`), or raises a scripted
exception. Nothing here opens a connection, reads the environment or builds an SDK client.
`tests/test_binance_probe_contract.py` binds every recorded call against the installed SDK
method signature, so a fake that accepts a keyword the SDK does not would be caught there.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.adapters.binance_probe import ErrorObservation, ProbeObservation
from src.adapters.binance_public import BinancePublicMarketData
from src.adapters.binance_ratelimit_gate import RestRateLimitGate

from tests.support.limits import test_only_rate_limit_policy

# The virtual clock's start; any timezone-aware instant works, the gate only compares.
TEST_ONLY_CLOCK_START = datetime(2026, 10, 16, 6, 0, 0, tzinfo=UTC)


class FakeResponse:
    """The `ApiResponse` surface the adapter reads: `data()`."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class FakeProbeRest:
    """Records every SDK call; answers from a per-method script (payload or exception)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.thread_ids: list[int] = []
        self._script: dict[str, list[object]] = {}

    def script(self, name: str, *outcomes: object) -> None:
        """Queue answers for `name`; an exception instance is raised, anything else returned."""
        self._script.setdefault(name, []).extend(outcomes)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def _answer(self, name: str, kwargs: dict[str, Any]) -> FakeResponse:
        self.calls.append((name, dict(kwargs)))
        self.thread_ids.append(threading.get_ident())
        queue = self._script.get(name)
        if not queue:
            raise AssertionError(f"unscripted SDK call: {name}")
        outcome = queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(outcome)

    # ----- queries (plan 18-12 Task 1) ----------------------------------- #

    def query_order(self, **kwargs: Any) -> FakeResponse:
        return self._answer("query_order", kwargs)

    def query_algo_order(self, **kwargs: Any) -> FakeResponse:
        return self._answer("query_algo_order", kwargs)

    # ----- placements and cancels (plan 18-12 Task 2) -------------------- #

    def new_order(self, **kwargs: Any) -> FakeResponse:
        return self._answer("new_order", kwargs)

    def new_algo_order(self, **kwargs: Any) -> FakeResponse:
        return self._answer("new_algo_order", kwargs)

    def cancel_order(self, **kwargs: Any) -> FakeResponse:
        return self._answer("cancel_order", kwargs)

    def cancel_algo_order(self, **kwargs: Any) -> FakeResponse:
        return self._answer("cancel_algo_order", kwargs)

    def cancel_all_open_orders(self, **kwargs: Any) -> FakeResponse:
        return self._answer("cancel_all_open_orders", kwargs)

    def cancel_all_algo_open_orders(self, **kwargs: Any) -> FakeResponse:
        return self._answer("cancel_all_algo_open_orders", kwargs)

    # ----- state capture (plan 18-12 Task 3) ----------------------------- #

    def current_all_open_orders(self, **kwargs: Any) -> FakeResponse:
        return self._answer("current_all_open_orders", kwargs)

    def current_all_algo_open_orders(self, **kwargs: Any) -> FakeResponse:
        return self._answer("current_all_algo_open_orders", kwargs)

    def position_information_v3(self, **kwargs: Any) -> FakeResponse:
        return self._answer("position_information_v3", kwargs)

    def account_trade_list(self, **kwargs: Any) -> FakeResponse:
        return self._answer("account_trade_list", kwargs)

    def futures_account_balance_v3(self, **kwargs: Any) -> FakeResponse:
        return self._answer("futures_account_balance_v3", kwargs)

    # ----- public reads, reached through BinancePublicMarketData --------- #

    def mark_price_kline_candlestick_data(self, **kwargs: Any) -> FakeResponse:
        return self._answer("mark_price_kline_candlestick_data", kwargs)

    def exchange_information(self, **kwargs: Any) -> FakeResponse:
        return self._answer("exchange_information", kwargs)


class FakeProbeSdk:
    """The `DerivativesTradingUsdsFutures` surface the adapter reads: `rest_api`."""

    def __init__(self, rest: FakeProbeRest | None = None) -> None:
        self.rest_api = rest if rest is not None else FakeProbeRest()


class VirtualClock:
    """A settable timezone-aware clock shared by the gate and the test."""

    def __init__(self, start: datetime = TEST_ONLY_CLOCK_START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def make_gate(clock: VirtualClock | None = None) -> RestRateLimitGate:
    """A gate holding the TEST_ONLY rate-limit policy and a virtual clock."""
    return RestRateLimitGate(
        policy=test_only_rate_limit_policy(),
        clock=clock if clock is not None else VirtualClock(),
    )


def make_public(rest: FakeProbeRest, gate: RestRateLimitGate) -> BinancePublicMarketData:
    """The real public reader over the fake REST object, holding `gate` (as plan 18-17 does)."""
    return BinancePublicMarketData(sdk_client=FakeProbeSdk(rest), rest_gate=gate)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Project-level probe ports (plan 18-17): the `ProbePort` of `scripts/demo_probe.py`.
#
# These fakes answer at the level of `BinanceProbeAdapter` (frozen `ProbeObservation`
# values), not at the SDK level. Nothing here imports the script, opens a connection, reads
# the environment or sleeps. Every value is FAKE.
# --------------------------------------------------------------------------- #

# The static market fixture of the dry run and of the fakes (FAKE values, never Binance data).
FAKE_LABEL = "FAKE"
FAKE_MARK_PRICE = "60000.00"
FAKE_SYMBOL_FILTERS: dict[str, str] = {
    "status": "TRADING",
    "tick_size": "0.10",
    "step_size": "0.001",
    "min_quantity": "0.001",
    "max_quantity": "1000",
    "min_notional": "100",
    "market_lot_min_quantity": "0.001",
    "market_lot_max_quantity": "120",
    "market_lot_step_size": "0.001",
    "percent_price_multiplier_up": "1.0500",
    "percent_price_multiplier_down": "0.9500",
    "percent_price_multiplier_decimals": "4",
}
FAKE_BALANCE_ASSET = "USDT"
FAKE_BALANCE = "5000.00000000"
FAKE_DRY_RUN_SUMMARY: dict[str, str] = {"dry_run": "true"}

# The probe-adapter operations that change exchange state (orders, cancels).
MUTATING_OPERATIONS: frozenset[str] = frozenset(
    {
        "new_limit_order",
        "new_market_order",
        "new_conditional_order",
        "cancel_order",
        "cancel_algo_order",
        "cancel_all_open_orders",
        "cancel_all_algo_open_orders",
    }
)
# The per-case requests (reads a case sends about one id): recorded as planned in a dry run.
CASE_QUERY_OPERATIONS: frozenset[str] = frozenset({"query_order", "query_algo_order"})


def ok_observation(operation: str, summary: dict[str, str] | None = None) -> ProbeObservation:
    """An accepted answer with a text summary."""
    return ProbeObservation(operation=operation, ok=True, summary=summary or {}, error=None)


def error_observation(
    operation: str,
    *,
    code: int | None,
    category: str,
    http_class: str = "BAD_REQUEST",
    message: str = "FAKE exchange message",
    retry_after_seconds: int | None = None,
) -> ProbeObservation:
    """An exchange error recorded as data (as `BinanceProbeAdapter` records it)."""
    return ProbeObservation(
        operation=operation,
        ok=False,
        summary={},
        error=ErrorObservation(
            http_class=http_class,
            code=code,
            retry_after_seconds=retry_after_seconds,
            category=category,
            message=message,
        ),
    )


def fake_mark_price(symbol: str) -> ProbeObservation:
    return ok_observation(
        "mark_price",
        {"symbol": symbol, "interval": "1m", "count": "1", "close": FAKE_MARK_PRICE},
    )


def fake_symbol_filters(symbol: str) -> ProbeObservation:
    return ok_observation(
        "symbol_filters", {"symbol": symbol, "found": "true", **FAKE_SYMBOL_FILTERS}
    )


TEST_ONLY_CASE_TIMEOUT_SECONDS = 30
TEST_ONLY_CLEANUP_TIMEOUT_SECONDS = 60

_TEST_ONLY_PROBE_LIMITS = """
[order]
symbol = "{symbol}"
quantity = "0.002"
max_notional_quote = "150"
far_price_fraction = "0.80"
{extra_order}
[waits]
case_timeout_seconds = {case_timeout}
cleanup_timeout_seconds = {cleanup_timeout}

[optional_cases]
explicit_time_in_force = {explicit_time_in_force}
stream_gap = {stream_gap}
market_lot_size_out_of_range = {market_lot}
"""


def write_probe_limits(
    directory: Path,
    *,
    symbol: str = "BTCUSDT",
    optional: tuple[str, ...] = (),
    name: str = "probe-limits.toml",
) -> Path:
    """A TEST_ONLY probe limits file (the owner writes the real one at plan 18-20)."""
    market_lot = "market_lot_size_out_of_range" in optional
    text = _TEST_ONLY_PROBE_LIMITS.format(
        symbol=symbol,
        extra_order='market_lot_probe_quantity = "200"\n' if market_lot else "",
        case_timeout=TEST_ONLY_CASE_TIMEOUT_SECONDS,
        cleanup_timeout=TEST_ONLY_CLEANUP_TIMEOUT_SECONDS,
        explicit_time_in_force=str("explicit_time_in_force" in optional).lower(),
        stream_gap=str("stream_gap" in optional).lower(),
        market_lot=str(market_lot).lower(),
    )
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _rows(prefix_rows: list[dict[str, str]]) -> dict[str, str]:
    out = {"count": str(len(prefix_rows))}
    for index, row in enumerate(prefix_rows):
        for name, value in row.items():
            out[f"row_{index}_{name}"] = value
    return out


class _Sequence:
    """One sequence number shared by the frame, raw-frame and state logs of a fake port."""

    def __init__(self) -> None:
        self.value = 0

    def next(self) -> int:
        self.value += 1
        return self.value


class FakeProbePort:
    """A scriptable `ProbePort` with a small exchange state, for the case-logic tests.

    Every call is recorded in `calls` as (operation, kwargs). An answer comes, in order, from
    `script_call(operation, index, answer)` (the answer of that call index of the operation),
    from `script(operation, *answers)` (a queue), or from the default derived from the state:
    open order ids, open algo ids, position rows and trades. A scripted answer that is an
    exception instance is raised (for example `ProbeBanned`). `flatten_takes_effect=False`
    keeps a position after a reduce-only market order (the CLEANUP_FAILED path).
    """

    def __init__(self, *, symbol: str = "BTCUSDT", dual_side: bool = False) -> None:
        self.symbol = symbol
        self.dual_side = dual_side
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._by_index: dict[str, dict[int, object]] = {}
        self._queued: dict[str, list[object]] = {}
        self.open_order_ids: list[str] = []
        self.open_algo_ids: list[str] = []
        self.positions_rows: list[tuple[str, Decimal]] = []
        self.trades: list[dict[str, str]] = []
        self.flatten_takes_effect = True
        self.stream_running = False
        self._sequence = _Sequence()
        self.frame_log: list[tuple[int, dict[str, str]]] = []
        self.raw_log: list[tuple[int, object]] = []
        self.state_log: list[tuple[int, str]] = []
        self.drop_results: list[bool] = []

    # ----- scripting --------------------------------------------------------- #

    def script(self, operation: str, *answers: object) -> None:
        self._queued.setdefault(operation, []).extend(answers)

    def script_call(self, operation: str, index: int, answer: object) -> None:
        self._by_index.setdefault(operation, {})[index] = answer

    def count(self, operation: str) -> int:
        return sum(1 for name, _ in self.calls if name == operation)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def emit_frame(self, record: dict[str, str], raw: object | None = None) -> None:
        self.frame_log.append((self._sequence.next(), dict(record)))
        if raw is not None:
            self.raw_log.append((self._sequence.next(), raw))

    def emit_state(self, state: str) -> None:
        self.state_log.append((self._sequence.next(), state))

    def _answer(self, operation: str, kwargs: dict[str, Any], default: Any) -> ProbeObservation:
        index = self.count(operation)
        self.calls.append((operation, dict(kwargs)))
        answer: object | None = self._by_index.get(operation, {}).pop(index, None)
        if answer is None and self._queued.get(operation):
            answer = self._queued[operation].pop(0)
        if answer is None:
            answer = default()
        if isinstance(answer, BaseException):
            raise answer
        assert isinstance(answer, ProbeObservation), answer
        return answer

    # ----- the adapter operations -------------------------------------------- #

    async def query_order(self, *, symbol: str, client_order_id: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            if client_order_id in self.open_order_ids:
                return ok_observation(
                    "query_order", {"client_order_id": client_order_id, "status": "NEW"}
                )
            return error_observation("query_order", code=-2013, category="ORDER_ABSENT")

        return self._answer(
            "query_order", {"symbol": symbol, "client_order_id": client_order_id}, default
        )

    async def query_algo_order(self, *, client_algo_id: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            if client_algo_id in self.open_algo_ids:
                return ok_observation(
                    "query_algo_order", {"client_algo_id": client_algo_id, "algo_status": "NEW"}
                )
            return error_observation("query_algo_order", code=-2013, category="ORDER_ABSENT")

        return self._answer("query_algo_order", {"client_algo_id": client_algo_id}, default)

    async def new_limit_order(self, **kwargs: Any) -> ProbeObservation:
        def default() -> ProbeObservation:
            self.open_order_ids.append(kwargs["client_order_id"])
            return ok_observation(
                "new_limit_order", {"client_order_id": kwargs["client_order_id"], "status": "NEW"}
            )

        return self._answer("new_limit_order", kwargs, default)

    async def new_market_order(self, **kwargs: Any) -> ProbeObservation:
        def default() -> ProbeObservation:
            if self.flatten_takes_effect and kwargs.get("reduce_only") is not False:
                self.positions_rows = [
                    row
                    for row in self.positions_rows
                    if not (row[0] == kwargs["position_side"] or kwargs["position_side"] == "BOTH")
                ]
            return ok_observation(
                "new_market_order",
                {"client_order_id": kwargs["client_order_id"], "status": "FILLED"},
            )

        return self._answer("new_market_order", kwargs, default)

    async def new_conditional_order(self, **kwargs: Any) -> ProbeObservation:
        def default() -> ProbeObservation:
            self.open_algo_ids.append(kwargs["client_algo_id"])
            return ok_observation(
                "new_conditional_order",
                {"client_algo_id": kwargs["client_algo_id"], "algo_status": "NEW"},
            )

        return self._answer("new_conditional_order", kwargs, default)

    async def cancel_order(self, *, symbol: str, client_order_id: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            if client_order_id in self.open_order_ids:
                self.open_order_ids.remove(client_order_id)
                return ok_observation("cancel_order", {"status": "CANCELED"})
            return error_observation("cancel_order", code=-2011, category="ORDER_ABSENT")

        return self._answer(
            "cancel_order", {"symbol": symbol, "client_order_id": client_order_id}, default
        )

    async def cancel_algo_order(self, *, client_algo_id: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            if client_algo_id in self.open_algo_ids:
                self.open_algo_ids.remove(client_algo_id)
                return ok_observation("cancel_algo_order", {"code": "200"})
            return error_observation("cancel_algo_order", code=-2011, category="ORDER_ABSENT")

        return self._answer("cancel_algo_order", {"client_algo_id": client_algo_id}, default)

    async def cancel_all_open_orders(self, *, symbol: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            self.open_order_ids.clear()
            return ok_observation("cancel_all_open_orders", {"code": "200"})

        return self._answer("cancel_all_open_orders", {"symbol": symbol}, default)

    async def cancel_all_algo_open_orders(self, *, symbol: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            self.open_algo_ids.clear()
            return ok_observation("cancel_all_algo_open_orders", {"code": "200"})

        return self._answer("cancel_all_algo_open_orders", {"symbol": symbol}, default)

    async def open_orders(self, *, symbol: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            return ok_observation(
                "open_orders", _rows([{"client_order_id": cid} for cid in self.open_order_ids])
            )

        return self._answer("open_orders", {"symbol": symbol}, default)

    async def open_algo_orders(self, *, symbol: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            return ok_observation(
                "open_algo_orders",
                _rows([{"client_algo_id": cid} for cid in self.open_algo_ids]),
            )

        return self._answer("open_algo_orders", {"symbol": symbol}, default)

    async def positions(self, *, symbol: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            return ok_observation(
                "positions",
                _rows(
                    [
                        {
                            "symbol": symbol,
                            "position_side": side,
                            "position_amt": format(amount, "f"),
                        }
                        for side, amount in self.positions_rows
                    ]
                ),
            )

        return self._answer("positions", {"symbol": symbol}, default)

    async def user_trades(self, *, symbol: str, order_id: int | None = None) -> ProbeObservation:
        def default() -> ProbeObservation:
            return ok_observation("user_trades", _rows(list(self.trades)))

        return self._answer("user_trades", {"symbol": symbol, "order_id": order_id}, default)

    async def account_balance(self) -> ProbeObservation:
        def default() -> ProbeObservation:
            return ok_observation(
                "account_balance",
                _rows([{"asset": FAKE_BALANCE_ASSET, "balance": FAKE_BALANCE}]),
            )

        return self._answer("account_balance", {}, default)

    async def mark_price(self, *, symbol: str) -> ProbeObservation:
        return self._answer("mark_price", {"symbol": symbol}, lambda: fake_mark_price(symbol))

    async def symbol_filters(self, *, symbol: str) -> ProbeObservation:
        return self._answer(
            "symbol_filters", {"symbol": symbol}, lambda: fake_symbol_filters(symbol)
        )

    async def position_mode(self) -> ProbeObservation:
        def default() -> ProbeObservation:
            return ok_observation(
                "position_mode", {"dual_side_position": "true" if self.dual_side else "false"}
            )

        return self._answer("position_mode", {}, default)

    # ----- the stream accessors ---------------------------------------------- #

    def marker(self) -> int:
        return self._sequence.value

    def frames_since(self, marker: int) -> list[dict[str, str]]:
        return [dict(record) for seq, record in self.frame_log if seq > marker]

    def raw_frames_since(self, marker: int) -> list[object]:
        return [raw for seq, raw in self.raw_log if seq > marker]

    def stream_states_since(self, marker: int) -> list[str]:
        return [state for seq, state in self.state_log if seq > marker]

    async def drop_stream_transport(self) -> bool:
        self.calls.append(("drop_stream_transport", {}))
        if self.drop_results:
            return self.drop_results.pop(0)
        return self.stream_running


class RecordingProbePort:
    """The dry-run `ProbePort`: nothing is sent; every request a case would send is recorded.

    State reads (open orders, open algo orders, positions, balance, position mode, mark price,
    symbol filters, trades) answer from the static FAKE fixture of a flat account. Every
    mutating call and every per-case query (`query_order`, `query_algo_order`) is appended to
    `planned_requests` as {"operation", "kwargs", "mutating"} and answers `ok=True` with the
    summary {"dry_run": "true"}: a canned answer that proves nothing about the exchange.
    `drop_stream_transport()` returns False and the frame and state accessors are empty.
    """

    label = FAKE_LABEL

    def __init__(self, *, symbol: str) -> None:
        self.symbol = symbol
        self.planned_requests: list[dict[str, Any]] = []
        self.reads: list[str] = []

    def _plan(self, operation: str, kwargs: dict[str, Any]) -> ProbeObservation:
        self.planned_requests.append(
            {
                "operation": operation,
                "kwargs": dict(kwargs),
                "mutating": operation in MUTATING_OPERATIONS,
            }
        )
        return ok_observation(operation, dict(FAKE_DRY_RUN_SUMMARY))

    def _read(self, operation: str, summary: dict[str, str]) -> ProbeObservation:
        self.reads.append(operation)
        return ok_observation(operation, summary)

    async def query_order(self, *, symbol: str, client_order_id: str) -> ProbeObservation:
        return self._plan("query_order", {"symbol": symbol, "client_order_id": client_order_id})

    async def query_algo_order(self, *, client_algo_id: str) -> ProbeObservation:
        return self._plan("query_algo_order", {"client_algo_id": client_algo_id})

    async def new_limit_order(self, **kwargs: Any) -> ProbeObservation:
        return self._plan("new_limit_order", kwargs)

    async def new_market_order(self, **kwargs: Any) -> ProbeObservation:
        return self._plan("new_market_order", kwargs)

    async def new_conditional_order(self, **kwargs: Any) -> ProbeObservation:
        return self._plan("new_conditional_order", kwargs)

    async def cancel_order(self, *, symbol: str, client_order_id: str) -> ProbeObservation:
        return self._plan("cancel_order", {"symbol": symbol, "client_order_id": client_order_id})

    async def cancel_algo_order(self, *, client_algo_id: str) -> ProbeObservation:
        return self._plan("cancel_algo_order", {"client_algo_id": client_algo_id})

    async def cancel_all_open_orders(self, *, symbol: str) -> ProbeObservation:
        return self._plan("cancel_all_open_orders", {"symbol": symbol})

    async def cancel_all_algo_open_orders(self, *, symbol: str) -> ProbeObservation:
        return self._plan("cancel_all_algo_open_orders", {"symbol": symbol})

    async def open_orders(self, *, symbol: str) -> ProbeObservation:
        return self._read("open_orders", {"count": "0"})

    async def open_algo_orders(self, *, symbol: str) -> ProbeObservation:
        return self._read("open_algo_orders", {"count": "0"})

    async def positions(self, *, symbol: str) -> ProbeObservation:
        return self._read("positions", {"count": "0"})

    async def user_trades(self, *, symbol: str, order_id: int | None = None) -> ProbeObservation:
        return self._read("user_trades", {"count": "0"})

    async def account_balance(self) -> ProbeObservation:
        return self._read(
            "account_balance", _rows([{"asset": FAKE_BALANCE_ASSET, "balance": FAKE_BALANCE}])
        )

    async def mark_price(self, *, symbol: str) -> ProbeObservation:
        self.reads.append("mark_price")
        return fake_mark_price(symbol)

    async def symbol_filters(self, *, symbol: str) -> ProbeObservation:
        self.reads.append("symbol_filters")
        return fake_symbol_filters(symbol)

    async def position_mode(self) -> ProbeObservation:
        return self._read("position_mode", {"dual_side_position": "false"})

    def marker(self) -> int:
        return 0

    def frames_since(self, marker: int) -> list[dict[str, str]]:
        return []

    def raw_frames_since(self, marker: int) -> list[object]:
        return []

    def stream_states_since(self, marker: int) -> list[str]:
        return []

    async def drop_stream_transport(self) -> bool:
        return False


__all__ = [
    "CASE_QUERY_OPERATIONS",
    "FAKE_BALANCE",
    "FAKE_LABEL",
    "FAKE_MARK_PRICE",
    "FAKE_SYMBOL_FILTERS",
    "MUTATING_OPERATIONS",
    "TEST_ONLY_CLOCK_START",
    "FakeProbePort",
    "FakeProbeRest",
    "FakeProbeSdk",
    "FakeResponse",
    "RecordingProbePort",
    "TEST_ONLY_CASE_TIMEOUT_SECONDS",
    "TEST_ONLY_CLEANUP_TIMEOUT_SECONDS",
    "VirtualClock",
    "error_observation",
    "fake_mark_price",
    "fake_symbol_filters",
    "make_gate",
    "make_public",
    "ok_observation",
    "write_probe_limits",
]
