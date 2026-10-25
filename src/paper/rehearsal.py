"""The test-only rehearsal of the SHADOW chain (Phase 16, plan 16-39, REV-03, D061 item D, D-19).

REV-03 (D063 item 3) asks for one clearly labelled test signal that exercises the SHADOW chain
BEFORE the trial soak, in a separate rehearsal window and never inside the soak: alert, APPROVE,
confirmation card, CONFIRM, the journal and state transitions, and a simulated position opened by
the same fill driver. This module is that path. It is a separate entry from the production paper
path:

- it builds its own signal and plan from a fixed fixture (the `TEST-` ids, the label `TEST SIGNAL`
  and fixed relative offsets around the observed mark price); nothing comes from a parameter-set
  candidate or from research output, and the signal is not a strategy candidate;
- it constructs the very same chain (`ShadowCoordinator`) with test-only marking: every store
  write goes through `RehearsalStores`, which refuses a row that is not traceable to the `TEST-`
  signal and stamps `test_only` into every journal payload, and every paper record the chain
  assembles is rebuilt with `test_only` set;
- it never calls the production start gate, never reads the paper-start allowlist, never pins an
  epoch and imports nothing from the production runtime or pipeline modules; the empty production
  allowlist is therefore not bypassed, it is simply not on this path;
- it refuses to run a second time against the same rehearsal database (REV-03: once).

The analytics reader excludes and counts `test_only` records (plan 16-36) and the trial evaluator
rejects them (plan 16-25); the rehearsal runs in its own compose project with its own database
(RUNBOOK 20.4), so the soak database never holds a rehearsal row.
"""

from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from src.adapters.telegram_notify import TelegramTextBot
from src.approval.mapping import ShortIdMapping
from src.backtest.costs import build_cost_model, cost_slice
from src.core.types import Candle
from src.domain.approval import Approval
from src.domain.canonical import sha256_hex
from src.domain.enums import (
    ApprovalAction,
    ApprovalResult,
    DailyState,
    SignalStatus,
    TradePlanStatus,
)
from src.domain.journal import JournalEvent
from src.domain.registry import ParameterSet
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan
from src.ops.redaction import Redactor
from src.paper.attribution import ShadowOutcome
from src.paper.evidence_export import ShadowRow
from src.paper.journal import PaperRecord
from src.paper.loop import BarOutcome
from src.paper.shadow import SHADOW_LABEL, Mode, ShadowSendOutcome, approval_id_for
from src.paper.shadow_confirm import (
    EVENT_SHADOW_CONFIRMED,
    TERMINAL_CONFIRM_EVENTS,
)
from src.paper.shadow_ledger import (
    CORRELATION_PREFIX,
    EVENT_SHADOW_POSITION_OPENED,
    ShadowLedger,
)
from src.paper.shadow_runtime import (
    FillContext,
    ShadowCoordinator,
    ShadowPublicFeed,
    ShadowRuntimeStores,
    SnapshotSource,
)
from src.risk.types import PortfolioVerdict, SizedResult

# --------------------------------------------------------------------------- #
# The fixed fixture. Nothing here is a strategy parameter or a tuned value.
# --------------------------------------------------------------------------- #

TEST_ID_PREFIX: Final = "TEST-"
TEST_SIGNAL_ID: Final = "TEST-REHEARSAL-SIGNAL-0001"
TEST_PLAN_ID: Final = "TEST-REHEARSAL-PLAN-0001"
TEST_EPOCH_ID: Final = "TEST-REHEARSAL-EPOCH"
TEST_STRATEGY_ID: Final = "TEST-REHEARSAL"
TEST_STRATEGY_VERSION: Final = "TEST-v0"
TEST_PARAMETER_SET_ID: Final = "TEST-PARAMS"
TEST_PARAMETER_SET_HASH: Final = TEST_ID_PREFIX + "0" * 59
# The label travels in the regime reason code of the alert (`REGIME_TEST SIGNAL`) and in the
# `TEST-` ids. The persisted `setup_type` must be one of the six values the database allows
# (`ck_signals_setup_type`), so it cannot carry the label; a long pullback matches the plan.
TEST_LABEL: Final = "TEST SIGNAL"
TEST_SETUP_TYPE: Final = "TREND_PULLBACK_LONG"

# Offsets around the observed mark price, as fractions of it. They only make the labelled plan
# marketable on the next live minutes; they say nothing about any setup.
ENTRY_HALF_WIDTH: Final = Decimal("0.0005")
STOP_DISTANCE: Final = Decimal("0.01")
TP1_DISTANCE: Final = Decimal("0.015")
TP2_DISTANCE: Final = Decimal("0.03")
# The planned notional is this multiple of the exchange minimum notional (a small position).
NOTIONAL_FACTOR: Final = Decimal("2")
PLAN_TTL: Final = timedelta(hours=4)

PROOF_FAKE: Final = "FAKE"
PROOF_REAL_REHEARSAL: Final = "REAL_REHEARSAL"

ALREADY_RAN_MESSAGE: Final = "rehearsal already ran on this database (REV-03: once)"

EVIDENCE_KEYS: Final = (
    "test_id",
    "label_seen",
    "approval_requested_at_utc",
    "approval_acted_at_utc",
    "confirm_requested_at_utc",
    "confirmed_at_utc",
    "measured_delay_seconds",
    "confirmed_within_ttl",
    "position_opened",
    "records_written",
    "records_test_only",
    "proof_class",
)


class RehearsalError(RuntimeError):
    """The rehearsal cannot run or continue (fail closed): the message is this module's own."""


class RehearsalAlreadyRan(RehearsalError):
    """The rehearsal database already holds the test signal: the rehearsal runs once (REV-03)."""


class RehearsalMode(StrEnum):
    """DRY_RUN drives the chain with fakes; LIVE is the operator's run with real Telegram taps.

    The proof class follows the mode (`proof_class_for`), never a caller-supplied value.
    """

    DRY_RUN = "dry-run"
    LIVE = "live-telegram"


def proof_class_for(mode: RehearsalMode) -> str:
    """REAL_REHEARSAL only in live mode; a dry run is FAKE and can never claim more (SC9)."""
    return PROOF_REAL_REHEARSAL if mode is RehearsalMode.LIVE else PROOF_FAKE


@dataclass(frozen=True)
class RehearsalSettings:
    """What the rehearsal needs besides the injected ports (the runtime values in live mode)."""

    symbol: str
    chat_id: int
    authorized_user_ids: frozenset[int]
    initial_equity: Decimal
    risk_rate: Decimal
    minute_poll_interval_seconds: int
    minute_close_lag_seconds: int
    confirm_ttl_seconds: int
    max_wait_seconds: int = 900


# The operator's two presses. In a dry run the script supplies them; in a live run the human
# presses the real buttons and no press function exists.
PressFn = Callable[[ShadowCoordinator, str, str], Awaitable[None]]


# --------------------------------------------------------------------------- #
# Test-only marking of the stores.
# --------------------------------------------------------------------------- #


def _is_test_id(value: str | None) -> bool:
    return value is not None and value.startswith(TEST_ID_PREFIX)


class RehearsalStores:
    """The chain's stores with test-only marking, in front of the real ones.

    A signal, plan, approval, mapping or journal row whose signal id is not a `TEST-` id is
    refused (fail closed: nothing the rehearsal does may touch another plan), and every journal
    payload gets `"test_only": true` before it is stored. `written` counts the rows written
    through this wrapper and `marked` those that carry the mark when they reach the store; the
    mark is read back from the object that is stored, not assumed.
    """

    def __init__(self, inner: ShadowRuntimeStores) -> None:
        self._inner = inner
        self.written = 0
        self.marked = 0

    # ---- writers ---------------------------------------------------------- #

    def _count(self, signal_id: str | None, *, flagged: bool = False) -> None:
        if signal_id is not None and not _is_test_id(signal_id):
            raise RehearsalError(
                f"the rehearsal refuses a row of the non-test signal {signal_id!r}"
            )
        self.written += 1
        if flagged or _is_test_id(signal_id):
            self.marked += 1

    def insert_signal(self, signal: Signal) -> None:
        self._count(signal.signal_id)
        self._inner.insert_signal(signal)

    def insert_trade_plan(self, plan: TradePlan) -> None:
        self._count(plan.signal_id)
        self._inner.insert_trade_plan(plan)

    def insert_pending(self, approval: Approval) -> None:
        self._count(approval.signal_id)
        self._inner.insert_pending(approval)

    def record_short_id_mapping(self, mapping: ShortIdMapping) -> None:
        self._count(mapping.signal_id)
        self._inner.record_short_id_mapping(mapping)

    def save_atomic(self, approval: Approval, mapping: ShortIdMapping | None) -> None:
        self._count(approval.signal_id)
        self._inner.save_atomic(approval, mapping)

    def record_journal(self, event: JournalEvent) -> None:
        marked = dataclasses.replace(event, payload_json=_mark_payload(event.payload_json))
        flagged = json.loads(marked.payload_json).get("test_only") is True
        self._count(marked.signal_id, flagged=flagged)
        self._inner.record_journal(marked)

    # ---- readers (delegated unchanged) ------------------------------------ #

    def lookup_by_token_hash(self, token_hash: str) -> Approval | None:
        return self._inner.lookup_by_token_hash(token_hash)

    def lookup_by_short_id(self, short_id: str) -> tuple[str, str] | None:
        return self._inner.lookup_by_short_id(short_id)

    def list_pending_approvals(self) -> list[Approval]:
        return self._inner.list_pending_approvals()

    def list_approved_approvals(self) -> list[Approval]:
        return self._inner.list_approved_approvals()

    def journal_for_correlation(self, correlation_id: str) -> list[JournalEvent]:
        return self._inner.journal_for_correlation(correlation_id)

    def get_signal(self, signal_id: str) -> Signal | None:
        return self._inner.get_signal(signal_id)

    def get_trade_plan(self, trade_plan_id: str) -> TradePlan | None:
        return self._inner.get_trade_plan(trade_plan_id)

    def get_approval(self, approval_id: str) -> Approval | None:
        return self._inner.get_approval(approval_id)


def _mark_payload(payload_json: str) -> str:
    """The journal payload with `test_only: true` (same canonical layout as the chain's own)."""
    loaded = json.loads(payload_json)
    if not isinstance(loaded, dict):
        raise RehearsalError("a journal payload of the rehearsal must be a JSON object")
    loaded["test_only"] = True
    return json.dumps(loaded, sort_keys=True, separators=(",", ":"))


class RehearsalCoordinator(ShadowCoordinator):
    """The SHADOW chain, with every paper record it assembles marked `test_only` (REV-03)."""

    def records_for(
        self, signal: Signal, plan: TradePlan, now_utc: datetime | None = None
    ) -> list[PaperRecord]:
        return [
            dataclasses.replace(record, test_only=True)
            for record in super().records_for(signal, plan, now_utc)
        ]


class RecordingBot:
    """Forwards to the real bot and remembers the texts that were delivered.

    `label_seen` in the evidence is true only when the delivered alert carried both the SHADOW
    label and the TEST SIGNAL label. The real bot may exist only once the Telegram application
    does, so it can be bound after construction.
    """

    def __init__(self, inner: TelegramTextBot | None) -> None:
        self._inner = inner
        self.delivered: list[str] = []

    def bind(self, bot: TelegramTextBot) -> None:
        self._inner = bot

    def _require(self) -> TelegramTextBot:
        if self._inner is None:
            raise RehearsalError("the Telegram bot is not bound yet")
        return self._inner

    async def send_message(
        self, *, chat_id: str | int, text: str, reply_markup: Any = None
    ) -> object:
        result = await self._require().send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup
        )
        self.delivered.append(text)
        return result

    async def edit_message_text(
        self, *, chat_id: str | int, message_id: int, text: str, reply_markup: Any = None
    ) -> object:
        result = await self._require().edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, reply_markup=reply_markup
        )
        self.delivered.append(text)
        return result

    async def edit_message_reply_markup(
        self, *, chat_id: str | int, message_id: int, reply_markup: Any = None
    ) -> object:
        return await self._require().edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
        )


# --------------------------------------------------------------------------- #
# The labelled test signal.
# --------------------------------------------------------------------------- #


def _floor_to(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def _ceil_to(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def _to_ms(value: datetime) -> int:
    return (value - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1)


def build_test_outcome(
    *,
    settings: RehearsalSettings,
    constraints: SnapshotSource,
    reference_price: Decimal,
    now_utc: datetime,
) -> BarOutcome:
    """The labelled test signal and its plan, sized from the fixed fixture and the exchange tick.

    The signal bar is the last whole hour before `now_utc`. The levels are fixed fractions of
    `reference_price` (the observed mark price) rounded to the exchange tick; the quantity is the
    smallest step multiple whose notional reaches `NOTIONAL_FACTOR` times the minimum notional.
    """
    if reference_price <= 0:
        raise RehearsalError("the reference price must be positive")
    close = now_utc.replace(minute=0, second=0, microsecond=0) - timedelta(milliseconds=1)
    snapshot = constraints.snapshot_for(settings.symbol, close)
    tick, step = snapshot.price_tick_size, snapshot.quantity_step_size
    entry_min = _floor_to(reference_price * (1 - ENTRY_HALF_WIDTH), tick)
    entry_max = _floor_to(reference_price * (1 + ENTRY_HALF_WIDTH), tick)
    stop = _floor_to(reference_price * (1 - STOP_DISTANCE), tick)
    tp1 = _floor_to(reference_price * (1 + TP1_DISTANCE), tick)
    tp2 = _floor_to(reference_price * (1 + TP2_DISTANCE), tick)
    if not stop < entry_min <= entry_max < tp1 < tp2:
        raise RehearsalError("the price tick is too coarse for the fixed plan offsets")
    quantity = max(
        _ceil_to(snapshot.min_notional * NOTIONAL_FACTOR / entry_min, step),
        snapshot.min_quantity,
    )
    risk = quantity * (entry_max - stop)
    risk_distance = entry_max - stop
    rr1 = ((tp1 - entry_max) / risk_distance).quantize(Decimal("0.01"))
    rr2 = ((tp2 - entry_max) / risk_distance).quantize(Decimal("0.01"))
    detected = now_utc
    expiry = detected + PLAN_TTL
    plan_hash = (
        TEST_ID_PREFIX
        + sha256_hex(
            {
                "symbol": settings.symbol,
                "entry_min": str(entry_min),
                "entry_max": str(entry_max),
                "stop": str(stop),
                "tp1": str(tp1),
                "tp2": str(tp2),
                "quantity": str(quantity),
                "detected_at_utc": detected.isoformat(),
            }
        )[:59]
    )
    signal = Signal(
        signal_id=TEST_SIGNAL_ID,
        strategy_id=TEST_STRATEGY_ID,
        strategy_version=TEST_STRATEGY_VERSION,
        parameter_set_id=TEST_PARAMETER_SET_ID,
        parameter_set_hash=TEST_PARAMETER_SET_HASH,
        symbol=settings.symbol,
        direction="LONG",
        setup_type=TEST_SETUP_TYPE,
        source_timeframe="1h",
        source_candle_close_utc=close,
        detected_at_utc=detected,
        status=SignalStatus.DETECTED,
        expires_at_utc=expiry,
    )
    plan = TradePlan(
        trade_plan_id=TEST_PLAN_ID,
        signal_id=TEST_SIGNAL_ID,
        trade_plan_version=TEST_STRATEGY_VERSION,
        entry_model="LIMIT_ZONE",
        entry_min_price=entry_min,
        entry_max_price=entry_max,
        stop_loss_price=stop,
        take_profit_json=json.dumps(
            {
                "tp1": str(tp1),
                "tp1_role": "TAKE_PROFIT_1",
                "tp2": str(tp2),
                "tp2_role": "TAKE_PROFIT_2",
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        invalidation_rule_json=json.dumps(
            {"basis": "CANDLE_CLOSE", "break_distance_atr": "10", "level": str(stop)},
            sort_keys=True,
            separators=(",", ":"),
        ),
        expiry_utc=expiry,
        expected_rr_json=json.dumps(
            {"tp1_rr": str(rr1), "tp2_rr": str(rr2)}, sort_keys=True, separators=(",", ":")
        ),
        risk_rate=settings.risk_rate,
        risk_budget=risk,
        suggested_quantity=quantity,
        quantity_before_rounding=quantity,
        quantity_after_rounding=quantity,
        quantization_decision="ACCEPTED",
        plan_hash=plan_hash,
        status=TradePlanStatus.READY,
        created_at_utc=detected,
    )
    candle = Candle(
        symbol=settings.symbol,
        interval="1h",
        open_time_utc=close - timedelta(hours=1) + timedelta(milliseconds=1),
        close_time_utc=close,
        open=reference_price,
        high=reference_price,
        low=reference_price,
        close=reference_price,
        volume=Decimal("0"),
    )
    sized = SizedResult(
        is_no_trade=False,
        quantity=quantity,
        quantity_before_rounding=quantity,
        quantity_after_rounding=quantity,
        quantization_decision="ACCEPTED",
        realized_risk=risk,
    )
    return BarOutcome(
        closed_candle=candle,
        stage="risk_passed",
        reason_code="OK",
        signal=signal,
        trade_plan=plan,
        verdict=PortfolioVerdict(False, sized, "OK", DailyState.NORMAL),
        regime=TEST_LABEL,
    )


async def observed_reference_price(
    public: ShadowPublicFeed, symbol: str, now_utc: datetime
) -> Decimal:
    """The close of the newest closed 1m mark-price minute (credential-free public data)."""
    rows = await public.mark_klines(symbol, "1m", start_ms=None, end_ms=_to_ms(now_utc), limit=2)
    closed = [row for row in rows if row.close_time_utc <= now_utc]
    if not closed:
        raise RehearsalError(f"no closed mark price minute of {symbol} is available")
    return max(closed, key=lambda row: row.open_time_utc).close


# --------------------------------------------------------------------------- #
# Observation of the journaled chain and the evidence.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Observation:
    approve: Approval | None
    skip: Approval | None
    confirm_requested_at: datetime | None
    confirmed_at: datetime | None
    confirm_terminal: str | None
    opened: bool

    @property
    def finished(self) -> bool:
        """True when nothing more can happen: a position opened or the plan ended."""
        if self.opened:
            return True
        if self.skip is not None and self.skip.status is not ApprovalResult.PENDING:
            return True
        if self.approve is not None and self.approve.status not in (
            ApprovalResult.PENDING,
            ApprovalResult.APPROVED,
        ):
            return True
        return self.confirm_terminal is not None and self.confirm_terminal != EVENT_SHADOW_CONFIRMED


def _observe(stores: ShadowRuntimeStores, plan: TradePlan) -> _Observation:
    approve = stores.get_approval(approval_id_for(plan, ApprovalAction.APPROVE))
    skip = stores.get_approval(approval_id_for(plan, ApprovalAction.SKIP_USER))
    requested: datetime | None = None
    confirmed: datetime | None = None
    terminal: str | None = None
    opened = False
    if approve is not None:
        events = stores.journal_for_correlation(f"{CORRELATION_PREFIX}{approve.approval_id}")
        for event in events:
            body = json.loads(event.payload_json)
            if event.event_type in TERMINAL_CONFIRM_EVENTS:
                terminal = event.event_type
            if "confirm_requested_at_utc" in body:
                requested = datetime.fromisoformat(str(body["confirm_requested_at_utc"]))
            if event.event_type == EVENT_SHADOW_CONFIRMED and "confirmed_at_utc" in body:
                confirmed = datetime.fromisoformat(str(body["confirmed_at_utc"]))
            if event.event_type == EVENT_SHADOW_POSITION_OPENED:
                opened = True
    return _Observation(approve, skip, requested, confirmed, terminal, opened)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def evidence_document(
    *,
    observation: _Observation,
    label_seen: bool,
    confirm_ttl_seconds: int,
    records_written: int,
    records_test_only: int,
    proof_class: str,
) -> dict[str, Any]:
    """The rehearsal evidence: exactly `EVIDENCE_KEYS`, nothing else."""
    requested = None if observation.approve is None else observation.approve.requested_at_utc
    acted = None if observation.approve is None else observation.approve.acted_at_utc
    delay: float | None = None
    if requested is not None and acted is not None:
        delay = round((acted - requested).total_seconds(), 3)
    within_ttl = (
        observation.confirm_requested_at is not None
        and observation.confirmed_at is not None
        and observation.confirmed_at - observation.confirm_requested_at
        <= timedelta(seconds=confirm_ttl_seconds)
    )
    document: dict[str, Any] = {
        "test_id": TEST_SIGNAL_ID,
        "label_seen": label_seen,
        "approval_requested_at_utc": _iso(requested),
        "approval_acted_at_utc": _iso(acted),
        "confirm_requested_at_utc": _iso(observation.confirm_requested_at),
        "confirmed_at_utc": _iso(observation.confirmed_at),
        "measured_delay_seconds": delay,
        "confirmed_within_ttl": within_ttl,
        "position_opened": observation.opened,
        "records_written": records_written,
        "records_test_only": records_test_only,
        "proof_class": proof_class,
    }
    if tuple(document) != EVIDENCE_KEYS:  # pragma: no cover - guards the literal above
        raise RehearsalError("the evidence keys drifted from the agreed list")
    return document


def write_evidence(document: Mapping[str, Any], out: Path, *, environ: Mapping[str, str]) -> Path:
    """Scrub, write to a temp file, `os.replace` into place, re-scan; delete a file that fails.

    The file is never overwritten: an existing `out` is refused before anything is written.
    """
    if out.exists():
        raise RehearsalError(
            f"{out.name} already exists: the rehearsal evidence is not overwritten"
        )
    redactor = Redactor.from_environ(environ)
    text = redactor.scrub(json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.parent / f".{out.name}.tmp"
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temp, out)
    written = out.read_bytes().decode("utf-8")
    if redactor.scrub(written) != written:
        out.unlink()
        raise RehearsalError("the evidence failed the post-write secret scan and was removed")
    return out


# --------------------------------------------------------------------------- #
# The run.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RehearsalResult:
    """What a rehearsal run produced (the evidence file is already written)."""

    evidence: dict[str, Any]
    path: Path
    records: tuple[PaperRecord, ...]
    shadow_row: ShadowRow | None
    complete: bool


def _shadow_row_of(records: tuple[PaperRecord, ...], observation: _Observation) -> ShadowRow | None:
    """The export row of a finished APPROVE then CONFIRM then fill (None for anything else)."""
    sim = next((r for r in records if r.attribution.value == "user-executed-sim"), None)
    approve = observation.approve
    if (
        sim is None
        or approve is None
        or sim.signal_id is None
        or sim.plan_hash is None
        or sim.fill_time_utc is None
        or sim.order_submitted_at_utc is None
        or observation.confirm_requested_at is None
        or observation.confirmed_at is None
    ):
        return None
    return ShadowRow(
        epoch_id=sim.epoch_id,
        signal={
            "strategy_id": sim.strategy_id,
            "strategy_version": sim.strategy_version,
            "parameter_set_id": sim.parameter_set_id,
            "parameter_set_hash": sim.parameter_set_hash,
            "experiment_id": sim.experiment_id,
            "symbol": sim.symbol,
            "signal_id": sim.signal_id,
            "detected_at_utc": _iso(sim.signal_detected_at_utc),
        },
        trade_plan={"plan_hash": sim.plan_hash},
        approval={
            "approval_id": approve.approval_id,
            "action": approve.action.value,
            "requested_at_utc": _iso(approve.requested_at_utc),
            "acted_at_utc": _iso(approve.acted_at_utc),
        },
        order={"submitted_at_utc": _iso(sim.order_submitted_at_utc)},
        fill={"fill_time_utc": _iso(sim.fill_time_utc)},
        confirm={
            "confirm_requested_at_utc": _iso(observation.confirm_requested_at),
            "confirmed_at_utc": _iso(observation.confirmed_at),
        },
        shadow_outcome=ShadowOutcome(approval_action="APPROVE", confirm_event="SHADOW_CONFIRMED"),
        test_only=True,
    )


async def run_rehearsal(
    *,
    mode: RehearsalMode,
    stores: ShadowRuntimeStores,
    bot: TelegramTextBot | None,
    public: ShadowPublicFeed,
    clock: Callable[[], datetime],
    out: Path,
    settings: RehearsalSettings,
    parameter_set: ParameterSet,
    constraints: SnapshotSource,
    sleep: Callable[[float], Awaitable[None]],
    environ: Mapping[str, str],
    press: PressFn | None = None,
    application_factory: Callable[[dict[str, Any]], Any] | None = None,
) -> RehearsalResult:
    """Run the labelled test signal through the SHADOW chain once and write the evidence.

    Refuses, before anything is written or sent, when the stores already hold the test signal
    (`RehearsalAlreadyRan`) or when `out` exists. In live mode `application_factory` builds the
    Telegram application that receives the operator's real presses (`press` is None); its bot is
    bound into the recording bot so that every delivered text is seen. A failure while the chain
    runs still writes the evidence of what happened (it then shows the missing steps) and is
    raised afterwards as a `RehearsalError` naming the exception class only.
    """
    if stores.get_signal(TEST_SIGNAL_ID) is not None:
        raise RehearsalAlreadyRan(ALREADY_RAN_MESSAGE)
    if out.exists():
        raise RehearsalError(
            f"{out.name} already exists: the rehearsal evidence is not overwritten"
        )
    recording = RecordingBot(bot)
    marked = RehearsalStores(stores)
    ledger = ShadowLedger(
        initial_equity=settings.initial_equity,
        parameter_set_params=parameter_set.params,
        started_at_utc=clock(),
    )
    fill = FillContext(
        cost_model=build_cost_model(cost_slice(parameter_set.params)),
        strategy_version=TEST_STRATEGY_VERSION,
        parameter_set_hash=TEST_PARAMETER_SET_HASH,
        constraints_for=constraints.snapshot_for,
    )
    coordinator = RehearsalCoordinator(
        mode=Mode.SHADOW,
        stores=marked,
        bot=recording,
        chat_id=settings.chat_id,
        authorized_user_ids=settings.authorized_user_ids,
        clock=clock,
        ledger=ledger,
        public=public,
        fill=fill,
        minute_poll_interval_seconds=settings.minute_poll_interval_seconds,
        minute_close_lag_seconds=settings.minute_close_lag_seconds,
        experiment_id=TEST_EPOCH_ID,
        epoch_id=TEST_EPOCH_ID,
        confirm_ttl_seconds=settings.confirm_ttl_seconds,
        sleep=sleep,
        application_factory=(
            None
            if application_factory is None
            else _binding_factory(application_factory, recording)
        ),
    )
    failure: Exception | None = None
    await coordinator.start()
    try:
        started = clock()
        reference = await observed_reference_price(public, settings.symbol, started)
        outcome = build_test_outcome(
            settings=settings, constraints=constraints, reference_price=reference, now_utc=started
        )
        plan = outcome.trade_plan
        if plan is None:  # pragma: no cover - build_test_outcome always sets it
            raise RehearsalError("the test outcome has no plan")
        try:
            alert = await coordinator.on_outcome(outcome)
            if alert is None or not alert.sent:
                raise RehearsalError("the labelled alert was not delivered")
            await _drive(coordinator, marked, plan, alert, settings, clock, sleep, press)
        except Exception as exc:  # noqa: BLE001 - the evidence of the partial run is still written
            failure = exc
    finally:
        await coordinator.stop()
    observation = _observe(stores, plan)
    records = tuple(record for group in coordinator.paper_records().values() for record in group)
    written = marked.written + len(records)
    test_only = marked.marked + sum(1 for record in records if record.test_only)
    label_seen = bool(recording.delivered) and (
        SHADOW_LABEL in recording.delivered[0] and TEST_LABEL in recording.delivered[0]
    )
    document = evidence_document(
        observation=observation,
        label_seen=label_seen,
        confirm_ttl_seconds=settings.confirm_ttl_seconds,
        records_written=written,
        records_test_only=test_only,
        proof_class=proof_class_for(mode),
    )
    path = write_evidence(document, out, environ=environ)
    if failure is not None:
        if isinstance(failure, RehearsalError):
            raise failure
        raise RehearsalError(
            f"the rehearsal stopped ({type(failure).__name__}); evidence of the partial run "
            f"is in {path.name}"
        ) from failure
    row = _shadow_row_of(records, observation)
    return RehearsalResult(
        evidence=document,
        path=path,
        records=records,
        shadow_row=row,
        complete=observation.opened and label_seen,
    )


def _binding_factory(
    factory: Callable[[dict[str, Any]], Any], recording: RecordingBot
) -> Callable[[dict[str, Any]], Any]:
    """The application factory that also binds the application's bot into the recording bot."""

    def build(callback_kwargs: dict[str, Any]) -> Any:
        application = factory(callback_kwargs)
        application_bot = getattr(application, "bot", None)
        if application_bot is not None:
            recording.bind(application_bot)
        return application

    return build


async def _drive(
    coordinator: ShadowCoordinator,
    stores: ShadowRuntimeStores,
    plan: TradePlan,
    alert: ShadowSendOutcome,
    settings: RehearsalSettings,
    clock: Callable[[], datetime],
    sleep: Callable[[float], Awaitable[None]],
    press: PressFn | None,
) -> None:
    """Press APPROVE and CONFIRM (dry run) and poll until a position opened or the plan ended."""
    if press is not None:
        await press(coordinator, f"APR:{alert.short_id}", f"q-apr-{alert.short_id[:6]}")
        await press(coordinator, f"CNF:{alert.short_id}", f"q-cnf-{alert.short_id[:6]}")
    deadline = clock() + timedelta(seconds=settings.max_wait_seconds)
    while True:
        await coordinator.poll_once()
        if _observe(stores, plan).finished or clock() >= deadline:
            return
        await sleep(settings.minute_poll_interval_seconds)


__all__ = [
    "ALREADY_RAN_MESSAGE",
    "EVIDENCE_KEYS",
    "PROOF_FAKE",
    "PROOF_REAL_REHEARSAL",
    "TEST_ID_PREFIX",
    "TEST_LABEL",
    "TEST_SIGNAL_ID",
    "RecordingBot",
    "proof_class_for",
    "RehearsalAlreadyRan",
    "RehearsalCoordinator",
    "RehearsalError",
    "RehearsalMode",
    "RehearsalResult",
    "RehearsalSettings",
    "RehearsalStores",
    "build_test_outcome",
    "evidence_document",
    "observed_reference_price",
    "run_rehearsal",
    "write_evidence",
]
