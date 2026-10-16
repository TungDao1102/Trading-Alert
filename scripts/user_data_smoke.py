"""Connected-machine smoke of the Binance USD-M user-data stream (Phase 18, plan 18-16, D-04, D-15).

Run from the repository root::

    uv run python -m scripts.user_data_smoke --environment DEMO --smoke-limits-file <file>

What it is. A single-file operator tool, in the style of ``scripts/demo_rehearsal.py``, that
composes the project's user-data adapter (``UserDataAdapter``, ``SdkListenKeyPort``,
``SdkUserDataTransport``) and its supervisor (``UserDataSupervisor``) for one selected non-LIVE
environment and records, in one scrubbed evidence file, the acceptance items a to h of the
research (C3): (a) a listenKey is started, (b) the SDK ``user_data`` subscription completes,
(c) after one far LIMIT order is placed and cancelled, typed ``ORDER_TRADE_UPDATE`` events NEW
and CANCELED arrive through the SDK ``user_data`` route, (d) a keepalive returns, (e) a forced
transport drop goes UNKNOWN, then a REST snapshot, then LIVE, with the measured gap, (f) what a
``DELETE`` followed by a ``PUT`` of the listenKey answers, (g) no key, secret, signature or
listenKey in the captured logs, (h) the evidence is written. The first acceptance criterion is
delivery through the SDK route (research finding 2): a silent route is recorded as
``sdk_route_delivery`` FAIL and never hidden. Scripts are the only allowed wiring (D-04).

Safety posture (read before running anything):

* Dry run is the default. Without ``--execute`` the identical pipeline runs over the SDK-shaped
  fakes of ``tests/userdata_fakes.py`` on virtual time: no socket, no HTTP request, no
  credential, no real sleep. Its evidence carries ``proof_class`` FAKE, which never closes an
  acceptance item on Binance.
* ``--execute`` needs an interactive terminal AND the exactly typed phrase
  ``DEMO SMOKE <SYMBOL>`` (the symbol of the smoke limits file). Anything else exits 2 before
  any network call.
* There is no option for a host, a URL, a key, a secret or LIVE: the environment choices are
  DEMO and TESTNET, every URL comes from the environment row of
  ``src/adapters/binance_client.py``, and the environment guard (``assert_environment``) runs
  before every stage and every call. Credentials come only from the environment variables of
  the environment's credential specification (or their ``<NAME>_FILE`` files outside the
  repository); the presence of any LIVE credential variable refuses the run.
* A failed or out-of-limit server-time drift measurement (ratified drift limits) aborts with
  exit 3 before any order, and so does a far price outside the symbol's PERCENT_PRICE band or a
  size below the minimum quantity or the minimum notional.
* The smoke places exactly ONE far LIMIT BUY of the size in the owner-approved smoke limits
  file and cancels it (also in the cleanup path). It never places a protective order, a market
  order or any second order. Account state is recorded before and after; an end state that is
  not flat with zero open orders is reported as MANUAL_CLEANUP_REQUIRED (exit 1).
* The account's listenKey is a singleton: no other process may run on the same account during
  the smoke (research P7). The run stops the stream with ``close_listen_key=True``.
* Evidence and recorded frames are scrubbed before and re-scanned after an atomic write and
  never overwrite a file. One ``RestRateLimitGate`` per run is shared by every REST holder: a
  418 ban or a 429 pause stops every REST call of the process (user record 18-DEC-O-18-01.md
  and its amendment of 2026-10-16).

Exit codes::

    0  the run completed and every step passed
    1  the run failed part-way (evidence written), the SDK route was silent, or the end state
       needs manual cleanup
    2  refused before any network call (usage, limits files, environment, credentials,
       --execute gate)
    3  aborted before any order (environment guard, server-time drift, exchange filters,
       account not flat before the smoke)

Operator runbook: plan 18-18 (blocking-human) runs this tool on Demo with the owner present.
The executor agent that built this tool never ran it against Binance. Dry runs write
``user-data-smoke-DRYRUN-<UTC stamp>.json``; executed runs write
``user-data-smoke-EVIDENCE-<UTC stamp>.json`` under the phase ``evidence`` directory.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import heapq
import importlib.metadata
import io
import itertools
import json
import logging
import os
import re
import sys
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, NoReturn, Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from binance_common import websocket as sdk_websocket  # noqa: E402
from binance_common.configuration import ConfigurationWebSocketStreams  # noqa: E402
from binance_common.websocket import StreamConnectionsMap  # noqa: E402
from src.adapters import binance_client  # noqa: E402
from src.adapters.binance_client import (  # noqa: E402
    SDK_STREAMS_PATH_SUFFIX,
    CredentialError,
    CredentialNamesNotRatified,
    EndpointViolation,
    Environment,
    EnvironmentNotConfigured,
    LiveNotEnabled,
    Surface,
    assert_endpoint_url,
    parse_environment,
)
from src.adapters.binance_clock import measure_clock_drift  # noqa: E402
from src.adapters.binance_errors import error_facts_from_exception  # noqa: E402
from src.adapters.binance_limits import (  # noqa: E402
    BinanceLimits,
    LimitsNotRatified,
    load_binance_limits,
)
from src.adapters.binance_public import BinancePublicMarketData, SymbolFilters  # noqa: E402
from src.adapters.binance_ratelimit_gate import RestGateRefusal, RestRateLimitGate  # noqa: E402
from src.adapters.binance_usdm import (  # noqa: E402
    EntryPlacementResult,
    OpenAlgoOrderSnapshot,
    OpenOrderSnapshot,
    PositionModeResult,
    PositionSnapshot,
)
from src.adapters.binance_userdata import (  # noqa: E402
    PRIVATE_URL_PATH,
    ListenKeyError,
    ListenKeyPort,
    SdkListenKeyPort,
    SdkUserDataTransport,
    UserDataAdapter,
    capture_raw_user_events,
    install_sdk_noise_guard,
)
from src.adapters.binance_userdata_events import OrderUpdateEvent, StreamAnomaly  # noqa: E402
from src.adapters.binance_userdata_supervisor import (  # noqa: E402
    StreamSnapshot,
    StreamState,
    TrustedEvent,
    UserDataSupervisor,
)
from src.domain.exchange_errors import CallKind, ExchangeErrorCategory, classify  # noqa: E402
from src.ops.operator_evidence import (  # noqa: E402
    EXIT_ABORTED,
    EXIT_FAILED,
    EXIT_OK,
    EXIT_REFUSED,
    ConfirmationRefused,
    DemoOrderLimits,
    DemoOrderLimitsRefused,
    confirm_execute,
    jsonable,
    load_demo_order_limits,
    sha256_lf,
    write_evidence_atomic,
)
from src.ops.redaction import (  # noqa: E402
    RedactingFilter,
    Redactor,
    configure_logging,
    register_runtime_secret,
)

# --------------------------------------------------------------------------- #
# Constants (tool settings and vocabulary; no safety threshold lives here).
# --------------------------------------------------------------------------- #

EVIDENCE_SCHEMA = "user-data-smoke-evidence/schema-1"
PHASE_DIR = REPO_ROOT / ".planning" / "phases" / "18-user-data-stream-error-taxonomy"
DEFAULT_EVIDENCE_DIR = PHASE_DIR / "evidence"
DEFAULT_LIMITS_FILE = REPO_ROOT / "config" / "binance" / "binance-limits-v1.toml"
RECORDED_DEMO_FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "phase18" / "recorded_demo"

ENVIRONMENT_CHOICES: tuple[str, ...] = (Environment.DEMO.value, Environment.TESTNET.value)
SURFACES: frozenset[Surface] = frozenset({Surface.REST, Surface.WS_STREAMS})

MODE_DRY_RUN = "dry-run"
MODE_EXECUTE = "execute"
MODES: frozenset[str] = frozenset({MODE_DRY_RUN, MODE_EXECUTE})
PROOF_FAKE = "FAKE"
PROOF_REAL_SMOKE = "REAL_SMOKE"
PROOF_CLASSES: frozenset[str] = frozenset({PROOF_FAKE, PROOF_REAL_SMOKE})

ROUTE_PASS = "PASS"
ROUTE_FAIL = "FAIL"
ROUTE_NOT_RUN = "NOT_RUN"
ROUTE_VALUES: frozenset[str] = frozenset({ROUTE_PASS, ROUTE_FAIL, ROUTE_NOT_RUN})

PASSED = "PASSED"
FAILED = "FAILED"
NOT_RUN = "NOT_RUN"
SKIPPED_DRY_RUN = "SKIPPED_DRY_RUN"
STEP_STATUSES: frozenset[str] = frozenset({PASSED, FAILED, NOT_RUN, SKIPPED_DRY_RUN})

STEP_NAMES: tuple[str, ...] = (
    "preflight",
    "account_before",
    "stream_start",
    "keepalive",
    "order_place",
    "order_new_event",
    "order_cancel",
    "order_canceled_event",
    "forced_drop",
    "account_after",
    "stop_and_delete_then_put",
    "log_scan",
    "evidence_write",
)

END_FLAT = "FLAT"
END_MANUAL_CLEANUP = "MANUAL_CLEANUP_REQUIRED"
END_NOT_RUN = "NOT_RUN"

OUTCOME_COMPLETE = "COMPLETE"
OUTCOME_FAILED = "FAILED"
OUTCOME_ABORTED = "ABORTED_NO_ORDER"

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_UNPROVEN = "UNPROVEN"
VERDICT_OBSERVED = "OBSERVED"
VERDICT_RESULTS: frozenset[str] = frozenset(
    {VERDICT_PASS, VERDICT_FAIL, VERDICT_UNPROVEN, VERDICT_OBSERVED}
)
ACCEPTANCE_LETTERS: tuple[str, ...] = ("a", "b", "c", "d", "e", "f", "g", "h")

FIXTURE_LABEL_EXECUTE = "RECORDED_DEMO"
FIXTURE_LABEL_DRY_RUN = "FAKE_DRYRUN"

SINGLETON_NOTE = (
    "The account's listenKey is a singleton: no other process may run on the same account "
    "during the smoke (a DELETE ends the stream of every holder of the key, research P7)."
)
FAKE_NOTE = "proof_class FAKE: evidence over the SDK-shaped fakes never closes an acceptance item."

# The one far order (tool vocabulary, not a trading decision).
ORDER_SIDE = "BUY"
ORDER_TIME_IN_FORCE = "GTC"
POSITION_SIDE_ONE_WAY = "BOTH"
POSITION_SIDE_HEDGE_LONG = "LONG"
MARK_INTERVAL = "1m"
MARK_LIMIT = 1
CLIENT_ID_PREFIX = "uds-smoke-"
TRADING_STATUS = "TRADING"

EXECUTION_NEW = "NEW"
EXECUTION_CANCELED = "CANCELED"

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MS = timedelta(milliseconds=1)
_GATE_CATEGORIES: frozenset[ExchangeErrorCategory] = frozenset(
    {ExchangeErrorCategory.IP_BANNED, ExchangeErrorCategory.RATE_LIMITED}
)
# A listenKey is long alphanumeric text; a sha256 digest (lower-case hex) is not one.
_LISTEN_KEY_SHAPE = re.compile(r"[A-Za-z0-9]{60,}")
_HEX_DIGEST = re.compile(r"^[0-9a-f]+$")
_SIGNATURE_SHAPE = re.compile(r"(?i)signature=[0-9a-f]{64}")
_FIXTURE_EVENT_RE = re.compile(r"[^A-Za-z0-9_]")
# The SDK module global the receive loop parses every user-data payload with; the dry run
# calls it by name so the raw-frame tap (`capture_raw_user_events`) sees the fake frames too.
_PARSE_USER_EVENT = "parse_user_event"

# How many event-loop turns the dry run's virtual clock waits for in-loop work to settle
# before it moves virtual time to the next sleeper (a dry-run mechanism, not a time value).
SETTLE_ROUNDS = 500


# --------------------------------------------------------------------------- #
# Errors.
# --------------------------------------------------------------------------- #


class UsageError(Exception):
    """A bad or forbidden command-line argument."""


class LimitsFileRefused(Exception):  # noqa: N818 - a refusal, like ConfirmationRefused
    """A limits file is missing or invalid; the message names the file and keys only."""

    def __init__(self, label: str, path: Path, problems: Sequence[str] = ()) -> None:
        detail = f" ({'; '.join(problems)})" if problems else ""
        super().__init__(f"the {label} file is missing or invalid: {path}{detail}")


class _Abort(Exception):  # noqa: N818 - an internal signal: fail closed before any order
    """The run stops before any order (exit 3)."""


class _Bounded(Exception):  # noqa: N818 - an internal signal
    """A cleanup step did not finish within the owner's cleanup timeout."""


class _ArgumentParser(argparse.ArgumentParser):
    """argparse that raises instead of exiting, so `main` returns the exit code."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


# --------------------------------------------------------------------------- #
# Configuration.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SmokeConfig:
    environment: Environment
    mode: str
    limits_file: Path
    smoke_limits_file: Path
    evidence_dir: Path
    fixtures_dir: Path | None
    limits: BinanceLimits
    order_limits: DemoOrderLimits

    @property
    def symbol(self) -> str:
        return self.order_limits.symbol


def required_phrase(environment: Environment, symbol: str) -> str:
    """The exact phrase `--execute` needs, for example ``DEMO SMOKE BTCUSDT``."""
    return f"{environment.value} SMOKE {symbol}"


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="user_data_smoke",
        description="User-data stream smoke on a non-LIVE environment (dry run by default).",
        allow_abbrev=False,
    )
    parser.add_argument("--environment", required=True, choices=ENVIRONMENT_CHOICES)
    parser.add_argument(
        "--limits-file",
        type=Path,
        default=DEFAULT_LIMITS_FILE,
        help="the ratified Binance limits file (default: config/binance/binance-limits-v1.toml)",
    )
    parser.add_argument(
        "--smoke-limits-file",
        type=Path,
        required=True,
        help="the owner-approved order size and waits of the smoke (no default)",
    )
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help="write every raw user-data payload, scrubbed, into this directory",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="run against the selected environment (interactive terminal and typed phrase)",
    )
    return parser


def _is_within(path: Path, parent: Path) -> bool:
    return path.resolve().is_relative_to(parent.resolve())


def parse_config(argv: Sequence[str] | None) -> SmokeConfig:
    """Parse the command line and load both limits files (refusals raise before any I/O)."""
    args = _build_parser().parse_args(argv)
    environment = parse_environment(args.environment)
    mode = MODE_EXECUTE if args.execute else MODE_DRY_RUN
    fixtures_dir: Path | None = args.fixtures_dir
    if (
        mode == MODE_DRY_RUN
        and fixtures_dir is not None
        and _is_within(fixtures_dir, RECORDED_DEMO_FIXTURES_DIR)
    ):
        raise UsageError("a dry run never writes into the recorded Demo fixtures directory")
    try:
        limits = load_binance_limits(args.limits_file)
    except (LimitsNotRatified, ValueError, TypeError):
        raise LimitsFileRefused("binance limits", args.limits_file) from None
    try:
        order_limits = load_demo_order_limits(args.smoke_limits_file, kind="smoke")
    except DemoOrderLimitsRefused as exc:
        raise LimitsFileRefused("smoke limits", args.smoke_limits_file, exc.problems) from None
    return SmokeConfig(
        environment=environment,
        mode=mode,
        limits_file=Path(args.limits_file),
        smoke_limits_file=Path(args.smoke_limits_file),
        evidence_dir=Path(args.evidence_dir),
        fixtures_dir=fixtures_dir,
        limits=limits,
        order_limits=order_limits,
    )


def require_configured(environment: Environment) -> None:
    """Raise `EnvironmentNotConfigured` unless REST and WebSocket Streams have a row URL."""
    row = binance_client.ENVIRONMENT_ROWS[environment]
    for surface in sorted(SURFACES):
        if row.url_for(surface) is None:
            raise EnvironmentNotConfigured(
                f"environment {environment.value} has no configured URL for surface {surface.value}"
            )


def assert_stream_url(url: object, environment: Environment) -> None:
    """The streams URL of the transport must be the row URL (with or without the SDK suffix)."""
    expected = binance_client.ENVIRONMENT_ROWS[environment].ws_streams_url
    if expected is None:
        raise EnvironmentNotConfigured(
            f"environment {environment.value} has no configured URL for surface WS_STREAMS"
        )
    for accepted in (expected, expected + SDK_STREAMS_PATH_SUFFIX):
        try:
            assert_endpoint_url(url, accepted)
        except EndpointViolation:
            continue
        return
    raise EndpointViolation(
        f"{environment.value} WS_STREAMS transport endpoint does not match its environment row"
    )


# --------------------------------------------------------------------------- #
# Ports and guarded wrappers (the environment guard runs before every call).
# --------------------------------------------------------------------------- #


class OrderPort(Protocol):
    """The order and account surface of `BinanceUsdmAdapter` the smoke uses."""

    async def get_position_mode(self) -> PositionModeResult: ...

    async def snapshot_open_normal_orders(
        self, *, symbol: str | None = None
    ) -> list[OpenOrderSnapshot]: ...

    async def snapshot_open_algo_orders(
        self, *, symbol: str | None = None
    ) -> list[OpenAlgoOrderSnapshot]: ...

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[PositionSnapshot]: ...

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
    ) -> EntryPlacementResult: ...

    async def cancel_normal_order(self, *, symbol: str, orig_client_order_id: str) -> None: ...


class PublicReader(Protocol):
    """The public-data surface the smoke reads (`BinancePublicMarketData`)."""

    async def server_time(self) -> datetime: ...

    async def exchange_info(self) -> list[SymbolFilters]: ...

    async def mark_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = ...,
    ) -> list[Any]: ...


Guard = Callable[[], None]


class GuardedOrders:
    """Explicit delegation of the order port; the environment guard runs before each call."""

    def __init__(self, inner: OrderPort, guard: Guard) -> None:
        self._inner = inner
        self._guard = guard

    async def get_position_mode(self) -> PositionModeResult:
        self._guard()
        return await self._inner.get_position_mode()

    async def snapshot_open_normal_orders(
        self, *, symbol: str | None = None
    ) -> list[OpenOrderSnapshot]:
        self._guard()
        return await self._inner.snapshot_open_normal_orders(symbol=symbol)

    async def snapshot_open_algo_orders(
        self, *, symbol: str | None = None
    ) -> list[OpenAlgoOrderSnapshot]:
        self._guard()
        return await self._inner.snapshot_open_algo_orders(symbol=symbol)

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[PositionSnapshot]:
        self._guard()
        return await self._inner.snapshot_positions(symbol=symbol)

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
    ) -> EntryPlacementResult:
        self._guard()
        return await self._inner.place_entry(
            symbol=symbol,
            side=side,
            position_side=position_side,
            time_in_force=time_in_force,
            quantity=quantity,
            price=price,
            new_client_order_id=new_client_order_id,
        )

    async def cancel_normal_order(self, *, symbol: str, orig_client_order_id: str) -> None:
        self._guard()
        await self._inner.cancel_normal_order(
            symbol=symbol, orig_client_order_id=orig_client_order_id
        )


class GuardedPublic:
    """Explicit delegation of the public reader; the environment guard runs before each call."""

    def __init__(self, inner: BinancePublicMarketData, guard: Guard) -> None:
        self._inner = inner
        self._guard = guard

    async def server_time(self) -> datetime:
        self._guard()
        return await self._inner.server_time()

    async def exchange_info(self) -> list[SymbolFilters]:
        self._guard()
        return await self._inner.exchange_info()

    async def mark_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = MARK_LIMIT,
    ) -> list[Any]:
        self._guard()
        return list(await self._inner.mark_klines(symbol, interval, start_ms, end_ms, limit))


class ObservedListenKeys:
    """The listenKey port with the guard before each call and counts of what succeeded.

    The keys are held in memory for the log scan only (never written, never in a repr).
    """

    def __init__(self, inner: ListenKeyPort, *, guard: Guard, held: list[str]) -> None:
        self._inner = inner
        self._guard = guard
        self._held = held
        self.start_ok = 0
        self.keepalive_ok = 0
        self.close_ok = 0
        self.errors: list[str] = []

    def __repr__(self) -> str:
        return f"{type(self).__name__}(start_ok={self.start_ok})"

    @property
    def current_key(self) -> str | None:
        return self._held[-1] if self._held else None

    def _failed(self, call: str, exc: BaseException) -> None:
        if isinstance(exc, ListenKeyError):
            self.errors.append(f"{call}: {exc.category.value}")
        elif isinstance(exc, RestGateRefusal):
            self.errors.append(f"{call}: {exc.reason}")
        else:
            self.errors.append(f"{call}: {type(exc).__name__}")

    async def start(self) -> str:
        self._guard()
        try:
            key = await self._inner.start()
        except Exception as exc:
            self._failed("start", exc)
            raise
        self._held.append(key)
        self.start_ok += 1
        return key

    async def keepalive(self) -> None:
        self._guard()
        try:
            await self._inner.keepalive()
        except Exception as exc:
            self._failed("keepalive", exc)
            raise
        self.keepalive_ok += 1

    async def close(self) -> None:
        self._guard()
        try:
            await self._inner.close()
        except Exception as exc:
            self._failed("close", exc)
            raise
        self.close_ok += 1


class GuardedTransport:
    """`SdkUserDataTransport` with the environment guard before every connect and rebuild."""

    def __init__(self, inner: SdkUserDataTransport, guard: Guard) -> None:
        self._inner = inner
        self._guard = guard

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._inner!r})"

    async def connect(self, listen_key: str) -> None:
        self._guard()
        await self._inner.connect(listen_key)

    async def resubscribe(self, listen_key: str) -> None:
        self._guard()
        await self._inner.resubscribe(listen_key)

    async def rebuild(self, listen_key: str) -> None:
        self._guard()
        await self._inner.rebuild(listen_key)

    async def close(self) -> None:
        await self._inner.close()

    def set_message_sink(self, sink: Callable[[object], None]) -> None:
        self._inner.set_message_sink(sink)

    def set_connection_sink(self, sink: Callable[[str], None]) -> None:
        self._inner.set_connection_sink(sink)

    def private_connection_open(self) -> bool:
        return self._inner.private_connection_open()

    def diagnostics(self) -> object:
        return self._inner.diagnostics()


async def account_snapshot(account: OrderPort, symbol: str) -> dict[str, Any]:
    """Open normal orders, open algo orders and positions of `symbol` (REST is the truth)."""
    orders = await account.snapshot_open_normal_orders(symbol=symbol)
    algo = await account.snapshot_open_algo_orders(symbol=symbol)
    positions = await account.snapshot_positions(symbol=symbol)
    return {
        "open_orders": len(orders),
        "open_order_client_ids": sorted(order.client_order_id for order in orders),
        "open_algo_orders": len(algo),
        "positions": [
            {
                "symbol": position.symbol,
                "position_side": position.position_side,
                "position_amt": position.position_amt,
            }
            for position in positions
        ],
    }


def _is_flat(snapshot: Mapping[str, Any]) -> bool:
    return (
        snapshot.get("open_orders") == 0
        and snapshot.get("open_algo_orders") == 0
        and snapshot.get("positions") == []
    )


def _listen_key_of(response: object) -> str | None:
    try:
        data = response.data()  # type: ignore[attr-defined]
    except Exception:
        return None
    key = getattr(data, "listen_key", None)
    return key if isinstance(key, str) and key else None


async def direct_keepalive(
    rest_api: Any, gate: RestRateLimitGate, held: list[str]
) -> dict[str, Any]:
    """Observation f: one direct `PUT /fapi/v1/listenKey` after the stream's `DELETE`.

    The gate is checked first (a refusal propagates and nothing is sent); a 418 or 429 is
    recorded in the gate. The SDK error becomes its (http class, int code, category) only.
    """
    gate.check()
    try:
        response = await asyncio.to_thread(rest_api.keepalive_user_data_stream)
    except Exception as exc:
        facts = error_facts_from_exception(exc)
        category = classify(facts, CallKind.LISTEN_KEY)
        if category in _GATE_CATEGORIES:
            gate.record(category, facts.retry_after_seconds)
        return {
            "outcome": "ERROR",
            "http_class": facts.http_class.value,
            "code": facts.code,
            "category": category.value,
        }
    key = _listen_key_of(response)
    if key is not None:
        register_runtime_secret(key)
        held.append(key)
    return {"outcome": "NO_ERROR", "http_class": None, "code": None, "category": None}


# --------------------------------------------------------------------------- #
# The rig.
# --------------------------------------------------------------------------- #


@dataclass
class SmokeRig:
    """Everything the run needs, built for one mode (`build_live_rig`, `build_dry_run_rig`).

    `orders` is the order port and `account` the account reader (the same object in both
    rigs); `snapshot_provider` is the supervisor's REST snapshot. `clock` returns aware UTC
    time and `sleep` waits on that clock. `drop` forces an unsolicited transport drop of the
    private connection. `guard` is the environment guard. `context` scopes dry-run patches to
    the run; `driver` moves virtual time (dry run only).
    """

    real: bool
    clock: Callable[[], datetime]
    sleep: Callable[[float], Awaitable[None]]
    rest_gate: RestRateLimitGate
    listen_keys: ObservedListenKeys
    transport: GuardedTransport
    orders: OrderPort
    account: OrderPort
    public: PublicReader
    snapshot_provider: Callable[[], Awaitable[object]]
    drop: Callable[[], Awaitable[None]]
    private_connection_count: Callable[[], int]
    direct_keepalive: Callable[[], Awaitable[dict[str, Any]]]
    guard: Guard
    held_secrets: Callable[[], Mapping[str, Sequence[str]]]
    driver: Callable[[], Awaitable[None]] | None = None
    context: Callable[[], contextlib.AbstractContextManager[None]] = contextlib.nullcontext
    cleanup: Callable[[], None] = lambda: None
    fakes: Any = None


def _private_count(clients: Sequence[Any]) -> int:
    if not clients:
        return 0
    return sum(
        1 for connection in clients[-1].connections if connection.url_path == PRIVATE_URL_PATH
    )


def _drop_transport(connection: Any) -> None:
    """End the TCP connection beneath an SDK connection without a WebSocket close handshake.

    Closes the aiohttp response that backs the connection's websocket, like a network failure;
    the SDK's receive loop then takes its unsolicited-close branch. Copied from
    `scripts/paper_ws_smoke.py`; `tests/test_user_data_smoke_evidence.py` pins the attribute.
    """
    connection.websocket._response.close()


def _wall_clock() -> datetime:
    """The only wall-clock read of the tool (executed runs only)."""
    return datetime.now(UTC)


def build_live_rig(
    config: SmokeConfig,
    *,
    environ: Mapping[str, str],
    client_factory: Callable[..., Any] | None = None,
) -> SmokeRig:
    """The executed rig: credentials, the guarded SDK client and ONE shared REST gate.

    Constructed only in `--execute` mode. The SDK client comes from `build_sdk_client` with
    surfaces REST and WS_STREAMS and the ratified client limits; `assert_environment` runs
    before every stage and every call; the transport re-asserts the environment before every
    connect and rebuild. One `RestRateLimitGate` is passed to every REST holder.
    """
    from binance_sdk_derivatives_trading_usds_futures.websocket_streams import (  # noqa: PLC0415
        DerivativesTradingUsdsFuturesWebSocketStreams,
    )
    from src.adapters.binance_usdm import BinanceUsdmAdapter  # noqa: PLC0415

    environment = config.environment
    limits = config.limits
    require_configured(environment)
    spec = binance_client.credential_spec_for(environment)
    live_spec = binance_client.credential_spec_for(Environment.LIVE)
    credentials = binance_client.load_api_credentials(
        environ, spec=spec, repo_root=REPO_ROOT, refuse_if_present=(live_spec,)
    )
    factory = client_factory if client_factory is not None else binance_client.build_sdk_client
    bundle = factory(
        environment=environment,
        credentials=credentials,
        limits=limits.client,
        surfaces=SURFACES,
    )
    row = binance_client.ENVIRONMENT_ROWS[environment]
    stream_config = ConfigurationWebSocketStreams(
        stream_url=row.ws_streams_url,
        reconnect_delay=limits.stream.sdk_reconnect_delay_ms,
        reconnect_attempts=limits.stream.sdk_reconnect_attempts,
    )

    def guard() -> None:
        binance_client.assert_environment(bundle)
        assert_stream_url(stream_config.stream_url, environment)

    guard()
    gate = RestRateLimitGate(policy=limits.signed.rate_limit, clock=_wall_clock)
    adapter = BinanceUsdmAdapter(
        bundle.client, rest_gate=gate, signed_call_policy=limits.signed, clock=_wall_clock
    )
    public = BinancePublicMarketData(sdk_client=bundle.client, rest_gate=gate)
    held: list[str] = []
    listen_keys = ObservedListenKeys(
        SdkListenKeyPort(bundle.client.rest_api, rest_gate=gate), guard=guard, held=held
    )
    clients: list[Any] = []

    def ws_factory(configuration: ConfigurationWebSocketStreams) -> Any:
        client = DerivativesTradingUsdsFuturesWebSocketStreams(configuration)
        clients.append(client)
        return client

    transport = GuardedTransport(
        SdkUserDataTransport(stream_config, client_factory=ws_factory), guard=guard
    )
    install_sdk_noise_guard()
    orders = GuardedOrders(adapter, guard)

    async def snapshot() -> object:
        return await account_snapshot(orders, config.symbol)

    async def drop() -> None:
        private = [
            c
            for c in (clients[-1].connections if clients else [])
            if c.url_path == PRIVATE_URL_PATH
        ]
        if not private:
            raise RuntimeError("no private SDK connection to drop")
        _drop_transport(private[0])

    async def keepalive_after_delete() -> dict[str, Any]:
        guard()
        return await direct_keepalive(bundle.client.rest_api, gate, held)

    return SmokeRig(
        real=True,
        clock=_wall_clock,
        sleep=asyncio.sleep,
        rest_gate=gate,
        listen_keys=listen_keys,
        transport=transport,
        orders=orders,
        account=orders,
        public=GuardedPublic(public, guard),
        snapshot_provider=snapshot,
        drop=drop,
        private_connection_count=lambda: _private_count(clients),
        direct_keepalive=keepalive_after_delete,
        guard=guard,
        held_secrets=lambda: {
            "api_key": (credentials.api_key,),
            "api_secret": (credentials.api_secret,),
            "listen_key": tuple(held),
        },
    )


# --------------------------------------------------------------------------- #
# Dry run: SDK-shaped fakes on virtual time.
# --------------------------------------------------------------------------- #


async def _yield_to_loop() -> None:
    """One turn of the running loop (no `asyncio.sleep`)."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[None] = loop.create_future()
    loop.call_soon(future.set_result, None)
    await future


class VirtualClock:
    """Aware UTC virtual time: `sleep` waits for `drive` to move time to its deadline.

    `drive` lets in-loop work settle, then moves virtual time to the earliest pending sleeper
    and wakes it. Nothing here sleeps in real time.
    """

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("start must be timezone-aware")
        self._now = start
        self._sleepers: list[tuple[datetime, int, asyncio.Future[None]]] = []
        self._sequence = itertools.count()

    def now(self) -> datetime:
        return self._now

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            await _yield_to_loop()
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        deadline = self._now + timedelta(seconds=seconds)
        heapq.heappush(self._sleepers, (deadline, next(self._sequence), future))
        await future

    def _discard_done(self) -> None:
        while self._sleepers and self._sleepers[0][2].done():
            heapq.heappop(self._sleepers)

    async def drive(self) -> None:
        while True:
            for _ in range(SETTLE_ROUNDS):
                await _yield_to_loop()
            self._discard_done()
            if not self._sleepers:
                continue
            deadline, _, future = heapq.heappop(self._sleepers)
            if deadline > self._now:
                self._now = deadline
            future.set_result(None)


@dataclass(frozen=True)
class DryRunScenario:
    """What the fakes do in a dry run (test seam; the defaults are the passing run).

    `route_silent`: the fake order port places and cancels but no event reaches the SDK
    route. `server_offset_ms`: the fake server time minus the virtual host time.
    `end_state_not_flat`: a position remains after the order (manual cleanup case).
    `put_after_delete_code`: the SDK error code the fake answers to the PUT after the DELETE.
    """

    route_silent: bool = False
    server_offset_ms: int = 0
    end_state_not_flat: bool = False
    put_after_delete_code: int = -1125
    start_utc: datetime = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


# The fake exchange of the dry run (FAKE values, never Binance data).
DRY_RUN_FAKE_MARK = "60000.00"
DRY_RUN_FAKE_FILTERS: Mapping[str, str] = {
    "tick_size": "0.10",
    "step_size": "0.001",
    "min_qty": "0.001",
    "max_qty": "1000",
    "notional": "100",
    "multiplier_up": "1.0500",
    "multiplier_down": "0.9500",
    "multiplier_decimal": "4",
}
DRY_RUN_FAKE_FIRST_ORDER_ID = 8_100_000_001


def _load_fakes() -> Any:
    """Import the SDK-shaped fakes lazily: only the dry run loads test code."""
    from tests import userdata_fakes  # noqa: PLC0415

    return userdata_fakes


def _load_frames() -> Any:
    from tests.support import userdata_frames  # noqa: PLC0415

    return userdata_frames


class _DryRunResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def data(self) -> Any:
        return self._payload


class DryRunPublicRest:
    """SDK-shaped fake of the three public REST methods the smoke reads (FAKE values)."""

    def __init__(self, clock: VirtualClock, scenario: DryRunScenario, symbol: str) -> None:
        self._clock = clock
        self._scenario = scenario
        self._symbol = symbol
        self.calls: dict[str, int] = {
            "check_server_time": 0,
            "exchange_information": 0,
            "mark_price_kline_candlestick_data": 0,
        }

    def check_server_time(self) -> _DryRunResponse:
        from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (  # noqa: PLC0415
            CheckServerTimeResponse,
        )

        self.calls["check_server_time"] += 1
        host_ms = (self._clock.now() - _EPOCH) // _ONE_MS
        return _DryRunResponse(
            CheckServerTimeResponse(server_time=host_ms + self._scenario.server_offset_ms)
        )

    def exchange_information(self) -> _DryRunResponse:
        from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (  # noqa: PLC0415
            ExchangeInformationResponse,
            ExchangeInformationResponseSymbolsInner,
            ExchangeInformationResponseSymbolsInnerFiltersInner,
        )

        self.calls["exchange_information"] += 1
        values = DRY_RUN_FAKE_FILTERS
        filters = [
            ExchangeInformationResponseSymbolsInnerFiltersInner(
                filter_type="PRICE_FILTER", tick_size=values["tick_size"]
            ),
            ExchangeInformationResponseSymbolsInnerFiltersInner(
                filter_type="LOT_SIZE",
                step_size=values["step_size"],
                min_qty=values["min_qty"],
                max_qty=values["max_qty"],
            ),
            ExchangeInformationResponseSymbolsInnerFiltersInner(
                filter_type="MIN_NOTIONAL", notional=values["notional"]
            ),
            ExchangeInformationResponseSymbolsInnerFiltersInner(
                filter_type="PERCENT_PRICE",
                multiplier_up=values["multiplier_up"],
                multiplier_down=values["multiplier_down"],
                multiplier_decimal=values["multiplier_decimal"],
            ),
        ]
        symbol = ExchangeInformationResponseSymbolsInner(
            symbol=self._symbol,
            contract_type="PERPETUAL",
            status=TRADING_STATUS,
            base_asset=self._symbol.removesuffix("USDT") or self._symbol,
            quote_asset="USDT",
            margin_asset="USDT",
            filters=filters,
        )
        return _DryRunResponse(ExchangeInformationResponse(symbols=[symbol]))

    def mark_price_kline_candlestick_data(self, **_kwargs: Any) -> _DryRunResponse:
        self.calls["mark_price_kline_candlestick_data"] += 1
        open_ms = (self._clock.now() - _EPOCH) // _ONE_MS
        mark = DRY_RUN_FAKE_MARK
        row = [open_ms, mark, mark, mark, mark, "0", open_ms + 59_999, "0", 1, "0", "0", "0"]
        return _DryRunResponse([row])


class _DryRunSdk:
    """The `rest_api` holder `BinancePublicMarketData` reads."""

    def __init__(self, rest_api: Any) -> None:
        self.rest_api = rest_api


class DryRunOrders:
    """The fake order port: one book of open orders; placement and cancel emit SDK frames.

    Each call consults the shared gate first (a refused call is not counted) and is recorded
    in `calls`. Placement and cancel hand a frame to `emit` (the SDK `user_data` route) unless
    the scenario keeps the route silent.
    """

    def __init__(
        self,
        *,
        gate: RestRateLimitGate,
        clock: VirtualClock,
        scenario: DryRunScenario,
        emit: Callable[..., None],
    ) -> None:
        self._gate = gate
        self._clock = clock
        self._scenario = scenario
        self._emit = emit
        self.calls: list[str] = []
        self._open: dict[str, OpenOrderSnapshot] = {}
        self._placed = False
        self._next_id = DRY_RUN_FAKE_FIRST_ORDER_ID

    def _enter(self, name: str) -> None:
        self._gate.check()
        self.calls.append(name)

    async def get_position_mode(self) -> PositionModeResult:
        self._enter("get_position_mode")
        return PositionModeResult(dual_side_position=False)

    async def snapshot_open_normal_orders(
        self, *, symbol: str | None = None
    ) -> list[OpenOrderSnapshot]:
        self._enter("snapshot_open_normal_orders")
        return [o for o in self._open.values() if symbol is None or o.symbol == symbol]

    async def snapshot_open_algo_orders(
        self, *, symbol: str | None = None
    ) -> list[OpenAlgoOrderSnapshot]:
        self._enter("snapshot_open_algo_orders")
        return []

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[PositionSnapshot]:
        self._enter("snapshot_positions")
        if not (self._scenario.end_state_not_flat and self._placed):
            return []
        return [
            PositionSnapshot(
                symbol=symbol or "",
                position_side=POSITION_SIDE_ONE_WAY,
                position_amt=Decimal(DRY_RUN_FAKE_FILTERS["min_qty"]),
                entry_price=Decimal(DRY_RUN_FAKE_MARK),
                break_even_price=Decimal(DRY_RUN_FAKE_MARK),
                mark_price=Decimal(DRY_RUN_FAKE_MARK),
                unrealized_profit=Decimal("0"),
                liquidation_price=None,
                notional=None,
                margin_asset="USDT",
                update_time_utc=self._clock.now(),
            )
        ]

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
    ) -> EntryPlacementResult:
        self._enter("place_entry")
        order_id = str(self._next_id)
        self._next_id += 1
        now = self._clock.now()
        self._open[new_client_order_id] = OpenOrderSnapshot(
            symbol=symbol,
            client_order_id=new_client_order_id,
            exchange_order_id=order_id,
            side=side,
            position_side=position_side,
            order_type="LIMIT",
            time_in_force=time_in_force,
            status=EXECUTION_NEW,
            quantity=quantity,
            price=price,
            stop_price=None,
            reduce_only=False,
            close_position=False,
            working_type=None,
            price_protect=None,
            update_time_utc=now,
        )
        self._placed = True
        if not self._scenario.route_silent:
            self._emit(self._open[new_client_order_id], EXECUTION_NEW)
        return EntryPlacementResult(
            symbol=symbol,
            client_order_id=new_client_order_id,
            exchange_order_id=order_id,
            side=side,
            position_side=position_side,
            order_type="LIMIT",
            time_in_force=time_in_force,
            status=EXECUTION_NEW,
            quantity=quantity,
            price=price,
            update_time_utc=now,
        )

    async def cancel_normal_order(self, *, symbol: str, orig_client_order_id: str) -> None:
        self._enter("cancel_normal_order")
        order = self._open.pop(orig_client_order_id, None)
        if order is not None and not self._scenario.route_silent:
            self._emit(order, EXECUTION_CANCELED)


@dataclass
class DryRunHandles:
    """The fakes of a dry run, for tests."""

    clock: VirtualClock
    clients: list[Any]
    rest_userdata: Any
    public_rest: DryRunPublicRest
    orders: DryRunOrders
    guard_calls: list[int]


@contextlib.contextmanager
def _dry_run_patches() -> Iterator[None]:
    """Scope two process-wide swaps to the dry run and restore them afterwards.

    A fresh SDK stream map (research P6, P18), and SDK REST calls of the fakes run inline
    instead of in a worker thread, so virtual time alone orders the run.
    """
    saved_map = sdk_websocket.global_stream_connections
    saved_to_thread = asyncio.to_thread

    async def _inline(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    sdk_websocket.global_stream_connections = StreamConnectionsMap()  # type: ignore[no-untyped-call]
    asyncio.to_thread = _inline
    try:
        yield
    finally:
        asyncio.to_thread = saved_to_thread
        sdk_websocket.global_stream_connections = saved_map


def build_dry_run_rig(config: SmokeConfig, scenario: DryRunScenario | None = None) -> SmokeRig:
    """The dry rig: SDK-shaped fakes, virtual time and ONE shared REST gate.

    The listenKey port, the transport, the adapter and the supervisor are the real project
    classes; the WebSocket client, the listenKey REST object, the public REST object and the
    order port are fakes. The real `BinancePublicMarketData` reads the fake public REST object
    through the same gate. Fakes are loaded lazily; nothing reads credentials.
    """
    scenario = scenario if scenario is not None else DryRunScenario()
    fakes = _load_fakes()
    frames = _load_frames()
    from binance_common.errors import BadRequestError  # noqa: PLC0415
    from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.user_data_stream_events_response import (  # noqa: E501, PLC0415
        UserDataStreamEventsResponse,
    )

    clock = VirtualClock(scenario.start_utc)
    guard_calls: list[int] = []

    def guard() -> None:
        guard_calls.append(1)

    gate = RestRateLimitGate(policy=config.limits.signed.rate_limit, clock=clock.now)
    put_after_delete_code = scenario.put_after_delete_code

    class _DryRunRestUserData(fakes.FakeRestUserDataApi):  # type: ignore[misc, name-defined]
        """The listenKey REST fake: after the DELETE the next PUT answers the scenario code."""

        def close_user_data_stream(self) -> Any:
            response = super().close_user_data_stream()
            self.fail_next(
                "keepalive_user_data_stream",
                BadRequestError("FAKE: listenKey closed", put_after_delete_code),
            )
            return response

    rest_userdata = _DryRunRestUserData()
    held: list[str] = []
    listen_keys = ObservedListenKeys(
        SdkListenKeyPort(rest_userdata, rest_gate=gate), guard=guard, held=held
    )
    clients: list[Any] = []

    def ws_factory(_configuration: Any) -> Any:
        client = fakes.FakeUserDataWsClient()
        clients.append(client)
        return client

    transport = GuardedTransport(
        SdkUserDataTransport(
            ConfigurationWebSocketStreams(stream_url=binance_client.INERT_WS_URL),
            client_factory=ws_factory,
        ),
        guard=guard,
    )

    def emit(order: OpenOrderSnapshot, execution: str) -> None:
        """Route a frame the way the SDK receive loop does: `parse_user_event`, then the
        callbacks of the stream the listenKey is mapped to."""
        key = listen_keys.current_key
        if key is None or not clients:
            return
        moment_ms = (clock.now() - _EPOCH) // _ONE_MS
        frame = frames.order_trade_update_frame(
            event_overrides={"E": moment_ms, "T": moment_ms},
            s=order.symbol,
            c=order.client_order_id,
            S=order.side,
            o="LIMIT",
            f=order.time_in_force,
            q=format(order.quantity, "f"),
            p=format(order.price, "f") if order.price is not None else "0",
            ap="0",
            x=execution,
            X=execution,
            i=int(order.exchange_order_id),
            l="0",
            z="0",
            L="0",
            n="0",
            T=moment_ms,
            t=0,
            ps=order.position_side,
        )
        parse = getattr(sdk_websocket, _PARSE_USER_EVENT)
        clients[-1].emit_user_event(key, parse(frame, UserDataStreamEventsResponse))

    orders = DryRunOrders(gate=gate, clock=clock, scenario=scenario, emit=emit)
    guarded_orders = GuardedOrders(orders, guard)
    public_rest = DryRunPublicRest(clock, scenario, config.symbol)
    public = BinancePublicMarketData(
        sdk_client=_DryRunSdk(public_rest),  # type: ignore[arg-type]
        rest_gate=gate,
    )

    async def snapshot() -> object:
        return await account_snapshot(guarded_orders, config.symbol)

    async def drop() -> None:
        if not clients:
            raise RuntimeError("no private SDK connection to drop")
        clients[-1].simulate_unsolicited_close(PRIVATE_URL_PATH)

    async def keepalive_after_delete() -> dict[str, Any]:
        guard()
        return await direct_keepalive(rest_userdata, gate, held)

    return SmokeRig(
        real=False,
        clock=clock.now,
        sleep=clock.sleep,
        rest_gate=gate,
        listen_keys=listen_keys,
        transport=transport,
        orders=guarded_orders,
        account=guarded_orders,
        public=GuardedPublic(public, guard),
        snapshot_provider=snapshot,
        drop=drop,
        private_connection_count=lambda: _private_count(clients),
        direct_keepalive=keepalive_after_delete,
        guard=guard,
        held_secrets=lambda: {"listen_key": tuple(held)},
        driver=clock.drive,
        context=_dry_run_patches,
        fakes=DryRunHandles(
            clock=clock,
            clients=clients,
            rest_userdata=rest_userdata,
            public_rest=public_rest,
            orders=orders,
            guard_calls=guard_calls,
        ),
    )


# --------------------------------------------------------------------------- #
# The far order (pure Decimal arithmetic on the exchange filters).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FarOrder:
    mark_price: Decimal
    price: Decimal
    quantity: Decimal
    notional: Decimal


def far_order_price(mark: Decimal, fraction: Decimal, tick: Decimal) -> Decimal:
    """The floor of `mark * fraction` on the tick grid."""
    steps = (mark * fraction / tick).to_integral_value(rounding=ROUND_FLOOR)
    return steps * tick


def plan_far_order(
    filters: SymbolFilters, *, mark: Decimal, quantity: Decimal, fraction: Decimal
) -> tuple[FarOrder, list[str]]:
    """The far BUY and every reason it must not be sent (an empty list: it may be sent)."""
    price = far_order_price(mark, fraction, filters.price_tick_size)
    order = FarOrder(mark_price=mark, price=price, quantity=quantity, notional=price * quantity)
    problems: list[str] = []
    if filters.status != TRADING_STATUS:
        problems.append("the symbol is not TRADING")
    if price <= 0:
        problems.append("the far price is not positive")
    down = filters.percent_price_multiplier_down
    up = filters.percent_price_multiplier_up
    if down is None or up is None:
        problems.append("the symbol publishes no PERCENT_PRICE band (unknown: fail closed)")
    elif price < mark * down or price > mark * up:
        problems.append("the far price is outside the PERCENT_PRICE band")
    if quantity < filters.min_quantity:
        problems.append("the quantity is below the minimum quantity")
    if filters.max_quantity is not None and quantity > filters.max_quantity:
        problems.append("the quantity is above the maximum quantity")
    if quantity % filters.quantity_step_size != 0:
        problems.append("the quantity is not on the step grid")
    if order.notional < filters.min_notional:
        problems.append("the notional is below the minimum notional")
    return order, problems


# --------------------------------------------------------------------------- #
# Log capture (acceptance g).
# --------------------------------------------------------------------------- #


class _Tee(io.TextIOBase):
    def __init__(self, primary: Any, buffer: io.StringIO) -> None:
        self._primary = primary
        self._buffer = buffer

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self._buffer.write(text)
        self._primary.write(text)
        return len(text)

    def flush(self) -> None:
        self._primary.flush()


@contextlib.contextmanager
def capture_output(buffer: io.StringIO) -> Iterator[None]:
    """Copy stdout, stderr (structlog prints there) and every root log record into `buffer`.

    The log handler carries the project's `RedactingFilter`, like every configured handler.
    """
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        with (
            contextlib.redirect_stdout(_Tee(sys.stdout, buffer)),
            contextlib.redirect_stderr(_Tee(sys.stderr, buffer)),
        ):
            yield
    finally:
        root.removeHandler(handler)


SECRET_KINDS: tuple[str, ...] = ("api_key", "api_secret", "listen_key")


def scan_for_secrets(texts: Sequence[str], held: Mapping[str, Sequence[str]]) -> dict[str, int]:
    """How often each held secret kind and a signed-request signature occur (counts only).

    `held` maps "api_key", "api_secret" and "listen_key" to the values the run holds; the
    signature is the shape `signature=` followed by 64 hex characters.
    """
    findings = dict.fromkeys((*SECRET_KINDS, "signature"), 0)
    for text in texts:
        findings["signature"] += len(_SIGNATURE_SHAPE.findall(text))
        for kind in SECRET_KINDS:
            for value in held.get(kind, ()):
                if value:
                    findings[kind] += text.count(value)
    return findings


# --------------------------------------------------------------------------- #
# The run.
# --------------------------------------------------------------------------- #


def _step_record(name: str, status: str, detail: str) -> dict[str, Any]:
    return {"name": name, "status": status, "detail": detail}


def _ms_between(start: datetime, end: datetime) -> int:
    return (end - start) // _ONE_MS


def _contains_in_order(sequence: Sequence[str], wanted: Sequence[str]) -> bool:
    position = 0
    for item in sequence:
        if position < len(wanted) and item == wanted[position]:
            position += 1
    return position == len(wanted)


def _utc_stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _describe(exc: BaseException) -> str:
    """Type name plus the exchange's int code when the SDK carried one (never message text)."""
    if isinstance(exc, ListenKeyError):
        return f"{type(exc).__name__}: {exc.category.value}"
    if isinstance(exc, RestGateRefusal):
        return f"{type(exc).__name__}: {exc.reason}"
    code = error_facts_from_exception(exc).code
    return type(exc).__name__ if code is None else f"{type(exc).__name__} (code {code})"


class SmokeRun:
    """One run of the smoke over a rig; `run()` never raises for a step failure."""

    def __init__(self, config: SmokeConfig, rig: SmokeRig, secrets: Sequence[str] = ()) -> None:
        self.config = config
        self.rig = rig
        self.symbol = config.symbol
        self.started_at = rig.clock()
        self.client_order_id = f"{CLIENT_ID_PREFIX}{_utc_stamp(self.started_at)}"
        self.steps: dict[str, dict[str, Any]] = {
            name: _step_record(name, NOT_RUN, "not reached") for name in STEP_NAMES
        }
        self.changed = asyncio.Event()
        self.state_log: list[tuple[StreamState, str, datetime]] = []
        self.events: list[dict[str, Any]] = []
        self.order_executions: list[str] = []
        self.snapshot_times: list[datetime] = []
        self.stream_failures: list[str] = []
        self.failures: list[dict[str, str]] = []
        self.supervisor: UserDataSupervisor | None = None
        self.adapter: UserDataAdapter | None = None
        self.position_side = POSITION_SIDE_ONE_WAY
        self.far_order: FarOrder | None = None
        self.order_attempted = False
        self.order_cancel_confirmed = False
        self.aborted = False
        self.crashed = False
        self.sdk_route_delivery = ROUTE_NOT_RUN
        self.drift: dict[str, Any] = {"status": NOT_RUN}
        self.symbol_filters: dict[str, Any] = {"status": NOT_RUN}
        self.order_record: dict[str, Any] = {"status": NOT_RUN}
        self.account_before: dict[str, Any] = {"status": NOT_RUN}
        self.account_after: dict[str, Any] = {"status": NOT_RUN}
        self.end_state = END_NOT_RUN
        self.listen_key: dict[str, Any] = {"status": NOT_RUN}
        self.subscription: dict[str, Any] = {"status": NOT_RUN}
        self.forced_drop: dict[str, Any] = {"status": NOT_RUN}
        self.delete_then_put: dict[str, Any] = {"status": NOT_RUN}
        self.log_scan: dict[str, Any] = {"status": NOT_RUN}
        self.fixtures: dict[str, Any] = {"status": NOT_RUN}
        self.raw_frames: list[object] = []
        self.finished_at: datetime | None = None

    # -- recording ----------------------------------------------------------- #

    def _set(self, name: str, status: str, detail: str) -> None:
        self.steps[name] = _step_record(name, status, detail)

    def _failure(self, step: str, exc: BaseException) -> None:
        self.failures.append({"step": step, "error": _describe(exc)})

    def _changed(self) -> None:
        self.changed.set()

    def on_state_change(self, state: StreamState, reason: str) -> None:
        self.state_log.append((state, reason, self.rig.clock()))
        self._changed()

    def on_event(self, event: TrustedEvent) -> None:
        outcome = event.outcome
        record: dict[str, Any] = {
            "after_gap": event.after_gap,
            "connection_epoch": event.connection_epoch,
            "received_at_utc": event.received_at_utc,
        }
        if isinstance(outcome, OrderUpdateEvent):
            ours = outcome.client_order_id == self.client_order_id
            record.update(
                {
                    "event_type": "ORDER_TRADE_UPDATE",
                    "execution_type": outcome.execution_type,
                    "order_status": outcome.order_status,
                    "symbol": outcome.symbol,
                    "is_smoke_order": ours,
                    "client_order_id": outcome.client_order_id if ours else None,
                }
            )
            if ours:
                self.order_executions.append(outcome.execution_type)
        elif isinstance(outcome, StreamAnomaly):
            record.update({"event_type": "ANOMALY", "anomaly_kind": outcome.kind.value})
        else:
            record.update({"event_type": type(outcome).__name__})
        self.events.append(record)
        self._changed()

    def on_snapshot(self, snapshot: StreamSnapshot, epoch: int) -> None:
        del epoch
        self.snapshot_times.append(snapshot.taken_at_utc)
        self._changed()

    def on_failure(self, reason: str) -> None:
        self.stream_failures.append(reason)
        self._changed()

    # -- waiting ------------------------------------------------------------- #

    async def wait_until(self, predicate: Callable[[], bool], timeout_seconds: int) -> bool:
        """True once `predicate` holds, False after `timeout_seconds` on the rig's clock."""
        if predicate():
            return True
        deadline = asyncio.ensure_future(self.rig.sleep(timeout_seconds))
        try:
            while not predicate() and not deadline.done():
                self.changed.clear()
                waiter = asyncio.ensure_future(self.changed.wait())
                try:
                    await asyncio.wait((waiter, deadline), return_when=asyncio.FIRST_COMPLETED)
                finally:
                    waiter.cancel()
                    await asyncio.gather(waiter, return_exceptions=True)
        finally:
            if not deadline.done():
                deadline.cancel()
            await asyncio.gather(deadline, return_exceptions=True)
        return predicate()

    async def bounded[T](self, call: Callable[[], Awaitable[T]], timeout_seconds: int) -> T:
        """`call()` raced against `timeout_seconds` on the rig's clock (`_Bounded` on timeout)."""
        work = asyncio.ensure_future(call())
        timer = asyncio.ensure_future(self.rig.sleep(timeout_seconds))
        try:
            done, _ = await asyncio.wait((work, timer), return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (work, timer):
                if not task.done():
                    task.cancel()
            await asyncio.gather(work, timer, return_exceptions=True)
        if work in done:
            return work.result()
        raise _Bounded("the step did not finish within cleanup_timeout_seconds")

    # -- the steps ----------------------------------------------------------- #

    def _clock_ms(self) -> int:
        return (self.rig.clock() - _EPOCH) // _ONE_MS

    async def preflight(self) -> None:
        name = "preflight"
        limits = self.config.limits
        try:
            self.rig.guard()
        except Exception as exc:
            self._failure(name, exc)
            self._set(name, FAILED, f"environment guard refused: {type(exc).__name__}")
            raise _Abort from None
        verdict = await measure_clock_drift(
            server_time=self.rig.public.server_time,
            clock_ms=self._clock_ms,
            now_utc=self.rig.clock,
            limits=limits.drift,
        )
        ok = not verdict.measurement_failed and verdict.within_limits
        self.drift = {
            "status": PASSED if ok else FAILED,
            "offset_ms": verdict.offset_ms,
            "uncertainty_ms": verdict.uncertainty_ms,
            "within_limits": verdict.within_limits,
            "measurement_failed": verdict.measurement_failed,
            "failure_type": verdict.failure_type,
            "measured_at_utc": verdict.measured_at_utc,
            "ahead_limit_ms": limits.drift.ahead_limit_ms,
            "behind_limit_ms": limits.drift.behind_limit_ms,
        }
        if verdict.measurement_failed:
            self._set(name, FAILED, f"server-time measurement failed: {verdict.failure_type}")
            raise _Abort
        if not verdict.within_limits:
            self._set(name, FAILED, "server-time drift is outside the ratified drift limits")
            raise _Abort
        try:
            all_filters = await self.rig.public.exchange_info()
            marks = await self.rig.public.mark_klines(self.symbol, MARK_INTERVAL, limit=MARK_LIMIT)
        except Exception as exc:
            self._failure(name, exc)
            self._set(name, FAILED, f"exchange filters or mark price unreadable: {_describe(exc)}")
            raise _Abort from None
        filters = next((f for f in all_filters if f.symbol == self.symbol), None)
        if filters is None or not marks:
            self._set(name, FAILED, "the symbol or its mark price is not published")
            raise _Abort
        order_limits = self.config.order_limits
        far, problems = plan_far_order(
            filters,
            mark=marks[-1].close,
            quantity=order_limits.quantity,
            fraction=order_limits.far_price_fraction,
        )
        self.symbol_filters = {
            "status": PASSED if not problems else FAILED,
            "symbol_status": filters.status,
            "price_tick_size": filters.price_tick_size,
            "quantity_step_size": filters.quantity_step_size,
            "min_quantity": filters.min_quantity,
            "max_quantity": filters.max_quantity,
            "min_notional": filters.min_notional,
            "percent_price_multiplier_up": filters.percent_price_multiplier_up,
            "percent_price_multiplier_down": filters.percent_price_multiplier_down,
        }
        self.order_record = {
            "status": NOT_RUN,
            "client_order_id": self.client_order_id,
            "side": ORDER_SIDE,
            "type": "LIMIT",
            "time_in_force": ORDER_TIME_IN_FORCE,
            "mark_price": far.mark_price,
            "far_price_fraction": order_limits.far_price_fraction,
            "price": far.price,
            "quantity": far.quantity,
            "notional": far.notional,
        }
        if problems:
            self._set(name, FAILED, "far order refused: " + "; ".join(problems))
            raise _Abort
        self.far_order = far
        self._set(name, PASSED, "limits loaded; environment guard; drift within limits; filters")

    async def account_before_step(self) -> None:
        name = "account_before"
        try:
            mode = await self.rig.account.get_position_mode()
            state = await account_snapshot(self.rig.account, self.symbol)
        except Exception as exc:
            self._failure(name, exc)
            self._set(name, FAILED, f"account state unreadable: {_describe(exc)}")
            raise _Abort from None
        self.position_side = (
            POSITION_SIDE_HEDGE_LONG if mode.dual_side_position else POSITION_SIDE_ONE_WAY
        )
        flat = _is_flat(state)
        self.account_before = {
            "status": PASSED if flat else FAILED,
            "dual_side_position": mode.dual_side_position,
            **state,
        }
        if not flat:
            self._set(name, FAILED, "the symbol is not flat before the smoke: nothing was sent")
            raise _Abort
        self._set(name, PASSED, "flat: no open order, no algo order, no position")

    async def stream_start(self) -> None:
        name = "stream_start"
        limits = self.config.limits.stream
        try:
            self.rig.guard()
            self.adapter = UserDataAdapter(
                transport=self.rig.transport,
                listen_keys=self.rig.listen_keys,
                limits=limits,
                clock=self.rig.clock,
            )
            self.supervisor = UserDataSupervisor(
                adapter=self.adapter,
                limits=limits,
                clock=self.rig.clock,
                sleep=self.rig.sleep,
                rest_gate=self.rig.rest_gate,
                snapshot_provider=self.rig.snapshot_provider,
                on_state_change=self.on_state_change,
                on_event=self.on_event,
                on_snapshot=self.on_snapshot,
                on_failure=self.on_failure,
            )
            await self.supervisor.start()
        except Exception as exc:
            self._failure(name, exc)
            self._set(name, FAILED, f"the stream did not start: {_describe(exc)}")
        live = self.supervisor is not None and self.supervisor.state is StreamState.LIVE
        started = self.rig.listen_keys.start_ok >= 1
        private = self.rig.private_connection_count()
        diagnostics = self.rig.transport.diagnostics()
        subscribed = getattr(diagnostics, "subscribed", False) is True
        self.listen_key = {
            "status": PASSED if started else FAILED,
            "start_calls_ok": self.rig.listen_keys.start_ok,
            "errors": list(self.rig.listen_keys.errors),
        }
        self.subscription = {
            "status": PASSED if live and subscribed and private >= 1 else FAILED,
            "private_connection_count": private,
            "connection_count": getattr(diagnostics, "connection_count", None),
            "subscribed": subscribed,
            "transport": "sdk",
        }
        if live and started and subscribed and private >= 1:
            self._set(name, PASSED, "listenKey started; SDK user_data subscribed; stream LIVE")
        elif self.steps[name]["status"] != FAILED:
            reasons = ", ".join(self.stream_failures) or "no failure reported"
            self._set(name, FAILED, f"the stream is not LIVE ({reasons})")

    async def keepalive_step(self) -> None:
        name = "keepalive"
        assert self.adapter is not None
        try:
            self.rig.guard()
            await self.adapter.keepalive()
        except Exception as exc:
            self._failure(name, exc)
            self._set(name, FAILED, f"keepalive failed: {_describe(exc)}")
            return
        self._set(name, PASSED, "PUT /fapi/v1/listenKey returned")

    async def order_steps(self) -> None:
        far = self.far_order
        assert far is not None
        wait = self.config.order_limits.event_wait_seconds
        assert wait is not None
        placed = False
        self.order_attempted = True
        try:
            result = await self.rig.orders.place_entry(
                symbol=self.symbol,
                side=ORDER_SIDE,
                position_side=self.position_side,
                time_in_force=ORDER_TIME_IN_FORCE,
                quantity=far.quantity,
                price=far.price,
                new_client_order_id=self.client_order_id,
            )
        except Exception as exc:
            self._failure("order_place", exc)
            self._set("order_place", FAILED, f"placement failed: {_describe(exc)}")
            self.order_record["status"] = FAILED
        else:
            placed = True
            self.order_record.update(
                {
                    "status": PASSED,
                    "position_side": self.position_side,
                    "exchange_order_id": result.exchange_order_id,
                    "exchange_status": result.status,
                }
            )
            self._set("order_place", PASSED, "one far LIMIT BUY placed")
        new_seen = False
        if placed:
            new_seen = await self.wait_until(lambda: EXECUTION_NEW in self.order_executions, wait)
            self._set(
                "order_new_event",
                PASSED if new_seen else FAILED,
                "typed ORDER_TRADE_UPDATE NEW delivered through the SDK user_data route"
                if new_seen
                else "no typed NEW event within event_wait_seconds (SDK route silent)",
            )
        else:
            self._set("order_new_event", NOT_RUN, "the placement failed")
        await self.cancel_step()
        canceled_seen = False
        if placed:
            canceled_seen = await self.wait_until(
                lambda: EXECUTION_CANCELED in self.order_executions, wait
            )
            self._set(
                "order_canceled_event",
                PASSED if canceled_seen else FAILED,
                "typed ORDER_TRADE_UPDATE CANCELED delivered through the SDK user_data route"
                if canceled_seen
                else "no typed CANCELED event within event_wait_seconds (SDK route silent)",
            )
            self.sdk_route_delivery = ROUTE_PASS if new_seen and canceled_seen else ROUTE_FAIL
        else:
            self._set("order_canceled_event", NOT_RUN, "the placement failed")

    async def cancel_step(self) -> None:
        name = "order_cancel"
        try:
            await self.rig.orders.cancel_normal_order(
                symbol=self.symbol, orig_client_order_id=self.client_order_id
            )
        except Exception as exc:
            self._failure(name, exc)
            self._set(name, FAILED, f"cancel failed: {_describe(exc)}")
            return
        self.order_cancel_confirmed = True
        self._set(name, PASSED, "the far order was cancelled (or was already absent)")

    def _recovered_after(self, marker: int) -> bool:
        states = [state.value for state, _, _ in self.state_log[marker:]]
        return _contains_in_order(states, (StreamState.UNKNOWN.value, StreamState.LIVE.value))

    async def forced_drop_step(self) -> None:
        name = "forced_drop"
        supervisor = self.supervisor
        if supervisor is None or supervisor.state is not StreamState.LIVE:
            self._set(name, NOT_RUN, "the stream is not LIVE")
            return
        wait = self.config.order_limits.event_wait_seconds
        assert wait is not None
        marker = len(self.state_log)
        snapshots_before = len(self.snapshot_times)
        dropped_at = self.rig.clock()
        try:
            self.rig.guard()
            await self.rig.drop()
        except Exception as exc:
            self._failure(name, exc)
            self._set(name, FAILED, f"the transport drop failed: {_describe(exc)}")
            self.forced_drop = {"status": FAILED, "dropped_at_utc": dropped_at}
            return
        recovered = await self.wait_until(lambda: self._recovered_after(marker), wait)
        after = self.state_log[marker:]
        sequence = [state.value for state, _, _ in after]
        unknown_at = next((at for state, _, at in after if state is StreamState.UNKNOWN), None)
        live_at = None
        if unknown_at is not None:
            live_at = next(
                (at for state, _, at in after if state is StreamState.LIVE and at >= unknown_at),
                None,
            )
        gap_ms = _ms_between(unknown_at, live_at) if unknown_at and live_at else None
        snapshots_after = len(self.snapshot_times) - snapshots_before
        proven = (
            recovered
            and _contains_in_order(
                sequence,
                (StreamState.UNKNOWN.value, StreamState.SYNCING.value, StreamState.LIVE.value),
            )
            and snapshots_after >= 1
        )
        self.forced_drop = {
            "status": PASSED if proven else FAILED,
            "method": "transport-drop",
            "dropped_at_utc": dropped_at,
            "state_sequence_after_drop": [
                {"state": state.value, "reason": reason, "at_utc": at}
                for state, reason, at in after
            ],
            "snapshot_count_after_drop": snapshots_after,
            "gap_ms": gap_ms,
        }
        self._set(
            name,
            PASSED if proven else FAILED,
            "UNKNOWN, snapshot, LIVE after the drop"
            if proven
            else "the stream did not recover through a snapshot within event_wait_seconds",
        )

    async def cleanup(self) -> None:
        cleanup_seconds = self.config.order_limits.cleanup_timeout_seconds
        if self.order_attempted and not self.order_cancel_confirmed:
            try:
                await self.bounded(self.cancel_step, cleanup_seconds)
            except Exception as exc:
                self._failure("order_cancel", exc)
                self._set("order_cancel", FAILED, f"cleanup cancel failed: {_describe(exc)}")
        if self.steps["account_before"]["status"] == PASSED:
            await self.account_after_step(cleanup_seconds)
        if self.supervisor is not None:
            await self.stop_step()

    async def account_after_step(self, cleanup_seconds: int) -> None:
        name = "account_after"
        try:
            state = await self.bounded(
                lambda: account_snapshot(self.rig.account, self.symbol), cleanup_seconds
            )
        except Exception as exc:
            self._failure(name, exc)
            self.end_state = END_MANUAL_CLEANUP
            self.account_after = {"status": FAILED}
            self._set(name, FAILED, f"{END_MANUAL_CLEANUP}: account state unreadable")
            return
        flat = _is_flat(state)
        self.end_state = END_FLAT if flat else END_MANUAL_CLEANUP
        self.account_after = {"status": PASSED if flat else FAILED, **state}
        if flat:
            self._set(name, PASSED, "flat: no open order, no algo order, no position")
        else:
            self._set(name, FAILED, f"{END_MANUAL_CLEANUP}: the symbol is not flat")
            print(
                f"OPERATOR: {END_MANUAL_CLEANUP} on {self.symbol}: check open orders and the "
                "position in the Demo account and clean them up by hand.",
                file=sys.stderr,
            )

    async def stop_step(self) -> None:
        name = "stop_and_delete_then_put"
        supervisor = self.supervisor
        assert supervisor is not None
        await supervisor.stop(close_listen_key=True)
        closed = self.rig.listen_keys.close_ok >= 1
        self.listen_key["close_calls_ok"] = self.rig.listen_keys.close_ok
        self.listen_key["errors"] = list(self.rig.listen_keys.errors)
        if self.rig.listen_keys.start_ok < 1:
            self._set(name, NOT_RUN, "no listenKey was started")
            return
        try:
            observation = await self.rig.direct_keepalive()
        except Exception as exc:
            self._failure(name, exc)
            self.delete_then_put = {
                "status": FAILED,
                "outcome": "NOT_SENT",
                "error": _describe(exc),
            }
            self._set(name, FAILED, f"the PUT after the DELETE was not sent: {_describe(exc)}")
            return
        self.delete_then_put = {"status": PASSED, "delete_ok": closed, **observation}
        self._set(
            name,
            PASSED if closed else FAILED,
            "stopped with close_listen_key=True; PUT after DELETE observed"
            if closed
            else "the DELETE of the listenKey did not succeed; PUT observed",
        )

    # -- orchestration -------------------------------------------------------- #

    async def run(self) -> None:
        print(SINGLETON_NOTE)
        try:
            await self.preflight()
            await self.account_before_step()
            await self.stream_start()
            if self.steps["stream_start"]["status"] == PASSED:
                await self.keepalive_step()
                await self.order_steps()
                await self.forced_drop_step()
        except _Abort:
            self.aborted = True
        except Exception as exc:  # recorded by type name; cleanup still runs
            self.crashed = True
            self._failure("run", exc)
        finally:
            await self.cleanup()
        self.finished_at = self.rig.clock()

    def exit_code(self) -> int:
        if self.aborted and not self.order_attempted:
            return EXIT_ABORTED
        failed = (
            self.crashed
            or any(step["status"] == FAILED for step in self.steps.values())
            or self.sdk_route_delivery == ROUTE_FAIL
            or self.end_state == END_MANUAL_CLEANUP
        )
        return EXIT_FAILED if failed else EXIT_OK

    def outcome(self) -> str:
        code = self.exit_code()
        if code == EXIT_ABORTED:
            return OUTCOME_ABORTED
        return OUTCOME_COMPLETE if code == EXIT_OK else OUTCOME_FAILED

    def document(self) -> dict[str, Any]:
        config = self.config
        order_limits = config.order_limits
        return {
            "schema": EVIDENCE_SCHEMA,
            "mode": config.mode,
            "proof_class": PROOF_REAL_SMOKE if self.rig.real else PROOF_FAKE,
            "environment": config.environment.value,
            "sdk_version": importlib.metadata.version(
                "binance-sdk-derivatives-trading-usds-futures"
            ),
            "binance_common_version": importlib.metadata.version("binance-common"),
            "started_at_utc": self.started_at,
            "finished_at_utc": self.finished_at,
            "symbol": self.symbol,
            "settings": {
                "limits_file": config.limits_file.name,
                "limits_file_sha256": sha256_lf(config.limits_file),
                "smoke_limits_file": config.smoke_limits_file.name,
                "smoke_limits_file_sha256": sha256_lf(config.smoke_limits_file),
                "quantity": order_limits.quantity,
                "far_price_fraction": order_limits.far_price_fraction,
                "event_wait_seconds": order_limits.event_wait_seconds,
                "cleanup_timeout_seconds": order_limits.cleanup_timeout_seconds,
                "transport": "sdk",
            },
            "steps": [self.steps[name] for name in STEP_NAMES],
            "state_sequence": [
                {"state": state.value, "reason": reason, "at_utc": at}
                for state, reason, at in self.state_log
            ],
            "events": self.events,
            "sdk_route_delivery": self.sdk_route_delivery,
            "listen_key": self.listen_key,
            "subscription": self.subscription,
            "drift": self.drift,
            "symbol_filters": self.symbol_filters,
            "order": self.order_record,
            "forced_drop": self.forced_drop,
            "account_before": self.account_before,
            "account_after": self.account_after,
            "end_state": self.end_state,
            "delete_then_put": self.delete_then_put,
            "stream_failures": self.stream_failures,
            "failures": self.failures,
            "log_scan": self.log_scan,
            "fixtures": self.fixtures,
            "notes": [SINGLETON_NOTE] + ([] if self.rig.real else [FAKE_NOTE]),
            "outcome": self.outcome(),
            "acceptance": {
                letter: {"result": VERDICT_UNPROVEN, "reason": "not evaluated"}
                for letter in ACCEPTANCE_LETTERS
            },
        }


def _fixture_stem(mode: str, index: int, payload: object) -> str:
    event = payload.get("e") if isinstance(payload, Mapping) else None
    name = _FIXTURE_EVENT_RE.sub("_", str(event)) if isinstance(event, str) and event else "UNKNOWN"
    return f"{mode}-{index:03d}-{name}"


def write_fixtures(
    directory: Path,
    *,
    mode: str,
    frames: Sequence[object],
    redactor: Redactor,
    started_at: datetime,
    environment: Environment,
) -> list[str]:
    """Write every raw payload scrubbed and list it in `provenance.md` with its label."""
    label = FIXTURE_LABEL_EXECUTE if mode == MODE_EXECUTE else FIXTURE_LABEL_DRY_RUN
    names: list[str] = []
    for index, payload in enumerate(frames, start=1):
        document = payload if isinstance(payload, Mapping) else {"payload": payload}
        path = write_evidence_atomic(
            directory, _fixture_stem(mode, index, payload), document, redactor
        )
        names.append(path.name)
    directory.mkdir(parents=True, exist_ok=True)
    provenance = directory / "provenance.md"
    lines = [] if provenance.exists() else ["# Provenance of the recorded user-data frames", ""]
    lines.append(
        f"## {mode} run of {_utc_stamp(started_at)} ({environment.value}, "
        "scripts/user_data_smoke.py)"
    )
    lines.append("")
    lines.extend(f"- `{name}`: {label}" for name in names)
    lines.append("")
    with provenance.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    return names


async def run_smoke(
    config: SmokeConfig, rig: SmokeRig, *, redactor: Redactor | None = None
) -> tuple[dict[str, Any], int]:
    """Run the smoke once and return (evidence document, exit code); the caller writes it."""
    redactor = redactor if redactor is not None else Redactor(None)
    run = SmokeRun(config, rig)
    buffer = io.StringIO()
    with rig.context(), capture_output(buffer):
        driver = asyncio.ensure_future(rig.driver()) if rig.driver is not None else None
        try:
            if config.fixtures_dir is not None:
                with capture_raw_user_events(run.raw_frames.append):
                    await run.run()
            else:
                await run.run()
        finally:
            if driver is not None:
                driver.cancel()
                await asyncio.gather(driver, return_exceptions=True)

    draft = json.dumps(jsonable(run.document()), sort_keys=True)
    findings = scan_for_secrets([buffer.getvalue(), draft], rig.held_secrets())
    clean = sum(findings.values()) == 0
    run.log_scan = {
        "status": PASSED if clean else FAILED,
        "findings": findings,
        "captured_characters": len(buffer.getvalue()),
    }
    run._set(
        "log_scan",
        PASSED if clean else FAILED,
        "no key, secret, signature or listenKey in the captured logs or the evidence"
        if clean
        else "a key, secret, signature or listenKey was found (counts only)",
    )

    if config.fixtures_dir is not None:
        try:
            names = write_fixtures(
                config.fixtures_dir,
                mode=config.mode,
                frames=run.raw_frames,
                redactor=redactor,
                started_at=run.started_at,
                environment=config.environment,
            )
            run.fixtures = {"status": PASSED, "files": names}
        except Exception as exc:
            run._failure("fixtures", exc)
            run.fixtures = {"status": FAILED, "error": _describe(exc)}

    run._set(
        "evidence_write",
        PASSED,
        "scrubbed, written atomically to a new name and re-scanned after the write",
    )
    document = run.document()
    document["acceptance"] = smoke_acceptance_verdict(document)
    return document, run.exit_code()


# --------------------------------------------------------------------------- #
# The evidence checker and the acceptance verdict (plan 18-18 reuses both).
# --------------------------------------------------------------------------- #

REQUIRED_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "schema",
    "mode",
    "proof_class",
    "environment",
    "sdk_version",
    "binance_common_version",
    "started_at_utc",
    "finished_at_utc",
    "symbol",
    "settings",
    "steps",
    "state_sequence",
    "events",
    "sdk_route_delivery",
    "listen_key",
    "subscription",
    "drift",
    "order",
    "forced_drop",
    "account_before",
    "account_after",
    "end_state",
    "delete_then_put",
    "log_scan",
    "notes",
    "acceptance",
)


def _walk_strings(value: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield f"{path}.{key}<key>", str(key)
            yield from _walk_strings(item, f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{path}[{index}]")


def _listen_key_shaped(text: str) -> bool:
    return any(not _HEX_DIGEST.fullmatch(run) for run in _LISTEN_KEY_SHAPE.findall(text)) or bool(
        re.search(r"(?i)listen_?key=[A-Za-z0-9]{24,}", text)
    )


def check_smoke_evidence(document: object) -> list[str]:
    """Problems that make a smoke evidence document invalid; an empty list means valid."""
    if not isinstance(document, Mapping):
        return ["evidence is not an object"]
    problems: list[str] = []
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in document:
            problems.append(f"missing key: {key}")
    if document.get("schema") != EVIDENCE_SCHEMA:
        problems.append(f"schema must be {EVIDENCE_SCHEMA}")
    mode = document.get("mode")
    proof = document.get("proof_class")
    if mode not in MODES:
        problems.append(f"mode must be one of {sorted(MODES)}")
    if proof not in PROOF_CLASSES:
        problems.append(f"proof_class must be one of {sorted(PROOF_CLASSES)}")
    if (mode, proof) in {(MODE_DRY_RUN, PROOF_REAL_SMOKE), (MODE_EXECUTE, PROOF_FAKE)}:
        problems.append("proof_class does not match the mode (a dry run is FAKE)")
    if document.get("sdk_route_delivery") not in ROUTE_VALUES:
        problems.append(f"sdk_route_delivery must be one of {sorted(ROUTE_VALUES)}")
    steps = document.get("steps")
    if not isinstance(steps, list):
        problems.append("steps is not a list")
    else:
        names = [step.get("name") if isinstance(step, Mapping) else None for step in steps]
        if names != list(STEP_NAMES):
            problems.append("steps must list every step once, in order")
        for step in steps:
            if not isinstance(step, Mapping) or step.get("status") not in STEP_STATUSES:
                problems.append(f"every step status must be one of {sorted(STEP_STATUSES)}")
                break
    acceptance = document.get("acceptance")
    if not isinstance(acceptance, Mapping) or any(
        letter not in acceptance for letter in ACCEPTANCE_LETTERS
    ):
        problems.append("acceptance must carry the keys a to h")
    elif any(
        not isinstance(acceptance[letter], Mapping)
        or acceptance[letter].get("result") not in VERDICT_RESULTS
        for letter in ACCEPTANCE_LETTERS
    ):
        problems.append(f"every acceptance result must be one of {sorted(VERDICT_RESULTS)}")
    for path, text in _walk_strings(dict(document), "$"):
        if _listen_key_shaped(text):
            problems.append(f"listenKey-shaped value at {path}")
            break
    return problems


def _step_status(document: Mapping[str, Any], name: str) -> str | None:
    for step in document.get("steps") or []:
        if isinstance(step, Mapping) and step.get("name") == name:
            status = step.get("status")
            return status if isinstance(status, str) else None
    return None


def _section(document: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = document.get(key)
    return value if isinstance(value, Mapping) else {}


def _verdict(result: str, reason: str, proof_class: object) -> dict[str, Any]:
    return {"result": result, "reason": reason, "proof_class": proof_class}


def smoke_acceptance_verdict(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """PASS, FAIL or UNPROVEN (f: OBSERVED) for each acceptance item a to h, with a reason.

    Every entry carries the document's `proof_class`: a FAKE PASS is never a REAL_SMOKE PASS.
    """
    proof = document.get("proof_class")
    out: dict[str, dict[str, Any]] = {}

    def by_status(status: str | None, what: str) -> dict[str, Any]:
        if status == PASSED:
            return _verdict(VERDICT_PASS, f"{what} passed", proof)
        if status == FAILED:
            return _verdict(VERDICT_FAIL, f"{what} failed", proof)
        return _verdict(VERDICT_UNPROVEN, f"{what} did not run", proof)

    out["a"] = by_status(_section(document, "listen_key").get("status"), "the listenKey start")

    subscription = _section(document, "subscription")
    count = subscription.get("private_connection_count")
    if subscription.get("status") == PASSED and isinstance(count, int) and count >= 1:
        out["b"] = _verdict(VERDICT_PASS, f"subscribed; private connections: {count}", proof)
    elif subscription.get("status") in (PASSED, FAILED):
        out["b"] = _verdict(
            VERDICT_FAIL, "the subscription or its private connection failed", proof
        )
    else:
        out["b"] = _verdict(VERDICT_UNPROVEN, "the subscription did not run", proof)

    route = document.get("sdk_route_delivery")
    if _step_status(document, "order_place") != PASSED:
        out["c"] = _verdict(VERDICT_UNPROVEN, "the order steps did not run", proof)
    else:
        executions = {
            event.get("execution_type")
            for event in document.get("events") or []
            if isinstance(event, Mapping) and event.get("is_smoke_order") is True
        }
        delivered = {EXECUTION_NEW, EXECUTION_CANCELED} <= executions
        if delivered and route == ROUTE_PASS:
            out["c"] = _verdict(VERDICT_PASS, "typed NEW and CANCELED via the SDK route", proof)
        elif delivered:
            out["c"] = _verdict(VERDICT_FAIL, f"inconsistent: sdk_route_delivery is {route}", proof)
        elif route == ROUTE_FAIL:
            missing = sorted({EXECUTION_NEW, EXECUTION_CANCELED} - executions)
            out["c"] = _verdict(VERDICT_FAIL, f"SDK route silent; missing: {missing}", proof)
        else:
            out["c"] = _verdict(
                VERDICT_FAIL, f"typed events missing but sdk_route_delivery is {route}", proof
            )

    out["d"] = by_status(_step_status(document, "keepalive"), "the keepalive")

    drop = _section(document, "forced_drop")
    if drop.get("status") in (None, NOT_RUN):
        out["e"] = _verdict(VERDICT_UNPROVEN, "the forced drop did not run", proof)
    else:
        sequence = [
            entry.get("state")
            for entry in drop.get("state_sequence_after_drop") or []
            if isinstance(entry, Mapping)
        ]
        snapshots = drop.get("snapshot_count_after_drop")
        gap = drop.get("gap_ms")
        ordered = _contains_in_order(
            [str(state) for state in sequence],
            (StreamState.UNKNOWN.value, StreamState.SYNCING.value, StreamState.LIVE.value),
        )
        if (
            ordered
            and isinstance(snapshots, int)
            and snapshots >= 1
            and isinstance(gap, int)
            and not isinstance(gap, bool)
        ):
            out["e"] = _verdict(VERDICT_PASS, f"UNKNOWN, SYNCING, LIVE; gap_ms={gap}", proof)
        else:
            out["e"] = _verdict(
                VERDICT_FAIL, "no UNKNOWN-SYNCING-LIVE recovery with a snapshot and a gap", proof
            )

    put = _section(document, "delete_then_put")
    if put.get("outcome") in ("ERROR", "NO_ERROR"):
        out["f"] = _verdict(
            VERDICT_OBSERVED,
            f"PUT after DELETE: outcome={put.get('outcome')}, http_class={put.get('http_class')}, "
            f"code={put.get('code')}, category={put.get('category')}",
            proof,
        )
    else:
        out["f"] = _verdict(VERDICT_UNPROVEN, "the PUT after the DELETE was not observed", proof)

    scan = _section(document, "log_scan")
    findings = scan.get("findings")
    total = (
        sum(v for v in findings.values() if isinstance(v, int))
        if isinstance(findings, Mapping)
        else None
    )
    status = _step_status(document, "log_scan")
    if status == PASSED and total == 0:
        out["g"] = _verdict(VERDICT_PASS, "no key, secret, signature or listenKey found", proof)
    elif status == FAILED or (isinstance(total, int) and total > 0):
        out["g"] = _verdict(VERDICT_FAIL, "the log scan found a secret (counts only)", proof)
    else:
        out["g"] = _verdict(VERDICT_UNPROVEN, "the log scan did not run", proof)

    problems = check_smoke_evidence(document)
    if problems:
        out["h"] = _verdict(VERDICT_FAIL, "; ".join(problems[:3]), proof)
    else:
        out["h"] = _verdict(VERDICT_PASS, "the evidence passes check_smoke_evidence", proof)
    return out


# --------------------------------------------------------------------------- #
# Command line.
# --------------------------------------------------------------------------- #


def _file_stem(config: SmokeConfig, started_at: datetime) -> str:
    kind = "DRYRUN" if config.mode == MODE_DRY_RUN else "EVIDENCE"
    return f"user-data-smoke-{kind}-{_utc_stamp(started_at)}"


def _started_at(document: Mapping[str, Any]) -> datetime:
    started = document["started_at_utc"]
    return started if isinstance(started, datetime) else datetime.fromisoformat(str(started))


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    is_tty: Callable[[], bool] | None = None,
    read_confirmation: Callable[[str], str] | None = None,
    rig_factory: Callable[[SmokeConfig], SmokeRig] | None = None,
    dry_run_scenario: DryRunScenario | None = None,
    sdk_client_factory: Callable[..., Any] | None = None,
) -> int:
    """Single entry point. Every seam defaults to the real implementation."""
    env: Mapping[str, str] = os.environ if environ is None else environ
    try:
        config = parse_config(argv)
        require_configured(config.environment)
        if config.mode == MODE_EXECUTE:
            confirm_execute(
                required_phrase(config.environment, config.symbol),
                is_tty if is_tty is not None else sys.stdin.isatty,
                read_confirmation if read_confirmation is not None else input,
            )
    except (
        UsageError,
        LimitsFileRefused,
        EnvironmentNotConfigured,
        ConfirmationRefused,
    ) as exc:
        print(f"refused ({type(exc).__name__}): {exc}", file=sys.stderr)
        return EXIT_REFUSED

    if config.mode == MODE_EXECUTE and rig_factory is None:
        configure_logging(env)

    factory: Callable[[SmokeConfig], SmokeRig]
    if rig_factory is not None:
        factory = rig_factory
    elif config.mode == MODE_EXECUTE:

        def factory(cfg: SmokeConfig) -> SmokeRig:
            return build_live_rig(cfg, environ=env, client_factory=sdk_client_factory)

    else:

        def factory(cfg: SmokeConfig) -> SmokeRig:
            return build_dry_run_rig(cfg, dry_run_scenario)

    try:
        rig = factory(config)
    except (CredentialError, CredentialNamesNotRatified, EnvironmentNotConfigured) as exc:
        print(f"refused ({type(exc).__name__}): {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except (EndpointViolation, LiveNotEnabled) as exc:
        print(f"ABORTED before any order ({type(exc).__name__}): {exc}", file=sys.stderr)
        return EXIT_ABORTED

    redactor = Redactor.from_environ(env)
    try:
        document, code = asyncio.run(run_smoke(config, rig, redactor=redactor))
    finally:
        rig.cleanup()
    try:
        path = write_evidence_atomic(
            config.evidence_dir, _file_stem(config, _started_at(document)), document, redactor
        )
    except RuntimeError as exc:
        print(f"evidence not written ({type(exc).__name__}): {exc}", file=sys.stderr)
        return EXIT_FAILED
    print(f"evidence: {path}")
    print(f"sdk_route_delivery: {document['sdk_route_delivery']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
