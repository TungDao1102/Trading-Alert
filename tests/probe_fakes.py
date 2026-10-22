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
from src.ops.operator_evidence import EVIDENCE_CASE_KEYS

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

    # ----- capture reads (quick task 261021-sj0) -------------------------- #

    def account_information_v3(self, **kwargs: Any) -> FakeResponse:
        return self._answer("account_information_v3", kwargs)

    def futures_account_configuration(self, **kwargs: Any) -> FakeResponse:
        return self._answer("futures_account_configuration", kwargs)

    def symbol_configuration(self, **kwargs: Any) -> FakeResponse:
        return self._answer("symbol_configuration", kwargs)

    def notional_and_leverage_brackets(self, **kwargs: Any) -> FakeResponse:
        return self._answer("notional_and_leverage_brackets", kwargs)

    def get_income_history(self, **kwargs: Any) -> FakeResponse:
        return self._answer("get_income_history", kwargs)

    # ----- public reads, reached through BinancePublicMarketData --------- #

    def mark_price(self, **kwargs: Any) -> FakeResponse:
        return self._answer("mark_price", kwargs)

    def mark_price_kline_candlestick_data(self, **kwargs: Any) -> FakeResponse:
        return self._answer("mark_price_kline_candlestick_data", kwargs)

    def exchange_information(self, **kwargs: Any) -> FakeResponse:
        return self._answer("exchange_information", kwargs)

    # Quick task 261022-sj1: the server time and the depth read.

    def check_server_time(self, **kwargs: Any) -> FakeResponse:
        return self._answer("check_server_time", kwargs)

    def order_book(self, **kwargs: Any) -> FakeResponse:
        return self._answer("order_book", kwargs)


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
        "new_gtd_limit_order",
    }
)
# The per-case requests (reads a case sends about one id): recorded as planned in a dry run.
CASE_QUERY_OPERATIONS: frozenset[str] = frozenset(
    {"query_order", "query_algo_order", "query_algo_order_by_algo_id"}
)


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


# FAKE flat summaries of the capture reads (quick task 261021-sj0): the shape of
# `_flat_summary`, never Binance data.
FAKE_EXCHANGE_TIME = "2026-10-16T06:00:00+00:00"


def fake_account_information() -> ProbeObservation:
    return ok_observation(
        "account_information",
        {
            "totalWalletBalance": FAKE_BALANCE,
            "availableBalance": FAKE_BALANCE,
            "assets.0.asset": FAKE_BALANCE_ASSET,
            "assets.0.walletBalance": FAKE_BALANCE,
            "positions.0.symbol": "BTCUSDT",
        },
    )


def fake_account_balance_all() -> ProbeObservation:
    return ok_observation(
        "account_balance_all",
        {
            "0.asset": FAKE_BALANCE_ASSET,
            "0.balance": FAKE_BALANCE,
            "0.availableBalance": FAKE_BALANCE,
        },
    )


def fake_account_config(dual_side: bool = False) -> ProbeObservation:
    flag = "true" if dual_side else "false"
    return ok_observation(
        "account_config",
        {"feeTier": "0", "dualSidePosition": flag, "multiAssetsMargin": "false"},
    )


def fake_symbol_config(symbol: str) -> ProbeObservation:
    return ok_observation(
        "symbol_config", {"0.symbol": symbol, "0.marginType": "CROSSED", "0.leverage": "20"}
    )


def fake_leverage_brackets(symbol: str) -> ProbeObservation:
    return ok_observation(
        "leverage_brackets",
        {
            "0.symbol": symbol,
            "0.brackets.0.bracket": "1",
            "0.brackets.0.initialLeverage": "125",
            "0.brackets.1.bracket": "2",
        },
    )


TEST_ONLY_CASE_TIMEOUT_SECONDS = 30
TEST_ONLY_CLEANUP_TIMEOUT_SECONDS = 60
TEST_ONLY_NEAR_TRIGGER_FRACTION = "0.999"
TEST_ONLY_GTD_LIFETIME_SECONDS = 660
TEST_ONLY_GTD_EXPIRY_WAIT_SECONDS = 720

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
{extra_waits}
[optional_cases]
explicit_time_in_force = {explicit_time_in_force}
stream_gap = {stream_gap}
market_lot_size_out_of_range = {market_lot}
{evidence_cases}"""


def write_probe_limits(
    directory: Path,
    *,
    symbol: str = "BTCUSDT",
    optional: tuple[str, ...] = (),
    name: str = "probe-limits.toml",
) -> Path:
    """A TEST_ONLY probe limits file (the owner writes the real one at plan 18-20).

    `optional` names the enabled optional cases. The ten evidence keys of quick task
    261021-sj0 are written (as `true`) only when named; the keys they need get TEST_ONLY values
    (`near_trigger_fraction` for the two near-trigger cases, the GTD lifetime and wait for
    `gtd_expiry`). The text of the three Phase 18 keys is unchanged.
    """
    market_lot = "market_lot_size_out_of_range" in optional
    extra_order = 'market_lot_probe_quantity = "200"\n' if market_lot else ""
    if "triggered_bracket" in optional or "tp1_from_fill" in optional:
        extra_order += f'near_trigger_fraction = "{TEST_ONLY_NEAR_TRIGGER_FRACTION}"\n'
    extra_waits = ""
    if "gtd_expiry" in optional:
        extra_order += f"gtd_lifetime_seconds = {TEST_ONLY_GTD_LIFETIME_SECONDS}\n"
        extra_waits = f"gtd_expiry_wait_seconds = {TEST_ONLY_GTD_EXPIRY_WAIT_SECONDS}\n"
    evidence = "".join(f"{key} = true\n" for key in EVIDENCE_CASE_KEYS if key in optional)
    text = _TEST_ONLY_PROBE_LIMITS.format(
        symbol=symbol,
        extra_order=extra_order,
        extra_waits=extra_waits,
        case_timeout=TEST_ONLY_CASE_TIMEOUT_SECONDS,
        cleanup_timeout=TEST_ONLY_CLEANUP_TIMEOUT_SECONDS,
        explicit_time_in_force=str("explicit_time_in_force" in optional).lower(),
        stream_gap=str("stream_gap" in optional).lower(),
        market_lot=str(market_lot).lower(),
        evidence_cases=evidence,
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

    Scenario helpers of the write cases (plan 18-23), all FAKE semantics:

    * Fills: a LIMIT BUY priced at or above `mark` fills at once (status FILLED, the position
      grows by its quantity) unless `fill_marketable` is False (it rests NEW);
      `partial_fill_quantity` makes it PARTIALLY_FILLED for that quantity instead.
    * Statuses: `order_status` and `algo_status` keep the last status per client id, so a
      query after a cancel answers CANCELED (the fake's assumption, not an exchange fact).
    * Duplicates: placing a client id that is still open answers `duplicate_order_answer` or
      `duplicate_algo_answer` (FAKE -4116 by default; the algo code is undocumented).
    * Waits: `on_wait` callables run (and are consumed) when the test rig's sleep runs, so a
      trigger, a system cancel or a stream recovery can happen "during" a wait.
    * `banned` is the adapter's ban flag the write cases read after a `ProbeBanned`.
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
        # Scenario state of the write cases (plan 18-23).
        self.mark = Decimal(FAKE_MARK_PRICE)
        self.fill_marketable = True
        self.partial_fill_quantity: Decimal | None = None
        self.order_status: dict[str, str] = {}
        self.algo_status: dict[str, str] = {}
        self.algo_quantity: dict[str, str] = {}
        self.duplicate_order_answer: ProbeObservation = error_observation(
            "new_limit_order",
            code=-4116,
            category="DUPLICATE_CLIENT_ID",
            message="FAKE ClientOrderId is duplicated.",
        )
        self.duplicate_algo_answer: ProbeObservation = error_observation(
            "new_conditional_order",
            code=-4116,
            category="DUPLICATE_CLIENT_ID",
            message="FAKE duplicate clientAlgoId.",
        )
        self.on_wait: list[Any] = []
        self.banned = False
        # Quick task 261021-sj0: the exchange algo ids, scriptable income rows, GTD record.
        self.algo_ids: dict[str, int] = {}
        self._next_algo_id = 1_000_000_000
        self.income_rows: list[dict[str, str]] = []
        self.good_till_dates: dict[str, int] = {}

    # ----- scenario helpers (plan 18-23) -------------------------------------- #

    def run_wait_hooks(self) -> None:
        """Run and consume the `on_wait` callables (the test rig's sleep calls this)."""
        hooks, self.on_wait = self.on_wait, []
        for hook in hooks:
            hook()

    def _require_own_symbol(self, kwargs: dict[str, Any]) -> None:
        assert kwargs["symbol"] == self.symbol, "an order for another symbol than the fake's"

    def _position_side(self, kwargs: dict[str, Any]) -> str:
        side = kwargs.get("position_side", "BOTH")
        return str(side)

    def _add_position(self, side: str, amount: Decimal) -> None:
        for index, (row_side, held) in enumerate(self.positions_rows):
            if row_side == side:
                self.positions_rows[index] = (row_side, held + amount)
                return
        self.positions_rows.append((side, amount))

    def system_cancel_algo(self, client_algo_id: str, status: str = "CANCELED") -> None:
        """The exchange ends an open algo order by itself (FAKE)."""
        if client_algo_id in self.open_algo_ids:
            self.open_algo_ids.remove(client_algo_id)
        self.algo_status[client_algo_id] = status
        self.emit_frame(
            {
                "event_type": "AlgoUpdateEvent",
                "client_algo_id": client_algo_id,
                "algo_status": status,
            }
        )

    def expire_order(
        self,
        client_order_id: str,
        *,
        raw: object | None = None,
        expire_reason: str | None = None,
    ) -> None:
        """The exchange expires an open GTD order (FAKE): status, a frame and a raw payload."""
        if client_order_id in self.open_order_ids:
            self.open_order_ids.remove(client_order_id)
        self.order_status[client_order_id] = "EXPIRED"
        record = {
            "event_type": "OrderUpdateEvent",
            "client_order_id": client_order_id,
            "order_status": "EXPIRED",
            "execution_type": "EXPIRED",
        }
        if expire_reason is not None:
            record["expire_reason"] = expire_reason
        self.emit_frame(record, raw=raw)

    def trigger_algo(
        self,
        client_algo_id: str,
        *,
        child_order_id: str = "FAKE-CHILD-1",
        child_client_id: str = "FAKE-CHILD-C",
        statuses: tuple[str, ...] = ("TRIGGERING", "TRIGGERED", "FINISHED"),
    ) -> None:
        """A FAKE trigger: ALGO_UPDATE frames per status, the child ORDER_TRADE_UPDATE, flat."""
        quantity = self.algo_quantity.get(client_algo_id, "0")
        for status in statuses:
            record = {
                "event_type": "AlgoUpdateEvent",
                "client_algo_id": client_algo_id,
                "algo_status": status,
            }
            if status in ("TRIGGERED", "FINISHED"):
                record["actual_order_id"] = child_order_id
                record["executed_quantity"] = quantity
            self.emit_frame(record)
        self.emit_frame(
            {
                "event_type": "OrderUpdateEvent",
                "client_order_id": child_client_id,
                "exchange_order_id": child_order_id,
                "order_status": "FILLED",
            }
        )
        if client_algo_id in self.open_algo_ids:
            self.open_algo_ids.remove(client_algo_id)
        self.algo_status[client_algo_id] = statuses[-1]
        self.positions_rows = []

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

    def emit_raw(self, payload: object) -> None:
        """A raw user-data payload without a typed record (quick task 261021-sj0)."""
        self.raw_log.append((self._sequence.next(), payload))

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
            status = self.order_status.get(client_order_id)
            if status is None and client_order_id in self.open_order_ids:
                status = "NEW"
            if status is not None:
                return ok_observation(
                    "query_order", {"client_order_id": client_order_id, "status": status}
                )
            return error_observation("query_order", code=-2013, category="ORDER_ABSENT")

        return self._answer(
            "query_order", {"symbol": symbol, "client_order_id": client_order_id}, default
        )

    async def query_algo_order(self, *, client_algo_id: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            status = self.algo_status.get(client_algo_id)
            if status is None and client_algo_id in self.open_algo_ids:
                status = "NEW"
            if status is not None:
                return ok_observation(
                    "query_algo_order", {"client_algo_id": client_algo_id, "algo_status": status}
                )
            return error_observation("query_algo_order", code=-2013, category="ORDER_ABSENT")

        return self._answer("query_algo_order", {"client_algo_id": client_algo_id}, default)

    async def query_algo_order_by_algo_id(self, *, algo_id: int) -> ProbeObservation:
        def default() -> ProbeObservation:
            client_algo_id = next(
                (cid for cid, aid in self.algo_ids.items() if aid == algo_id), None
            )
            if client_algo_id is None:
                return error_observation(
                    "query_algo_order_by_algo_id", code=-2013, category="ORDER_ABSENT"
                )
            status = self.algo_status.get(client_algo_id)
            if status is None and client_algo_id in self.open_algo_ids:
                status = "NEW"
            if status is None:
                return error_observation(
                    "query_algo_order_by_algo_id", code=-2013, category="ORDER_ABSENT"
                )
            return ok_observation(
                "query_algo_order_by_algo_id",
                {"algo_id": str(algo_id), "client_algo_id": client_algo_id, "algo_status": status},
            )

        return self._answer("query_algo_order_by_algo_id", {"algo_id": algo_id}, default)

    async def new_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        client_order_id: str,
        position_side: str,
        time_in_force: str,
        reduce_only: bool | None,
    ) -> ProbeObservation:
        kwargs: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "client_order_id": client_order_id,
            "position_side": position_side,
            "time_in_force": time_in_force,
            "reduce_only": reduce_only,
        }

        def default() -> ProbeObservation:
            self._require_own_symbol(kwargs)
            client_id = kwargs["client_order_id"]
            if client_id in self.open_order_ids:
                return self.duplicate_order_answer
            marketable = kwargs.get("side") == "BUY" and Decimal(kwargs["price"]) >= self.mark
            status = "NEW"
            if marketable and self.fill_marketable:
                side = self._position_side(kwargs)
                if self.partial_fill_quantity is not None:
                    status = "PARTIALLY_FILLED"
                    self._add_position(side, self.partial_fill_quantity)
                else:
                    status = "FILLED"
                    self._add_position(side, Decimal(kwargs["quantity"]))
            if status != "FILLED":
                self.open_order_ids.append(client_id)
            self.order_status[client_id] = status
            return ok_observation(
                "new_limit_order", {"client_order_id": client_id, "status": status}
            )

        return self._answer("new_limit_order", kwargs, default)

    async def new_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        client_order_id: str,
        position_side: str,
        reduce_only: bool | None,
    ) -> ProbeObservation:
        kwargs: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "client_order_id": client_order_id,
            "position_side": position_side,
            "reduce_only": reduce_only,
        }

        def default() -> ProbeObservation:
            self._require_own_symbol(kwargs)
            if self.flatten_takes_effect and kwargs.get("reduce_only") is not False:
                # A reducing order shrinks the position of its side by `quantity` (capped at
                # what is held) and only when it is the opposite side: a SELL reduces a long,
                # a BUY reduces a short. A wrong-side order leaves the position open.
                remaining: list[tuple[str, Decimal]] = []
                for row_side, held in self.positions_rows:
                    if row_side == kwargs["position_side"] or kwargs["position_side"] == "BOTH":
                        quantity = kwargs["quantity"]
                        if kwargs["side"] == "SELL" and held > 0:
                            held = max(held - quantity, Decimal(0))
                        elif kwargs["side"] == "BUY" and held < 0:
                            held = min(held + quantity, Decimal(0))
                    if held != 0:
                        remaining.append((row_side, held))
                self.positions_rows = remaining
            return ok_observation(
                "new_market_order",
                {"client_order_id": kwargs["client_order_id"], "status": "FILLED"},
            )

        return self._answer("new_market_order", kwargs, default)

    async def new_conditional_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        client_algo_id: str,
        position_side: str,
        trigger_price: Decimal,
        working_type: str,
        quantity: Decimal | None = None,
        reduce_only: bool | None = None,
        close_position: bool | None = None,
        price: Decimal | None = None,
        time_in_force: str | None = None,
    ) -> ProbeObservation:
        kwargs: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "client_algo_id": client_algo_id,
            "position_side": position_side,
            "trigger_price": trigger_price,
            "working_type": working_type,
            "quantity": quantity,
            "reduce_only": reduce_only,
            "close_position": close_position,
            "price": price,
            "time_in_force": time_in_force,
        }

        def default() -> ProbeObservation:
            self._require_own_symbol(kwargs)
            client_id = kwargs["client_algo_id"]
            if client_id in self.open_algo_ids:
                return self.duplicate_algo_answer
            self.open_algo_ids.append(client_id)
            self.algo_status[client_id] = "NEW"
            quantity = kwargs.get("quantity")
            self.algo_quantity[client_id] = format(quantity, "f") if quantity is not None else ""
            self._next_algo_id += 1
            self.algo_ids[client_id] = self._next_algo_id
            return ok_observation(
                "new_conditional_order",
                {
                    "client_algo_id": client_id,
                    "algo_status": "NEW",
                    "algo_id": str(self._next_algo_id),
                },
            )

        return self._answer("new_conditional_order", kwargs, default)

    async def cancel_order(self, *, symbol: str, client_order_id: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            if client_order_id in self.open_order_ids:
                self.open_order_ids.remove(client_order_id)
                self.order_status[client_order_id] = "CANCELED"
                return ok_observation("cancel_order", {"status": "CANCELED"})
            return error_observation("cancel_order", code=-2011, category="ORDER_ABSENT")

        return self._answer(
            "cancel_order", {"symbol": symbol, "client_order_id": client_order_id}, default
        )

    async def cancel_algo_order(self, *, client_algo_id: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            if client_algo_id in self.open_algo_ids:
                self.open_algo_ids.remove(client_algo_id)
                self.algo_status[client_algo_id] = "CANCELED"
                return ok_observation("cancel_algo_order", {"code": "200"})
            return error_observation("cancel_algo_order", code=-2011, category="ORDER_ABSENT")

        return self._answer("cancel_algo_order", {"client_algo_id": client_algo_id}, default)

    async def cancel_all_open_orders(self, *, symbol: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            for client_id in self.open_order_ids:
                self.order_status[client_id] = "CANCELED"
            self.open_order_ids.clear()
            return ok_observation("cancel_all_open_orders", {"code": "200"})

        return self._answer("cancel_all_open_orders", {"symbol": symbol}, default)

    async def cancel_all_algo_open_orders(self, *, symbol: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            for client_id in self.open_algo_ids:
                self.algo_status[client_id] = "CANCELED"
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
                _rows(
                    [
                        {
                            "client_algo_id": cid,
                            "algo_status": self.algo_status.get(cid, "NEW"),
                            "quantity": self.algo_quantity.get(cid, ""),
                        }
                        for cid in self.open_algo_ids
                    ]
                ),
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

    # ----- quick task 261021-sj0: the capture operations --------------------------- #

    async def account_information(self) -> ProbeObservation:
        return self._answer("account_information", {}, fake_account_information)

    async def account_balance_all(self) -> ProbeObservation:
        return self._answer("account_balance_all", {}, fake_account_balance_all)

    async def account_config(self) -> ProbeObservation:
        return self._answer("account_config", {}, lambda: fake_account_config(self.dual_side))

    async def symbol_config(self, *, symbol: str) -> ProbeObservation:
        return self._answer("symbol_config", {"symbol": symbol}, lambda: fake_symbol_config(symbol))

    async def leverage_brackets(self, *, symbol: str) -> ProbeObservation:
        return self._answer(
            "leverage_brackets", {"symbol": symbol}, lambda: fake_leverage_brackets(symbol)
        )

    async def income_history(self, *, symbol: str, start_time_ms: int) -> ProbeObservation:
        def default() -> ProbeObservation:
            return ok_observation("income_history", _rows(list(self.income_rows)))

        return self._answer(
            "income_history", {"symbol": symbol, "start_time_ms": start_time_ms}, default
        )

    async def new_gtd_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        client_order_id: str,
        position_side: str,
        good_till_date_ms: int,
    ) -> ProbeObservation:
        kwargs: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "client_order_id": client_order_id,
            "position_side": position_side,
            "good_till_date_ms": good_till_date_ms,
        }

        def default() -> ProbeObservation:
            self._require_own_symbol(kwargs)
            if client_order_id in self.open_order_ids:
                return self.duplicate_order_answer
            self.open_order_ids.append(client_order_id)
            self.order_status[client_order_id] = "NEW"
            self.good_till_dates[client_order_id] = good_till_date_ms
            return ok_observation(
                "new_gtd_limit_order",
                {
                    "client_order_id": client_order_id,
                    "status": "NEW",
                    "time_in_force": "GTD",
                    "good_till_date": str(good_till_date_ms),
                },
            )

        return self._answer("new_gtd_limit_order", kwargs, default)

    async def live_mark_price(self, *, symbol: str) -> ProbeObservation:
        def default() -> ProbeObservation:
            return ok_observation(
                "live_mark_price",
                {
                    "symbol": symbol,
                    "mark_price": format(self.mark, "f"),
                    "exchange_time_utc": FAKE_EXCHANGE_TIME,
                },
            )

        return self._answer("live_mark_price", {"symbol": symbol}, default)

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

    async def new_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        client_order_id: str,
        position_side: str,
        time_in_force: str,
        reduce_only: bool | None,
    ) -> ProbeObservation:
        return self._plan(
            "new_limit_order",
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "client_order_id": client_order_id,
                "position_side": position_side,
                "time_in_force": time_in_force,
                "reduce_only": reduce_only,
            },
        )

    async def new_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        client_order_id: str,
        position_side: str,
        reduce_only: bool | None,
    ) -> ProbeObservation:
        return self._plan(
            "new_market_order",
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "client_order_id": client_order_id,
                "position_side": position_side,
                "reduce_only": reduce_only,
            },
        )

    async def new_conditional_order(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        client_algo_id: str,
        position_side: str,
        trigger_price: Decimal,
        working_type: str,
        quantity: Decimal | None = None,
        reduce_only: bool | None = None,
        close_position: bool | None = None,
        price: Decimal | None = None,
        time_in_force: str | None = None,
    ) -> ProbeObservation:
        return self._plan(
            "new_conditional_order",
            {
                "symbol": symbol,
                "side": side,
                "order_type": order_type,
                "client_algo_id": client_algo_id,
                "position_side": position_side,
                "trigger_price": trigger_price,
                "working_type": working_type,
                "quantity": quantity,
                "reduce_only": reduce_only,
                "close_position": close_position,
                "price": price,
                "time_in_force": time_in_force,
            },
        )

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

    # ----- quick task 261021-sj0: the capture operations ----------------------------- #

    async def account_information(self) -> ProbeObservation:
        return self._read("account_information", dict(fake_account_information().summary))

    async def account_balance_all(self) -> ProbeObservation:
        return self._read("account_balance_all", dict(fake_account_balance_all().summary))

    async def account_config(self) -> ProbeObservation:
        return self._read("account_config", dict(fake_account_config().summary))

    async def symbol_config(self, *, symbol: str) -> ProbeObservation:
        return self._read("symbol_config", dict(fake_symbol_config(symbol).summary))

    async def leverage_brackets(self, *, symbol: str) -> ProbeObservation:
        return self._read("leverage_brackets", dict(fake_leverage_brackets(symbol).summary))

    async def income_history(self, *, symbol: str, start_time_ms: int) -> ProbeObservation:
        return self._read("income_history", {"count": "0"})

    async def query_algo_order_by_algo_id(self, *, algo_id: int) -> ProbeObservation:
        return self._plan("query_algo_order_by_algo_id", {"algo_id": algo_id})

    async def new_gtd_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        client_order_id: str,
        position_side: str,
        good_till_date_ms: int,
    ) -> ProbeObservation:
        return self._plan(
            "new_gtd_limit_order",
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "client_order_id": client_order_id,
                "position_side": position_side,
                "good_till_date_ms": good_till_date_ms,
            },
        )

    async def live_mark_price(self, *, symbol: str) -> ProbeObservation:
        return self._read(
            "live_mark_price",
            {
                "symbol": symbol,
                "mark_price": FAKE_MARK_PRICE,
                "exchange_time_utc": FAKE_EXCHANGE_TIME,
            },
        )

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
    "FAKE_EXCHANGE_TIME",
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
    "TEST_ONLY_GTD_EXPIRY_WAIT_SECONDS",
    "TEST_ONLY_GTD_LIFETIME_SECONDS",
    "TEST_ONLY_NEAR_TRIGGER_FRACTION",
    "VirtualClock",
    "error_observation",
    "fake_mark_price",
    "fake_symbol_filters",
    "make_gate",
    "make_public",
    "ok_observation",
    "write_probe_limits",
]
