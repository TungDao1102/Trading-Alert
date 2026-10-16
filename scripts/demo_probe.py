"""Connected-machine Demo probe of the D055, D-16 and G2-029 cases (Phase 18, plans 18-17, 18-23).

Run from the repository root::

    uv run python -m scripts.demo_probe --environment DEMO --probe-limits-file <file>

What it is. A single-file operator tool, in the style of ``scripts/demo_rehearsal.py`` and
``scripts/user_data_smoke.py``, that walks a registry of probe cases (``CASE_ORDER``, the
CONTEXT D-16 order of risk) against a project-owned port (``ProbePort``) and records every
exchange answer as data: the exact (HTTP class, int code, category, message) of each answer,
the user-data frames each case produced, and the account state before and after. Each case
ends OBSERVED with its observations or NOT_OBSERVED with the reason. After every case and at
the end the probe cleans up (cancel-all for normal and algo orders, one reduce-only market
order for a residual position) and verifies zero open orders, zero open algo orders and a flat
position. One scrubbed evidence file ``demo-probe-evidence/schema-1`` is written.

D055 stays OPEN: this tool records facts and stops. Results are labelled "demo-observed, not
mainnet"; the tool never edits a decision file, never chooses a model and its output is never
used to choose a trading parameter (D-17).

Plan 18-17 builds the safety envelope (runner, clock and sleep contracts, cleanup, evidence,
CLI gates) and the four read-only not-found cases; plan 18-23 registers the cases that send
orders on this envelope. Until then an ``--execute`` run records every unregistered case as
ERROR ("no handler registered"); the live run is plan 18-20 (blocking-human).

Safety posture (read before running anything):

* Dry run is the default. Without ``--execute`` every registered handler runs against
  ``RecordingProbePort`` (``tests/probe_fakes.py``) on virtual time: nothing is sent, no
  socket, no credential, no real sleep. Every request a case would send is recorded as a
  planned request; every case is written NOT_REHEARSED with ``proof_class`` FAKE.
* ``--execute`` needs an interactive terminal AND the exactly typed phrase
  ``DEMO PROBE <SYMBOL>`` (the symbol of the probe limits file). Anything else exits 2 before
  any network call.
* There is no option for a host, a URL, a key, a secret or LIVE. Every URL comes from the
  environment row of ``src/adapters/binance_client.py`` and the environment guard
  (``assert_environment``) runs before every call. Credentials come only from the variables of
  the environment's credential specification (or their ``<NAME>_FILE`` files outside the
  repository); any LIVE credential variable refuses the run.
* The owner's probe limits file (order size, notional cap, waits, optional cases) and the
  ratified Binance limits file are validated before any network call. The symbol must be flat
  (no open order, no algo order, no position) before the probe, else nothing is sent (exit 3).
* One ``RestRateLimitGate`` per run is shared by every REST holder: a 418 ban or a 429 pause
  stops every REST call of the process (user record 18-DEC-O-18-01.md and its amendment of
  2026-10-16). The probe never retries; after a ban or a rate-limit answer it stops (outcome
  ABORTED_BAN) and records every case not yet run NOT_OBSERVED.
* Time: every timestamp comes from the rig's injected clock and every wait goes through
  ``wait_up_to`` (one sleep of at most the owner's ``case_timeout_seconds`` or
  ``cleanup_timeout_seconds``). The only wall-clock read is ``live_clock``.
* The account's listenKey is a singleton: no other process may run on the same account during
  the probe (research P7).

Exit codes::

    0  the run completed (every case OBSERVED or NOT_OBSERVED, cleanup verified flat)
    1  the run failed part-way (evidence written): a case ERROR, a ban or rate limit, or
       CLEANUP_FAILED (the remaining state is in the evidence)
    2  refused before any network call (usage, limits files, environment, credentials,
       --execute gate)
    3  aborted before any order (environment guard, account not flat or unreadable before)

Operator runbook: plan 18-20 (blocking-human) runs this tool on Demo with the owner present.
Dry runs write ``demo-probe-DRYRUN-<UTC stamp>.json``; executed runs write
``demo-probe-EVIDENCE-<UTC stamp>.json`` under the phase ``evidence`` directory.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.metadata
import os
import re
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn, Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from binance_common.configuration import ConfigurationWebSocketStreams  # noqa: E402
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
from src.adapters.binance_errors import error_facts_from_exception  # noqa: E402
from src.adapters.binance_limits import (  # noqa: E402
    BinanceLimits,
    LimitsNotRatified,
    StreamLimits,
    load_binance_limits,
)
from src.adapters.binance_probe import (  # noqa: E402
    BinanceProbeAdapter,
    ErrorObservation,
    ProbeBanned,
    ProbeObservation,
)
from src.adapters.binance_public import BinancePublicMarketData  # noqa: E402
from src.adapters.binance_ratelimit_gate import (  # noqa: E402
    IP_BAN_418,
    RATE_LIMIT_PAUSE_429,
    RestGateRefusal,
    RestRateLimitGate,
)
from src.adapters.binance_usdm import PositionModeResult  # noqa: E402
from src.adapters.binance_userdata import (  # noqa: E402
    PRIVATE_URL_PATH,
    ListenKeyPort,
    SdkListenKeyPort,
    SdkUserDataTransport,
    UserDataAdapter,
    capture_raw_user_events,
    install_sdk_noise_guard,
)
from src.adapters.binance_userdata_events import StreamAnomaly  # noqa: E402
from src.adapters.binance_userdata_supervisor import (  # noqa: E402
    StreamSnapshot,
    StreamState,
    TrustedEvent,
    UserDataSupervisor,
)
from src.domain.exchange_errors import CallKind, classify  # noqa: E402
from src.ops.operator_evidence import (  # noqa: E402
    EXIT_ABORTED,
    EXIT_FAILED,
    EXIT_OK,
    EXIT_REFUSED,
    ConfirmationRefused,
    DemoOrderLimits,
    DemoOrderLimitsRefused,
    TextScrubber,
    confirm_execute,
    jsonable,
    load_demo_order_limits,
    sha256_lf,
    write_evidence_atomic,
)
from src.ops.redaction import Redactor, configure_logging  # noqa: E402

# --------------------------------------------------------------------------- #
# Constants (tool settings and vocabulary; no safety threshold lives here).
# --------------------------------------------------------------------------- #

EVIDENCE_SCHEMA = "demo-probe-evidence/schema-1"
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
PROOF_REAL_DEMO = "REAL_DEMO"
PROOF_CLASSES: frozenset[str] = frozenset({PROOF_FAKE, PROOF_REAL_DEMO})

LABEL = "demo-observed, not mainnet"
LABEL_FAKE = f"{LABEL} (FAKE dry run: nothing was sent and nothing was observed)"
D055_STATUS = (
    "OPEN: the probe records facts and stops; D055 is decided by the user, never by this tool"
)
D055_STATEMENT = "D055 stays OPEN: this tool records facts and stops"
D017_STATEMENT = "Demo observations are never used to choose a trading parameter or a model (D-17)"

# Case statuses.
OBSERVED = "OBSERVED"
NOT_OBSERVED = "NOT_OBSERVED"
NOT_REHEARSED = "NOT_REHEARSED"
SKIPPED_DRY_RUN = "SKIPPED_DRY_RUN"
ERROR = "ERROR"
CASE_STATUSES: frozenset[str] = frozenset(
    {OBSERVED, NOT_OBSERVED, NOT_REHEARSED, SKIPPED_DRY_RUN, ERROR}
)
NOT_RUN = "NOT_RUN"

# Cleanup verdicts.
CLEANUP_FLAT = "FLAT"
CLEANUP_FAILED_STATUS = "CLEANUP_FAILED"
CLEANUP_NOT_VERIFIED = "NOT_VERIFIED"
CLEANUP_NOT_RUN = NOT_RUN

# Run outcomes.
OUTCOME_COMPLETE = "COMPLETE"
OUTCOME_FAILED = "FAILED"
OUTCOME_CLEANUP_FAILED = "CLEANUP_FAILED"
OUTCOME_ABORTED_BAN = "ABORTED_BAN"
OUTCOME_ABORTED_NO_ORDER = "ABORTED_NO_ORDER"
OUTCOMES: frozenset[str] = frozenset(
    {
        OUTCOME_COMPLETE,
        OUTCOME_FAILED,
        OUTCOME_CLEANUP_FAILED,
        OUTCOME_ABORTED_BAN,
        OUTCOME_ABORTED_NO_ORDER,
    }
)

REASON_DRY_RUN = "dry run: nothing was sent"
REASON_BAN = "run aborted: ban"
REASON_NO_HANDLER = "no handler registered"
REASON_NOT_FLAT_BEFORE = (
    "run aborted before any order: the symbol was not flat, or its state or position mode "
    "was unreadable, before the probe"
)
NOTE_UNEXPECTED_EXISTS = "unexpected: the id existed"
OPERATOR_CLEANUP_NOTE = (
    "OPERATOR: {outcome} on {symbol}: check open orders, open algo orders and the position in "
    "the Demo account and clean them up by hand."
)

# The cases, in the CONTEXT D-16 order of risk: the read-only not-found codes, the duplicate
# client algo id, id reuse, the D055 cases, the G2-029 additions, then the owner-approved
# optional cases (run only when enabled in the probe limits file).
READ_ONLY_CASES: tuple[str, ...] = (
    "get_order_not_found",
    "get_algo_order_not_found",
    "cancel_order_not_found",
    "cancel_algo_order_not_found",
)
REQUIRED_CASES: tuple[str, ...] = (
    *READ_ONLY_CASES,
    "duplicate_client_algo_id",
    "id_reuse_after_canceled_normal",
    "id_reuse_after_canceled_algo",
    "id_reuse_after_filled",
    "preplaced_stop_reduce_only_flat",
    "closeposition_stop_flat",
    "entry_never_fills_protective_orphan",
    "full_fill_protective_quantity",
    "partial_fill",
    "rejected_protective_variants",
    "below_min_notional_reduce_only_leg",
    "triggered_market_exit_lifecycle",
)
# optional_cases key of the probe limits file -> case id.
OPTIONAL_CASES: Mapping[str, str] = MappingProxyType(
    {
        "explicit_time_in_force": "explicit_time_in_force_variant",
        "stream_gap": "stream_gap_during_case",
        "market_lot_size_out_of_range": "market_lot_size_out_of_range",
    }
)
CASE_ORDER: tuple[str, ...] = (*REQUIRED_CASES, *OPTIONAL_CASES.values())

# Client ids of the probe: the exchange's documented id shape (at most 36 characters).
CLIENT_ID_PREFIX = "dprobe-"
CLIENT_ID_RE = re.compile(r"^[.A-Z:/a-z0-9_-]{1,36}$")

# Order vocabulary of the cleanup (tool vocabulary, not a trading decision).
SIDE_BUY = "BUY"
SIDE_SELL = "SELL"
POSITION_SIDE_ONE_WAY = "BOTH"

# The port operations that change exchange state: unreachable through a dry-run guarded port.
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

# The acceptance verdict (research C4).
VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_RULES: tuple[str, ...] = (
    "cleanup",
    "account_state",
    "label_and_d055",
    "evidence",
    "proof_class",
)
ACCOUNT_READ = "READ"

BANNER = (
    "Demo probe. Results are demo-observed, not mainnet. The probe records facts and stops: "
    "D055 stays OPEN and nothing here chooses a model or a trading parameter (D-17). The "
    "account's listenKey is a singleton: no other process may run on the same account during "
    "the probe. Run it only with a probe limits file the owner approved (O-18-03)."
)

FIXTURE_LABEL_EXECUTE = "RECORDED_DEMO"
FIXTURE_LABEL_DRY_RUN = "FAKE_DRYRUN"
_FIXTURE_EVENT_RE = re.compile(r"[^A-Za-z0-9_]")

_RATE_LIMIT_CATEGORIES: Mapping[str, str] = MappingProxyType(
    {"IP_BANNED": IP_BAN_418, "RATE_LIMITED": RATE_LIMIT_PAUSE_429}
)
_TRUE = "true"
_FALSE = "false"


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


class _AbortNoOrder(Exception):  # noqa: N818 - an internal signal: fail closed before any order
    """The run stops before any order (exit 3)."""


class _ArgumentParser(argparse.ArgumentParser):
    """argparse that raises instead of exiting, so `main` returns the exit code."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


# --------------------------------------------------------------------------- #
# Configuration.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ProbeConfig:
    """The validated command line and both limits files of one run."""

    environment: Environment
    mode: str
    limits_file: Path
    probe_limits_file: Path
    evidence_dir: Path
    fixtures_dir: Path | None
    limits: BinanceLimits
    order_limits: DemoOrderLimits
    only: tuple[str, ...] | None = None

    @property
    def symbol(self) -> str:
        return self.order_limits.symbol

    @property
    def enabled_optional_cases(self) -> tuple[str, ...]:
        """The case ids of the enabled optional cases, in `CASE_ORDER` order."""
        return tuple(OPTIONAL_CASES[key] for key in self.order_limits.enabled_optional_cases)

    @property
    def case_ids(self) -> tuple[str, ...]:
        """The cases of this run in `CASE_ORDER` order (narrowed by `--only`)."""
        enabled = set(REQUIRED_CASES) | set(self.enabled_optional_cases)
        chosen = enabled if self.only is None else enabled & set(self.only)
        return tuple(case_id for case_id in CASE_ORDER if case_id in chosen)


def required_phrase(environment: Environment, symbol: str) -> str:
    """The exact phrase `--execute` needs, for example ``DEMO PROBE BTCUSDT``."""
    return f"{environment.value} PROBE {symbol}"


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="demo_probe",
        description="Demo probe of the D055 / D-16 / G2-029 cases (dry run by default).",
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
        "--probe-limits-file",
        type=Path,
        required=True,
        help="the owner-approved order size, notional cap, waits and optional cases (no default)",
    )
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help="write every raw user-data payload of each case, scrubbed, into this directory",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="a comma list of case ids to run (in CASE_ORDER order); default: every case",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="run against the selected environment (interactive terminal and typed phrase)",
    )
    return parser


def _is_within(path: Path, parent: Path) -> bool:
    return path.resolve().is_relative_to(parent.resolve())


def _parse_only(text: str | None, order_limits: DemoOrderLimits) -> tuple[str, ...] | None:
    if text is None:
        return None
    items = [item.strip() for item in text.split(",")]
    if any(not item for item in items):
        raise UsageError("--only must be a comma list of case ids without empty items")
    unknown = sorted(set(items) - set(CASE_ORDER))
    if unknown:
        raise UsageError(f"--only names unknown case ids: {unknown}")
    if len(set(items)) != len(items):
        raise UsageError("--only names a case id more than once")
    enabled = {OPTIONAL_CASES[key] for key in order_limits.enabled_optional_cases}
    disabled = sorted(set(items) & (set(OPTIONAL_CASES.values()) - enabled))
    if disabled:
        raise UsageError(
            f"--only names optional cases not enabled in the probe limits file: {disabled}"
        )
    return tuple(items)


def parse_config(argv: Sequence[str] | None) -> ProbeConfig:
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
        order_limits = load_demo_order_limits(args.probe_limits_file, kind="probe")
    except DemoOrderLimitsRefused as exc:
        raise LimitsFileRefused("probe limits", args.probe_limits_file, exc.problems) from None
    only = _parse_only(args.only, order_limits)
    return ProbeConfig(
        environment=environment,
        mode=mode,
        limits_file=Path(args.limits_file),
        probe_limits_file=Path(args.probe_limits_file),
        evidence_dir=Path(args.evidence_dir),
        fixtures_dir=fixtures_dir,
        limits=limits,
        order_limits=order_limits,
        only=only,
    )


def require_configured(environment: Environment) -> None:
    """Raise `EnvironmentNotConfigured` unless REST and WebSocket Streams have a row URL."""
    row = binance_client.ENVIRONMENT_ROWS[environment]
    for surface in sorted(SURFACES):
        if row.url_for(surface) is None:
            raise EnvironmentNotConfigured(
                f"environment {environment.value} has no configured URL for surface {surface.value}"
            )


# --------------------------------------------------------------------------- #
# The port, the rig and the case contract (plan 18-23 consumes these unchanged).
# --------------------------------------------------------------------------- #


class ProbePort(Protocol):
    """The project-owned probe surface: `BinanceProbeAdapter` plus position mode and frames.

    Every operation returns a `ProbeObservation` (an exchange error is data) or raises
    `ProbeBanned` (refused before sending). `marker()` is an opaque position in the stream
    record; `frames_since`, `raw_frames_since` and `stream_states_since` return what arrived
    after it: typed event records as text mappings, raw payloads, supervisor state names.
    `drop_stream_transport()` closes the private connection and returns False when no stream
    runs (the optional stream-gap case of plan 18-23).
    """

    async def query_order(self, *, symbol: str, client_order_id: str) -> ProbeObservation: ...

    async def query_algo_order(self, *, client_algo_id: str) -> ProbeObservation: ...

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
    ) -> ProbeObservation: ...

    async def new_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        client_order_id: str,
        position_side: str,
        reduce_only: bool | None,
    ) -> ProbeObservation: ...

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
    ) -> ProbeObservation: ...

    async def cancel_order(self, *, symbol: str, client_order_id: str) -> ProbeObservation: ...

    async def cancel_algo_order(self, *, client_algo_id: str) -> ProbeObservation: ...

    async def cancel_all_open_orders(self, *, symbol: str) -> ProbeObservation: ...

    async def cancel_all_algo_open_orders(self, *, symbol: str) -> ProbeObservation: ...

    async def open_orders(self, *, symbol: str) -> ProbeObservation: ...

    async def open_algo_orders(self, *, symbol: str) -> ProbeObservation: ...

    async def positions(self, *, symbol: str) -> ProbeObservation: ...

    async def user_trades(
        self, *, symbol: str, order_id: int | None = None
    ) -> ProbeObservation: ...

    async def account_balance(self) -> ProbeObservation: ...

    async def mark_price(self, *, symbol: str) -> ProbeObservation: ...

    async def symbol_filters(self, *, symbol: str) -> ProbeObservation: ...

    async def position_mode(self) -> ProbeObservation: ...

    def marker(self) -> int: ...

    def frames_since(self, marker: int) -> list[dict[str, str]]: ...

    def raw_frames_since(self, marker: int) -> list[object]: ...

    def stream_states_since(self, marker: int) -> list[str]: ...

    async def drop_stream_transport(self) -> bool: ...


class StreamControl(Protocol):
    """The user-data stream of an executed run: `start` raises when it does not go LIVE."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


@dataclass(frozen=True)
class ProbeRig:
    """Everything a run needs, built for one mode (`build_live_rig`, `build_dry_run_rig`).

    `clock` must return an aware UTC datetime (a naive one raises ValueError before any call);
    `sleep` waits on that clock and is called only by `wait_up_to`. `stream` is the user-data
    stream of an executed run (None: no stream, every frame field is NOT_OBSERVED). `planned`
    lists the requests the recording port planned (dry run); `live_calls` counts the calls of
    a live port; `real` marks an executed rig.
    """

    port: ProbePort
    clock: Callable[[], datetime]
    sleep: Callable[[int], Awaitable[None]]
    real: bool = False
    stream: StreamControl | None = None
    planned: Callable[[], Sequence[Mapping[str, Any]]] | None = None
    live_calls: Callable[[], int] | None = None


def _checked_now(rig: ProbeRig) -> datetime:
    """`rig.clock()`, refused unless it is an aware UTC datetime."""
    moment = rig.clock()
    if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("the rig clock must return an aware UTC datetime")
    if moment.utcoffset() != UTC.utcoffset(None):
        raise ValueError("the rig clock must return an aware UTC datetime (offset zero)")
    return moment


async def wait_up_to(
    rig: ProbeRig, predicate: Callable[[], Awaitable[bool]], timeout_seconds: int
) -> bool:
    """The one wait of the probe: `predicate` once, else one `rig.sleep(timeout)` and once more.

    No polling interval and no number of its own: the only wait numbers are the owner's
    `case_timeout_seconds` and `cleanup_timeout_seconds`, passed in by the caller.
    """
    if type(timeout_seconds) is not int:
        raise TypeError("timeout_seconds must be an int (the owner's wait)")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if await predicate():
        return True
    await rig.sleep(timeout_seconds)
    return await predicate()


@dataclass(frozen=True, kw_only=True)
class CaseResult:
    """What a handler returns: a status, the exchange answers as data, a reason, notes.

    OBSERVED needs at least one observation; NOT_OBSERVED and ERROR need a reason. `details`
    holds the text facts of the case (for example the probed client id).
    """

    status: str
    observations: tuple[ProbeObservation, ...] = ()
    reason: str | None = None
    notes: tuple[str, ...] = ()
    details: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in CASE_STATUSES:
            raise ValueError(f"unknown case status: {self.status!r}")
        observations = tuple(self.observations)
        if any(not isinstance(item, ProbeObservation) for item in observations):
            raise TypeError("observations must be ProbeObservation values")
        object.__setattr__(self, "observations", observations)
        object.__setattr__(self, "notes", tuple(str(note) for note in self.notes))
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in self.details.items()):
            raise TypeError("details must map text to text")
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))
        if self.status == OBSERVED and not observations:
            raise ValueError("an OBSERVED case needs at least one observation")
        if self.status in (NOT_OBSERVED, ERROR) and not (self.reason or "").strip():
            raise ValueError(f"a {self.status} case needs a reason")


@dataclass(frozen=True)
class CaseContext:
    """The handler's view: the rig (port, clock, sleep), the config and the recorder."""

    rig: ProbeRig
    config: ProbeConfig
    recorder: ProbeRecorder


CaseHandler = Callable[[CaseContext], Awaitable[CaseResult]]


# --------------------------------------------------------------------------- #
# The recorder (jsonable, sorted-key evidence).
# --------------------------------------------------------------------------- #


def _utc_stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


class ProbeRecorder:
    """Collects the run; `document(config)` is the evidence (plain JSON data).

    During the run the raw handler results stay in `results`, so a dependent case can read
    an earlier one (in a dry run it follows the canned accepted path). For serialization a
    dry run rewrites every case to NOT_REHEARSED, drops the canned observations and notes and
    keeps the planned requests.
    """

    def __init__(self) -> None:
        self.mode: str | None = None
        self.real = False
        self.started_utc: datetime | None = None
        self.finished_utc: datetime | None = None
        self.account_before: dict[str, Any] = {"status": NOT_RUN}
        self.account_after: dict[str, Any] = {"status": NOT_RUN}
        self.market: dict[str, Any] = {"status": NOT_RUN}
        self.stream: dict[str, Any] = {"status": NOT_RUN}
        self.records: dict[str, dict[str, Any]] = {}
        self.results: dict[str, CaseResult] = {}
        self.final_cleanup: dict[str, Any] = {"status": CLEANUP_NOT_RUN}
        self.ban: dict[str, Any] | None = None
        self.failures: list[dict[str, str]] = []
        self.fixtures: list[str] = []
        self.outcome = OUTCOME_COMPLETE
        self.live_port_calls = 0
        self.dual_side: bool | None = None
        self._next_id = 0

    def next_client_id(self, tag: str) -> str:
        """A fresh client id of this run: ``dprobe-<tag>-<start stamp>-<n>``."""
        if self.started_utc is None:
            raise RuntimeError("the run has not started")
        self._next_id += 1
        value = f"{CLIENT_ID_PREFIX}{tag}-{_utc_stamp(self.started_utc)}-{self._next_id}"
        if not CLIENT_ID_RE.fullmatch(value):
            raise ValueError("the client id does not fit the exchange's id shape")
        return value

    def _case_view(self, record: Mapping[str, Any], dry_run: bool) -> dict[str, Any]:
        view = dict(record)
        if dry_run:
            view.update(
                {"status": NOT_REHEARSED, "reason": REASON_DRY_RUN, "observations": [], "notes": []}
            )
        return view

    def document(self, config: ProbeConfig) -> dict[str, Any]:
        """The evidence document as plain JSON data (Decimal and time as text)."""
        dry_run = config.mode == MODE_DRY_RUN
        order = config.order_limits
        cases = [
            self._case_view(self.records[case_id], dry_run)
            for case_id in config.case_ids
            if case_id in self.records
        ]
        document: dict[str, Any] = {
            "schema": EVIDENCE_SCHEMA,
            "mode": config.mode,
            "proof_class": PROOF_REAL_DEMO if self.real else PROOF_FAKE,
            "label": LABEL if self.real else LABEL_FAKE,
            "environment": config.environment.value,
            "symbol": config.symbol,
            "sdk_version": importlib.metadata.version(
                "binance-sdk-derivatives-trading-usds-futures"
            ),
            "started_utc": self.started_utc,
            "finished_utc": self.finished_utc,
            "settings": {
                "limits_file": config.limits_file.name,
                "limits_file_sha256": sha256_lf(config.limits_file),
                "probe_limits_file": config.probe_limits_file.name,
                "probe_limits_file_sha256": sha256_lf(config.probe_limits_file),
                "quantity": order.quantity,
                "max_notional_quote": order.max_notional_quote,
                "far_price_fraction": order.far_price_fraction,
                "market_lot_probe_quantity": order.market_lot_probe_quantity,
                "case_timeout_seconds": order.case_timeout_seconds,
                "cleanup_timeout_seconds": order.cleanup_timeout_seconds,
                "optional_cases": dict(order.optional_cases),
                "only": list(config.only) if config.only is not None else None,
            },
            "case_order": list(config.case_ids),
            "account_before": self.account_before,
            "account_after": self.account_after,
            "market": self.market,
            "stream": self.stream,
            "cases": cases,
            "cleanup": {"final": self.final_cleanup},
            "ban": self.ban,
            "failures": self.failures,
            "fixtures": self.fixtures,
            "live_port_calls": self.live_port_calls,
            "d055": {
                "status": D055_STATUS,
                "statement": D055_STATEMENT,
                "parameters": D017_STATEMENT,
            },
            "notes": [
                D055_STATEMENT,
                D017_STATEMENT,
                "The account's listenKey is a singleton: no other process may run on the same "
                "account during the probe (research P7).",
            ],
            "outcome": self.outcome,
        }
        data: dict[str, Any] = jsonable(document)
        return data


# --------------------------------------------------------------------------- #
# Account state and the cleanup framework.
# --------------------------------------------------------------------------- #


def _rate_limit_reason(observation: ProbeObservation) -> str | None:
    error = observation.error
    if error is None:
        return None
    return _RATE_LIMIT_CATEGORIES.get(error.category)


def _raise_if_rate_limited(observation: ProbeObservation) -> None:
    """A 418 or 429 answer stops every further call of the run."""
    reason = _rate_limit_reason(observation)
    if reason is not None:
        raise ProbeBanned(
            reason, observation.error.retry_after_seconds if observation.error else None
        )


def _count(observation: ProbeObservation) -> int | None:
    if not observation.ok:
        return None
    try:
        value = int(observation.summary.get("count", ""))
    except ValueError:
        return None
    return value if value >= 0 else None


_POSITION_ROW_KEYS: tuple[str, ...] = ("symbol", "position_side", "position_amt")


def _position_rows(observation: ProbeObservation) -> list[dict[str, str]] | None:
    """The non-zero position rows (symbol, side, amount) or None when unreadable."""
    count = _count(observation)
    if count is None:
        return None
    rows: list[dict[str, str]] = []
    for index in range(count):
        row = {key: observation.summary.get(f"row_{index}_{key}", "") for key in _POSITION_ROW_KEYS}
        try:
            amount = Decimal(row["position_amt"])
        except InvalidOperation:
            return None
        if not amount.is_finite():
            return None
        if amount != 0:
            rows.append(row)
    return rows


async def _read_state(
    port: ProbePort, symbol: str
) -> tuple[dict[str, Any], dict[str, ProbeObservation]]:
    """Open orders, open algo orders and positions of `symbol`: a summary and the answers."""
    orders = await port.open_orders(symbol=symbol)
    _raise_if_rate_limited(orders)
    algo = await port.open_algo_orders(symbol=symbol)
    _raise_if_rate_limited(algo)
    positions = await port.positions(symbol=symbol)
    _raise_if_rate_limited(positions)
    rows = _position_rows(positions)
    readable = _count(orders) is not None and _count(algo) is not None and rows is not None
    summary: dict[str, Any] = {
        "open_orders": _count(orders),
        "open_algo_orders": _count(algo),
        "positions": rows if rows is not None else [],
        "readable": readable,
    }
    return summary, {"open_orders": orders, "open_algo_orders": algo, "positions": positions}


def _is_flat(summary: Mapping[str, Any]) -> bool:
    return (
        summary.get("readable") is True
        and summary.get("open_orders") == 0
        and summary.get("open_algo_orders") == 0
        and summary.get("positions") == []
    )


async def account_state(port: ProbePort, symbol: str) -> dict[str, Any]:
    """The account record before and after the probe: mode, orders, positions, balance."""
    mode = await port.position_mode()
    _raise_if_rate_limited(mode)
    summary, answers = await _read_state(port, symbol)
    balance = await port.account_balance()
    _raise_if_rate_limited(balance)
    flag = mode.summary.get("dual_side_position") if mode.ok else None
    dual_side = {_TRUE: True, _FALSE: False}.get(flag) if flag is not None else None
    return {
        "status": ACCOUNT_READ,
        "position_mode": mode,
        **answers,
        "balance": balance,
        "dual_side_position": dual_side,
        "remaining": summary,
        "flat": _is_flat(summary),
    }


async def cleanup_symbol(
    rig: ProbeRig,
    *,
    symbol: str,
    dual_side: bool | None,
    timeout_seconds: int,
    next_client_id: Callable[[], str],
) -> dict[str, Any]:
    """Cancel every normal and algo order, close a residual position, verify flat.

    The residual position is closed by ONE market order per non-zero row on the opposite
    side for the absolute amount: in one-way mode position side BOTH with reduce-only true; in
    hedge mode the row's position side without the reduce-only parameter (hedge mode rejects
    it). An unknown position mode sends no close. A re-read that is not flat is repeated once
    after `wait_up_to(rig, <flat>, timeout_seconds)`. A 418 or 429 answer raises `ProbeBanned`.
    """
    port = rig.port
    actions: list[ProbeObservation] = []
    notes: list[str] = []

    async def act(call: Awaitable[ProbeObservation]) -> ProbeObservation:
        observation = await call
        actions.append(observation)
        _raise_if_rate_limited(observation)
        return observation

    await act(port.cancel_all_open_orders(symbol=symbol))
    await act(port.cancel_all_algo_open_orders(symbol=symbol))
    positions = await act(port.positions(symbol=symbol))
    for row in _position_rows(positions) or []:
        amount = Decimal(row["position_amt"])
        if dual_side is None:
            notes.append("the position mode is unknown: no close order was sent")
            continue
        await act(
            port.new_market_order(
                symbol=symbol,
                side=SIDE_SELL if amount > 0 else SIDE_BUY,
                quantity=abs(amount),
                client_order_id=next_client_id(),
                position_side=row["position_side"] if dual_side else POSITION_SIDE_ONE_WAY,
                reduce_only=None if dual_side else True,
            )
        )

    remaining: dict[str, Any] = {}
    reads: list[int] = []

    async def flat_now() -> bool:
        summary, _ = await _read_state(port, symbol)
        reads.append(1)
        remaining.clear()
        remaining.update(summary)
        return _is_flat(summary)

    flat = await wait_up_to(rig, flat_now, timeout_seconds)
    return {
        "status": CLEANUP_FLAT if flat else CLEANUP_FAILED_STATUS,
        "actions": actions,
        "remaining": dict(remaining),
        "waited_seconds": timeout_seconds if len(reads) > 1 else 0,
        "notes": notes,
    }


# --------------------------------------------------------------------------- #
# The read-only cases (plan 18-17); plan 18-23 registers the cases that send orders.
# --------------------------------------------------------------------------- #


def _not_found_result(observation: ProbeObservation, probed: str) -> CaseResult:
    """The answer to an id that was never used, recorded as data (no decision is made)."""
    notes = (NOTE_UNEXPECTED_EXISTS,) if observation.ok else ()
    return CaseResult(
        status=OBSERVED,
        observations=(observation,),
        notes=notes,
        details={"probed_client_id": probed},
    )


async def case_get_order_not_found(context: CaseContext) -> CaseResult:
    """GET /fapi/v1/order for a client id this run never used."""
    probed = context.recorder.next_client_id("gonf")
    answer = await context.rig.port.query_order(
        symbol=context.config.symbol, client_order_id=probed
    )
    return _not_found_result(answer, probed)


async def case_get_algo_order_not_found(context: CaseContext) -> CaseResult:
    """GET /fapi/v1/algoOrder for a client algo id this run never used."""
    probed = context.recorder.next_client_id("ganf")
    answer = await context.rig.port.query_algo_order(client_algo_id=probed)
    return _not_found_result(answer, probed)


async def case_cancel_order_not_found(context: CaseContext) -> CaseResult:
    """DELETE /fapi/v1/order for a client id this run never used."""
    probed = context.recorder.next_client_id("conf")
    answer = await context.rig.port.cancel_order(
        symbol=context.config.symbol, client_order_id=probed
    )
    return _not_found_result(answer, probed)


async def case_cancel_algo_order_not_found(context: CaseContext) -> CaseResult:
    """DELETE /fapi/v1/algoOrder for a client algo id this run never used."""
    probed = context.recorder.next_client_id("canf")
    answer = await context.rig.port.cancel_algo_order(client_algo_id=probed)
    return _not_found_result(answer, probed)


# --------------------------------------------------------------------------- #
# The cases that send orders (plan 18-23): the write-case rules.
#
# Every write case runs through `run_write_case`, which applies the common rules: the
# position mode must be known; a reduce-only based case is NOT_OBSERVED in hedge mode; every
# order passes the one shared order bound (`order_bound_refusal`) before it is sent, and each
# handler checks every order it will send before the first one (so a refused case sends
# nothing and is ERROR); a script error becomes ERROR (the runner's cleanup still runs); a
# rate-limit answer stops the case (the runner then stops the run); a `ProbeBanned` ends the
# run after one cleanup attempt when the port reports no ban. No answer is ever retried.
# Prices are on the tick grid and quantities on the step grid of `symbol_filters`; every
# wait is one `wait_up_to` of the owner's `case_timeout_seconds`.
# --------------------------------------------------------------------------- #

WORKING_TYPE_MARK_PRICE = "MARK_PRICE"
TIME_IN_FORCE_GTC = "GTC"
ORDER_TYPE_STOP = "STOP"
ORDER_TYPE_STOP_MARKET = "STOP_MARKET"
ORDER_TYPE_TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"
POSITION_SIDE_LONG = "LONG"
POSITION_SIDE_SHORT = "SHORT"
# The time-in-force values the New Algo Order documentation lists (research B9, read
# 2026-10-15): the optional case sends one leg with each, one answer each.
DOCUMENTED_ALGO_TIME_IN_FORCE: tuple[str, ...] = ("GTC", "IOC", "FOK", "GTX", "GTD", "RPI")

ORDER_STATUS_FILLED = "FILLED"
ORDER_STATUS_PARTIALLY_FILLED = "PARTIALLY_FILLED"
ALGO_STATUS_NEW = "NEW"
# Algo statuses after NEW (research F3); "ended" ones close the lifecycle wait.
ALGO_LIFECYCLE_STATUSES: frozenset[str] = frozenset({"TRIGGERING", "TRIGGERED", "FINISHED"})
ALGO_ENDED_STATUSES: frozenset[str] = frozenset({"FINISHED", "CANCELED", "REJECTED", "EXPIRED"})
ALGO_ABSENT = "ABSENT"
EVENT_ALGO_UPDATE = "AlgoUpdateEvent"
EVENT_ORDER_UPDATE = "OrderUpdateEvent"
STREAM_STARTED = "STARTED"
CATEGORY_ORDER_ABSENT = "ORDER_ABSENT"

REASON_HEDGE_MODE = "hedge mode: reduceOnly cannot be sent"
REASON_POSITION_MODE_UNKNOWN = "the position mode is unknown: nothing was sent"
REASON_PREMISE_NOT_RUN = "premise case not run"
REASON_LEG_NOT_ACCEPTED = "pre-placed leg not accepted"
REASON_NO_PARTIAL = "every marketable entry filled completely at the approved size"
REASON_NO_ENTRY_FILLED = "no marketable entry of this run filled"
REASON_NO_STREAM = "no stream running"
REASON_NOT_TRIGGERED = "the trigger was not reached within case_timeout_seconds"

# The case whose leg the dependent D055 cases need, and the cases that open an entry.
PREPLACED_CASE = "preplaced_stop_reduce_only_flat"
ENTRY_CASES: tuple[str, ...] = ("id_reuse_after_filled", "full_fill_protective_quantity")


class OrderBoundRefused(Exception):  # noqa: N818 - a refusal, like ConfirmationRefused
    """An order above the owner's approved quantity or notional cap (nothing was sent)."""


class _StopCase(Exception):  # noqa: N818 - an internal signal: the case ends NOT_OBSERVED
    """The case cannot go on (unreadable market, rate-limit answer); `reason` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def order_bound_refusal(
    limits: DemoOrderLimits,
    *,
    quantity: Decimal | None,
    price: Decimal,
    step: Decimal | None = None,
    market_lot_probe: bool = False,
) -> str | None:
    """Why an order may not be sent under the owner's probe limits, or None (T-18-55).

    The one bound of every write case: the quantity is positive, on the step grid and never
    above the approved `quantity`, and `quantity * price` never exceeds `max_notional_quote`
    (`price` is the order's highest price: limit or trigger). A close-position order has no
    quantity (None) and passes the quantity rules. The single exception is the optional
    MARKET_LOT_SIZE case (`market_lot_probe`): its quantity must equal the owner-approved
    `market_lot_probe_quantity` exactly and the notional cap is not applied to it.
    """
    if not price.is_finite() or price <= 0:
        return f"the price {price} is not positive"
    if market_lot_probe:
        approved = limits.market_lot_probe_quantity
        if approved is None:
            return "market_lot_probe_quantity is not approved in the probe limits file"
        if quantity != approved:
            return f"quantity {quantity} is not the approved market_lot_probe_quantity {approved}"
        return None
    if quantity is None:
        return None
    if not quantity.is_finite() or quantity <= 0:
        return f"quantity {quantity} is not positive"
    if step is not None and quantity % step != 0:
        return f"quantity {quantity} is not on the step grid {step}"
    if quantity > limits.quantity:
        return f"quantity {quantity} is above the approved quantity {limits.quantity}"
    cap = limits.max_notional_quote
    if cap is None:
        return "max_notional_quote is not approved in the probe limits file"
    notional = quantity * price
    if notional > cap:
        return f"notional {notional} is above the approved cap {cap}"
    return None


def _flag_text(value: bool) -> str:
    return _TRUE if value else _FALSE


def _class_code(answer: ProbeObservation) -> str:
    """``<HTTP class> <code>`` of an error answer (the reason text of a rejected premise)."""
    error = answer.error
    if error is None:
        return "accepted"
    return f"{error.http_class} {error.code}"


def _brief(answer: ProbeObservation) -> str:
    """One line of an answer for `details`: the status of an accepted one, or the error."""
    if answer.ok:
        status = answer.summary.get("status") or answer.summary.get("algo_status")
        return f"accepted status={status}" if status else "accepted"
    error = answer.error
    if error is None:
        return "rejected"
    return f"rejected {error.http_class} {error.code} {error.category}: {error.message}"


def _positive_decimal(summary: Mapping[str, str], key: str) -> Decimal | None:
    text = summary.get(key)
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() and value > 0 else None


@dataclass(frozen=True)
class _Market:
    """The mark price and the filters of one case, read fresh from the exchange."""

    mark: Decimal
    tick: Decimal
    step: Decimal
    min_quantity: Decimal
    min_notional: Decimal | None
    multiplier_up: Decimal | None
    filters: Mapping[str, str]

    def floor(self, price: Decimal) -> Decimal:
        return (price / self.tick).to_integral_value(rounding=ROUND_FLOOR) * self.tick

    def far_below(self, fraction: Decimal) -> Decimal:
        """A far BUY or a flat protective trigger: mark times the fraction, on the tick grid."""
        return self.floor(self.mark * fraction)

    def far_above(self, fraction: Decimal) -> Decimal:
        """A far SELL or an up-trigger: mark times (2 minus the fraction), on the tick grid."""
        return self.floor(self.mark * (Decimal(2) - fraction))

    def just_below(self) -> Decimal:
        """The highest tick-grid price strictly below the mark (a trigger meant to trigger)."""
        above = (self.mark / self.tick).to_integral_value(rounding=ROUND_CEILING) * self.tick
        return above - self.tick

    def marketable_buy(self) -> Decimal:
        """A BUY limit that crosses the book: the PERCENT_PRICE upper bound of the mark.

        The port reads no order book, so the best ask is unknown; a BUY limit at the bound
        fills at the book's best ask and is the highest price the exchange accepts, which also
        bounds the notional check from above.
        """
        if self.multiplier_up is None:
            raise _StopCase("the PERCENT_PRICE filter is unreadable: no marketable price")
        return self.floor(self.mark * self.multiplier_up)

    def smallest_quantity(self) -> Decimal:
        """The minimum quantity of the lot-size filter, on the step grid."""
        steps = (self.min_quantity / self.step).to_integral_value(rounding=ROUND_CEILING)
        return steps * self.step


def _parse_market(mark: ProbeObservation, filters: ProbeObservation) -> _Market:
    if not mark.ok:
        raise _StopCase(f"the mark price is unreadable: {_class_code(mark)}")
    if not filters.ok or filters.summary.get("found") != _TRUE:
        raise _StopCase(f"the symbol filters are unreadable: {_class_code(filters)}")
    close = _positive_decimal(mark.summary, "close")
    tick = _positive_decimal(filters.summary, "tick_size")
    step = _positive_decimal(filters.summary, "step_size")
    min_quantity = _positive_decimal(filters.summary, "min_quantity")
    if close is None or tick is None or step is None or min_quantity is None:
        raise _StopCase("the mark price, tick size, step size or minimum quantity is unreadable")
    return _Market(
        mark=close,
        tick=tick,
        step=step,
        min_quantity=min_quantity,
        min_notional=_positive_decimal(filters.summary, "min_notional"),
        multiplier_up=_positive_decimal(filters.summary, "percent_price_multiplier_up"),
        filters=dict(filters.summary),
    )


class _WriteCase:
    """One running write case: its answers, details, the orders it placed, the bound check."""

    def __init__(self, context: CaseContext, case_id: str) -> None:
        self.context = context
        self.case_id = case_id
        self.rig = context.rig
        self.port = context.rig.port
        self.symbol = context.config.symbol
        self.limits = context.config.order_limits
        self.marker = self.port.marker()
        self.observations: list[ProbeObservation] = []
        self.notes: list[str] = []
        self.details: dict[str, str] = {}
        self.open_orders: list[str] = []
        self.open_algos: list[str] = []
        self.entry_sent = False
        self.step: Decimal | None = None

    # ----- settings ------------------------------------------------------------ #

    @property
    def quantity(self) -> Decimal:
        return self.limits.quantity

    @property
    def fraction(self) -> Decimal:
        return self.limits.far_price_fraction

    @property
    def case_timeout_seconds(self) -> int:
        """The owner's `case_timeout_seconds`: the only wait number of a write case."""
        value = self.limits.case_timeout_seconds
        if value is None:
            raise ValueError("case_timeout_seconds is not set in the probe limits file")
        return value

    @property
    def hedge_mode(self) -> bool:
        return self.context.recorder.dual_side is True

    def client_id(self, tag: str) -> str:
        return self.context.recorder.next_client_id(tag)

    def position_side(self, *, long: bool) -> str:
        """BOTH in one-way mode; LONG or SHORT (the position the order concerns) in hedge mode."""
        if not self.hedge_mode:
            return POSITION_SIDE_ONE_WAY
        return POSITION_SIDE_LONG if long else POSITION_SIDE_SHORT

    # ----- results --------------------------------------------------------------- #

    def result(self, status: str, reason: str | None = None) -> CaseResult:
        return CaseResult(
            status=status,
            observations=tuple(self.observations),
            reason=reason,
            notes=tuple(self.notes),
            details=dict(self.details),
        )

    def observed(self) -> CaseResult:
        return self.result(OBSERVED)

    def not_observed(self, reason: str) -> CaseResult:
        return self.result(NOT_OBSERVED, reason)

    def detail(self, key: str, value: str) -> None:
        name, index = key, 1
        while name in self.details:
            index += 1
            name = f"{key}_{index}"
        self.details[name] = value

    def known_state(self) -> dict[str, str]:
        """What this case last knew it left open (recorded when a ban stops the run)."""
        return {
            "orders_not_known_closed": ",".join(self.open_orders),
            "algo_orders_not_known_closed": ",".join(self.open_algos),
            "entry_sent": _flag_text(self.entry_sent),
        }

    # ----- the exchange ------------------------------------------------------------ #

    async def ask(self, label: str, call: Awaitable[ProbeObservation]) -> ProbeObservation:
        """Send one request (never retried); its answer is data; a rate limit stops the case."""
        answer = await call
        self.observations.append(answer)
        self.detail(label, _brief(answer))
        reason = _rate_limit_reason(answer)
        if reason is not None:
            raise _StopCase(f"a rate-limit answer ({reason}) stopped the case")
        return answer

    async def market(self) -> _Market:
        """The fresh mark price and filters (read, not recorded as case answers)."""
        mark = await self.port.mark_price(symbol=self.symbol)
        _raise_if_rate_limited(mark)
        filters = await self.port.symbol_filters(symbol=self.symbol)
        _raise_if_rate_limited(filters)
        market = _parse_market(mark, filters)
        self.step = market.step
        self.detail("mark_price", format(market.mark, "f"))
        return market

    def check_bounds(
        self,
        orders: Sequence[tuple[Decimal | None, Decimal]],
        *,
        market_lot_probe: bool = False,
    ) -> None:
        """Refuse (OrderBoundRefused) unless every (quantity, price) passes the order bound."""
        for quantity, price in orders:
            refusal = order_bound_refusal(
                self.limits,
                quantity=quantity,
                price=price,
                step=None if market_lot_probe else self.step,
                market_lot_probe=market_lot_probe,
            )
            if refusal is not None:
                raise OrderBoundRefused(refusal)

    async def limit(
        self,
        label: str,
        *,
        client_id: str,
        side: str,
        price: Decimal,
        long: bool = True,
    ) -> ProbeObservation:
        """A GTC LIMIT of the approved quantity (bound-checked again just before sending)."""
        self.check_bounds([(self.quantity, price)])
        answer = await self.ask(
            label,
            self.port.new_limit_order(
                symbol=self.symbol,
                side=side,
                quantity=self.quantity,
                price=price,
                client_order_id=client_id,
                position_side=self.position_side(long=long),
                time_in_force=TIME_IN_FORCE_GTC,
                reduce_only=None,
            ),
        )
        if answer.ok and answer.summary.get("status") != ORDER_STATUS_FILLED:
            self.open_orders.append(client_id)
        return answer

    async def conditional(
        self,
        label: str,
        *,
        client_id: str,
        side: str,
        order_type: str,
        trigger: Decimal,
        quantity: Decimal | None,
        reduce_only: bool | None = None,
        close_position: bool | None = None,
        price: Decimal | None = None,
        time_in_force: str | None = None,
        long: bool = True,
        market_lot_probe: bool = False,
    ) -> ProbeObservation:
        """One CONDITIONAL algo order on the mark price (bound-checked just before sending)."""
        highest = trigger if price is None else max(trigger, price)
        self.check_bounds([(quantity, highest)], market_lot_probe=market_lot_probe)
        answer = await self.ask(
            label,
            self.port.new_conditional_order(
                symbol=self.symbol,
                side=side,
                order_type=order_type,
                client_algo_id=client_id,
                position_side=self.position_side(long=long),
                trigger_price=trigger,
                working_type=WORKING_TYPE_MARK_PRICE,
                quantity=quantity,
                reduce_only=reduce_only,
                close_position=close_position,
                price=price,
                time_in_force=time_in_force,
            ),
        )
        if answer.ok and client_id not in self.open_algos:
            self.open_algos.append(client_id)
        return answer

    async def cancel(self, label: str, client_id: str) -> ProbeObservation:
        answer = await self.ask(
            label, self.port.cancel_order(symbol=self.symbol, client_order_id=client_id)
        )
        if answer.ok and client_id in self.open_orders:
            self.open_orders.remove(client_id)
        return answer

    async def cancel_algo(self, label: str, client_id: str) -> ProbeObservation:
        answer = await self.ask(label, self.port.cancel_algo_order(client_algo_id=client_id))
        if answer.ok and client_id in self.open_algos:
            self.open_algos.remove(client_id)
        return answer

    async def order_status(self, label: str, client_id: str) -> str:
        answer = await self.ask(
            label, self.port.query_order(symbol=self.symbol, client_order_id=client_id)
        )
        return answer.summary.get("status", "") if answer.ok else ""

    async def algo_status(self, label: str, client_id: str) -> str:
        """The algo status text; ABSENT when the exchange answers not-found; '' if unreadable."""
        answer = await self.ask(label, self.port.query_algo_order(client_algo_id=client_id))
        if answer.ok:
            return answer.summary.get("algo_status", "")
        error = answer.error
        return ALGO_ABSENT if error is not None and error.category == CATEGORY_ORDER_ABSENT else ""

    async def open_long(self, market: _Market, tag: str) -> tuple[ProbeObservation, str]:
        """A marketable BUY LIMIT of the approved quantity; one wait for FILLED.

        Returns the placement answer and the last status seen ('' when rejected or
        unreadable). Every status seen is in `details["entry_statuses"]`, so a dependent case
        can tell a partial fill from the run record.
        """
        client_id = self.client_id(tag)
        self.detail("entry_client_id", client_id)
        self.entry_sent = True
        placed = await self.limit(
            "entry", client_id=client_id, side=SIDE_BUY, price=market.marketable_buy()
        )
        if not placed.ok:
            return placed, ""
        statuses = [placed.summary.get("status", "")]

        async def filled() -> bool:
            statuses.append(await self.order_status("entry_status", client_id))
            return statuses[-1] == ORDER_STATUS_FILLED

        if statuses[0] != ORDER_STATUS_FILLED:
            await wait_up_to(self.rig, filled, self.case_timeout_seconds)
        self.detail("entry_statuses", ",".join(status or "unreadable" for status in statuses))
        if statuses[-1] == ORDER_STATUS_FILLED and client_id in self.open_orders:
            self.open_orders.remove(client_id)
        return placed, statuses[-1]

    def frames(self) -> list[dict[str, str]]:
        return self.port.frames_since(self.marker)

    def stream_started(self) -> bool:
        return self.context.recorder.stream.get("status") == STREAM_STARTED

    async def await_frames(self, match: Callable[[Mapping[str, str]], bool]) -> bool:
        """With a running stream, one wait (case timeout) for a matching frame; else False."""
        if not self.stream_started():
            return False

        async def seen() -> bool:
            return any(match(frame) for frame in self.frames())

        return await wait_up_to(self.rig, seen, self.case_timeout_seconds)

    async def reconcile(
        self,
        *,
        open_orders: int,
        open_algo_orders: int,
        position: Decimal,
    ) -> tuple[dict[str, Any], dict[str, ProbeObservation]]:
        """Snapshot open orders, open algo orders and positions against the expected state."""
        summary, answers = await _read_state(self.port, self.symbol)
        self.observations.extend(answers.values())
        held = sum((Decimal(row["position_amt"]) for row in summary["positions"]), Decimal(0))
        expected = (
            f"open_orders={open_orders} open_algo_orders={open_algo_orders} "
            f"position={format(position, 'f')}"
        )
        observed = (
            f"open_orders={summary['open_orders']} open_algo_orders={summary['open_algo_orders']} "
            f"position={format(held, 'f')}"
        )
        matches = (
            summary["readable"] is True
            and summary["open_orders"] == open_orders
            and summary["open_algo_orders"] == open_algo_orders
            and held == position
        )
        self.detail("reconciliation_expected", expected)
        self.detail("reconciliation_observed", observed)
        self.detail("reconciliation_matches", _flag_text(matches))
        return summary, answers


WriteBody = Callable[[_WriteCase], Awaitable[CaseResult]]


def _port_reports_ban(port: ProbePort) -> bool:
    """The port's ban flag; a port without a readable flag counts as banned (fail closed)."""
    flag = getattr(port, "banned", None)
    return flag is not False


async def _after_ban(case: _WriteCase, ban: ProbeBanned) -> None:
    """Record the ban of a write case and attempt the cleanup once if the port reports none."""
    context = case.context
    record: dict[str, Any] = {
        "reason": ban.reason,
        "retry_after_seconds": ban.retry_after_seconds,
        "during": case.case_id,
        "case_observations": list(case.observations),
        "known_state": case.known_state(),
    }
    if _port_reports_ban(case.port):
        record["cleanup_after_ban"] = {
            "status": CLEANUP_NOT_VERIFIED,
            "reason": "not attempted: the adapter reports a ban",
        }
    else:
        try:
            record["cleanup_after_ban"] = await cleanup_symbol(
                case.rig,
                symbol=case.symbol,
                dual_side=context.recorder.dual_side,
                timeout_seconds=case.limits.cleanup_timeout_seconds,
                next_client_id=lambda: context.recorder.next_client_id("flat"),
            )
        except ProbeBanned as again:
            record["cleanup_after_ban"] = {
                "status": CLEANUP_NOT_VERIFIED,
                "reason": f"refused: {again.reason}",
            }
        except Exception as exc:  # recorded; the run is stopping anyway
            record["cleanup_after_ban"] = {
                "status": CLEANUP_NOT_VERIFIED,
                "reason": f"the cleanup raised {type(exc).__name__}",
            }
    if context.recorder.ban is None:
        context.recorder.ban = record


async def run_write_case(
    context: CaseContext, body: WriteBody, *, case_id: str, reduce_only: bool
) -> CaseResult:
    """Run one write case under the common rules; it returns a result and never raises,
    except `ProbeBanned` (the run stops: plan 18-17's contract)."""
    dual_side = context.recorder.dual_side
    if dual_side is None:
        return CaseResult(status=NOT_OBSERVED, reason=REASON_POSITION_MODE_UNKNOWN)
    if reduce_only and dual_side:
        return CaseResult(status=NOT_OBSERVED, reason=REASON_HEDGE_MODE)
    case = _WriteCase(context, case_id)
    try:
        return await body(case)
    except _StopCase as stop:
        return case.not_observed(stop.reason)
    except OrderBoundRefused as refused:
        return case.result(ERROR, f"order bound: {refused} (nothing more was sent)")
    except ProbeBanned as ban:
        await _after_ban(case, ban)
        raise
    except Exception as exc:  # a script error: recorded, the runner's cleanup still runs
        return case.result(ERROR, f"script error: {type(exc).__name__}")


def _premise_leg(context: CaseContext) -> str | None:
    """None when the pre-placed leg of this run was accepted, else the NOT_OBSERVED reason."""
    premise = context.recorder.results.get(PREPLACED_CASE)
    if premise is None:
        return REASON_PREMISE_NOT_RUN
    if premise.status != OBSERVED or premise.details.get("leg_accepted") != _TRUE:
        return REASON_LEG_NOT_ACCEPTED
    return None


# ----- Task 1: the carrier cases ------------------------------------------------ #


async def _place_carrier(
    case: _WriteCase, market: _Market, label: str, client_id: str
) -> ProbeObservation:
    """The far carrier: a STOP BUY with the up-trigger far above the mark, not reduce-only."""
    trigger = market.far_above(case.fraction)
    return await case.conditional(
        label,
        client_id=client_id,
        side=SIDE_BUY,
        order_type=ORDER_TYPE_STOP,
        trigger=trigger,
        price=trigger,
        quantity=case.quantity,
    )


async def _duplicate_client_algo_id(case: _WriteCase) -> CaseResult:
    market = await case.market()
    case.check_bounds([(case.quantity, market.far_above(case.fraction))])
    client_id = case.client_id("dup")
    case.detail("client_algo_id", client_id)
    carrier = await _place_carrier(case, market, "carrier", client_id)
    if not carrier.ok:
        return case.not_observed(f"carrier rejected: {_class_code(carrier)}")
    duplicate = await _place_carrier(case, market, "duplicate", client_id)
    case.detail("duplicate_accepted", _flag_text(duplicate.ok))
    await case.cancel_algo("carrier_cancel", client_id)
    return case.observed()


async def _id_reuse_after_canceled_normal(case: _WriteCase) -> CaseResult:
    market = await case.market()
    price = market.far_below(case.fraction)
    case.check_bounds([(case.quantity, price)])
    client_id = case.client_id("rcn")
    case.detail("client_order_id", client_id)
    first = await case.limit("first", client_id=client_id, side=SIDE_BUY, price=price)
    if not first.ok:
        return case.not_observed(f"carrier rejected: {_class_code(first)}")
    canceled = await case.cancel("first_cancel", client_id)
    if not canceled.ok:
        return case.not_observed(f"the first order was not canceled: {_class_code(canceled)}")
    again = await case.limit("reuse", client_id=client_id, side=SIDE_BUY, price=price)
    case.detail("reuse_accepted", _flag_text(again.ok))
    if again.ok:
        await case.cancel("reuse_cancel", client_id)
    return case.observed()


async def _id_reuse_after_canceled_algo(case: _WriteCase) -> CaseResult:
    market = await case.market()
    case.check_bounds([(case.quantity, market.far_above(case.fraction))])
    client_id = case.client_id("rca")
    case.detail("client_algo_id", client_id)
    first = await _place_carrier(case, market, "carrier", client_id)
    if not first.ok:
        return case.not_observed(f"carrier rejected: {_class_code(first)}")
    canceled = await case.cancel_algo("carrier_cancel", client_id)
    if not canceled.ok:
        return case.not_observed(f"the carrier was not canceled: {_class_code(canceled)}")
    again = await _place_carrier(case, market, "reuse", client_id)
    case.detail("reuse_accepted", _flag_text(again.ok))
    if again.ok:
        await case.cancel_algo("reuse_cancel", client_id)
    return case.observed()


async def _id_reuse_after_filled(case: _WriteCase) -> CaseResult:
    market = await case.market()
    far = market.far_below(case.fraction)
    case.check_bounds([(case.quantity, market.marketable_buy()), (case.quantity, far)])
    placed, status = await case.open_long(market, "rfl")
    if not placed.ok:
        return case.not_observed(f"entry rejected: {_class_code(placed)}")
    if status != ORDER_STATUS_FILLED:
        return case.not_observed(f"the entry did not fill: status {status or 'unreadable'}")
    client_id = case.details["entry_client_id"]
    again = await case.limit("reuse", client_id=client_id, side=SIDE_BUY, price=far)
    case.detail("reuse_accepted", _flag_text(again.ok))
    if again.ok:
        await case.cancel("reuse_cancel", client_id)
    return case.observed()


async def case_duplicate_client_algo_id(context: CaseContext) -> CaseResult:
    """A far carrier STOP, the same clientAlgoId again: both answers recorded."""
    return await run_write_case(
        context, _duplicate_client_algo_id, case_id="duplicate_client_algo_id", reduce_only=False
    )


async def case_id_reuse_after_canceled_normal(context: CaseContext) -> CaseResult:
    """A far BUY LIMIT, cancelled, the same client order id placed again."""
    return await run_write_case(
        context,
        _id_reuse_after_canceled_normal,
        case_id="id_reuse_after_canceled_normal",
        reduce_only=False,
    )


async def case_id_reuse_after_canceled_algo(context: CaseContext) -> CaseResult:
    """The far carrier, cancelled, the same clientAlgoId placed again."""
    return await run_write_case(
        context,
        _id_reuse_after_canceled_algo,
        case_id="id_reuse_after_canceled_algo",
        reduce_only=False,
    )


async def case_id_reuse_after_filled(context: CaseContext) -> CaseResult:
    """A marketable entry that fills, then its client id placed again as a far LIMIT."""
    return await run_write_case(
        context, _id_reuse_after_filled, case_id="id_reuse_after_filled", reduce_only=False
    )


# The registry the runner walks in CASE_ORDER. A handler never raises for an exchange answer
# (answers are data); `ProbeBanned` propagates on purpose (the run stops) and any other
# exception is a bug the runner records as ERROR.
CASE_HANDLERS: dict[str, CaseHandler] = {
    "get_order_not_found": case_get_order_not_found,
    "get_algo_order_not_found": case_get_algo_order_not_found,
    "cancel_order_not_found": case_cancel_order_not_found,
    "cancel_algo_order_not_found": case_cancel_algo_order_not_found,
    "duplicate_client_algo_id": case_duplicate_client_algo_id,
    "id_reuse_after_canceled_normal": case_id_reuse_after_canceled_normal,
    "id_reuse_after_canceled_algo": case_id_reuse_after_canceled_algo,
    "id_reuse_after_filled": case_id_reuse_after_filled,
}


# --------------------------------------------------------------------------- #
# The runner.
# --------------------------------------------------------------------------- #


def _fixture_stem(case_id: str, index: int, payload: object) -> str:
    event = payload.get("e") if isinstance(payload, Mapping) else None
    name = _FIXTURE_EVENT_RE.sub("_", str(event)) if isinstance(event, str) and event else "UNKNOWN"
    return f"{case_id}-{index:03d}-{name}"


class _ProbeRun:
    """One walk of the case registry over a rig; `run()` returns the exit code."""

    def __init__(
        self,
        config: ProbeConfig,
        rig: ProbeRig,
        recorder: ProbeRecorder,
        redactor: TextScrubber,
    ) -> None:
        self.config = config
        self.rig = rig
        self.recorder = recorder
        self.redactor = redactor
        self.context = CaseContext(rig=rig, config=config, recorder=recorder)
        self.dry_run = config.mode == MODE_DRY_RUN
        self.banned = False
        self.aborted_no_order = False
        self.crashed = False
        self.cleanup_allowed = False
        self.stream_live = False
        self.stream_reason = "no user-data stream in this rig"
        self.case_cleanup_failed = False

    def now(self) -> datetime:
        return _checked_now(self.rig)

    def _note_ban(self, reason: str, retry_after: int | None, where: str) -> None:
        self.banned = True
        if self.recorder.ban is None:
            self.recorder.ban = {
                "reason": reason,
                "retry_after_seconds": retry_after,
                "during": where,
            }

    def _failure(self, where: str, exc: BaseException) -> None:
        self.recorder.failures.append({"during": where, "error": type(exc).__name__})

    async def _start_stream(self) -> None:
        stream = self.rig.stream
        if stream is None:
            self.stream_reason = (
                "dry run: no user-data stream runs"
                if self.dry_run
                else "no user-data stream in this rig"
            )
            self.recorder.stream = {"status": NOT_RUN, "reason": self.stream_reason}
            return
        try:
            await stream.start()
        except Exception as exc:  # the cases still run; every frame field is NOT_OBSERVED
            self._failure("stream_start", exc)
            self.stream_reason = f"the user-data stream did not start: {type(exc).__name__}"
            self.recorder.stream = {"status": "NOT_STARTED", "reason": self.stream_reason}
            return
        self.stream_live = True
        self.recorder.stream = {"status": "STARTED"}

    async def _stop_stream(self) -> None:
        stream = self.rig.stream
        if stream is None or not self.stream_live:
            return
        try:
            await stream.stop()
        except Exception as exc:
            self._failure("stream_stop", exc)
            self.recorder.stream["stop"] = f"failed: {type(exc).__name__}"
        else:
            self.recorder.stream["stop"] = "stopped"

    async def _account_before(self) -> None:
        state = await account_state(self.rig.port, self.config.symbol)
        self.recorder.account_before = state
        self.recorder.dual_side = state["dual_side_position"]
        if not state["flat"] or state["dual_side_position"] is None:
            raise _AbortNoOrder
        self.cleanup_allowed = True

    async def _market(self) -> None:
        port = self.rig.port
        mark = await port.mark_price(symbol=self.config.symbol)
        _raise_if_rate_limited(mark)
        filters = await port.symbol_filters(symbol=self.config.symbol)
        _raise_if_rate_limited(filters)
        self.recorder.market = {
            "status": ACCOUNT_READ,
            "mark_price": mark,
            "symbol_filters": filters,
        }

    async def _cleanup(self) -> dict[str, Any]:
        timeout = self.config.order_limits.cleanup_timeout_seconds
        return await cleanup_symbol(
            self.rig,
            symbol=self.config.symbol,
            dual_side=self.recorder.dual_side,
            timeout_seconds=timeout,
            next_client_id=lambda: self.recorder.next_client_id("flat"),
        )

    def _frames(self, case_id: str, marker: int) -> dict[str, Any]:
        if not self.stream_live:
            return {
                "status": NOT_OBSERVED,
                "reason": self.stream_reason,
                "events": [],
                "stream_states": [],
            }
        port = self.rig.port
        record: dict[str, Any] = {
            "status": OBSERVED,
            "events": port.frames_since(marker),
            "stream_states": port.stream_states_since(marker),
        }
        if self.config.fixtures_dir is not None:
            names: list[str] = []
            for index, payload in enumerate(port.raw_frames_since(marker), start=1):
                document = payload if isinstance(payload, Mapping) else {"payload": payload}
                path = write_evidence_atomic(
                    self.config.fixtures_dir,
                    _fixture_stem(case_id, index, payload),
                    document,
                    self.redactor,
                )
                names.append(path.name)
            record["fixtures"] = names
            self.recorder.fixtures.extend(names)
        return record

    def _planned(self) -> list[dict[str, Any]]:
        planned = self.rig.planned
        return [dict(item) for item in planned()] if planned is not None else []

    def _record(
        self,
        case_id: str,
        result: CaseResult,
        *,
        registered: bool,
        started: datetime,
        finished: datetime,
        planned: list[dict[str, Any]],
        cleanup: Mapping[str, Any],
        frames: Mapping[str, Any],
    ) -> None:
        self.recorder.results[case_id] = result
        self.recorder.records[case_id] = {
            "case_id": case_id,
            "status": result.status,
            "reason": result.reason,
            "observations": list(result.observations),
            "notes": list(result.notes),
            "details": dict(result.details),
            "handler_registered": registered,
            "planned_requests": planned,
            "started_utc": started,
            "finished_utc": finished,
            "cleanup": dict(cleanup),
            "frames": dict(frames),
        }

    def _record_not_run(self, case_id: str, reason: str) -> None:
        moment = self.now()
        self._record(
            case_id,
            CaseResult(status=NOT_OBSERVED, reason=reason),
            registered=case_id in CASE_HANDLERS,
            started=moment,
            finished=moment,
            planned=[],
            cleanup={"status": CLEANUP_NOT_RUN, "reason": reason},
            frames={"status": NOT_OBSERVED, "reason": reason, "events": [], "stream_states": []},
        )

    async def _run_case(self, case_id: str) -> None:
        handler = CASE_HANDLERS.get(case_id)
        started = self.now()
        if handler is None:
            result = (
                CaseResult(status=NOT_REHEARSED, reason=REASON_DRY_RUN)
                if self.dry_run
                else CaseResult(status=ERROR, reason=REASON_NO_HANDLER)
            )
            reason = "no handler was invoked"
            self._record(
                case_id,
                result,
                registered=False,
                started=started,
                finished=started,
                planned=[],
                cleanup={"status": CLEANUP_NOT_RUN, "reason": reason},
                frames={
                    "status": NOT_OBSERVED,
                    "reason": reason,
                    "events": [],
                    "stream_states": [],
                },
            )
            return
        port = self.rig.port
        marker = port.marker()
        planned_before = len(self._planned())
        try:
            result = await handler(self.context)
            if not isinstance(result, CaseResult):
                result = CaseResult(
                    status=ERROR, reason=f"the handler returned {type(result).__name__}"
                )
        except ProbeBanned as ban:
            self._note_ban(ban.reason, ban.retry_after_seconds, case_id)
            result = CaseResult(status=NOT_OBSERVED, reason=REASON_BAN)
        except Exception as exc:  # a handler bug: recorded, the run continues
            self._failure(case_id, exc)
            result = CaseResult(status=ERROR, reason=f"the handler raised {type(exc).__name__}")
        finished = self.now()
        for observation in result.observations:
            limit_reason = _rate_limit_reason(observation)
            if limit_reason is not None and not self.banned:
                error = observation.error
                self._note_ban(limit_reason, error.retry_after_seconds if error else None, case_id)
        planned = self._planned()[planned_before:]
        if self.banned:
            cleanup: dict[str, Any] = {"status": CLEANUP_NOT_VERIFIED, "reason": REASON_BAN}
        else:
            try:
                cleanup = await self._cleanup()
            except ProbeBanned as ban:
                self._note_ban(ban.reason, ban.retry_after_seconds, f"cleanup after {case_id}")
                cleanup = {"status": CLEANUP_NOT_VERIFIED, "reason": REASON_BAN}
            if cleanup["status"] != CLEANUP_FLAT:
                self.case_cleanup_failed = True
        self._record(
            case_id,
            result,
            registered=True,
            started=started,
            finished=finished,
            planned=planned,
            cleanup=cleanup,
            frames=self._frames(case_id, marker),
        )

    async def _final(self) -> None:
        if not self.cleanup_allowed:
            return
        if self.banned:
            self.recorder.final_cleanup = {
                "status": CLEANUP_NOT_VERIFIED,
                "reason": "a ban or rate limit stopped every REST call; verify the Demo "
                "account by hand",
            }
            self.recorder.account_after = {"status": NOT_RUN, "reason": REASON_BAN}
            return
        try:
            self.recorder.final_cleanup = await self._cleanup()
            self.recorder.account_after = await account_state(self.rig.port, self.config.symbol)
        except ProbeBanned as ban:
            self._note_ban(ban.reason, ban.retry_after_seconds, "final cleanup")
            if self.recorder.final_cleanup.get("status") == CLEANUP_NOT_RUN:
                self.recorder.final_cleanup = {"status": CLEANUP_NOT_VERIFIED, "reason": REASON_BAN}
            self.recorder.account_after = {"status": NOT_RUN, "reason": REASON_BAN}
        except Exception as exc:
            self.crashed = True
            self._failure("final cleanup", exc)
            if self.recorder.final_cleanup.get("status") == CLEANUP_NOT_RUN:
                self.recorder.final_cleanup = {
                    "status": CLEANUP_NOT_VERIFIED,
                    "reason": f"the cleanup raised {type(exc).__name__}",
                }

    def _write_provenance(self, directory: Path, names: Sequence[str]) -> None:
        """List the run's fixture files in `provenance.md` with their label (appended)."""
        label = FIXTURE_LABEL_DRY_RUN if self.dry_run else FIXTURE_LABEL_EXECUTE
        started = self.recorder.started_utc
        stamp = _utc_stamp(started) if started is not None else "unknown"
        provenance = directory / "provenance.md"
        lines = [] if provenance.exists() else ["# Provenance of the Demo probe frames", ""]
        lines.append(
            f"## {self.config.mode} run of {stamp} ({self.config.environment.value}, "
            "scripts/demo_probe.py)"
        )
        lines.append("")
        lines.extend(f"- `{name}`: {label}" for name in names)
        lines.append("")
        with provenance.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")

    def _outcome(self) -> tuple[str, int]:
        if self.aborted_no_order:
            return OUTCOME_ABORTED_NO_ORDER, EXIT_ABORTED
        if self.banned:
            return OUTCOME_ABORTED_BAN, EXIT_FAILED
        if self.recorder.final_cleanup.get("status") != CLEANUP_FLAT:
            return OUTCOME_CLEANUP_FAILED, EXIT_FAILED
        failed = (
            self.crashed
            or self.case_cleanup_failed
            or any(result.status == ERROR for result in self.recorder.results.values())
        )
        return (OUTCOME_FAILED, EXIT_FAILED) if failed else (OUTCOME_COMPLETE, EXIT_OK)

    async def run(self) -> int:
        recorder = self.recorder
        recorder.started_utc = self.now()  # a naive clock is refused before any port call
        recorder.mode = self.config.mode
        recorder.real = self.rig.real
        reason_left = REASON_BAN
        try:
            await self._start_stream()
            await self._account_before()
            await self._market()
            for case_id in self.config.case_ids:
                if self.banned:
                    break
                await self._run_case(case_id)
        except _AbortNoOrder:
            self.aborted_no_order = True
            reason_left = REASON_NOT_FLAT_BEFORE
        except ProbeBanned as ban:
            self._note_ban(ban.reason, ban.retry_after_seconds, "run")
        except Exception as exc:
            self.crashed = True
            self._failure("run", exc)
            reason_left = f"run aborted: {type(exc).__name__}"
        finally:
            await self._final()
            await self._stop_stream()
            if self.rig.live_calls is not None:
                recorder.live_port_calls = self.rig.live_calls()
            recorder.finished_utc = self.now()
        for case_id in self.config.case_ids:
            if case_id not in recorder.records:
                self._record_not_run(case_id, REASON_BAN if self.banned else reason_left)
        if self.config.fixtures_dir is not None and recorder.fixtures:
            self._write_provenance(self.config.fixtures_dir, recorder.fixtures)
        recorder.finished_utc = self.now()
        outcome, code = self._outcome()
        recorder.outcome = outcome
        if outcome in (OUTCOME_CLEANUP_FAILED, OUTCOME_ABORTED_BAN) and self.cleanup_allowed:
            print(
                OPERATOR_CLEANUP_NOTE.format(outcome=outcome, symbol=self.config.symbol),
                file=sys.stderr,
            )
        return code


async def run_probe(
    config: ProbeConfig,
    rig: ProbeRig,
    recorder: ProbeRecorder,
    *,
    redactor: TextScrubber | None = None,
) -> int:
    """Walk `config.case_ids` over `rig`, recording into `recorder`; return the exit code.

    The caller writes `recorder.document(config)`. Raises ValueError when the rig clock is not
    aware UTC (before any port call).
    """
    run = _ProbeRun(config, rig, recorder, redactor if redactor is not None else Redactor(None))
    return await run.run()


# --------------------------------------------------------------------------- #
# The live path: guarded port, frame log, stream, live rig (executed runs only).
# --------------------------------------------------------------------------- #

Guard = Callable[[], None]


class MutationRefused(Exception):  # noqa: N818 - a refusal, like ConfirmationRefused
    """A mutating operation was asked of a dry-run guarded port (nothing was sent)."""


class PositionModeReader(Protocol):
    """The position-mode read of `BinanceUsdmAdapter`."""

    async def get_position_mode(self) -> PositionModeResult: ...


def _evidence_text(value: object) -> str:
    if isinstance(value, bool):
        return _TRUE if value else _FALSE
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


# The typed-event fields copied into a case's frame record, by name (nothing else is copied).
_EVENT_FIELDS: tuple[str, ...] = (
    "symbol",
    "client_order_id",
    "exchange_order_id",
    "side",
    "position_side",
    "order_type",
    "original_order_type",
    "time_in_force",
    "execution_type",
    "order_status",
    "original_quantity",
    "original_price",
    "stop_price",
    "last_filled_quantity",
    "accumulated_filled_quantity",
    "last_filled_price",
    "trade_id",
    "reduce_only",
    "close_position",
    "working_type",
    "expire_reason",
    "client_algo_id",
    "algo_id",
    "algo_type",
    "algo_status",
    "actual_order_id",
    "actual_order_type",
    "executed_quantity",
    "trigger_price",
    "reject_reason",
    "reason",
    "kind",
    "event_name",
    "field",
)


def event_record(event: TrustedEvent) -> dict[str, str]:
    """A typed stream event as text: its type, the gap flags and the named fields present."""
    outcome = event.outcome
    record = {
        "event_type": type(outcome).__name__,
        "after_gap": _evidence_text(event.after_gap),
        "connection_epoch": _evidence_text(event.connection_epoch),
        "received_at_utc": _evidence_text(event.received_at_utc),
    }
    for name in _EVENT_FIELDS:
        value = getattr(outcome, name, None)
        if value is not None:
            record[name] = _evidence_text(value)
    if isinstance(outcome, StreamAnomaly):
        record["anomaly"] = _TRUE
    return record


class FrameLog:
    """Typed events, raw payloads and stream states with one shared sequence number."""

    def __init__(self) -> None:
        self._sequence = 0
        self._events: list[tuple[int, dict[str, str]]] = []
        self._raw: list[tuple[int, object]] = []
        self._states: list[tuple[int, str]] = []

    def _next(self) -> int:
        self._sequence += 1
        return self._sequence

    def marker(self) -> int:
        return self._sequence

    def add_event(self, record: Mapping[str, str]) -> None:
        self._events.append((self._next(), dict(record)))

    def add_raw(self, payload: object) -> None:
        self._raw.append((self._next(), payload))

    def add_state(self, state: str) -> None:
        self._states.append((self._next(), state))

    def events_since(self, marker: int) -> list[dict[str, str]]:
        return [dict(record) for seq, record in self._events if seq > marker]

    def raw_since(self, marker: int) -> list[object]:
        return [payload for seq, payload in self._raw if seq > marker]

    def states_since(self, marker: int) -> list[str]:
        return [state for seq, state in self._states if seq > marker]


def _position_mode_failure(exc: Exception) -> ProbeObservation:
    """A failed position-mode read as data: class, int code, category, the type name."""
    facts = error_facts_from_exception(exc)
    category = classify(facts, CallKind.QUERY)
    return ProbeObservation(
        operation="position_mode",
        ok=False,
        summary={},
        error=ErrorObservation(
            http_class=facts.http_class.value,
            code=facts.code,
            retry_after_seconds=facts.retry_after_seconds,
            category=category.value,
            message=type(exc).__name__,
        ),
    )


class GuardedProbePort:
    """The probe port of an executed run; the environment guard runs before every call.

    Explicit delegation only (no attribute passthrough), like the rehearsal's
    `GuardedAdapter`: in dry-run mode a mutating operation raises `MutationRefused` before
    the inner adapter is reached. `adapter` is the `BinanceProbeAdapter` (or a fake with its
    operations), `position_mode_reader` the production adapter's position-mode read, `frames`
    the run's frame log and `drop_transport` the private-connection drop of the stream.
    """

    def __init__(
        self,
        adapter: Any,
        *,
        position_mode_reader: PositionModeReader,
        frames: FrameLog,
        guard: Guard,
        mode: str,
        drop_transport: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode!r}")
        self._adapter = adapter
        self._reader = position_mode_reader
        self._frames = frames
        self._guard = guard
        self._mode = mode
        self._drop = drop_transport
        self.call_count = 0
        self.mutating_attempts = 0

    def _enter(self, operation: str) -> None:
        self._guard()
        if operation in MUTATING_OPERATIONS and self._mode != MODE_EXECUTE:
            self.mutating_attempts += 1
            raise MutationRefused(f"{operation} is not reachable in a dry run")
        self.call_count += 1

    # ----- per-case queries ---------------------------------------------------- #

    async def query_order(self, *, symbol: str, client_order_id: str) -> ProbeObservation:
        self._enter("query_order")
        result: ProbeObservation = await self._adapter.query_order(
            symbol=symbol, client_order_id=client_order_id
        )
        return result

    async def query_algo_order(self, *, client_algo_id: str) -> ProbeObservation:
        self._enter("query_algo_order")
        result: ProbeObservation = await self._adapter.query_algo_order(
            client_algo_id=client_algo_id
        )
        return result

    # ----- mutating operations ------------------------------------------------- #

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
        self._enter("new_limit_order")
        result: ProbeObservation = await self._adapter.new_limit_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            client_order_id=client_order_id,
            position_side=position_side,
            time_in_force=time_in_force,
            reduce_only=reduce_only,
        )
        return result

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
        self._enter("new_market_order")
        result: ProbeObservation = await self._adapter.new_market_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            client_order_id=client_order_id,
            position_side=position_side,
            reduce_only=reduce_only,
        )
        return result

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
        self._enter("new_conditional_order")
        result: ProbeObservation = await self._adapter.new_conditional_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            client_algo_id=client_algo_id,
            position_side=position_side,
            trigger_price=trigger_price,
            working_type=working_type,
            quantity=quantity,
            reduce_only=reduce_only,
            close_position=close_position,
            price=price,
            time_in_force=time_in_force,
        )
        return result

    async def cancel_order(self, *, symbol: str, client_order_id: str) -> ProbeObservation:
        self._enter("cancel_order")
        result: ProbeObservation = await self._adapter.cancel_order(
            symbol=symbol, client_order_id=client_order_id
        )
        return result

    async def cancel_algo_order(self, *, client_algo_id: str) -> ProbeObservation:
        self._enter("cancel_algo_order")
        result: ProbeObservation = await self._adapter.cancel_algo_order(
            client_algo_id=client_algo_id
        )
        return result

    async def cancel_all_open_orders(self, *, symbol: str) -> ProbeObservation:
        self._enter("cancel_all_open_orders")
        result: ProbeObservation = await self._adapter.cancel_all_open_orders(symbol=symbol)
        return result

    async def cancel_all_algo_open_orders(self, *, symbol: str) -> ProbeObservation:
        self._enter("cancel_all_algo_open_orders")
        result: ProbeObservation = await self._adapter.cancel_all_algo_open_orders(symbol=symbol)
        return result

    # ----- state reads --------------------------------------------------------- #

    async def open_orders(self, *, symbol: str) -> ProbeObservation:
        self._enter("open_orders")
        result: ProbeObservation = await self._adapter.open_orders(symbol=symbol)
        return result

    async def open_algo_orders(self, *, symbol: str) -> ProbeObservation:
        self._enter("open_algo_orders")
        result: ProbeObservation = await self._adapter.open_algo_orders(symbol=symbol)
        return result

    async def positions(self, *, symbol: str) -> ProbeObservation:
        self._enter("positions")
        result: ProbeObservation = await self._adapter.positions(symbol=symbol)
        return result

    async def user_trades(self, *, symbol: str, order_id: int | None = None) -> ProbeObservation:
        self._enter("user_trades")
        result: ProbeObservation = await self._adapter.user_trades(symbol=symbol, order_id=order_id)
        return result

    async def account_balance(self) -> ProbeObservation:
        self._enter("account_balance")
        result: ProbeObservation = await self._adapter.account_balance()
        return result

    async def mark_price(self, *, symbol: str) -> ProbeObservation:
        self._enter("mark_price")
        result: ProbeObservation = await self._adapter.mark_price(symbol=symbol)
        return result

    async def symbol_filters(self, *, symbol: str) -> ProbeObservation:
        self._enter("symbol_filters")
        result: ProbeObservation = await self._adapter.symbol_filters(symbol=symbol)
        return result

    async def position_mode(self) -> ProbeObservation:
        """The account's position mode as an observation (`dual_side_position` true/false)."""
        self._enter("position_mode")
        try:
            mode = await self._reader.get_position_mode()
        except RestGateRefusal as refusal:
            raise ProbeBanned(refusal.reason, refusal.retry_after_seconds) from None
        except Exception as exc:  # an exchange error is data, like every probe answer
            return _position_mode_failure(exc)
        flag = _TRUE if mode.dual_side_position else _FALSE
        return ProbeObservation(
            operation="position_mode", ok=True, summary={"dual_side_position": flag}, error=None
        )

    # ----- the stream ---------------------------------------------------------- #

    def marker(self) -> int:
        return self._frames.marker()

    def frames_since(self, marker: int) -> list[dict[str, str]]:
        return self._frames.events_since(marker)

    def raw_frames_since(self, marker: int) -> list[object]:
        return self._frames.raw_since(marker)

    def stream_states_since(self, marker: int) -> list[str]:
        return self._frames.states_since(marker)

    async def drop_stream_transport(self) -> bool:
        if self._drop is None:
            return False
        self._guard()
        return await self._drop()


class _GuardedListenKeys:
    """The listenKey port with the environment guard before each call."""

    def __init__(self, inner: ListenKeyPort, guard: Guard) -> None:
        self._inner = inner
        self._guard = guard

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    async def start(self) -> str:
        self._guard()
        return await self._inner.start()

    async def keepalive(self) -> None:
        self._guard()
        await self._inner.keepalive()

    async def close(self) -> None:
        self._guard()
        await self._inner.close()


class _GuardedTransport:
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


class StreamNotLive(Exception):  # noqa: N818 - a condition of the run, recorded as data
    """The user-data stream did not reach LIVE; the cases still run without frames."""


class LiveStream:
    """The user-data supervisor of plan 18-14 with the raw-frame tap, for the whole run.

    Typed events, raw payloads and state names go to the run's `FrameLog`; `start` raises
    `StreamNotLive` (after stopping what it started) when the supervisor is not LIVE; `stop`
    stops with `close_listen_key=True`.
    """

    def __init__(
        self,
        *,
        transport: Any,
        listen_keys: Any,
        limits: StreamLimits,
        clock: Callable[[], datetime],
        sleep: Callable[[float], Awaitable[None]],
        rest_gate: RestRateLimitGate,
        snapshot_provider: Callable[[], Awaitable[object]],
        frames: FrameLog,
        guard: Guard,
    ) -> None:
        self._transport = transport
        self._listen_keys = listen_keys
        self._limits = limits
        self._clock = clock
        self._sleep = sleep
        self._rest_gate = rest_gate
        self._snapshot_provider = snapshot_provider
        self._frames = frames
        self._guard = guard
        self._exits = contextlib.ExitStack()
        self._supervisor: UserDataSupervisor | None = None
        self.failures: list[str] = []

    def _on_state(self, state: StreamState, reason: str) -> None:
        del reason
        self._frames.add_state(state.value)

    def _on_event(self, event: TrustedEvent) -> None:
        self._frames.add_event(event_record(event))

    def _on_snapshot(self, snapshot: StreamSnapshot, epoch: int) -> None:
        del snapshot, epoch

    def _on_failure(self, reason: str) -> None:
        self.failures.append(reason)

    async def start(self) -> None:
        self._guard()
        self._exits.enter_context(capture_raw_user_events(self._frames.add_raw))
        adapter = UserDataAdapter(
            transport=self._transport,
            listen_keys=self._listen_keys,
            limits=self._limits,
            clock=self._clock,
        )
        self._supervisor = UserDataSupervisor(
            adapter=adapter,
            limits=self._limits,
            clock=self._clock,
            sleep=self._sleep,
            rest_gate=self._rest_gate,
            snapshot_provider=self._snapshot_provider,
            on_state_change=self._on_state,
            on_event=self._on_event,
            on_snapshot=self._on_snapshot,
            on_failure=self._on_failure,
        )
        try:
            await self._supervisor.start()
        except BaseException:
            await self.stop()
            raise
        if self._supervisor.state is not StreamState.LIVE:
            await self.stop()
            raise StreamNotLive(", ".join(self.failures) or "the stream is not LIVE")

    async def stop(self) -> None:
        try:
            if self._supervisor is not None:
                await self._supervisor.stop(close_listen_key=True)
        finally:
            self._supervisor = None
            self._exits.close()


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


def _drop_transport(connection: Any) -> None:
    """End the TCP connection beneath an SDK connection without a WebSocket close handshake.

    Closes the aiohttp response that backs the connection's websocket, like a network
    failure (copied from `scripts/user_data_smoke.py`, which pins the attribute in a test).
    """
    connection.websocket._response.close()


def live_clock() -> datetime:
    """The only wall-clock read of the tool (executed runs only): aware UTC."""
    return datetime.now(UTC)


def build_live_rig(
    config: ProbeConfig,
    *,
    environ: Mapping[str, str],
    client_factory: Callable[..., Any] | None = None,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> ProbeRig:
    """The executed rig: credentials, the guarded SDK client and ONE shared REST gate.

    Constructed only in `--execute` mode, after the typed phrase. The SDK client comes from
    `build_sdk_client` (REST and WS_STREAMS, the ratified client limits); the presence of a
    LIVE credential variable refuses; `assert_environment` and the streams-URL check run
    before every call. One `RestRateLimitGate` (the ratified rate-limit policy, the rig
    clock) is shared by the probe adapter, its public reader, the position-mode reader, the
    listenKey port and the supervisor: a 418 ban or a 429 pause stops every REST call.
    """
    from binance_sdk_derivatives_trading_usds_futures.websocket_streams import (  # noqa: PLC0415
        DerivativesTradingUsdsFuturesWebSocketStreams,
    )
    from src.adapters.binance_usdm import BinanceUsdmAdapter  # noqa: PLC0415

    rig_clock = clock if clock is not None else live_clock
    rig_sleep = sleep if sleep is not None else asyncio.sleep
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
    gate = RestRateLimitGate(policy=limits.signed.rate_limit, clock=rig_clock)
    public = BinancePublicMarketData(sdk_client=bundle.client, rest_gate=gate)
    probe = BinanceProbeAdapter(
        bundle.client,
        policy=limits.signed,
        rest_gate=gate,
        public=public,
    )
    usdm = BinanceUsdmAdapter(
        bundle.client,
        rest_gate=gate,
        signed_call_policy=limits.signed,
        clock=rig_clock,
    )
    frames = FrameLog()
    listen_keys = _GuardedListenKeys(
        SdkListenKeyPort(bundle.client.rest_api, rest_gate=gate), guard
    )
    clients: list[Any] = []

    def ws_factory(configuration: ConfigurationWebSocketStreams) -> Any:
        client = DerivativesTradingUsdsFuturesWebSocketStreams(configuration)
        clients.append(client)
        return client

    transport = _GuardedTransport(
        SdkUserDataTransport(stream_config, client_factory=ws_factory), guard
    )
    install_sdk_noise_guard()

    async def snapshot() -> object:
        guard()
        orders = await usdm.snapshot_open_normal_orders(symbol=config.symbol)
        algo = await usdm.snapshot_open_algo_orders(symbol=config.symbol)
        positions = await usdm.snapshot_positions(symbol=config.symbol)
        return {
            "open_orders": len(orders),
            "open_algo_orders": len(algo),
            "positions": len(positions),
        }

    async def drop() -> bool:
        private = [
            connection
            for connection in (clients[-1].connections if clients else [])
            if connection.url_path == PRIVATE_URL_PATH
        ]
        if not private:
            return False
        _drop_transport(private[0])
        return True

    stream = LiveStream(
        transport=transport,
        listen_keys=listen_keys,
        limits=limits.stream,
        clock=rig_clock,
        sleep=rig_sleep,
        rest_gate=gate,
        snapshot_provider=snapshot,
        frames=frames,
        guard=guard,
    )
    port = GuardedProbePort(
        probe,
        position_mode_reader=usdm,
        frames=frames,
        guard=guard,
        mode=MODE_EXECUTE,
        drop_transport=drop,
    )
    return ProbeRig(
        port=port,
        clock=rig_clock,
        sleep=rig_sleep,
        real=True,
        stream=stream,
        live_calls=lambda: port.call_count,
    )


# --------------------------------------------------------------------------- #
# Dry run: the recording port on virtual time.
# --------------------------------------------------------------------------- #


def _load_fakes() -> Any:
    """Import the probe fakes lazily: only the dry run loads test code."""
    from tests import probe_fakes  # noqa: PLC0415

    return probe_fakes


def _load_virtual_time() -> Any:
    from tests.support import virtual_time  # noqa: PLC0415

    return virtual_time


def build_dry_run_rig(config: ProbeConfig) -> ProbeRig:
    """The dry rig: `RecordingProbePort` (FAKE market fixture) and `VirtualTime`.

    The sleep moves virtual time by itself (it never waits for another task and never
    sleeps in real time); nothing reads credentials or opens a connection.
    """
    fakes = _load_fakes()
    clock = _load_virtual_time().VirtualTime()
    port = fakes.RecordingProbePort(symbol=config.symbol)

    async def sleep(seconds: int) -> None:
        clock.sleeps.append(seconds)
        await clock.advance(seconds)

    return ProbeRig(
        port=port,
        clock=clock.now,
        sleep=sleep,
        real=False,
        stream=None,
        planned=lambda: port.planned_requests,
    )


# --------------------------------------------------------------------------- #
# The evidence checker.
# --------------------------------------------------------------------------- #

REQUIRED_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "schema",
    "mode",
    "proof_class",
    "label",
    "environment",
    "symbol",
    "started_utc",
    "finished_utc",
    "account_before",
    "account_after",
    "cases",
    "cleanup",
    "d055",
    "outcome",
)
_ANSWER_KEYS: tuple[str, ...] = ("http_class", "code", "category", "message")


def _aware_utc(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None or moment.utcoffset() != UTC.utcoffset(None):
        return None
    return moment


def _observation_problems(case_id: str, observations: object) -> list[str]:
    if not isinstance(observations, list):
        return [f"case {case_id}: observations is not a list"]
    problems: list[str] = []
    for index, item in enumerate(observations):
        if not isinstance(item, Mapping) or not isinstance(item.get("ok"), bool):
            problems.append(f"case {case_id}: observation {index} has no ok flag")
            continue
        if item["ok"]:
            continue
        error = item.get("error")
        if not isinstance(error, Mapping):
            problems.append(f"case {case_id}: observation {index} has no error facts")
            continue
        for key in _ANSWER_KEYS:
            if key not in error:
                problems.append(f"case {case_id}: observation {index} lacks error {key}")
    return problems


def _case_problems(cases: object) -> list[str]:
    if not isinstance(cases, list):
        return ["cases is not a list"]
    problems: list[str] = []
    seen: list[str] = []
    for item in cases:
        if not isinstance(item, Mapping):
            problems.append("a case is not an object")
            continue
        case_id = item.get("case_id")
        if case_id not in CASE_ORDER:
            problems.append(f"unknown case id: {case_id!r}")
            continue
        if case_id in seen:
            problems.append(f"case {case_id} appears more than once")
            continue
        seen.append(str(case_id))
        status = item.get("status")
        if status not in CASE_STATUSES:
            problems.append(f"case {case_id}: status must be one of {sorted(CASE_STATUSES)}")
            continue
        observations = item.get("observations")
        if status == OBSERVED and not observations:
            problems.append(f"case {case_id}: OBSERVED without observations")
        problems.extend(_observation_problems(str(case_id), observations or []))
        reason = item.get("reason")
        if status == NOT_OBSERVED and not (isinstance(reason, str) and reason.strip()):
            problems.append(f"case {case_id}: NOT_OBSERVED without a reason")
    if seen != [case_id for case_id in CASE_ORDER if case_id in seen]:
        problems.append("cases are not in CASE_ORDER order")
    return problems


def check_probe_evidence(document: object) -> list[str]:
    """Problems that make a probe evidence document invalid; an empty list means valid."""
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
    if (mode, proof) in {(MODE_DRY_RUN, PROOF_REAL_DEMO), (MODE_EXECUTE, PROOF_FAKE)}:
        problems.append("proof_class does not match the mode (a dry run is FAKE)")
    label = document.get("label")
    if not isinstance(label, str) or LABEL not in label:
        problems.append(f"label must contain '{LABEL}'")
    d055 = document.get("d055")
    status = d055.get("status") if isinstance(d055, Mapping) else None
    if not isinstance(status, str) or not status.startswith("OPEN"):
        problems.append("d055.status must start with OPEN (the probe never closes D055)")
    if "outcome" in document and document.get("outcome") not in OUTCOMES:
        problems.append(f"outcome must be one of {sorted(OUTCOMES)}")
    started = _aware_utc(document.get("started_utc"))
    finished = _aware_utc(document.get("finished_utc"))
    if started is None:
        problems.append("started_utc must be aware UTC ISO text")
    if finished is None:
        problems.append("finished_utc must be aware UTC ISO text")
    if started is not None and finished is not None and finished < started:
        problems.append("finished_utc is before started_utc")
    if "cases" in document:
        problems.extend(_case_problems(document.get("cases")))
    return problems


def _verdict(result: str, reason: str, proof_class: object) -> dict[str, Any]:
    return {"result": result, "reason": reason, "proof_class": proof_class}


def _expected_cases(document: Mapping[str, Any]) -> tuple[str, ...]:
    """Every required case plus each optional case the document's settings enable."""
    settings = document.get("settings")
    optional = settings.get("optional_cases") if isinstance(settings, Mapping) else None
    enabled = {
        case_id
        for key, case_id in OPTIONAL_CASES.items()
        if isinstance(optional, Mapping) and optional.get(key) is True
    }
    return tuple(
        case_id for case_id in CASE_ORDER if case_id in REQUIRED_CASES or case_id in enabled
    )


def _case_verdict(item: object) -> tuple[str, str]:
    if not isinstance(item, Mapping):
        return VERDICT_FAIL, "the case was not run"
    status = item.get("status")
    if status == OBSERVED:
        observations = item.get("observations")
        if not isinstance(observations, list) or not observations:
            return VERDICT_FAIL, "OBSERVED without observations"
        for index, answer in enumerate(observations):
            if not isinstance(answer, Mapping) or not isinstance(answer.get("ok"), bool):
                return VERDICT_FAIL, f"answer {index} has no ok flag"
            if answer["ok"]:
                continue
            error = answer.get("error")
            missing = [
                key for key in _ANSWER_KEYS if not isinstance(error, Mapping) or key not in error
            ]
            if missing:
                return VERDICT_FAIL, f"answer {index} lacks {missing}"
        return VERDICT_PASS, f"OBSERVED: {len(observations)} exchange answer(s) recorded"
    if status == NOT_OBSERVED:
        reason = item.get("reason")
        if isinstance(reason, str) and reason.strip():
            return VERDICT_PASS, f"NOT_OBSERVED: {reason}"
        return VERDICT_FAIL, "NOT_OBSERVED without a reason"
    if status == NOT_REHEARSED:
        return VERDICT_FAIL, "NOT_REHEARSED (dry run: nothing was sent)"
    return VERDICT_FAIL, f"status {status}: {item.get('reason')}"


def _cleanup_verdict(document: Mapping[str, Any]) -> tuple[str, str]:
    cleanup = document.get("cleanup")
    final = cleanup.get("final") if isinstance(cleanup, Mapping) else None
    if not isinstance(final, Mapping):
        return VERDICT_FAIL, "no final cleanup record"
    remaining = final.get("remaining")
    if final.get("status") != CLEANUP_FLAT or not isinstance(remaining, Mapping):
        return VERDICT_FAIL, f"final cleanup status {final.get('status')}"
    if (
        remaining.get("open_orders") != 0
        or remaining.get("open_algo_orders") != 0
        or remaining.get("positions") != []
    ):
        return VERDICT_FAIL, "the final state is not zero orders, zero algo orders and flat"
    return VERDICT_PASS, "zero open orders, zero open algo orders, flat position"


def probe_acceptance_verdict(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """PASS or FAIL with a reason per case (research C4) and per rule, plus `overall`.

    A case passes when it is OBSERVED with (class, code, category, message) for each error
    answer, or NOT_OBSERVED with a reason. The rules: the final cleanup shows zero open orders,
    zero open algo orders and a flat position; the account state before and after is present;
    the label and the D055-OPEN statement are present; the evidence passes
    `check_probe_evidence`; the proof class is REAL_DEMO (FAKE evidence never passes).
    `overall` is PASS only when every entry passes. Every entry carries the proof class.
    """
    proof = document.get("proof_class")
    by_id = {
        item.get("case_id"): item
        for item in document.get("cases") or []
        if isinstance(item, Mapping)
    }
    out: dict[str, dict[str, Any]] = {}
    for case_id in _expected_cases(document):
        result, reason = _case_verdict(by_id.get(case_id))
        out[case_id] = _verdict(result, reason, proof)
    result, reason = _cleanup_verdict(document)
    out["cleanup"] = _verdict(result, reason, proof)
    accounts = [document.get(key) for key in ("account_before", "account_after")]
    read = all(
        isinstance(state, Mapping) and state.get("status") == ACCOUNT_READ for state in accounts
    )
    out["account_state"] = _verdict(
        VERDICT_PASS if read else VERDICT_FAIL,
        "account state recorded before and after" if read else "account state missing",
        proof,
    )
    label = document.get("label")
    d055 = document.get("d055")
    status = d055.get("status") if isinstance(d055, Mapping) else None
    marked = (
        isinstance(label, str)
        and LABEL in label
        and isinstance(status, str)
        and status.startswith("OPEN")
    )
    out["label_and_d055"] = _verdict(
        VERDICT_PASS if marked else VERDICT_FAIL,
        "labelled demo-observed, not mainnet; D055 stays OPEN"
        if marked
        else "the label or the D055-OPEN statement is missing",
        proof,
    )
    problems = check_probe_evidence(document)
    out["evidence"] = _verdict(
        VERDICT_FAIL if problems else VERDICT_PASS,
        "; ".join(problems[:3]) if problems else "the evidence passes check_probe_evidence",
        proof,
    )
    out["proof_class"] = _verdict(
        VERDICT_PASS if proof == PROOF_REAL_DEMO else VERDICT_FAIL,
        "executed on Demo" if proof == PROOF_REAL_DEMO else "FAKE evidence never passes",
        proof,
    )
    failing = sorted(key for key, entry in out.items() if entry["result"] != VERDICT_PASS)
    out["overall"] = _verdict(
        VERDICT_FAIL if failing else VERDICT_PASS,
        f"failing: {failing}" if failing else "every case and every rule passes",
        proof,
    )
    return out


# --------------------------------------------------------------------------- #
# Command line.
# --------------------------------------------------------------------------- #


def evidence_stem(config: ProbeConfig, document: Mapping[str, Any]) -> str:
    """``demo-probe-DRYRUN-<stamp>`` or ``demo-probe-EVIDENCE-<stamp>`` (the rig clock start)."""
    kind = "DRYRUN" if config.mode == MODE_DRY_RUN else "EVIDENCE"
    started = _aware_utc(document.get("started_utc"))
    if started is None:
        raise ValueError("the evidence has no aware UTC start time")
    return f"demo-probe-{kind}-{_utc_stamp(started)}"


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    is_tty: Callable[[], bool] | None = None,
    read_confirmation: Callable[[str], str] | None = None,
    rig_factory: Callable[[ProbeConfig], ProbeRig] | None = None,
    sdk_client_factory: Callable[..., Any] | None = None,
    configure_output: Callable[[Mapping[str, str]], object] | None = None,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> int:
    """Single entry point. Every seam defaults to the real implementation.

    The limits files, the environment row and the `--execute` gate are checked before any
    network call. An executed run configures the redacting logging (`configure_logging`)
    before any credential is loaded (`configure_output` replaces it in tests) and builds the
    live rig with `clock` and `sleep` (default `live_clock` and `asyncio.sleep`); a dry run
    always runs on virtual time.
    """
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

    if config.mode == MODE_EXECUTE:
        (configure_output if configure_output is not None else configure_logging)(env)

    factory: Callable[[ProbeConfig], ProbeRig]
    if rig_factory is not None:
        factory = rig_factory
    elif config.mode == MODE_EXECUTE:

        def factory(cfg: ProbeConfig) -> ProbeRig:
            return build_live_rig(
                cfg, environ=env, client_factory=sdk_client_factory, clock=clock, sleep=sleep
            )

    else:
        factory = build_dry_run_rig

    try:
        rig = factory(config)
    except (CredentialError, CredentialNamesNotRatified, EnvironmentNotConfigured) as exc:
        print(f"refused ({type(exc).__name__}): {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except (EndpointViolation, LiveNotEnabled) as exc:
        print(f"ABORTED before any order ({type(exc).__name__}): {exc}", file=sys.stderr)
        return EXIT_ABORTED

    print(BANNER)
    redactor = Redactor.from_environ(env)
    recorder = ProbeRecorder()
    code = asyncio.run(run_probe(config, rig, recorder, redactor=redactor))
    document = recorder.document(config)
    document["acceptance"] = probe_acceptance_verdict(document)
    try:
        path = write_evidence_atomic(
            config.evidence_dir, evidence_stem(config, document), document, redactor
        )
    except RuntimeError as exc:
        print(f"evidence not written ({type(exc).__name__}): {exc}", file=sys.stderr)
        return EXIT_FAILED
    print(f"evidence: {path}")
    print(f"outcome: {document['outcome']}")
    print(f"acceptance: {document['acceptance']['overall']['result']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
