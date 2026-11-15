"""Pure live daily-loss rules (Phase 21, plan 21-05; D033, D-06 to D-14, F-013, F-963).

Definition (D033, the same as `src/backtest/ledger.py::daily_loss_quote`): over one UTC
day, `loss = max(0, -(sum of realized PnL - commissions + funding))`. The thresholds are
the registry rates times the equity at the UTC day start; the state comes from the shared
`derive_daily_state` (inclusive boundaries). Phase 21 only supplies the live input (rows
reported by Binance) and the sticky wrapper; persistence, the REST and stream feeds and
the DAILY_STOP actions are other plans.

Component conventions. Every amount is signed and in the quote asset:

- `FILL_PNL`: the fill's realized PnL (ORDER_TRADE_UPDATE `rp`, userTrades `realizedPnl`).
- `FILL_COMMISSION`: MINUS the fill's commission (`n`, userTrades `commission`); a
  negative commission (a rebate) gives a positive amount.
- `FUNDING`: the FUNDING_FEE income amount as reported (negative when paid).

`source_key` is "<symbol>:<exchange order id>:<trade id>" for fills (the stream `i`/`t`
and REST `orderId`/`id` share one key space) and "<symbol>:<tranId>" for funding.
`FUNDING` only comes from `REST_INCOME`; fills never do.

realizedPnl semantics (A9): on Demo, `realizedPnl` excludes commission. That is
demo-observed, not mainnet. Commission is therefore added explicitly as its own
component; if mainnet `realizedPnl` already includes it, adding it again can only
OVERSTATE the loss (conservative). `LIVE_NET_PNL_SEMANTICS_VERIFIED` is not touched here
and live R stays INCOMPLETE until Phase 24 verifies it on mainnet (G2-042, D-10).

Two sources can report the same fill or funding row (stream and REST). The row counts
once, at the MOST ADVERSE amount (the smallest signed amount); the key is reported as
divergent. No tolerance number exists (D-09).

A component whose asset is not the quote asset makes the day loss unknown: no conversion
rate source exists (D-11, F-031). Unknown means NO_TRADE with UNCERTAIN_ACCOUNT_STATE,
never a zero and never a default.

Funding (O-2 is the owner's choice, recorded by plan 21-01; this module chooses no
default): both `FundingPolicy` members are built and every caller passes one.
`TRADES_WITH_UNVERIFIED_FUNDING` counts the funding rows it has and labels the result
`FUNDING_SOURCE_UNVERIFIED`; `REQUIRE_VERIFIED_FUNDING_SOURCE` makes the loss unknown
while `FUNDING_SOURCE_VERIFIED` is False (income rows were never observed on Demo). A
failed funding read, or trade sources that are not complete, make the loss unknown
under either policy.

This module reads no clock (every time is injected), builds no float and imports only
the stdlib, `src.domain`, `src.core` and `src.risk`. It persists and alerts nothing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from src.core._decimal import _add, _sub
from src.domain.enums import DailyState, RejectionReason
from src.risk.portfolio import (
    _extract_thresholds,
    derive_daily_state,
    resolve_absolute_thresholds,
)

_ZERO = Decimal("0")
_OK = "OK"
_UNCERTAIN = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
_REASON_CODES = frozenset(r.value for r in RejectionReason)
_MAX_KEY_LENGTH = 128

# Whether Binance FUNDING_FEE income rows were observed. Demo returned zero income rows in
# four tries (19-OWNER-GAPS R-A9), so this stays False until that is observed (Phase 24/26).
FUNDING_SOURCE_VERIFIED: bool = False
FUNDING_LABEL_UNVERIFIED = "FUNDING_SOURCE_UNVERIFIED"
FUNDING_LABEL_VERIFIED = "FUNDING_SOURCE_VERIFIED"

BLOCKED_DAY_STATE_MISSING = "DAY_STATE_MISSING"
BLOCKED_DAY_STATE_UNREADABLE = "DAY_STATE_UNREADABLE"
BLOCKED_DAY_BASE_UNAVAILABLE = "DAY_BASE_UNAVAILABLE"
BLOCKED_DAILY_LOSS_UNKNOWN = "DAILY_LOSS_UNKNOWN"
BLOCKED_DAY_THRESHOLDS_INVALID = "DAY_THRESHOLDS_INVALID"


class ComponentKind(Enum):
    FILL_PNL = "FILL_PNL"
    FILL_COMMISSION = "FILL_COMMISSION"
    FUNDING = "FUNDING"


class ComponentSource(Enum):
    USER_DATA_EVENT = "USER_DATA_EVENT"
    REST_USER_TRADES = "REST_USER_TRADES"
    REST_INCOME = "REST_INCOME"


class FundingPolicy(Enum):
    TRADES_WITH_UNVERIFIED_FUNDING = "TRADES_WITH_UNVERIFIED_FUNDING"
    REQUIRE_VERIFIED_FUNDING_SOURCE = "REQUIRE_VERIFIED_FUNDING_SOURCE"


def _require_utc_aware(value: object, field_name: str) -> datetime:
    """Reject non-datetimes, naive and non-UTC datetimes."""
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")
    return value


def _require_day(value: object, field_name: str) -> date:
    """A UTC calendar day is a `date` (a `datetime` is refused: it is not a day)."""
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{field_name} must be a date, got {type(value).__name__}")
    return value


def _require_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite, got {value}")
    return value


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def utc_day_of(at_utc: datetime) -> date:
    """The UTC day containing `at_utc`; 00:00:00.000 UTC belongs to the NEW day."""
    return _require_utc_aware(at_utc, "at_utc").date()


def utc_day_start(utc_day: date) -> datetime:
    """00:00:00.000 UTC of `utc_day`."""
    return datetime.combine(_require_day(utc_day, "utc_day"), time(0, 0), tzinfo=UTC)


def _next_day_start(utc_day: date) -> datetime:
    return utc_day_start(utc_day) + timedelta(days=1)


def _inside_day(utc_day: date, at_utc: datetime) -> bool:
    return utc_day_start(utc_day) <= at_utc < _next_day_start(utc_day)


@dataclass(frozen=True, kw_only=True)
class LossComponent:
    """One signed daily-loss component as reported by Binance (see the module docstring)."""

    kind: ComponentKind
    source: ComponentSource
    source_key: str
    amount: Decimal
    asset: str
    event_time_utc: datetime
    utc_day: date

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ComponentKind):
            raise TypeError(f"kind must be ComponentKind, got {type(self.kind).__name__}")
        if not isinstance(self.source, ComponentSource):
            raise TypeError(f"source must be ComponentSource, got {type(self.source).__name__}")
        _require_text(self.source_key, "source_key")
        if len(self.source_key) > _MAX_KEY_LENGTH:
            raise ValueError(f"source_key must be at most {_MAX_KEY_LENGTH} characters")
        _require_decimal(self.amount, "amount")
        _require_text(self.asset, "asset")
        _require_utc_aware(self.event_time_utc, "event_time_utc")
        _require_day(self.utc_day, "utc_day")
        if self.kind is ComponentKind.FUNDING:
            if self.source is not ComponentSource.REST_INCOME:
                raise ValueError("a FUNDING component only comes from REST_INCOME")
        elif self.source is ComponentSource.REST_INCOME:
            raise ValueError("a fill component never comes from REST_INCOME")
        if self.utc_day != utc_day_of(self.event_time_utc):
            raise ValueError(
                f"utc_day {self.utc_day} differs from the UTC day of event_time_utc "
                f"{self.event_time_utc.isoformat()}"
            )


@dataclass(frozen=True, kw_only=True)
class DayRiskState:
    """The persisted state of one UTC day (the day-start base and the latch/alert marks).

    `equity_at_day_start` is the threshold base for the whole day (D-06). The marks are
    UTC-aware and inside the day window: a latch never crosses a day boundary (D-14).
    """

    utc_day: date
    equity_at_day_start: Decimal
    base_observed_at_utc: datetime
    stop_latched_at_utc: datetime | None = None
    warning_alerted_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        _require_day(self.utc_day, "utc_day")
        _require_decimal(self.equity_at_day_start, "equity_at_day_start")
        if self.equity_at_day_start <= _ZERO:
            raise ValueError(f"equity_at_day_start must be > 0, got {self.equity_at_day_start}")
        for name in ("base_observed_at_utc", "stop_latched_at_utc", "warning_alerted_at_utc"):
            value = getattr(self, name)
            if value is None and name != "base_observed_at_utc":
                continue
            _require_utc_aware(value, name)
            if not _inside_day(self.utc_day, value):
                raise ValueError(f"{name} {value.isoformat()} is outside UTC day {self.utc_day}")


@dataclass(frozen=True, kw_only=True)
class DailyLossResult:
    """The folded day loss, or why it is unknown.

    `loss_quote` present requires `reason_code == "OK"` and no blocked reason; absent
    requires a non-OK RejectionReason code and a blocked reason.

    `net_pnl_upper_quote` (WR-06) is the day's signed result (positive = gain) taking the MOST
    FAVORABLE amount per fill where two sources disagree, the opposite of `loss_quote`, which
    takes the most adverse. A day base derived as "equity now minus the day's net result" is
    smallest (conservative) with the favorable figure. None when the loss is unknown.
    """

    loss_quote: Decimal | None
    reason_code: str
    blocked_reason: str | None
    divergent_keys: tuple[str, ...]
    funding_label: str
    net_pnl_upper_quote: Decimal | None = None

    def __post_init__(self) -> None:
        if self.loss_quote is None:
            if self.reason_code == _OK or self.reason_code not in _REASON_CODES:
                raise ValueError(
                    f"an unknown loss needs a non-OK RejectionReason code, got {self.reason_code!r}"
                )
            if self.blocked_reason is None:
                raise ValueError("an unknown loss needs a blocked_reason")
            if self.net_pnl_upper_quote is not None:
                raise ValueError("an unknown loss carries no net result")
        else:
            _require_decimal(self.loss_quote, "loss_quote")
            if self.loss_quote < _ZERO:
                raise ValueError(f"loss_quote must be >= 0, got {self.loss_quote}")
            if self.reason_code != _OK or self.blocked_reason is not None:
                raise ValueError("a known loss requires reason_code OK and no blocked_reason")
            if self.net_pnl_upper_quote is not None:
                _require_decimal(self.net_pnl_upper_quote, "net_pnl_upper_quote")
        if tuple(sorted(self.divergent_keys)) != self.divergent_keys:
            raise ValueError("divergent_keys must be sorted")
        if self.funding_label not in (FUNDING_LABEL_UNVERIFIED, FUNDING_LABEL_VERIFIED):
            raise ValueError(f"unknown funding_label {self.funding_label!r}")


def _funding_label() -> str:
    return FUNDING_LABEL_VERIFIED if FUNDING_SOURCE_VERIFIED else FUNDING_LABEL_UNVERIFIED


def _unknown_loss() -> DailyLossResult:
    return DailyLossResult(
        loss_quote=None,
        reason_code=_UNCERTAIN,
        blocked_reason=BLOCKED_DAILY_LOSS_UNKNOWN,
        divergent_keys=(),
        funding_label=_funding_label(),
    )


def fold_daily_loss(
    *,
    components: Iterable[LossComponent],
    utc_day: date,
    quote_asset: str,
    trades_complete: bool,
    funding_read_ok: bool,
    funding_policy: FundingPolicy,
) -> DailyLossResult:
    """Fold the day's components into the D033 loss, or an unknown (fail-closed) result.

    Order: day check, completeness flags, funding policy, duplicate check per
    (kind, source, key), asset check, group by (kind, source_key) taking the smallest
    signed amount across sources, sum, `loss = max(0, -sum)`.

    Raises:
        TypeError: an argument has the wrong type.
        ValueError: a component belongs to another UTC day, or the same
            (kind, source, key) appears with two different amounts.
    """
    _require_day(utc_day, "utc_day")
    _require_text(quote_asset, "quote_asset")
    if not isinstance(funding_policy, FundingPolicy):
        raise TypeError(
            f"funding_policy must be FundingPolicy, got {type(funding_policy).__name__}"
        )
    for name, flag in (("trades_complete", trades_complete), ("funding_read_ok", funding_read_ok)):
        if not isinstance(flag, bool):
            raise TypeError(f"{name} must be bool, got {type(flag).__name__}")
    rows = tuple(components)
    for row in rows:
        if not isinstance(row, LossComponent):
            raise TypeError(f"components must be LossComponent, got {type(row).__name__}")
        if row.utc_day != utc_day:
            raise ValueError(f"component utc_day {row.utc_day} is not the folded day {utc_day}")

    if not trades_complete or not funding_read_ok:
        return _unknown_loss()
    if funding_policy is FundingPolicy.REQUIRE_VERIFIED_FUNDING_SOURCE and (
        not FUNDING_SOURCE_VERIFIED
    ):
        return _unknown_loss()

    seen: dict[tuple[ComponentKind, ComponentSource, str], Decimal] = {}
    for row in rows:
        identity = (row.kind, row.source, row.source_key)
        previous = seen.get(identity)
        if previous is None:
            seen[identity] = row.amount
        elif previous != row.amount:
            raise ValueError(
                f"duplicate {row.kind.value} component {row.source_key!r} from "
                f"{row.source.value} with different amounts {previous} and {row.amount}"
            )

    if any(row.asset != quote_asset for row in rows):
        return _unknown_loss()

    grouped: dict[tuple[ComponentKind, str], list[Decimal]] = {}
    for (kind, _source, key), amount in seen.items():
        grouped.setdefault((kind, key), []).append(amount)

    divergent: set[str] = set()
    total = _ZERO
    favorable_total = _ZERO
    for kind, key in sorted(grouped, key=lambda item: (item[0].value, item[1])):
        amounts = grouped[(kind, key)]
        if len({amount.normalize() for amount in amounts}) > 1:
            divergent.add(key)
        total = _add(total, min(amounts))
        favorable_total = _add(favorable_total, max(amounts))

    loss = _sub(_ZERO, total)
    return DailyLossResult(
        loss_quote=loss if loss > _ZERO else _ZERO,
        reason_code=_OK,
        blocked_reason=None,
        divergent_keys=tuple(sorted(divergent)),
        funding_label=_funding_label(),
        net_pnl_upper_quote=favorable_total,
    )


def day_thresholds(*, parameter_set: dict[str, Any], day: DayRiskState) -> dict[str, Any] | None:
    """Absolute thresholds against the persisted day-start base ONLY (D-06, Pitfall 8).

    There is no current-equity argument: an intraday equity change cannot move them.
    Returns None when the parameter set is malformed (the caller fails closed).
    """
    try:
        return resolve_absolute_thresholds(
            parameter_set=parameter_set, equity=day.equity_at_day_start
        )
    except (KeyError, TypeError, ValueError):
        return None


class DayOpenAction(Enum):
    """What the service does about the persisted state of today's UTC day (D-07, D-08)."""

    USE_STORED = "USE_STORED"
    OPEN_FROM_FRESH_BASE = "OPEN_FROM_FRESH_BASE"
    BLOCKED_MISSING_STATE = "BLOCKED_MISSING_STATE"
    BLOCKED_STORE_UNREADABLE = "BLOCKED_STORE_UNREADABLE"


_BLOCKED_REASONS = frozenset(
    {
        BLOCKED_DAY_STATE_MISSING,
        BLOCKED_DAY_STATE_UNREADABLE,
        BLOCKED_DAY_BASE_UNAVAILABLE,
        BLOCKED_DAILY_LOSS_UNKNOWN,
        BLOCKED_DAY_THRESHOLDS_INVALID,
    }
)
_ALERTABLE = (DailyState.WARNING, DailyState.DAILY_STOP)


@dataclass(frozen=True, kw_only=True)
class DayStateVerdict:
    """The day's state for the gates: a DailyState, or why none can be given.

    `state` None means NO_TRADE: `reason_code` is UNCERTAIN_ACCOUNT_STATE and
    `blocked_reason` names the cause. DAILY_STOP carries DAILY_STOP_BLOCK. `latch_now` asks
    the service to persist the latch (only with a newly derived DAILY_STOP). `alerts_due`
    lists the alerts not yet sent; this module sends nothing.
    """

    utc_day: date
    state: DailyState | None
    reason_code: str
    blocked_reason: str | None
    loss_quote: Decimal | None
    latch_now: bool
    alerts_due: tuple[DailyState, ...]

    def __post_init__(self) -> None:
        _require_day(self.utc_day, "utc_day")
        if self.state is None:
            if self.reason_code != _UNCERTAIN or self.blocked_reason not in _BLOCKED_REASONS:
                raise ValueError(
                    "a verdict without a state needs UNCERTAIN_ACCOUNT_STATE and a known "
                    "blocked_reason"
                )
            if self.latch_now or self.alerts_due:
                raise ValueError("a verdict without a state asks for no latch and no alert")
        else:
            if not isinstance(self.state, DailyState):
                raise TypeError(f"state must be DailyState, got {type(self.state).__name__}")
            if self.blocked_reason is not None:
                raise ValueError("a verdict with a state has no blocked_reason")
            expected = (
                RejectionReason.DAILY_STOP_BLOCK.value
                if self.state is DailyState.DAILY_STOP
                else _OK
            )
            if self.reason_code != expected:
                raise ValueError(
                    f"state {self.state.value} requires reason_code {expected}, "
                    f"got {self.reason_code!r}"
                )
            if self.latch_now and self.state is not DailyState.DAILY_STOP:
                raise ValueError("latch_now is only valid with DAILY_STOP")
        if self.loss_quote is not None:
            _require_decimal(self.loss_quote, "loss_quote")
        if not isinstance(self.latch_now, bool):
            raise TypeError("latch_now must be bool")
        for alert in self.alerts_due:
            if alert not in _ALERTABLE:
                raise ValueError(f"alerts_due may hold WARNING or DAILY_STOP only, got {alert!r}")


def blocked_verdict(*, utc_day: date, blocked_reason: str) -> DayStateVerdict:
    """NO_TRADE verdict (UNCERTAIN_ACCOUNT_STATE) for one of the BLOCKED_* causes."""
    if blocked_reason not in _BLOCKED_REASONS:
        raise ValueError(f"unknown blocked_reason {blocked_reason!r}")
    return DayStateVerdict(
        utc_day=utc_day,
        state=None,
        reason_code=_UNCERTAIN,
        blocked_reason=blocked_reason,
        loss_quote=None,
        latch_now=False,
        alerts_due=(),
    )


def _thresholds_usable(thresholds: dict[str, Any] | None) -> bool:
    """True when the resolved set can derive a state and warning <= stop.

    `derive_daily_state` answers NORMAL for a malformed set, so a malformed set must be
    stopped here. Inverted warning/stop thresholds are not rejected by the shared rule
    (ROADMAP 999.3, Phase 05 IN-03, trigger: Phase 21 daily-loss work); the live path
    rejects them here and leaves `src/risk/portfolio.py` unchanged.
    """
    if thresholds is None:
        return False
    extracted = _extract_thresholds(thresholds)
    if extracted is None:
        return False
    warning, stop = extracted[3], extracted[4]
    if not (warning.is_finite() and stop.is_finite()):
        return False
    return warning <= stop


def evaluate_day_state(
    *, day: DayRiskState, loss: DailyLossResult, parameter_set: dict[str, Any]
) -> DayStateVerdict:
    """The day's verdict: sticky latch first, then thresholds, then the loss (D-06, D-14).

    A held latch is DAILY_STOP for the rest of the UTC day whatever the loss does. A newly
    derived DAILY_STOP asks for the latch (`latch_now`). A jump straight to DAILY_STOP alerts
    DAILY_STOP only. A WARNING alerts once (`warning_alerted_at_utc` is None).
    """
    if day.stop_latched_at_utc is not None:
        return DayStateVerdict(
            utc_day=day.utc_day,
            state=DailyState.DAILY_STOP,
            reason_code=RejectionReason.DAILY_STOP_BLOCK.value,
            blocked_reason=None,
            loss_quote=loss.loss_quote,
            latch_now=False,
            alerts_due=(),
        )
    thresholds = day_thresholds(parameter_set=parameter_set, day=day)
    if not _thresholds_usable(thresholds):
        return blocked_verdict(utc_day=day.utc_day, blocked_reason=BLOCKED_DAY_THRESHOLDS_INVALID)
    if loss.loss_quote is None:
        return blocked_verdict(utc_day=day.utc_day, blocked_reason=BLOCKED_DAILY_LOSS_UNKNOWN)
    assert thresholds is not None  # narrowed by _thresholds_usable
    state = derive_daily_state(daily_loss_quote=loss.loss_quote, parameter_set=thresholds)
    if state is DailyState.DAILY_STOP:
        return DayStateVerdict(
            utc_day=day.utc_day,
            state=state,
            reason_code=RejectionReason.DAILY_STOP_BLOCK.value,
            blocked_reason=None,
            loss_quote=loss.loss_quote,
            latch_now=True,
            alerts_due=(DailyState.DAILY_STOP,),
        )
    alerts: tuple[DailyState, ...] = ()
    if state is DailyState.WARNING and day.warning_alerted_at_utc is None:
        alerts = (DailyState.WARNING,)
    return DayStateVerdict(
        utc_day=day.utc_day,
        state=state,
        reason_code=_OK,
        blocked_reason=None,
        loss_quote=loss.loss_quote,
        latch_now=False,
        alerts_due=alerts,
    )


def day_open_action(
    *,
    today: DayRiskState | None,
    earlier_day_present: bool,
    exposure: bool | None,
    store_readable: bool,
) -> DayOpenAction:
    """What to do about today's persisted day state (D-07, D-08).

    D-07: a missing day state is never a fresh day while exposure exists or is unknown
    (`exposure` None means unknown). D-08: the rollover from a persisted earlier day opens
    the new day from a fresh REST base. `earlier_day_present` is True when ANY stored day lies
    before today, not only yesterday: after an outage of two or more UTC days an earlier row
    still proves the store is intact (WR-08); only a store that never held a day blocks. The
    operator acknowledgement path for a missing state with exposure is not built; it is an
    owner item (research Open Question 5).
    """
    if not store_readable:
        return DayOpenAction.BLOCKED_STORE_UNREADABLE
    if today is not None:
        return DayOpenAction.USE_STORED
    if earlier_day_present:
        return DayOpenAction.OPEN_FROM_FRESH_BASE
    if exposure is False:
        return DayOpenAction.OPEN_FROM_FRESH_BASE
    return DayOpenAction.BLOCKED_MISSING_STATE


def base_is_inside_day(*, utc_day: date, observed_at_utc: datetime) -> bool:
    """True when the base was observed inside the half-open UTC day window."""
    return _inside_day(utc_day, _require_utc_aware(observed_at_utc, "observed_at_utc"))
