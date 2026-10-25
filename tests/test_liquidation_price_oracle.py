"""Independent oracle for the isolated liquidation guard (Phase 22, plan 22-07; criterion 2).

The oracle shares no code path with `src.risk.liquidation`. It walks the mark price away from the
entry, one bracket segment at a time, in exact `Fraction` arithmetic, and stops at the first price
where the margin balance (`wallet + unrealised PnL`) no longer exceeds the maintenance margin
(`Q x p x m - cum`, the bracket chosen by the notional `Q x p`). The module under test instead
solves every bracket in closed form and filters by consistency. Agreement over seeded random cases
on the recorded Demo 10-tier table (demo-observed, not mainnet) is the evidence; every None must be
a refusal the oracle also reaches for a stated reason.
"""

from __future__ import annotations

import random
from decimal import Decimal
from fractions import Fraction

from src.risk.liquidation import (
    LEVERAGE_ABOVE_BRACKET,
    LIQUIDATION_INPUT_UNAVAILABLE,
    LIQUIDATION_OK,
    LIQUIDATION_TOO_CLOSE,
    NOTIONAL_ABOVE_MAX,
    Bracket,
    liquidation_price,
    liquidation_verdict,
)

from tests.support.phase22_fixtures import demo_brackets

CASES = 300
TOLERANCE = Fraction(1, 1_000_000)


def _margin_surplus(
    side: str, p: Fraction, ep: Fraction, q: Fraction, wallet: Fraction, t: Bracket
) -> Fraction:
    pnl = q * (p - ep) if side == "LONG" else q * (ep - p)
    return wallet + pnl - (q * p * Fraction(t.maint_margin_ratio) - Fraction(t.cum))


def _oracle(
    side: str, ep: Fraction, q: Fraction, lev: int, fee: Fraction, table: list[Bracket]
) -> tuple[str, Fraction | None]:
    """(reason, liquidation price) by walking the price from the entry, first crossing wins."""
    notional = q * ep
    if notional > Fraction(table[-1].notional_cap):
        return NOTIONAL_ABOVE_MAX, None
    allowed = min(
        t.initial_leverage
        for t in table
        if Fraction(t.notional_floor) <= notional <= Fraction(t.notional_cap)
    )
    if lev > allowed:
        return LEVERAGE_ABOVE_BRACKET, None
    wallet = q * ep / lev - fee * q * ep
    if wallet <= 0:
        return LIQUIDATION_INPUT_UNAVAILABLE, None
    segments = [(Fraction(t.notional_floor) / q, Fraction(t.notional_cap) / q, t) for t in table]
    if side == "LONG":
        for lo, hi, t in sorted(segments, key=lambda s: s[0], reverse=True):
            if lo > ep:
                continue
            top = min(hi, ep)
            assert _margin_surplus(side, top, ep, q, wallet, t) > 0
            if _margin_surplus(side, lo, ep, q, wallet, t) <= 0:
                root = (q * ep - wallet - Fraction(t.cum)) / (
                    q * (1 - Fraction(t.maint_margin_ratio))
                )
                return (LIQUIDATION_OK, root) if root > 0 else (LIQUIDATION_INPUT_UNAVAILABLE, None)
        return LIQUIDATION_INPUT_UNAVAILABLE, None  # never crossed above a price of zero
    for lo, hi, t in sorted(segments, key=lambda s: s[0]):
        if hi < ep:
            continue
        bottom = max(lo, ep)
        assert _margin_surplus(side, bottom, ep, q, wallet, t) > 0
        if _margin_surplus(side, hi, ep, q, wallet, t) <= 0:
            root = (q * ep + wallet + Fraction(t.cum)) / (q * (1 + Fraction(t.maint_margin_ratio)))
            return LIQUIDATION_OK, root
    return NOTIONAL_ABOVE_MAX, None  # no crossing inside the table (price above the top cap)


def _case(rng: random.Random, side: str) -> dict[str, object]:
    entry = Decimal(rng.randint(1_000, 100_000)) + Decimal(rng.randint(0, 99)) / 100
    notional = Decimal(10) ** Decimal(str(rng.uniform(3.0, 8.7)))  # 1e3 .. ~5e8
    quantity = (notional / entry).quantize(Decimal("0.0001")) or Decimal("0.0001")
    return {
        "side": side,
        "entry": entry,
        "quantity": quantity,
        "leverage": rng.randint(1, 5),
        "fee": Decimal(rng.randint(0, 5)) / 10_000,
        "stop_gap": Decimal(rng.randint(5, 4000)) / 10_000,
        "buffer_bps": rng.randint(1, 500),
    }


def test_liquidation_price_agrees_with_the_first_crossing_oracle_on_300_cases() -> None:
    rng = random.Random(220_007)
    table = demo_brackets()
    ok_seen = {"LONG": 0, "SHORT": 0}
    tiers_seen: set[int] = set()
    refusals: dict[str, int] = {}
    for index in range(CASES):
        side = "LONG" if index % 2 == 0 else "SHORT"
        c = _case(rng, side)
        entry, qty, lev, fee = c["entry"], c["quantity"], c["leverage"], c["fee"]
        assert isinstance(entry, Decimal) and isinstance(qty, Decimal)
        assert isinstance(lev, int) and isinstance(fee, Decimal)
        reason, expected = _oracle(side, Fraction(entry), Fraction(qty), lev, Fraction(fee), table)
        got = liquidation_price(
            side=side,
            entry_price=entry,
            quantity=qty,
            leverage=lev,
            brackets=table,
            entry_fee_rate=fee,
        )
        if expected is None:
            assert got is None, f"case {index} {c}: oracle refuses ({reason}), module gave {got}"
            refusals[reason] = refusals.get(reason, 0) + 1
        else:
            assert got is not None, f"case {index} {c}: oracle gives {expected}, module None"
            relative = abs(Fraction(got) - expected) / expected
            assert relative <= TOLERANCE, f"case {index} {c}: {got} vs {expected}"
            ok_seen[side] += 1
            tiers_seen.add(
                next(
                    t.bracket
                    for t in table
                    if Fraction(t.notional_floor)
                    <= Fraction(qty) * expected
                    <= Fraction(t.notional_cap)
                )
            )
        # The verdict composes the same price with the strict buffer predicate.
        gap = c["stop_gap"]
        buffer_bps = c["buffer_bps"]
        assert isinstance(gap, Decimal) and isinstance(buffer_bps, int)
        stop = entry * (1 - gap) if side == "LONG" else entry * (1 + gap)
        verdict = liquidation_verdict(
            side=side,
            entry_price=entry,
            quantity=qty,
            leverage=lev,
            brackets=table,
            stop_price=stop,
            buffer_bps=buffer_bps,
            entry_fee_rate=fee,
        )
        if expected is None:
            assert not verdict.ok and verdict.reason_code == reason
            assert verdict.liquidation_price is None
            continue
        buffer = Fraction(entry) * buffer_bps / 10_000
        beyond = (
            expected < Fraction(stop) - buffer
            if side == "LONG"
            else expected > Fraction(stop) + buffer
        )
        assert verdict.ok is beyond, f"case {index} {c}"
        assert verdict.reason_code == (LIQUIDATION_OK if beyond else LIQUIDATION_TOO_CLOSE)
    # The random draw must actually exercise both sides, several tiers and several refusals.
    assert ok_seen["LONG"] >= 40 and ok_seen["SHORT"] >= 40, ok_seen
    assert len(tiers_seen) >= 3, tiers_seen
    assert sum(refusals.values()) >= 20, refusals
    assert LEVERAGE_ABOVE_BRACKET in refusals, refusals
