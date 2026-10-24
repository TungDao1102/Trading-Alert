"""Live account-equity resolver (Phase 21, plan 21-04; F-012, D-02, D-03, D-04, D-05).

Live sizing must use the account equity Binance reports, never a caller constant.
`resolve_live_equity` turns one fresh, consistent, single-asset account reading into the
pure core input `AccountState(equity, risk_rate)` and refuses every other case.

Field choice (D-02, O-5). The reading carries `totalMarginBalance` of GET /fapi/v3/account:
wallet balance plus unrealized PnL, and in single-asset mode it is denominated in the quote asset
only (SDK 17.4.0 response model). The equity USED for sizing is the SMALLER of `totalWalletBalance`
and `totalMarginBalance` (owner decision of 2026-10-24, DECISIONS D086, O-5): an unrealized profit
never raises the position size, an unrealized loss lowers it. On the Demo account the recorded
payload shows the margin balance equal to `totalWalletBalance + totalUnrealizedProfit`, to the
`marginBalance` of the quote-asset row of the same response, and (as wallet) to the quote-asset
row of GET /fapi/v3/balance. That is demo-observed, not mainnet. `availableBalance` is never the
equity: since Phase 22 (plan 22-10) the reading carries it, the open-order margin total and the
position mode for the margin check of `src.risk.margin_check`, but `check_equity_reading` and
`equity_basis` do not look at them.

Fail closed (D-03, D-04). A missing reading, a stale reading (age greater than `max_age`), a
future-dated reading (negative age), `multiAssetsMargin` true (equity would mix assets; owner
question O-3, default refuse), a `totalMarginBalance` that differs from
`totalWalletBalance + totalUnrealizedProfit`, a missing or differing quote-asset row, a
missing or differing balance-endpoint wallet, and equity that is zero or negative all give a
NO_TRADE result with `UNCERTAIN_ACCOUNT_STATE` and no `AccountState`. The identities are exact
Decimal equality with no tolerance. The freshness rule is the `check_portfolio` predicate:
age greater than the limit, or negative age, is stale; age exactly equal to the limit passes.

The equity basis lives in `equity_basis` alone; the owner chose the smaller of the wallet balance
and the margin balance there (O-5, D086).

The caller supplies `now_utc` and `max_age`; this module reads no clock. The quote asset is a
parameter of the caller that builds the reading, so no asset name appears here. Paper and
backtest keep their own equity (Phase 12 D-12) and never call this code.

Purity (Phase 5 D-05): stdlib, Decimal, `src.domain.enums`, `src.core` and `src.risk` only;
no SDK, no adapters, no floats.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from src.core._decimal import _add
from src.core.types import AccountState
from src.domain.enums import RejectionReason

_OK = "OK"
_REASON_CODES = frozenset({r.value for r in RejectionReason})
_UNCERTAIN = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value


def _require_utc_aware(value: object, field_name: str) -> None:
    """Reject non-datetime, naive and non-UTC values."""
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def _require_amount(value: object, field_name: str) -> None:
    """Reject non-Decimal (float, int, bool, str) and non-finite amounts."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite, got {value}")


@dataclass(frozen=True)
class AccountEquityReading:
    """One account reading as the adapter returned it, stamped by the caller.

    `total_margin_balance`, `total_wallet_balance` and `total_unrealized_profit` come from
    GET /fapi/v3/account. `quote_asset_margin_balance` is the `marginBalance` of the quote-asset
    row of the same response, None when the row is absent. `balance_endpoint_wallet` is the
    `balance` of the quote-asset row of GET /fapi/v3/balance, None when absent.
    `multi_assets_margin` and `dual_side_position` come from GET /fapi/v1/accountConfig (the
    same read, no second position-mode call). `available_balance` and
    `total_open_order_initial_margin` are the account-level free-margin figures of GET
    /fapi/v3/account (Phase 22, plan 22-10; never the equity); `quote_asset_available_balance`
    is the `availableBalance` of the quote-asset row of the same response, None when the row is
    absent. `observed_at_utc` is the injected clock read before the first request and stamps
    every field.
    """

    total_margin_balance: Decimal
    total_wallet_balance: Decimal
    total_unrealized_profit: Decimal
    quote_asset_margin_balance: Decimal | None
    balance_endpoint_wallet: Decimal | None
    multi_assets_margin: bool
    available_balance: Decimal
    total_open_order_initial_margin: Decimal
    quote_asset_available_balance: Decimal | None
    dual_side_position: bool
    observed_at_utc: datetime

    def __post_init__(self) -> None:
        _require_amount(self.total_margin_balance, "total_margin_balance")
        _require_amount(self.total_wallet_balance, "total_wallet_balance")
        _require_amount(self.total_unrealized_profit, "total_unrealized_profit")
        if self.quote_asset_margin_balance is not None:
            _require_amount(self.quote_asset_margin_balance, "quote_asset_margin_balance")
        if self.balance_endpoint_wallet is not None:
            _require_amount(self.balance_endpoint_wallet, "balance_endpoint_wallet")
        if not isinstance(self.multi_assets_margin, bool):
            raise TypeError(
                f"multi_assets_margin must be bool, got {type(self.multi_assets_margin).__name__}"
            )
        _require_amount(self.available_balance, "available_balance")
        _require_amount(self.total_open_order_initial_margin, "total_open_order_initial_margin")
        if self.quote_asset_available_balance is not None:
            _require_amount(self.quote_asset_available_balance, "quote_asset_available_balance")
        if not isinstance(self.dual_side_position, bool):
            raise TypeError(
                f"dual_side_position must be bool, got {type(self.dual_side_position).__name__}"
            )
        _require_utc_aware(self.observed_at_utc, "observed_at_utc")


@dataclass(frozen=True)
class EquityCheck:
    """Outcome of the reading checks: a positive equity, or a NO_TRADE reason.

    `equity is None` requires a non-OK `RejectionReason` code and no `observed_at_utc`;
    `equity` present requires `reason_code == OK` and an `observed_at_utc`.
    """

    equity: Decimal | None
    observed_at_utc: datetime | None
    reason_code: str

    def __post_init__(self) -> None:
        if self.equity is None:
            if self.observed_at_utc is not None:
                raise ValueError("a check without equity must not carry observed_at_utc")
            if self.reason_code == _OK or self.reason_code not in _REASON_CODES:
                raise ValueError(
                    "a check without equity needs a non-OK RejectionReason code, "
                    f"got {self.reason_code!r}"
                )
        else:
            _require_amount(self.equity, "equity")
            if self.observed_at_utc is None:
                raise ValueError("a check with equity requires observed_at_utc")
            if self.reason_code != _OK:
                raise ValueError(
                    f"a check with equity requires reason_code OK, got {self.reason_code!r}"
                )


@dataclass(frozen=True)
class LiveEquityResult:
    """Outcome of live equity resolution: an `AccountState`, or a NO_TRADE reason.

    `account_state is None` requires a non-OK `RejectionReason` code and no equity;
    `account_state` present requires `reason_code == OK` and its equity.
    """

    account_state: AccountState | None
    reason_code: str
    equity: Decimal | None
    observed_at_utc: datetime | None

    def __post_init__(self) -> None:
        if self.account_state is None:
            if self.equity is not None or self.observed_at_utc is not None:
                raise ValueError("a result without an account state must not carry equity")
            if self.reason_code == _OK or self.reason_code not in _REASON_CODES:
                raise ValueError(
                    "a result without an account state needs a non-OK RejectionReason code, "
                    f"got {self.reason_code!r}"
                )
        else:
            if self.reason_code != _OK:
                raise ValueError(
                    f"a result with an account state requires reason_code OK, "
                    f"got {self.reason_code!r}"
                )
            if self.equity is None or self.equity != self.account_state.equity:
                raise ValueError("a result's equity must equal its account state's equity")
            if self.observed_at_utc is None:
                raise ValueError("a result with an account state requires observed_at_utc")

    @property
    def is_no_trade(self) -> bool:
        return self.account_state is None

    @property
    def equity_for_snapshot(self) -> Decimal | None:
        """The equity for `build_plan_constraint_snapshot(equity_used=...)`; None on NO_TRADE."""
        return self.equity if self.account_state is not None else None


def equity_basis(reading: AccountEquityReading) -> Decimal:
    """The equity used for sizing: the smaller of `totalWalletBalance` and `totalMarginBalance`.

    The one place the basis is chosen (owner decision O-5 of 2026-10-24, DECISIONS D086). Since
    the margin balance is the wallet balance plus the unrealized PnL (the reading is refused
    unless that identity holds), a positive unrealized PnL leaves the wallet balance as the
    basis, so an open profit never raises the position size, and a negative unrealized PnL lowers
    it to the margin balance.
    """
    return min(reading.total_wallet_balance, reading.total_margin_balance)


def _no_equity() -> EquityCheck:
    return EquityCheck(equity=None, observed_at_utc=None, reason_code=_UNCERTAIN)


def check_equity_reading(
    *,
    reading: AccountEquityReading | None,
    now_utc: datetime,
    max_age: timedelta,
) -> EquityCheck:
    """Return the checked equity of a reading, or a fail-closed NO_TRADE check.

    Raises:
        ValueError: `now_utc` is naive or non-UTC, or `max_age` is not positive
            (programming errors, not market states).
    """
    _require_utc_aware(now_utc, "now_utc")
    if max_age <= timedelta(0):
        raise ValueError(f"max_age must be positive, got {max_age}")

    if reading is None:
        return _no_equity()
    age = now_utc - reading.observed_at_utc
    if age > max_age or age < timedelta(0):
        return _no_equity()
    if reading.multi_assets_margin:
        return _no_equity()
    if reading.total_margin_balance != _add(
        reading.total_wallet_balance, reading.total_unrealized_profit
    ):
        return _no_equity()
    if reading.quote_asset_margin_balance is None:
        return _no_equity()
    if reading.quote_asset_margin_balance != reading.total_margin_balance:
        return _no_equity()
    if reading.balance_endpoint_wallet is None:
        return _no_equity()
    if reading.balance_endpoint_wallet != reading.total_wallet_balance:
        return _no_equity()
    equity = equity_basis(reading)
    if equity <= Decimal("0"):
        return _no_equity()
    return EquityCheck(equity=equity, observed_at_utc=reading.observed_at_utc, reason_code=_OK)


def resolve_live_equity(
    *,
    reading: AccountEquityReading | None,
    risk_rate: Decimal,
    now_utc: datetime,
    max_age: timedelta,
) -> LiveEquityResult:
    """Return `AccountState(equity, risk_rate)` from a fresh reading, or fail closed.

    Raises:
        ValueError: `now_utc` is naive or non-UTC, `max_age` is not positive, or `risk_rate`
            is outside (0, 1] (programming errors, not market states).
    """
    if not isinstance(risk_rate, Decimal):
        raise TypeError(f"risk_rate must be Decimal, got {type(risk_rate).__name__}")
    if not (Decimal("0") < risk_rate <= Decimal("1")):
        raise ValueError(f"risk_rate {risk_rate} must be in (0, 1]")
    check = check_equity_reading(reading=reading, now_utc=now_utc, max_age=max_age)
    if check.equity is None:
        return LiveEquityResult(
            account_state=None, reason_code=check.reason_code, equity=None, observed_at_utc=None
        )
    return LiveEquityResult(
        account_state=AccountState(equity=check.equity, risk_rate=risk_rate),
        reason_code=_OK,
        equity=check.equity,
        observed_at_utc=check.observed_at_utc,
    )


__all__ = [
    "AccountEquityReading",
    "EquityCheck",
    "LiveEquityResult",
    "check_equity_reading",
    "equity_basis",
    "resolve_live_equity",
]
