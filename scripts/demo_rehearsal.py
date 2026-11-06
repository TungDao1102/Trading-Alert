"""Binance Demo Trading smoke and rehearsal runner (plan 24-29, D-33; closes the 09-04 rehearsal).

Run from the repository root, only as the owner::

    uv run python -m scripts.demo_rehearsal                       # dry run: fakes, SYNTHETIC
    uv run python -m scripts.demo_rehearsal --execute             # the Demo smoke (typed phrase)
    uv run python -m scripts.demo_rehearsal --scenario taps       # approval taps only, no order

Scenario ``smoke`` (the default) is criterion 2 of Phase 24 over the COMPOSED live process:
``build_wiring`` constructs the process (with an SDK factory that re-checks the Demo host),
``run_start_sequence`` starts it, and this script only observes it. Nothing here steps the
protection coordinator or places an order by hand. The sequence: the Demo injector queues a
signal (the ``/demo_signal`` handler of the process); the owner taps APPROVE and CONFIRM on the
live Demo bot (bounded waits); one GTD LIMIT entry with no entry-time stop (D079); the fill is seen
on the user-data stream; the stop is placed and REST-confirmed; TP1 and TP2; reconcile clean; a
restart and rehydrate (a second wiring over the same stores); replayed presses place nothing; close
and clean-up; last, the SAFE_MODE drill (enter, a CONFIRM refused, operator exit through
/safemode_exit). The drill is last because a second request on the symbol is refused while a
position, a plan or an approval is open and a refused CONFIRM leaves its reservation counted.

Without ``--execute`` the same sequence runs against the Binance-semantics fake with fake presses
(tests/support/live_smoke_env.py); every step of such a run is labelled SYNTHETIC and none is
Demo-observed. With ``--execute`` the environment is the live process's own: LIVE_RUNTIME_MODE=DEMO,
BINANCE_DEMO_API_KEY and BINANCE_DEMO_API_SECRET, TELEGRAM_LIVE_BOT_TOKEN,
TELEGRAM_LIVE_AUTHORIZED_CHAT_ID, TELEGRAM_AUTHORIZED_USER_IDS and DATABASE_URL (the Demo database,
migrated with ``alembic upgrade head``). LIVE credentials, a LIVE mode and the shadow bot's token
refuse the run before any network call. Stop the live service first: one process per bot token.

Safety posture:

* ``--execute`` needs an interactive terminal AND the exactly typed phrase ``DEMO SMOKE BTCUSDT``;
  anything else exits 2 before any network call. The assistant that built this tool never ran it.
* The only host is the SDK constant for Demo Trading; there is no host, base-url or symbol option.
* Evidence carries exchange-returned ids only, never a secret, and is scrubbed before and re-checked
  after the write. The user-data listen key is replaced by a fixed marker.

Scenario ``taps`` (no order) keeps the REST-only health preflight and the SKIP, APPROVE and
unknown-chat taps on the five Phase 23 variables (BINANCE_DEMO_*, TELEGRAM_BOT_TOKEN,
TELEGRAM_AUTHORIZED_CHAT_ID, TELEGRAM_AUTHORIZED_USER_IDS).

Exit codes::

    0  the run completed
    1  the run failed part-way (evidence written, exception type name only)
    2  refused before any network call (usage, credentials, --execute gate)
    3  aborted before any order (host violation, failed health probe, fail-closed constraint)

Evidence files: the smoke writes under ``.planning/phases/24-live-runtime-composition-demo/
evidence/`` and the taps scenario under ``.planning/phases/09-live-execution-rollout/``
(``--evidence-dir`` to change): ``09-DEMO-REHEARSAL-DRYRUN-*.json`` for a dry run,
``09-DEMO-REHEARSAL-EVIDENCE-*.json`` for an executed run.
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
from typing import Any, NoReturn, Protocol, TypeVar

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
from src.adapters.binance_public import LastPriceReading, MarkPriceReading  # noqa: E402
from src.adapters.binance_ratelimit_gate import RestRateLimitGate  # noqa: E402
from src.adapters.binance_usdm import (  # noqa: E402
    AccountBalanceRow,
    AccountConfigSnapshot,
    AccountInformationSnapshot,
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
    SymbolConfigSnapshot,
    SymbolFilters,
    SymbolLeverageBrackets,
)
from src.adapters.telegram_callbacks import (  # noqa: E402
    DispatchResult,
    build_application,
    dispatch_callback,
)
from src.adapters.telegram_notify import (  # noqa: E402
    build_decision_keyboard,
    format_approve,
)
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
    ExecutionIntentStatus,
    OrderRole,
    QuantizationDecision,
    RejectionReason,
    TradePlanStatus,
)
from src.domain.ids import derive_child_id  # noqa: E402
from src.domain.journal import JournalEvent, content_hash_event_id  # noqa: E402
from src.domain.lot_filters import LotFilters  # noqa: E402
from src.domain.registry import ParameterSet, load_parameter_set  # noqa: E402
from src.domain.trade_plan import TradePlan  # noqa: E402
from src.execution.manager import (  # noqa: E402
    LIVE5_SYMBOLS,
)
from src.execution.order_ids import derive_algo_client_id, derive_client_order_id  # noqa: E402
from src.execution.placement import (  # noqa: E402
    PRICE_ROUND_DOWN,
    PRICE_ROUND_UP,
    quantize_price,
)
from src.execution.protection import (  # noqa: E402
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
    HealthRuntimeMode,
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
from src.paper.runtime_config import parse_authorized_user_ids  # noqa: E402
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
ENV_TELEGRAM_USERS = "TELEGRAM_AUTHORIZED_USER_IDS"

EVIDENCE_SCHEMA = "demo-rehearsal-evidence/schema-1"
DEFAULT_EVIDENCE_DIR = REPO_ROOT / ".planning" / "phases" / "09-live-execution-rollout"
SMOKE_EVIDENCE_DIR = (
    REPO_ROOT / ".planning" / "phases" / "24-live-runtime-composition-demo" / "evidence"
)
# Plan 18-13: the ratified limits file (plan 18-09). Its signed-call policy gives every
# signed request an explicit recvWindow; no number is chosen here.
DEFAULT_LIMITS_FILE = REPO_ROOT / "config" / "binance" / "binance-limits-v1.toml"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2
EXIT_ABORTED = 3

OUTCOME_COMPLETE = "COMPLETE"
OUTCOME_COMPLETE_WITH_GAPS = "COMPLETE_WITH_GAPS"
OUTCOME_ABORTED = "ABORTED_NO_ORDER"
OUTCOME_FAILED = "FAILED"

SCENARIO_SMOKE = "smoke"
SCENARIOS = (SCENARIO_SMOKE, "taps")
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
# 19-REVIEW CR-02: the entry zone reaches this far past the derive-time mark on the near side,
# so the live mark read at gate 5e (after the approval tap) can still sit inside the zone.
# A rehearsal value, not a strategy parameter; the production zone check (adverse side only,
# 19-REVIEW WR-06) is not loosened for the rehearsal.
MARK_ZONE_CUSHION_RATE = Decimal("0.005")
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
# Credentials (SR-1): the five named environment variables only.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, repr=False)
class RehearsalCredentials:
    """The five credentials. Secret fields never appear in repr, str or logs."""

    binance_api_key: str = field(repr=False)
    binance_api_secret: str = field(repr=False)
    telegram_bot_token: str = field(repr=False)
    telegram_chat_id: int = field(repr=False)
    telegram_user_ids: frozenset[int] = field(repr=False)

    def __repr__(self) -> str:
        return "RehearsalCredentials(<masked>)"

    __str__ = __repr__


def load_credentials(environ: Mapping[str, str]) -> RehearsalCredentials:
    """Read exactly the five named variables from ``environ``. Errors name the variable only."""

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
    raw_users = need(ENV_TELEGRAM_USERS)
    try:
        user_ids = parse_authorized_user_ids(raw_users)
    except ValueError:
        raise CredentialError(
            f"environment variable {ENV_TELEGRAM_USERS} is not a comma-separated list of "
            "positive integers"
        ) from None
    return RehearsalCredentials(
        binance_api_key=key,
        binance_api_secret=secret,
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        telegram_user_ids=user_ids,
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

    def record_ids(
        self,
        step: str,
        *,
        order_ids: Sequence[str] = (),
        client_order_ids: Sequence[str] = (),
        algo_client_ids: Sequence[str] = (),
    ) -> None:
        """Per step: the exchange order ids and the deterministic client ids (D-33; no secret)."""
        self.details.setdefault("order_ids", []).append(
            {
                "step": step,
                "demo_order_ids": list(order_ids),
                "client_order_ids": list(client_order_ids),
                "algo_client_ids": list(algo_client_ids),
            }
        )

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

    async def get_last_price(self, *, symbol: str) -> LastPriceReading:
        """The last traded price of `symbol` (quick task 261020-l4p, gate 5e); a read, allowed in
        DRY_RUN."""
        return await self._call("get_last_price", lambda: self._inner.get_last_price(symbol=symbol))

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

    # ----- Phase 22 margin guard reads (22-REVIEW WR-08) --------------------- #
    # A MarginGuard must be built over THIS adapter (`margin_guard_factory`), never over the raw
    # inner one, so every read and both configuration POSTs pass the host guard, the error log
    # and the evidence record below.

    async def account_config_snapshot(self) -> AccountConfigSnapshot:
        return await self._call(
            "account_config_snapshot", lambda: self._inner.account_config_snapshot()
        )

    async def account_information_snapshot(self) -> AccountInformationSnapshot:
        return await self._call(
            "account_information_snapshot", lambda: self._inner.account_information_snapshot()
        )

    async def account_balances_snapshot(self) -> tuple[AccountBalanceRow, ...]:
        return await self._call(
            "account_balances_snapshot", lambda: self._inner.account_balances_snapshot()
        )

    async def symbol_config_snapshot(self, *, symbol: str) -> SymbolConfigSnapshot:
        return await self._call(
            "symbol_config_snapshot", lambda: self._inner.symbol_config_snapshot(symbol=symbol)
        )

    async def leverage_brackets_snapshot(self, *, symbol: str) -> SymbolLeverageBrackets:
        return await self._call(
            "leverage_brackets_snapshot",
            lambda: self._inner.leverage_brackets_snapshot(symbol=symbol),
        )

    # ----- mutating methods (blocked in DRY_RUN) ------------------------------ #

    async def change_margin_type(self, *, symbol: str, margin_type: str) -> None:
        """The margin-type POST: counted, only PLANNED in DRY_RUN (nothing reaches the host)."""
        self.mutating_attempts += 1
        if self._mode is RunMode.DRY_RUN:
            self._recorder.record_planned_request(
                "change_margin_type", {"symbol": symbol, "margin_type": margin_type}
            )
            return
        await self._call(
            "change_margin_type",
            lambda: self._inner.change_margin_type(symbol=symbol, margin_type=margin_type),
        )

    async def change_initial_leverage(self, *, symbol: str, leverage: int) -> None:
        """The leverage POST: counted, only PLANNED in DRY_RUN (nothing reaches the host)."""
        self.mutating_attempts += 1
        if self._mode is RunMode.DRY_RUN:
            self._recorder.record_planned_request(
                "change_initial_leverage", {"symbol": symbol, "leverage": leverage}
            )
            return
        await self._call(
            "change_initial_leverage",
            lambda: self._inner.change_initial_leverage(symbol=symbol, leverage=leverage),
        )

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
    parser.add_argument("--scenario", choices=SCENARIOS, default=SCENARIO_SMOKE)
    parser.add_argument(
        "--initialize-gate-state",
        action="store_true",
        help="first install of the smoke host only: create the REST gate state file (smoke)",
    )
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
            authorized_user_ids=self._credentials.telegram_user_ids,
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
        # Phase 23 (D-05): ONE message carries APPROVE and SKIP for every step kind. `kind` only
        # names the button the operator is asked to tap in the text; the other button of a
        # single-row step is refused by the replay layer (action mismatch), fail closed.
        del kind
        markup = build_decision_keyboard(signal_id)
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
    # D056 (2): the taps scenario is the explicit Demo/Rehearsal mode; its three DEGRADED probes
    # (no WebSocket, no user-data stream, no database) are recorded verbatim, never hidden.
    verdict = run_health_checks(
        results=ordered, mode=HealthRuntimeMode.DEMO, demo_degraded_allowed=True
    )
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
                "entry_min_price": self.trade_plan.entry_min_price,
                "entry_max_price": self.trade_plan.entry_max_price,
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
    # 19-REVIEW CR-02: gate 5e refuses a LONG whose live mark is below entry_min (the adverse
    # side only, 19-REVIEW WR-06), so a one-price zone at the `fill` entry (above the mark) could
    # never place. The zone contains the mark for both scenarios and reaches past it by the
    # cushion on the near side and is mirrored on the far side, so its mid (the price the manager
    # places at) is still exactly `entry`. Both edges are on the tick grid.
    if scenario == "fill":
        entry_min = quantize_price(
            price=mark_price * (Decimal("1") - MARK_ZONE_CUSHION_RATE),
            price_tick_size=tick,
            direction=PRICE_ROUND_DOWN,
        )
        entry_max = entry + (entry - entry_min)
    else:
        entry_max = quantize_price(
            price=mark_price * (Decimal("1") + MARK_ZONE_CUSHION_RATE),
            price_tick_size=tick,
            direction=PRICE_ROUND_UP,
        )
        entry_min = entry - (entry_max - entry)
    if not Decimal("0") < entry_min < mark_price < entry_max:
        raise RehearsalAbort("the entry zone does not contain the mark price")
    # The stop is anchored below the zone (the binding requires sl < entry_min for a LONG, and
    # it is then below the mark) and the targets at or above the mark, so neither can trigger
    # on placement even when the entry sits on the far side of the mark.
    stop = quantize_price(
        price=entry_min * (Decimal("1") - SL_DISTANCE_RATE),
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
    if not stop < entry_min or not stop < mark_price or not tp1 > mark_price or not tp2 > tp1:
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
    # The risk pipeline sizes a LONG at the adverse zone edge `entry_max` (Phase 12 D-03).
    risk_per_unit = (entry_max - stop) + per_unit_round_trip_cost(
        side="LONG", entry_price=entry_max, stop_price=stop, rates=rates
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
        entry_min_price=entry_min,
        entry_max_price=entry_max,
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
        entry_min_price=entry_min,
        entry_max_price=entry_max,
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
        # D078 (19-REVIEW WR-01): the quantity of the plan the request is issued for.
        approved_quantity=plan.trade_plan.quantity_after_rounding,
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


def render_approval_text(
    ctx: RunContext,
    plan: DerivedPlan,
    *,
    title: str,
    signal_id: str,
    approved_quantity: Decimal,
) -> str:
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
        approved_quantity=approved_quantity,
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
    if issued.approval.approved_quantity is None:
        # D078 item (6): the message must show the stored quantity; without one nothing is sent.
        ctx.recorder.add_step(step_name, STEP_FAILED, "approval carries no approved quantity")
        raise RehearsalAbort("the approval carries no approved quantity")
    try:
        await channel.send_approval(
            chat_id=chat_id,
            text=render_approval_text(
                ctx,
                plan,
                title=title,
                signal_id=issued.signal_id,
                approved_quantity=issued.approval.approved_quantity,
            ),
            signal_id=issued.signal_id,
            kind=kind,
        )
    except Exception as exc:  # noqa: BLE001 - recorded by type name only
        ctx.recorder.record_failure("telegram_send", exc)
        ctx.recorder.add_step(step_name, STEP_FAILED, f"send failed: {type(exc).__name__}")
        raise RehearsalAbort("the approval message could not be sent") from None
    return issued


def _reason(result: DispatchResult) -> str:
    code = result.reason_code
    if code is None:
        return "NONE"
    # A RejectionReason member or, since Phase 23, a plain-string code (src/approval/reason_codes).
    return code.value if isinstance(code, RejectionReason) else code


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
        and _reason(result) == "INVALIDATED"
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


async def run_rehearsal(ctx: RunContext) -> str:
    """Dispatch one scenario. Raises RehearsalAbort for a fail-closed stop."""
    if ctx.scenario == "taps":
        return await run_taps(ctx)
    raise UsageError(f"unknown scenario {ctx.scenario!r}")


# --------------------------------------------------------------------------- #
# Composed smoke (plan 24-29, D-33): the whole sequence over the composed live process.
#
# `build_wiring` constructs the process (stores, exchange edge, desk, sender, runner, confirm
# flow, execution service, coordinator, closer, reconcile, stream, scheduler); `run_start_sequence`
# starts it; this section only OBSERVES it and, in a real run, tells the owner which button to
# press. Nothing here steps the coordinator or places an order by hand. The same flow runs on
# the Binance-semantics fake with fake presses (`tests/support/live_smoke_env.py`): every step
# of such a run is labelled SYNTHETIC and none counts as Demo-observed.
# --------------------------------------------------------------------------- #

EVIDENCE_KIND_SYNTHETIC = "SYNTHETIC"
EVIDENCE_KIND_DEMO = "DEMO_OBSERVED"
LISTEN_KEY_MARKER = "<LISTEN_KEY_REDACTED>"
# The documented path form of the user-data connection (docs/SOURCES.md, Phase 18). The SDK owns the
# transport (D-16); the form is recorded once for Phase 25, never a key.
USER_DATA_PATH_FORM = f"/private/ws/{LISTEN_KEY_MARKER}"
SMOKE_POLL_SECONDS = 2
SMOKE_LAG_POLLS = 4
SMOKE_LAG_GAP_SECONDS = 0.5
SMOKE_REPLAY_SETTLE_TICKS = 5
SMOKE_LIVENESS_SAMPLE_CAP = 200
SMOKE_EXPIRY_STEP_SECONDS = 30
SMOKE_EXPIRY_ROUNDS = 60
_SMOKE_STEPS = (
    "start",
    "wiring_check",
    "demo_enable",
    "signal",
    "card",
    "approve",
    "confirm_entry",
    "stream_fill",
    "stop_confirmed",
    "tp_legs",
    "reconcile_clean",
    "restart_rehydrate",
    "replays_place_nothing",
    "close_cleanup",
    "reservation_released_on_close",
    "account_clean",
    "safe_mode_drill",
    "drill_reservation_released",
)


class SmokeHalt(Exception):  # noqa: N818 - a stop of the smoke after the step was recorded
    """The smoke stops here; the failed step is already in the evidence."""


class SmokeOwner(Protocol):
    """What only the owner can do on the live bot (a real run) or a fake does (tests)."""

    async def act(self, action: str, **context: Any) -> None: ...


@dataclass
class SmokeEnv:
    """One composed process and the edges around it.

    `tick` advances the process by one poll (a real run sleeps while the scheduler works; the
    fake runs the task bodies and moves the virtual clock). `restart` builds a second wiring over
    the same stores and the same exchange.
    """

    assembly: Any
    clock: Callable[[], datetime]
    tick: Callable[[], Awaitable[None]]
    pause: Callable[[float], Awaitable[None]]
    owner: SmokeOwner
    synthetic: bool
    wait_ticks: int
    ports_transform: Callable[[Any], Any] = field(default=lambda ports: ports)
    deliver_fill: Callable[[Any], Awaitable[None]] | None = None
    placements: Callable[[], int] | None = None
    restart: Callable[[], Awaitable[SmokeEnv]] | None = None
    initialize_gate_state: bool = False

    @property
    def wiring(self) -> Any:
        return self.assembly.wiring

    @property
    def label(self) -> str:
        return EVIDENCE_KIND_SYNTHETIC if self.synthetic else EVIDENCE_KIND_DEMO


def demo_guarded_sdk_factory(**kwargs: Any) -> Any:
    """The SDK factory of the smoke: DEMO only, and the host is re-read after the build.

    `build_wiring(sdk_factory=...)` hands every SDK object of the process through here, so the
    Demo-host guard wraps the one place a client is made. A LIVE environment never gets a client.
    """
    if kwargs.get("environment") is not Environment.DEMO:
        raise DemoHostViolation("the smoke builds a DEMO SDK client only")
    from src.adapters import binance_client

    bundle = binance_client.build_sdk_client(**kwargs)
    assert_demo_sdk_client(bundle.client)
    return bundle


class SmokeRefused(Exception):  # noqa: N818 - a refusal before any network call
    """The environment does not admit a Demo smoke (mode, credentials, Telegram, limits)."""


def admit_smoke_environment(environ: Mapping[str, str], *, limits_path: Path | None = None) -> Any:
    """The `LiveConfig` of a DEMO smoke, or `SmokeRefused` (names only, never values).

    The live process's own admission (`parse_live_environment`) refuses LIVE credentials next to a
    DEMO mode, the shadow bot's token and any `NOT_CONFIGURED` limit; this adds the rule that the
    smoke runs DEMO and nothing else.
    """
    from src.live.config import LiveRefusal, parse_live_environment

    try:
        config = parse_live_environment(environ, repo_root=REPO_ROOT, limits_path=limits_path)
    except LiveRefusal as exc:
        raise SmokeRefused(exc.reason) from None
    if config.mode is not Environment.DEMO:
        raise SmokeRefused("the smoke runs in DEMO mode only")
    return config


class ConsoleOwner:
    """The real owner: told what to press on the live bot; the flow waits for the effect."""

    _TEXT: Mapping[str, str] = {
        "approve": "On the live Demo bot tap APPROVE on the card {note}(short id {short_id}).",
        "confirm": "Tap CONFIRM on the confirm prompt that follows {note}(short id {short_id}).",
        "confirm_refused": (
            "SAFE_MODE was entered on purpose (the drill): tap CONFIRM now on the confirm prompt "
            "(short id {short_id}); the entry must be REFUSED and nothing placed."
        ),
        "safemode_exit": (
            "Send /safemode_exit to the live Demo bot, then send the '/confirm <token>' line "
            "it answers with, within the token lifetime."
        ),
        "replay_approve": "Tap APPROVE on the FIRST card again (a replay; it must place nothing).",
        "replay_confirm": "Tap CONFIRM on the FIRST confirm prompt again (a replay; it must "
        "place nothing).",
    }

    def __init__(self, recorder: EvidenceRecorder) -> None:
        self._recorder = recorder

    async def act(self, action: str, **context: Any) -> None:
        text = self._TEXT[action].format(
            note=str(context.get("note", "")), short_id=str(context.get("short_id", ""))
        )
        self._recorder.details.setdefault("operator_instructions", []).append(text)
        print(f"OPERATOR: {text}", flush=True)


def _smoke_record(
    env: SmokeEnv, recorder: EvidenceRecorder, name: str, status: str, text: str
) -> None:
    prefix = "SYNTHETIC: " if env.synthetic else ""
    recorder.add_step(name, status, prefix + text)


def _smoke_fail(env: SmokeEnv, recorder: EvidenceRecorder, name: str, text: str) -> SmokeHalt:
    _smoke_record(env, recorder, name, STEP_FAILED, text)
    return SmokeHalt(name)


async def _smoke_read(env: SmokeEnv, fn: Callable[..., Any], *args: Any) -> Any:
    return await env.assembly.executor.read(fn, *args)


async def _wait_until(
    env: SmokeEnv, predicate: Callable[[], Awaitable[bool]], *, ticks: int | None = None
) -> bool:
    for _ in range(env.wait_ticks if ticks is None else ticks):
        if await predicate():
            return True
        await env.tick()
    return await predicate()


def _authorized_update(config: Any) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        update_id=None,
        effective_chat=SimpleNamespace(id=config.authorized_chat_id, type="private"),
        effective_user=SimpleNamespace(id=min(config.authorized_user_ids)),
    )


@dataclass
class _Request:
    """The ids of one injected request (what the evidence and the presses need)."""

    signal_id: str
    trade_plan_id: str
    plan_hash: str
    short_id: str
    entry_client_id: str
    quantity: Decimal
    scenario: str
    expiry_utc: datetime


async def _inject(env: SmokeEnv, recorder: EvidenceRecorder, scenario: str, step: str) -> _Request:
    """The Demo injector: the `/demo_signal` handler of the process, called as the owner."""
    from types import SimpleNamespace

    wiring = env.wiring
    command = wiring.demo_signal
    if command is None:
        raise _smoke_fail(env, recorder, step, "this process has no Demo signal command")
    queued = await command.handle(
        _authorized_update(env.assembly.config), SimpleNamespace(args=[scenario])
    )
    request = command.source.peek()
    if not queued or request is None:
        raise _smoke_fail(env, recorder, step, "no request was queued by the Demo injector")
    ids = _Request(
        signal_id=request.signal.signal_id,
        trade_plan_id=request.plan.trade_plan_id,
        plan_hash=request.plan.plan_hash,
        short_id=derive_short_id(request.signal.signal_id),
        entry_client_id=derive_client_order_id(
            plan_hash=request.plan.plan_hash, role=OrderRole.ENTRY.value
        ),
        quantity=request.plan.quantity_after_rounding,
        scenario=scenario,
        expiry_utc=request.plan.expiry_utc,
    )
    _smoke_record(
        env,
        recorder,
        step,
        STEP_PASSED,
        f"{scenario} request queued by the Demo injector; quantity {ids.quantity}",
    )
    return ids


def _protection(env: SmokeEnv, ids: _Request) -> Any:
    return env.wiring.coordinator.protection_of(ids.plan_hash)


async def _record_order_ids(
    env: SmokeEnv,
    recorder: EvidenceRecorder,
    step: str,
    ids: _Request,
    *,
    legs: Sequence[str] = (),
) -> dict[str, Any]:
    """Per step: the exchange order id and client ids of the entry and the named algo legs."""
    adapter = env.assembly.exchange.adapter
    probe = await adapter.query_order_by_client(
        symbol=SYMBOL, orig_client_order_id=ids.entry_client_id
    )
    algo_ids = [derive_algo_client_id(plan_hash=ids.plan_hash, role=role) for role in legs]
    algo_status: dict[str, str | None] = {}
    for algo_id in algo_ids:
        algo = await adapter.query_algo_order_by_client(client_algo_id=algo_id)
        algo_status[algo_id] = algo.algo_status if algo.found else None
    recorder.record_ids(
        step,
        order_ids=[probe.order_id] if probe.order_id is not None else [],
        client_order_ids=[ids.entry_client_id],
        algo_client_ids=algo_ids,
    )
    return {"entry": probe, "algo": algo_status}


async def _record_start_facts(env: SmokeEnv, recorder: EvidenceRecorder) -> None:
    """D-22 (commission rates per tracked symbol) and D-16 (the user-data URL form, once)."""
    assembly = env.assembly
    rates: dict[str, Any] = {}
    for symbol in assembly.symbols:
        rate = await assembly.exchange.adapter.user_commission_rate(symbol)
        rates[symbol] = {"maker_rate": rate.maker_rate, "taker_rate": rate.taker_rate}
    recorder.details["commission_rates"] = _jsonable(rates)
    recorder.details["user_data_url_form"] = {
        "stream_base": str(assembly.exchange.stream_configuration.stream_url),
        "path_form": USER_DATA_PATH_FORM,
        "listen_key": LISTEN_KEY_MARKER,
        "observation": "documented form recorded; the SDK owns the transport (D-16)",
    }


async def _bring_up(env: SmokeEnv, recorder: EvidenceRecorder, label: str) -> Any:
    """Start the process (D-08 as amended by D094); it must be admitted and enabled."""
    from src.live.startup import run_start_sequence
    from src.live.wiring import check_wiring

    assembly = env.assembly
    ports = env.ports_transform(
        assembly.startup_ports(
            initialize_gate_state=env.initialize_gate_state, operator_id=OPERATOR_ID
        )
    )
    outcome = await run_start_sequence(ports, now_utc=env.clock())
    steps = ", ".join(f"{s.name}={s.outcome}" for s in outcome.steps)
    recovery = outcome.recovery
    recorder.details.setdefault("start_sequences", []).append(
        {
            "label": label,
            "admitted": outcome.admitted,
            "steps": steps,
            "safe_mode_reasons": list(outcome.safe_mode_reasons),
            "recovery_failed_steps": [] if recovery is None else list(recovery.failed_steps),
            "recovery_safe_mode_reasons": []
            if recovery is None
            else list(recovery.safe_mode_reasons),
            "plans_restored": None if recovery is None else recovery.plans_restored,
        }
    )
    if not outcome.admitted:
        raise _smoke_fail(
            env,
            recorder,
            "start" if label == "start" else f"{label}_start",
            f"held at {outcome.held_step} ({outcome.held_code})",
        )
    if recovery is not None and recovery.failed_steps:
        # Finding F3 (24-29): nothing in `src` records the plan constraint snapshot, so the
        # recovery of a restart cannot rebuild a live plan; it fails closed (SAFE_MODE DB_FAILURE).
        raise _smoke_fail(
            env,
            recorder,
            "start" if label == "start" else "restart_rehydrate",
            "recovery failed at "
            + ", ".join(recovery.failed_steps)
            + " (SAFE_MODE "
            + ",".join(recovery.safe_mode_reasons)
            + "): a restorable plan has no persisted snapshot (F3)",
        )
    _smoke_record(env, recorder, label, STEP_PASSED, f"admitted; {steps}")
    broken = check_wiring(assembly.wiring)
    if broken:
        raise _smoke_fail(env, recorder, "wiring_check", f"broken links: {', '.join(broken)}")
    if label == "start":
        _smoke_record(env, recorder, "wiring_check", STEP_PASSED, "check_wiring is empty")
        await _record_start_facts(env, recorder)
    name = "demo_enable" if label == "start" else f"{label}_enable"
    if outcome.in_safe_mode or not outcome.enabled:
        # D094 (24-37): the stream is started before the first reconcile tick, so a CLEAN start
        # is enabled by the start sequence itself (HEALTH, then ENABLE as the last step). A start
        # that is still in SAFE_MODE or disabled is a real finding: the smoke stops and names it;
        # it no longer hides it behind an operator exit and a hand-made enable.
        enable_row = next((s for s in outcome.steps if s.name == "ENABLE"), None)
        standing = getattr(env.wiring.safe_mode, "entered_reason", None)
        raise _smoke_fail(
            env,
            recorder,
            name,
            "the start did not enable entries: SAFE_MODE "
            + (
                ",".join(outcome.safe_mode_reasons) or str(standing)
                if outcome.in_safe_mode
                else "off"
            )
            + "; ENABLE "
            + ("missing" if enable_row is None else f"{enable_row.outcome} {enable_row.code}"),
        )
    # The CLOCK_DRIFT step passes when the MEASUREMENT works, not when the clock is inside the
    # limits; a guard that blocks entries would refuse the placement after the owner's two taps
    # and leave the approved plan blocking the symbol for its whole lifetime (first Demo run,
    # 2026-11-06: host 540 ms ahead of Binance, limit 500 ms).
    # A synthetic run measures nothing real (the fake exchange has no server time).
    guard = getattr(getattr(env.wiring, "exchange", None), "drift_guard", None)
    drift_reason = None if guard is None or env.synthetic else guard.blocked_reason(env.clock())
    if drift_reason is not None:
        verdict = guard.last_verdict
        raise _smoke_fail(
            env,
            recorder,
            name,
            f"the clock drift guard blocks new entries ({drift_reason}; offset_ms="
            f"{None if verdict is None else verdict.offset_ms}): fix the host clock "
            "(w32tm /resync) before a rehearsal; nothing was sent",
        )
    _smoke_record(
        env, recorder, name, STEP_PASSED, "entries enabled by the start sequence (DEMO), last step"
    )
    return outcome


async def _async_value(value: bool) -> bool:
    return value


async def run_composed_smoke(env: SmokeEnv, recorder: EvidenceRecorder) -> str:
    """The D-33 sequence; returns the outcome. Raises `SmokeHalt` after recording a failed step.

    Whatever happens, the process that is running at the end is stopped in order.
    """
    from src.live.runtime import shutdown_in_order

    current = [env]
    try:
        return await _smoke_sequence(env, recorder, current)
    finally:
        try:
            await shutdown_in_order(current[-1].assembly)
        except Exception:  # noqa: BLE001 - shutdown is best effort at the end of a smoke
            pass


async def _smoke_sequence(
    env: SmokeEnv, recorder: EvidenceRecorder, current: list[SmokeEnv]
) -> str:
    from src.live.reconcile import reconcile_tick_once

    recorder.details["evidence_kind"] = env.label
    if env.synthetic:
        recorder.add_synthetic_input(
            "SYNTHETIC run: the exchange is the Binance-semantics fake, the presses are fake and "
            "every id, price and time is a test value; nothing here is Demo-observed"
        )
    _sample_liveness_on_tick(env, recorder)
    await _bring_up(env, recorder, "start")
    record_user_data_liveness(env, recorder)

    # ---- signal, card, APPROVE, CONFIRM, the GTD LIMIT entry with no entry-time stop --------- #
    first = await _inject(env, recorder, "fill", "signal")
    wiring = env.wiring

    async def card_issued() -> bool:
        # The pump empties the queue when it TAKES the request; the plan row is written when the
        # card is issued, seconds later (first Demo run: the script gave up in that gap).
        if wiring.demo_signal is None or wiring.demo_signal.source.pending != 0:
            return False
        row = await _smoke_read(env, wiring.stores.entities.get_trade_plan, first.trade_plan_id)
        return row is not None

    shown = await _wait_until(env, card_issued)
    plan_row = await _smoke_read(env, wiring.stores.entities.get_trade_plan, first.trade_plan_id)
    if not shown or plan_row is None:
        raise _smoke_fail(env, recorder, "card", "the approval card was not issued")
    _smoke_record(env, recorder, "card", STEP_PASSED, "the composed pump sent the approval card")

    await env.owner.act("approve", short_id=first.short_id, note="")

    async def approved() -> bool:
        row = await _smoke_read(env, wiring.stores.entities.get_trade_plan, first.trade_plan_id)
        return row is not None and row.status is TradePlanStatus.APPROVED

    if not await _wait_until(env, approved):
        raise _smoke_fail(env, recorder, "approve", "no APPROVE was seen before the timeout")
    _smoke_record(env, recorder, "approve", STEP_PASSED, "the plan is APPROVED by the owner press")

    await env.owner.act("confirm", short_id=first.short_id, note="")

    async def entry_acked() -> bool:
        row = await _smoke_read(
            env, wiring.stores.execution_state.intent_for_client_id, first.entry_client_id
        )
        return row is not None and row.intent_status is ExecutionIntentStatus.ACKED

    if not await _wait_until(env, entry_acked):
        raise _smoke_fail(env, recorder, "confirm_entry", "the entry was not acknowledged")
    before_fill = _protection(env, first)
    open_algos = await env.assembly.exchange.adapter.snapshot_open_algo_orders(symbol=SYMBOL)
    recorder.details["entry_acked"] = _jsonable(
        {
            "protection_state": None if before_fill is None else before_fill.state,
            "open_algo_orders_at_ack": len(open_algos),
        }
    )
    await _record_order_ids(env, recorder, "confirm_entry", first)
    _smoke_record(
        env,
        recorder,
        "confirm_entry",
        STEP_PASSED,
        "one GTD LIMIT entry acknowledged; no entry-time stop (D079)",
    )

    # ---- the fill is seen on the user-data stream; the coordinator places the stop --------- #
    if env.deliver_fill is not None:
        await env.deliver_fill(first)

    async def filled() -> bool:
        view = _protection(env, first)
        return view is not None and view.state not in (
            ProtectionState.AWAITING_FILL,
            ProtectionState.ENTRY_ENDED_NO_FILL,
        )

    if not await _wait_until(env, filled):
        raise _smoke_fail(env, recorder, "stream_fill", "no fill reached the coordinator")
    _smoke_record(env, recorder, "stream_fill", STEP_PASSED, "the fill reached the coordinator")

    async def stop_confirmed() -> bool:
        view = _protection(env, first)
        return view is not None and view.stop_confirmed_at_utc is not None

    if not await _wait_until(env, stop_confirmed):
        raise _smoke_fail(env, recorder, "stop_confirmed", "the stop was not confirmed by REST")
    stop_role = OrderRole.STOP_LOSS.value
    record_user_data_liveness(env, recorder)
    seen = await _record_order_ids(env, recorder, "stop_confirmed", first, legs=(stop_role,))
    _smoke_record(
        env,
        recorder,
        "stop_confirmed",
        STEP_PASSED,
        f"stop confirmed by REST (algo status {next(iter(seen['algo'].values()), None)})",
    )

    async def complete() -> bool:
        view = _protection(env, first)
        return view is not None and view.state in (
            ProtectionState.COMPLETE,
            ProtectionState.TP_UNAVAILABLE,
        )

    gaps = 0
    await _wait_until(env, complete)
    tp_roles = (OrderRole.TAKE_PROFIT_1.value, OrderRole.TAKE_PROFIT_2.value)
    seen = await _record_order_ids(env, recorder, "tp_legs", first, legs=(stop_role, *tp_roles))
    view = _protection(env, first)
    if view is not None and view.state is ProtectionState.COMPLETE:
        _smoke_record(
            env, recorder, "tp_legs", STEP_PASSED, "TP1 and TP2 placed (complete snapshot)"
        )
    else:
        gaps += 1
        _smoke_record(
            env,
            recorder,
            "tp_legs",
            STEP_NOT_REHEARSED,
            "take-profit legs not placed: "
            + str(None if view is None else (view.state.value, view.last_reason)),
        )
    await _record_fill_sample(env, recorder, first)
    await _record_entry_price(env, recorder)

    # ---- reconcile clean, then the SAFE_MODE drill ------------------------------------------ #
    report = await reconcile_tick_once(wiring.reconcile, env.clock())
    clean = report.agreement is True and not report.divergences and report.failed_source is None
    recorder.details["reconcile_after_fill"] = _jsonable(
        {"agreement": report.agreement, "divergences": len(report.divergences)}
    )
    if not clean:
        raise _smoke_fail(env, recorder, "reconcile_clean", "the reconcile compare was not clean")
    _smoke_record(env, recorder, "reconcile_clean", STEP_PASSED, "reconcile agrees, no divergence")

    # ---- restart and rehydrate over the same stores, then the replays ------------------------ #
    if env.restart is None:
        raise _smoke_fail(env, recorder, "restart_rehydrate", "no restart is available")
    from src.live.runtime import shutdown_in_order

    failed_steps = await shutdown_in_order(env.assembly)
    recorder.details["first_process_shutdown_failed_steps"] = failed_steps
    second = await env.restart()
    current.append(second)
    _sample_liveness_on_tick(second, recorder)
    await _bring_up(second, recorder, "restart")
    restored = _protection(second, first)
    if restored is None or restored.state is not ProtectionState.COMPLETE:
        state = None if restored is None else restored.state.value
        raise _smoke_fail(second, recorder, "restart_rehydrate", f"plan not rehydrated: {state}")
    _smoke_record(
        second, recorder, "restart_rehydrate", STEP_PASSED, "the second wiring rehydrated the plan"
    )
    await _replays(second, recorder, first)

    # ---- close and clean up ------------------------------------------------------------------ #
    from src.execution.manager import operator_close_position

    record_user_data_liveness(second, recorder)
    closed = await operator_close_position(
        coordinator=second.wiring.coordinator, plan_hash=first.plan_hash, operator_id=OPERATOR_ID
    )
    if not closed.accepted:
        raise _smoke_fail(second, recorder, "close_cleanup", f"close refused: {closed.code}")

    async def flat() -> bool:
        view = _protection(second, first)
        return view is not None and view.state is ProtectionState.FLAT

    if not await _wait_until(second, flat):
        raise _smoke_fail(second, recorder, "close_cleanup", "the plan did not end FLAT")
    await _record_cancel_lag(second, recorder, first, (stop_role, *tp_roles))
    _smoke_record(second, recorder, "close_cleanup", STEP_PASSED, "closed by the operator close")
    await _reservation_released_on_close(second, recorder, first)
    adapter = second.assembly.exchange.adapter
    left = (
        len(await adapter.snapshot_open_normal_orders(symbol=SYMBOL)),
        len(await adapter.snapshot_open_algo_orders(symbol=SYMBOL)),
        len(await adapter.snapshot_positions(symbol=SYMBOL)),
    )
    if any(left):
        raise _smoke_fail(
            second,
            recorder,
            "account_clean",
            f"orders {left[0]}, algos {left[1]}, positions {left[2]}",
        )
    _smoke_record(
        second, recorder, "account_clean", STEP_PASSED, "no order, algo order or position"
    )
    await _safe_mode_drill(second, recorder, after=first.expiry_utc)
    return OUTCOME_COMPLETE_WITH_GAPS if gaps else OUTCOME_COMPLETE


async def _wait_for_expiry(env: SmokeEnv, expiry_utc: datetime) -> None:
    """Wait (bounded) until a plan's expiry has passed, ticking the process meanwhile."""
    for _ in range(SMOKE_EXPIRY_ROUNDS):
        remaining = (expiry_utc - env.clock()).total_seconds()
        if remaining <= 0:
            break
        await env.pause(min(remaining + 1, SMOKE_EXPIRY_STEP_SECONDS))
        await env.tick()
    for _ in range(SMOKE_REPLAY_SETTLE_TICKS):
        await env.tick()


async def _safe_mode_drill(env: SmokeEnv, recorder: EvidenceRecorder, *, after: datetime) -> None:
    """Enter SAFE_MODE, show the owner's CONFIRM refused, leave it through the operator exit.

    It runs after the close, on an idle symbol, once the main plan has expired. It cannot sit
    between the clean reconcile and the restart (the D-33 position): while the first position is
    open, a second request on the symbol is refused at the card (CONFLICT_WITH_OPEN_POSITION,
    ACTIVE_PLAN, PENDING_OR_APPROVED_APPROVAL), and that is the symbol rule, not the reservation.
    A refused CONFIRM leaves its plan APPROVED, so the card of the symbol stays refused until the
    drill plan expires; the last step (F4, plan 24-37) waits for that expiry and shows that the
    scheduler's reservation sweep released the reservation, so the next entry is not counted out.
    """
    wiring = env.wiring
    await _wait_for_expiry(env, after)
    drill = await _inject(env, recorder, "far", "safe_mode_drill_signal")
    shown = await _wait_until(
        env,
        lambda: _async_value(
            wiring.demo_signal is not None and wiring.demo_signal.source.pending == 0
        ),
    )
    if not shown:
        raise _smoke_fail(env, recorder, "safe_mode_drill", "the drill card was not issued")
    await env.owner.act("approve", short_id=drill.short_id, note="of the DRILL request ")

    async def approved() -> bool:
        row = await _smoke_read(env, wiring.stores.entities.get_trade_plan, drill.trade_plan_id)
        return row is not None and row.status is TradePlanStatus.APPROVED

    if not await _wait_until(env, approved):
        raise _smoke_fail(env, recorder, "safe_mode_drill", "the drill plan was not APPROVED")
    wiring.safe_mode.enter_safe_mode(reason="DEMO_SMOKE_DRILL", now_utc=env.clock())
    await env.owner.act("confirm_refused", short_id=drill.short_id)
    for _ in range(SMOKE_REPLAY_SETTLE_TICKS):
        await env.tick()
    adapter = env.assembly.exchange.adapter
    placed = await _smoke_read(
        env, wiring.stores.execution_state.intent_for_client_id, drill.entry_client_id
    )
    orders = await adapter.snapshot_open_normal_orders(symbol=SYMBOL)
    if placed is not None or orders:
        raise _smoke_fail(env, recorder, "safe_mode_drill", "an entry was placed in SAFE_MODE")
    await env.owner.act("safemode_exit")
    if not await _wait_until(env, lambda: _async_value(not wiring.safe_mode.in_safe_mode)):
        raise _smoke_fail(env, recorder, "safe_mode_drill", "SAFE_MODE was not left")
    _smoke_record(
        env,
        recorder,
        "safe_mode_drill",
        STEP_PASSED,
        "entered; a CONFIRM placed nothing; left through /safemode_exit",
    )
    await _drill_reservation_released(env, recorder, drill)


async def _reservation_released_on_close(
    env: SmokeEnv, recorder: EvidenceRecorder, first: _Request
) -> None:
    """F5: the closed position's reservation is released by the sweep (POSITION_CLOSED)."""
    reservations = env.wiring.stores.reservations

    async def released() -> bool:
        record = await _smoke_read(env, reservations.get, first.trade_plan_id)
        return record is not None and record.status.value == "RELEASED"

    if not await _wait_until(env, released):
        raise _smoke_fail(
            env,
            recorder,
            "reservation_released_on_close",
            "the reservation of the closed position was not released by the sweep",
        )
    record = await _smoke_read(env, reservations.get, first.trade_plan_id)
    reason = (
        None if record is None or record.release_reason is None else record.release_reason.value
    )
    if reason != "POSITION_CLOSED":
        raise _smoke_fail(
            env, recorder, "reservation_released_on_close", f"released with reason {reason}"
        )
    _smoke_record(
        env,
        recorder,
        "reservation_released_on_close",
        STEP_PASSED,
        "the sweep released the closed position's reservation (POSITION_CLOSED)",
    )


async def _drill_reservation_released(
    env: SmokeEnv, recorder: EvidenceRecorder, drill: _Request
) -> None:
    """F4: the refused drill plan's reservation is released by the sweep once the plan expires."""
    wiring = env.wiring
    reservations = wiring.stores.reservations
    await _wait_for_expiry(env, drill.expiry_utc)

    async def released() -> bool:
        record = await _smoke_read(env, reservations.get, drill.trade_plan_id)
        return record is not None and record.status.value == "RELEASED"

    if not await _wait_until(env, released):
        raise _smoke_fail(
            env,
            recorder,
            "drill_reservation_released",
            "the reservation of the refused drill plan was not released after its expiry",
        )
    record = await _smoke_read(env, reservations.get, drill.trade_plan_id)
    reason = (
        None if record is None or record.release_reason is None else record.release_reason.value
    )
    if reason != "PLAN_EXPIRED":
        raise _smoke_fail(
            env, recorder, "drill_reservation_released", f"released with reason {reason}"
        )
    _smoke_record(
        env,
        recorder,
        "drill_reservation_released",
        STEP_PASSED,
        "the sweep released the refused plan's reservation (PLAN_EXPIRED)",
    )


async def _replays(env: SmokeEnv, recorder: EvidenceRecorder, first: _Request) -> None:
    """Replayed APPROVE and CONFIRM presses of the first card place nothing."""
    adapter = env.assembly.exchange.adapter
    positions_before = await adapter.snapshot_positions(symbol=SYMBOL)
    placed_before = None if env.placements is None else env.placements()
    await env.owner.act("replay_approve", short_id=first.short_id)
    await env.owner.act("replay_confirm", short_id=first.short_id)
    for _ in range(SMOKE_REPLAY_SETTLE_TICKS):
        await env.tick()
    orders = await adapter.snapshot_open_normal_orders(symbol=SYMBOL)
    positions_after = await adapter.snapshot_positions(symbol=SYMBOL)
    same = [p.position_amt for p in positions_before] == [p.position_amt for p in positions_after]
    placed_after = None if env.placements is None else env.placements()
    if orders or not same or placed_before != placed_after:
        raise _smoke_fail(env, recorder, "replays_place_nothing", "a replay changed the account")
    _smoke_record(
        env, recorder, "replays_place_nothing", STEP_PASSED, "the replays placed no order"
    )


async def _record_fill_sample(env: SmokeEnv, recorder: EvidenceRecorder, ids: _Request) -> None:
    """D-23: one fill's realizedPnl and commission side by side, as evidence only (D086)."""
    now = env.clock()
    rows = await env.assembly.exchange.adapter.user_trades_in_window(
        symbol=SYMBOL, start_utc=now - timedelta(hours=1), end_utc=now + timedelta(minutes=1)
    )
    sample = None if not rows else rows[-1]
    recorder.details["fill_pnl_sample"] = (
        None
        if sample is None
        else {
            "realized_pnl": format(sample.realized_pnl, "f"),
            "commission": format(sample.commission, "f"),
            "commission_asset": sample.commission_asset,
            "note": "evidence only, D086: LIVE_NET_PNL_SEMANTICS_VERIFIED stays False",
        }
    )
    del ids


async def _record_entry_price(env: SmokeEnv, recorder: EvidenceRecorder) -> None:
    """D-34: the entry price as the adapter boundary hands it over (string/Decimal path)."""
    positions = await env.assembly.exchange.adapter.snapshot_positions(symbol=SYMBOL)
    if positions:
        price = positions[0].entry_price
        recorder.details["entry_price_raw"] = {
            "value": format(price, "f"),
            "type": type(price).__name__,
            "boundary": "adapter output after the string/Decimal conversion (24-34)",
        }
    else:
        recorder.details["entry_price_raw"] = None


async def _record_cancel_lag(
    env: SmokeEnv, recorder: EvidenceRecorder, ids: _Request, roles: Sequence[str]
) -> None:
    """D-34: how long a cancelled algo order still reads NEW by client id (a few quick polls)."""
    adapter = env.assembly.exchange.adapter
    observations: list[dict[str, Any]] = []
    for role in roles:
        algo_id = derive_algo_client_id(plan_hash=ids.plan_hash, role=role)
        series: list[dict[str, Any]] = []
        for poll in range(SMOKE_LAG_POLLS):
            probe = await adapter.query_algo_order_by_client(client_algo_id=algo_id)
            series.append(
                {
                    "after_seconds": poll * SMOKE_LAG_GAP_SECONDS,
                    "found": probe.found,
                    "algo_status": probe.algo_status,
                }
            )
            await env.pause(SMOKE_LAG_GAP_SECONDS)
        observations.append({"role": role, "algo_client_id": algo_id, "polls": series})
    recorder.details["cancel_query_lag_observations"] = _jsonable(observations)


def record_user_data_liveness(env: SmokeEnv, recorder: EvidenceRecorder) -> None:
    """The ping and pong times the supervisor saw (reused from the process, not re-measured).

    A sample is kept only when one of the times changed since the last one, so the list is the
    sequence of distinct observed ping/pong/event times (capped). The long silence measurement
    stays `scripts/user_data_silence_probe.py`.
    """
    snapshot = env.wiring.stream.supervisor.liveness()
    sample = _jsonable(
        {
            "state": snapshot.state,
            "last_event_at_utc": snapshot.last_event_at_utc,
            "last_ping_at_utc": snapshot.last_ping_at_utc,
            "last_pong_at_utc": snapshot.last_pong_at_utc,
        }
    )
    samples: list[dict[str, Any]] = recorder.details.setdefault("user_data_liveness", [])
    if len(samples) >= SMOKE_LIVENESS_SAMPLE_CAP or (samples and samples[-1] == sample):
        return
    samples.append(sample)


def _sample_liveness_on_tick(env: SmokeEnv, recorder: EvidenceRecorder) -> None:
    """Sample the supervisor's ping/pong times after every poll of this process."""
    inner = env.tick

    async def tick() -> None:
        await inner()
        if env.assembly.is_complete:
            record_user_data_liveness(env, recorder)

    env.tick = tick


def build_smoke_attestation(recorder: EvidenceRecorder) -> dict[str, Any]:
    """Per step: OBSERVED only for a real run's PASSED step, SYNTHETIC for a fake one (T-24-93)."""
    synthetic = recorder.details.get("evidence_kind") == EVIDENCE_KIND_SYNTHETIC
    result: dict[str, Any] = {}
    for name in _SMOKE_STEPS:
        status = _step_status(recorder, name)
        if status == STEP_PASSED:
            result[name] = "SYNTHETIC_NOT_OBSERVED" if synthetic else "OBSERVED"
        else:
            result[name] = status or "NOT_OBSERVED"
    return {"composed_smoke": result}


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


SmokeEnvFactory = Callable[[EvidenceRecorder], Awaitable[SmokeEnv]]


def _real_smoke_env_factory(
    *,
    config: Any,
    environ: Mapping[str, str],
    clock: Callable[[], datetime],
    initialize_gate_state: bool,
    approval_timeout_seconds: int,
    sleep: Callable[[int], Awaitable[None]],
) -> SmokeEnvFactory:
    """The real process: `default_assemble` with the Demo-host-guarded SDK factory (D-33)."""
    from src.live.runtime import LiveContext, default_assemble

    async def poll() -> None:
        await sleep(SMOKE_POLL_SECONDS)

    async def pause(seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def build(recorder: EvidenceRecorder) -> SmokeEnv:
        def make(initialize: bool) -> SmokeEnv:
            context = LiveContext(
                config=config,
                env=environ,
                clock=clock,
                started_at_utc=clock(),
                initialize_gate_state=initialize,
                operator_id=OPERATOR_ID,
            )
            assembly = default_assemble(context, sdk_factory=demo_guarded_sdk_factory)

            async def restart() -> SmokeEnv:
                return make(False)

            return SmokeEnv(
                assembly=assembly,
                clock=clock,
                tick=poll,
                pause=pause,
                owner=ConsoleOwner(recorder),
                synthetic=False,
                wait_ticks=max(1, approval_timeout_seconds // SMOKE_POLL_SECONDS),
                restart=restart,
                initialize_gate_state=initialize,
            )

        return make(initialize_gate_state)

    return build


async def _fake_smoke_env(recorder: EvidenceRecorder) -> SmokeEnv:
    """The default (no --execute) environment: the composed process on the fakes, SYNTHETIC."""
    import tempfile

    from tests.support.live_smoke_env import build_fake_smoke_env

    del recorder
    directory = Path(tempfile.mkdtemp(prefix="smoke-fake-"))
    env = build_fake_smoke_env(directory)
    assert isinstance(env, SmokeEnv)
    return env


async def _run_smoke(factory: SmokeEnvFactory, recorder: EvidenceRecorder) -> str:
    env = await factory(recorder)
    return await run_composed_smoke(env, recorder)


def _main_smoke(
    args: argparse.Namespace,
    mode: RunMode,
    env: Mapping[str, str],
    now: Callable[[], datetime],
    evidence_dir: Path | None,
    smoke_env_factory: SmokeEnvFactory | None,
    sleep: Callable[[int], Awaitable[None]] | None,
) -> int:
    """The composed smoke (D-33): admission first, then the sequence, then the evidence."""
    factory: SmokeEnvFactory
    if smoke_env_factory is not None:
        factory = smoke_env_factory
    elif mode is RunMode.EXECUTE:
        try:
            config = admit_smoke_environment(env)
        except SmokeRefused as exc:
            print(f"refused ({type(exc).__name__}): {exc}", file=sys.stderr)
            return EXIT_REFUSED
        factory = _real_smoke_env_factory(
            config=config,
            environ=env,
            clock=now,
            initialize_gate_state=bool(args.initialize_gate_state),
            approval_timeout_seconds=args.approval_timeout_seconds,
            sleep=sleep if sleep is not None else _default_sleep,
        )
    else:
        factory = _fake_smoke_env
    target_dir = evidence_dir if evidence_dir is not None else args.evidence_dir
    if target_dir is None:
        target_dir = SMOKE_EVIDENCE_DIR
    recorder = EvidenceRecorder(
        mode=mode,
        scenario=SCENARIO_SMOKE,
        symbol=SYMBOL,
        base_url=DEMO_BASE_URL,
        environ=env,
        clock=now,
    )
    outcome: str
    try:
        outcome = asyncio.run(_run_smoke(factory, recorder))
    except SmokeHalt as exc:
        recorder.record_failure("run", exc)
        print(f"STOPPED at step {exc}", file=sys.stderr)
        if mode is RunMode.EXECUTE:
            recorder.details.setdefault("operator_instructions", []).append(
                "Check the Binance Demo UI for any open position or order and close it by hand."
            )
        outcome = OUTCOME_FAILED
    except (DemoHostViolation, RehearsalAbort) as exc:
        recorder.record_failure("run", exc)
        recorder.add_step("run", STEP_FAILED, f"aborted: {type(exc).__name__}: {exc}")
        outcome = OUTCOME_ABORTED
    except Exception as exc:  # noqa: BLE001 - recorded by type name, never by message
        recorder.record_failure("run", exc)
        recorder.add_step("run", STEP_FAILED, f"run failed: {type(exc).__name__}")
        outcome = OUTCOME_FAILED
    recorder.attestation_map = build_smoke_attestation(recorder)
    recorder.outcome = outcome
    path = recorder.write(target_dir)
    print(f"evidence: {path}")
    for line in recorder.details.get("operator_instructions", []):
        print(f"OPERATOR: {line}")
    return _outcome_exit_code(outcome)


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
    smoke_env_factory: SmokeEnvFactory | None = None,
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
        if args.scenario == SCENARIO_SMOKE:
            return _main_smoke(args, mode, env, now, evidence_dir, smoke_env_factory, sleep)
        credentials = load_credentials(env)
        signed_call_policy = load_signed_call_policy(args.limits_file)
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
