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
orders on this envelope (every id of ``CASE_ORDER`` has a handler). Each order a case sends
passes one shared bound first (``order_bound_refusal``: never above the owner's approved
quantity or notional cap; the owner-approved ``market_lot_probe_quantity`` of the optional
MARKET_LOT_SIZE case is the single exception). The live run is plan 18-20 (blocking-human).

Quick task 261021-sj0 adds ten owner opt-in evidence cases (``CAPTURE_CASES``), each enabled by
its own key in the owner's probe limits file (the Phase 18 file enables none, so its run is
unchanged). They record raw, scrubbed Binance Demo answers and user-data frames as evidence and
fixtures for Phases 19 to 25. In an executed run with ``--fixtures-dir`` the REST answers of
these cases are written as ``<case_id>-rest-<NNN>-<operation>.json`` beside the raw frames and
listed in ``provenance.md``; a dry run writes none. An ``--only`` run of a few cases leaves
``acceptance.overall`` at FAIL because the required set did not run: by design, read the
per-case verdicts. The owner runbook is ``.planning/DEMO-EVIDENCE-PLAN.md``.

Quick task 261022-sj1 adds five more owner opt-in cases on the same framework (``SJ1_CASES``):
``exchange_info_read_for_close`` (A10), ``gtd_min_lifetime_boundary`` (A1: goodTillDate at the
public server time plus 599 s and plus 601 s), ``partial_fill_attempt`` (P3, best effort),
``entry_cancel_fill_race`` (P7, best effort, ``race_repeats`` place-and-cancel pairs) and
``stream_loss_during_case`` (P5, the ``stream_gap_during_case`` drop around an entry and stop
cycle). Three of them can stay NOT_OBSERVED on Demo for ever (the partial fill, the race, and
the stream comparison when the stream does not return). The runbook section "One session: all
cases" lists every case id in run order.

Quick task 261023-sj2 adds eight more owner opt-in cases (``SJ2_CASES``):
``reduce_only_market_on_flat``
(A4), ``reduce_only_market_larger_than_position`` (A8), ``non_reduce_only_below_min_notional``
(-4164), ``insufficient_margin_order`` (-2019), ``stop_rejected_after_acceptance`` (P5, best
effort), ``trigger_cancel_race`` (P7 trigger part, best effort), ``timestamp_outside_recv_window``
(-1021, one read-only signed GET with a stale timestamp) and ``income_history_read``. Seven obey
the approved quantity and ``max_notional_quote``; ``insufficient_margin_order`` alone sends the
owner's own ``insufficient_margin_quantity`` (a far LIMIT BUY that can only rest) and is bound by
``margin_order_refusal`` instead: no other case may exceed a cap.

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
from datetime import UTC, datetime, timedelta
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
    ORDER_BOOK_LIMIT,
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
from src.backtest.semantics import TP1_QUANTITY_FRACTION  # noqa: E402
from src.domain.exchange_errors import CallKind, classify  # noqa: E402
from src.domain.lot_filters import LotFilters  # noqa: E402
from src.execution.lot_split import quantize_to_lot  # noqa: E402
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
        # Quick task 261021-sj0: the ten owner opt-in evidence-capture cases (CAPTURE_CASES).
        "account_capture": "account_read_only_capture",
        "algo_query_timing": "algo_query_timing_after_new",
        "close_position_with_position": "close_position_stop_with_position",
        "stop_trigger_after_fill": "stop_would_trigger_after_fill",
        "stop_absent_same_id": "stop_query_absent_then_same_id",
        "manual_close_open_legs": "manual_close_with_open_legs",
        "commission_realized_pnl": "commission_vs_realized_pnl",
        "triggered_bracket": "triggered_close_position_bracket",
        "tp1_from_fill": "tp1_quantity_from_fill",
        # Quick task 261022-sj1: five more (SJ1_CASES); gtd_expiry, the only case that waits
        # more than ten minutes, stays last.
        "exchange_info_read": "exchange_info_read_for_close",
        "gtd_min_lifetime": "gtd_min_lifetime_boundary",
        "partial_fill_attempt": "partial_fill_attempt",
        "cancel_fill_race": "entry_cancel_fill_race",
        "stream_loss": "stream_loss_during_case",
        # Quick task 261023-sj2: eight more (SJ2_CASES), still before gtd_expiry.
        "reduce_only_flat": "reduce_only_market_on_flat",
        "reduce_only_oversize": "reduce_only_market_larger_than_position",
        "min_notional_entry": "non_reduce_only_below_min_notional",
        "insufficient_margin": "insufficient_margin_order",
        "stop_reject_after_accept": "stop_rejected_after_acceptance",
        "trigger_cancel_race": "trigger_cancel_race",
        "recv_window_error": "timestamp_outside_recv_window",
        "income_history": "income_history_read",
        "gtd_expiry": "gtd_entry_expiry_status",
    }
)
CASE_ORDER: tuple[str, ...] = (*REQUIRED_CASES, *OPTIONAL_CASES.values())
# The ten cases of quick task 261021-sj0, in CASE_ORDER order. In an executed run with
# `--fixtures-dir` each REST answer of these cases is also written as a scrubbed fixture file.
CAPTURE_CASES: tuple[str, ...] = (
    "account_read_only_capture",
    "algo_query_timing_after_new",
    "close_position_stop_with_position",
    "stop_would_trigger_after_fill",
    "stop_query_absent_then_same_id",
    "manual_close_with_open_legs",
    "commission_vs_realized_pnl",
    "triggered_close_position_bracket",
    "tp1_quantity_from_fill",
    "gtd_entry_expiry_status",
)
# The five cases of quick task 261022-sj1, in CASE_ORDER order (before gtd_entry_expiry_status).
SJ1_CASES: tuple[str, ...] = (
    "exchange_info_read_for_close",
    "gtd_min_lifetime_boundary",
    "partial_fill_attempt",
    "entry_cancel_fill_race",
    "stream_loss_during_case",
)
# The eight cases of quick task 261023-sj2, in CASE_ORDER order (before gtd_entry_expiry_status).
SJ2_CASES: tuple[str, ...] = (
    "reduce_only_market_on_flat",
    "reduce_only_market_larger_than_position",
    "non_reduce_only_below_min_notional",
    "insufficient_margin_order",
    "stop_rejected_after_acceptance",
    "trigger_cancel_race",
    "timestamp_outside_recv_window",
    "income_history_read",
)
# The cases whose REST answers are also written as fixture files in an executed run.
FIXTURE_CASES: tuple[str, ...] = (*CAPTURE_CASES, *SJ1_CASES, *SJ2_CASES)

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
        "new_gtd_limit_order",
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

    # Quick task 261021-sj0: the evidence-capture operations of the owner opt-in cases.

    async def account_information(self) -> ProbeObservation: ...

    async def account_balance_all(self) -> ProbeObservation: ...

    async def account_config(self) -> ProbeObservation: ...

    async def symbol_config(self, *, symbol: str) -> ProbeObservation: ...

    async def leverage_brackets(self, *, symbol: str) -> ProbeObservation: ...

    async def income_history(self, *, symbol: str, start_time_ms: int) -> ProbeObservation: ...

    async def query_algo_order_by_algo_id(self, *, algo_id: int) -> ProbeObservation: ...

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
    ) -> ProbeObservation: ...

    async def live_mark_price(self, *, symbol: str) -> ProbeObservation: ...

    # Quick task 261022-sj1: the exchange clock and the depth of the book (unsigned reads).

    async def server_time(self) -> ProbeObservation: ...

    async def order_book(self, *, symbol: str) -> ProbeObservation: ...

    # Quick task 261023-sj2: one read-only signed GET with a deliberately stale timestamp.

    async def stale_timestamp_read(
        self, *, symbol: str, recv_window_ms: int, timestamp_behind_ms: int
    ) -> ProbeObservation: ...

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
                "near_trigger_fraction": order.near_trigger_fraction,
                "gtd_lifetime_seconds": order.gtd_lifetime_seconds,
                "gtd_expiry_wait_seconds": order.gtd_expiry_wait_seconds,
                "race_repeats": order.race_repeats,
                "insufficient_margin_quantity": order.insufficient_margin_quantity,
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
# Quick task 261021-sj0.
REASON_CLOSE_LEGS_REJECTED = "neither closePosition leg was accepted"
REASON_NO_POSITION_HELD = "no open position to work on: the position read shows none"
REASON_LOT_FILTERS_UNREADABLE = (
    "a LOT_SIZE or MARKET_LOT_SIZE filter value is unreadable: TP1 cannot be sized"
)
REASON_TP1_ZERO = "the TP1 quantity is zero after quantization to the lot grid"
REASON_GTD_NOT_TERMINAL = "not terminal within gtd_expiry_wait_seconds"
REASON_NO_PARTIAL_PRODUCED = "no partial fill produced"
REASON_STREAM_NOT_RECOVERED = (
    "the stream did not return to LIVE within case_timeout_seconds: the later deliveries "
    "cannot be compared with what REST said during the gap"
)
# The two points of `gtd_min_lifetime_boundary`: goodTillDate = public server time + this many
# seconds, one just below and one just above the exchange's documented floor of 600 seconds
# (assumption A1). Tool vocabulary of the probe, not a trading threshold.
GTD_BOUNDARY_MARGINS_SECONDS: tuple[int, int] = (599, 601)
RACE_NOTE = (
    "this case does not reproduce a deterministic race: each repeat places a BUY LIMIT at the "
    "best ask and cancels it as soon as the placement answer arrives; the exchange timing "
    "decides whether the cancel meets a NEW, FILLED or CANCELED order, so the outcomes below are "
    "samples of the exchange answers (for example -2011 or FILLED), not a proof of their order"
)
# Order statuses that end an order (the GTD case waits for one of them).
ORDER_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"}
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

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


def margin_order_refusal(
    limits: DemoOrderLimits,
    *,
    quantity: Decimal | None,
    price: Decimal,
    ceiling_price: Decimal,
    step: Decimal | None,
) -> str | None:
    """Why the `insufficient_margin_order` order may not be sent, or None (quick task sj2).

    This is NOT `order_bound_refusal`: the owner's `max_notional_quote` and approved `quantity`
    are deliberately not applied to this one order, which has to be larger than the available
    margin. What stays: the case is enabled, the quantity is exactly the owner's own
    `insufficient_margin_quantity` (never another number), it is positive and on the step grid,
    and the price is positive and not above `ceiling_price` (the far price inside the owner
    `far_price_fraction` band), so the order can only rest.
    """
    approved = limits.insufficient_margin_quantity
    if limits.optional_cases.get("insufficient_margin") is not True or approved is None:
        return "insufficient_margin is not enabled with an owner insufficient_margin_quantity"
    if quantity != approved:
        return "the quantity is not the owner's insufficient_margin_quantity"
    if not approved.is_finite() or approved <= 0:
        return f"quantity {approved} is not positive"
    if step is not None and approved % step != 0:
        return f"quantity {approved} is not on the step grid {step}"
    if not price.is_finite() or price <= 0:
        return f"the price {price} is not positive"
    if price > ceiling_price:
        return f"the price {price} is above the far price {ceiling_price} of the owner band"
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
        """A BUY limit that crosses the book: halfway between the mark and the PERCENT_PRICE edge.

        The port reads no order book, so the best ask is unknown; a BUY limit above the mark
        fills at the book's best ask. The mark comes from the last one-minute close and can sit
        above the exchange's own mark, so the price is not put at the band edge: the first live
        probe (2026-10-16) had its entry refused with -4016 at the edge. Halfway leaves half of
        the band as room and still bounds the notional check from above.
        """
        if self.multiplier_up is None:
            raise _StopCase("the PERCENT_PRICE filter is unreadable: no marketable price")
        halfway = (Decimal(1) + self.multiplier_up) / 2
        return self.floor(self.mark * halfway)

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
    def near_trigger_fraction(self) -> Decimal:
        """The owner's `near_trigger_fraction` (quick task 261021-sj0): trigger closeness."""
        value = self.limits.near_trigger_fraction
        if value is None:
            raise ValueError("near_trigger_fraction is not set in the probe limits file")
        return value

    @property
    def gtd_lifetime_seconds(self) -> int:
        """The owner's GTD lifetime (quick task 261021-sj0)."""
        value = self.limits.gtd_lifetime_seconds
        if value is None:
            raise ValueError("gtd_lifetime_seconds is not set in the probe limits file")
        return value

    @property
    def gtd_expiry_wait_seconds(self) -> int:
        """The owner's wait for the GTD order to end (longer than its lifetime)."""
        value = self.limits.gtd_expiry_wait_seconds
        if value is None:
            raise ValueError("gtd_expiry_wait_seconds is not set in the probe limits file")
        return value

    @property
    def race_repeats(self) -> int:
        """The owner's `race_repeats` (quick task 261022-sj1): place-and-cancel pairs."""
        value = self.limits.race_repeats
        if value is None:
            raise ValueError("race_repeats is not set in the probe limits file")
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
        quantity: Decimal | None = None,
    ) -> ProbeObservation:
        """A GTC LIMIT, by default of the approved quantity; `quantity` may only be a smaller one.

        Bound-checked again just before sending (`order_bound_refusal`: never above the approved
        quantity and never above `max_notional_quote`).
        """
        amount = self.quantity if quantity is None else quantity
        self.check_bounds([(amount, price)])
        answer = await self.ask(
            label,
            self.port.new_limit_order(
                symbol=self.symbol,
                side=side,
                quantity=amount,
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

    async def gtd_limit(
        self, label: str, *, client_id: str, price: Decimal, good_till_date_ms: int
    ) -> ProbeObservation:
        """A GTD LIMIT BUY of the approved quantity (bound-checked again just before sending)."""
        self.check_bounds([(self.quantity, price)])
        answer = await self.ask(
            label,
            self.port.new_gtd_limit_order(
                symbol=self.symbol,
                side=SIDE_BUY,
                quantity=self.quantity,
                price=price,
                client_order_id=client_id,
                position_side=self.position_side(long=True),
                good_till_date_ms=good_till_date_ms,
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

    async def algo_status_by_id(self, label: str, algo_id: int) -> str:
        """Like `algo_status`, but by the exchange's algo id (quick task 261021-sj0)."""
        answer = await self.ask(label, self.port.query_algo_order_by_algo_id(algo_id=algo_id))
        if answer.ok:
            return answer.summary.get("algo_status", "")
        error = answer.error
        return ALGO_ABSENT if error is not None and error.category == CATEGORY_ORDER_ABSENT else ""

    def elapsed_ms(self, since: datetime) -> int:
        """Whole milliseconds on the rig clock since `since` (integer arithmetic only)."""
        return (_checked_now(self.rig) - since) // timedelta(milliseconds=1)

    async def live_mark(self) -> Decimal:
        """The live premiumIndex mark (recorded); `_StopCase` when it cannot be read."""
        answer = await self.ask(
            "live_mark_price_read", self.port.live_mark_price(symbol=self.symbol)
        )
        value = _positive_decimal(answer.summary, "mark_price") if answer.ok else None
        if value is None:
            raise _StopCase(f"the live mark price is unreadable: {_class_code(answer)}")
        self.detail("live_mark_price", format(value, "f"))
        return value

    async def held_quantity(self, label: str) -> Decimal:
        """The summed signed position amount of the symbol (one read); `_StopCase` if unreadable."""
        answer = await self.ask(label, self.port.positions(symbol=self.symbol))
        rows = _position_rows(answer)
        if rows is None:
            raise _StopCase("the position is unreadable")
        return sum((Decimal(row["position_amt"]) for row in rows), Decimal(0))

    async def observe_state(self, prefix: str) -> dict[str, ProbeObservation]:
        """Record open orders, open algo orders, the position and the algo ids as observed facts.

        Nothing is compared with an expectation (unlike `reconcile`): these are plain facts.
        """
        summary, answers = await _read_state(self.port, self.symbol)
        self.observations.extend(answers.values())
        readable = summary["readable"] is True
        held = sum((Decimal(row["position_amt"]) for row in summary["positions"]), Decimal(0))
        self.detail(f"{prefix}_open_orders", _count_text(summary["open_orders"]))
        self.detail(f"{prefix}_open_algo_orders", _count_text(summary["open_algo_orders"]))
        self.detail(f"{prefix}_position", format(held, "f") if readable else "unreadable")
        algo = answers["open_algo_orders"]
        ids = [algo.summary.get(f"row_{i}_client_algo_id", "") for i in range(_count(algo) or 0)]
        self.detail(f"{prefix}_open_algo_ids", ",".join(ids) or "none")
        return answers

    async def market_close(
        self, label: str, quantity: Decimal, bound_price: Decimal, tag: str
    ) -> tuple[ProbeObservation, str]:
        """One reduce-only MARKET SELL (position side BOTH) of `quantity`, bound-checked first.

        `bound_price` is an upper bound of the fill price (the notional check). Returns the
        answer and the client id sent.
        """
        self.check_bounds([(quantity, bound_price)])
        client_id = self.client_id(tag)
        answer = await self.ask(
            label,
            self.port.new_market_order(
                symbol=self.symbol,
                side=SIDE_SELL,
                quantity=quantity,
                client_order_id=client_id,
                position_side=POSITION_SIDE_ONE_WAY,
                reduce_only=True,
            ),
        )
        return answer, client_id

    async def flatten(
        self, label: str, held: Decimal, bound_price: Decimal, tag: str
    ) -> tuple[ProbeObservation, str]:
        """One reduce-only MARKET order that closes the signed position `held` (quick task sj2).

        SELL for a long, BUY for a short; position side BOTH. Bound-checked first like every
        capped order: the absolute amount is never above the approved quantity.
        """
        quantity = abs(held)
        self.check_bounds([(quantity, bound_price)])
        client_id = self.client_id(tag)
        answer = await self.ask(
            label,
            self.port.new_market_order(
                symbol=self.symbol,
                side=SIDE_SELL if held > 0 else SIDE_BUY,
                quantity=quantity,
                client_order_id=client_id,
                position_side=POSITION_SIDE_ONE_WAY,
                reduce_only=True,
            ),
        )
        return answer, client_id

    async def margin_limit(
        self, label: str, *, client_id: str, price: Decimal, ceiling_price: Decimal
    ) -> ProbeObservation:
        """The ONE order that is not held to the approved quantity and `max_notional_quote`.

        Only `insufficient_margin_order` calls this (a test pins it). It sends exactly the
        owner's own `insufficient_margin_quantity` as a GTC LIMIT BUY that can only rest: the
        owner notional cap is deliberately NOT applied (the order has to be larger than the
        margin allows to provoke -2019), so this method does the checks that remain: the key is
        enabled, the quantity is the owner's one and is on the step grid, the price is positive
        and not above `ceiling_price` (the far price inside the owner far_price_fraction band,
        always below the mark).
        """
        quantity = self.limits.insufficient_margin_quantity
        refusal = margin_order_refusal(
            self.limits, quantity=quantity, price=price, ceiling_price=ceiling_price, step=self.step
        )
        if refusal is not None or quantity is None:
            raise OrderBoundRefused(refusal or "insufficient_margin_quantity is not set")
        answer = await self.ask(
            label,
            self.port.new_limit_order(
                symbol=self.symbol,
                side=SIDE_BUY,
                quantity=quantity,
                price=price,
                client_order_id=client_id,
                position_side=self.position_side(long=True),
                time_in_force=TIME_IN_FORCE_GTC,
                reduce_only=None,
            ),
        )
        if answer.ok and answer.summary.get("status") != ORDER_STATUS_FILLED:
            self.open_orders.append(client_id)
        return answer

    async def open_long(
        self, market: _Market, tag: str, quantity: Decimal | None = None
    ) -> tuple[ProbeObservation, str]:
        """A marketable BUY LIMIT (default: the approved quantity; else a smaller one); one wait.

        Returns the placement answer and the last status seen ('' when rejected or
        unreadable). Every status seen is in `details["entry_statuses"]`, so a dependent case
        can tell a partial fill from the run record.
        """
        client_id = self.client_id(tag)
        self.detail("entry_client_id", client_id)
        self.entry_sent = True
        placed = await self.limit(
            "entry",
            client_id=client_id,
            side=SIDE_BUY,
            price=market.marketable_buy(),
            quantity=quantity,
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


# ----- Task 2: the D055 cases ------------------------------------------------------ #


async def _place_flat_leg(
    case: _WriteCase, label: str, client_id: str, trigger: Decimal, *, time_in_force: str | None
) -> ProbeObservation:
    """The pre-placed protective leg of a long: STOP_MARKET SELL, explicit quantity, reduceOnly."""
    return await case.conditional(
        label,
        client_id=client_id,
        side=SIDE_SELL,
        order_type=ORDER_TYPE_STOP_MARKET,
        trigger=trigger,
        quantity=case.quantity,
        reduce_only=True,
        time_in_force=time_in_force,
    )


def _row_values(answer: ProbeObservation, match_key: str, match: str) -> dict[str, str] | None:
    """The summary fields of the snapshot row whose `match_key` equals `match`, or None."""
    count = _count(answer)
    for index in range(count or 0):
        prefix = f"row_{index}_"
        if answer.summary.get(f"{prefix}{match_key}") == match:
            return {
                key[len(prefix) :]: value
                for key, value in answer.summary.items()
                if key.startswith(prefix)
            }
    return None


async def _preplaced_stop_reduce_only_flat(case: _WriteCase) -> CaseResult:
    market = await case.market()
    trigger = market.far_below(case.fraction)
    case.check_bounds([(case.quantity, trigger)])
    leg_id = case.client_id("pre")
    case.detail("client_algo_id", leg_id)
    leg = await _place_flat_leg(case, "leg", leg_id, trigger, time_in_force=None)
    case.detail("leg_accepted", _flag_text(leg.ok))
    if leg.ok:
        await case.algo_status("leg_status", leg_id)
        await case.await_frames(lambda frame: frame.get("client_algo_id") == leg_id)
    await case.reconcile(open_orders=0, open_algo_orders=1 if leg.ok else 0, position=Decimal(0))
    return case.observed()


async def _closeposition_stop_flat(case: _WriteCase) -> CaseResult:
    market = await case.market()
    trigger = market.far_below(case.fraction)
    case.check_bounds([(None, trigger)])
    leg_id = case.client_id("cpf")
    case.detail("client_algo_id", leg_id)
    leg = await case.conditional(
        "close_position_leg",
        client_id=leg_id,
        side=SIDE_SELL,
        order_type=ORDER_TYPE_STOP_MARKET,
        trigger=trigger,
        quantity=None,
        close_position=True,
    )
    case.detail("close_position_accepted", _flag_text(leg.ok))
    if leg.ok:
        await case.algo_status("close_position_status", leg_id)
    return case.observed()


async def _entry_never_fills_protective_orphan(case: _WriteCase) -> CaseResult:
    premise = _premise_leg(case.context)
    if premise is not None:
        return case.not_observed(premise)
    market = await case.market()
    price = market.far_below(case.fraction)
    trigger = market.far_below(case.fraction)
    case.check_bounds([(case.quantity, price), (case.quantity, trigger)])
    entry_id = case.client_id("ore")
    leg_id = case.client_id("orl")
    case.detail("entry_client_id", entry_id)
    case.detail("client_algo_id", leg_id)
    entry = await case.limit("entry", client_id=entry_id, side=SIDE_BUY, price=price)
    if not entry.ok:
        return case.not_observed(f"entry rejected: {_class_code(entry)}")
    leg = await _place_flat_leg(case, "leg", leg_id, trigger, time_in_force=None)
    if not leg.ok:
        return case.not_observed(f"{REASON_LEG_NOT_ACCEPTED} in this case: {_class_code(leg)}")
    await case.cancel("entry_cancel", entry_id)
    statuses: list[str] = []

    async def leg_ended() -> bool:
        statuses.append(await case.algo_status("leg_query", leg_id))
        return statuses[-1] in ALGO_ENDED_STATUSES or statuses[-1] == ALGO_ABSENT

    await wait_up_to(case.rig, leg_ended, case.case_timeout_seconds)
    final = statuses[-1]
    case.detail("leg_status_after_entry_cancel", final or "unreadable")
    if final == ALGO_STATUS_NEW:
        orphaned = _TRUE
    elif final in ALGO_ENDED_STATUSES or final == ALGO_ABSENT:
        orphaned = _FALSE
    else:
        orphaned = "unknown"
    case.detail("orphaned", orphaned)
    if orphaned != _FALSE:
        canceled = await case.cancel_algo("leg_cancel", leg_id)
        case.detail("leg_cancel_clean", _flag_text(canceled.ok))
        after = await case.algo_status("leg_query_after_cancel", leg_id)
        case.detail("leg_status_after_cancel", after or "unreadable")
    await case.reconcile(open_orders=0, open_algo_orders=0, position=Decimal(0))
    return case.observed()


async def _full_fill_protective_quantity(case: _WriteCase) -> CaseResult:
    premise = _premise_leg(case.context)
    if premise is not None:
        return case.not_observed(premise)
    market = await case.market()
    trigger = market.far_below(case.fraction)
    case.check_bounds([(case.quantity, trigger), (case.quantity, market.marketable_buy())])
    leg_id = case.client_id("ffl")
    case.detail("client_algo_id", leg_id)
    leg = await _place_flat_leg(case, "leg", leg_id, trigger, time_in_force=None)
    if not leg.ok:
        return case.not_observed(f"{REASON_LEG_NOT_ACCEPTED} in this case: {_class_code(leg)}")
    placed, status = await case.open_long(market, "ffe")
    if not placed.ok:
        return case.not_observed(f"entry rejected: {_class_code(placed)}")
    if status != ORDER_STATUS_FILLED:
        return case.not_observed(f"the entry did not fill: status {status or 'unreadable'}")
    leg_status = await case.algo_status("leg_query", leg_id)
    case.detail("leg_status_after_fill", leg_status or "unreadable")
    summary, answers = await case.reconcile(
        open_orders=0, open_algo_orders=1, position=case.quantity
    )
    held = sum((Decimal(row["position_amt"]) for row in summary["positions"]), Decimal(0))
    case.detail("position_amount", format(held, "f"))
    row = _row_values(answers["open_algo_orders"], "client_algo_id", leg_id)
    leg_quantity = row.get("quantity", "") if row is not None else ""
    case.detail("leg_quantity", leg_quantity or "not listed")
    if row is not None and row.get("algo_status"):
        case.detail("leg_status_listed", row["algo_status"])
    listed = _positive_decimal({"quantity": leg_quantity}, "quantity")
    case.detail(
        "protective_quantity_equals_position",
        "unknown" if listed is None else _flag_text(listed == held),
    )
    return case.observed()


def _partially_filled_answers(result: CaseResult) -> list[ProbeObservation]:
    return [
        answer
        for answer in result.observations
        if answer.ok
        and answer.operation in ("new_limit_order", "query_order")
        and answer.summary.get("status") == ORDER_STATUS_PARTIALLY_FILLED
    ]


def _partial_fill_frames(record: Mapping[str, Any]) -> bool:
    frames = record.get("frames")
    events = frames.get("events") if isinstance(frames, Mapping) else None
    return any(
        isinstance(event, Mapping) and event.get("order_status") == ORDER_STATUS_PARTIALLY_FILLED
        for event in events or []
    )


def _filled_any(result: CaseResult) -> bool:
    return any(
        answer.ok
        and answer.operation in ("new_limit_order", "query_order")
        and answer.summary.get("status") == ORDER_STATUS_FILLED
        for answer in result.observations
    )


async def case_partial_fill(context: CaseContext) -> CaseResult:
    """Derived, not a new order: did any entry of this run show PARTIALLY_FILLED?"""
    try:
        recorder = context.recorder
        ran = [case_id for case_id in ENTRY_CASES if case_id in recorder.results]
        if not ran:
            return CaseResult(status=NOT_OBSERVED, reason=REASON_PREMISE_NOT_RUN)
        details = {"derived_from": ",".join(ran)}
        partial: list[ProbeObservation] = []
        seen_in: list[str] = []
        for case_id in ran:
            partial.extend(_partially_filled_answers(recorder.results[case_id]))
        if partial:
            seen_in.append("rest")
        if any(_partial_fill_frames(recorder.records.get(case_id, {})) for case_id in ran):
            seen_in.append("frames")
        if seen_in:
            evidence = partial or [
                answer for case_id in ran for answer in recorder.results[case_id].observations
            ]
            details["seen_in"] = ",".join(seen_in)
            if evidence:
                return CaseResult(status=OBSERVED, observations=tuple(evidence), details=details)
            return CaseResult(
                status=NOT_OBSERVED,
                reason="a partial fill frame arrived but no exchange answer was recorded",
                details=details,
            )
        if any(_filled_any(recorder.results[case_id]) for case_id in ran):
            return CaseResult(status=NOT_OBSERVED, reason=REASON_NO_PARTIAL, details=details)
        return CaseResult(status=NOT_OBSERVED, reason=REASON_NO_ENTRY_FILLED, details=details)
    except Exception as exc:  # a script error: recorded, the run continues
        return CaseResult(status=ERROR, reason=f"script error: {type(exc).__name__}")


async def _rejected_protective_variants(case: _WriteCase) -> CaseResult:
    market = await case.market()
    below = market.far_below(case.fraction)
    above = market.far_above(case.fraction)
    case.check_bounds([(None, above), (None, below), (case.quantity, above)])
    # (a) close-position with no position (a take-profit close, unlike closeposition_stop_flat)
    await case.conditional(
        "variant_a_close_position_flat",
        client_id=case.client_id("rva"),
        side=SIDE_SELL,
        order_type=ORDER_TYPE_TAKE_PROFIT_MARKET,
        trigger=above,
        quantity=None,
        close_position=True,
    )
    # (b) reduceOnly together with closePosition (documented invalid)
    if case.hedge_mode:
        case.detail(
            "variant_b_reduce_only_with_close_position", f"NOT_OBSERVED: {REASON_HEDGE_MODE}"
        )
    else:
        await case.conditional(
            "variant_b_reduce_only_with_close_position",
            client_id=case.client_id("rvb"),
            side=SIDE_SELL,
            order_type=ORDER_TYPE_STOP_MARKET,
            trigger=below,
            quantity=None,
            reduce_only=True,
            close_position=True,
        )
    # (c) a SELL stop whose trigger is on the wrong side of the mark (would trigger at once)
    await case.conditional(
        "variant_c_wrong_side_trigger",
        client_id=case.client_id("rvc"),
        side=SIDE_SELL,
        order_type=ORDER_TYPE_STOP_MARKET,
        trigger=above,
        quantity=case.quantity,
        long=False,
    )
    return case.observed()


# ----- Task 3: the G2-029 additions and the optional cases ---------------------------- #

# The lot-size and market-lot filters recorded by the triggered-exit cases.
_LOT_FILTERS: tuple[str, ...] = (
    "min_quantity",
    "max_quantity",
    "step_size",
    "market_lot_min_quantity",
    "market_lot_max_quantity",
    "market_lot_step_size",
)
MARKET_LOT_CASE = "market_lot_size_out_of_range"


async def _below_min_notional_reduce_only_leg(case: _WriteCase) -> CaseResult:
    market = await case.market()
    trigger = market.far_below(case.fraction)
    smallest = market.smallest_quantity()
    notional = smallest * trigger
    case.detail("smallest_quantity", format(smallest, "f"))
    case.detail("trigger_price", format(trigger, "f"))
    case.detail("leg_notional", format(notional, "f"))
    minimum = market.min_notional
    if minimum is None:
        return case.not_observed("the minimum notional filter is unreadable")
    case.detail("min_notional", format(minimum, "f"))
    if notional >= minimum:
        return case.not_observed(
            f"the smallest valid quantity {format(smallest, 'f')} at trigger "
            f"{format(trigger, 'f')} has notional {format(notional, 'f')}, not below the "
            f"minimum notional {format(minimum, 'f')}"
        )
    case.check_bounds([(case.quantity, market.marketable_buy()), (smallest, trigger)])
    placed, status = await case.open_long(market, "bme")
    if not placed.ok:
        return case.not_observed(f"entry rejected: {_class_code(placed)}")
    if status != ORDER_STATUS_FILLED:
        return case.not_observed(
            f"no open position: the entry did not fill: status {status or 'unreadable'}"
        )
    leg_id = case.client_id("bml")
    case.detail("client_algo_id", leg_id)
    leg = await case.conditional(
        "below_min_notional_leg",
        client_id=leg_id,
        side=SIDE_SELL,
        order_type=ORDER_TYPE_STOP_MARKET,
        trigger=trigger,
        quantity=smallest,
        reduce_only=True,
    )
    case.detail("leg_accepted", _flag_text(leg.ok))
    if leg.ok:
        await case.algo_status("leg_status", leg_id)
    return case.observed()


def _algo_frames(
    frames: Sequence[Mapping[str, str]], client_algo_id: str
) -> list[Mapping[str, str]]:
    return [
        frame
        for frame in frames
        if frame.get("event_type") == EVENT_ALGO_UPDATE
        and frame.get("client_algo_id") == client_algo_id
    ]


def _first_field(frames: Sequence[Mapping[str, str]], name: str) -> str | None:
    return next((frame[name] for frame in frames if frame.get(name)), None)


def _record_child_identity(case: _WriteCase, leg_id: str) -> None:
    """`ai`, `aq`, `rm` of the leg's ALGO_UPDATE frames and `c`, `i` of the child order."""
    frames = case.frames()
    algo = _algo_frames(frames, leg_id)
    actual = _first_field(algo, "actual_order_id")
    executed = _first_field(algo, "executed_quantity")
    reject = _first_field(algo, "reject_reason")
    case.detail("child_ai", actual or "NOT_OBSERVED: no ALGO_UPDATE frame carried ai")
    case.detail("child_aq", executed or "NOT_OBSERVED: no ALGO_UPDATE frame carried aq")
    if reject:
        case.detail("reject_reason", reject)
    child = next(
        (
            frame
            for frame in frames
            if actual
            and frame.get("event_type") == EVENT_ORDER_UPDATE
            and frame.get("exchange_order_id") == actual
        ),
        None,
    )
    missing = "NOT_OBSERVED: no child ORDER_TRADE_UPDATE frame"
    case.detail("child_c", child.get("client_order_id", missing) if child else missing)
    case.detail("child_i", child.get("exchange_order_id", missing) if child else missing)
    rest = next(
        (
            answer.summary.get("actual_order_id", "")
            for answer in reversed(case.observations)
            if answer.ok and answer.operation == "query_algo_order"
        ),
        "",
    )
    case.detail("rest_actual_order_id", rest or "NOT_OBSERVED: empty or not answered")


async def _triggered_exit(
    case: _WriteCase, *, quantity: Decimal | None, market_lot_probe: bool, tag: str
) -> CaseResult:
    """A position from a marketable entry, then a reduce-only STOP_MARKET meant to trigger.

    The trigger is the highest tick-grid price below a fresh mark. One wait of the case
    timeout for the lifecycle (ended in REST or in the stream frames); the statuses seen, the
    child order identity and the lot-size filters are recorded. For the MARKET_LOT_SIZE case
    (`market_lot_probe`) a rejected placement is the finding itself.
    """
    market = await case.market()
    for name in _LOT_FILTERS:
        case.detail(f"filter_{name}", market.filters.get(name, "not listed"))
    case.check_bounds([(case.quantity, market.marketable_buy())])
    case.check_bounds([(quantity, market.just_below())], market_lot_probe=market_lot_probe)
    placed, status = await case.open_long(market, f"{tag}e")
    if not placed.ok:
        return case.not_observed(f"entry rejected: {_class_code(placed)}")
    if status != ORDER_STATUS_FILLED:
        return case.not_observed(
            f"no open position: the entry did not fill: status {status or 'unreadable'}"
        )
    fresh = await case.market()
    leg_id = case.client_id(f"{tag}x")
    case.detail("client_algo_id", leg_id)
    leg = await case.conditional(
        "exit_leg",
        client_id=leg_id,
        side=SIDE_SELL,
        order_type=ORDER_TYPE_STOP_MARKET,
        trigger=fresh.just_below(),
        quantity=quantity,
        reduce_only=True,
        market_lot_probe=market_lot_probe,
    )
    case.detail("exit_leg_accepted", _flag_text(leg.ok))
    if not leg.ok:
        if market_lot_probe:
            return case.observed()
        return case.not_observed(f"the exit leg was not accepted: {_class_code(leg)}")
    rest: list[str] = []

    def frame_statuses() -> list[str]:
        return [frame.get("algo_status", "") for frame in _algo_frames(case.frames(), leg_id)]

    async def ended() -> bool:
        rest.append(await case.algo_status("exit_query", leg_id))
        seen = [rest[-1], *frame_statuses()]
        return any(status in ALGO_ENDED_STATUSES or status == ALGO_ABSENT for status in seen)

    await wait_up_to(case.rig, ended, case.case_timeout_seconds)
    streamed = frame_statuses()
    case.detail("algo_statuses_rest", ",".join(status or "unreadable" for status in rest))
    case.detail("algo_statuses_frames", ",".join(streamed) or "none")
    _record_child_identity(case, leg_id)
    progressed = ALGO_LIFECYCLE_STATUSES | ALGO_ENDED_STATUSES
    if not any(status in progressed for status in [*rest, *streamed]):
        return case.not_observed(REASON_NOT_TRIGGERED)
    return case.observed()


async def _triggered_market_exit_lifecycle(case: _WriteCase) -> CaseResult:
    if MARKET_LOT_CASE in case.context.config.case_ids:
        question = (
            f"NOT_OBSERVED at the approved size; the optional case {MARKET_LOT_CASE} "
            "of this run answers it"
        )
    else:
        question = (
            f"NOT_OBSERVED at the approved size: the optional case {MARKET_LOT_CASE} is not enabled"
        )
    case.detail("market_lot_size_question", question)
    return await _triggered_exit(case, quantity=case.quantity, market_lot_probe=False, tag="tml")


async def _market_lot_size_out_of_range(case: _WriteCase) -> CaseResult:
    approved = case.limits.market_lot_probe_quantity
    case.detail(
        "market_lot_probe_quantity",
        format(approved, "f") if approved is not None else "not approved",
    )
    return await _triggered_exit(case, quantity=approved, market_lot_probe=True, tag="mlo")


async def _explicit_time_in_force_variant(case: _WriteCase) -> CaseResult:
    market = await case.market()
    trigger = market.far_below(case.fraction)
    case.check_bounds([(case.quantity, trigger)])
    for time_in_force in DOCUMENTED_ALGO_TIME_IN_FORCE:
        await _place_flat_leg(
            case,
            f"leg_{time_in_force}",
            case.client_id("tif"),
            trigger,
            time_in_force=time_in_force,
        )
    return case.observed()


async def _stream_gap_during_case(case: _WriteCase) -> CaseResult:
    market = await case.market()
    price = market.far_below(case.fraction)
    case.check_bounds([(case.quantity, price)])
    order_id = case.client_id("gap")
    case.detail("client_order_id", order_id)
    placed = await case.limit("far_order", client_id=order_id, side=SIDE_BUY, price=price)
    if not placed.ok:
        return case.not_observed(f"the far order was rejected: {_class_code(placed)}")
    gap_marker = case.port.marker()
    dropped = await case.port.drop_stream_transport()
    case.detail("transport_dropped", _flag_text(dropped))
    if not dropped:
        return case.not_observed(REASON_NO_STREAM)

    async def recovered() -> bool:
        return StreamState.LIVE.value in case.port.stream_states_since(gap_marker)

    back = await wait_up_to(case.rig, recovered, case.case_timeout_seconds)
    states = case.port.stream_states_since(gap_marker)
    case.detail("stream_states_after_drop", ",".join(states) or "none")
    case.detail("stream_recovered_live", _flag_text(back))
    await case.reconcile(open_orders=1, open_algo_orders=0, position=Decimal(0))
    await case.cancel("far_order_cancel", order_id)
    return case.observed()


async def case_below_min_notional_reduce_only_leg(context: CaseContext) -> CaseResult:
    """G2-029: a reduce-only conditional leg below the minimum notional, on an open position."""
    return await run_write_case(
        context,
        _below_min_notional_reduce_only_leg,
        case_id="below_min_notional_reduce_only_leg",
        reduce_only=True,
    )


async def case_triggered_market_exit_lifecycle(context: CaseContext) -> CaseResult:
    """G2-029: a reduce-only STOP_MARKET that triggers; lifecycle and child order identity."""
    return await run_write_case(
        context,
        _triggered_market_exit_lifecycle,
        case_id="triggered_market_exit_lifecycle",
        reduce_only=True,
    )


async def case_explicit_time_in_force_variant(context: CaseContext) -> CaseResult:
    """Optional: the pre-placed leg once per documented time-in-force value."""
    return await run_write_case(
        context,
        _explicit_time_in_force_variant,
        case_id="explicit_time_in_force_variant",
        reduce_only=True,
    )


async def case_stream_gap_during_case(context: CaseContext) -> CaseResult:
    """Optional: drop the private connection during an open far order; recovery and REST."""
    return await run_write_case(
        context, _stream_gap_during_case, case_id="stream_gap_during_case", reduce_only=False
    )


async def case_market_lot_size_out_of_range(context: CaseContext) -> CaseResult:
    """Optional: the triggered exit with the owner-approved market_lot_probe_quantity."""
    return await run_write_case(
        context, _market_lot_size_out_of_range, case_id=MARKET_LOT_CASE, reduce_only=True
    )


async def case_preplaced_stop_reduce_only_flat(context: CaseContext) -> CaseResult:
    """A STOP_MARKET with explicit quantity and reduceOnly while flat (D055)."""
    return await run_write_case(
        context, _preplaced_stop_reduce_only_flat, case_id=PREPLACED_CASE, reduce_only=True
    )


async def case_closeposition_stop_flat(context: CaseContext) -> CaseResult:
    """A close-position STOP_MARKET while flat (-4509 seen in Phase 9; the answer is the fact)."""
    return await run_write_case(
        context, _closeposition_stop_flat, case_id="closeposition_stop_flat", reduce_only=False
    )


async def case_entry_never_fills_protective_orphan(context: CaseContext) -> CaseResult:
    """A far entry plus the pre-placed leg; the entry is cancelled: is the leg orphaned?"""
    return await run_write_case(
        context,
        _entry_never_fills_protective_orphan,
        case_id="entry_never_fills_protective_orphan",
        reduce_only=True,
    )


async def case_full_fill_protective_quantity(context: CaseContext) -> CaseResult:
    """The pre-placed leg, then a marketable entry that fills: leg quantity versus position."""
    return await run_write_case(
        context,
        _full_fill_protective_quantity,
        case_id="full_fill_protective_quantity",
        reduce_only=True,
    )


async def case_rejected_protective_variants(context: CaseContext) -> CaseResult:
    """Three protective variants the docs call invalid; each answer recorded, none retried."""
    return await run_write_case(
        context,
        _rejected_protective_variants,
        case_id="rejected_protective_variants",
        reduce_only=False,
    )


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


# --------------------------------------------------------------------------- #
# Quick task 261021-sj0: the owner opt-in evidence-capture cases (`CAPTURE_CASES`).
#
# Facts only: each case records what the exchange answered (and the frames it produced) and
# decides nothing; D055 stays OPEN and no parameter is chosen (D-17). They run only when the
# owner enables their key in the probe limits file, go through `run_write_case` (so the
# one-way, bound and cleanup rules apply) and never retry a request.
# --------------------------------------------------------------------------- #


def _positive_int_text(summary: Mapping[str, str], key: str) -> int | None:
    text = summary.get(key, "")
    if not (text.isascii() and text.isdigit()):
        return None
    value = int(text)
    return value if value > 0 else None


def _algo_id_of(answer: ProbeObservation) -> int | None:
    """The exchange's algo id of an accepted answer (ASCII digits, positive), else None."""
    return _positive_int_text(answer.summary, "algo_id") if answer.ok else None


def _order_id_of(answer: ProbeObservation) -> int | None:
    """The exchange's order id of an accepted answer (ASCII digits, positive), else None."""
    return _positive_int_text(answer.summary, "order_id") if answer.ok else None


def _field_set(summary: Mapping[str, str]) -> str:
    """The sorted unique field names of a flat summary, list positions shown as ``*``."""
    names = {
        ".".join("*" if part.isascii() and part.isdigit() else part for part in key.split("."))
        for key in summary
    }
    return ",".join(sorted(names))


async def _account_read_only_capture(case: _WriteCase) -> CaseResult:
    port = case.port
    symbol = case.symbol
    steps: tuple[tuple[str, Callable[[], Awaitable[ProbeObservation]]], ...] = (
        ("account_information", lambda: port.account_information()),
        ("account_balance_all", lambda: port.account_balance_all()),
        ("account_config", lambda: port.account_config()),
        ("symbol_config", lambda: port.symbol_config(symbol=symbol)),
        ("leverage_brackets", lambda: port.leverage_brackets(symbol=symbol)),
        ("position_mode", lambda: port.position_mode()),
    )
    for label, call in steps:
        answer = await case.ask(label, call())
        if not answer.ok:
            continue
        case.detail(f"{label}_fields", _field_set(answer.summary))
        case.detail(f"{label}_field_count", str(len(answer.summary)))
        if answer.summary.get("truncated") == _TRUE:
            case.detail(f"{label}_truncated", _TRUE)
    return case.observed()


async def _timing_variant(
    case: _WriteCase, prefix: str, leg_id: str, placed: ProbeObservation
) -> None:
    """Query a just-placed algo leg by client id and by algo id, wait once, cancel, query."""
    placed_at = _checked_now(case.rig)
    algo_id = _algo_id_of(placed)
    if algo_id is None:
        case.detail(
            f"{prefix}_algo_id",
            "NOT_OBSERVED: the placement answer carried no algo id; "
            "no query by algo id was sent for this leg",
        )
    else:
        case.detail(f"{prefix}_algo_id", str(algo_id))
    attempts = 0

    async def query_both(phase: str) -> bool:
        """One query by client id and, when the id is known, one by algo id; all answered OK?"""
        answers = []
        elapsed = case.elapsed_ms(placed_at)
        by_client = await case.ask(
            f"{prefix}_{phase}_by_client_id", case.port.query_algo_order(client_algo_id=leg_id)
        )
        case.detail(f"{prefix}_{phase}_by_client_id_elapsed_ms", str(elapsed))
        answers.append(by_client)
        if algo_id is not None:
            elapsed = case.elapsed_ms(placed_at)
            by_id = await case.ask(
                f"{prefix}_{phase}_by_algo_id",
                case.port.query_algo_order_by_algo_id(algo_id=algo_id),
            )
            case.detail(f"{prefix}_{phase}_by_algo_id_elapsed_ms", str(elapsed))
            answers.append(by_id)
        return all(answer.ok for answer in answers)

    async def found() -> bool:
        nonlocal attempts
        attempts += 1
        return await query_both(f"query{attempts}")

    await wait_up_to(case.rig, found, case.case_timeout_seconds)
    case.detail(f"{prefix}_queries_before_all_ok", str(attempts))
    listed = await case.ask(
        f"{prefix}_open_algo_orders", case.port.open_algo_orders(symbol=case.symbol)
    )
    row = _row_values(listed, "client_algo_id", leg_id)
    case.detail(
        f"{prefix}_listed_in_open_algo_orders",
        _flag_text(row is not None) if _count(listed) is not None else "unknown",
    )
    await case.cancel_algo(f"{prefix}_cancel", leg_id)
    await query_both("after_cancel")


async def _algo_query_timing_after_new(case: _WriteCase) -> CaseResult:
    market = await case.market()
    trigger = market.far_below(case.fraction)
    carrier_trigger = market.far_above(case.fraction)
    case.check_bounds([(case.quantity, trigger), (case.quantity, carrier_trigger)])
    for prefix, tag in (("ro", "aqr"), ("carrier", "aqc")):
        leg_id = case.client_id(tag)
        case.detail(f"{prefix}_client_algo_id", leg_id)
        if prefix == "ro":
            placed = await _place_flat_leg(
                case, f"{prefix}_place", leg_id, trigger, time_in_force=None
            )
        else:
            placed = await _place_carrier(case, market, f"{prefix}_place", leg_id)
        case.detail(f"{prefix}_placement_accepted", _flag_text(placed.ok))
        if not placed.ok:
            continue
        await _timing_variant(case, prefix, leg_id, placed)
    return case.observed()


def _count_text(value: object) -> str:
    return str(value) if isinstance(value, int) else "unreadable"


def _near_triggers(mark: Decimal, tick: Decimal, fraction: Decimal) -> tuple[Decimal, Decimal]:
    """A trigger just below and one just above the live `mark`, on the tick grid.

    below = min(floor(mark x fraction), the highest tick strictly below the mark);
    above = max(ceil(mark x (2 - fraction)), the lowest tick strictly above the mark). The tick
    rule keeps both on the right side of the mark for a fraction very close to 1.
    """
    units = mark / tick
    highest_below = (units.to_integral_value(rounding=ROUND_CEILING) - 1) * tick
    lowest_above = (units.to_integral_value(rounding=ROUND_FLOOR) + 1) * tick
    near_below = (mark * fraction / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
    far = mark * (Decimal(2) - fraction)
    near_above = (far / tick).to_integral_value(rounding=ROUND_CEILING) * tick
    return min(near_below, highest_below), max(near_above, lowest_above)


_PROGRESSED_STATUSES: frozenset[str] = ALGO_LIFECYCLE_STATUSES | ALGO_ENDED_STATUSES
_CANCEL_STATUSES: frozenset[str] = frozenset({"CANCELED", "REJECTED", "EXPIRED"})
WIRE_ALGO_UPDATE = "ALGO_UPDATE"
WIRE_ORDER_UPDATE = "ORDER_TRADE_UPDATE"
_TRADE_KEYS: tuple[str, ...] = (
    "trade_id",
    "side",
    "price",
    "qty",
    "quote_qty",
    "commission",
    "commission_asset",
    "realized_pnl",
    "maker",
    "time_ms",
)
_INCOME_KEYS: tuple[str, ...] = (
    "income_type",
    "income",
    "asset",
    "trade_id",
    "tran_id",
    "time_ms",
)
NOT_OBSERVED_ORDER_ID = "NOT_OBSERVED: the answer carried no order id"


@dataclass
class _Leg:
    """One algo leg a capture case placed: its label prefix, client algo id, REST statuses."""

    prefix: str
    leg_id: str
    rest: list[str] = field(default_factory=list)


def _leg_statuses(case: _WriteCase, leg: _Leg) -> list[str]:
    """Every status seen for the leg: the REST answers, then the typed ALGO_UPDATE frames."""
    streamed = [frame.get("algo_status", "") for frame in _algo_frames(case.frames(), leg.leg_id)]
    return [*leg.rest, *streamed]


def _progressed(statuses: Sequence[str]) -> bool:
    """A status after NEW (lifecycle or ended); an ORDER_ABSENT answer never counts."""
    return any(status in _PROGRESSED_STATUSES for status in statuses)


def _ended(statuses: Sequence[str]) -> bool:
    return any(status in ALGO_ENDED_STATUSES for status in statuses)


def _triggered(statuses: Sequence[str]) -> bool:
    return any(status in ALGO_LIFECYCLE_STATUSES for status in statuses)


def _auto_cancelled(leg: _Leg, statuses: Sequence[str]) -> str:
    """true: a cancel-type end was seen; false: still NEW at the last query; else unknown."""
    if any(status in _CANCEL_STATUSES for status in statuses):
        return _TRUE
    if leg.rest and leg.rest[-1] == ALGO_STATUS_NEW:
        return _FALSE
    return "unknown"


def _raw_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return _TRUE if value else _FALSE
    return str(value)


def _distinct(values: Sequence[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _raw_algo_updates(case: _WriteCase, leg_id: str) -> list[Mapping[str, Any]]:
    """The raw ALGO_UPDATE payloads of one leg since the case started, in delivery order."""
    updates: list[Mapping[str, Any]] = []
    for raw in case.port.raw_frames_since(case.marker):
        if not isinstance(raw, Mapping) or raw.get("e") != WIRE_ALGO_UPDATE:
            continue
        body = raw.get("o")
        if isinstance(body, Mapping) and body.get("caid") == leg_id:
            updates.append(raw)
    return updates


def _last_raw_field(updates: Sequence[Mapping[str, Any]], wire: str) -> str:
    values = [_raw_text(update["o"].get(wire)) for update in updates]
    return next((value for value in reversed(values) if value), "")


def _last_field(frames: Sequence[Mapping[str, str]], name: str) -> str | None:
    return next((frame[name] for frame in reversed(frames) if frame.get(name)), None)


def _leg_actual_order_id(case: _WriteCase, leg: _Leg) -> str:
    """The matching-engine order id (`ai`) of the leg: typed frames first, else the raw ones."""
    typed = _last_field(_algo_frames(case.frames(), leg.leg_id), "actual_order_id")
    return typed or _last_raw_field(_raw_algo_updates(case, leg.leg_id), "ai")


def _record_leg_lifecycle(case: _WriteCase, leg: _Leg) -> None:
    """REST and typed-frame statuses of the leg, and its `ai`, `aq`, `rm` (facts only)."""
    prefix = leg.prefix
    frames = _algo_frames(case.frames(), leg.leg_id)
    updates = _raw_algo_updates(case, leg.leg_id)
    case.detail(
        f"{prefix}_statuses_rest", ",".join(status or "unreadable" for status in leg.rest) or "none"
    )
    case.detail(
        f"{prefix}_statuses_frames",
        ",".join(frame.get("algo_status", "") for frame in frames) or "none",
    )
    for name, typed_key, wire in (
        ("ai", "actual_order_id", "ai"),
        ("aq", "executed_quantity", "aq"),
        ("rm", "reject_reason", "rm"),
    ):
        value = _last_field(frames, typed_key) or _last_raw_field(updates, wire)
        case.detail(
            f"{prefix}_{name}", value or f"NOT_OBSERVED: no ALGO_UPDATE frame carried {name}"
        )


def _record_algo_update_sequence(case: _WriteCase, leg: _Leg) -> None:
    """The full raw ALGO_UPDATE sequence of one leg and its raw child ORDER_TRADE_UPDATE.

    Every delivery in delivery order (`X|ia|ai|aq|rm|E|T`, values verbatim as text), the
    statuses delivered more than once, the statuses beyond NEW and CANCELED, the distinct
    `ia`, `ai` and `aq` values, and for each distinct non-empty `ai` the raw child frames
    (`c|X|x|ot|z|ap|n|N|rp|T`). Facts only; it decides nothing (owner audit addition b).
    """
    prefix = leg.prefix
    raws = case.port.raw_frames_since(case.marker)
    updates = _raw_algo_updates(case, leg.leg_id)
    if not updates:
        case.detail(
            f"{prefix}_algo_update_sequence", "NOT_OBSERVED: no raw ALGO_UPDATE frame for this leg"
        )
        return
    bodies = [update["o"] for update in updates]
    items = [
        "|".join(
            _raw_text(value)
            for value in (
                body.get("X"),
                body.get("ia"),
                body.get("ai"),
                body.get("aq"),
                body.get("rm"),
                update.get("E"),
                update.get("T"),
            )
        )
        for update, body in zip(updates, bodies, strict=True)
    ]
    statuses = [_raw_text(body.get("X")) for body in bodies]
    repeated = [f"{status} x{statuses.count(status)}" for status in _distinct(statuses)]
    repeated = [item for item in repeated if not item.endswith(" x1")]
    beyond = sorted({status for status in statuses if status not in ("NEW", "CANCELED")})
    case.detail(f"{prefix}_algo_update_count", str(len(updates)))
    case.detail(f"{prefix}_algo_update_sequence", ";".join(items))
    case.detail(f"{prefix}_repeated_statuses", ", ".join(repeated) or "none")
    case.detail(f"{prefix}_statuses_beyond_new_canceled", ",".join(beyond) or "none")
    for key, wire in (("ia", "ia"), ("ai", "ai"), ("aq", "aq")):
        values = _distinct([_raw_text(body.get(wire)) for body in bodies])
        case.detail(f"{prefix}_{key}_values", ",".join(value or "(empty)" for value in values))
    child = 0
    for actual in [value for value in _distinct([_raw_text(b.get("ai")) for b in bodies]) if value]:
        found = False
        for raw in raws:
            order = raw.get("o") if isinstance(raw, Mapping) else None
            if (
                isinstance(raw, Mapping)
                and raw.get("e") == WIRE_ORDER_UPDATE
                and isinstance(order, Mapping)
                and _raw_text(order.get("i")) == actual
            ):
                child += 1
                found = True
                case.detail(
                    f"{prefix}_child_{child}",
                    "|".join(
                        _raw_text(value)
                        for value in (
                            order.get("c"),
                            order.get("X"),
                            order.get("x"),
                            order.get("ot"),
                            order.get("z"),
                            order.get("ap"),
                            order.get("n"),
                            order.get("N"),
                            order.get("rp"),
                            order.get("T"),
                        )
                    ),
                )
        if not found:
            case.detail(
                f"{prefix}_child_of_ai_{actual}",
                "NOT_OBSERVED: no raw ORDER_TRADE_UPDATE frame with this order id",
            )


async def _wait_for_progress(case: _WriteCase, legs: Sequence[_Leg]) -> bool:
    """One wait of the owner timeout until some leg shows a status after NEW (REST or frames).

    An ORDER_ABSENT answer (-2013) is recorded but never counts as ended or progressed: the
    Demo answers it right after a NEW placement, which ended the wait of the Phase 18 case
    `triggered_market_exit_lifecycle` at once (the 20261021T132718Z run).
    """

    async def any_progressed() -> bool:
        for leg in legs:
            leg.rest.append(await case.algo_status(f"{leg.prefix}_wait_query", leg.leg_id))
        return any(_progressed(_leg_statuses(case, leg)) for leg in legs)

    return await wait_up_to(case.rig, any_progressed, case.case_timeout_seconds)


async def _open_position(
    case: _WriteCase, market: _Market, tag: str, quantity: Decimal | None = None
) -> tuple[CaseResult | None, ProbeObservation]:
    """The marketable entry of a capture case; a NOT_OBSERVED result when it did not fill.

    `quantity` (quick task 261023-sj2) may be a smaller quantity than the approved one.
    """
    placed, status = await case.open_long(market, tag, quantity)
    if not placed.ok:
        return case.not_observed(f"entry rejected: {_class_code(placed)}"), placed
    if status != ORDER_STATUS_FILLED:
        reason = f"the entry did not fill: status {status or 'unreadable'}"
        return case.not_observed(reason), placed
    return None, placed


async def _place_close_position_legs(
    case: _WriteCase, *, below: Decimal, above: Decimal, stop_tag: str, tp_tag: str
) -> tuple[list[_Leg], str]:
    """A closePosition STOP_MARKET SELL at `below` and TAKE_PROFIT_MARKET SELL at `above`.

    Returns the accepted legs (prefixes ``stop`` and ``tp``) and the codes of the rejected.
    """
    legs: list[_Leg] = []
    codes: list[str] = []
    for prefix, tag, order_type, trigger in (
        ("stop", stop_tag, ORDER_TYPE_STOP_MARKET, below),
        ("tp", tp_tag, ORDER_TYPE_TAKE_PROFIT_MARKET, above),
    ):
        leg_id = case.client_id(tag)
        case.detail(f"{prefix}_client_algo_id", leg_id)
        answer = await case.conditional(
            f"{prefix}_leg",
            client_id=leg_id,
            side=SIDE_SELL,
            order_type=order_type,
            trigger=trigger,
            quantity=None,
            close_position=True,
        )
        case.detail(f"{prefix}_leg_accepted", _flag_text(answer.ok))
        if answer.ok:
            legs.append(_Leg(prefix, leg_id))
        else:
            codes.append(f"{prefix} {_class_code(answer)}")
    return legs, ", ".join(codes)


async def _close_position_stop_with_position(case: _WriteCase) -> CaseResult:
    market = await case.market()
    below = market.far_below(case.fraction)
    above = market.far_above(case.fraction)
    case.check_bounds([(case.quantity, market.marketable_buy()), (None, below), (None, above)])
    refusal, _ = await _open_position(case, market, "cpe")
    if refusal is not None:
        return refusal
    legs: list[_Leg] = []
    for prefix, label, tag, order_type, trigger in (
        ("stop", "close_position_stop", "cps", ORDER_TYPE_STOP_MARKET, below),
        ("tp", "close_position_tp", "cpt", ORDER_TYPE_TAKE_PROFIT_MARKET, above),
    ):
        leg_id = case.client_id(tag)
        answer = await case.conditional(
            label,
            client_id=leg_id,
            side=SIDE_SELL,
            order_type=order_type,
            trigger=trigger,
            quantity=None,
            close_position=True,
        )
        case.detail(f"{label}_accepted", _flag_text(answer.ok))
        if answer.ok:
            legs.append(_Leg(prefix, leg_id))
    for leg in legs:
        await case.algo_status(f"{leg.prefix}_status", leg.leg_id)
    if legs:
        answers = await case.observe_state("with_legs")
        for leg in legs:
            row = _row_values(answers["open_algo_orders"], "client_algo_id", leg.leg_id)
            for key, value in (row or {}).items():
                case.detail(f"{leg.prefix}_listed_{key}", value)
        for leg in legs:
            await case.cancel_algo(f"{leg.prefix}_cancel", leg.leg_id)
    return case.observed()


async def _stop_would_trigger_after_fill(case: _WriteCase) -> CaseResult:
    market = await case.market()
    above = market.far_above(case.fraction)
    case.check_bounds([(case.quantity, market.marketable_buy()), (None, above)])
    refusal, _ = await _open_position(case, market, "wte")
    if refusal is not None:
        return refusal
    leg_id = case.client_id("wts")
    case.detail("client_algo_id", leg_id)
    answer = await case.conditional(
        "would_trigger_stop",
        client_id=leg_id,
        side=SIDE_SELL,
        order_type=ORDER_TYPE_STOP_MARKET,
        trigger=above,
        quantity=None,
        close_position=True,
    )
    case.detail("would_trigger_accepted", _flag_text(answer.ok))
    if answer.ok:
        case.notes.append(
            "the wrong-side stop was accepted and may trigger at once; "
            "the runner cleanup flattens the position"
        )
        await case.algo_status("would_trigger_status", leg_id)
        await case.observe_state("after")
    return case.observed()


async def _stop_query_absent_then_same_id(case: _WriteCase) -> CaseResult:
    market = await case.market()
    below = market.far_below(case.fraction)
    case.check_bounds(
        [(case.quantity, market.marketable_buy()), (None, below), (case.quantity, below)]
    )
    refusal, _ = await _open_position(case, market, "sae")
    if refusal is not None:
        return refusal
    sid = case.client_id("sas")
    case.detail("client_algo_id", sid)
    await case.algo_status("query_before_place", sid)
    await case.conditional(
        "first_place",
        client_id=sid,
        side=SIDE_SELL,
        order_type=ORDER_TYPE_STOP_MARKET,
        trigger=below,
        quantity=None,
        close_position=True,
    )
    placed_at = _checked_now(case.rig)
    case.detail("query_right_after_place_elapsed_ms", str(case.elapsed_ms(placed_at)))
    await case.algo_status("query_right_after_place", sid)
    # The deliberate same-id re-placements of the owner request (Q5): not a retry of a failure.
    await case.conditional(
        "same_id_replace_close_position",
        client_id=sid,
        side=SIDE_SELL,
        order_type=ORDER_TYPE_STOP_MARKET,
        trigger=below,
        quantity=None,
        close_position=True,
    )
    await case.conditional(
        "same_id_replace_reduce_only",
        client_id=sid,
        side=SIDE_SELL,
        order_type=ORDER_TYPE_STOP_MARKET,
        trigger=below,
        quantity=case.quantity,
        reduce_only=True,
    )
    listing = await case.ask(
        "open_algo_orders_listing", case.port.open_algo_orders(symbol=case.symbol)
    )
    total = _count(listing)
    with_id = sum(
        1 for i in range(total or 0) if listing.summary.get(f"row_{i}_client_algo_id") == sid
    )
    case.detail("legs_listed_with_id", str(with_id) if total is not None else "unreadable")
    case.detail("legs_listed_total", str(total) if total is not None else "unreadable")
    await case.cancel_algo("cancel_once", sid)
    await case.algo_status("query_after_cancel", sid)
    return case.observed()


async def _manual_close_with_open_legs(case: _WriteCase) -> CaseResult:
    market = await case.market()
    below = market.far_below(case.fraction)
    above = market.far_above(case.fraction)
    case.check_bounds([(case.quantity, market.marketable_buy()), (None, below), (None, above)])
    refusal, _ = await _open_position(case, market, "mce")
    if refusal is not None:
        return refusal
    legs, codes = await _place_close_position_legs(
        case, below=below, above=above, stop_tag="mcs", tp_tag="mct"
    )
    if not legs:
        return case.not_observed(f"{REASON_CLOSE_LEGS_REJECTED}: {codes}")
    held = await case.held_quantity("position_before_close")
    case.detail("held_quantity", format(held, "f"))
    if held <= 0:
        return case.not_observed(REASON_NO_POSITION_HELD)
    closed, close_id = await case.market_close("manual_close", held, market.marketable_buy(), "mcx")
    case.detail("manual_close_client_id", close_id)
    case.detail(
        "manual_close_status",
        closed.summary.get("status", "NOT_OBSERVED: no status")
        if closed.ok
        else f"rejected {_class_code(closed)}",
    )
    case.detail(
        "manual_close_executed_qty",
        closed.summary.get("executed_qty", "NOT_OBSERVED: not answered"),
    )

    async def legs_ended() -> bool:
        for leg in legs:
            leg.rest.append(await case.algo_status(f"{leg.prefix}_wait_query", leg.leg_id))
        return all(_ended(_leg_statuses(case, leg)) for leg in legs)

    await wait_up_to(case.rig, legs_ended, case.case_timeout_seconds)
    verdicts: dict[str, str] = {}
    for leg in legs:
        _record_leg_lifecycle(case, leg)
        _record_algo_update_sequence(case, leg)
        verdicts[leg.leg_id] = _auto_cancelled(leg, _leg_statuses(case, leg))
        case.detail(f"{leg.prefix}_auto_cancelled", verdicts[leg.leg_id])
    await case.observe_state("after_close")
    for leg in legs:
        if verdicts[leg.leg_id] != _TRUE:
            await case.cancel_algo(f"{leg.prefix}_cancel", leg.leg_id)
    return case.observed()


def _trade_rows(answer: ProbeObservation) -> list[dict[str, str]]:
    return [
        {key: answer.summary.get(f"row_{i}_{key}", "") for key in _TRADE_KEYS}
        for i in range(_count(answer) or 0)
    ]


def _income_rows(answer: ProbeObservation) -> list[dict[str, str]]:
    return [
        {key: answer.summary.get(f"row_{i}_{key}", "") for key in _INCOME_KEYS}
        for i in range(_count(answer) or 0)
    ]


def _decimal_or_none(text: str) -> Decimal | None:
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _decimal_sum(texts: Sequence[str]) -> Decimal | None:
    """The exact sum, or None when there is no value or one is not a finite decimal."""
    values = [_decimal_or_none(text) for text in texts]
    if not values or any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), Decimal(0))


async def _commission_vs_realized_pnl(case: _WriteCase) -> CaseResult:
    market = await case.market()
    case.check_bounds([(case.quantity, market.marketable_buy())])
    refusal, entry = await _open_position(case, market, "cre")
    if refusal is not None:
        return refusal
    entry_id = _order_id_of(entry)
    case.detail("entry_order_id", str(entry_id) if entry_id is not None else NOT_OBSERVED_ORDER_ID)
    held = await case.held_quantity("position_before_close")
    case.detail("held_quantity", format(held, "f"))
    if held <= 0:
        return case.not_observed(REASON_NO_POSITION_HELD)
    closed, close_client_id = await case.market_close("close", held, market.marketable_buy(), "crx")
    close_id = _order_id_of(closed)
    case.detail("close_client_id", close_client_id)
    case.detail("close_order_id", str(close_id) if close_id is not None else NOT_OBSERVED_ORDER_ID)
    without = "the answer carried no order id: queried without order_id (all recent trades)"
    if close_id is None:
        case.detail("close_trades_query_note", without)
    last_close: list[ProbeObservation] = []

    async def close_trades_seen() -> bool:
        answer = await case.ask(
            "close_trades_query", case.port.user_trades(symbol=case.symbol, order_id=close_id)
        )
        last_close[:] = [answer]
        return (_count(answer) or 0) >= 1

    await wait_up_to(case.rig, close_trades_seen, case.case_timeout_seconds)
    if entry_id is None:
        case.detail("entry_trades_query_note", without)
    entry_trades = await case.ask(
        "entry_trades_query", case.port.user_trades(symbol=case.symbol, order_id=entry_id)
    )
    close_rows = _trade_rows(last_close[0]) if last_close else []
    entry_rows = _trade_rows(entry_trades)
    for prefix, rows in (("close", close_rows), ("entry", entry_rows)):
        for number, row in enumerate(rows, start=1):
            case.detail(f"{prefix}_trade_{number}", "|".join(row[key] for key in _TRADE_KEYS))
    unique: dict[str, dict[str, str]] = {}
    for row in [*close_rows, *entry_rows]:
        unique.setdefault(row["trade_id"], row)
    times = [int(row["time_ms"]) for row in unique.values() if row["time_ms"].isdigit()]
    income: list[dict[str, str]] = []
    if not times:
        case.detail("income_history", "NOT_OBSERVED: no trade time to start the income read from")
    else:
        start_ms = min(times)  # the exchange clock of the earliest trade

        async def income_seen() -> bool:
            answer = await case.ask(
                "income_history_query",
                case.port.income_history(symbol=case.symbol, start_time_ms=start_ms),
            )
            income[:] = [row for row in _income_rows(answer) if row["trade_id"] in unique]
            return bool(income)

        await wait_up_to(case.rig, income_seen, case.case_timeout_seconds)
    for number, row in enumerate(income, start=1):
        case.detail(f"income_{number}", "|".join(row[key] for key in _INCOME_KEYS))
    _record_derived_sums(case, list(unique.values()), income)
    return case.observed()


def _record_derived_sums(
    case: _WriteCase, trades: Sequence[Mapping[str, str]], income: Sequence[Mapping[str, str]]
) -> None:
    """Exact Decimal sums of the recorded rows, named ``derived_`` (arithmetic, no verdict).

    Whether realizedPnl includes the commission is the owner decision
    `LIVE_NET_PNL_SEMANTICS_VERIFIED`; nothing here answers it.
    """
    quotes: list[Decimal] = []
    for row in trades:
        value = _decimal_or_none(row["quote_qty"])
        if value is None or row["side"] not in (SIDE_BUY, SIDE_SELL):
            quotes = []
            break
        quotes.append(value if row["side"] == SIDE_SELL else -value)
    case.detail(
        "derived_sell_quote_minus_buy_quote",
        format(sum(quotes, Decimal(0)), "f") if quotes else "NOT_OBSERVED: no usable quote_qty",
    )
    realized = _decimal_sum([row["realized_pnl"] for row in trades])
    case.detail(
        "derived_sum_realized_pnl_trades",
        format(realized, "f") if realized is not None else "NOT_OBSERVED: no usable realized_pnl",
    )
    assets = {row["commission_asset"] for row in trades}
    case.detail("commission_assets", ",".join(sorted(assets)) or "none")
    commission = _decimal_sum([row["commission"] for row in trades])
    if len(assets) == 1 and commission is not None:
        case.detail("derived_sum_commission_trades", format(commission, "f"))
    for key, income_type in (
        ("derived_income_realized_pnl_sum", "REALIZED_PNL"),
        ("derived_income_commission_sum", "COMMISSION"),
    ):
        total = _decimal_sum([row["income"] for row in income if row["income_type"] == income_type])
        case.detail(
            key, format(total, "f") if total is not None else "NOT_OBSERVED: no matching income row"
        )


async def _triggered_close_position_bracket(case: _WriteCase) -> CaseResult:
    market = await case.market()
    case.check_bounds(
        [
            (case.quantity, market.marketable_buy()),
            (None, market.far_below(case.fraction)),
            (None, market.far_above(case.fraction)),
        ]
    )
    refusal, _ = await _open_position(case, market, "tbe")
    if refusal is not None:
        return refusal
    live = await case.live_mark()
    below, above = _near_triggers(live, market.tick, case.near_trigger_fraction)
    case.detail("stop_trigger_price", format(below, "f"))
    case.detail("tp_trigger_price", format(above, "f"))
    case.check_bounds([(None, below), (None, above)])
    legs, codes = await _place_close_position_legs(
        case, below=below, above=above, stop_tag="tbs", tp_tag="tbt"
    )
    if not legs:
        return case.not_observed(f"{REASON_CLOSE_LEGS_REJECTED}: {codes}")
    if not await _wait_for_progress(case, legs):
        for leg in legs:
            _record_leg_lifecycle(case, leg)
            _record_algo_update_sequence(case, leg)
        await case.observe_state("not_triggered")
        return case.not_observed(REASON_NOT_TRIGGERED)
    triggered = [leg for leg in legs if _triggered(_leg_statuses(case, leg))]
    if len(triggered) == len(legs) and len(legs) == 2:
        case.detail("triggered_leg", "both")
    else:
        case.detail("triggered_leg", triggered[0].prefix if triggered else "unknown")
    others = [leg for leg in legs if leg not in triggered]

    async def settled() -> bool:
        held = await case.held_quantity("settle_position")
        for leg in others:
            leg.rest.append(await case.algo_status(f"{leg.prefix}_settle_query", leg.leg_id))
        return held == 0 and all(_ended(_leg_statuses(case, leg)) for leg in others)

    await wait_up_to(case.rig, settled, case.case_timeout_seconds)
    for leg in legs:
        _record_leg_lifecycle(case, leg)
        _record_algo_update_sequence(case, leg)
    for leg in others:
        case.detail(f"{leg.prefix}_auto_cancelled", _auto_cancelled(leg, _leg_statuses(case, leg)))
    await case.observe_state("after_trigger")
    if triggered:
        child = _leg_actual_order_id(case, triggered[0])
        if child.isascii() and child.isdigit():
            await case.ask(
                "child_trades_query", case.port.user_trades(symbol=case.symbol, order_id=int(child))
            )
    return case.observed()


def _lot_filters(symbol: str, market: _Market) -> LotFilters | None:
    """The exchange lot filters of the case market as `LotFilters`, None when one is unreadable."""
    filters = market.filters
    try:
        return LotFilters(
            symbol=symbol,
            price_tick_size=Decimal(filters["tick_size"]),
            lot_min_quantity=Decimal(filters["min_quantity"]),
            lot_max_quantity=Decimal(filters["max_quantity"]),
            lot_step_size=Decimal(filters["step_size"]),
            market_lot_min_quantity=Decimal(filters["market_lot_min_quantity"]),
            market_lot_max_quantity=Decimal(filters["market_lot_max_quantity"]),
            market_lot_step_size=Decimal(filters["market_lot_step_size"]),
            min_notional=Decimal(filters["min_notional"]),
        )
    except (KeyError, InvalidOperation, ValueError, TypeError):
        return None


async def _tp1_quantity_from_fill(case: _WriteCase) -> CaseResult:
    market = await case.market()
    case.check_bounds([(case.quantity, market.marketable_buy())])
    refusal, _ = await _open_position(case, market, "tpe")
    if refusal is not None:
        return refusal
    held = await case.held_quantity("position_after_fill")
    case.detail("held_quantity", format(held, "f"))
    if held <= 0:
        return case.not_observed(REASON_NO_POSITION_HELD)
    lot_filters = _lot_filters(case.symbol, market)
    if lot_filters is None:
        return case.not_observed(REASON_LOT_FILTERS_UNREADABLE)
    wanted = held * TP1_QUANTITY_FRACTION
    tp1 = min(quantize_to_lot(quantity=wanted, filters=lot_filters, market_exit=True), held)
    case.detail("tp1_quantity", format(tp1, "f"))
    case.detail(
        "tp1_quantity_lot_size_only",
        format(quantize_to_lot(quantity=wanted, filters=lot_filters, market_exit=False), "f"),
    )
    case.detail(
        "tp1_fraction_source",
        f"src.backtest.semantics.TP1_QUANTITY_FRACTION = {TP1_QUANTITY_FRACTION}",
    )
    if tp1 <= 0:
        return case.not_observed(REASON_TP1_ZERO)
    live = await case.live_mark()
    _, above = _near_triggers(live, market.tick, case.near_trigger_fraction)
    case.detail("tp_trigger_price", format(above, "f"))
    case.check_bounds([(tp1, above)])
    tp_id = case.client_id("tp1")
    case.detail("client_algo_id", tp_id)
    leg_answer = await case.conditional(
        "tp1_leg",
        client_id=tp_id,
        side=SIDE_SELL,
        order_type=ORDER_TYPE_TAKE_PROFIT_MARKET,
        trigger=above,
        quantity=tp1,
        reduce_only=True,
    )
    case.detail("tp1_leg_accepted", _flag_text(leg_answer.ok))
    if not leg_answer.ok:
        return case.not_observed(f"the TP1 leg was not accepted: {_class_code(leg_answer)}")
    case.detail("tp1_notional_at_trigger", format(tp1 * above, "f"))
    case.detail(
        "min_notional",
        format(market.min_notional, "f") if market.min_notional is not None else "not listed",
    )
    leg = _Leg("tp1", tp_id)
    progressed = await _wait_for_progress(case, [leg])
    _record_leg_lifecycle(case, leg)
    _record_algo_update_sequence(case, leg)
    await case.observe_state("after_tp1")
    if not progressed:
        return case.not_observed(REASON_NOT_TRIGGERED)
    return case.observed()


def _order_frames(
    frames: Sequence[Mapping[str, str]], client_order_id: str
) -> list[Mapping[str, str]]:
    return [
        frame
        for frame in frames
        if frame.get("event_type") == EVENT_ORDER_UPDATE
        and frame.get("client_order_id") == client_order_id
    ]


def _raw_order_updates(case: _WriteCase, client_order_id: str) -> list[str]:
    """``X|x|T`` of every raw ORDER_TRADE_UPDATE of one client order id, in delivery order."""
    items: list[str] = []
    for raw in case.port.raw_frames_since(case.marker):
        if not isinstance(raw, Mapping) or raw.get("e") != WIRE_ORDER_UPDATE:
            continue
        order = raw.get("o")
        if isinstance(order, Mapping) and order.get("c") == client_order_id:
            items.append("|".join(_raw_text(order.get(key)) for key in ("X", "x", "T")))
    return items


async def _gtd_entry_expiry_status(case: _WriteCase) -> CaseResult:
    market = await case.market()
    price = market.far_below(case.fraction)
    case.check_bounds([(case.quantity, price)])
    client_id = case.client_id("gtd")
    case.detail("client_order_id", client_id)
    placed_at = _checked_now(case.rig)
    lifetime = case.gtd_lifetime_seconds
    # Whole epoch seconds of the rig clock plus the owner lifetime, in milliseconds: integer
    # timedelta floor division only (no float).
    good_till_date_ms = ((placed_at - _EPOCH) // timedelta(seconds=1) + lifetime) * 1000
    case.detail("placed_at_utc", placed_at.isoformat())
    case.detail("good_till_date_lifetime_seconds", str(lifetime))
    case.detail("good_till_date_ms", str(good_till_date_ms))
    placed = await case.gtd_limit(
        "gtd_limit", client_id=client_id, price=price, good_till_date_ms=good_till_date_ms
    )
    echoed = placed.summary.get("good_till_date") if placed.ok else None
    if echoed:
        case.detail("good_till_date_echoed", echoed)
    if not placed.ok:
        return case.observed()  # the exchange answer to this GTD is the A1 fact itself
    rest: list[str] = []

    def frame_terminal() -> list[str]:
        return [
            frame.get("order_status", "")
            for frame in _order_frames(case.frames(), client_id)
            if frame.get("order_status", "") in ORDER_TERMINAL_STATUSES
        ]

    async def terminal() -> bool:
        # An ORDER_ABSENT answer is recorded ('' in `rest`) but never ends the wait.
        rest.append(await case.order_status("order_status_query", client_id))
        return rest[-1] in ORDER_TERMINAL_STATUSES or bool(frame_terminal())

    ended = await wait_up_to(case.rig, terminal, case.gtd_expiry_wait_seconds)
    streamed = _order_frames(case.frames(), client_id)
    case.detail("rest_statuses", ",".join(status or "unreadable" for status in rest))
    case.detail(
        "frame_statuses",
        ";".join(
            f"{frame.get('order_status', '')}/{frame.get('execution_type', '')}/"
            f"{frame.get('expire_reason', '')}"
            for frame in streamed
        )
        or "none",
    )
    raw_updates = _raw_order_updates(case, client_id)
    case.detail(
        "raw_order_updates", ";".join(raw_updates) or "NOT_OBSERVED: no raw ORDER_TRADE_UPDATE"
    )
    if rest[-1] in ORDER_TERMINAL_STATUSES:
        terminal_status = rest[-1]
    else:
        terminal_status = (frame_terminal() or ["none"])[-1]
    case.detail("terminal_status", terminal_status)
    if ended:
        elapsed = (_checked_now(case.rig) - placed_at) // timedelta(seconds=1)
        case.detail("seconds_to_terminal", str(elapsed))
        return case.observed()
    await case.cancel("gtd_cancel", client_id)
    return case.not_observed(REASON_GTD_NOT_TERMINAL)


# ----- quick task 261022-sj1: five more owner opt-in cases ------------------------------- #

# The four exchangeInfo filters the emergency close fallback depends on (A10, Q3):
# (filter, detail suffix, key of the `symbol_filters` summary).
_EXCHANGE_INFO_FILTERS: tuple[tuple[str, str, str], ...] = (
    ("LOT_SIZE", "min_qty", "min_quantity"),
    ("LOT_SIZE", "max_qty", "max_quantity"),
    ("LOT_SIZE", "step_size", "step_size"),
    ("MARKET_LOT_SIZE", "min_qty", "market_lot_min_quantity"),
    ("MARKET_LOT_SIZE", "max_qty", "market_lot_max_quantity"),
    ("MARKET_LOT_SIZE", "step_size", "market_lot_step_size"),
    ("PRICE_FILTER", "tick_size", "tick_size"),
    ("MIN_NOTIONAL", "notional", "min_notional"),
)
# The summary keys compared with the filters the run read at its start.
_SNAPSHOT_COMPARED: tuple[str, ...] = (
    "status",
    "tick_size",
    "step_size",
    "min_quantity",
    "max_quantity",
    "min_notional",
    "market_lot_min_quantity",
    "market_lot_max_quantity",
    "market_lot_step_size",
)
_RACE_FILLED_STATUSES: frozenset[str] = frozenset(
    {ORDER_STATUS_FILLED, ORDER_STATUS_PARTIALLY_FILLED}
)


def _ms_of(moment: datetime) -> int:
    """Whole epoch milliseconds of an aware datetime (integer arithmetic only)."""
    return (moment - _EPOCH) // timedelta(milliseconds=1)


def _code_text(answer: ProbeObservation) -> str:
    """The exact error code of an answer as text: ``accepted``, the int, or ``none``."""
    error = answer.error
    if answer.ok or error is None:
        return "accepted"
    return "none" if error.code is None else str(error.code)


def _book_side(book: ProbeObservation, side: str) -> list[tuple[Decimal, Decimal]] | None:
    """The (price, quantity) levels of one side of an `order_book` answer, best first.

    None when the answer is not OK or its count is unreadable; a level whose price or quantity
    is unreadable ends the list (nothing is guessed).
    """
    if not book.ok:
        return None
    count_text = book.summary.get(f"{side}_count", "")
    if not (count_text.isascii() and count_text.isdigit()):
        return None
    levels: list[tuple[Decimal, Decimal]] = []
    for index in range(int(count_text)):
        price = _positive_decimal(book.summary, f"{side}_{index}_price")
        quantity = _positive_decimal(book.summary, f"{side}_{index}_quantity")
        if price is None or quantity is None:
            break
        levels.append((price, quantity))
    return levels


async def _exchange_info_read_for_close(case: _WriteCase) -> CaseResult:
    started = _checked_now(case.rig)
    answer = await case.ask("symbol_filters_read", case.port.symbol_filters(symbol=case.symbol))
    case.detail("read_elapsed_ms", str(case.elapsed_ms(started)))
    case.detail(
        "read_endpoint",
        "GET /fapi/v1/exchangeInfo through BinancePublicMarketData.exchange_info",
    )
    if not answer.ok:
        return case.not_observed(f"the exchangeInfo read failed: {_class_code(answer)}")
    if answer.summary.get("found") != _TRUE:
        return case.not_observed("the symbol is not listed in the exchangeInfo answer")
    for name, suffix, key in _EXCHANGE_INFO_FILTERS:
        case.detail(f"filter_{name}_{suffix}", answer.summary.get(key, "not listed"))
    case.detail("symbol_status", answer.summary.get("status", "not listed"))
    case.detail(
        "price_filter_min_price_max_price",
        "NOT_OBSERVED: the project port reads the tick size of PRICE_FILTER only",
    )
    snapshot = case.context.recorder.market.get("symbol_filters")
    if isinstance(snapshot, ProbeObservation) and snapshot.ok:
        differing = [
            key
            for key in _SNAPSHOT_COMPARED
            if snapshot.summary.get(key) != answer.summary.get(key)
        ]
        case.detail("matches_run_start_snapshot", _flag_text(not differing))
        case.detail("snapshot_differences", ",".join(differing) or "none")
    else:
        case.detail("matches_run_start_snapshot", "unknown")
        case.detail("snapshot_differences", "unknown: no run-start snapshot")
    return case.observed()


async def _gtd_min_lifetime_boundary(case: _WriteCase) -> CaseResult:
    market = await case.market()
    price = market.far_below(case.fraction)
    case.check_bounds([(case.quantity, price)])
    case.detail("far_price", format(price, "f"))
    sent_any = False
    for margin in GTD_BOUNDARY_MARGINS_SECONDS:
        prefix = f"plus_{margin}s"
        local_before = _checked_now(case.rig)
        clock = await case.ask(f"{prefix}_server_time", case.port.server_time())
        local_after = _checked_now(case.rig)
        server_ms = _positive_int_text(clock.summary, "server_time_ms") if clock.ok else None
        if server_ms is None:
            case.detail(
                f"{prefix}_skipped",
                "NOT_OBSERVED: the server time was unreadable: nothing was sent for this point",
            )
            continue
        good_till_date_ms = server_ms + margin * 1000
        local_ms = _ms_of(local_after)
        case.detail(f"{prefix}_margin_seconds", str(margin))
        case.detail(f"{prefix}_server_time_ms", str(server_ms))
        case.detail(f"{prefix}_local_clock_before_utc", local_before.isoformat())
        case.detail(f"{prefix}_local_clock_after_utc", local_after.isoformat())
        case.detail(f"{prefix}_local_minus_server_ms", str(local_ms - server_ms))
        case.detail(f"{prefix}_good_till_date_ms", str(good_till_date_ms))
        case.detail(f"{prefix}_good_till_date_minus_server_ms", str(good_till_date_ms - server_ms))
        case.detail(f"{prefix}_good_till_date_minus_local_ms", str(good_till_date_ms - local_ms))
        client_id = case.client_id(f"gtd{margin}")
        sent_any = True
        placed = await case.gtd_limit(
            f"{prefix}_gtd_limit",
            client_id=client_id,
            price=price,
            good_till_date_ms=good_till_date_ms,
        )
        case.detail(f"{prefix}_accepted", _flag_text(placed.ok))
        if placed.ok:
            echoed = placed.summary.get("good_till_date")
            if echoed:
                case.detail(f"{prefix}_good_till_date_echoed", echoed)
            canceled = await case.cancel(f"{prefix}_cancel", client_id)
            case.detail(f"{prefix}_cancel_accepted", _flag_text(canceled.ok))
            continue
        error = placed.error
        case.detail(f"{prefix}_error_code", _code_text(placed))
        if error is not None:
            case.detail(f"{prefix}_error_class", error.http_class)
            case.detail(f"{prefix}_error_category", error.category)
            case.detail(f"{prefix}_error_message", error.message)
    if not sent_any:
        return case.not_observed("the server time was unreadable: no order was sent")
    return case.observed()


def _is_partial(summary: Mapping[str, str]) -> bool:
    """PARTIALLY_FILLED, or an executed quantity strictly between zero and the original."""
    if summary.get("status") == ORDER_STATUS_PARTIALLY_FILLED:
        return True
    executed = _decimal_or_none(summary.get("executed_qty", ""))
    original = _decimal_or_none(summary.get("orig_qty", ""))
    return executed is not None and original is not None and 0 < executed < original


def _record_numbers(case: _WriteCase, prefix: str, answer: ProbeObservation) -> None:
    """The raw status and quantities of one order answer (text as the exchange gave it)."""
    for key in ("status", "orig_qty", "executed_qty", "avg_price"):
        case.detail(f"{prefix}{key}", answer.summary.get(key, "NOT_OBSERVED: not answered"))


async def _partial_fill_attempt(case: _WriteCase) -> CaseResult:
    market = await case.market()
    cap = case.limits.max_notional_quote
    if cap is None:
        raise _StopCase("max_notional_quote is not approved in the probe limits file")
    # As far as the owner bound allows: the highest tick-grid price under the notional cap,
    # but never past the price a marketable entry already uses (halfway to the PERCENT_PRICE
    # edge, the first live probe having met -4016 at the edge).
    cap_price = market.floor(cap / case.quantity)
    limit_price = min(market.marketable_buy(), cap_price)
    case.check_bounds([(case.quantity, limit_price)])
    case.detail("approved_quantity", format(case.quantity, "f"))
    case.detail("notional_cap", format(cap, "f"))
    case.detail("cap_price", format(cap_price, "f"))
    case.detail("band_price", format(market.marketable_buy(), "f"))
    case.detail("limit_price", format(limit_price, "f"))
    book = await case.ask("order_book_read", case.port.order_book(symbol=case.symbol))
    asks = _book_side(book, "ask")
    bids = _book_side(book, "bid")
    expects = "unknown"
    if asks:
        within = sum((qty for price, qty in asks if price <= limit_price), Decimal(0))
        case.detail("best_ask", format(asks[0][0], "f"))
        case.detail("ask_levels_read", str(len(asks)))
        case.detail("ask_quantity_within_limit_price", format(within, "f"))
        if within >= case.quantity:
            expects = _FALSE
        elif len(asks) < ORDER_BOOK_LIMIT:
            expects = _TRUE
    if bids:
        case.detail("best_bid", format(bids[0][0], "f"))
    case.detail("depth_expects_partial", expects)
    if asks and asks[0][0] > limit_price:
        case.detail(
            "not_sent",
            f"the limit price {format(limit_price, 'f')} does not reach the best ask "
            f"{format(asks[0][0], 'f')}: the owner notional cap stops the order short of the book",
        )
        return case.not_observed(REASON_NO_PARTIAL_PRODUCED)
    client_id = case.client_id("pfa")
    case.detail("client_order_id", client_id)
    placed = await case.limit("limit_order", client_id=client_id, side=SIDE_BUY, price=limit_price)
    case.detail("placement_accepted", _flag_text(placed.ok))
    if not placed.ok:
        return case.not_observed(REASON_NO_PARTIAL_PRODUCED)
    _record_numbers(case, "", placed)
    case.detail("placement_status", placed.summary.get("status", "NOT_OBSERVED: not answered"))
    seen_in: list[str] = []
    rest_partial = _is_partial(placed.summary)
    queried = await case.ask(
        "order_query", case.port.query_order(symbol=case.symbol, client_order_id=client_id)
    )
    if queried.ok:
        case.detail("query_status", queried.summary.get("status", "unreadable"))
        case.detail("query_executed_qty", queried.summary.get("executed_qty", "not answered"))
        rest_partial = rest_partial or _is_partial(queried.summary)
    if client_id in case.open_orders and not (
        queried.ok and queried.summary.get("status") == ORDER_STATUS_FILLED
    ):
        await case.cancel("remainder_cancel", client_id)
        final = await case.ask(
            "final_query", case.port.query_order(symbol=case.symbol, client_order_id=client_id)
        )
        if final.ok:
            case.detail("final_status", final.summary.get("status", "unreadable"))
            case.detail("final_executed_qty", final.summary.get("executed_qty", "not answered"))
            rest_partial = rest_partial or _is_partial(final.summary)
    frame_partial = any(
        frame.get("order_status") == ORDER_STATUS_PARTIALLY_FILLED
        for frame in _order_frames(case.frames(), client_id)
    )
    if rest_partial:
        seen_in.append("rest")
    if frame_partial:
        seen_in.append("frames")
    case.detail("partial_fill_seen", _flag_text(bool(seen_in)))
    if seen_in:
        case.detail("partial_seen_in", ",".join(seen_in))
    try:
        held = await case.held_quantity("position_after")
    except _StopCase as stop:
        held = Decimal(0)
        case.detail("flatten", f"skipped: {stop.reason}")
    if held > 0:
        case.detail("flatten_quantity", format(held, "f"))
        await case.market_close("flatten", held, limit_price, "pff")
    if seen_in:
        return case.observed()
    return case.not_observed(REASON_NO_PARTIAL_PRODUCED)


async def _entry_cancel_fill_race(case: _WriteCase) -> CaseResult:
    repeats = case.race_repeats
    case.detail("race_repeats", str(repeats))
    case.detail("note", RACE_NOTE)
    case.detail("touch_price_side", "best ask (the price a BUY LIMIT executes against)")
    market = await case.market()
    lower = market.far_below(case.fraction)
    upper = market.far_above(case.fraction)
    tally = {"canceled_in_time": 0, "cancel_rejected": 0, "filled": 0}
    completed = 0
    for number in range(1, repeats + 1):
        prefix = f"r{number}"
        book = await case.ask(f"{prefix}_order_book", case.port.order_book(symbol=case.symbol))
        asks = _book_side(book, "ask")
        if not asks:
            case.detail("stopped", f"{prefix}: the best ask is unreadable")
            break
        touch = asks[0][0]
        if not lower <= touch <= upper:
            case.detail(
                "stopped",
                f"{prefix}: the best ask {format(touch, 'f')} is outside the far_price_fraction "
                f"band {format(lower, 'f')} to {format(upper, 'f')}",
            )
            break
        client_id = case.client_id(f"rc{number}")
        placed = await case.limit(
            f"{prefix}_place", client_id=client_id, side=SIDE_BUY, price=touch
        )
        if not placed.ok:
            case.detail("stopped", f"{prefix}: placement rejected {_class_code(placed)}")
            break
        place_status = placed.summary.get("status", "")
        case.detail(f"{prefix}_touch_price", format(touch, "f"))
        case.detail(f"{prefix}_place_status", place_status or "unreadable")
        case.detail(
            f"{prefix}_place_executed_qty", placed.summary.get("executed_qty", "not answered")
        )
        canceled = await case.cancel(f"{prefix}_cancel", client_id)
        case.detail(f"{prefix}_cancel_code", _code_text(canceled))
        final = await case.ask(
            f"{prefix}_final_query",
            case.port.query_order(symbol=case.symbol, client_order_id=client_id),
        )
        final_status = final.summary.get("status", "") if final.ok else ""
        case.detail(f"{prefix}_final_status", final_status or "unreadable")
        if place_status in _RACE_FILLED_STATUSES or final_status in _RACE_FILLED_STATUSES:
            filled = _TRUE
        elif place_status and final_status:
            filled = _FALSE
        else:
            filled = "unknown"
        case.detail(f"{prefix}_filled", filled)
        cancel_text = (
            "canceled in time" if canceled.ok else f"cancel rejected {_code_text(canceled)}"
        )
        case.detail(f"{prefix}_outcome", f"{cancel_text}; final {final_status or 'unreadable'}")
        tally["canceled_in_time" if canceled.ok else "cancel_rejected"] += 1
        completed += 1
        if filled == _TRUE:
            tally["filled"] += 1
            try:
                held = await case.held_quantity(f"{prefix}_position")
            except _StopCase as stop:
                case.detail("stopped", f"{prefix}: cannot flatten: {stop.reason}")
                break
            if held > 0:
                await case.market_close(f"{prefix}_flatten", held, touch, f"rf{number}")
    case.detail("repeats_completed", str(completed))
    for name, count in tally.items():
        case.detail(f"outcome_{name}", str(count))
    if completed == 0:
        stopped = case.details.get("stopped", "no repeat ran")
        return case.not_observed(f"no place-and-cancel pair was completed: {stopped}")
    return case.observed()


def _frame_texts(frames: Sequence[Mapping[str, str]], *fields: str) -> str:
    """``a/b`` per frame (the named fields, in order), ``;``-joined, or ``none``."""
    return ";".join("/".join(frame.get(name, "") for name in fields) for frame in frames) or "none"


async def _stream_loss_during_case(case: _WriteCase) -> CaseResult:
    if not case.stream_started():
        return case.not_observed(REASON_NO_STREAM)
    market = await case.market()
    below = market.far_below(case.fraction)
    case.check_bounds([(case.quantity, market.marketable_buy()), (None, below)])
    gap_marker = case.port.marker()
    # The existing stream-gap mechanism (stream_gap_during_case): close the private connection
    # first, so nothing is placed when the port cannot drop it.
    dropped = await case.port.drop_stream_transport()
    case.detail("transport_dropped", _flag_text(dropped))
    if not dropped:
        return case.not_observed(REASON_NO_STREAM)
    case.detail(
        "stream_states_at_entry_send", ",".join(case.port.stream_states_since(gap_marker)) or "none"
    )
    placed, status = await case.open_long(market, "slg")
    entry_id = case.details.get("entry_client_id", "")
    if not placed.ok:
        return case.not_observed(f"entry rejected: {_class_code(placed)}")
    if status != ORDER_STATUS_FILLED:
        if entry_id in case.open_orders:
            await case.cancel("entry_cancel", entry_id)
        return case.not_observed(f"the entry did not fill: status {status or 'unreadable'}")
    case.detail("rest_entry_status_during_gap", status)
    stop_id = case.client_id("slx")
    case.detail("client_algo_id", stop_id)
    stop = await case.conditional(
        "stop",
        client_id=stop_id,
        side=SIDE_SELL,
        order_type=ORDER_TYPE_STOP_MARKET,
        trigger=below,
        quantity=None,
        close_position=True,
    )
    case.detail("stop_accepted", _flag_text(stop.ok))
    rest_stop = "not placed"
    if stop.ok:
        rest_stop = await case.algo_status("rest_stop_query", stop_id) or "unreadable"
        case.detail("rest_stop_status_during_gap", rest_stop)
    case.detail(
        "stream_states_when_stop_answered",
        ",".join(case.port.stream_states_since(gap_marker)) or "none",
    )

    async def recovered() -> bool:
        return StreamState.LIVE.value in case.port.stream_states_since(gap_marker)

    back = await wait_up_to(case.rig, recovered, case.case_timeout_seconds)
    states = case.port.stream_states_since(gap_marker)
    case.detail("stream_states_after_drop", ",".join(states) or "none")
    case.detail("stream_recovered_live", _flag_text(back))
    after = case.port.frames_since(gap_marker)
    case.detail("frames_before_drop_count", str(len(case.frames()) - len(after)))
    entry_frames = _order_frames(after, entry_id)
    stop_frames = _algo_frames(after, stop_id)
    entry_text = _frame_texts(entry_frames, "order_status", "execution_type")
    stop_text = _frame_texts(stop_frames, "algo_status")
    case.detail("frames_after_drop_entry", entry_text)
    case.detail("frames_after_drop_stop", stop_text)
    case.detail(
        "entry_fill_frame_delivered",
        _flag_text(any(f.get("order_status") == ORDER_STATUS_FILLED for f in entry_frames)),
    )
    case.detail("stop_frame_delivered", _flag_text(bool(stop_frames)))
    case.detail("comparison_entry", f"rest={status}; stream_after_drop={entry_text}")
    case.detail("comparison_stop", f"rest={rest_stop}; stream_after_drop={stop_text}")
    if stop.ok:
        await case.cancel_algo("stop_cancel", stop_id)
    await case.observe_state("end")
    if not back:
        return case.not_observed(REASON_STREAM_NOT_RECOVERED)
    return case.observed()


# ----- quick task 261023-sj2: eight more owner opt-in cases ------------------------------ #
#
# Facts only, like the sj0 and sj1 cases: each records what the exchange answered (a rejection
# code IS an answer), never retries a request and ends with a clean account (the runner cleanup
# cancels and flattens after the case). Seven of them obey the owner caps (the approved
# quantity and `max_notional_quote`, through `check_bounds`). `insufficient_margin_order` is the
# one exception, with its own owner quantity and its own bound (`margin_order_refusal`).

REASON_NOT_FLAT_CASE = "the symbol is not flat before the case: {state}; nothing was sent"
REASON_STOP_NO_UPDATE = (
    "the stop was accepted but no ALGO_UPDATE status beyond NEW was seen within "
    "case_timeout_seconds (the acceptance itself is recorded in details)"
)
REASON_STALE_CLOCK_NOT_HONOURED = (
    "the SDK did not ask the stale clock (clock_calls is 0): the request carried the real "
    "timestamp, so no conclusion about the recvWindow can be drawn"
)
REASON_MARGIN_ACCEPTED = (
    "the order was accepted (it rests): the quantity did not exceed the available margin, so "
    "-2019 was not observed; the margin figures before and after are recorded"
)
RACE_NOTE_TRIGGER = (
    "this case is not a deterministic race: each repeat places a closePosition STOP_MARKET near "
    "the live mark and cancels it as soon as the placement answer arrives; whether the exchange "
    "triggers it before the cancel lands is up to its timing, so the outcomes are samples of the "
    "exchange answers, not a proof of their order"
)
_MARGIN_FIGURES: tuple[tuple[str, str], ...] = (
    ("availableBalance", "available_balance"),
    ("totalWalletBalance", "total_wallet_balance"),
    ("totalInitialMargin", "total_initial_margin"),
    ("totalOpenOrderInitialMargin", "total_open_order_initial_margin"),
)


def _record_order_answer(
    case: _WriteCase, answer: ProbeObservation, prefix: str = "order_"
) -> None:
    """The exact answer of one order: accepted, its fields, or HTTP class, code, category, text."""
    case.detail(f"{prefix}accepted", _flag_text(answer.ok))
    if answer.ok:
        for key in ("status", "orig_qty", "executed_qty", "avg_price"):
            if key in answer.summary:
                case.detail(f"{prefix}{key}", answer.summary[key])
        return
    error = answer.error
    case.detail(f"{prefix}error_code", _code_text(answer))
    if error is not None:
        case.detail(f"{prefix}error_class", error.http_class)
        case.detail(f"{prefix}error_category", error.category)
        case.detail(f"{prefix}error_message", error.message)


def _half_quantity(case: _WriteCase, market: _Market) -> tuple[Decimal | None, str | None]:
    """About half of the approved quantity, floored to the step; (None, reason) if unusable."""
    steps = (case.quantity / 2 / market.step).to_integral_value(rounding=ROUND_FLOOR)
    half = steps * market.step
    case.detail("half_quantity", format(half, "f"))
    if half <= 0 or half < market.min_quantity:
        return None, (
            f"half of the approved quantity ({format(half, 'f')} after flooring to the step) is "
            f"below the exchange minimum quantity {format(market.min_quantity, 'f')}"
        )
    return half, None


async def _require_flat(case: _WriteCase, prefix: str) -> str | None:
    """Read open orders, open algo orders and the position; None if flat, else the state text."""
    summary, answers = await _read_state(case.port, case.symbol)
    case.observations.extend(answers.values())
    state = (
        f"open_orders={summary['open_orders']} open_algo_orders={summary['open_algo_orders']} "
        f"positions={len(summary['positions'])} readable={_flag_text(summary['readable'] is True)}"
    )
    case.detail(f"{prefix}_state", state)
    return None if _is_flat(summary) else state


async def _reduce_only_market_on_flat(case: _WriteCase) -> CaseResult:
    market = await case.market()
    upper = market.marketable_buy()
    case.check_bounds([(case.quantity, upper)])
    state = await _require_flat(case, "precheck")
    if state is not None:
        return case.not_observed(REASON_NOT_FLAT_CASE.format(state=state))
    answer, client_id = await case.market_close("reduce_only_market", case.quantity, upper, "rof")
    case.detail("client_order_id", client_id)
    _record_order_answer(case, answer)
    held = await case.held_quantity("position_read_after")
    case.detail("position_after", format(held, "f"))
    flipped = held != 0
    case.detail("flipped", _flag_text(flipped))
    if flipped:
        case.notes.append("a position appeared after the reduce-only order: it was flattened")
        await case.flatten("flatten_after_flip", held, upper, "rff")
    return case.observed()


async def _reduce_only_market_larger_than_position(case: _WriteCase) -> CaseResult:
    market = await case.market()
    upper = market.marketable_buy()
    half, reason = _half_quantity(case, market)
    if half is None:
        return case.not_observed(reason or "no usable half quantity")
    case.check_bounds([(half, upper), (case.quantity, upper)])
    refusal, _ = await _open_position(case, market, "roe", quantity=half)
    if refusal is not None:
        return refusal
    held_before = await case.held_quantity("position_read_before")
    case.detail("held_before", format(held_before, "f"))
    if held_before <= 0:
        return case.not_observed(REASON_NO_POSITION_HELD)
    case.detail("oversize_quantity", format(case.quantity, "f"))
    answer, client_id = await case.market_close("oversize_reduce_only", case.quantity, upper, "rox")
    case.detail("client_order_id", client_id)
    _record_order_answer(case, answer)
    if answer.ok:

        async def changed() -> bool:
            return await case.held_quantity("position_wait_read") != held_before

        await wait_up_to(case.rig, changed, case.case_timeout_seconds)
        final = await case.ask(
            "oversize_final_query",
            case.port.query_order(symbol=case.symbol, client_order_id=client_id),
        )
        if final.ok:
            for key in ("status", "executed_qty"):
                case.detail(f"final_{key}", final.summary.get(key, "not answered"))
    after = await case.held_quantity("position_read_after")
    case.detail("position_after", format(after, "f"))
    if not answer.ok:
        outcome = "rejected"
    elif after < 0:
        outcome = "flipped"
    elif after == 0:
        outcome = "clipped_to_position"
    elif after < held_before:
        outcome = "partly_reduced"
    else:
        outcome = "unchanged"
    case.detail("outcome", outcome)
    if after != 0:
        await case.flatten("remainder_flatten", after, upper, "rof")
    return case.observed()


async def _non_reduce_only_below_min_notional(case: _WriteCase) -> CaseResult:
    market = await case.market()
    min_notional = market.min_notional
    if min_notional is None:
        return case.not_observed("the MIN_NOTIONAL filter is not listed for the symbol")
    price = market.far_below(case.fraction)
    case.detail("min_notional_used", format(min_notional, "f"))
    case.detail("far_price", format(price, "f"))
    # The largest quantity on the step grid whose notional at the far price is strictly below the
    # exchange minimum, never above the approved quantity (the tool never raises a quantity).
    below_steps = (min_notional / price / market.step).to_integral_value(rounding=ROUND_CEILING) - 1
    approved_steps = (case.quantity / market.step).to_integral_value(rounding=ROUND_FLOOR)
    quantity = min(below_steps, approved_steps) * market.step
    case.detail("sent_quantity", format(quantity, "f"))
    if quantity <= 0 or quantity < market.min_quantity:
        return case.not_observed(
            f"a quantity below the minimum notional ({format(quantity, 'f')} on the step grid) "
            f"is below the exchange minimum quantity {format(market.min_quantity, 'f')}"
        )
    notional = quantity * price
    case.detail("computed_notional", format(notional, "f"))
    if notional >= min_notional:
        return case.not_observed("the approved quantity gives a notional at or above the minimum")
    refusal = order_bound_refusal(case.limits, quantity=quantity, price=price, step=market.step)
    if refusal is not None:
        return case.not_observed(f"order bound: {refusal} (nothing was sent)")
    client_id = case.client_id("mnl")
    case.detail("client_order_id", client_id)
    placed = await case.limit(
        "below_min_notional_limit",
        client_id=client_id,
        side=SIDE_BUY,
        price=price,
        quantity=quantity,
    )
    _record_order_answer(case, placed)
    if placed.ok:
        canceled = await case.cancel("below_min_notional_cancel", client_id)
        case.detail("cancel_accepted", _flag_text(canceled.ok))
    return case.observed()


def _leverage_of(answer: ProbeObservation) -> Decimal | None:
    """The first ``leverage`` value of a flattened symbol-configuration answer."""
    for key, value in answer.summary.items():
        if key.split(".")[-1] == "leverage":
            parsed = _decimal_or_none(value)
            return parsed if parsed is not None and parsed > 0 else None
    return None


def _record_margin_figures(
    case: _WriteCase, answer: ProbeObservation, suffix: str
) -> Decimal | None:
    """The account margin figures of one ``account_information`` read; returns the available."""
    available: Decimal | None = None
    for wire, name in _MARGIN_FIGURES:
        text = answer.summary.get(wire) if answer.ok else None
        case.detail(f"{name}_{suffix}", text if text is not None else "NOT_OBSERVED: not answered")
        if wire == "availableBalance" and text is not None:
            available = _decimal_or_none(text)
    return available


async def _insufficient_margin_order(case: _WriteCase) -> CaseResult:
    # The -2019 case. It does NOT use the max_notional_quote check or the approved quantity of
    # the other cases (check_bounds / order_bound_refusal): the order has to be larger than the
    # margin allows. Its own bound is `margin_order_refusal` (inside `margin_limit`): the owner's
    # insufficient_margin_quantity exactly, on the step grid, one far LIMIT BUY at or below the
    # far price of the owner band (below the mark: it can only rest). Kept here: the symbol,
    # the flat precheck, the price band and the runner cleanup (which flattens anything filled).
    quantity = case.limits.insufficient_margin_quantity
    if quantity is None:
        raise ValueError("insufficient_margin_quantity is not set in the probe limits file")
    market = await case.market()
    state = await _require_flat(case, "precheck")
    if state is not None:
        return case.not_observed(REASON_NOT_FLAT_CASE.format(state=state))
    price = market.far_below(case.fraction)
    case.detail("far_price", format(price, "f"))
    case.detail("insufficient_margin_quantity", format(quantity, "f"))
    if price >= market.mark:
        return case.not_observed("the far price is not below the mark: the order could fill")
    if quantity < market.min_quantity:
        return case.not_observed(
            "the quantity is below the exchange minimum quantity "
            f"{format(market.min_quantity, 'f')}: the answer would be a lot-size error, not -2019"
        )
    maximum = _positive_decimal(market.filters, "max_quantity")
    if maximum is not None and quantity > maximum:
        return case.not_observed(
            f"the quantity is above the exchange maximum quantity {format(maximum, 'f')}: "
            "the answer would be a lot-size error, not -2019"
        )
    if quantity % market.step != 0:
        return case.not_observed(
            f"the quantity is not on the step grid {format(market.step, 'f')}: nothing was sent"
        )
    before = await case.ask("account_information_before", case.port.account_information())
    configuration = await case.ask(
        "symbol_config_read", case.port.symbol_config(symbol=case.symbol)
    )
    available_before = _record_margin_figures(case, before, "before")
    leverage = _leverage_of(configuration) if configuration.ok else None
    case.detail("leverage", format(leverage, "f") if leverage is not None else "NOT_OBSERVED")
    notional = quantity * price
    case.detail("implied_notional", format(notional, "f"))
    if leverage is not None:
        margin = notional / leverage
        case.detail("implied_initial_margin", format(margin, "f"))
        if available_before is not None:
            case.detail("implied_margin_exceeds_available", _flag_text(margin > available_before))
    client_id = case.client_id("ism")
    case.detail("client_order_id", client_id)
    placed = await case.margin_limit(
        "margin_limit",
        client_id=client_id,
        price=price,
        ceiling_price=market.far_below(case.fraction),
    )
    _record_order_answer(case, placed)
    if placed.ok:
        canceled = await case.cancel("margin_cancel", client_id)
        case.detail("cancel_accepted", _flag_text(canceled.ok))
        final = await case.ask(
            "margin_final_query",
            case.port.query_order(symbol=case.symbol, client_order_id=client_id),
        )
        if final.ok:
            case.detail("final_status", final.summary.get("status", "unreadable"))
    after = await case.ask("account_information_after", case.port.account_information())
    _record_margin_figures(case, after, "after")
    held = await case.held_quantity("position_read_after")
    case.detail("position_after", format(held, "f"))
    if held != 0:
        case.notes.append(
            "a position exists after the margin order (it should not fill): the runner cleanup "
            "flattens it (no owner cap applies to this quantity)"
        )
    if placed.ok:
        return case.not_observed(REASON_MARGIN_ACCEPTED)
    return case.observed()


async def _stop_rejected_after_acceptance(case: _WriteCase) -> CaseResult:
    market = await case.market()
    upper = market.marketable_buy()
    half, reason = _half_quantity(case, market)
    if half is None:
        return case.not_observed(reason or "no usable half quantity")
    case.check_bounds([(half, upper), (case.quantity, upper)])
    refusal, _ = await _open_position(case, market, "sre", quantity=half)
    if refusal is not None:
        return refusal
    held = await case.held_quantity("position_read_before")
    case.detail("held_before", format(held, "f"))
    if held <= 0:
        return case.not_observed(REASON_NO_POSITION_HELD)
    live = await case.live_mark()
    below, _ = _near_triggers(live, market.tick, case.near_trigger_fraction)
    case.detail("stop_trigger_price", format(below, "f"))
    case.detail("stop_quantity", format(case.quantity, "f"))
    leg_id = case.client_id("srs")
    case.detail("client_algo_id", leg_id)
    # reduce-only, NOT closePosition, quantity larger than the position: the approved quantity
    # against a position of about half of it (never above the approved quantity).
    placed = await case.conditional(
        "stop_leg",
        client_id=leg_id,
        side=SIDE_SELL,
        order_type=ORDER_TYPE_STOP_MARKET,
        trigger=below,
        quantity=case.quantity,
        reduce_only=True,
    )
    case.detail("placement_accepted", _flag_text(placed.ok))
    if not placed.ok:
        _record_order_answer(case, placed, "stop_leg_")
        return case.observed()  # the rejection code is the answer
    leg = _Leg("stop", leg_id)

    async def ended() -> bool:
        leg.rest.append(await case.algo_status("stop_wait_query", leg_id))
        return _ended(_leg_statuses(case, leg))

    await wait_up_to(case.rig, ended, case.case_timeout_seconds)
    _record_leg_lifecycle(case, leg)
    _record_algo_update_sequence(case, leg)
    statuses = _leg_statuses(case, leg)
    await case.observe_state("after")
    if not _ended(statuses):
        await case.cancel_algo("stop_cancel", leg_id)
    if _progressed(statuses):
        return case.observed()
    return case.not_observed(REASON_STOP_NO_UPDATE)


async def _trigger_cancel_race(case: _WriteCase) -> CaseResult:
    repeats = case.race_repeats
    case.detail("race_repeats", str(repeats))
    case.detail("note", RACE_NOTE_TRIGGER)
    market = await case.market()
    upper = market.marketable_buy()
    case.check_bounds([(case.quantity, upper)])
    tally = {"triggered": 0, "not_triggered": 0, "cancel_rejected": 0, "placement_rejected": 0}
    completed = 0
    for number in range(1, repeats + 1):
        prefix = f"r{number}"
        held = await case.held_quantity(f"{prefix}_position_read_before")
        if held <= 0:
            refusal, _ = await _open_position(case, market, f"tr{number}")
            if refusal is not None:
                case.detail("stopped", f"{prefix}: no position could be opened: {refusal.reason}")
                break
        live = await case.live_mark()
        below, _ = _near_triggers(live, market.tick, case.near_trigger_fraction)
        case.check_bounds([(None, below)])
        case.detail(f"{prefix}_stop_trigger_price", format(below, "f"))
        leg_id = case.client_id(f"tc{number}")
        placed = await case.conditional(
            f"{prefix}_stop",
            client_id=leg_id,
            side=SIDE_SELL,
            order_type=ORDER_TYPE_STOP_MARKET,
            trigger=below,
            quantity=None,
            close_position=True,
        )
        case.detail(f"{prefix}_placement_accepted", _flag_text(placed.ok))
        if not placed.ok:
            _record_order_answer(case, placed, f"{prefix}_placement_")
            tally["placement_rejected"] += 1
            continue
        canceled = await case.cancel_algo(f"{prefix}_cancel", leg_id)
        case.detail(f"{prefix}_cancel_code", _code_text(canceled))
        final_status = await case.algo_status(f"{prefix}_final_algo_query", leg_id)
        case.detail(f"{prefix}_final_algo_status", final_status or "unreadable")
        streamed = [f.get("algo_status", "") for f in _algo_frames(case.frames(), leg_id)]
        after = await case.held_quantity(f"{prefix}_position_read_after")
        closed = after <= 0
        triggered = _triggered([final_status, *streamed]) or closed
        case.detail(f"{prefix}_position_closed", _flag_text(closed))
        case.detail(f"{prefix}_triggered", _flag_text(triggered))
        outcome = "canceled in time" if canceled.ok else f"cancel rejected {_code_text(canceled)}"
        case.detail(
            f"{prefix}_outcome",
            f"{outcome}; final {final_status or 'unreadable'}; "
            f"position {'closed' if closed else 'open'}",
        )
        tally["triggered" if triggered else "not_triggered"] += 1
        if not canceled.ok:
            tally["cancel_rejected"] += 1
        completed += 1
    case.detail("repeats_completed", str(completed))
    for name, count in tally.items():
        case.detail(f"outcome_{name}", str(count))
    if completed == 0:
        stopped = case.details.get("stopped", "every placement was rejected or none was tried")
        return case.not_observed(f"no stop was placed and cancelled: {stopped}")
    return case.observed()


async def _timestamp_outside_recv_window(case: _WriteCase) -> CaseResult:
    window = case.context.config.limits.signed.recv_window_ms
    local_before = _checked_now(case.rig)
    clock = await case.ask("server_time_read", case.port.server_time())
    local_after = _checked_now(case.rig)
    server_ms = _positive_int_text(clock.summary, "server_time_ms") if clock.ok else None
    if server_ms is None:
        return case.not_observed("the server time was unreadable: no stale read was sent")
    local_ms = _ms_of(local_after)
    offset = local_ms - server_ms
    # The request is stale relative to the EXCHANGE clock: twice the window behind the server
    # time, whatever the local clock reads. The SDK stamps the real local clock, so the offset
    # between the two clocks is added to what is taken away.
    behind = 2 * window + offset
    case.detail("recv_window_ms", str(window))
    case.detail(
        "recv_window_note", "the ratified signed_calls.recv_window_ms of the Binance limits file"
    )
    case.detail("server_time_ms", str(server_ms))
    case.detail("local_clock_before_utc", local_before.isoformat())
    case.detail("local_clock_after_utc", local_after.isoformat())
    case.detail("local_minus_server_ms", str(offset))
    case.detail("timestamp_behind_server_ms_target", str(2 * window))
    case.detail("timestamp_behind_local_ms", str(behind))
    if behind <= 0:
        return case.not_observed(
            "the clock offset between the tool and the exchange swallows the stale offset: "
            "no stale read was sent"
        )
    answer = await case.ask(
        "stale_signed_read",
        case.port.stale_timestamp_read(
            symbol=case.symbol, recv_window_ms=window, timestamp_behind_ms=behind
        ),
    )
    for key in ("clock_calls", "timestamp_sent_ms", "real_clock_ms"):
        if key in answer.summary:
            case.detail(key, answer.summary[key])
    if answer.summary.get("clock_calls", "0") == "0":
        return case.not_observed(REASON_STALE_CLOCK_NOT_HONOURED)
    sent_ms = _positive_int_text(answer.summary, "timestamp_sent_ms")
    if sent_ms is not None:
        case.detail("timestamp_sent_minus_server_read_ms", str(sent_ms - server_ms))
    _record_order_answer(case, answer, "")
    return case.observed()


async def _income_history_read(case: _WriteCase) -> CaseResult:
    started = case.context.recorder.started_utc
    if started is None:
        raise ValueError("the run has not started")
    local_before = _checked_now(case.rig)
    clock = await case.ask("server_time_read", case.port.server_time())
    local_after = _checked_now(case.rig)
    server_ms = _positive_int_text(clock.summary, "server_time_ms") if clock.ok else None
    start_ms = _ms_of(started)
    if server_ms is None:
        case.detail("window_note", "server time unreadable: the local run start is used")
    else:
        offset = _ms_of(local_after) - server_ms
        start_ms -= offset  # the run start on the exchange clock
        case.detail("local_clock_before_utc", local_before.isoformat())
        case.detail("local_clock_after_utc", local_after.isoformat())
        case.detail("local_minus_server_ms", str(offset))
        case.detail("window_note", "the run start converted to the exchange clock")
    case.detail("window_start_ms", str(start_ms))
    if start_ms <= 0:
        return case.not_observed("the run window start is not a positive time")
    answer = await case.ask(
        "income_history_read",
        case.port.income_history(symbol=case.symbol, start_time_ms=start_ms),
    )
    if not answer.ok:
        return case.not_observed(f"the income history read failed: {_class_code(answer)}")
    count = _count(answer) or 0
    case.detail("row_count", str(count))
    if count == 0:
        return case.not_observed("no income row in the run window (nothing was charged or paid)")
    fields = sorted(
        {re.sub(r"^row_\d+_", "", key) for key in answer.summary if key.startswith("row_")}
    )
    case.detail("row_fields", ",".join(fields))
    rows = _income_rows(answer)
    types = sorted({row["income_type"] or "UNKNOWN" for row in rows})
    case.detail("row_types", ",".join(types))
    for income_type in types:
        selected = [row for row in rows if (row["income_type"] or "UNKNOWN") == income_type]
        case.detail(f"row_count_{income_type}", str(len(selected)))
        for asset in sorted({row["asset"] or "UNKNOWN" for row in selected}):
            total = _decimal_sum(
                [row["income"] for row in selected if (row["asset"] or "UNKNOWN") == asset]
            )
            case.detail(
                f"derived_sum_{income_type}_{asset}",
                format(total, "f")
                if total is not None
                else "NOT_OBSERVED: an income was unreadable",
            )
    times = [int(row["time_ms"]) for row in rows if row["time_ms"].isdigit()]
    if times:
        case.detail("first_row_time_ms", str(min(times)))
        case.detail("last_row_time_ms", str(max(times)))
    return case.observed()


async def case_reduce_only_market_on_flat(context: CaseContext) -> CaseResult:
    """Owner opt-in (A4): ONE reduce-only MARKET order on a flat account."""
    return await run_write_case(
        context,
        _reduce_only_market_on_flat,
        case_id="reduce_only_market_on_flat",
        reduce_only=True,
    )


async def case_reduce_only_market_larger_than_position(context: CaseContext) -> CaseResult:
    """Owner opt-in (A8): a reduce-only MARKET of the full quantity against half a position."""
    return await run_write_case(
        context,
        _reduce_only_market_larger_than_position,
        case_id="reduce_only_market_larger_than_position",
        reduce_only=True,
    )


async def case_non_reduce_only_below_min_notional(context: CaseContext) -> CaseResult:
    """Owner opt-in (-4164): a far LIMIT BUY whose notional is below the exchange minimum."""
    return await run_write_case(
        context,
        _non_reduce_only_below_min_notional,
        case_id="non_reduce_only_below_min_notional",
        reduce_only=True,
    )


async def case_insufficient_margin_order(context: CaseContext) -> CaseResult:
    """Owner opt-in (-2019): ONE far LIMIT BUY of the owner's own insufficient_margin_quantity."""
    return await run_write_case(
        context,
        _insufficient_margin_order,
        case_id="insufficient_margin_order",
        reduce_only=True,
    )


async def case_stop_rejected_after_acceptance(context: CaseContext) -> CaseResult:
    """Owner opt-in (P5 remainder, ALGO_UPDATE.o.rm): an oversize reduce-only stop, watched."""
    return await run_write_case(
        context,
        _stop_rejected_after_acceptance,
        case_id="stop_rejected_after_acceptance",
        reduce_only=True,
    )


async def case_trigger_cancel_race(context: CaseContext) -> CaseResult:
    """Owner opt-in (P7 trigger part): place and cancel a near stop, `race_repeats` times."""
    return await run_write_case(
        context, _trigger_cancel_race, case_id="trigger_cancel_race", reduce_only=True
    )


async def case_timestamp_outside_recv_window(context: CaseContext) -> CaseResult:
    """Owner opt-in (-1021): ONE read-only signed GET with a timestamp 2x the window behind."""
    return await run_write_case(
        context,
        _timestamp_outside_recv_window,
        case_id="timestamp_outside_recv_window",
        reduce_only=False,
    )


async def case_income_history_read(context: CaseContext) -> CaseResult:
    """Owner opt-in (Phase 21): the income history of the run window, read-only."""
    return await run_write_case(
        context, _income_history_read, case_id="income_history_read", reduce_only=False
    )


async def case_exchange_info_read_for_close(context: CaseContext) -> CaseResult:
    """Owner opt-in (A10, Q3): the live exchangeInfo filters and the read time; no order."""
    return await run_write_case(
        context,
        _exchange_info_read_for_close,
        case_id="exchange_info_read_for_close",
        reduce_only=False,
    )


async def case_gtd_min_lifetime_boundary(context: CaseContext) -> CaseResult:
    """Owner opt-in (A1): GTD entries at server time + 599 s and + 601 s."""
    return await run_write_case(
        context,
        _gtd_min_lifetime_boundary,
        case_id="gtd_min_lifetime_boundary",
        reduce_only=True,
    )


async def case_partial_fill_attempt(context: CaseContext) -> CaseResult:
    """Owner opt-in (P3, A5): one best-effort limit order priced to cross; may stay NOT_OBSERVED."""
    return await run_write_case(
        context, _partial_fill_attempt, case_id="partial_fill_attempt", reduce_only=True
    )


async def case_entry_cancel_fill_race(context: CaseContext) -> CaseResult:
    """Owner opt-in (P7): place at the touch and cancel at once, `race_repeats` times."""
    return await run_write_case(
        context, _entry_cancel_fill_race, case_id="entry_cancel_fill_race", reduce_only=True
    )


async def case_stream_loss_during_case(context: CaseContext) -> CaseResult:
    """Owner opt-in (P5): one entry and stop cycle across a dropped user-data stream."""
    return await run_write_case(
        context, _stream_loss_during_case, case_id="stream_loss_during_case", reduce_only=True
    )


async def case_account_read_only_capture(context: CaseContext) -> CaseResult:
    """Owner opt-in (O-05, G2-042, Phase 21 SC1, Phase 22): the six read-only account answers."""
    return await run_write_case(
        context,
        _account_read_only_capture,
        case_id="account_read_only_capture",
        reduce_only=False,
    )


async def case_algo_query_timing_after_new(context: CaseContext) -> CaseResult:
    """Owner opt-in (P5, P11): an algo leg queried at once, after one wait, by both ids."""
    return await run_write_case(
        context,
        _algo_query_timing_after_new,
        case_id="algo_query_timing_after_new",
        reduce_only=True,
    )


async def case_close_position_stop_with_position(context: CaseContext) -> CaseResult:
    """Owner opt-in (P1, A6): closePosition STOP and TP legs with an open position."""
    return await run_write_case(
        context,
        _close_position_stop_with_position,
        case_id="close_position_stop_with_position",
        reduce_only=True,
    )


async def case_stop_would_trigger_after_fill(context: CaseContext) -> CaseResult:
    """Owner opt-in (P8, B5): a closePosition stop on the wrong side after the fill."""
    return await run_write_case(
        context,
        _stop_would_trigger_after_fill,
        case_id="stop_would_trigger_after_fill",
        reduce_only=True,
    )


async def case_stop_query_absent_then_same_id(context: CaseContext) -> CaseResult:
    """Owner opt-in (B2, B3, Q5): a stop queried, placed and re-placed with the same id."""
    return await run_write_case(
        context,
        _stop_query_absent_then_same_id,
        case_id="stop_query_absent_then_same_id",
        reduce_only=True,
    )


async def case_manual_close_with_open_legs(context: CaseContext) -> CaseResult:
    """Owner opt-in (P6, P9, A3, G4-035): a reduce-only MARKET close with two legs open."""
    return await run_write_case(
        context,
        _manual_close_with_open_legs,
        case_id="manual_close_with_open_legs",
        reduce_only=True,
    )


async def case_commission_vs_realized_pnl(context: CaseContext) -> CaseResult:
    """Owner opt-in (G2-042, A9): trades, income rows and derived sums of a round trip."""
    return await run_write_case(
        context,
        _commission_vs_realized_pnl,
        case_id="commission_vs_realized_pnl",
        reduce_only=True,
    )


async def case_triggered_close_position_bracket(context: CaseContext) -> CaseResult:
    """Owner opt-in (P2, P11, A3): a near-mark closePosition bracket and its ALGO_UPDATEs."""
    return await run_write_case(
        context,
        _triggered_close_position_bracket,
        case_id="triggered_close_position_bracket",
        reduce_only=True,
    )


async def case_gtd_entry_expiry_status(context: CaseContext) -> CaseResult:
    """Owner opt-in (A2, P4, part of A1): a far GTD entry and the status it ends with."""
    return await run_write_case(
        context,
        _gtd_entry_expiry_status,
        case_id="gtd_entry_expiry_status",
        reduce_only=True,
    )


async def case_tp1_quantity_from_fill(context: CaseContext) -> CaseResult:
    """Owner opt-in (P10, A7, O-03): a TP1 sized from the fill, triggered near the mark."""
    return await run_write_case(
        context,
        _tp1_quantity_from_fill,
        case_id="tp1_quantity_from_fill",
        reduce_only=True,
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
    "preplaced_stop_reduce_only_flat": case_preplaced_stop_reduce_only_flat,
    "closeposition_stop_flat": case_closeposition_stop_flat,
    "entry_never_fills_protective_orphan": case_entry_never_fills_protective_orphan,
    "full_fill_protective_quantity": case_full_fill_protective_quantity,
    "partial_fill": case_partial_fill,
    "rejected_protective_variants": case_rejected_protective_variants,
    "below_min_notional_reduce_only_leg": case_below_min_notional_reduce_only_leg,
    "triggered_market_exit_lifecycle": case_triggered_market_exit_lifecycle,
    "explicit_time_in_force_variant": case_explicit_time_in_force_variant,
    "stream_gap_during_case": case_stream_gap_during_case,
    "market_lot_size_out_of_range": case_market_lot_size_out_of_range,
    "account_read_only_capture": case_account_read_only_capture,
    "algo_query_timing_after_new": case_algo_query_timing_after_new,
    "close_position_stop_with_position": case_close_position_stop_with_position,
    "stop_would_trigger_after_fill": case_stop_would_trigger_after_fill,
    "stop_query_absent_then_same_id": case_stop_query_absent_then_same_id,
    "manual_close_with_open_legs": case_manual_close_with_open_legs,
    "commission_vs_realized_pnl": case_commission_vs_realized_pnl,
    "triggered_close_position_bracket": case_triggered_close_position_bracket,
    "tp1_quantity_from_fill": case_tp1_quantity_from_fill,
    "exchange_info_read_for_close": case_exchange_info_read_for_close,
    "gtd_min_lifetime_boundary": case_gtd_min_lifetime_boundary,
    "partial_fill_attempt": case_partial_fill_attempt,
    "entry_cancel_fill_race": case_entry_cancel_fill_race,
    "stream_loss_during_case": case_stream_loss_during_case,
    "reduce_only_market_on_flat": case_reduce_only_market_on_flat,
    "reduce_only_market_larger_than_position": case_reduce_only_market_larger_than_position,
    "non_reduce_only_below_min_notional": case_non_reduce_only_below_min_notional,
    "insufficient_margin_order": case_insufficient_margin_order,
    "stop_rejected_after_acceptance": case_stop_rejected_after_acceptance,
    "trigger_cancel_race": case_trigger_cancel_race,
    "timestamp_outside_recv_window": case_timestamp_outside_recv_window,
    "income_history_read": case_income_history_read,
    "gtd_entry_expiry_status": case_gtd_entry_expiry_status,
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
        rest_fixtures: Sequence[str] = (),
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
        if rest_fixtures:
            self.recorder.records[case_id]["rest_fixtures"] = list(rest_fixtures)

    def _rest_fixtures(self, case_id: str, result: CaseResult) -> list[str]:
        """Write each REST answer of a capture case as a scrubbed fixture (executed runs only).

        One file per observation, `<case_id>-rest-<NNN>-<operation>.json`, beside the raw frame
        fixtures; the names go to `recorder.fixtures` (so `provenance.md` lists them). Only the
        cases of `FIXTURE_CASES` (the sj0 ten and the sj1 five) write them; dry runs write none.
        """
        directory = self.config.fixtures_dir
        if case_id not in FIXTURE_CASES or self.dry_run or directory is None:
            return []
        names: list[str] = []
        for index, observation in enumerate(result.observations, start=1):
            document = {
                "label": FIXTURE_LABEL_EXECUTE,
                "case_id": case_id,
                "index": index,
                "observation": observation,
            }
            stem = f"{case_id}-rest-{index:03d}-{_FIXTURE_EVENT_RE.sub('_', observation.operation)}"
            names.append(write_evidence_atomic(directory, stem, document, self.redactor).name)
        self.recorder.fixtures.extend(names)
        return names

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
            rest_fixtures=self._rest_fixtures(case_id, result),
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

    @property
    def banned(self) -> bool:
        """The adapter's ban flag (read only); an adapter without a readable flag counts as
        banned, so a write case never attempts its after-ban cleanup on an unknown state."""
        flag = getattr(self._adapter, "banned", None)
        return flag if isinstance(flag, bool) else True

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

    # ----- quick task 261021-sj0: the capture operations ---------------------- #

    async def account_information(self) -> ProbeObservation:
        self._enter("account_information")
        result: ProbeObservation = await self._adapter.account_information()
        return result

    async def account_balance_all(self) -> ProbeObservation:
        self._enter("account_balance_all")
        result: ProbeObservation = await self._adapter.account_balance_all()
        return result

    async def account_config(self) -> ProbeObservation:
        self._enter("account_config")
        result: ProbeObservation = await self._adapter.account_config()
        return result

    async def symbol_config(self, *, symbol: str) -> ProbeObservation:
        self._enter("symbol_config")
        result: ProbeObservation = await self._adapter.symbol_config(symbol=symbol)
        return result

    async def leverage_brackets(self, *, symbol: str) -> ProbeObservation:
        self._enter("leverage_brackets")
        result: ProbeObservation = await self._adapter.leverage_brackets(symbol=symbol)
        return result

    async def income_history(self, *, symbol: str, start_time_ms: int) -> ProbeObservation:
        self._enter("income_history")
        result: ProbeObservation = await self._adapter.income_history(
            symbol=symbol, start_time_ms=start_time_ms
        )
        return result

    async def query_algo_order_by_algo_id(self, *, algo_id: int) -> ProbeObservation:
        self._enter("query_algo_order_by_algo_id")
        result: ProbeObservation = await self._adapter.query_algo_order_by_algo_id(algo_id=algo_id)
        return result

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
        self._enter("new_gtd_limit_order")
        result: ProbeObservation = await self._adapter.new_gtd_limit_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            client_order_id=client_order_id,
            position_side=position_side,
            good_till_date_ms=good_till_date_ms,
        )
        return result

    async def live_mark_price(self, *, symbol: str) -> ProbeObservation:
        self._enter("live_mark_price")
        result: ProbeObservation = await self._adapter.live_mark_price(symbol=symbol)
        return result

    async def server_time(self) -> ProbeObservation:
        self._enter("server_time")
        result: ProbeObservation = await self._adapter.server_time()
        return result

    async def order_book(self, *, symbol: str) -> ProbeObservation:
        self._enter("order_book")
        result: ProbeObservation = await self._adapter.order_book(symbol=symbol)
        return result

    async def stale_timestamp_read(
        self, *, symbol: str, recv_window_ms: int, timestamp_behind_ms: int
    ) -> ProbeObservation:
        self._enter("stale_timestamp_read")
        result: ProbeObservation = await self._adapter.stale_timestamp_read(
            symbol=symbol, recv_window_ms=recv_window_ms, timestamp_behind_ms=timestamp_behind_ms
        )
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
