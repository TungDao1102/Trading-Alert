"""Symbol configuration guard (Phase 22, plan 22-11; D-01, D-02, D-03, D-05, D-06, criterion 1).

Nothing in the system had ever read or set the configuration of a symbol: the Demo account
showed the BTC perpetual as CROSSED x20 from the account defaults (2026-10-04, demo-observed, not
mainnet). ``SymbolConfigGuard.ensure`` sets ISOLATED margin and the target leverage on one
symbol and VERIFIES it from the exchange before it reports success. The system never relies on
the account default.

Sequence of ``ensure(symbol, symbol_is_flat)``:

1. One ``symbolConfig`` read. When the margin type is ISOLATED, the leverage equals the target
   and ``isAutoAddMargin`` is false, NOTHING is sent (also when the symbol is not flat).
2. Otherwise, on a flat symbol only, ``change_margin_type`` (only when the type is wrong) and
   ``change_initial_leverage`` (only when the leverage is wrong), each AT MOST ONCE per run.
3. Exactly one more ``symbolConfig`` read. ONLY that last read decides.

The rules behind it:

* REST is the truth; the answer of a POST never decides (D-03). Requesting the type the symbol
  already has is an exchange ERROR (-4046), a change with open orders or a position is -4047 /
  -4048, a leverage above the bracket maximum is -4028, and a timeout leaves the outcome open.
  Every exception of a POST is swallowed (only the class name is kept, never the message) and
  the verification read decides.
* Single attempt (Q5, D080): a configuration POST is never retried and never slept on. A failed
  margin-type POST ends the mutations of the run: the leverage POST is not sent into an
  unexpected state. The next run starts from a fresh read.
* A symbol that holds a position, an open order or an open algo order whose configuration does
  not already match is refused (``MARGIN_CONFIG_CHANGE_REFUSED``, zero POSTs, D-04): the guard
  never cancels or closes anything to make room and never touches a position the owner opened
  by hand.
* ``isAutoAddMargin`` true is refused (``AUTO_ADD_MARGIN_ENABLED``) before any POST: there is no
  USD-M setter, and an automatic top-up would defeat the liquidation guard's input (D-06).
* A read that fails, or a last read that does not show the target, is NO_TRADE
  (``MARGIN_CONFIG_UNVERIFIED``) with an alert reason (D-03).
* The result carries the margin type, the leverage and ``maxNotionalValue`` as VERIFIED by the
  last read, plus ``changed``, the previous configuration and the number of POSTs sent. The
  previous configuration is evidence for the journal and is never auto-restored (Pitfall 9,
  OWNER-OPEN O-1).

``TARGET_LEVERAGE`` is the D035 cap held as ONE named constant. The constructor takes the target
as a required keyword with no default, so a lower target (OWNER-OPEN O-1) is a composition
decision and never a hidden one. The margin type is compared as the exact upper-case text the
Demo returned (2026-10-24, owner-run case); any other casing fails closed.

Purity: the module imports no adapter, store, SDK or sqlalchemy (it talks to the adapter through
``SymbolConfigPort``), reads no wall clock, logs nothing and holds no quote-asset literal. The
orchestrator (plan 22-14) sequences margin, liquidation, position mode and SAFE_MODE; this guard
decides none of them. Not wired in a running process until Phase 24.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Protocol

# D035: the leverage cap of the live pilot. A lower target is OWNER-OPEN O-1.
TARGET_LEVERAGE: Final[int] = 5
TARGET_MARGIN_TYPE: Final[str] = "ISOLATED"

MARGIN_CONFIG_UNVERIFIED: Final[str] = "MARGIN_CONFIG_UNVERIFIED"
MARGIN_CONFIG_CHANGE_REFUSED: Final[str] = "MARGIN_CONFIG_CHANGE_REFUSED"
AUTO_ADD_MARGIN_ENABLED: Final[str] = "AUTO_ADD_MARGIN_ENABLED"

_OK: Final[str] = "OK"


class SymbolConfigPort(Protocol):
    """The three adapter methods the guard calls (all async; the two POSTs mutate)."""

    async def symbol_config_snapshot(self, *, symbol: str) -> Any: ...

    async def change_margin_type(self, *, symbol: str, margin_type: str) -> None: ...

    async def change_initial_leverage(self, *, symbol: str, leverage: int) -> None: ...


@dataclass(frozen=True)
class ConfigGuardResult:
    """What ``ensure`` verified. ``margin_type``, ``leverage`` and ``max_notional_value`` come
    from the LAST read (None when nothing could be read); ``previous_*`` from the first.
    ``error_types`` holds exception CLASS NAMES only, never a message.
    """

    ok: bool
    reason_code: str
    alert_reason: str | None
    margin_type: str | None
    leverage: int | None
    max_notional_value: Decimal | None
    changed: bool
    previous_margin_type: str | None
    previous_leverage: int | None
    posts_sent: int
    error_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class _View:
    """The checked fields of one snapshot; a field of the wrong type reads as None."""

    margin_type: str | None
    leverage: int | None
    max_notional_value: Decimal | None
    auto_add: object


def _view(snapshot: Any) -> _View:
    margin_type = getattr(snapshot, "margin_type", None)
    leverage = getattr(snapshot, "leverage", None)
    max_notional = getattr(snapshot, "max_notional_value", None)
    return _View(
        margin_type=margin_type if isinstance(margin_type, str) else None,
        leverage=leverage if type(leverage) is int else None,
        max_notional_value=max_notional if isinstance(max_notional, Decimal) else None,
        auto_add=getattr(snapshot, "is_auto_add_margin", None),
    )


def _matches(view: _View, target_leverage: int) -> bool:
    """True when the view shows ISOLATED, the target leverage and no auto top-up.

    Exact comparison (the one decision shared by the first read, the verification and the
    idempotence): the margin type is the str "ISOLATED", the leverage an int (never a bool)
    equal to the target and ``is_auto_add_margin`` the bool False.
    """
    return (
        view.margin_type == TARGET_MARGIN_TYPE
        and view.leverage == target_leverage
        and view.auto_add is False
    )


class SymbolConfigGuard:
    """Set and verify ISOLATED plus the target leverage on one symbol; see the module docstring."""

    def __init__(self, *, adapter: SymbolConfigPort, target_leverage: int) -> None:
        if isinstance(target_leverage, bool) or not isinstance(target_leverage, int):
            raise TypeError("target_leverage must be an int")
        if target_leverage < 1:
            raise ValueError("target_leverage must be at least 1")
        if target_leverage > TARGET_LEVERAGE:
            raise ValueError("target_leverage must not exceed the D035 cap")
        self._adapter = adapter
        self._target_leverage = target_leverage

    @property
    def target_leverage(self) -> int:
        """The leverage ``ensure`` sets and verifies (never above the D035 cap)."""
        return self._target_leverage

    async def ensure(self, *, symbol: str, symbol_is_flat: bool) -> ConfigGuardResult:
        """Make ``symbol`` ISOLATED at the target leverage (verified by a read), or refuse.

        ``symbol_is_flat`` is the caller's fact: no position, no open order and no open algo
        order on the symbol. The guard changes nothing on a symbol that is not flat. Never
        raises for an exchange or gate failure (they are NO_TRADE results); a ``BaseException``
        such as a cancellation propagates.
        """
        if not isinstance(symbol, str) or symbol == "":
            raise ValueError("symbol must be non-empty text")
        if not isinstance(symbol_is_flat, bool):
            raise TypeError("symbol_is_flat must be a bool")
        target = self._target_leverage
        errors: list[str] = []

        try:
            first = _view(await self._adapter.symbol_config_snapshot(symbol=symbol))
        except Exception as exc:  # noqa: BLE001 - an unreadable configuration is NO_TRADE
            return _unverified(errors=[type(exc).__name__], posts_sent=0, first=None, last=None)

        if first.auto_add is True:
            return _refusal(AUTO_ADD_MARGIN_ENABLED, first=first, last=first, posts_sent=0)
        if first.auto_add is not False or first.margin_type is None or first.leverage is None:
            # A field of the wrong type is an unreadable configuration: nothing is sent.
            return _unverified(errors=errors, posts_sent=0, first=first, last=first)
        if _matches(first, target):
            return _result_ok(first=first, last=first, posts_sent=0)
        if not symbol_is_flat:
            return _refusal(MARGIN_CONFIG_CHANGE_REFUSED, first=first, last=first, posts_sent=0)

        posts_sent = 0
        margin_failed = False
        if first.margin_type != TARGET_MARGIN_TYPE:
            posts_sent += 1
            try:
                await self._adapter.change_margin_type(
                    symbol=symbol, margin_type=TARGET_MARGIN_TYPE
                )
            except Exception as exc:  # noqa: BLE001 - the answer of a POST never decides (D-03)
                errors.append(type(exc).__name__)
                margin_failed = True
        if first.leverage != target and not margin_failed:
            posts_sent += 1
            try:
                await self._adapter.change_initial_leverage(symbol=symbol, leverage=target)
            except Exception as exc:  # noqa: BLE001 - the answer of a POST never decides (D-03)
                errors.append(type(exc).__name__)

        try:
            last = _view(await self._adapter.symbol_config_snapshot(symbol=symbol))
        except Exception as exc:  # noqa: BLE001 - an unverifiable change is NO_TRADE
            errors.append(type(exc).__name__)
            return _unverified(errors=errors, posts_sent=posts_sent, first=first, last=None)

        if last.auto_add is True:
            return _refusal(
                AUTO_ADD_MARGIN_ENABLED,
                first=first,
                last=last,
                posts_sent=posts_sent,
                errors=errors,
            )
        if _matches(last, target):
            return _result_ok(first=first, last=last, posts_sent=posts_sent, errors=errors)
        return _unverified(errors=errors, posts_sent=posts_sent, first=first, last=last)


def _build(
    *,
    ok: bool,
    reason_code: str,
    alert_reason: str | None,
    first: _View | None,
    last: _View | None,
    posts_sent: int,
    errors: list[str],
) -> ConfigGuardResult:
    return ConfigGuardResult(
        ok=ok,
        reason_code=reason_code,
        alert_reason=alert_reason,
        margin_type=None if last is None else last.margin_type,
        leverage=None if last is None else last.leverage,
        max_notional_value=None if last is None else last.max_notional_value,
        changed=(
            ok
            and first is not None
            and last is not None
            and (last.margin_type, last.leverage) != (first.margin_type, first.leverage)
        ),
        previous_margin_type=None if first is None else first.margin_type,
        previous_leverage=None if first is None else first.leverage,
        posts_sent=posts_sent,
        error_types=tuple(errors),
    )


def _result_ok(
    *, first: _View, last: _View, posts_sent: int, errors: list[str] | None = None
) -> ConfigGuardResult:
    return _build(
        ok=True,
        reason_code=_OK,
        alert_reason=None,
        first=first,
        last=last,
        posts_sent=posts_sent,
        errors=errors or [],
    )


def _refusal(
    reason_code: str,
    *,
    first: _View,
    last: _View,
    posts_sent: int,
    errors: list[str] | None = None,
) -> ConfigGuardResult:
    """A plain NO_TRADE refusal: a normal outcome, so no alert reason (D-03)."""
    return _build(
        ok=False,
        reason_code=reason_code,
        alert_reason=None,
        first=first,
        last=last,
        posts_sent=posts_sent,
        errors=errors or [],
    )


def _unverified(
    *, errors: list[str], posts_sent: int, first: _View | None, last: _View | None
) -> ConfigGuardResult:
    """The exchange did not show the target after the allowed calls: NO_TRADE plus an alert."""
    return _build(
        ok=False,
        reason_code=MARGIN_CONFIG_UNVERIFIED,
        alert_reason=MARGIN_CONFIG_UNVERIFIED,
        first=first,
        last=last,
        posts_sent=posts_sent,
        errors=errors,
    )


__all__ = [
    "AUTO_ADD_MARGIN_ENABLED",
    "MARGIN_CONFIG_CHANGE_REFUSED",
    "MARGIN_CONFIG_UNVERIFIED",
    "TARGET_LEVERAGE",
    "TARGET_MARGIN_TYPE",
    "ConfigGuardResult",
    "SymbolConfigGuard",
    "SymbolConfigPort",
]
