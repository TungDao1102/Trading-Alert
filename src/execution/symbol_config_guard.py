"""Symbol configuration guard (Phase 22, plan 22-11; D-01, D-02, D-03, D-05, D-06, criterion 1).

Nothing in the system had ever read or set the configuration of a symbol: the Demo account
showed BTCUSDT as CROSSED x20 from the account defaults (2026-10-04, demo-observed, not
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


def _matches(snapshot: Any, target_leverage: int) -> bool:
    """True when the snapshot shows ISOLATED, the target leverage and no auto top-up.

    Exact comparison: the margin type must be the str "ISOLATED", the leverage an int (not a
    bool) equal to the target and ``is_auto_add_margin`` the bool False.
    """
    margin_type = snapshot.margin_type
    leverage = snapshot.leverage
    return (
        isinstance(margin_type, str)
        and margin_type == TARGET_MARGIN_TYPE
        and type(leverage) is int
        and leverage == target_leverage
        and snapshot.is_auto_add_margin is False
    )


class SymbolConfigGuard:
    """Set and verify ISOLATED plus the target leverage on one symbol; see the module docstring."""

    def __init__(self, *, adapter: SymbolConfigPort, target_leverage: int) -> None:
        if isinstance(target_leverage, bool) or not isinstance(target_leverage, int):
            raise TypeError("target_leverage must be an int")
        if target_leverage < 1:
            raise ValueError("target_leverage must be at least 1")
        self._adapter = adapter
        self._target_leverage = target_leverage

    async def ensure(self, *, symbol: str, symbol_is_flat: bool) -> ConfigGuardResult:
        """Make ``symbol`` ISOLATED at the target leverage (verified by a read), or refuse."""
        first = await self._adapter.symbol_config_snapshot(symbol=symbol)
        previous_margin_type = first.margin_type
        previous_leverage = first.leverage
        if _matches(first, self._target_leverage):
            return ConfigGuardResult(
                ok=True,
                reason_code=_OK,
                alert_reason=None,
                margin_type=first.margin_type,
                leverage=first.leverage,
                max_notional_value=first.max_notional_value,
                changed=False,
                previous_margin_type=previous_margin_type,
                previous_leverage=previous_leverage,
                posts_sent=0,
            )
        posts_sent = 0
        if first.margin_type != TARGET_MARGIN_TYPE:
            await self._adapter.change_margin_type(symbol=symbol, margin_type=TARGET_MARGIN_TYPE)
            posts_sent += 1
        if first.leverage != self._target_leverage:
            await self._adapter.change_initial_leverage(
                symbol=symbol, leverage=self._target_leverage
            )
            posts_sent += 1
        last = await self._adapter.symbol_config_snapshot(symbol=symbol)
        return ConfigGuardResult(
            ok=_matches(last, self._target_leverage),
            reason_code=_OK,
            alert_reason=None,
            margin_type=last.margin_type,
            leverage=last.leverage,
            max_notional_value=last.max_notional_value,
            changed=(last.margin_type, last.leverage) != (previous_margin_type, previous_leverage),
            previous_margin_type=previous_margin_type,
            previous_leverage=previous_leverage,
            posts_sent=posts_sent,
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
