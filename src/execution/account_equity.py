"""Live account-equity source (Phase 21, plan 21-07; F-012, D-01, D-02, D-03, D-05, D-20).

``LiveEquitySource`` is the one object that turns the adapter's account reads into a fresh
``AccountEquityReading``, keeps it only until the stream says the account changed, and resolves
it to ``AccountState`` or NO_TRADE with the owner's age bound (``account.max_equity_age_ms``).

* D-01, REST is the truth, the stream is only the freshness trigger. ``ACCOUNT_UPDATE`` carries
  wallet deltas and per-position unrealized PnL, never the margin balance, so equity cannot be
  rebuilt from the stream: any account event or stream gap calls ``invalidate`` and the next
  equity is a REST read again. Frames sent during a gap are not replayed (Demo, observed).
* D-02, the fields: ``totalMarginBalance``, ``totalWalletBalance`` and ``totalUnrealizedProfit``
  of GET /fapi/v3/account, the quote-asset row of the same response, the quote-asset ``balance``
  of GET /fapi/v3/balance and ``multiAssetsMargin`` of GET /fapi/v1/accountConfig. The quote
  asset is a constructor argument. Phase 22 (plan 22-10): the same three reads also carry
  ``availableBalance``, ``totalOpenOrderInitialMargin``, the quote row's ``availableBalance`` and
  ``dualSidePosition`` (same accountConfig read, no second position-mode call) for the margin
  check, ``check_margin``, under the same stamp and the same age bound. The cross-checks
  themselves live in ``src.risk.live_equity`` and ``src.risk.margin_check``.
* Read order of ``refresh``: accountConfig, account, balance. Each is read once and never
  retried, slept on or replaced by an older reading (D-20): any exception (a refused gate, an
  SDK error, a malformed field) leaves no reading and keeps only the exception type name.
* Freshness contract (D-03). ``refresh`` stamps ``observed_at_utc`` with the injected clock
  BEFORE the first request, so the age is only over-estimated. Every caller therefore reads the
  injected clock for ``now_utc`` AFTER ``refresh`` returns: a ``now_utc`` captured before the
  call can precede the stamp (a negative age, stale by design) and in any case ignores the time
  the reads took.
* The source reads no wall clock (only the injected one), imports no SDK and no adapter module
  (it talks to the adapter through ``AccountReadPort``), and logs nothing: no balance, no
  account identifier and no exception message is ever kept.

Not wired in a running process until Phase 24. Figures quoted in tests are demo-observed, not
mainnet.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from src.execution.execution_limits import ExecutionLimits, ExecutionLimitsNotConfigured
from src.risk.live_equity import (
    AccountEquityReading,
    EquityCheck,
    LiveEquityResult,
    check_equity_reading,
    resolve_live_equity,
)
from src.risk.margin_check import AvailableMarginCheck, check_available_margin

_AGE_KEY = "account.max_equity_age_ms"
_ONE_MS = timedelta(milliseconds=1)

INVALIDATION_REASONS = frozenset({"ACCOUNT_UPDATE", "STREAM_GAP"})


class AccountReadPort(Protocol):
    """The three adapter reads the source calls (all async, REST, read-only)."""

    async def account_information_snapshot(self) -> Any: ...

    async def account_balances_snapshot(self) -> Any: ...

    async def account_config_snapshot(self) -> Any: ...


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    return value


def _quote_row(rows: Any, quote_asset: str, *, rows_name: str) -> Any | None:
    """The one row whose ``asset`` is the quote asset; None when absent; two rows raise."""
    matches = [row for row in rows if row.asset == quote_asset]
    if len(matches) > 1:
        raise ValueError(f"{rows_name} holds more than one quote-asset row")
    return matches[0] if matches else None


def equity_reading_from_snapshots(
    *,
    information: Any,
    balances: Any,
    config: Any,
    quote_asset: str,
    observed_at_utc: datetime,
) -> AccountEquityReading:
    """Map the three adapter snapshots to one ``AccountEquityReading`` (D-02).

    The rows of the quote asset are picked by name; any other asset is ignored. A missing quote
    row maps to None, which the resolver then refuses. A wrong type raises ``TypeError`` and a
    duplicated quote row ``ValueError``; ``LiveEquitySource.refresh`` treats both as a failed
    read.
    """
    if not isinstance(quote_asset, str) or quote_asset.strip() == "":
        raise ValueError("quote_asset must be a non-empty string")
    asset_row = _quote_row(information.assets, quote_asset, rows_name="account assets")
    balance_row = _quote_row(balances, quote_asset, rows_name="account balances")
    multi_assets = config.multi_assets_margin
    if not isinstance(multi_assets, bool):
        raise TypeError("multi_assets_margin must be bool")
    dual_side = config.dual_side_position
    if not isinstance(dual_side, bool):
        raise TypeError("dual_side_position must be bool")
    return AccountEquityReading(
        total_margin_balance=_decimal(information.total_margin_balance, "total_margin_balance"),
        total_wallet_balance=_decimal(information.total_wallet_balance, "total_wallet_balance"),
        total_unrealized_profit=_decimal(
            information.total_unrealized_profit, "total_unrealized_profit"
        ),
        quote_asset_margin_balance=(
            None if asset_row is None else _decimal(asset_row.margin_balance, "margin_balance")
        ),
        balance_endpoint_wallet=(
            None if balance_row is None else _decimal(balance_row.balance, "balance")
        ),
        multi_assets_margin=multi_assets,
        available_balance=_decimal(information.available_balance, "available_balance"),
        total_open_order_initial_margin=_decimal(
            information.total_open_order_initial_margin, "total_open_order_initial_margin"
        ),
        quote_asset_available_balance=(
            None
            if asset_row is None
            else _decimal(asset_row.available_balance, "quote_asset_available_balance")
        ),
        dual_side_position=dual_side,
        observed_at_utc=observed_at_utc,
    )


class LiveEquitySource:
    """Fresh REST equity or NO_TRADE; see the module docstring for the contract."""

    def __init__(
        self,
        *,
        adapter: AccountReadPort,
        clock: Callable[[], datetime],
        limits: ExecutionLimits,
        quote_asset: str,
    ) -> None:
        age_ms = limits.account_max_equity_age_ms
        if age_ms is None:
            raise ExecutionLimitsNotConfigured((_AGE_KEY,))
        if not isinstance(quote_asset, str) or quote_asset.strip() == "":
            raise ValueError("quote_asset must be a non-empty string")
        self._adapter = adapter
        self._clock = clock
        self._quote_asset = quote_asset
        self._max_age = age_ms * _ONE_MS
        self._reading: AccountEquityReading | None = None
        self._generation = 0
        self._last_error_type: str | None = None
        self._last_invalidation_reason: str | None = None

    @property
    def last_error_type(self) -> str | None:
        """Type name of the last failed refresh; None after a success. Never a message."""
        return self._last_error_type

    @property
    def last_invalidation_reason(self) -> str | None:
        """The reason of the last ``invalidate`` call, or None."""
        return self._last_invalidation_reason

    async def refresh(self) -> None:
        """Read the account from REST once; on any failure keep no reading (D-01, D-20).

        The reading is stamped with the injected clock BEFORE the first request. Callers take
        ``now_utc`` AFTER this returns (a ``now_utc`` read before it can precede the stamp,
        a negative age that is stale by design, D-03). A failure drops the previous reading too
        (no stale fallback) and records only the exception type name. An ``invalidate`` that
        arrives while the reads are in flight discards their result: it may predate the account
        change.
        """
        generation = self._generation
        self._reading = None
        try:
            observed = self._clock()
            config = await self._adapter.account_config_snapshot()
            information = await self._adapter.account_information_snapshot()
            balances = await self._adapter.account_balances_snapshot()
            reading = equity_reading_from_snapshots(
                information=information,
                balances=balances,
                config=config,
                quote_asset=self._quote_asset,
                observed_at_utc=observed,
            )
        except Exception as exc:  # noqa: BLE001 - any failed read is "no equity", fail closed
            self._last_error_type = type(exc).__name__
            return
        self._last_error_type = None
        if generation == self._generation:
            self._reading = reading

    def invalidate(self, *, reason: str) -> None:
        """Drop the reading: an account event or a stream gap makes it untrustworthy (D-01).

        Phase 24 wires the user-data router's account sink and the supervisor's after-gap flag
        to this. Any ``ACCOUNT_UPDATE`` reason, FUNDING_FEE included, invalidates, because the
        event carries no margin balance. Equity is NO_TRADE until the next successful
        ``refresh``.
        """
        if reason not in INVALIDATION_REASONS:
            raise ValueError("invalidation reason must be ACCOUNT_UPDATE or STREAM_GAP")
        self._generation += 1
        self._reading = None
        self._last_invalidation_reason = reason

    def check(self, *, now_utc: datetime) -> EquityCheck:
        """The checked equity of the last reading, or NO_TRADE (UNCERTAIN_ACCOUNT_STATE).

        ``now_utc`` must be read from the injected clock AFTER ``refresh`` returned (a value
        captured before the call can precede the stamp: a negative age, stale by design, D-03).
        """
        return check_equity_reading(reading=self._reading, now_utc=now_utc, max_age=self._max_age)

    def check_margin(self, *, now_utc: datetime) -> AvailableMarginCheck:
        """The free margin, the equity and the account mode of the last reading, or a refusal.

        The same reading, stamp and age bound as ``check``/``resolve`` (never an older reading,
        Pitfall 6): ``check_available_margin`` applied to it. ``now_utc`` must be read from the
        injected clock AFTER ``refresh`` returned (D-03).
        """
        return check_available_margin(reading=self._reading, now_utc=now_utc, max_age=self._max_age)

    def resolve(self, *, risk_rate: Decimal, now_utc: datetime) -> LiveEquityResult:
        """``AccountState(equity, risk_rate)`` from the last reading, or NO_TRADE.

        ``now_utc`` must be read from the injected clock AFTER ``refresh`` returned (a value
        captured before the call can precede the stamp: a negative age, stale by design, D-03).
        """
        return resolve_live_equity(
            reading=self._reading,
            risk_rate=risk_rate,
            now_utc=now_utc,
            max_age=self._max_age,
        )


__all__ = [
    "INVALIDATION_REASONS",
    "AccountReadPort",
    "LiveEquitySource",
    "equity_reading_from_snapshots",
]
