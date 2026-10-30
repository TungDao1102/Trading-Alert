"""The mode-independent CONFIRM state machine of D041 (Phase 23, plan 23-06, D-09, D-10, D-16).

D041 is a two-step flow: APPROVE does not confirm anything, it turns the alert into a
confirmation card with CONFIRM and CANCEL buttons, and only CONFIRM within a short TTL counts.
SHADOW has run this flow since Phase 16 (`src/paper/shadow_confirm.py`); this module is its
mode-independent core, moved here unchanged except for the parametrization by a
`ConfirmProfile`, so that SHADOW, DEMO and LIVE share one state machine (D-09).

What lives here:
  - `ConfirmBook`: a confirm token is issued per APPROVED approval, is separate from the approval
    token (a fresh one-time token, memory only; PostgreSQL and the journal never see it), is
    single use, is bound to the Telegram user id that pressed APPROVE and to the plan hash, and
    expires `ttl_seconds` (60 s by default, D041) after the card was issued. CANCEL, expiry and
    every rejection are journaled; a replayed CONFIRM replays to the existing outcome and never
    reaches `on_confirmed` a second time. A restart expires every outstanding confirm
    (`RUNTIME_RESTART`), and `assert_no_stranded_approvals` is the T-16-112 invariant.
  - `ConfirmProfile`: every string that differs by mode (the journal event names, the entity type,
    the correlation and journal id prefixes, the payload mode label, the log namespace). The
    SHADOW profile holds the literals SHADOW has always written.

What does NOT live here: the card text (injected as a `CardRenderer`, so this module has no
message text), the Telegram edit/send delivery and the callbacks (SHADOW keeps them in
`src/paper`). This module imports nothing from `src.execution`, `src.paper`, `src.adapters` or
`telegram`; the only side effect of a successful CONFIRM is the injected `on_confirmed` callable,
the single seam Phase 24 connects to `execute_approved_plan`. Money amounts on the card and the
approval-time user allow-list are plans 23-04 and 23-01.

Expiry (REV-12): the approval expiry stays the plan expiry; at CONFIRM the plan expiry is checked
again (inclusive boundary, as `src/approval/binding.py`).

Lock order (B2-CR-01): `on_confirmed` is called AFTER the book lock and the reservation section
are released. P16R-02 (D-16): every CONFIRM adopted in one sweep reaches the hook, once, in
order; one raising call does not skip the later ones and the first exception is re-raised after
all ran.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Final, Protocol, TypeVar, cast

import structlog

from src.approval.reason_codes import USER_ID_UNAVAILABLE
from src.approval.tokens import issue_one_time_token, token_hash_of
from src.domain.approval import Approval
from src.domain.enums import ApprovalResult, RejectionReason
from src.domain.journal import JournalEvent, correlated_event_id
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan

log = structlog.get_logger()

_T = TypeVar("_T")

# D041: the confirm TTL. It is the human-confirmation window of the two-step flow, not a strategy
# or risk parameter; REV-12 keeps the approval expiry equal to the plan expiry.
CONFIRM_TTL_SECONDS_DEFAULT: Final = 60


@dataclass(frozen=True)
class ConfirmProfile:
    """What differs by mode: journal names, entity type, id prefixes, payload label, log prefix.

    `event_rejected` and `event_notice_failed` are not terminal; the other three are.
    """

    mode_label: str
    event_issued: str
    event_confirmed: str
    event_cancelled: str
    event_expired: str
    event_rejected: str
    event_notice_failed: str
    entity_type: str
    correlation_prefix: str
    journal_prefix: str
    log_namespace: str

    @property
    def terminal_events(self) -> tuple[str, str, str]:
        return (self.event_confirmed, self.event_cancelled, self.event_expired)

    def correlation(self, approval_id: str) -> str:
        return f"{self.correlation_prefix}{approval_id}"


# The literals SHADOW has written since Phase 16 (pinned by the SHADOW tests, read by
# `src/paper/attribution.py`).
SHADOW_CONFIRM_PROFILE: Final = ConfirmProfile(
    mode_label="SHADOW",
    event_issued="SHADOW_CONFIRM_ISSUED",
    event_confirmed="SHADOW_CONFIRMED",
    event_cancelled="SHADOW_CONFIRM_CANCELLED",
    event_expired="SHADOW_CONFIRM_EXPIRED",
    event_rejected="SHADOW_CONFIRM_REJECTED",
    event_notice_failed="SHADOW_CONFIRM_NOTICE_FAILED",
    entity_type="ShadowConfirm",
    correlation_prefix="shadow-confirm:",
    journal_prefix="shadow-cnf",
    log_namespace="paper.shadow_confirm",
)

# DEMO and LIVE (D-09, Claude's discretion): mode-prefixed like SHADOW's. DEMO/LIVE attribution is
# a later consumer (plan 23-13 register).
DEMO_CONFIRM_PROFILE: Final = ConfirmProfile(
    mode_label="DEMO",
    event_issued="DEMO_CONFIRM_ISSUED",
    event_confirmed="DEMO_CONFIRMED",
    event_cancelled="DEMO_CONFIRM_CANCELLED",
    event_expired="DEMO_CONFIRM_EXPIRED",
    event_rejected="DEMO_CONFIRM_REJECTED",
    event_notice_failed="DEMO_CONFIRM_NOTICE_FAILED",
    entity_type="DemoConfirm",
    correlation_prefix="demo-confirm:",
    journal_prefix="demo-cnf",
    log_namespace="execution.demo_confirm",
)

LIVE_CONFIRM_PROFILE: Final = ConfirmProfile(
    mode_label="LIVE",
    event_issued="LIVE_CONFIRM_ISSUED",
    event_confirmed="LIVE_CONFIRMED",
    event_cancelled="LIVE_CONFIRM_CANCELLED",
    event_expired="LIVE_CONFIRM_EXPIRED",
    event_rejected="LIVE_CONFIRM_REJECTED",
    event_notice_failed="LIVE_CONFIRM_NOTICE_FAILED",
    entity_type="LiveConfirm",
    correlation_prefix="live-confirm:",
    journal_prefix="live-cnf",
    log_namespace="execution.live_confirm",
)


class ConfirmOutcome(str, Enum):
    """What a CONFIRM or CANCEL press amounted to, as shown to the operator (plan 16-11)."""

    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED_TTL = "EXPIRED_TTL"
    REJECTED_PLAN_EXPIRED = "REJECTED_PLAN_EXPIRED"
    REJECTED_USER_MISMATCH = "REJECTED_USER_MISMATCH"
    REJECTED_OTHER = "REJECTED_OTHER"


@dataclass(frozen=True)
class ConfirmRecord:
    """What the last CONFIRM or CANCEL press amounted to (consumed by the reply function)."""

    outcome: ConfirmOutcome
    detail: str
    confirm_requested_at_utc: datetime | None
    plan_expiry_utc: datetime | None


class _FailureKind(Protocol):
    @property
    def value(self) -> str: ...


class DeliveryFailure(Protocol):
    """A classified card-delivery failure as the book journals it (`TelegramFailure` fits)."""

    @property
    def kind(self) -> _FailureKind: ...
    @property
    def retry_after_seconds(self) -> int | None: ...
    @property
    def detail(self) -> str: ...


# The card text of one confirm: (signal, plan, mark price or None, now, ttl seconds) -> text.
CardRenderer = Callable[[Signal, TradePlan, Decimal | None, datetime, int], str]

REASON_CONFIRM_TTL_ELAPSED: Final = "CONFIRM_TTL_ELAPSED"
REASON_CARD_DELIVERY_FAILED: Final = "CARD_DELIVERY_FAILED"
REASON_RUNTIME_RESTART: Final = "RUNTIME_RESTART"
# One definition of the text: `src/approval/reason_codes.py` (the edge gate uses it too).
REASON_USER_ID_UNAVAILABLE: Final = USER_ID_UNAVAILABLE
REASON_USER_MISMATCH: Final = "USER_MISMATCH"
REASON_CHAT_MISMATCH: Final = "CHAT_MISMATCH"
REASON_NO_CONFIRM_CONTEXT: Final = "NO_CONFIRM_CONTEXT"
REASON_RECHECK_ERROR: Final = "RECHECK_ERROR"
REASON_CONFIRM_ALREADY_EXPIRED: Final = "CONFIRM_ALREADY_EXPIRED"

# How many press records are kept for replies that have not run yet (a bound, not a tuning knob).
_RESULT_RECORDS_MAX: Final = 64

# A re-check returns None to pass or the reason: a `RejectionReason`, or a plain code text for the
# labels that are not enum members (the engine's CONFLICT_WITH_OPEN_POSITION).
RecheckFn = Callable[[Signal, TradePlan, datetime], RejectionReason | str | None]
OnConfirmedFn = Callable[[Approval, TradePlan, datetime], None]
MarkPriceFn = Callable[[str], Decimal | None]


class ConfirmStores(Protocol):
    """What the confirm layer needs from persistence: the journal and the approval readers.

    The Phase 17 PostgreSQL stores provide the writers; plan 16-31 adds the two list readers
    the sweep uses (`list_approved_approvals`, `journal_for_correlation`).
    """

    def record_journal(self, event: JournalEvent) -> None: ...
    def lookup_by_token_hash(self, token_hash: str) -> Approval | None: ...
    def lookup_by_short_id(self, short_id: str) -> tuple[str, str] | None: ...
    # Every APPROVED approval of the database, of any mode (review WR-06): the orphan sweep and
    # `assert_no_stranded_approvals` judge them by the profile-prefixed correlation id only, so
    # one database must serve ONE mode until a mode-scoped reader exists.
    def list_approved_approvals(self) -> list[Approval]: ...
    def journal_for_correlation(self, correlation_id: str) -> list[JournalEvent]: ...


class ReserveOutcome(Protocol):
    """What a reservation attempt amounted to (`src/paper/shadow_ledger.py:ReserveResult`)."""

    @property
    def reserved(self) -> bool: ...
    @property
    def reason_code(self) -> str: ...


class ReservationPort(Protocol):
    """The exposure reservation of the Q-C decision `reserve-at-confirm` (plan 16-23).

    `section()` is the serialized section the CONFIRM runs in: recheck, the *_CONFIRMED
    journal write and `reserve` happen inside it, so no other CONFIRM can interleave. `check` is
    the full capacity check on the current ledger and runs BEFORE the journal write; a failure
    rejects the CONFIRM. `confirm_payload` returns the reservation facts merged into the
    *_CONFIRMED payload (the journal is the source of truth for recovery). `reserve` runs only
    after that write succeeded.
    """

    def section(self) -> AbstractContextManager[Any]: ...
    def check(self, signal: Signal, plan: TradePlan, now_utc: datetime) -> str | None: ...
    def confirm_payload(
        self,
        *,
        approval: Approval,
        signal: Signal,
        plan: TradePlan,
        short_id: str,
        confirmed_at_utc: datetime,
    ) -> Mapping[str, Any]: ...
    def reserve(
        self,
        *,
        approval: Approval,
        signal: Signal,
        plan: TradePlan,
        short_id: str,
        confirmed_at_utc: datetime,
    ) -> ReserveOutcome: ...


class StrandedApprovals(AssertionError):
    """An approved plan is past the confirm TTL with no terminal confirm event (T-16-112)."""


# --------------------------------------------------------------------------- #
# State.
# --------------------------------------------------------------------------- #


class ConfirmState(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass
class ConfirmEntry:
    """One issued confirm token and where it stands. Internal state: read it, do not edit it.

    The capability is this in-memory entry, looked up by short id; `raw_token` is held but no
    press carries or compares it (review WR-07). Replay protection is the entry state, never the
    token text. `raw_token` is a secret and is left out of the generated `__repr__`.
    """

    short_id: str
    approval: Approval
    signal: Signal
    plan: TradePlan
    approving_user_id: int
    issued_at_utc: datetime
    ttl_seconds: int
    token_hash: str
    # Review WR-07: a secret never prints; the generated __repr__ leaves it out.
    raw_token: str = field(repr=False)
    card_text: str
    state: ConfirmState = ConfirmState.PENDING
    outcome: ConfirmOutcome | None = None
    reason: str = ""
    decided_at_utc: datetime | None = None
    delivered: bool = False
    message_id: int | None = None
    # The *_CONFIRMED append raised, so whether it committed is unknown: the next press
    # reconciles against the journal before doing anything else (plan 16-23).
    confirm_append_unknown: bool = False
    # The CONFIRM is journaled but the reservation step has not completed: a repeated press
    # retries it (idempotent) so the ledger never lacks a journaled reservation.
    reservation_pending: bool = False
    # The `on_confirmed` hook raised for this CONFIRM (review WR-08): the entry is CONFIRMED and
    # journaled, but nothing proves the plan was handed over, so a final text must not say so.
    hand_off_failed: bool = False

    @property
    def expires_at_utc(self) -> datetime:
        return self.issued_at_utc + timedelta(seconds=self.ttl_seconds)


@dataclass(frozen=True)
class ConfirmResult:
    """What a CONFIRM or CANCEL press amounted to."""

    outcome: ConfirmOutcome
    replayed: bool
    reason: str
    detail: str


def _payload(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _require_utc(value: datetime, field: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be UTC-aware, got naive datetime")


# --------------------------------------------------------------------------- #
# The confirm book.
# --------------------------------------------------------------------------- #


class ConfirmBook:
    """Issues confirm tokens, holds them in memory, and journals every outcome.

    Pure of Telegram: it returns results, the callbacks of the mode's module do the I/O. The mode
    is the `profile` (journal names, ids, payload label); the card text is the `card_renderer`.
    Everything is keyed by the short id of the alert (`CNF:<short>` / `CXL:<short>`).
    """

    def __init__(
        self,
        stores: ConfirmStores,
        *,
        profile: ConfirmProfile,
        clock: Callable[[], datetime],
        card_renderer: CardRenderer,
        ttl_seconds: int = CONFIRM_TTL_SECONDS_DEFAULT,
        mark_price: MarkPriceFn | None = None,
        recheck: RecheckFn | None = None,
        on_confirmed: OnConfirmedFn | None = None,
        reservations: ReservationPort | None = None,
    ) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be a positive integer, got {ttl_seconds!r}")
        self._stores = stores
        self._profile = profile
        self._clock = clock
        self._card_renderer = card_renderer
        self._ttl = ttl_seconds
        self._mark_price = mark_price
        self._recheck = recheck
        self._on_confirmed = on_confirmed
        self._reservations = reservations
        self._lock = threading.RLock()
        self._entries: dict[str, ConfirmEntry] = {}
        # The reply record of each CONFIRM or CANCEL press, by the press correlation id
        # (`cbq:<callback query id>`), taken by the reply of that press (plan 16-58, B2-WR-03).
        # Bounded: a press whose reply never ran cannot grow it without limit.
        self._results: dict[str, ConfirmRecord] = {}
        self._press_correlation: str | None = None
        # Appended by `_finish_confirm` inside the book lock (one item per CONFIRM finished by
        # the running press or sweep), taken and called by `_in_section` after the locks are
        # released (P16R-02, D-16: a list, so a sweep that adopts several loses none).
        self._deferred_confirmed: list[tuple[Approval, TradePlan, datetime]] = []

    # ---- read side ------------------------------------------------------ #

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def now(self) -> datetime:
        """The book's clock: the anchor of every TTL decision."""
        return self._clock()

    def get(self, short_id: str) -> ConfirmEntry | None:
        return self._entries.get(short_id)

    def take_result(self, correlation_id: str | None) -> ConfirmRecord | None:
        """Return and clear the record of the press with this correlation id (for its reply).

        None for an unknown id, a press that left no record, or no id at all: a reply never
        borrows the record of another press or of a background sweep.
        """
        if correlation_id is None:
            return None
        with self._lock:
            return self._results.pop(correlation_id, None)

    def _store_result(self, record: ConfirmRecord) -> None:
        """Keep `record` for the reply of the press being handled (sweeps have none)."""
        press = self._press_correlation
        if press is None:
            return
        self._results[press] = record
        while len(self._results) > _RESULT_RECORDS_MAX:
            del self._results[next(iter(self._results))]

    # ---- journal -------------------------------------------------------- #

    def _event(
        self,
        *,
        event_type: str,
        step: str,
        approval: Approval,
        signal_id: str,
        trade_plan_id: str,
        now_utc: datetime,
        payload: Mapping[str, Any],
    ) -> JournalEvent:
        correlation = self._profile.correlation(approval.approval_id)
        return JournalEvent(
            journal_event_id=correlated_event_id(
                prefix=self._profile.journal_prefix,
                correlation_id=correlation,
                event_type=event_type,
                entity_id=approval.approval_id,
                step=step,
            ),
            occurred_at_utc=now_utc,
            event_type=event_type,
            entity_type=self._profile.entity_type,
            entity_id=approval.approval_id,
            correlation_id=correlation,
            signal_id=signal_id,
            trade_plan_id=trade_plan_id,
            approval_id=approval.approval_id,
            payload_json=_payload({**payload, "mode": self._profile.mode_label}),
        )

    def _journal(
        self,
        entry: ConfirmEntry,
        event_type: str,
        step: str,
        now_utc: datetime,
        payload: Mapping[str, Any],
    ) -> None:
        self._stores.record_journal(
            self._event(
                event_type=event_type,
                step=step,
                approval=entry.approval,
                signal_id=entry.signal.signal_id,
                trade_plan_id=entry.plan.trade_plan_id,
                now_utc=now_utc,
                payload={
                    "approval_id": entry.approval.approval_id,
                    "short_id": entry.short_id,
                    "confirm_requested_at_utc": entry.issued_at_utc.isoformat(),
                    "approving_user_id": str(entry.approving_user_id),
                    **payload,
                },
            )
        )

    def _journal_rejection(
        self,
        entry: ConfirmEntry,
        *,
        reason: str,
        presented_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
        kind: str,
    ) -> None:
        self._journal(
            entry,
            self._profile.event_rejected,
            f"press:{correlation_id}:{reason}",
            now_utc,
            {
                "reason": reason,
                "kind": kind,
                "presented_user_id": None if presented_user_id is None else str(presented_user_id),
            },
        )

    # ---- issue ---------------------------------------------------------- #

    def issue(
        self,
        *,
        short_id: str,
        approval: Approval,
        signal: Signal,
        plan: TradePlan,
        approving_user_id: int | None,
        now_utc: datetime,
    ) -> ConfirmEntry:
        """Issue the confirm token for an APPROVED approval and render the card (idempotent).

        A second call for the same short id returns the existing entry: one token per approval.
        Without a user id to bind to, no card can be confirmed by anyone, so the confirm is
        journaled EXPIRED at once (reason USER_ID_UNAVAILABLE) instead of issuing a token.
        """
        _require_utc(now_utc, "now_utc")
        existing = self._entries.get(short_id)
        if existing is not None:
            return existing
        mark = self._current_mark(signal.symbol)
        raw_token = issue_one_time_token()
        fields: dict[str, Any] = {
            "short_id": short_id,
            "approval": approval,
            "signal": signal,
            "plan": plan,
            "approving_user_id": approving_user_id if approving_user_id is not None else -1,
            "issued_at_utc": now_utc,
            "ttl_seconds": self._ttl,
            "token_hash": token_hash_of(raw_token),
            "raw_token": raw_token,
        }
        entry = self._new_entry(fields, mark=mark, now_utc=now_utc)
        self._entries[short_id] = entry
        if approving_user_id is None:
            self._terminate(
                entry,
                state=ConfirmState.EXPIRED,
                outcome=ConfirmOutcome.REJECTED_OTHER,
                reason=REASON_USER_ID_UNAVAILABLE,
                now_utc=now_utc,
                event_type=self._profile.event_expired,
            )
        return entry

    def _new_entry(
        self, fields: Mapping[str, Any], *, mark: Decimal | None, now_utc: datetime
    ) -> ConfirmEntry:
        """Build the entry with its card text from the injected `card_renderer`.

        `fields` are the `ConfirmEntry` fields but the card. A mode module may override this to
        keep the construction site of its card next to its composer (SHADOW does).
        """
        card_text = self._card_renderer(fields["signal"], fields["plan"], mark, now_utc, self._ttl)
        return ConfirmEntry(**fields, card_text=card_text)

    def _current_mark(self, symbol: str) -> Decimal | None:
        if self._mark_price is None:
            return None
        try:
            return self._mark_price(symbol)
        except Exception as exc:  # noqa: BLE001 - a missing mark price is shown, not fatal
            log.warning(
                f"{self._profile.log_namespace}.mark_price_failed", error_class=type(exc).__name__
            )
            return None

    # ---- delivery outcomes ---------------------------------------------- #

    def record_issued(
        self,
        entry: ConfirmEntry,
        *,
        delivery: str,
        message_id: int | None,
        attempts: int,
        edit_failure: DeliveryFailure | None,
        now_utc: datetime,
    ) -> None:
        """The card reached the chat: journal *_CONFIRM_ISSUED (unless already decided)."""
        if entry.state is not ConfirmState.PENDING:
            return
        if now_utc >= entry.expires_at_utc:
            # Fail safe: a card delivered after its TTL ran out is expired at once.
            self._terminate(
                entry,
                state=ConfirmState.EXPIRED,
                outcome=ConfirmOutcome.EXPIRED_TTL,
                reason=REASON_CONFIRM_TTL_ELAPSED,
                now_utc=now_utc,
                event_type=self._profile.event_expired,
                extra={"delivered_late": True, "delivery": delivery},
            )
            return
        self._journal(
            entry,
            self._profile.event_issued,
            "issued",
            now_utc,
            {
                "issued_at_utc": entry.issued_at_utc.isoformat(),
                "expires_at_utc": entry.expires_at_utc.isoformat(),
                "ttl_seconds": entry.ttl_seconds,
                "delivery": delivery,
                "message_id": None if message_id is None else str(message_id),
                "attempts": attempts,
                "edit_failure_kind": None if edit_failure is None else edit_failure.kind.value,
                "confirm_token_hash_prefix": entry.token_hash[:16],
            },
        )
        entry.delivered = True
        entry.message_id = message_id

    def abort_delivery(
        self,
        entry: ConfirmEntry,
        *,
        failure: DeliveryFailure,
        notice: str,
        attempts: int,
        now_utc: datetime,
    ) -> None:
        """No card could be delivered: EXPIRED with reason CARD_DELIVERY_FAILED, token invalid."""
        if entry.state is not ConfirmState.PENDING:
            return
        self._terminate(
            entry,
            state=ConfirmState.EXPIRED,
            outcome=ConfirmOutcome.REJECTED_OTHER,
            reason=REASON_CARD_DELIVERY_FAILED,
            now_utc=now_utc,
            event_type=self._profile.event_expired,
            extra={
                "failure_kind": failure.kind.value,
                "retry_after_seconds": failure.retry_after_seconds,
                "error_class": failure.detail,
                "attempts": attempts,
                "failure_notice": notice,
            },
        )

    def record_notice_failed(
        self, entry: ConfirmEntry, failure: DeliveryFailure, now_utc: datetime
    ) -> None:
        """The best-effort failure notice failed too: journal it, change nothing else."""
        self._journal(
            entry,
            self._profile.event_notice_failed,
            "notice_failed",
            now_utc,
            {
                "failure_kind": failure.kind.value,
                "retry_after_seconds": failure.retry_after_seconds,
                "error_class": failure.detail,
            },
        )

    # ---- terminal transitions ------------------------------------------- #

    def _terminate(
        self,
        entry: ConfirmEntry,
        *,
        state: ConfirmState,
        outcome: ConfirmOutcome,
        reason: str,
        now_utc: datetime,
        event_type: str,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        """Journal the single terminal event, THEN move the state (a failed write moves nothing)."""
        body: dict[str, Any] = {"reason": reason, "decided_at_utc": now_utc.isoformat()}
        if state is ConfirmState.CONFIRMED:
            body["confirmed_at_utc"] = now_utc.isoformat()
        if state is ConfirmState.CANCELLED:
            body["cancelled_at_utc"] = now_utc.isoformat()
        if state is ConfirmState.EXPIRED:
            body["expired_at_utc"] = now_utc.isoformat()
        # Integer milliseconds: no float anywhere in this module (Decimal-only guard).
        body["elapsed_ms"] = max(0, (now_utc - entry.issued_at_utc) // timedelta(milliseconds=1))
        if extra:
            body.update(extra)
        self._journal(entry, event_type, "terminal", now_utc, body)
        entry.state = state
        entry.outcome = outcome
        entry.reason = reason
        entry.decided_at_utc = now_utc

    def _result(
        self, entry: ConfirmEntry, outcome: ConfirmOutcome, reason: str, *, replayed: bool
    ) -> ConfirmResult:
        detail = reason if not replayed else f"REPLAYED existing outcome ({reason})"
        result = ConfirmResult(outcome=outcome, replayed=replayed, reason=reason, detail=detail)
        self._store_result(
            ConfirmRecord(
                outcome=outcome,
                detail=detail,
                confirm_requested_at_utc=entry.issued_at_utc,
                plan_expiry_utc=entry.plan.expiry_utc,
            )
        )
        return result

    def _replay(
        self,
        entry: ConfirmEntry,
        *,
        kind: str,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult:
        """A press on a decided confirm replays the existing outcome.

        CONFIRMED and CANCELLED replays write nothing. A press on an EXPIRED confirm hit a dead
        token (a TTL that ran out, a failed card delivery, a restart): the attempt itself is
        journaled (idempotent per callback query) and simulates nothing.
        """
        if entry.state is ConfirmState.EXPIRED:
            self._journal_rejection(
                entry,
                reason=REASON_CONFIRM_ALREADY_EXPIRED,
                presented_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
                kind=kind,
            )
        if entry.state is ConfirmState.CONFIRMED:
            return self._result(entry, ConfirmOutcome.CONFIRMED, "CONFIRMED", replayed=True)
        if entry.state is ConfirmState.CANCELLED:
            return self._result(entry, ConfirmOutcome.CANCELLED, "CANCELLED", replayed=True)
        outcome = entry.outcome or ConfirmOutcome.REJECTED_OTHER
        return self._result(entry, outcome, entry.reason, replayed=True)

    def _expire_ttl(self, entry: ConfirmEntry, now_utc: datetime) -> ConfirmResult:
        self._terminate(
            entry,
            state=ConfirmState.EXPIRED,
            outcome=ConfirmOutcome.EXPIRED_TTL,
            reason=REASON_CONFIRM_TTL_ELAPSED,
            now_utc=now_utc,
            event_type=self._profile.event_expired,
        )
        return self._result(
            entry, ConfirmOutcome.EXPIRED_TTL, REASON_CONFIRM_TTL_ELAPSED, replayed=False
        )

    def _press_gate(
        self,
        entry: ConfirmEntry,
        *,
        kind: str,
        chat_id: int,
        authorized_chat_id: int,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult | None:
        """Chat, then user: a refusal is journaled and leaves the token usable by its owner."""
        if chat_id != authorized_chat_id:
            self._journal_rejection(
                entry,
                reason=REASON_CHAT_MISMATCH,
                presented_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
                kind=kind,
            )
            return self._result(
                entry, ConfirmOutcome.REJECTED_OTHER, REASON_CHAT_MISMATCH, replayed=False
            )
        if from_user_id is None or from_user_id != entry.approving_user_id:
            self._journal_rejection(
                entry,
                reason=REASON_USER_MISMATCH,
                presented_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
                kind=kind,
            )
            return self._result(
                entry, ConfirmOutcome.REJECTED_USER_MISMATCH, REASON_USER_MISMATCH, replayed=False
            )
        return None

    def _reject_unknown(
        self,
        short_id: str,
        *,
        kind: str,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult:
        """No confirm context for this short id (never issued, or lost to a restart)."""
        mapping = self._stores.lookup_by_short_id(short_id)
        signal_id, plan_id = (None, None) if mapping is None else mapping
        correlation = f"{self._profile.correlation_prefix}short:{short_id}"
        self._stores.record_journal(
            JournalEvent(
                journal_event_id=correlated_event_id(
                    prefix=self._profile.journal_prefix,
                    correlation_id=correlation,
                    event_type=self._profile.event_rejected,
                    entity_id=f"short:{short_id}",
                    step=f"press:{correlation_id}",
                ),
                occurred_at_utc=now_utc,
                event_type=self._profile.event_rejected,
                entity_type=self._profile.entity_type,
                entity_id=f"short:{short_id}",
                correlation_id=correlation,
                signal_id=signal_id,
                trade_plan_id=plan_id,
                payload_json=_payload(
                    {
                        "reason": REASON_NO_CONFIRM_CONTEXT,
                        "kind": kind,
                        "short_id": short_id,
                        "presented_user_id": None if from_user_id is None else str(from_user_id),
                        "mode": self._profile.mode_label,
                    }
                ),
            )
        )
        detail = REASON_NO_CONFIRM_CONTEXT
        self._store_result(
            ConfirmRecord(
                outcome=ConfirmOutcome.REJECTED_OTHER,
                detail=detail,
                confirm_requested_at_utc=None,
                plan_expiry_utc=None,
            )
        )
        return ConfirmResult(ConfirmOutcome.REJECTED_OTHER, False, detail, detail)

    # ---- the binding gate ------------------------------------------------ #

    def _binding_gate(
        self, entry: ConfirmEntry, now_utc: datetime
    ) -> tuple[RejectionReason, ConfirmOutcome] | None:
        """Re-run the approval binding gate at CONFIRM, in the order of `src/approval/binding.py`.

        Chat was gated first (`_press_gate`). Then: plan expiry (inclusive, REV-12), plan hash,
        version and parameter set and the identity of the approved row. The confirm token itself
        is the in-memory capability looked up by short id, so there is no token-hash gate here.
        """
        plan, signal, approval = entry.plan, entry.signal, entry.approval
        if now_utc >= plan.expiry_utc:
            return RejectionReason.APPROVAL_EXPIRED, ConfirmOutcome.REJECTED_PLAN_EXPIRED
        stored = self._stores.lookup_by_token_hash(approval.approval_token_hash)
        if stored is None or stored.status != ApprovalResult.APPROVED:
            return RejectionReason.INVALIDATED, ConfirmOutcome.REJECTED_OTHER
        if stored.request_hash != plan.plan_hash or entry.approval.request_hash != plan.plan_hash:
            return RejectionReason.STALE_SETUP, ConfirmOutcome.REJECTED_OTHER
        if (
            plan.signal_id != signal.signal_id
            or stored.trade_plan_id != plan.trade_plan_id
            or stored.signal_id != signal.signal_id
        ):
            return RejectionReason.INVALIDATED, ConfirmOutcome.REJECTED_OTHER
        return None

    def _run_recheck(self, entry: ConfirmEntry, now_utc: datetime) -> str | None:
        """The injected re-check, then the reservation capacity check; fail closed on any error."""
        try:
            if self._recheck is not None:
                reason = self._recheck(entry.signal, entry.plan, now_utc)
                if reason is not None:
                    return reason.value if isinstance(reason, RejectionReason) else reason
            if self._reservations is not None:
                return self._reservations.check(entry.signal, entry.plan, now_utc)
        except Exception as exc:  # noqa: BLE001 - fail closed: a broken re-check rejects
            log.warning(
                f"{self._profile.log_namespace}.recheck_failed", error_class=type(exc).__name__
            )
            return REASON_RECHECK_ERROR
        return None

    # ---- CONFIRM / CANCEL ------------------------------------------------ #

    def handle_confirm(
        self,
        *,
        short_id: str,
        chat_id: int,
        authorized_chat_id: int,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult:
        """A CNF: press. CONFIRMED only for the approving user, once, inside the TTL, after the
        binding gate and the injected re-check; every other outcome is journaled and simulates
        nothing. A repeat press replays the existing outcome.

        With a `ReservationPort` (plan 16-23, Q-C `reserve-at-confirm`) the whole press runs in
        its serialized section: re-check and capacity check (before the journal write), the
        *_CONFIRMED write, then the reservation. A failed check or write reserves nothing.
        """
        _require_utc(now_utc, "now_utc")
        return self._in_section(
            lambda: self._handle_confirm_locked(
                short_id=short_id,
                chat_id=chat_id,
                authorized_chat_id=authorized_chat_id,
                from_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
            ),
            correlation_id,
        )

    def _in_section(self, body: Callable[[], _T], press_correlation: str | None = None) -> _T:
        """Run `body` under the book lock and, with a reservation port, its serialized section.

        Every path that can finish a CONFIRM (a press, an adopted stored CONFIRM) runs here, so
        `on_confirmed` is called once for each of them AFTER the section and the book lock are
        released (B2-CR-01): the hook may take the coordinator lock without waiting on the ledger
        lock. One sweep can adopt several CONFIRMs (P16R-02, D-16): the hook receives each, in
        order, with its own approval, plan and confirm instant. A hook that raises does not skip
        the later ones; the first hook exception is re-raised after all ran. When the body itself
        raised after finishing some CONFIRMs (they are journaled and their state is CONFIRMED, so
        no later sweep would adopt them again), their hooks still run and the body error wins.

        `press_correlation` is the id of the CONFIRM or CANCEL press being handled; the reply
        record is stored under it. A sweep passes None and records nothing. A body that raises
        leaves no record behind (B2-WR-03).
        """
        body_error: BaseException | None = None
        result: _T | None = None
        with self._lock:
            self._deferred_confirmed = []
            self._press_correlation = press_correlation
            try:
                if self._reservations is None:
                    result = body()
                else:
                    with self._reservations.section():
                        result = body()
            except BaseException as exc:
                if press_correlation is not None:
                    self._results.pop(press_correlation, None)
                body_error = exc
            finally:
                self._press_correlation = None
            deferred, self._deferred_confirmed = self._deferred_confirmed, []
        hook_error = self._run_confirmed_hooks(deferred, suppress=body_error is not None)
        if body_error is not None:
            raise body_error
        if hook_error is not None:
            raise hook_error
        return cast(_T, result)

    def _run_confirmed_hooks(
        self, deferred: list[tuple[Approval, TradePlan, datetime]], *, suppress: bool
    ) -> Exception | None:
        """Call `on_confirmed` for each finished CONFIRM, in order; return the first error.

        Every item is attempted even after one raised. With `suppress` (the body already raised)
        the errors are only logged, because the body error is the one the caller must see.
        """
        hook = self._on_confirmed
        if hook is None:
            return None
        first_error: Exception | None = None
        for item in deferred:
            try:
                hook(*item)
            except Exception as exc:  # noqa: BLE001 - every adopted CONFIRM gets its call
                log.warning(
                    f"{self._profile.log_namespace}.on_confirmed_failed",
                    error_class=type(exc).__name__,
                )
                with self._lock:
                    for entry in self._entries.values():
                        if entry.approval.approval_id == item[0].approval_id:
                            entry.hand_off_failed = True
                if first_error is None:
                    first_error = exc
        return None if suppress else first_error

    def _reconcile_unknown(self, entry: ConfirmEntry) -> ConfirmResult | None:
        """Settle an earlier *_CONFIRMED append of unknown outcome against the journal.

        None when the entry has no unknown append, or the journal shows none committed (the flag
        is cleared and the caller goes on). A committed one is adopted as the CONFIRM and its
        result returned: the caller must not write a second terminal event (plan 16-58, B2-WR-02).
        A journal that cannot be read raises (fail closed: nothing is written).
        """
        if not entry.confirm_append_unknown:
            return None
        stored = self._stored_confirmed(entry)
        if stored is not None:
            return self._adopt_stored_confirm(entry, stored)
        entry.confirm_append_unknown = False
        return None

    def _handle_confirm_locked(
        self,
        *,
        short_id: str,
        chat_id: int,
        authorized_chat_id: int,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult:
        entry = self._entries.get(short_id)
        if entry is None:
            return self._reject_unknown(
                short_id,
                kind="CONFIRM",
                from_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
            )
        refused = self._press_gate(
            entry,
            kind="CONFIRM",
            chat_id=chat_id,
            authorized_chat_id=authorized_chat_id,
            from_user_id=from_user_id,
            now_utc=now_utc,
            correlation_id=correlation_id,
        )
        if refused is not None:
            return refused
        if entry.state is ConfirmState.CONFIRMED and entry.reservation_pending:
            # Journaled CONFIRMED but the reservation step did not complete: finish it (idempotent).
            return self._finish_confirm(entry, entry.decided_at_utc or now_utc)
        if entry.state is not ConfirmState.PENDING:
            return self._replay(
                entry,
                kind="CONFIRM",
                from_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
            )
        # An earlier *_CONFIRMED append has an unknown outcome: the journal decides. A
        # journal that cannot be read raises here (fail closed: nothing reserved).
        adopted = self._reconcile_unknown(entry)
        if adopted is not None:
            return adopted
        if now_utc >= entry.expires_at_utc:  # boundary inclusive, as binding.py
            return self._expire_ttl(entry, now_utc)
        rejection = self._binding_gate(entry, now_utc)
        if rejection is not None:
            reason, outcome = rejection
            return self._reject_terminal(entry, reason.value, outcome, now_utc)
        recheck_reason = self._run_recheck(entry, now_utc)
        if recheck_reason is not None:
            return self._reject_terminal(
                entry, recheck_reason, ConfirmOutcome.REJECTED_OTHER, now_utc
            )
        extra: dict[str, Any] = {
            "plan_hash": entry.plan.plan_hash,
            "ttl_seconds": entry.ttl_seconds,
        }
        if self._reservations is not None:
            try:
                extra.update(
                    self._reservations.confirm_payload(
                        approval=entry.approval,
                        signal=entry.signal,
                        plan=entry.plan,
                        short_id=entry.short_id,
                        confirmed_at_utc=now_utc,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - fail closed: no reservation facts, no confirm
                log.warning(
                    f"{self._profile.log_namespace}.reservation_payload_failed",
                    error_class=type(exc).__name__,
                )
                return self._reject_terminal(
                    entry, REASON_RECHECK_ERROR, ConfirmOutcome.REJECTED_OTHER, now_utc
                )
        try:
            self._terminate(
                entry,
                state=ConfirmState.CONFIRMED,
                outcome=ConfirmOutcome.CONFIRMED,
                reason="CONFIRMED",
                now_utc=now_utc,
                event_type=self._profile.event_confirmed,
                extra=extra,
            )
        except Exception:
            # The append raised: it may or may not have committed. Reconcile against the journal
            # before anything else; an event that did commit is the authoritative CONFIRM.
            entry.confirm_append_unknown = True
            stored = self._stored_confirmed(entry)  # raises when unreadable: fail closed
            if stored is None:
                entry.confirm_append_unknown = False
                raise
            return self._adopt_stored_confirm(entry, stored)
        return self._finish_confirm(entry, now_utc)

    def _stored_confirmed(self, entry: ConfirmEntry) -> JournalEvent | None:
        """The *_CONFIRMED event of this approval in the journal, or None when absent."""
        for event in self._stores.journal_for_correlation(
            self._profile.correlation(entry.approval.approval_id)
        ):
            if event.event_type == self._profile.event_confirmed:
                return event
        return None

    def _adopt_stored_confirm(self, entry: ConfirmEntry, stored: JournalEvent) -> ConfirmResult:
        """Treat a committed *_CONFIRMED as the CONFIRM; reuse its stored confirm instant."""
        loaded = json.loads(stored.payload_json) if stored.payload_json else {}
        raw = loaded.get("confirmed_at_utc") if isinstance(loaded, dict) else None
        if not isinstance(raw, str):
            raise ValueError("the stored *_CONFIRMED has no confirmed_at_utc")
        confirmed_at = datetime.fromisoformat(raw)
        entry.state = ConfirmState.CONFIRMED
        entry.outcome = ConfirmOutcome.CONFIRMED
        entry.reason = "CONFIRMED"
        entry.decided_at_utc = confirmed_at
        entry.confirm_append_unknown = False
        return self._finish_confirm(entry, confirmed_at)

    def _finish_confirm(self, entry: ConfirmEntry, confirmed_at_utc: datetime) -> ConfirmResult:
        """After *_CONFIRMED is journaled: reserve the exposure, then notify `on_confirmed`.

        A reservation that cannot be made (never expected inside the serialized section) is
        journaled by the reservation layer as refused and the press is reported as NOT confirmed,
        so a refused plan never reaches `on_confirmed`. A reserve that raises leaves
        `reservation_pending` set; a repeated press retries it.
        """
        result = self._result(entry, ConfirmOutcome.CONFIRMED, "CONFIRMED", replayed=False)
        if self._reservations is not None:
            entry.reservation_pending = True
            outcome = self._reservations.reserve(
                approval=entry.approval,
                signal=entry.signal,
                plan=entry.plan,
                short_id=entry.short_id,
                confirmed_at_utc=confirmed_at_utc,
            )
            entry.reservation_pending = False
            if not outcome.reserved:
                return self._result(
                    entry, ConfirmOutcome.REJECTED_OTHER, outcome.reason_code, replayed=False
                )
        # State is already CONFIRMED, so a replay can never append this a second time. The hook
        # runs in `_in_section` once the section is released (B2-CR-01).
        self._deferred_confirmed.append((entry.approval, entry.plan, confirmed_at_utc))
        return result

    def _reject_terminal(
        self, entry: ConfirmEntry, reason: str, outcome: ConfirmOutcome, now_utc: datetime
    ) -> ConfirmResult:
        self._terminate(
            entry,
            state=ConfirmState.EXPIRED,
            outcome=outcome,
            reason=reason,
            now_utc=now_utc,
            event_type=self._profile.event_expired,
            extra={"rejected_at_confirm": True},
        )
        return self._result(entry, outcome, reason, replayed=False)

    def handle_cancel(
        self,
        *,
        short_id: str,
        chat_id: int,
        authorized_chat_id: int,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult:
        """A CXL: press. Journals *_CONFIRM_CANCELLED; nothing is simulated. A cancel after
        a decision cannot flip it: it replays the existing outcome. A CONFIRM append of unknown
        outcome is reconciled against the journal first, so a committed CONFIRM is never followed
        by a second terminal event (B2-WR-02).
        """
        _require_utc(now_utc, "now_utc")
        return self._in_section(
            lambda: self._handle_cancel_locked(
                short_id=short_id,
                chat_id=chat_id,
                authorized_chat_id=authorized_chat_id,
                from_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
            ),
            correlation_id,
        )

    def _handle_cancel_locked(
        self,
        *,
        short_id: str,
        chat_id: int,
        authorized_chat_id: int,
        from_user_id: int | None,
        now_utc: datetime,
        correlation_id: str,
    ) -> ConfirmResult:
        entry = self._entries.get(short_id)
        if entry is None:
            return self._reject_unknown(
                short_id,
                kind="CANCEL",
                from_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
            )
        refused = self._press_gate(
            entry,
            kind="CANCEL",
            chat_id=chat_id,
            authorized_chat_id=authorized_chat_id,
            from_user_id=from_user_id,
            now_utc=now_utc,
            correlation_id=correlation_id,
        )
        if refused is not None:
            return refused
        if entry.state is ConfirmState.PENDING:
            self._reconcile_unknown(entry)  # adopting a committed CONFIRM makes it non-PENDING
        if entry.state is not ConfirmState.PENDING:
            return self._replay(
                entry,
                kind="CANCEL",
                from_user_id=from_user_id,
                now_utc=now_utc,
                correlation_id=correlation_id,
            )
        if now_utc >= entry.expires_at_utc:
            return self._expire_ttl(entry, now_utc)
        self._terminate(
            entry,
            state=ConfirmState.CANCELLED,
            outcome=ConfirmOutcome.CANCELLED,
            reason="CANCELLED",
            now_utc=now_utc,
            event_type=self._profile.event_cancelled,
        )
        return self._result(entry, ConfirmOutcome.CANCELLED, "CANCELLED", replayed=False)

    # ---- sweeps ---------------------------------------------------------- #

    def expire_if_due(self, short_id: str, now_utc: datetime) -> bool:
        """Expire one outstanding confirm whose TTL has run out. True when it was expired.

        An unknown CONFIRM append is reconciled against the journal first (B2-WR-02): a committed
        CONFIRM is adopted and nothing is expired; an unreadable journal raises.
        """
        return self._in_section(lambda: self._expire_if_due_locked(short_id, now_utc))

    def _expire_if_due_locked(self, short_id: str, now_utc: datetime) -> bool:
        entry = self._entries.get(short_id)
        if (
            entry is None
            or entry.state is not ConfirmState.PENDING
            or now_utc < entry.expires_at_utc
        ):
            return False
        if self._reconcile_unknown(entry) is not None:
            return False
        self._expire_ttl(entry, now_utc)
        return True

    def expire_due(self, now_utc: datetime) -> list[str]:
        """Journal EXPIRED for every confirm past its TTL, and repair stranded approvals.

        Returns the approval ids expired by this call, sorted. A second call writes nothing.
        Two sources: tokens held in memory (reason CONFIRM_TTL_ELAPSED), and APPROVED approvals
        older than the TTL that have no terminal confirm event and no token here: with no
        *_CONFIRM_* event at all the card was never delivered (CARD_DELIVERY_FAILED), with
        an ISSUED event only the token is gone (RUNTIME_RESTART).
        """
        _require_utc(now_utc, "now_utc")
        expired = self._in_section(lambda: self._expire_held_locked(now_utc))
        expired.extend(self._sweep_orphans(now_utc, require_age=True))
        return sorted(expired)

    def _expire_held_locked(self, now_utc: datetime) -> list[str]:
        expired: list[str] = []
        for entry in sorted(self._entries.values(), key=lambda e: e.approval.approval_id):
            if entry.state is ConfirmState.PENDING and now_utc >= entry.expires_at_utc:
                if self._reconcile_unknown(entry) is not None:
                    continue  # the unknown append had committed: the CONFIRM stands (B2-WR-02)
                self._expire_ttl(entry, now_utc)
                expired.append(entry.approval.approval_id)
        return expired

    def expire_on_restart(self, now_utc: datetime) -> list[str]:
        """Expire every outstanding confirm of the previous process (raw tokens are gone).

        Call once at startup with a fresh book. APPROVED approvals without a terminal confirm
        event are expired at once: ISSUED ones with reason RUNTIME_RESTART, those that never
        got a card with CARD_DELIVERY_FAILED. Idempotent.
        """
        _require_utc(now_utc, "now_utc")
        return sorted(self._sweep_orphans(now_utc, require_age=False))

    def _sweep_orphans(self, now_utc: datetime, *, require_age: bool) -> list[str]:
        swept: list[str] = []
        held = {e.approval.approval_id for e in self._entries.values()}
        for approval in sorted(self._stores.list_approved_approvals(), key=lambda a: a.approval_id):
            if approval.approval_id in held:
                continue  # its token is in memory: the TTL path owns it
            events = self._stores.journal_for_correlation(
                self._profile.correlation(approval.approval_id)
            )
            types = {e.event_type for e in events}
            if types & set(self._profile.terminal_events):
                continue
            issued = [e for e in events if e.event_type == self._profile.event_issued]
            if issued:
                reason = REASON_RUNTIME_RESTART
                base = issued[0].occurred_at_utc
            else:
                reason = REASON_CARD_DELIVERY_FAILED
                base = approval.acted_at_utc or approval.requested_at_utc
            if require_age and now_utc < base + timedelta(seconds=self._ttl):
                continue
            self._stores.record_journal(
                self._event(
                    event_type=self._profile.event_expired,
                    step="terminal",
                    approval=approval,
                    signal_id=approval.signal_id,
                    trade_plan_id=approval.trade_plan_id,
                    now_utc=now_utc,
                    payload={
                        "approval_id": approval.approval_id,
                        "reason": reason,
                        "expired_at_utc": now_utc.isoformat(),
                        "swept": True,
                    },
                )
            )
            swept.append(approval.approval_id)
        return swept


def assert_no_stranded_approvals(
    stores: ConfirmStores,
    now_utc: datetime,
    *,
    profile: ConfirmProfile,
    ttl_seconds: int = CONFIRM_TTL_SECONDS_DEFAULT,
) -> None:
    """Raise `StrandedApprovals` unless every approved plan past the TTL has one terminal event.

    The invariant of T-16-112: after APPROVE a plan can never sit with no confirm card and no
    journaled outcome. Each APPROVED approval older than `ttl_seconds` must have exactly one
    *_CONFIRMED, *_CONFIRM_CANCELLED or *_CONFIRM_EXPIRED event (any reason).
    """
    _require_utc(now_utc, "now_utc")
    stranded: list[str] = []
    for approval in sorted(stores.list_approved_approvals(), key=lambda a: a.approval_id):
        acted = approval.acted_at_utc or approval.requested_at_utc
        if now_utc < acted + timedelta(seconds=ttl_seconds):
            continue
        events = stores.journal_for_correlation(profile.correlation(approval.approval_id))
        terminal = [e for e in events if e.event_type in profile.terminal_events]
        if len(terminal) != 1:
            stranded.append(f"{approval.approval_id} ({len(terminal)} terminal events)")
    if stranded:
        raise StrandedApprovals(
            "approved plans without exactly one confirm outcome: " + ", ".join(stranded)
        )


__all__ = [
    "CONFIRM_TTL_SECONDS_DEFAULT",
    "DEMO_CONFIRM_PROFILE",
    "LIVE_CONFIRM_PROFILE",
    "REASON_CARD_DELIVERY_FAILED",
    "REASON_CHAT_MISMATCH",
    "REASON_CONFIRM_ALREADY_EXPIRED",
    "REASON_CONFIRM_TTL_ELAPSED",
    "REASON_NO_CONFIRM_CONTEXT",
    "REASON_RECHECK_ERROR",
    "REASON_RUNTIME_RESTART",
    "REASON_USER_ID_UNAVAILABLE",
    "REASON_USER_MISMATCH",
    "SHADOW_CONFIRM_PROFILE",
    "CardRenderer",
    "ConfirmBook",
    "ConfirmEntry",
    "ConfirmOutcome",
    "ConfirmProfile",
    "ConfirmRecord",
    "ConfirmResult",
    "ConfirmState",
    "ConfirmStores",
    "DeliveryFailure",
    "MarkPriceFn",
    "OnConfirmedFn",
    "RecheckFn",
    "ReservationPort",
    "ReserveOutcome",
    "StrandedApprovals",
    "assert_no_stranded_approvals",
]
