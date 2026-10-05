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
  BINANCE_TESTNET_API_KEY, BINANCE_TESTNET_API_SECRET, TELEGRAM_BOT_TOKEN and
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
import json
import os
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn, TypeVar
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from binance_common.constants import (  # noqa: E402
    DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL,
)
from src.adapters.binance_usdm import (  # noqa: E402
    AlgoOrderProbe,
    AlgoPlacementResult,
    BinanceUsdmAdapter,
    CommissionRates,
    EntryPlacementResult,
    Kline,
    MarkKline,
    OpenAlgoOrderSnapshot,
    OpenOrderSnapshot,
    OrderProbe,
    PositionModeResult,
    PositionSnapshot,
    SymbolFilters,
)
from src.ops.redaction import Redactor  # noqa: E402

# --------------------------------------------------------------------------- #
# Constants and errors.
# --------------------------------------------------------------------------- #

DEMO_BASE_URL: str = DERIVATIVES_TRADING_USDS_FUTURES_REST_API_DEMO_URL
DEMO_HOST = "demo-fapi.binance.com"
SYMBOL = "BTCUSDT"

ENV_BINANCE_KEY = "BINANCE_TESTNET_API_KEY"
ENV_BINANCE_SECRET = "BINANCE_TESTNET_API_SECRET"  # noqa: S105 - a variable NAME, not a secret
ENV_TELEGRAM_TOKEN = "TELEGRAM_BOT_TOKEN"  # noqa: S105 - a variable NAME, not a secret
ENV_TELEGRAM_CHAT = "TELEGRAM_AUTHORIZED_CHAT_ID"

EVIDENCE_SCHEMA = "demo-rehearsal-evidence/schema-1"
DEFAULT_EVIDENCE_DIR = REPO_ROOT / ".planning" / "phases" / "09-live-execution-rollout"

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

_T = TypeVar("_T")


class DemoHostViolation(Exception):  # noqa: N818 - public name fixed by the plan
    """A base URL other than the exact Demo Trading REST host was seen."""


class CredentialError(Exception):
    """A required environment variable is missing, blank or malformed (names only)."""


class ConfirmationRefused(Exception):  # noqa: N818 - public name fixed by the plan
    """The --execute interactive confirmation was not given exactly."""


class UsageError(Exception):
    """A bad or forbidden command-line argument."""


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
    """Accept only the exact Demo Trading REST base URL; everything else raises."""
    if not isinstance(url, str) or not url:
        raise DemoHostViolation("base URL is missing or not text")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise DemoHostViolation("base URL is not parseable") from None
    if (
        parts.scheme != "https"
        or parts.netloc != DEMO_HOST
        or parts.hostname != DEMO_HOST
        or port is not None
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
        or url != DEMO_BASE_URL
    ):
        raise DemoHostViolation(f"base URL is not the Demo Trading host {DEMO_HOST}")


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


def default_adapter_factory(credentials: RehearsalCredentials) -> AdapterBundle:
    """Real Demo client, real adapter built on it, per-call live host re-check."""
    client = build_demo_sdk_client(
        api_key=credentials.binance_api_key, api_secret=credentials.binance_api_secret
    )
    adapter = BinanceUsdmAdapter(sdk_client=client)
    return AdapterBundle(inner=adapter, guard=lambda: assert_demo_sdk_client(client))


# --------------------------------------------------------------------------- #
# Evidence (SR-8): only exchange-returned dataclasses can become exchange records.
# --------------------------------------------------------------------------- #

_ORDER_RECORD_TYPES = (EntryPlacementResult, AlgoPlacementResult)
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
        entry: dict[str, Any] = {"step": step, "exception_type": type(exc).__name__}
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
        self._sim_orders: dict[str, str] = {}
        self._sim_algos: dict[str, str] = {}

    @property
    def mode(self) -> RunMode:
        return self._mode

    async def _call(self, call: Callable[[], Awaitable[_T]]) -> _T:
        self._guard()
        self.call_count += 1
        try:
            return await call()
        except Exception:
            self.error_count += 1
            raise

    # ----- reads ------------------------------------------------------------- #

    async def exchange_info(self) -> list[SymbolFilters]:
        return await self._call(lambda: self._inner.exchange_info())

    async def server_time(self) -> datetime:
        return await self._call(lambda: self._inner.server_time())

    async def klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1500,
    ) -> list[Kline]:
        return await self._call(
            lambda: self._inner.klines(symbol, interval, start_ms, end_ms, limit)
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
            lambda: self._inner.mark_klines(symbol, interval, start_ms, end_ms, limit)
        )

    async def user_commission_rate(self, symbol: str) -> CommissionRates:
        return await self._call(lambda: self._inner.user_commission_rate(symbol))

    async def get_position_mode(self) -> PositionModeResult:
        return await self._call(lambda: self._inner.get_position_mode())

    async def snapshot_open_normal_orders(
        self, *, symbol: str | None = None
    ) -> list[OpenOrderSnapshot]:
        return await self._call(lambda: self._inner.snapshot_open_normal_orders(symbol=symbol))

    async def snapshot_open_algo_orders(
        self, *, symbol: str | None = None
    ) -> list[OpenAlgoOrderSnapshot]:
        return await self._call(lambda: self._inner.snapshot_open_algo_orders(symbol=symbol))

    async def snapshot_positions(self, *, symbol: str | None = None) -> list[PositionSnapshot]:
        return await self._call(lambda: self._inner.snapshot_positions(symbol=symbol))

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
            lambda: self._inner.query_order_by_client(
                symbol=symbol, orig_client_order_id=orig_client_order_id
            )
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
            lambda: self._inner.query_algo_order_by_client(client_algo_id=client_algo_id)
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
    ) -> EntryPlacementResult:
        if self._mode is RunMode.DRY_RUN:
            self._recorder.record_planned_request(
                "place_entry",
                {
                    "symbol": symbol,
                    "side": side,
                    "position_side": position_side,
                    "time_in_force": time_in_force,
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
            lambda: self._inner.place_entry(
                symbol=symbol,
                side=side,
                position_side=position_side,
                time_in_force=time_in_force,
                quantity=quantity,
                price=price,
                new_client_order_id=new_client_order_id,
            )
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
            )
        )
        self._recorder.record_exchange_record(result)
        return result

    async def cancel_normal_order(self, *, symbol: str, orig_client_order_id: str) -> None:
        if self._mode is RunMode.DRY_RUN:
            self._recorder.record_planned_request(
                "cancel_normal_order",
                {"symbol": symbol, "orig_client_order_id": orig_client_order_id},
            )
            if orig_client_order_id in self._sim_orders:
                self._sim_orders[orig_client_order_id] = "CANCELED"
            return
        await self._call(
            lambda: self._inner.cancel_normal_order(
                symbol=symbol, orig_client_order_id=orig_client_order_id
            )
        )

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> None:
        if self._mode is RunMode.DRY_RUN:
            self._recorder.record_planned_request(
                "cancel_algo_order", {"symbol": symbol, "client_algo_id": client_algo_id}
            )
            if client_algo_id in self._sim_algos:
                self._sim_algos[client_algo_id] = "CANCELED"
            return
        await self._call(
            lambda: self._inner.cancel_algo_order(symbol=symbol, client_algo_id=client_algo_id)
        )


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
# Scenarios. Task 1 is the tracer: read the Demo constraints and record them.
# --------------------------------------------------------------------------- #


def select_symbol(filters: Sequence[SymbolFilters]) -> SymbolFilters:
    """BTCUSDT must be a TRADING PERPETUAL; anything else fails closed."""
    for item in filters:
        if item.symbol == SYMBOL:
            if item.status != "TRADING" or item.contract_type != "PERPETUAL":
                raise RehearsalAbort(f"{SYMBOL} is not a TRADING PERPETUAL on Demo")
            return item
    raise RehearsalAbort(f"{SYMBOL} is absent from exchangeInfo on Demo")


async def run_tracer(guarded: GuardedAdapter, recorder: EvidenceRecorder) -> str:
    """Thinnest path through every layer: server time, exchangeInfo, constraints, evidence."""
    server_now = await guarded.server_time()
    recorder.details["exchange_server_time_utc"] = _jsonable(server_now)
    filters = select_symbol(await guarded.exchange_info())
    recorder.set_constraints(filters)
    recorder.add_step(
        "read_constraints",
        STEP_PASSED,
        "exchangeInfo constraints for BTCUSDT read from Binance Demo",
    )
    return OUTCOME_COMPLETE


async def run_rehearsal(
    guarded: GuardedAdapter,
    recorder: EvidenceRecorder,
    *,
    scenario: str,
    approval_timeout_seconds: int,
    discovery_timeout_seconds: int,
) -> str:
    """Dispatch one scenario. Raises RehearsalAbort for a fail-closed stop."""
    del scenario, approval_timeout_seconds, discovery_timeout_seconds
    return await run_tracer(guarded, recorder)


def _outcome_exit_code(outcome: str) -> int:
    if outcome in (OUTCOME_COMPLETE, OUTCOME_COMPLETE_WITH_GAPS):
        return EXIT_OK
    if outcome == OUTCOME_ABORTED:
        return EXIT_ABORTED
    return EXIT_FAILED


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    adapter_factory: Callable[[RehearsalCredentials], AdapterBundle] | None = None,
    clock: Callable[[], datetime] | None = None,
    is_tty: Callable[[], bool] | None = None,
    read_confirmation: Callable[[str], str] | None = None,
    evidence_dir: Path | None = None,
    channel_factory: Callable[..., Any] | None = None,
) -> int:
    """Single entry point. Every seam defaults to the real implementation."""
    del channel_factory  # used from the Telegram scenarios onward
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
    except (UsageError, ConfirmationRefused, CredentialError) as exc:
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
    factory = adapter_factory if adapter_factory is not None else default_adapter_factory
    try:
        bundle = factory(credentials)
        guarded = GuardedAdapter(
            bundle.inner, guard=bundle.guard, mode=mode, clock=now, recorder=recorder
        )
        outcome = asyncio.run(
            run_rehearsal(
                guarded,
                recorder,
                scenario=args.scenario,
                approval_timeout_seconds=args.approval_timeout_seconds,
                discovery_timeout_seconds=args.discovery_timeout_seconds,
            )
        )
    except (DemoHostViolation, RehearsalAbort) as exc:
        recorder.record_failure("run", exc)
        recorder.add_step("run", STEP_FAILED, f"aborted before any order: {type(exc).__name__}")
        outcome = OUTCOME_ABORTED
    except Exception as exc:  # noqa: BLE001 - recorded by type name, never by message
        recorder.record_failure("run", exc)
        recorder.add_step("run", STEP_FAILED, f"run failed: {type(exc).__name__}")
        outcome = OUTCOME_FAILED
    recorder.outcome = outcome
    path = recorder.write(target_dir)
    print(f"evidence: {path}")
    return _outcome_exit_code(outcome)


if __name__ == "__main__":
    sys.exit(main())
