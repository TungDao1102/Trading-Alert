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
import importlib.metadata
import os
import re
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn, Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.adapters import binance_client  # noqa: E402
from src.adapters.binance_client import (  # noqa: E402
    Environment,
    EnvironmentNotConfigured,
    Surface,
    parse_environment,
)
from src.adapters.binance_limits import (  # noqa: E402
    BinanceLimits,
    LimitsNotRatified,
    load_binance_limits,
)
from src.adapters.binance_probe import ProbeBanned, ProbeObservation  # noqa: E402
from src.adapters.binance_ratelimit_gate import IP_BAN_418, RATE_LIMIT_PAUSE_429  # noqa: E402
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
from src.ops.redaction import Redactor  # noqa: E402

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
        "status": "READ",
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


# The registry the runner walks in CASE_ORDER. A handler never raises for an exchange answer
# (answers are data); `ProbeBanned` propagates on purpose (the run stops) and any other
# exception is a bug the runner records as ERROR.
CASE_HANDLERS: dict[str, CaseHandler] = {
    "get_order_not_found": case_get_order_not_found,
    "get_algo_order_not_found": case_get_algo_order_not_found,
    "cancel_order_not_found": case_cancel_order_not_found,
    "cancel_algo_order_not_found": case_cancel_algo_order_not_found,
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
        self.recorder.market = {"status": "READ", "mark_price": mark, "symbol_filters": filters}

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
            reason = _rate_limit_reason(observation)
            if reason is not None and not self.banned:
                error = observation.error
                self._note_ban(reason, error.retry_after_seconds if error else None, case_id)
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
            if rig_factory is None:
                raise UsageError("the live rig is not available in this build")
    except (
        UsageError,
        LimitsFileRefused,
        EnvironmentNotConfigured,
        ConfirmationRefused,
    ) as exc:
        print(f"refused ({type(exc).__name__}): {exc}", file=sys.stderr)
        return EXIT_REFUSED

    factory: Callable[[ProbeConfig], ProbeRig] = (
        rig_factory if rig_factory is not None else build_dry_run_rig
    )
    rig = factory(config)
    redactor = Redactor.from_environ(env)
    recorder = ProbeRecorder()
    code = asyncio.run(run_probe(config, rig, recorder, redactor=redactor))
    document = recorder.document(config)
    try:
        path = write_evidence_atomic(
            config.evidence_dir, evidence_stem(config, document), document, redactor
        )
    except RuntimeError as exc:
        print(f"evidence not written ({type(exc).__name__}): {exc}", file=sys.stderr)
        return EXIT_FAILED
    print(f"evidence: {path}")
    print(f"outcome: {document['outcome']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
