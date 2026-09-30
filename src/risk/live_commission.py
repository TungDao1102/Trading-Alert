"""Live commission-rate resolver (Phase 12, plan 12-05; D-10, D-11, D-12).

Live sizing must never use a modeled fee that is below the account's real
tier (F-962) and must not let the BNB fee discount shrink the modeled cost
(F-031). `resolve_live_cost_rates` combines the versioned parameter
`CostRates` with a fresh account commission as a per-side maximum:

    fee_rate_entry = fee_rate_exit = max(parameter_fee, account_taker_rate)

Entry and the protective stop exit are both taker fills (D036), so the
account TAKER rate applies to both sides. The MAKER rate is validated and
carried on `AccountCommission` but is not used for sizing. The BNB discount
is deliberately ignored (F-031): the account rate is read as reported and
nothing reduces it.

`fee_source` on the returned `CostRates` is `ACCOUNT_MAX`. It means the
live `max()` rule was applied; the parameter rate may still be the larger
side (a real account rate of 0 is legitimate and is floored by the
parameter rate).

Fail closed (D-11): a missing, wrong-symbol, stale (age greater than the
TTL) or future-dated account commission returns a NO_TRADE result with
`UNCERTAIN_ACCOUNT_STATE` and NO rates. It never yields a zero fee and
never silently substitutes the parameter rates. The freshness rule is the
same as `check_portfolio`: age greater than the TTL, or negative age, is
stale; age exactly equal to the TTL passes.

The caller supplies `now_utc` and the TTL (from the registry key
`commission_rate_ttl_seconds`); this module reads no clock. Backtest and
paper keep the versioned parameter fees (D-12) and never call this code.
Runtime refresh wiring is Phase 24 (D-13).

Purity (Phase 5 D-05): stdlib, Decimal, `src.risk.cost_rates` and
`src.domain.enums` only; no SDK, no backtest, no adapters, no floats.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from src.domain.enums import RejectionReason

from .cost_rates import FEE_SOURCE_ACCOUNT_MAX, MAX_RATE, CostRates

_OK = "OK"
_REASON_CODES = frozenset({r.value for r in RejectionReason})
_UNCERTAIN = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive and non-UTC datetimes."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def _require_rate(value: object, field_name: str) -> Decimal:
    """Reject non-Decimal values and rates outside [0, MAX_RATE]."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite() or value < Decimal("0") or value > MAX_RATE:
        raise ValueError(f"{field_name} must be in [0, {MAX_RATE}], got {value}")
    return value


@dataclass(frozen=True)
class AccountCommission:
    """One symbol's account commission rates as reported by Binance.

    `observed_at_utc` is stamped by the caller when the adapter read
    returned; the adapter itself takes no clock. A real rate of 0 is valid.
    """

    symbol: str
    maker_rate: Decimal
    taker_rate: Decimal
    observed_at_utc: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or self.symbol == "":
            raise ValueError("symbol must be a non-empty string")
        _require_rate(self.maker_rate, "maker_rate")
        _require_rate(self.taker_rate, "taker_rate")
        _require_utc_aware(self.observed_at_utc, "observed_at_utc")


@dataclass(frozen=True)
class LiveCostRatesResult:
    """Outcome of live rate resolution: rates, or a NO_TRADE reason.

    `rates is None` requires a `reason_code` from the RejectionReason
    vocabulary other than OK; `rates` present requires `reason_code == OK`.
    """

    rates: CostRates | None
    reason_code: str

    def __post_init__(self) -> None:
        if self.rates is None:
            if self.reason_code == _OK or self.reason_code not in _REASON_CODES:
                raise ValueError(
                    "a result without rates needs a non-OK RejectionReason code, "
                    f"got {self.reason_code!r}"
                )
        elif self.reason_code != _OK:
            raise ValueError(
                f"a result with rates requires reason_code OK, got {self.reason_code!r}"
            )

    @property
    def is_no_trade(self) -> bool:
        return self.rates is None


def resolve_live_cost_rates(
    *,
    parameter_rates: CostRates,
    account_commission: AccountCommission | None,
    candidate_symbol: str,
    now_utc: datetime,
    ttl: timedelta,
) -> LiveCostRatesResult:
    """Return per-side max(parameter, account taker) rates, or fail closed.

    Args:
        parameter_rates: the versioned registry rates (fees and slippage).
        account_commission: the account's commission for the candidate
            symbol, or None when unknown.
        candidate_symbol: the symbol being sized.
        now_utc: the injected UTC-aware clock reading.
        ttl: the maximum acceptable age (`commission_rate_ttl_seconds`).

    Raises:
        ValueError: `now_utc` is naive or non-UTC, or `ttl` is not positive
            (programming errors, not market states).
    """
    _require_utc_aware(now_utc, "now_utc")
    if ttl <= timedelta(0):
        raise ValueError(f"ttl must be positive, got {ttl}")

    if account_commission is None:
        return LiveCostRatesResult(rates=None, reason_code=_UNCERTAIN)
    if account_commission.symbol != candidate_symbol:
        return LiveCostRatesResult(rates=None, reason_code=_UNCERTAIN)
    age = now_utc - account_commission.observed_at_utc
    if age > ttl or age < timedelta(0):
        return LiveCostRatesResult(rates=None, reason_code=_UNCERTAIN)

    taker = account_commission.taker_rate
    fee_entry = max(parameter_rates.fee_rate_entry, taker)
    fee_exit = max(parameter_rates.fee_rate_exit, taker)
    rates = CostRates(
        fee_rate_entry=fee_entry,
        entry_slippage_rate=parameter_rates.entry_slippage_rate,
        fee_rate_exit=fee_exit,
        exit_slippage_rate=parameter_rates.exit_slippage_rate,
        fee_source=FEE_SOURCE_ACCOUNT_MAX,
        account_symbol=account_commission.symbol,
        commission_observed_at_utc=account_commission.observed_at_utc,
        commission_expires_at_utc=account_commission.observed_at_utc + ttl,
    )
    return LiveCostRatesResult(rates=rates, reason_code=_OK)


__all__ = [
    "AccountCommission",
    "LiveCostRatesResult",
    "resolve_live_cost_rates",
]
