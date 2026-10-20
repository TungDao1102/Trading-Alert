"""Binance Demo Trading rehearsal runner (quick task 261005-tx9, closes plan 09-04 task 3).

Run from the repository root, never with real credentials unless you are the operator::

    uv run --python 3.13 python -m scripts.demo_rehearsal --scenario far

What it is. A single-file operator tool that rehearses the Phase 9 execution path against
Binance Demo Trading (REST only) and writes an evidence file. The only host it can reach is
the SDK constant for Demo Trading. There is no host, base-url or symbol option. The symbol is
fixed to BTCUSDT.

Safety posture (read before running anything):

* Dry run is the default. Without ``--execute`` no request that changes exchange state ever
  leaves the process: the four mutating adapter methods (place_entry, place_algo_protective,
  cancel_normal_order, cancel_algo_order) never reach the underlying adapter.
* ``--execute`` needs an interactive terminal AND an exactly typed phrase, for example
  ``DEMO FAR BTCUSDT``. Anything else exits 2 before any network call.
* Credentials come only from four environment variables of the current shell session:
  BINANCE_DEMO_API_KEY, BINANCE_DEMO_API_SECRET, TELEGRAM_BOT_TOKEN and
  TELEGRAM_AUTHORIZED_CHAT_ID. No file is read for credentials and no other variable is used.
  Set them in the shell session only, never in a file that is committed.
* Evidence files carry exchange-returned ids only, never a secret, and are scrubbed before
  and re-checked after the write.

Exit codes::

    0  the run completed
    1  the run failed part-way (evidence written, exception type name only)
    2  refused before any network call (usage, credentials, --execute gate)
    3  aborted before any order (host violation, failed health probe, fail-closed constraint)

Operator runbook (the executor agent that built this tool never ran it):

1. Set the four variables in the shell session. Stop any other process that polls the bot.
2. Run the dry run first (the default), then the taps scenario, then far, then fill. Each
   ``--execute`` run asks you to type its phrase.
3. Read the evidence file under ``.planning/phases/09-live-execution-rollout/``. Dry runs write
   ``09-DEMO-REHEARSAL-DRYRUN-*.json`` with zero exchange order records; executed runs write
   ``09-DEMO-REHEARSAL-EVIDENCE-*.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn, Protocol, TypeVar, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from binance_common.constants import (  # noqa: E402
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL,
)
from src.adapters.binance_client import (  # noqa: E402
    ENVIRONMENT_ROWS,
    EndpointViolation,
    Environment,
    assert_endpoint_url,
)
from src.adapters.binance_limits import (  # noqa: E402
    DriftLimits,
    LimitsNotRatified,
    SignedCallPolicy,
    load_binance_limits,
)
from src.adapters.binance_public import MarkPriceReading  # noqa: E402
from src.adapters.binance_ratelimit_gate import RestRateLimitGate  # noqa: E402
from src.adapters.binance_usdm import (  # noqa: E402
    AlgoOrderProbe,
    AlgoPlacementResult,
    BinanceUsdmAdapter,
    CommissionRates,
    EntryPlacementResult,
    Kline,
    MarketCloseResult,
    MarkKline,
    OpenAlgoOrderSnapshot,
    OpenOrderSnapshot,
    OrderProbe,
    PositionModeResult,
    PositionSnapshot,
    SymbolFilters,
)
from src.adapters.telegram_callbacks import (  # noqa: E402
    DispatchResult,
    build_application,
    dispatch_callback,
)
from src.adapters.telegram_notify import (  # noqa: E402
    build_approve_keyboard,
    build_skip_keyboard,
    format_approve,
)
from src.approval.binding import Callback  # noqa: E402
from src.approval.mapping import ShortIdMapping, derive_short_id  # noqa: E402
from src.approval.tokens import issue_one_time_token, token_hash_of  # noqa: E402
from src.backtest.semantics import TP1_QUANTITY_FRACTION  # noqa: E402
from src.core.planner import plan_hash_from_fields  # noqa: E402
from src.core.types import AccountState  # noqa: E402
from src.domain.approval import Approval  # noqa: E402
from src.domain.canonical import sha256_hex  # noqa: E402
from src.domain.enums import (  # noqa: E402
    ApprovalAction,
    ApprovalResult,
    KillGateState,
    OrderRole,
    QuantizationDecision,
    SignalStatus,
    TradePlanStatus,
)
from src.domain.ids import derive_child_id  # noqa: E402
from src.domain.journal import JournalEvent, content_hash_event_id  # noqa: E402
from src.domain.lot_filters import LotFilters  # noqa: E402
from src.domain.registry import ParameterSet, load_parameter_set  # noqa: E402
from src.domain.signal import Signal  # noqa: E402
from src.domain.trade_plan import TradePlan  # noqa: E402
from src.execution.constraint_snapshot import (  # noqa: E402
    ExchangeFilterExtras,
    build_plan_constraint_snapshot,
)
from src.execution.emergency_close import MarketEmergencyCloser  # noqa: E402
from src.execution.enablement import LiveEnablementController  # noqa: E402
from src.execution.execution_limits import (  # noqa: E402
    ExecutionLimits,
    ExecutionLimitsInvalid,
    load_execution_limits,
)
from src.execution.intent_store import ExecutionIntentStore  # noqa: E402
from src.execution.live_context import LivePlacementContext  # noqa: E402
from src.execution.manager import (  # noqa: E402
    LIVE5_SYMBOLS,
    cancel_untriggered_protectives,
    execute_approved_plan,
    expire_pending_entry,
)
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id  # noqa: E402
from src.execution.placement import (  # noqa: E402
    PRICE_ROUND_DOWN,
    PRICE_ROUND_UP,
    quantize_price,
)
from src.execution.pre_placement import LIMITS_NOT_CONFIGURED  # noqa: E402
from src.execution.protection import (  # noqa: E402
    ALERT_TP_UNAVAILABLE,
    EVENT_PROTECTION_TRANSITION,
    PlanProtection,
    ProtectionCoordinator,
    ProtectionState,
)
from src.ops.health import (  # noqa: E402
    ALL_CHECK_NAMES,
    CHECK_DB_WRITES,
    CHECK_USER_DATA_STREAM_STATE,
    CHECK_WS_CONNECTION_STATE,
    STATUS_DEGRADED,
    STATUS_FAIL,
    HealthCheckResult,
    HealthVerdict,
    check_last_closed_candle_time,
    check_market_feed_freshness,
    check_orphaned_orders,
    check_reconciliation_drift,
    check_rest_error_rate,
    check_telegram_delivery,
    check_unprotected_positions,
    run_health_checks,
)
from src.ops.redaction import Redactor  # noqa: E402
from src.reconcile.safe_mode import SafeModeController  # noqa: E402
from src.risk.cost_rates import (  # noqa: E402
    FEE_SOURCE_PARAMETER,
    CostRates,
    per_unit_round_trip_cost,
)
from src.risk.gating import evaluate_risk  # noqa: E402
from src.risk.live_commission import AccountCommission, resolve_live_cost_rates  # noqa: E402
from src.risk.portfolio import resolve_absolute_thresholds  # noqa: E402
from src.risk.types import ConstraintSnapshot  # noqa: E402

# --------------------------------------------------------------------------- #
# Constants and errors.
# --------------------------------------------------------------------------- #

DEMO_BASE_URL: str = DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL
DEMO_HOST = "demo-fapi.binance.com"
SYMBOL = "BTCUSDT"

ENV_BINANCE_KEY = "BINANCE_DEMO_API_KEY"
ENV_BINANCE_SECRET = "BINANCE_DEMO_API_SECRET"  # noqa: S105 - a variable NAME, not a secret
ENV_TELEGRAM_TOKEN = "TELEGRAM_BOT_TOKEN"  # noqa: S105 - a variable NAME, not a secret
ENV_TELEGRAM_CHAT = "TELEGRAM_AUTHORIZED_CHAT_ID"

EVIDENCE_SCHEMA = "demo-rehearsal-evidence/schema-1"
DEFAULT_EVIDENCE_DIR = REPO_ROOT / ".planning" / "phases" / "09-live-execution-rollout"
# Plan 18-13: the ratified limits file (plan 18-09). Its signed-call policy gives every
# signed request an explicit recvWindow; no number is chosen here.
DEFAULT_LIMITS_FILE = REPO_ROOT / "config" / "binance" / "binance-limits-v1.toml"
# Plan 19-13: the owner's four execution limits (plan 19-01). Every value is NOT_CONFIGURED in
# the committed file, so a run that reaches the order path aborts before any mutation.
DEFAULT_EXECUTION_LIMITS_FILE = REPO_ROOT / "config" / "execution" / "execution-limits-v1.toml"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2
EXIT_ABORTED = 3

OUTCOME_COMPLETE = "COMPLETE"
OUTCOME_COMPLETE_WITH_GAPS = "COMPLETE_WITH_GAPS"
OUTCOME_ABORTED = "ABORTED_NO_ORDER"
OUTCOME_FAILED = "FAILED"

SCENARIOS = ("taps", "far", "fill")
DEFAULT_APPROVAL_TIMEOUT_SECONDS = 300
DEFAULT_DISCOVERY_TIMEOUT_SECONDS = 120
SDK_TIMEOUT_MS = 10000

STEP_PASSED = "PASSED"
STEP_FAILED = "FAILED"
STEP_NOT_REHEARSED = "NOT_REHEARSED"
STEP_SKIPPED_DRY_RUN = "SKIPPED_DRY_RUN"

# Plan and run constants (SR-4). Named in one block so an operator can audit them.
STRATEGY_ID = "trend-pullback"
PARAMETER_SET_ID = "baseline-v5"
OPERATOR_ID = "demo-rehearsal-runner"
FAR_BAND_FRACTION = Decimal("0.5")  # fraction of the PERCENT_PRICE band used for the entry
SL_DISTANCE_RATE = Decimal("0.015")
TP1_DISTANCE_RATE = Decimal("0.03")
TP2_DISTANCE_RATE = Decimal("0.06")
PLAN_EXPIRY_MARGIN = timedelta(minutes=10)
FILL_POLL_SECONDS = 2
FILL_TIMEOUT_SECONDS = 60
FILL_MAX_POLLS = FILL_TIMEOUT_SECONDS // FILL_POLL_SECONDS
MARKET_FEED_STALENESS = timedelta(seconds=120)
CANDLE_CADENCE = timedelta(hours=1, minutes=5)
MAX_REST_ERROR_RATE = Decimal("0.1")
_QUANTITY_SEARCH_LIMIT = 10000
_PORTFOLIO_KEYS = (
    "max_open_positions",
    "max_aggregate_open_risk",
    "cluster_cap",
    "daily_loss_warning_threshold",
    "daily_loss_stop_threshold",
)
_TAP_STEPS = ("skip_tap", "approve_tap", "unknown_chat_tap")

_T = TypeVar("_T")


class DemoHostViolation(Exception):  # noqa: N818 - public name fixed by the plan
    """A base URL other than the exact Demo Trading REST host was seen."""


class CredentialError(Exception):
    """A required environment variable is missing, blank or malformed (names only)."""


class ConfirmationRefused(Exception):  # noqa: N818 - public name fixed by the plan
    """The --execute interactive confirmation was not given exactly."""


class UsageError(Exception):
    """A bad or forbidden command-line argument."""


class LimitsFileRefused(Exception):  # noqa: N818 - a refusal, like ConfirmationRefused
    """The ratified limits file is missing or invalid; the message names the path only."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"the binance limits file is missing or invalid: {path}")


def load_signed_call_policy(path: Path) -> SignedCallPolicy:
    """The ratified signed-call policy of `path` (plan 18-13), or `LimitsFileRefused`."""
    try:
        return load_binance_limits(path).signed
    except (LimitsNotRatified, ValueError, TypeError):
        raise LimitsFileRefused(path) from None


def load_drift_limits(path: Path) -> DriftLimits:
    """The ratified clock-drift limits of `path` (plan 19-13: the GTD clock margin)."""
    try:
        return load_binance_limits(path).drift
    except (LimitsNotRatified, ValueError, TypeError):
        raise LimitsFileRefused(path) from None


class RehearsalAbort(Exception):  # noqa: N818 - public name fixed by the plan
    """The run stops before any order (fail closed). The message is operator-readable."""


class RunMode(StrEnum):
    """DRY_RUN (default) never mutates exchange state; EXECUTE forwards to Demo."""

    DRY_RUN = "DRY_RUN"
    EXECUTE = "EXECUTE"


# --------------------------------------------------------------------------- #
# Credentials (SR-1): the four named environment variables only.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, repr=False)
class RehearsalCredentials:
    """The four credentials. Secret fields never appear in repr, str or logs."""

    binance_api_key: str = field(repr=False)
    binance_api_secret: str = field(repr=False)
    telegram_bot_token: str = field(repr=False)
    telegram_chat_id: int = field(repr=False)

    def __repr__(self) -> str:
        return "RehearsalCredentials(<masked>)"

    __str__ = __repr__


def load_credentials(environ: Mapping[str, str]) -> RehearsalCredentials:
    """Read exactly the four named variables from ``environ``. Errors name the variable only."""

    def need(name: str) -> str:
        value = environ.get(name)
        if value is None or not value.strip():
            raise CredentialError(f"environment variable {name} is missing or blank")
        return value.strip()

    key = need(ENV_BINANCE_KEY)
    secret = need(ENV_BINANCE_SECRET)
    token = need(ENV_TELEGRAM_TOKEN)
    raw_chat = need(ENV_TELEGRAM_CHAT)
    try:
        chat_id = int(raw_chat)
    except ValueError:
        raise CredentialError(
            f"environment variable {ENV_TELEGRAM_CHAT} is not an integer"
        ) from None
    return RehearsalCredentials(
        binance_api_key=key,
        binance_api_secret=secret,
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
    )


# --------------------------------------------------------------------------- #
# Demo host guard and client factory (SR-2).
# --------------------------------------------------------------------------- #


def assert_demo_base_url(url: object) -> None:
    """Accept only the exact Demo Trading REST base URL; everything else raises.

    Delegates to the production guard ``src.adapters.binance_client.assert_endpoint_url``
    against the DEMO environment row (plan 18-04) and keeps this script's error type.
    """
    if not isinstance(url, str) or not url:
        raise DemoHostViolation("base URL is missing or not text")
    expected = ENVIRONMENT_ROWS[Environment.DEMO].rest_url
    if expected is None or expected != DEMO_BASE_URL:
        raise DemoHostViolation(f"base URL is not the Demo Trading host {DEMO_HOST}")
    try:
        assert_endpoint_url(url, expected)
    except EndpointViolation:
        raise DemoHostViolation(f"base URL is not the Demo Trading host {DEMO_HOST}") from None


def assert_demo_sdk_client(client: Any) -> None:
    """Re-read the live REST configuration (one object shared by every API) and check it."""
    assert_demo_base_url(client.rest_api.configuration.base_path)


def build_demo_sdk_client(*, api_key: str, api_secret: str) -> Any:
    """The only place the SDK client is built. It has no host parameter on purpose."""
    from binance_common.configuration import ConfigurationRestAPI
    from binance_sdk_derivatives_trading_usds_futures import DerivativesTradingUsdsFutures

    config = ConfigurationRestAPI(
        api_key=api_key,
        api_secret=api_secret,
        base_path=DEMO_BASE_URL,
        timeout=SDK_TIMEOUT_MS,
    )
    client = DerivativesTradingUsdsFutures(config_rest_api=config)
    assert_demo_sdk_client(client)
    return client


@dataclass(frozen=True)
class AdapterBundle:
    """An inner adapter plus the guard run before every delegated call."""

    inner: BinanceUsdmAdapter
    guard: Callable[[], None]


def default_adapter_factory(
    credentials: RehearsalCredentials,
    *,
    signed_call_policy: SignedCallPolicy,
    clock: Callable[[], datetime],
) -> AdapterBundle:
    """Real Demo client, real adapter built on it, per-call live host re-check.

    Plan 18-13: the adapter carries the ratified `signed_call_policy` (explicit recvWindow on
    every signed call) and the ONE `RestRateLimitGate` of this run, built here once on the
    script's aware-UTC `clock` and shared by every REST holder of the rehearsal (the adapter
    and the public reader inside it). No drift guard: the rehearsal is an operator tool.
    """
    client = build_demo_sdk_client(
        api_key=credentials.binance_api_key, api_secret=credentials.binance_api_secret
    )
    gate = RestRateLimitGate(policy=signed_call_policy.rate_limit, clock=clock)
    adapter = BinanceUsdmAdapter(
        sdk_client=client, rest_gate=gate, signed_call_policy=signed_call_policy
    )
    return AdapterBundle(inner=adapter, guard=lambda: assert_demo_sdk_client(client))


# --------------------------------------------------------------------------- #
# Evidence (SR-8): only exchange-returned dataclasses can become exchange records.
# --------------------------------------------------------------------------- #

_ORDER_RECORD_TYPES = (EntryPlacementResult, AlgoPlacementResult, MarketCloseResult)
_OBSERVATION_TYPES = (
    OrderProbe,
    AlgoOrderProbe,
    OpenOrderSnapshot,
    OpenAlgoOrderSnapshot,
    PositionSnapshot,
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    return str(value)


def _utc_stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


class EvidenceRecorder:
    """Collects the run record and writes it as scrubbed, atomic, LF-only JSON."""

    def __init__(
        self,
        *,
        mode: RunMode,
        scenario: str,
        symbol: str,
        base_url: str,
        environ: Mapping[str, str],
        clock: Callable[[], datetime],
    ) -> None:
        self.mode = mode
        self.scenario = scenario
        self.symbol = symbol
        self.base_url = base_url
        self._environ = dict(environ)
        self._clock = clock
        self._started = clock()
        self.steps: list[dict[str, Any]] = []
        self.exchange_orders: list[dict[str, Any]] = []
        self.observations: list[dict[str, Any]] = []
        self.planned_requests: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.synthetic_inputs: list[str] = []
        self.constraints: dict[str, Any] = {}
        self.details: dict[str, Any] = {}
        self.attestation_map: dict[str, Any] = {}
        self.outcome = OUTCOME_FAILED

    # ----- recording --------------------------------------------------------- #

    def add_step(self, name: str, status: str, detail: str) -> None:
        self.steps.append({"name": name, "status": status, "detail": detail})

    def add_synthetic_input(self, text: str) -> None:
        self.synthetic_inputs.append(text)

    def record_failure(self, step: str, exc: BaseException, message: str | None = None) -> None:
        """Type name only by default; an explicit message is scrubbed on write."""
        self.record_failure_name(step, type(exc).__name__, message)

    def record_failure_name(
        self, step: str, exception_type: str, message: str | None = None
    ) -> None:
        entry: dict[str, Any] = {"step": step, "exception_type": exception_type}
        if message is not None:
            entry["message"] = message
        self.failures.append(entry)

    def record_planned_request(self, method: str, request: Mapping[str, Any]) -> None:
        self.planned_requests.append({"method": method, "request": _jsonable(request)})

    def record_exchange_record(self, record: object) -> None:
        """Accept only adapter result dataclasses returned by the exchange."""
        if isinstance(record, _ORDER_RECORD_TYPES):
            if self.mode is not RunMode.EXECUTE:
                raise TypeError("a dry run cannot hold an exchange order record")
            target = self.exchange_orders
        elif isinstance(record, _OBSERVATION_TYPES):
            target = self.observations
        else:
            raise TypeError(f"not an exchange-returned record: {type(record).__name__}")
        entry = _jsonable(record)
        entry["type"] = type(record).__name__
        entry["source"] = "exchange_response"
        target.append(entry)

    def set_constraints(self, filters: SymbolFilters) -> None:
        self.constraints = {
            "symbol": filters.symbol,
            "contract_type": filters.contract_type,
            "status": filters.status,
            "price_tick_size": filters.price_tick_size,
            "quantity_step_size": filters.quantity_step_size,
            "min_quantity": filters.min_quantity,
            "max_quantity": filters.max_quantity,
            "min_notional": filters.min_notional,
            "percent_price_multiplier_up": filters.percent_price_multiplier_up,
            "percent_price_multiplier_down": filters.percent_price_multiplier_down,
        }
        self.constraints = _jsonable(self.constraints)

    # ----- output ------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EVIDENCE_SCHEMA,
            "mode": self.mode.value,
            "scenario": self.scenario,
            "symbol": self.symbol,
            "base_url": self.base_url,
            "runner_clock_utc": {
                "started": _jsonable(self._started),
                "finished": _jsonable(self._clock()),
            },
            "constraints": self.constraints,
            "steps": self.steps,
            "exchange_orders": self.exchange_orders,
            "observations": self.observations,
            "planned_requests": self.planned_requests,
            "failures": self.failures,
            "synthetic_inputs": self.synthetic_inputs,
            "details": self.details,
            "attestation_map": self.attestation_map,
            "outcome": self.outcome,
        }

    def _file_stem(self) -> str:
        kind = "DRYRUN" if self.mode is RunMode.DRY_RUN else "EVIDENCE"
        return f"09-DEMO-REHEARSAL-{kind}-{self.scenario}-{_utc_stamp(self._started)}"

    def write(self, directory: Path) -> Path:
        """Scrub, write to a temp file, os.replace into a fresh name, re-check the result."""
        redactor = Redactor.from_environ(self._environ)
        text = json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=True) + "\n"
        text = redactor.scrub(text)
        directory.mkdir(parents=True, exist_ok=True)
        stem = self._file_stem()
        target = directory / f"{stem}.json"
        counter = 2
        while target.exists():
            target = directory / f"{stem}-{counter}.json"
            counter += 1
        temp = directory / f".{target.name}.tmp"
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temp, target)
        written = target.read_bytes().decode("utf-8")
        if redactor.scrub(written) != written:
            target.unlink()
            raise RuntimeError("evidence failed the post-write secret scan and was removed")
        return target


# --------------------------------------------------------------------------- #
# Guarded adapter (SR-2, SR-9): explicit methods only, no attribute passthrough.
# --------------------------------------------------------------------------- #


def _exchange_error_detail(exc: BaseException) -> str | None:
    """The exchange's own error code and text, only when the SDK carried an int code.

    Binance error text is public API vocabulary (never request data); it is still scrubbed
    on write and capped here. Anything without an int `status_code` yields no detail.
    """
    code = getattr(exc, "status_code", None)
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    text = str(getattr(exc, "error_message", "") or "")[:200]
    return f"binance code {code}: {text}"


class GuardedAdapter:
    """Run the host guard before every call; in DRY_RUN never reach a mutating method."""

    def __init__(
        self,
        inner: BinanceUsdmAdapter,
        *,
        guard: Callable[[], None],
        mode: RunMode,
        clock: Callable[[], datetime],
        recorder: EvidenceRecorder,
    ) -> None:
        self._inner = inner
        self._guard = guard
        self._mode = mode
        self._clock = clock
        self._recorder = recorder
        self.call_count = 0
        self.error_count = 0
        self.mutating_attempts = 0
        self.error_log: list[tuple[str, str, str | None]] = []
        self._sim_orders: dict[str, str] = {}
        self._sim_algos: dict[str, str] = {}

    @property
    def mode(self) -> RunMode:
        return self._mode

    async def _call(self, name: str, call: Callable[[], Awaitable[_T]]) -> _T:
        self._guard()
        self.call_count += 1
        try:
            return await call()
        except Exception as exc:
            self.error_count += 1
            self.error_log.append((name, type(exc).__name__, _exchange_error_detail(exc)))
            raise

    # ----- reads ------------------------------------------------------------- #

    async def exchange_info(self) -> list[SymbolFilters]:
        return await self._call("exchange_info", lambda: self._inner.exchange_info())

    async def server_time(self) -> datetime:
        return await self._call("server_time", lambda: self._inner.server_time())

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        return await self._call(
            "klines", lambda: self._inner.klines(symbol, interval, start_ms, end_ms, limit)
        )

    async def mark_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[MarkKline]:
        return await self._call(
            "mark_klines",
            lambda: self._inner.mark_klines(symbol, interval, start_ms, end_ms, limit),
        )

    async def user_commission_rate(self, symbol: str) -> CommissionRates:
        return await self._call(
            "user_commission_rate", lambda: self._inner.user_commission_rate(symbol)
        )

    async def get_position_mode(self) -> PositionModeResult:
        return await self._call("get_position_mode", lambda: self._inner.get_position_mode())

    async def get_mark_price(self, *, symbol: str) -> MarkPriceReading:
        """The live mark price of `symbol` (plan 19-13, gate 5e); a read, allowed in DRY_RUN."""
        return await self._call("get_mark_price", lambda: self._inner.get_mark_price(symbol=symbol))

    async def symbol_lot_filters(self, *, symbol: str) -> LotFilters:
        """The live lot filters of `symbol` (the protection coordinator reads them); a read."""
        return await self._call(
            "symbol_lot_filters", lambda: self._inner.symbol_lot_filters(symbol=symbol)
        )

    @staticmethod
    def error_facts(exc: BaseException) -> Any:
        """The SDK-free error facts of `exc` (pure classification, no request)."""
        return BinanceUsdmAdapter.error_facts(exc)

    async def snapshot_open_normal_orders(
        self, *, symbol: str | None = None
    ) -> list[OpenOrderSnapshot]:
        return await self._call(
            "snapshot_open_normal_orders",
            lambda: self._inner.snapshot_open_normal_orders(symbol=symbol),
        )

    async def snapshot_open_algo_orders(
        self, *, symbol: str | None = None
    ) -> list[OpenAlgoOrderSnapshot]:
        return await self._call(
            "snapshot_open_algo_orders",
            lambda: self._inner.snapshot_open_algo_orders(symbol=symbol),
        )

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[PositionSnapshot]:
        return await self._call(
            "snapshot_positions", lambda: self._inner.snapshot_positions(symbol=symbol)
        )

    async def query_order_by_client(self, *, symbol: str, orig_client_order_id: str) -> OrderProbe:
        simulated = self._sim_orders.get(orig_client_order_id)
        if self._mode is RunMode.DRY_RUN and simulated is not None:
            return OrderProbe(
                client_order_id=orig_client_order_id,
                found=True,
                order_id=f"DRYRUN-{orig_client_order_id}",
                status=simulated,
                update_time_utc=self._clock(),
            )
        probe = await self._call(
            "query_order_by_client",
            lambda: self._inner.query_order_by_client(
                symbol=symbol, orig_client_order_id=orig_client_order_id
            ),
        )
        if probe.found:
            self._recorder.record_exchange_record(probe)
        return probe

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> AlgoOrderProbe:
        simulated = self._sim_algos.get(client_algo_id)
        if self._mode is RunMode.DRY_RUN and simulated is not None:
            return AlgoOrderProbe(
                client_algo_id=client_algo_id,
                found=True,
                algo_status=simulated,
                update_time_utc=self._clock(),
            )
        probe = await self._call(
            "query_algo_order_by_client",
            lambda: self._inner.query_algo_order_by_client(client_algo_id=client_algo_id),
        )
        if probe.found:
            self._recorder.record_exchange_record(probe)
        return probe

    # ----- mutating methods (blocked in DRY_RUN) ------------------------------ #

    async def place_entry(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        time_in_force: str,
        quantity: Decimal,
        price: Decimal,
        new_client_order_id: str,
        good_till_date: int | None = None,
    ) -> EntryPlacementResult:
        self.mutating_attempts += 1
        if self._mode is RunMode.DRY_RUN:
            self._recorder.record_planned_request(
                "place_entry",
                {
                    "symbol": symbol,
                    "side": side,
                    "position_side": position_side,
                    "time_in_force": time_in_force,
                    "good_till_date": good_till_date,
                    "quantity": quantity,
                    "price": price,
                    "new_client_order_id": new_client_order_id,
                },
            )
            self._sim_orders[new_client_order_id] = "NEW"
            return EntryPlacementResult(
                symbol=symbol,
                client_order_id=new_client_order_id,
                exchange_order_id=f"DRYRUN-{new_client_order_id}",
                side=side,
                position_side=position_side,
                order_type="LIMIT",
                time_in_force=time_in_force,
                status="NEW",
                quantity=quantity,
                price=price,
                update_time_utc=self._clock(),
            )
        result = await self._call(
            "place_entry",
            lambda: self._inner.place_entry(
                symbol=symbol,
                side=side,
                position_side=position_side,
                time_in_force=time_in_force,
                quantity=quantity,
                price=price,
                new_client_order_id=new_client_order_id,
                good_till_date=good_till_date,
            ),
        )
        self._recorder.record_exchange_record(result)
        return result

    async def place_algo_protective(
        self,
        *,
        symbol: str,
        side: str,
        algo_type: str,
        type: str,
        position_side: str,
        trigger_price: Decimal,
        close_position: bool,
        quantity: Decimal | None,
        working_type: str,
        client_algo_id: str,
        reduce_only: bool | None = None,
    ) -> AlgoPlacementResult:
        self.mutating_attempts += 1
        if self._mode is RunMode.DRY_RUN:
            self._recorder.record_planned_request(
                "place_algo_protective",
                {
                    "symbol": symbol,
                    "side": side,
                    "algo_type": algo_type,
                    "type": type,
                    "position_side": position_side,
                    "trigger_price": trigger_price,
                    "close_position": close_position,
                    "quantity": quantity,
                    "working_type": working_type,
                    "client_algo_id": client_algo_id,
                    "reduce_only": reduce_only,
                },
            )
            self._sim_algos[client_algo_id] = "NEW"
            return AlgoPlacementResult(
                symbol=symbol,
                client_algo_id=client_algo_id,
                algo_id=f"DRYRUN-{client_algo_id}",
                algo_type=algo_type,
                order_type=type,
                side=side,
                position_side=position_side,
                algo_status="NEW",
                trigger_price=trigger_price,
                close_position=close_position,
                working_type=working_type,
                update_time_utc=self._clock(),
            )
        result = await self._call(
            "place_algo_protective",
            lambda: self._inner.place_algo_protective(
                symbol=symbol,
                side=side,
                algo_type=algo_type,
                type=type,
                position_side=position_side,
                trigger_price=trigger_price,
                close_position=close_position,
                quantity=quantity,
                working_type=working_type,
                client_algo_id=client_algo_id,
                reduce_only=reduce_only,
            ),
        )
        self._recorder.record_exchange_record(result)
        return result

    async def cancel_normal_order(self, *, symbol: str, orig_client_order_id: str) -> None:
        self.mutating_attempts += 1
        if self._mode is RunMode.DRY_RUN:
            self._recorder.record_planned_request(
                "cancel_normal_order",
                {"symbol": symbol, "orig_client_order_id": orig_client_order_id},
            )
            if orig_client_order_id in self._sim_orders:
                self._sim_orders[orig_client_order_id] = "CANCELED"
            return
        await self._call(
            "cancel_normal_order",
            lambda: self._inner.cancel_normal_order(
                symbol=symbol, orig_client_order_id=orig_client_order_id
            ),
        )

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> None:
        self.mutating_attempts += 1
        if self._mode is RunMode.DRY_RUN:
            self._recorder.record_planned_request(
                "cancel_algo_order", {"symbol": symbol, "client_algo_id": client_algo_id}
            )
            if client_algo_id in self._sim_algos:
                self._sim_algos[client_algo_id] = "CANCELED"
            return
        await self._call(
            "cancel_algo_order",
            lambda: self._inner.cancel_algo_order(symbol=symbol, client_algo_id=client_algo_id),
        )

    async def place_market_close(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        quantity: Decimal,
        new_client_order_id: str,
    ) -> MarketCloseResult:
        """The emergency reduce-only MARKET close (plan 19-12): counted, simulated in DRY_RUN."""
        self.mutating_attempts += 1
        if self._mode is RunMode.DRY_RUN:
            self._recorder.record_planned_request(
                "place_market_close",
                {
                    "symbol": symbol,
                    "side": side,
                    "position_side": position_side,
                    "quantity": quantity,
                    "new_client_order_id": new_client_order_id,
                },
            )
            return MarketCloseResult(
                symbol=symbol,
                client_order_id=new_client_order_id,
                exchange_order_id=f"DRYRUN-{new_client_order_id}",
                side=side,
                position_side=position_side,
                status="NEW",
                executed_quantity=None,
                average_price=None,
                update_time_utc=self._clock(),
            )
        result = await self._call(
            "place_market_close",
            lambda: self._inner.place_market_close(
                symbol=symbol,
                side=side,
                position_side=position_side,
                quantity=quantity,
                new_client_order_id=new_client_order_id,
            ),
        )
        self._recorder.record_exchange_record(result)
        return result


# --------------------------------------------------------------------------- #
# CLI gate (SR-9).
# --------------------------------------------------------------------------- #


class _ArgumentParser(argparse.ArgumentParser):
    """argparse that raises instead of exiting, so `main` returns the exit code."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="demo_rehearsal",
        description="Binance Demo Trading rehearsal runner (dry run by default).",
        allow_abbrev=False,
    )
    parser.add_argument("--scenario", choices=SCENARIOS, default="far")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="send real requests to Demo Trading (interactive terminal and typed phrase)",
    )
    parser.add_argument(
        "--approval-timeout-seconds", type=int, default=DEFAULT_APPROVAL_TIMEOUT_SECONDS
    )
    parser.add_argument(
        "--discovery-timeout-seconds", type=int, default=DEFAULT_DISCOVERY_TIMEOUT_SECONDS
    )
    parser.add_argument("--evidence-dir", type=Path, default=None)
    parser.add_argument(
        "--limits-file",
        type=Path,
        default=DEFAULT_LIMITS_FILE,
        help="the ratified Binance limits file (default: config/binance/binance-limits-v1.toml)",
    )
    return parser


def required_phrase(scenario: str) -> str:
    return f"DEMO {scenario.upper()} {SYMBOL}"


def _confirm_execute(
    scenario: str,
    is_tty: Callable[[], bool],
    read_confirmation: Callable[[str], str],
) -> None:
    if not is_tty():
        raise ConfirmationRefused("--execute needs an interactive terminal")
    phrase = required_phrase(scenario)
    try:
        typed = read_confirmation(f"Type exactly '{phrase}' to send real Demo requests: ")
    except (EOFError, OSError):
        raise ConfirmationRefused("no confirmation was typed") from None
    if typed != phrase:
        raise ConfirmationRefused("the typed phrase did not match")


# --------------------------------------------------------------------------- #
# Run journal, in-memory approval book and the approval channel (SR-7, SR-11).
# --------------------------------------------------------------------------- #


class RunJournal:
    """Collects journal events in memory (the rehearsal has no database)."""

    def __init__(self) -> None:
        self.events: list[JournalEvent] = []

    def record(self, event: Any) -> None:
        self.events.append(event)

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self.events:
            counts[event.event_type] = counts.get(event.event_type, 0) + 1
        return dict(sorted(counts.items()))


def chat_fingerprint(chat_id: int) -> str:
    """Only a sha256 prefix of a chat id is ever written to evidence (T-tx9-07)."""
    return hashlib.sha256(str(chat_id).encode("utf-8")).hexdigest()[:12]


class ApprovalBook:
    """In-memory approvals, short-id mapping and binding contexts for one run."""

    def __init__(self, journal: RunJournal) -> None:
        self.journal = journal
        self._by_hash: dict[str, Approval] = {}
        self._mappings: dict[str, tuple[str, str]] = {}
        self._contexts: dict[str, dict[str, Any]] = {}

    def register(self, *, approval: Approval, raw_token: str, context: Mapping[str, Any]) -> None:
        short_id = derive_short_id(approval.signal_id)
        self._by_hash[approval.approval_token_hash] = approval
        self._mappings[short_id] = (approval.signal_id, approval.trade_plan_id)
        self._contexts[short_id] = {**context, "raw_token": raw_token}

    def lookup_by_short_id(self, short_id: str) -> tuple[str, str] | None:
        return self._mappings.get(short_id)

    def lookup_by_token_hash(self, token_hash: str) -> Approval | None:
        return self._by_hash.get(token_hash)

    def save_atomic(self, approval: Approval, mapping: ShortIdMapping | None) -> None:
        del mapping  # the mapping was registered when the approval was issued
        self._by_hash[approval.approval_token_hash] = approval

    def journal_receipt(self, event: JournalEvent) -> None:
        self.journal.record(event)

    def binding_context_resolver(self, short_id: str) -> dict[str, Any] | None:
        context = self._contexts.get(short_id)
        return None if context is None else dict(context)

    def fingerprint(self, approval: Approval) -> str:
        """Text form of the stored row, to prove an unauthorized tap left it untouched."""
        return repr(self._by_hash[approval.approval_token_hash])


@dataclass(frozen=True)
class TapHandlerDeps:
    """What the tap intake needs: the production on_callback dependencies."""

    authorized_chat_id: int
    binding_context_resolver: Callable[[str], dict[str, Any] | None]
    dispatch: Callable[..., DispatchResult]


class ApprovalChannel(Protocol):
    """Telegram side of the rehearsal: send keyboards, wait for taps, discover a second chat."""

    @property
    def notifier(self) -> Any: ...

    async def open(self, deps: TapHandlerDeps) -> None: ...

    async def close(self) -> None: ...

    async def send_approval(
        self, *, chat_id: int, text: str, signal_id: str, kind: str
    ) -> None: ...

    async def next_result(self, *, timeout_seconds: int) -> DispatchResult | None: ...

    async def discover_other_chat(self, *, timeout_seconds: int) -> int | None: ...


class PtbApprovalChannel:
    """Real channel on python-telegram-bot polling.

    Only ONE process may poll a bot token at a time: stop the bot service and any other
    poller before running a scenario. The Application is built by the production
    `build_application`, so a tap is handled by the production `on_callback` and
    `dispatch_callback`. Nothing here is exercised by the offline tests.
    """

    def __init__(self, credentials: RehearsalCredentials) -> None:
        self._credentials = credentials
        self._app: Any = None
        self._results: asyncio.Queue[DispatchResult] | None = None
        self._chats: asyncio.Queue[int] | None = None

    @property
    def notifier(self) -> Any:
        if self._app is None:
            return None
        return self._app.bot

    async def open(self, deps: TapHandlerDeps) -> None:
        from telegram.ext import CommandHandler

        results: asyncio.Queue[DispatchResult] = asyncio.Queue()
        chats: asyncio.Queue[int] = asyncio.Queue()
        holder: list[Any] = []

        def dispatch(parsed: Any, **kwargs: Any) -> DispatchResult:
            result = deps.dispatch(parsed, **kwargs)
            results.put_nowait(result)
            return result

        async def reply(chat_id: int, text: str) -> None:
            await holder[0].bot.send_message(chat_id=chat_id, text=text)

        async def on_start(update: Any, context: Any) -> None:
            chat = update.effective_chat
            if chat is not None and int(chat.id) != deps.authorized_chat_id:
                chats.put_nowait(int(chat.id))

        app: Any = build_application(
            token=self._credentials.telegram_bot_token,
            authorized_chat_id=deps.authorized_chat_id,
            binding_context_resolver=deps.binding_context_resolver,
            dispatch=dispatch,
            reply_text_fn=reply,
        )
        holder.append(app)
        app.add_handler(CommandHandler("start", on_start))
        self._app, self._results, self._chats = app, results, chats
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=["message", "callback_query"])

    async def close(self) -> None:
        app: Any = self._app
        if app is None:
            return
        self._app = None

        async def stop_updater() -> None:
            if app.updater is not None:
                await app.updater.stop()

        for stop in (stop_updater, app.stop, app.shutdown):
            try:
                await stop()
            except Exception:  # noqa: BLE001 - keep shutting down, nothing to report
                continue

    async def send_approval(self, *, chat_id: int, text: str, signal_id: str, kind: str) -> None:
        if self._app is None:
            raise RuntimeError("channel is not open")
        markup = (
            build_approve_keyboard(signal_id)
            if kind == "APPROVE"
            else build_skip_keyboard(signal_id)
        )
        await self._app.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)

    async def next_result(self, *, timeout_seconds: int) -> DispatchResult | None:
        if self._results is None:
            return None
        try:
            return await asyncio.wait_for(self._results.get(), timeout=timeout_seconds)
        except TimeoutError:
            return None

    async def discover_other_chat(self, *, timeout_seconds: int) -> int | None:
        if self._chats is None:
            return None
        try:
            return await asyncio.wait_for(self._chats.get(), timeout=timeout_seconds)
        except TimeoutError:
            return None


def default_channel_factory(credentials: RehearsalCredentials) -> ApprovalChannel:
    return PtbApprovalChannel(credentials)


# --------------------------------------------------------------------------- #
# Run context.
# --------------------------------------------------------------------------- #


@dataclass
class RunContext:
    """Everything one scenario run needs, built once by `build_context`."""

    guarded: GuardedAdapter
    recorder: EvidenceRecorder
    channel: ApprovalChannel | None
    credentials: RehearsalCredentials
    scenario: str
    mode: RunMode
    clock: Callable[[], datetime]
    sleep: Callable[[int], Awaitable[None]]
    approval_timeout_seconds: int
    discovery_timeout_seconds: int
    token_factory: Callable[[], str]
    journal: RunJournal
    book: ApprovalBook
    run_id: str
    controller: LiveEnablementController | None = None
    health: HealthVerdict | None = None
    # Plan 19-13. None loads the committed file (execution limits) or the ratified Binance
    # limits file (drift limits); a test injects a value instead.
    execution_limits: ExecutionLimits | None = None
    drift_limits: DriftLimits | None = None
    # Plan 19-16. The coordinator `build_live_context` built (the fill scenario steps it).
    coordinator: ProtectionCoordinator | None = None
    # Plan 19-16, TEST SEAM only (no CLI flag): margin_type, leverage and equity_used for the
    # plan snapshot. None is the real behavior: they are unknown until Phases 21-22, the
    # snapshot stays INCOMPLETE and every TP placement is refused into TP_UNAVAILABLE.
    snapshot_live_inputs: Mapping[str, Any] | None = None


def build_context(
    *,
    guarded: GuardedAdapter,
    recorder: EvidenceRecorder,
    channel: ApprovalChannel | None,
    credentials: RehearsalCredentials,
    scenario: str,
    mode: RunMode,
    clock: Callable[[], datetime],
    sleep: Callable[[int], Awaitable[None]],
    approval_timeout_seconds: int,
    discovery_timeout_seconds: int,
    token_factory: Callable[[], str],
    execution_limits: ExecutionLimits | None = None,
    drift_limits: DriftLimits | None = None,
    snapshot_live_inputs: Mapping[str, Any] | None = None,
) -> RunContext:
    journal = RunJournal()
    return RunContext(
        guarded=guarded,
        recorder=recorder,
        channel=channel,
        credentials=credentials,
        scenario=scenario,
        mode=mode,
        clock=clock,
        sleep=sleep,
        approval_timeout_seconds=approval_timeout_seconds,
        discovery_timeout_seconds=discovery_timeout_seconds,
        token_factory=token_factory,
        journal=journal,
        book=ApprovalBook(journal),
        run_id=f"{scenario}-{_utc_stamp(clock())}",
        execution_limits=execution_limits,
        drift_limits=drift_limits,
        snapshot_live_inputs=snapshot_live_inputs,
    )


def _require_channel(ctx: RunContext) -> ApprovalChannel:
    if ctx.channel is None:
        raise RehearsalAbort("no Telegram channel is configured")
    return ctx.channel


# --------------------------------------------------------------------------- #
# Health preflight (SR-6): ten probes first, any FAIL aborts before any order.
# --------------------------------------------------------------------------- #

_DEGRADED_DETAILS: dict[str, str] = {
    CHECK_WS_CONNECTION_STATE: (
        "not evaluated: this REST-only rehearsal opens no WebSocket (no market stream)"
    ),
    CHECK_USER_DATA_STREAM_STATE: (
        "not evaluated: this REST-only rehearsal opens no user-data stream (Phase 18)"
    ),
    CHECK_DB_WRITES: "not evaluated: this rehearsal has no PostgreSQL, so no db writes occur",
}


def _degraded_result(
    ctx: RunContext, name: str, detail: str, now_utc: datetime
) -> HealthCheckResult:
    payload_json = json.dumps(
        {"check": name, "status": STATUS_DEGRADED, "detail": detail}, separators=(",", ":")
    )
    ctx.journal.record(
        JournalEvent(
            journal_event_id=content_hash_event_id(
                prefix="health_check",
                event_type="HEALTH_CHECK",
                entity_id=name,
                occurred_at_utc=now_utc,
                payload_json=payload_json,
            ),
            occurred_at_utc=now_utc,
            event_type="HEALTH_CHECK",
            entity_type="HealthProbe",
            entity_id=name,
            correlation_id="execution_health",
            payload_json=payload_json,
        )
    )
    return HealthCheckResult(
        check_name=name, status=STATUS_DEGRADED, detail=detail, observed_at_utc=now_utc
    )


async def run_health_preflight(ctx: RunContext) -> HealthVerdict:
    """Evaluate the ten probes against live Demo REST state; record them verbatim."""
    guarded = ctx.guarded
    now = await guarded.server_time()
    minute = await guarded.klines(SYMBOL, "1m", limit=2)
    hourly = await guarded.klines(SYMBOL, "1h", limit=3)
    positions = await guarded.snapshot_positions(symbol=SYMBOL)
    orders = await guarded.snapshot_open_normal_orders(symbol=SYMBOL)
    algos = await guarded.snapshot_open_algo_orders(symbol=SYMBOL)

    last_market_event = max((k.open_time_utc for k in minute), default=None)
    last_closed = max((k.close_time_utc for k in hourly if k.close_time_utc <= now), default=None)
    clean_slate = not (positions or orders or algos)
    divergences: list[dict[str, str]] = []
    if positions and not any(a.order_type == "STOP_MARKET" and a.close_position for a in algos):
        divergences.append({"kind": "ENTRY_WITHOUT_PROTECTIVE"})
    if (orders or algos) and not positions:
        divergences.append({"kind": "ORPHAN_PROTECTIVE"})

    journal = ctx.journal
    results: dict[str, HealthCheckResult] = {}
    for result in (
        check_market_feed_freshness(
            last_market_event_at_utc=last_market_event,
            now_utc=now,
            staleness_threshold=MARKET_FEED_STALENESS,
            journal=journal,
        ),
        check_last_closed_candle_time(
            last_closed_candle_close_utc=last_closed,
            now_utc=now,
            expected_cadence=CANDLE_CADENCE,
            journal=journal,
        ),
        check_rest_error_rate(
            error_count=guarded.error_count,
            total_count=guarded.call_count,
            max_error_rate=MAX_REST_ERROR_RATE,
            now_utc=now,
            journal=journal,
        ),
        check_reconciliation_drift(positions_reconciled=clean_slate, now_utc=now, journal=journal),
        await check_telegram_delivery(
            notifier=None if ctx.channel is None else ctx.channel.notifier,
            chat_id=ctx.credentials.telegram_chat_id,
            probe_text="Demo rehearsal health probe (no action needed)",
            now_utc=now,
            journal=journal,
        ),
        check_unprotected_positions(divergences=divergences, now_utc=now, journal=journal),
        check_orphaned_orders(divergences=divergences, now_utc=now, journal=journal),
    ):
        results[result.check_name] = result
    for name, detail in _DEGRADED_DETAILS.items():
        results[name] = _degraded_result(ctx, name, detail, now)

    ordered = [results[name] for name in ALL_CHECK_NAMES]
    verdict = run_health_checks(results=ordered)
    ctx.health = verdict
    ctx.recorder.details["health"] = [
        {"check_name": r.check_name, "status": r.status, "detail": r.detail} for r in ordered
    ]
    degraded = [r.check_name for r in ordered if r.status == STATUS_DEGRADED]
    if verdict.is_no_trade:
        failed = [r.check_name for r in ordered if r.status == STATUS_FAIL]
        ctx.recorder.add_step(
            "health_preflight", STEP_FAILED, f"health FAIL before any order: {', '.join(failed)}"
        )
    else:
        ctx.recorder.add_step(
            "health_preflight",
            STEP_PASSED,
            f"{len(ordered) - len(degraded)} PASS, {len(degraded)} DEGRADED "
            f"({', '.join(degraded)}); none FAILED",
        )
    return verdict


async def _require_healthy(ctx: RunContext) -> HealthVerdict:
    verdict = await run_health_preflight(ctx)
    if verdict.is_no_trade:
        raise RehearsalAbort("health preflight failed")
    return verdict


# --------------------------------------------------------------------------- #
# Plan derivation (SR-4): a pure function of exchangeInfo, the mark price and the parameters.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DerivedPlan:
    """The rehearsal plan. Every price, quantity and rate is a Decimal."""

    scenario: str
    run_id: str
    observed_at: datetime
    mark_price: Decimal
    entry_price: Decimal
    stop_loss: Decimal
    tp1_trigger: Decimal
    tp2_trigger: Decimal
    quantity: Decimal
    tp1_quantity: Decimal
    equity: Decimal
    risk_rate: Decimal
    rr: Decimal
    trade_plan: TradePlan
    constraints: ConstraintSnapshot
    parameter_set: ParameterSet
    cost_rates: CostRates

    @property
    def signal_id(self) -> str:
        return self.trade_plan.signal_id

    def to_evidence(self) -> dict[str, Any]:
        evidence: dict[str, Any] = _jsonable(
            {
                "scenario": self.scenario,
                "run_id": self.run_id,
                "mark_price": self.mark_price,
                "entry_price": self.entry_price,
                "stop_loss": self.stop_loss,
                "tp1_trigger": self.tp1_trigger,
                "tp2_trigger": self.tp2_trigger,
                "quantity": self.quantity,
                "tp1_quantity": self.tp1_quantity,
                "tp1_quantity_fraction": TP1_QUANTITY_FRACTION,
                "rehearsal_equity": self.equity,
                "risk_rate": self.risk_rate,
                "trade_plan_id": self.trade_plan.trade_plan_id,
                "plan_hash": self.trade_plan.plan_hash,
                "expiry_utc": self.trade_plan.expiry_utc,
                "strategy_version": self.parameter_set.strategy_version,
                "parameter_set_id": self.parameter_set.parameter_set_id,
                "parameter_set_hash": self.parameter_set.parameter_set_hash,
            }
        )
        return evidence


def constraint_values(filters: SymbolFilters) -> dict[str, Decimal]:
    return {
        "price_tick_size": filters.price_tick_size,
        "quantity_step_size": filters.quantity_step_size,
        "min_quantity": filters.min_quantity,
        "min_notional": filters.min_notional,
    }


def _ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value // step) * step


def _portfolio_inputs(params: Mapping[str, Any]) -> dict[str, Any]:
    return {key: params[key] for key in _PORTFOLIO_KEYS}


def build_risk_kwargs(
    plan: DerivedPlan,
    *,
    trade_plan: TradePlan,
    constraints: ConstraintSnapshot,
    cost_rates: CostRates,
    now_utc: datetime,
) -> dict[str, Any]:
    """The `evaluate_risk` inputs, with the five portfolio thresholds resolved to quote amounts."""
    params = plan.parameter_set.params
    return {
        "trade_plan": trade_plan,
        "candidate_position_side": "LONG",
        "account_state": AccountState(equity=plan.equity, risk_rate=plan.risk_rate),
        "constraint_snapshot": constraints,
        "open_positions": [],
        "daily_loss_quote": Decimal("0"),
        "now_utc": now_utc,
        "ttl": timedelta(seconds=int(params["constraint_snapshot_ttl_seconds"])),
        "cost_rates": cost_rates,
        "min_stop_distance_rate": params["min_stop_distance_rate"],
        "max_cost_to_risk": params["max_cost_to_risk"],
        "minimum_risk_utilization_after_rounding": params[
            "minimum_risk_utilization_after_rounding"
        ],
        "parameter_set": resolve_absolute_thresholds(
            parameter_set=_portfolio_inputs(params), equity=plan.equity
        ),
    }


def resolve_rates(
    *,
    parameter_set: ParameterSet,
    commission: CommissionRates,
    observed_at: datetime,
) -> CostRates:
    """Live cost rates from the account commission (fail closed, never a zero fee)."""
    params = parameter_set.params
    parameter_rates = CostRates(
        fee_rate_entry=params["fee_rate_entry"],
        entry_slippage_rate=params["expected_slippage"],
        fee_rate_exit=params["fee_rate_exit"],
        exit_slippage_rate=params["exit_slippage_rate"],
        fee_source=FEE_SOURCE_PARAMETER,
    )
    resolved = resolve_live_cost_rates(
        parameter_rates=parameter_rates,
        account_commission=AccountCommission(
            symbol=commission.symbol,
            maker_rate=commission.maker_rate,
            taker_rate=commission.taker_rate,
            observed_at_utc=observed_at,
        ),
        candidate_symbol=SYMBOL,
        now_utc=observed_at,
        ttl=timedelta(seconds=int(params["commission_rate_ttl_seconds"])),
    )
    if resolved.rates is None:
        raise RehearsalAbort(f"live cost rates unavailable: {resolved.reason_code}")
    return resolved.rates


def derive_plan(
    *,
    scenario: str,
    filters: SymbolFilters,
    mark_price: Decimal,
    parameter_set: ParameterSet,
    commission: CommissionRates,
    observed_at: datetime,
    run_id: str,
    approval_timeout_seconds: int,
) -> DerivedPlan:
    """Derive the BTCUSDT plan and prove the unmodified risk pipeline sizes exactly it."""
    if SYMBOL not in LIVE5_SYMBOLS:
        raise RehearsalAbort(f"{SYMBOL} is not in the live-5 universe")
    up = filters.percent_price_multiplier_up
    down = filters.percent_price_multiplier_down
    if scenario == "fill":
        if up is None:
            raise RehearsalAbort("PERCENT_PRICE multiplierUp is missing from exchangeInfo")
        raw_entry = mark_price * (Decimal("1") + (up - Decimal("1")) * FAR_BAND_FRACTION)
    else:
        if down is None:
            raise RehearsalAbort("PERCENT_PRICE multiplierDown is missing from exchangeInfo")
        raw_entry = mark_price * (Decimal("1") - (Decimal("1") - down) * FAR_BAND_FRACTION)
    tick = filters.price_tick_size
    step = filters.quantity_step_size
    entry = quantize_price(price=raw_entry, price_tick_size=tick, direction=PRICE_ROUND_DOWN)
    # The stop is anchored at or below the mark and the targets at or above it, so neither
    # can trigger on placement even when the entry sits on the far side of the mark.
    stop = quantize_price(
        price=min(entry, mark_price) * (Decimal("1") - SL_DISTANCE_RATE),
        price_tick_size=tick,
        direction=PRICE_ROUND_UP,
    )
    target_anchor = max(entry, mark_price)
    tp1 = quantize_price(
        price=target_anchor * (Decimal("1") + TP1_DISTANCE_RATE),
        price_tick_size=tick,
        direction=PRICE_ROUND_DOWN,
    )
    tp2 = quantize_price(
        price=target_anchor * (Decimal("1") + TP2_DISTANCE_RATE),
        price_tick_size=tick,
        direction=PRICE_ROUND_DOWN,
    )
    if not stop < entry or not stop < mark_price or not tp1 > mark_price or not tp2 > tp1:
        raise RehearsalAbort("derived levels would trigger on placement or are out of order")
    if scenario == "fill" and not entry > mark_price:
        raise RehearsalAbort("the fill entry is not above the mark price")
    if scenario != "fill" and not entry < mark_price:
        raise RehearsalAbort("the far entry is not below the mark price")

    quantity = _ceil_to_step(max(filters.min_quantity, filters.min_notional / entry), step)
    tp1_quantity = Decimal("0")
    for _ in range(_QUANTITY_SEARCH_LIMIT):
        tp1_quantity = _floor_to_step(quantity * TP1_QUANTITY_FRACTION, step)
        if (
            quantity * entry >= filters.min_notional
            and tp1_quantity >= filters.min_quantity
            and tp1_quantity * tp1 >= filters.min_notional
        ):
            break
        quantity += step
    else:
        raise RehearsalAbort("no quantity passes the exchange minimums")
    if filters.max_quantity is not None and quantity > filters.max_quantity:
        raise RehearsalAbort("the smallest passing quantity exceeds the maximum quantity")

    params = parameter_set.params
    rates = resolve_rates(
        parameter_set=parameter_set, commission=commission, observed_at=observed_at
    )
    risk_rate = params["risk_rate"]
    risk_per_unit = (entry - stop) + per_unit_round_trip_cost(
        side="LONG", entry_price=entry, stop_price=stop, rates=rates
    )
    # The risk pipeline sizes from equity, so back-solve the rehearsal equity that makes it
    # return exactly this quantity, rounded UP to the cent. It is a rehearsal input.
    equity = _ceil_to_step(quantity * risk_per_unit / risk_rate, Decimal("0.01"))
    rr = (tp1 - entry) / (entry - stop)

    signal_id = sha256_hex({"run_id": run_id, "role": "signal"})
    take_profit_json = json.dumps(
        {"tp1": str(tp1), "tp2": str(tp2)}, sort_keys=True, separators=(",", ":")
    )
    # Plan 19-13 (D-01, D-08): the execution binding re-derives the plan hash with the planner's
    # own algorithm and the pre-placement check reads a CANDLE_CLOSE invalidation rule, so the
    # rehearsal plan carries both (a bar closing below the stop invalidates a LONG).
    invalidation_rule_json = json.dumps(
        {"basis": "CANDLE_CLOSE", "level": str(stop)}, sort_keys=True, separators=(",", ":")
    )
    expiry_utc = observed_at + timedelta(seconds=approval_timeout_seconds) + PLAN_EXPIRY_MARGIN
    plan_hash = plan_hash_from_fields(
        signal_id=signal_id,
        entry_min_price=entry,
        entry_max_price=entry,
        stop_loss_price=stop,
        take_profit_json=take_profit_json,
        invalidation_rule_json=invalidation_rule_json,
        expiry_utc=expiry_utc,
    )
    trade_plan = TradePlan(
        trade_plan_id=derive_child_id(signal_id, "trade_plan:v1"),
        signal_id=signal_id,
        trade_plan_version="demo-rehearsal-v1",
        entry_model="LIMIT_ZONE",
        entry_min_price=entry,
        entry_max_price=entry,
        stop_loss_price=stop,
        take_profit_json=take_profit_json,
        invalidation_rule_json=invalidation_rule_json,
        expiry_utc=expiry_utc,
        expected_rr_json=json.dumps({"rr": str(rr)}, sort_keys=True, separators=(",", ":")),
        risk_rate=risk_rate,
        risk_budget=equity * risk_rate,
        suggested_quantity=quantity,
        quantity_before_rounding=quantity,
        quantity_after_rounding=quantity,
        quantization_decision=QuantizationDecision.ACCEPTED.value,
        plan_hash=plan_hash,
        status=TradePlanStatus.APPROVAL_PENDING,
        created_at_utc=observed_at,
    )
    constraints = ConstraintSnapshot(
        symbol=SYMBOL,
        price_tick_size=tick,
        quantity_step_size=step,
        min_quantity=filters.min_quantity,
        min_notional=filters.min_notional,
        metadata_observed_at_utc=observed_at,
    )
    plan = DerivedPlan(
        scenario=scenario,
        run_id=run_id,
        observed_at=observed_at,
        mark_price=mark_price,
        entry_price=entry,
        stop_loss=stop,
        tp1_trigger=tp1,
        tp2_trigger=tp2,
        quantity=quantity,
        tp1_quantity=tp1_quantity,
        equity=equity,
        risk_rate=risk_rate,
        rr=rr,
        trade_plan=trade_plan,
        constraints=constraints,
        parameter_set=parameter_set,
        cost_rates=rates,
    )
    verdict = evaluate_risk(
        **build_risk_kwargs(
            plan,
            trade_plan=trade_plan,
            constraints=constraints,
            cost_rates=rates,
            now_utc=observed_at,
        )
    )
    sized = verdict.sized
    if verdict.is_no_trade or sized is None or sized.quantity != quantity:
        raise RehearsalAbort(
            f"the risk pipeline did not size the derived quantity: {verdict.reason_code}"
        )
    return plan


async def prepare_plan(ctx: RunContext, scenario: str) -> DerivedPlan:
    """Read Demo state through the guarded adapter and derive the plan."""
    guarded = ctx.guarded
    now = await guarded.server_time()
    filters = select_symbol(await guarded.exchange_info())
    ctx.recorder.set_constraints(filters)
    marks = await guarded.mark_klines(SYMBOL, "1m", limit=1)
    if not marks:
        raise RehearsalAbort("no mark price candle was returned")
    commission = await guarded.user_commission_rate(SYMBOL)
    plan = derive_plan(
        scenario=scenario,
        filters=filters,
        mark_price=marks[-1].close,
        parameter_set=load_parameter_set(STRATEGY_ID, PARAMETER_SET_ID),
        commission=commission,
        observed_at=now,
        run_id=ctx.run_id,
        approval_timeout_seconds=ctx.approval_timeout_seconds,
    )
    ctx.recorder.details["plan"] = plan.to_evidence()
    ctx.recorder.details["authorized_chat_sha256_prefix"] = chat_fingerprint(
        ctx.credentials.telegram_chat_id
    )
    for text in (
        f"rehearsal equity {plan.equity} USDT back-solved from the target quantity "
        "(a rehearsal input, not a Demo account fact)",
        "daily_loss_quote fixed at 0 (not read from the account)",
        "kill-gate state constant WITHIN_BUDGET passed to enable() "
        "(not an evaluation of the research ledger)",
        "execution intent store is the in-memory test double "
        "tests.support.intent_store_fakes.InMemoryExecutionIntentStore",
        "approval book, short-id mapping and journal are in-memory rehearsal doubles",
        "plan prices derive from the Demo mark price and exchangeInfo "
        "(rehearsal values, not a strategy signal)",
    ):
        ctx.recorder.add_synthetic_input(text)
    return plan


# --------------------------------------------------------------------------- #
# Live placement context (plan 19-13): what the manager needs beyond the approval.
# --------------------------------------------------------------------------- #


def _resolved_execution_limits(ctx: RunContext) -> ExecutionLimits:
    """The injected limits, or the committed file. A missing or invalid file aborts the run."""
    if ctx.execution_limits is None:
        try:
            ctx.execution_limits = load_execution_limits(DEFAULT_EXECUTION_LIMITS_FILE)
        except ExecutionLimitsInvalid as exc:
            raise RehearsalAbort(f"the execution limits file is unusable: {exc}") from None
    return ctx.execution_limits


def require_execution_limits_set(ctx: RunContext) -> ExecutionLimits:
    """Abort before any mutation while any execution limit is NOT_CONFIGURED (D-07, D-13).

    The failed step names the unset keys and never a value. With the committed file (every value
    NOT_CONFIGURED) every order scenario ends here, recorded honestly.
    """
    limits = _resolved_execution_limits(ctx)
    unset = limits.unset_keys()
    if unset:
        detail = f"{LIMITS_NOT_CONFIGURED}: {', '.join(unset)}"
        ctx.recorder.add_step("execution_limits", STEP_FAILED, detail)
        raise RehearsalAbort(detail)
    ctx.recorder.add_step("execution_limits", STEP_PASSED, "all four execution limits are set")
    return limits


def _resolved_drift_limits(ctx: RunContext) -> DriftLimits:
    if ctx.drift_limits is None:
        ctx.drift_limits = load_drift_limits(DEFAULT_LIMITS_FILE)
    return ctx.drift_limits


class RehearsalAlertSink:
    """`CriticalAlertSink` of the rehearsal: evidence plus an operator instruction.

    Telegram alert UX is Phase 23, so a critical alert is recorded in the evidence file and
    printed as an operator instruction at the end of the run; nothing is sent.
    """

    def __init__(self, ctx: RunContext) -> None:
        self._ctx = ctx

    def critical(
        self, *, event: str, plan_hash: str, symbol: str, reason: str, now_utc: datetime
    ) -> None:
        alerts = self._ctx.recorder.details.setdefault("critical_alerts", [])
        alerts.append(
            _jsonable(
                {
                    "event": event,
                    "plan_hash": plan_hash,
                    "symbol": symbol,
                    "reason": reason,
                    "now_utc": now_utc,
                }
            )
        )
        _instruct(
            self._ctx,
            f"CRITICAL {event} on {symbol} ({reason}): check the Binance Demo UI and close any "
            "position by hand.",
        )


async def _latest_closed_bar_close(ctx: RunContext, now: datetime) -> Decimal | None:
    """The close of the latest CLOSED 1h kline, or None when it cannot be read (fail closed)."""
    try:
        bars = await ctx.guarded.klines(SYMBOL, "1h", limit=2)
    except Exception:  # noqa: BLE001 - an unreadable bar means "not available": the gate refuses
        return None
    closed = [bar for bar in bars if bar.close_time_utc <= now]
    return closed[-1].close if closed else None


async def build_live_context(
    ctx: RunContext,
    plan: DerivedPlan,
    filters: SymbolFilters,
    constraints: ConstraintSnapshot,
    now: datetime,
    *,
    safe_mode: SafeModeController,
    intent_store: ExecutionIntentStore,
) -> LivePlacementContext:
    """The `LivePlacementContext` of one rehearsal placement (plan 19-13).

    The Signal is the one the plan is bound to (same id, symbol, LONG, strategy version and
    parameter set); the constraint snapshot comes from the re-checked filters with the MARK_PRICE
    working type; the limits are the injected ones or the committed file; the protection
    coordinator and its emergency closer run over the same guarded adapter; the bar close is read
    through it; the GTD margin is the larger of the ratified drift limits.
    """
    limits = _resolved_execution_limits(ctx)
    unset = limits.unset_keys()
    if unset:
        raise RehearsalAbort(f"{LIMITS_NOT_CONFIGURED}: {', '.join(unset)}")
    drift = _resolved_drift_limits(ctx)
    params = plan.parameter_set
    bar_close = await _latest_closed_bar_close(ctx, now)
    signal = Signal(
        signal_id=plan.signal_id,
        strategy_id=params.strategy_id,
        strategy_version=params.strategy_version,
        parameter_set_id=params.parameter_set_id,
        parameter_set_hash=params.parameter_set_hash,
        symbol=SYMBOL,
        direction="LONG",
        setup_type="DEMO_REHEARSAL",
        source_timeframe="1h",
        source_candle_close_utc=plan.observed_at,
        detected_at_utc=plan.observed_at,
        status=SignalStatus.APPROVED,
        expires_at_utc=plan.trade_plan.expiry_utc,
    )
    snapshot = build_plan_constraint_snapshot(
        plan.trade_plan.trade_plan_id,
        constraints,
        ExchangeFilterExtras(
            market_lot_min_quantity=filters.market_lot_min_quantity,
            market_lot_max_quantity=filters.market_lot_max_quantity,
            market_lot_step_size=filters.market_lot_step_size,
            percent_price_multiplier_up=filters.percent_price_multiplier_up,
            percent_price_multiplier_down=filters.percent_price_multiplier_down,
            percent_price_multiplier_decimals=filters.percent_price_multiplier_decimals,
        ),
        filters.max_quantity,
        "MARK_PRICE",
        captured_at_utc=now,
        **dict(ctx.snapshot_live_inputs or {}),
    )
    alerts = RehearsalAlertSink(ctx)
    closer = MarketEmergencyCloser(
        adapter=cast(Any, ctx.guarded),
        journal=ctx.journal,
        safe_mode_controller=safe_mode,
        alert_sink=alerts,
        clock=ctx.clock,
    )
    coordinator = ProtectionCoordinator(
        adapter=cast(Any, ctx.guarded),
        intent_store=intent_store,
        journal=ctx.journal,
        safe_mode_controller=safe_mode,
        alert_sink=alerts,
        emergency_closer=closer,
        limits=limits,
        clock=ctx.clock,
    )
    margin = timedelta(milliseconds=max(drift.ahead_limit_ms, drift.behind_limit_ms))
    ctx.recorder.details["live_context"] = _jsonable(
        {
            "latest_closed_bar_close": bar_close,
            "gtd_clock_margin_ms": int(margin.total_seconds() * 1000),
            "tp1_quantity_fraction": TP1_QUANTITY_FRACTION,
            "working_type": snapshot.working_type,
            "plan_snapshot_status": snapshot.live_inputs_status.value,
        }
    )
    ctx.coordinator = coordinator
    return LivePlacementContext(
        signal=signal,
        plan_constraint_snapshot=snapshot,
        execution_limits=limits,
        protection_registry=coordinator,
        latest_closed_bar_close=bar_close,
        gtd_clock_margin=margin,
        tp1_quantity_fraction=TP1_QUANTITY_FRACTION,
        # 19-REVIEW CR-01: the manager reads this clock after the mark-price read; the local
        # clock's drift from Binance's is bounded by the drift guard and `margin`.
        clock=ctx.clock,
    )


# --------------------------------------------------------------------------- #
# Approvals and taps (SR-7, SR-11): APPROVED only ever comes from dispatch_callback.
# --------------------------------------------------------------------------- #


def _tap_deps(ctx: RunContext) -> TapHandlerDeps:
    book, clock = ctx.book, ctx.clock

    def dispatch(parsed: Any, **kwargs: Any) -> DispatchResult:
        return dispatch_callback(
            parsed,
            journal_receipt=book.journal_receipt,
            lookup_by_short_id=book.lookup_by_short_id,
            lookup_by_token_hash=book.lookup_by_token_hash,
            save_atomic=book.save_atomic,
            now_utc=clock(),
            **kwargs,
        )

    return TapHandlerDeps(
        authorized_chat_id=ctx.credentials.telegram_chat_id,
        binding_context_resolver=book.binding_context_resolver,
        dispatch=dispatch,
    )


@dataclass(frozen=True)
class IssuedApproval:
    approval: Approval
    raw_token: str
    signal_id: str


def issue_approval(
    ctx: RunContext, plan: DerivedPlan, *, role: str, action: ApprovalAction
) -> IssuedApproval:
    """Create one PENDING approval with a one-time token. Nothing here can approve."""
    signal_id = (
        plan.signal_id
        if role == "approve"
        else sha256_hex({"run_id": ctx.run_id, "role": f"signal:{role}"})
    )
    raw_token = ctx.token_factory()
    approval = Approval(
        approval_id="apv-" + sha256_hex({"run_id": ctx.run_id, "role": role})[:32],
        trade_plan_id=plan.trade_plan.trade_plan_id,
        signal_id=signal_id,
        action=action,
        result=ApprovalResult.PENDING,
        status=ApprovalResult.PENDING,
        approval_token_hash=token_hash_of(raw_token),
        requested_at_utc=plan.observed_at,
        request_hash=plan.trade_plan.plan_hash,
    )
    params = plan.parameter_set
    ctx.book.register(
        approval=approval,
        raw_token=raw_token,
        context={
            "plan_hash": plan.trade_plan.plan_hash,
            "strategy_version": params.strategy_version,
            "parameter_set_id": params.parameter_set_id,
            "parameter_set_hash": params.parameter_set_hash,
            "expiry_utc": plan.trade_plan.expiry_utc,
        },
    )
    return IssuedApproval(approval=approval, raw_token=raw_token, signal_id=signal_id)


def render_approval_text(ctx: RunContext, plan: DerivedPlan, *, title: str, signal_id: str) -> str:
    body = format_approve(
        symbol=SYMBOL,
        direction="LONG",
        setup="DEMO_REHEARSAL",
        entry_min=plan.trade_plan.entry_min_price,
        entry_max=plan.trade_plan.entry_max_price,
        stop_loss=plan.stop_loss,
        take_profits=[
            (plan.tp1_trigger, TP1_QUANTITY_FRACTION),
            (plan.tp2_trigger, Decimal("1") - TP1_QUANTITY_FRACTION),
        ],
        rr=plan.rr,
        risk_pct=plan.risk_rate,
        expiry_utc=plan.trade_plan.expiry_utc,
        invalidation="DEMO_REHEARSAL_ONLY",
        exposure_quote=Decimal("0"),
        reason_codes=["DEMO_ONLY", ctx.mode.value],
        signal_id=signal_id,
        detected_at_utc=plan.observed_at,
    )
    return f"{title} ({ctx.mode.value}, Binance Demo Trading)\n{body}"


async def issue_and_send(
    ctx: RunContext,
    plan: DerivedPlan,
    *,
    role: str,
    action: ApprovalAction,
    kind: str,
    chat_id: int,
    title: str,
    step_name: str,
) -> IssuedApproval:
    """Issue a PENDING approval and post its keyboard. A send failure aborts: no approval."""
    channel = _require_channel(ctx)
    issued = issue_approval(ctx, plan, role=role, action=action)
    try:
        await channel.send_approval(
            chat_id=chat_id,
            text=render_approval_text(ctx, plan, title=title, signal_id=issued.signal_id),
            signal_id=issued.signal_id,
            kind=kind,
        )
    except Exception as exc:  # noqa: BLE001 - recorded by type name only
        ctx.recorder.record_failure("telegram_send", exc)
        ctx.recorder.add_step(step_name, STEP_FAILED, f"send failed: {type(exc).__name__}")
        raise RehearsalAbort("the approval message could not be sent") from None
    return issued


def _reason(result: DispatchResult) -> str:
    return "NONE" if result.reason_code is None else result.reason_code.value


async def run_skip_rehearsal(ctx: RunContext, plan: DerivedPlan) -> None:
    channel = _require_channel(ctx)
    await issue_and_send(
        ctx,
        plan,
        role="skip",
        action=ApprovalAction.SKIP_USER,
        kind="SKIP",
        chat_id=ctx.credentials.telegram_chat_id,
        title="TAPS REHEARSAL: tap SKIP (no order will be placed)",
        step_name="skip_tap",
    )
    result = await channel.next_result(timeout_seconds=ctx.approval_timeout_seconds)
    if result is None:
        ctx.recorder.add_step("skip_tap", STEP_FAILED, "no tap before the timeout")
        raise RehearsalAbort("no SKIP tap before the timeout")
    approval = result.approval
    if result.ok and approval is not None and approval.status is ApprovalResult.SKIPPED:
        ctx.recorder.add_step(
            "skip_tap", STEP_PASSED, "SKIP resolved SKIPPED through dispatch_callback; no order"
        )
        return
    ctx.recorder.add_step("skip_tap", STEP_FAILED, f"tap not accepted: {_reason(result)}")
    raise RehearsalAbort("the SKIP tap was not accepted")


async def request_approve_tap(
    ctx: RunContext, plan: DerivedPlan, *, step_name: str, title: str
) -> IssuedApproval:
    """Post the APPROVE keyboard and wait for the real tap. Timeout or rejection aborts."""
    channel = _require_channel(ctx)
    issued = await issue_and_send(
        ctx,
        plan,
        role="approve",
        action=ApprovalAction.APPROVE,
        kind="APPROVE",
        chat_id=ctx.credentials.telegram_chat_id,
        title=title,
        step_name=step_name,
    )
    result = await channel.next_result(timeout_seconds=ctx.approval_timeout_seconds)
    if result is None:
        ctx.recorder.add_step(step_name, STEP_FAILED, "no tap before the timeout; no order")
        raise RehearsalAbort("no APPROVE tap before the timeout")
    approval = result.approval
    if not (result.ok and approval is not None and approval.status is ApprovalResult.APPROVED):
        ctx.recorder.add_step(step_name, STEP_FAILED, f"tap not accepted: {_reason(result)}")
        raise RehearsalAbort("the APPROVE tap was not accepted")
    ctx.recorder.add_step(
        step_name, STEP_PASSED, "APPROVE resolved APPROVED through dispatch_callback"
    )
    return IssuedApproval(approval=approval, raw_token=issued.raw_token, signal_id=issued.signal_id)


async def run_unknown_chat_rehearsal(ctx: RunContext, plan: DerivedPlan) -> bool:
    """Learn a second chat from /start, post both keyboards there, expect the gate to reject."""
    channel = _require_channel(ctx)
    other = await channel.discover_other_chat(timeout_seconds=ctx.discovery_timeout_seconds)
    if other is None:
        ctx.recorder.add_step(
            "unknown_chat_tap",
            STEP_NOT_REHEARSED,
            "no second chat sent /start before the discovery timeout; nothing fabricated",
        )
        return False
    approve = await issue_and_send(
        ctx,
        plan,
        role="unknown-approve",
        action=ApprovalAction.APPROVE,
        kind="APPROVE",
        chat_id=other,
        title="TAPS REHEARSAL, unknown-chat check: tap APPROVE (it must be rejected)",
        step_name="unknown_chat_tap",
    )
    skip = await issue_and_send(
        ctx,
        plan,
        role="unknown-skip",
        action=ApprovalAction.SKIP_USER,
        kind="SKIP",
        chat_id=other,
        title="TAPS REHEARSAL, unknown-chat check: tap SKIP (it must be rejected)",
        step_name="unknown_chat_tap",
    )
    before = {i.approval.approval_id: ctx.book.fingerprint(i.approval) for i in (approve, skip)}
    mark = len(ctx.journal.events)
    result = await channel.next_result(timeout_seconds=ctx.approval_timeout_seconds)
    if result is None:
        ctx.recorder.add_step(
            "unknown_chat_tap",
            STEP_NOT_REHEARSED,
            "no tap from the second chat before the timeout; nothing fabricated",
        )
        return False
    new_events = ctx.journal.events[mark:]
    received_rejected = any(
        e.event_type == "CALLBACK_RECEIVED"
        and json.loads(e.payload_json).get("chat_gate_rejected") is True
        for e in new_events
    )
    rejected = any(e.event_type == "CALLBACK_REJECTED" for e in new_events)
    unchanged = all(
        ctx.book.fingerprint(i.approval) == before[i.approval.approval_id] for i in (approve, skip)
    )
    ok = (
        result.ok is False
        and result.reason_code is not None
        and result.reason_code.value == "INVALIDATED"
        and received_rejected
        and rejected
        and unchanged
    )
    ctx.recorder.details["unknown_chat"] = {
        "chat_sha256_prefix": chat_fingerprint(other),
        "result_ok": result.ok,
        "reason_code": _reason(result),
        "callback_received_chat_gate_rejected": received_rejected,
        "callback_rejected": rejected,
        "approval_row_unchanged": unchanged,
    }
    ctx.recorder.add_step(
        "unknown_chat_tap",
        STEP_PASSED if ok else STEP_FAILED,
        "authorized_chat_gate rejected the tap, journaled it and left the approval rows untouched"
        if ok
        else "the unauthorized tap was not handled as required",
    )
    return True


# --------------------------------------------------------------------------- #
# Scenarios (SR-3, SR-5). Task 1 left the tracer in place as a CLI-less seam.
# --------------------------------------------------------------------------- #


def select_symbol(filters: Sequence[SymbolFilters]) -> SymbolFilters:
    """BTCUSDT must be a TRADING PERPETUAL; anything else fails closed."""
    for item in filters:
        if item.symbol == SYMBOL:
            if item.status != "TRADING" or item.contract_type != "PERPETUAL":
                raise RehearsalAbort(f"{SYMBOL} is not a TRADING PERPETUAL on Demo")
            return item
    raise RehearsalAbort(f"{SYMBOL} is absent from exchangeInfo on Demo")


async def run_tracer(ctx: RunContext) -> str:
    """Thinnest path through every layer: server time, exchangeInfo, constraints, evidence."""
    server_now = await ctx.guarded.server_time()
    ctx.recorder.details["exchange_server_time_utc"] = _jsonable(server_now)
    filters = select_symbol(await ctx.guarded.exchange_info())
    ctx.recorder.set_constraints(filters)
    ctx.recorder.add_step(
        "read_constraints",
        STEP_PASSED,
        "exchangeInfo constraints for BTCUSDT read from Binance Demo",
    )
    return OUTCOME_COMPLETE


def _instruct(ctx: RunContext, text: str) -> None:
    ctx.recorder.details.setdefault("operator_instructions", []).append(text)


async def run_taps(ctx: RunContext) -> str:
    """Health, SKIP rehearsal, APPROVE rehearsal and the unknown-chat check. No order, ever."""
    channel = _require_channel(ctx)
    await channel.open(_tap_deps(ctx))
    try:
        await _require_healthy(ctx)
        plan = await prepare_plan(ctx, "far")
        await run_skip_rehearsal(ctx, plan)
        await request_approve_tap(
            ctx,
            plan,
            step_name="approve_tap",
            title="TAPS REHEARSAL: tap APPROVE (no order will be placed)",
        )
        rehearsed = await run_unknown_chat_rehearsal(ctx, plan)
    finally:
        await channel.close()
    failed = any(s["status"] == STEP_FAILED for s in ctx.recorder.steps)
    if failed:
        return OUTCOME_FAILED
    return OUTCOME_COMPLETE if rehearsed else OUTCOME_COMPLETE_WITH_GAPS


async def _confirm_clean(ctx: RunContext) -> bool:
    guarded = ctx.guarded
    orders = await guarded.snapshot_open_normal_orders(symbol=SYMBOL)
    algos = await guarded.snapshot_open_algo_orders(symbol=SYMBOL)
    positions = await guarded.snapshot_positions(symbol=SYMBOL)
    clean = not (orders or algos or positions)
    ctx.recorder.add_step(
        "account_clean",
        STEP_PASSED if clean else STEP_FAILED,
        f"open orders {len(orders)}, open algo orders {len(algos)}, "
        f"open positions {len(positions)}",
    )
    return clean


async def _cancel_everything(
    ctx: RunContext, plan: DerivedPlan, *, entry: bool, protectives: bool = True
) -> bool:
    """Cancel the entry and/or every protective leg by deterministic id."""
    now = ctx.clock()
    plan_hash = plan.trade_plan.plan_hash
    ok = True
    if entry:
        try:
            await expire_pending_entry(
                plan_hash=plan_hash,
                symbol=SYMBOL,
                adapter=cast(Any, ctx.guarded),
                journal=ctx.journal,
                now_utc=now,
                trigger_reason="expiry_time",
            )
        except Exception:  # noqa: BLE001 - recorded through the guarded error log
            ok = False
    if protectives:
        try:
            await cancel_untriggered_protectives(
                plan_hash=plan_hash,
                symbol=SYMBOL,
                adapter=cast(Any, ctx.guarded),
                journal=ctx.journal,
                now_utc=now,
            )
        except ExceptionGroup:
            # TP1 and TP2 were never placed on an unfilled entry, so their cancels may fail.
            pass
    return ok


async def _entry_probe(ctx: RunContext, plan: DerivedPlan) -> OrderProbe:
    """Read back the entry and the open orders. No stop is read: none exists at entry time (D-10).

    The closePosition stop is placed after the first fill by the protection coordinator, which
    the fill scenario steps (plan 19-16), so a rehearsal that has only placed the entry has
    nothing protective to probe.
    """
    plan_hash = plan.trade_plan.plan_hash
    entry_probe = await ctx.guarded.query_order_by_client(
        symbol=SYMBOL,
        orig_client_order_id=derive_client_order_id(
            plan_hash=plan_hash, role=OrderRole.ENTRY.value
        ),
    )
    snaps_orders = await ctx.guarded.snapshot_open_normal_orders(symbol=SYMBOL)
    snaps_algos = await ctx.guarded.snapshot_open_algo_orders(symbol=SYMBOL)
    for snapshot in (*snaps_orders, *snaps_algos):
        ctx.recorder.record_exchange_record(snapshot)
    return entry_probe


async def _far_cleanup(ctx: RunContext, plan: DerivedPlan, entry_probe: OrderProbe) -> str:
    if not (entry_probe.found and entry_probe.status == "NEW"):
        ctx.recorder.add_step(
            "cleanup",
            STEP_FAILED,
            f"entry status is {entry_probe.status!r}, not NEW: nothing was cancelled",
        )
        _instruct(
            ctx,
            "The entry is no longer NEW: close the Demo position and cancel leftover orders "
            "in the Binance Demo UI.",
        )
        return OUTCOME_FAILED
    cancelled = await _cancel_everything(ctx, plan, entry=True, protectives=False)
    ctx.recorder.add_step(
        "cleanup",
        STEP_PASSED if cancelled else STEP_FAILED,
        "entry cancelled by deterministic id; no protective leg exists to cancel (D-10)",
    )
    clean = await _confirm_clean(ctx)
    if not (cancelled and clean):
        _instruct(ctx, "Check the Binance Demo UI and cancel any leftover order.")
        return OUTCOME_FAILED
    return OUTCOME_COMPLETE


_FINAL_PROTECTION_STATES = frozenset(
    {
        ProtectionState.COMPLETE,
        ProtectionState.TP_UNAVAILABLE,
        ProtectionState.FLAT,
        ProtectionState.CLOSE_FAILED,
        ProtectionState.ENTRY_ENDED_NO_FILL,
    }
)
_KNOWN_GAP_PREFIX = "plan snapshot is INCOMPLETE"


def _protection_view(ctx: RunContext, plan: DerivedPlan) -> PlanProtection | None:
    coordinator = ctx.coordinator
    if coordinator is None:
        return None
    return coordinator.protection_of(plan.trade_plan.plan_hash)


def _protection_transitions(ctx: RunContext, plan: DerivedPlan) -> list[dict[str, str]]:
    """The journaled protection transitions of this plan, in order (from, to, reason)."""
    plan_hash = plan.trade_plan.plan_hash
    transitions: list[dict[str, str]] = []
    for event in ctx.journal.events:
        if event.event_type != EVENT_PROTECTION_TRANSITION or event.entity_id != plan_hash:
            continue
        payload = json.loads(event.payload_json)
        transitions.append(
            {"from": payload["from"], "to": payload["to"], "reason": payload["reason"]}
        )
    return transitions


def _record_protection_flow(ctx: RunContext, plan: DerivedPlan) -> None:
    view = _protection_view(ctx, plan)
    ctx.recorder.details["protection_flow"] = {
        "final_state": None if view is None else view.state.value,
        "transitions": _protection_transitions(ctx, plan),
    }


async def _drive_protection(ctx: RunContext, plan: DerivedPlan) -> ProtectionState | None:
    """Step the coordinator (REST-only: no user-data stream) until the plan settles or the bound.

    Each iteration is one `coordinator.step()` followed by the injected sleep; the loop ends at
    COMPLETE, TP_UNAVAILABLE, FLAT, CLOSE_FAILED, ENTRY_ENDED_NO_FILL or after FILL_MAX_POLLS
    sleeps. The coordinator's own deadlines run on the context clock.
    """
    coordinator = ctx.coordinator
    if coordinator is None:
        raise RehearsalAbort("the protection coordinator was not built")
    state: ProtectionState | None = None
    for poll in range(FILL_MAX_POLLS + 1):
        await coordinator.step()
        view = coordinator.protection_of(plan.trade_plan.plan_hash)
        state = None if view is None else view.state
        if state in _FINAL_PROTECTION_STATES:
            break
        if poll < FILL_MAX_POLLS:
            await ctx.sleep(FILL_POLL_SECONDS)
    return state


async def _record_leg_echoes(ctx: RunContext, plan: DerivedPlan) -> None:
    """Record the open algo legs the exchange echoes back (stop, and TP1 and TP2 when placed)."""
    roles = {
        derive_algo_client_id(plan_hash=plan.trade_plan.plan_hash, role=role.value): role.value
        for role in (OrderRole.STOP_LOSS, OrderRole.TAKE_PROFIT_1, OrderRole.TAKE_PROFIT_2)
    }
    echoes: list[dict[str, Any]] = []
    for snapshot in await ctx.guarded.snapshot_open_algo_orders(symbol=SYMBOL):
        ctx.recorder.record_exchange_record(snapshot)
        echoes.append(
            _jsonable(
                {
                    "role": roles.get(snapshot.client_algo_id, "UNKNOWN"),
                    "client_algo_id": snapshot.client_algo_id,
                    "algo_id": snapshot.algo_id,
                    "order_type": snapshot.order_type,
                    "reduce_only": snapshot.reduce_only,
                    "close_position": snapshot.close_position,
                    "quantity": snapshot.quantity,
                    "trigger_price": snapshot.trigger_price,
                    "algo_status": snapshot.algo_status,
                }
            )
        )
    ctx.recorder.details["leg_echoes"] = echoes


def _tp_unavailable_reason(ctx: RunContext) -> str:
    """The reason of the last TP_UNAVAILABLE critical alert (fixed project text)."""
    alerts = ctx.recorder.details.get("critical_alerts", [])
    reasons = [a["reason"] for a in alerts if a.get("event") == ALERT_TP_UNAVAILABLE]
    return str(reasons[-1]) if reasons else "no reason was recorded"


async def _fill_flow(ctx: RunContext, plan: DerivedPlan, entry_probe: OrderProbe) -> str:
    """The fill scenario, driven end to end by the protection coordinator (plan 19-16).

    After `execute_approved_plan` handed the GTD entry to the coordinator, this loop only steps
    it: the coordinator detects the fill by REST, places the closePosition stop after it, confirms
    the stop by REST, ends the entry remainder, then places TP1 and TP2 from the real position
    (or goes TP_UNAVAILABLE). Every final state is recorded as a step with an honest status; a
    TP_UNAVAILABLE caused by the INCOMPLETE plan snapshot is a known gap, never a pass.
    """
    if ctx.mode is RunMode.DRY_RUN:
        ctx.recorder.add_step(
            "fill_wait", STEP_SKIPPED_DRY_RUN, "a dry run never fills; the entry is only simulated"
        )
        ctx.recorder.add_step(
            "attach_protectives", STEP_NOT_REHEARSED, "dry run: no fill, nothing to attach"
        )
        outcome = await _far_cleanup(ctx, plan, entry_probe)
        return OUTCOME_COMPLETE_WITH_GAPS if outcome == OUTCOME_COMPLETE else outcome

    recorder = ctx.recorder
    state = await _drive_protection(ctx, plan)
    cancelled = True
    if state is ProtectionState.AWAITING_FILL:
        # No fill within the bound: end the entry, then let the coordinator observe the end (or a
        # fill that raced the cancel).
        cancelled = await _cancel_everything(ctx, plan, entry=True, protectives=False)
        state = await _drive_protection(ctx, plan)
    view = _protection_view(ctx, plan)
    _record_protection_flow(ctx, plan)
    filled = view is not None and view.first_fill_at_utc is not None
    transitions = " -> ".join(t["to"] for t in _protection_transitions(ctx, plan))
    recorder.add_step(
        "fill_wait",
        STEP_PASSED if filled else STEP_NOT_REHEARSED,
        f"protection path {transitions or 'none'}; final state "
        f"{'none' if state is None else state.value}",
    )

    if not filled:
        recorder.add_step(
            "protection_stop", STEP_NOT_REHEARSED, "the entry never filled; no stop was placed"
        )
        recorder.add_step(
            "attach_protectives", STEP_NOT_REHEARSED, "the entry never filled; nothing to attach"
        )
        if state is not ProtectionState.ENTRY_ENDED_NO_FILL:
            # The plan is neither filled nor observed as ended: do not claim a clean account.
            _instruct(
                ctx,
                "The entry state is unknown: check the Binance Demo UI for a position and any "
                "open order, and close them by hand.",
            )
            return OUTCOME_FAILED
        clean = await _confirm_clean(ctx)
        return OUTCOME_COMPLETE_WITH_GAPS if (cancelled and clean) else OUTCOME_FAILED

    stop_confirmed = view is not None and view.stop_confirmed_at_utc is not None
    recorder.add_step(
        "protection_stop",
        STEP_PASSED if stop_confirmed else STEP_FAILED,
        "stop placed after the first fill and confirmed ACTIVE by REST"
        if stop_confirmed
        else "the stop was not confirmed by REST",
    )
    await _record_leg_echoes(ctx, plan)
    closed_by_emergency = any(
        t["to"] == ProtectionState.CLOSE_REQUIRED.value for t in _protection_transitions(ctx, plan)
    )
    if state is ProtectionState.COMPLETE:
        recorder.add_step(
            "attach_protectives",
            STEP_PASSED,
            f"SL, TP1 (fraction {TP1_QUANTITY_FRACTION}) and TP2 confirmed by REST",
        )
        _instruct(
            ctx,
            "Protective legs are left in place; close the Demo position and cancel leftover "
            "orders in the Binance Demo UI.",
        )
        return OUTCOME_COMPLETE
    if state is ProtectionState.TP_UNAVAILABLE:
        reason = _tp_unavailable_reason(ctx)
        _instruct(
            ctx,
            "The stop is in place but no take profit is: close the Demo position and cancel "
            "leftover orders in the Binance Demo UI.",
        )
        if reason.startswith(_KNOWN_GAP_PREFIX):
            recorder.add_step(
                "attach_protectives",
                STEP_NOT_REHEARSED,
                f"known gap: {reason} (margin type, leverage and equity stay unknown until "
                "Phases 21-22); the stop is kept and TP1 and TP2 were not placed",
            )
            return OUTCOME_COMPLETE_WITH_GAPS
        recorder.add_step("attach_protectives", STEP_FAILED, f"TP_UNAVAILABLE: {reason}")
        return OUTCOME_FAILED
    if state is ProtectionState.FLAT and not closed_by_emergency:
        recorder.add_step(
            "attach_protectives",
            STEP_NOT_REHEARSED,
            "the position was already flat when the take profits were due",
        )
        _instruct(ctx, "Check the Binance Demo UI for leftover orders.")
        return OUTCOME_COMPLETE_WITH_GAPS
    detail = (
        "the position was closed by the emergency market close"
        if state is ProtectionState.FLAT
        else f"protection ended in {'none' if state is None else state.value}"
    )
    recorder.add_step("attach_protectives", STEP_NOT_REHEARSED, detail)
    recorder.add_step("protection_outcome", STEP_FAILED, detail)
    if state is not ProtectionState.FLAT:
        _instruct(
            ctx, "A position exists without confirmed protection: close it NOW in the Demo UI."
        )
    else:
        _instruct(ctx, "Check the Binance Demo UI: the position was closed by market.")
    return OUTCOME_FAILED


async def run_order_scenario(ctx: RunContext, kind: str) -> str:
    """far or fill: health, plan, real tap, re-check, enable in-process, place via the manager."""
    channel = _require_channel(ctx)
    guarded = ctx.guarded
    recorder = ctx.recorder
    # Plan 19-13 (D-07, D-13, T-19-34): unset execution limits end the run here, before the
    # channel opens, before any approval is requested and before any exchange mutation.
    require_execution_limits_set(ctx)
    await channel.open(_tap_deps(ctx))
    try:
        verdict = await _require_healthy(ctx)
        plan = await prepare_plan(ctx, kind)
        issued = await request_approve_tap(
            ctx,
            plan,
            step_name="approval_tap",
            title=f"DEMO {kind.upper()} REHEARSAL: tap APPROVE to place the Demo orders",
        )
        now = await guarded.server_time()
        filters = select_symbol(await guarded.exchange_info())
        drift = [
            name
            for name, value in constraint_values(filters).items()
            if value != constraint_values_of_plan(plan)[name]
        ]
        if drift:
            recorder.add_step(
                "constraint_recheck", STEP_FAILED, f"constraints changed: {', '.join(drift)}"
            )
            raise RehearsalAbort("exchange constraints changed after the plan was derived")
        recorder.add_step("constraint_recheck", STEP_PASSED, "tick, step, minimums unchanged")
        commission = await guarded.user_commission_rate(SYMBOL)
        rates = resolve_rates(
            parameter_set=plan.parameter_set, commission=commission, observed_at=now
        )
        constraints = ConstraintSnapshot(
            symbol=SYMBOL,
            price_tick_size=filters.price_tick_size,
            quantity_step_size=filters.quantity_step_size,
            min_quantity=filters.min_quantity,
            min_notional=filters.min_notional,
            metadata_observed_at_utc=now,
        )
        approved_plan = dataclasses.replace(plan.trade_plan, status=TradePlanStatus.APPROVED)
        params = plan.parameter_set
        callback = Callback(
            raw_token=issued.raw_token,
            chat_id=ctx.credentials.telegram_chat_id,
            plan_hash=plan.trade_plan.plan_hash,
            strategy_version=params.strategy_version,
            parameter_set_id=params.parameter_set_id,
            parameter_set_hash=params.parameter_set_hash,
            callback_at_utc=now,
            action=ApprovalAction.APPROVE,
        )
        controller = LiveEnablementController(journal=ctx.journal)
        ctx.controller = controller
        enablement: dict[str, Any] = {
            "operator_id": OPERATOR_ID,
            "enabled_in_run": False,
            "disabled_after_run": False,
        }
        recorder.details["enablement"] = enablement
        try:
            controller.enable(
                operator_id=OPERATOR_ID,
                now_utc=now,
                health_verdict=verdict,
                kill_gate_state=KillGateState.WITHIN_BUDGET,
            )
            enablement["enabled_in_run"] = True
            safe_mode = SafeModeController(adapter=guarded, journal=ctx.journal)
            from tests.support.intent_store_fakes import InMemoryExecutionIntentStore

            intent_store = InMemoryExecutionIntentStore()
            live_context = await build_live_context(
                ctx,
                plan,
                filters,
                constraints,
                now,
                safe_mode=safe_mode,
                intent_store=intent_store,
            )
            open_algos = await guarded.snapshot_open_algo_orders()
            outcome = await execute_approved_plan(
                callback=callback,
                approval=issued.approval,
                authorized_chat_id=ctx.credentials.telegram_chat_id,
                expiry_utc=plan.trade_plan.expiry_utc,
                approval_strategy_version=params.strategy_version,
                approval_parameter_set_id=params.parameter_set_id,
                approval_parameter_set_hash=params.parameter_set_hash,
                now_utc=now,
                adapter=cast(Any, guarded),
                risk_kwargs=build_risk_kwargs(
                    plan,
                    trade_plan=approved_plan,
                    constraints=constraints,
                    cost_rates=rates,
                    now_utc=now,
                ),
                safe_mode_controller=safe_mode,
                journal=ctx.journal,
                enablement=controller,
                gate_kwargs={
                    "open_algo_count": len(open_algos),
                    "planned_leg_count": 3,
                    "positions_reconciled": _probe_passed(verdict, "reconciliation_drift"),
                },
                intent_store=intent_store,
                live_context=live_context,
            )
            result = await _after_placement(ctx, plan, kind, outcome)
        finally:
            if not controller.is_disabled:
                controller.disable(operator_id=OPERATOR_ID, now_utc=ctx.clock())
            enablement["disabled_after_run"] = controller.is_disabled
    finally:
        await channel.close()
    return result


def _probe_passed(verdict: HealthVerdict, name: str) -> bool:
    return any(r.check_name == name and r.status == "PASS" for r in verdict.results)


def constraint_values_of_plan(plan: DerivedPlan) -> dict[str, Decimal]:
    snapshot = plan.constraints
    return {
        "price_tick_size": snapshot.price_tick_size,
        "quantity_step_size": snapshot.quantity_step_size,
        "min_quantity": snapshot.min_quantity,
        "min_notional": snapshot.min_notional,
    }


async def _after_placement(ctx: RunContext, plan: DerivedPlan, kind: str, outcome: Any) -> str:
    recorder = ctx.recorder
    guarded = ctx.guarded
    if outcome.is_no_trade:
        recorder.add_step(
            "place_entry", STEP_FAILED, f"execute_approved_plan: {outcome.reason_code}"
        )
        if guarded.mutating_attempts == 0:
            raise RehearsalAbort(f"no order was attempted: {outcome.reason_code}")
        await _cancel_everything(ctx, plan, entry=True, protectives=False)
        _instruct(ctx, "Check the Binance Demo UI for any leftover order or position.")
        return OUTCOME_FAILED
    if ctx.mode is RunMode.DRY_RUN:
        recorder.add_step(
            "place_entry",
            STEP_SKIPPED_DRY_RUN,
            f"simulated only, {len(recorder.planned_requests)} planned request(s), no order sent",
        )
    else:
        recorder.add_step(
            "place_entry",
            STEP_PASSED,
            "entry LIMIT (GTD) placed through the manager; the stop follows the first fill (D-10)",
        )
    entry_probe = await _entry_probe(ctx, plan)
    recorder.add_step(
        "readback",
        STEP_PASSED,
        f"entry status {entry_probe.status!r}; no stop at entry time (D-10)"
        + (" (simulated)" if ctx.mode is RunMode.DRY_RUN else ""),
    )
    if kind == "far":
        return await _far_cleanup(ctx, plan, entry_probe)
    return await _fill_flow(ctx, plan, entry_probe)


async def run_rehearsal(ctx: RunContext) -> str:
    """Dispatch one scenario. Raises RehearsalAbort for a fail-closed stop."""
    if ctx.scenario == "taps":
        return await run_taps(ctx)
    if ctx.scenario in ("far", "fill"):
        return await run_order_scenario(ctx, ctx.scenario)
    raise UsageError(f"unknown scenario {ctx.scenario!r}")


# --------------------------------------------------------------------------- #
# Attestation map (09-04 task 3): derived only from recorded step outcomes.
# --------------------------------------------------------------------------- #


def _step_status(recorder: EvidenceRecorder, name: str) -> str | None:
    matches = [s["status"] for s in recorder.steps if s["name"] == name]
    return matches[-1] if matches else None


def build_attestation_map(recorder: EvidenceRecorder) -> dict[str, Any]:
    echoes = recorder.details.get("leg_echoes", [])
    roles = {e.get("role") for e in echoes}
    all_legs = {"STOP_LOSS", "TAKE_PROFIT_1", "TAKE_PROFIT_2"} <= roles
    attached = _step_status(recorder, "attach_protectives") == STEP_PASSED
    tp1 = next((e for e in echoes if e.get("role") == "TAKE_PROFIT_1"), None)
    tp2 = next((e for e in echoes if e.get("role") == "TAKE_PROFIT_2"), None)
    tp_echoed = (
        tp1 is not None
        and tp2 is not None
        and tp1["reduce_only"] is True
        and tp1["close_position"] is False
        and tp2["close_position"] is True
    )
    item1_ok = recorder.scenario == "fill" and attached and all_legs
    health = recorder.details.get("health", [])
    degraded = [h["check_name"] for h in health if h["status"] == STATUS_DEGRADED]
    failed = [h["check_name"] for h in health if h["status"] == STATUS_FAIL]
    taps = {name: _step_status(recorder, name) for name in _TAP_STEPS}
    approve_status = taps["approve_tap"] or _step_status(recorder, "approval_tap")
    item5 = [taps["skip_tap"], taps["unknown_chat_tap"], approve_status]
    if all(s == STEP_PASSED for s in item5):
        item5_status = "OBSERVED"
    elif any(s == STEP_PASSED for s in item5):
        item5_status = "PARTIALLY_OBSERVED"
    else:
        item5_status = "NOT_OBSERVED"
    if not health:
        item6_status, item6_detail = "NOT_OBSERVED", "no health preflight result was recorded"
    elif failed:
        item6_status, item6_detail = "FAILED", f"probes FAILED: {', '.join(failed)}"
    else:
        item6_status = "OBSERVED_WITH_DEGRADED" if degraded else "OBSERVED"
        item6_detail = (
            f"{len(health) - len(degraded)} PASS and {len(degraded)} DEGRADED; DEGRADED probes "
            f"(not evaluated by a REST-only rehearsal): {', '.join(degraded) or 'none'}"
        )
    return {
        "1": {
            "title": "smallest LIMIT plus SL, TP1, TP2 round trip on Demo",
            "status": "OBSERVED" if item1_ok else "NOT_OBSERVED",
            "detail": "fill scenario confirmed SL, TP1 and TP2"
            if item1_ok
            else "the fill scenario did not confirm all three legs in this run",
        },
        "2": {
            "title": "TP1 partial then TP2 close-all semantics",
            "status": "OBSERVED_ACCEPTANCE_ONLY" if tp_echoed else "NOT_OBSERVED",
            "detail": "TP1 reduce-only and TP2 close-all were accepted and echoed; trigger-time "
            "behaviour is not forced by this runner"
            if tp_echoed
            else "no TP1 and TP2 echoes were recorded; trigger-time behaviour is never forced",
        },
        "3": {
            "title": "ALGO_UPDATE.o.rm rejection parsing",
            "status": "NOT_OBSERVED",
            "detail": "needs a user-data stream, which arrives with Phase 18",
        },
        "4": {
            "title": "live credential provisioning (no withdrawal, IP allowlist, storage)",
            "status": "HUMAN_ONLY",
            "detail": "no runner can attest this; the operator confirms it by hand",
        },
        "5": {
            "title": "Telegram approval taps",
            "status": item5_status,
            "detail": f"skip_tap={taps['skip_tap']}, approve={approve_status}, "
            f"unknown_chat_tap={taps['unknown_chat_tap']}",
        },
        "6": {
            "title": "ten health probes",
            "status": item6_status,
            "detail": item6_detail,
        },
    }


# --------------------------------------------------------------------------- #
# Entry point.
# --------------------------------------------------------------------------- #


def _outcome_exit_code(outcome: str) -> int:
    if outcome in (OUTCOME_COMPLETE, OUTCOME_COMPLETE_WITH_GAPS):
        return EXIT_OK
    if outcome == OUTCOME_ABORTED:
        return EXIT_ABORTED
    return EXIT_FAILED


async def _default_sleep(seconds: int) -> None:
    await asyncio.sleep(seconds)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    adapter_factory: Callable[[RehearsalCredentials], AdapterBundle] | None = None,
    clock: Callable[[], datetime] | None = None,
    is_tty: Callable[[], bool] | None = None,
    read_confirmation: Callable[[str], str] | None = None,
    evidence_dir: Path | None = None,
    channel_factory: Callable[[RehearsalCredentials], ApprovalChannel] | None = None,
    sleep: Callable[[int], Awaitable[None]] | None = None,
    token_factory: Callable[[], str] | None = None,
    scenario_runner: Callable[[RunContext], Awaitable[str]] | None = None,
    execution_limits: ExecutionLimits | None = None,
    snapshot_live_inputs: Mapping[str, Any] | None = None,
) -> int:
    """Single entry point. Every seam defaults to the real implementation."""
    env: Mapping[str, str] = os.environ if environ is None else environ
    now: Callable[[], datetime] = clock if clock is not None else (lambda: datetime.now(UTC))
    try:
        args = _build_parser().parse_args(argv)
        mode = RunMode.EXECUTE if args.execute else RunMode.DRY_RUN
        if mode is RunMode.EXECUTE:
            if args.scenario == "taps":
                raise UsageError("--execute is not valid with the taps scenario (no order)")
            _confirm_execute(
                args.scenario,
                is_tty if is_tty is not None else sys.stdin.isatty,
                read_confirmation if read_confirmation is not None else input,
            )
        credentials = load_credentials(env)
        signed_call_policy = load_signed_call_policy(args.limits_file)
        drift_limits = load_drift_limits(args.limits_file)
    except (UsageError, ConfirmationRefused, CredentialError, LimitsFileRefused) as exc:
        print(f"refused ({type(exc).__name__}): {exc}", file=sys.stderr)
        return EXIT_REFUSED

    target_dir = evidence_dir if evidence_dir is not None else args.evidence_dir
    if target_dir is None:
        target_dir = DEFAULT_EVIDENCE_DIR
    recorder = EvidenceRecorder(
        mode=mode,
        scenario=args.scenario,
        symbol=SYMBOL,
        base_url=DEMO_BASE_URL,
        environ=env,
        clock=now,
    )
    factory: Callable[[RehearsalCredentials], AdapterBundle]
    if adapter_factory is not None:
        factory = adapter_factory
    else:

        def factory(creds: RehearsalCredentials) -> AdapterBundle:
            return default_adapter_factory(creds, signed_call_policy=signed_call_policy, clock=now)

    make_channel = channel_factory if channel_factory is not None else default_channel_factory
    runner = scenario_runner if scenario_runner is not None else run_rehearsal
    guarded: GuardedAdapter | None = None
    ctx: RunContext | None = None
    outcome: str
    try:
        bundle = factory(credentials)
        guarded = GuardedAdapter(
            bundle.inner, guard=bundle.guard, mode=mode, clock=now, recorder=recorder
        )
        ctx = build_context(
            guarded=guarded,
            recorder=recorder,
            channel=make_channel(credentials),
            credentials=credentials,
            scenario=args.scenario,
            mode=mode,
            clock=now,
            sleep=sleep if sleep is not None else _default_sleep,
            approval_timeout_seconds=args.approval_timeout_seconds,
            discovery_timeout_seconds=args.discovery_timeout_seconds,
            token_factory=token_factory if token_factory is not None else issue_one_time_token,
            execution_limits=execution_limits,
            drift_limits=drift_limits,
            snapshot_live_inputs=snapshot_live_inputs,
        )
        run_ctx = ctx

        async def run_scenario() -> str:
            return await runner(run_ctx)

        outcome = asyncio.run(run_scenario())
    except (DemoHostViolation, RehearsalAbort) as exc:
        recorder.record_failure("run", exc)
        # Both exception types carry fixed, operator-readable reasons (never request data).
        recorder.add_step(
            "run", STEP_FAILED, f"aborted before any order: {type(exc).__name__}: {exc}"
        )
        print(f"ABORTED before any order: {exc}", file=sys.stderr)
        outcome = OUTCOME_ABORTED
    except Exception as exc:  # noqa: BLE001 - recorded by type name, never by message
        recorder.record_failure("run", exc)
        recorder.add_step("run", STEP_FAILED, f"run failed: {type(exc).__name__}")
        outcome = OUTCOME_FAILED
    if guarded is not None:
        for method, exc_type, detail in guarded.error_log:
            recorder.record_failure_name(method, exc_type, detail)
    if ctx is not None:
        recorder.details["journal_event_counts"] = ctx.journal.counts()
        recorder.details["run_id"] = ctx.run_id
    recorder.attestation_map = build_attestation_map(recorder)
    recorder.outcome = outcome
    path = recorder.write(target_dir)
    print(f"evidence: {path}")
    for line in recorder.details.get("operator_instructions", []):
        print(f"OPERATOR: {line}")
    return _outcome_exit_code(outcome)


if __name__ == "__main__":
    sys.exit(main())
