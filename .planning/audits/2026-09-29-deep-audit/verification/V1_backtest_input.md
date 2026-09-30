# Verification batch V1_backtest — BLIND INPUT (claims + locations only)

## F-901
- Claimed severity: HIGH
- Claim: Backtest fills, invalidates and exits a plan inside the same bar that generated its signal (look-ahead); plans are never carried to later bars; the skipped fix CR-04 was never scheduled
- Expected behavior (per claimant): A plan created at the close of bar N fills only from bar N+1 until expiry (trade-through). The position is carried across bars until SL/TP/expiry. The intrabar walk starts after the fill. TP ladder semantics match live.
- Location(s): src/backtest/simulator.py:753-866
- Component: Phase 6 simulator design (06-01-PLAN entry semantics; skipped 06-REVIEW CR-04)

## F-120
- Claimed severity: HIGH
- Claim: The backtest fills and exits trades using the same 1H bar that produced the signal, i.e. with data from before the decision time. The strategy and planner are evaluated on closed bar `bar` (decision at bar.close_time_utc). `_resolve_entry(bar=bar)` then decides the zone touch/fill and the invalidation from that bar's own high/low/open/close, and the exit is resolved from the 1m candles keyed to that same bar (`intrabar_key = f"{bar.symbol}|{bar.close_time_utc}"`, 09:00-09:59 for a 09:59:59 decision). Every trade is also held for at most one bar ('EOD' at the last 1m close). The SUMMARY/VERIFICATION claims that BKTS-01 intrabar resolution and the DOMN-03 no-lookahead suite hold are therefore false for the simulator.
- Expected behavior (per claimant): BACKTEST_SPEC.md:18-22 'No future candle data ... or future intrabar outcome may leak into historical decisions'; RESEARCH_PROTOCOL §3 closed-candle rule; entry can only fill on bars AFTER the signal close, within expiry; exits after entry.
- Location(s): src/backtest/simulator.py:752-870
- Component: src/backtest/simulator.py run/_resolve_entry

## F-902
- Claimed severity: HIGH
- Claim: Backtest counts any touch of the entry zone (even the far edge) as a fill at the zone mid, a price the bar may never have traded
- Expected behavior (per claimant): Fill only where the live LIMIT (at the zone mid) would fill: a trade-through of the mid by >= 1 tick. The fill price is the limit.
- Location(s): src/backtest/simulator.py:448-518
- Component: 04-03 checkpoint option A (zone-mid entry_ref) as mapped into the Phase 6 simulator

## F-601
- Claimed severity: HIGH
- Claim: Cost-unit seam (rate from modeled_costs_per_unit vs quote/unit in size_position) has no oracle; the only joining test recomputes the buggy formula; golden input yields SL loss 103.59 vs allowed risk 50 unasserted.
- Expected behavior (per claimant): Property test: SL-exit realized loss <= allowed risk (+ tolerance) and sizing realized_risk ~= simulated SL loss incl. fees; producer returns quote/unit scaling with price.
- Location(s): tests/test_backtest_simulator.py:326-358
- Component: tests for src/backtest/costs.py + src/risk/sizing.py

## F-602
- Claimed severity: HIGH
- Claim: Simulator tests lack causality/exit-structure oracles; fixture generator places fill/exit 1m data inside the signal bar; 7 of 9 phase6 cases have no expected.json (_load_expected dead); lookahead suites test strategy.evaluate only; paper parity projects to (signal_id, reason_code); TP2 never compared.
- Expected behavior (per claimant): Per-record invariants signal_close < entry_time <= exit_time; hand-verified expected outputs; negative fixture (signal-bar touch only => no fill); backtest-vs-live exit-structure (TP1/TP2) parity or explicit pinned deviation.
- Location(s): scripts/gen_phase6_fixtures.py:211-358
- Component: tests/test_backtest_simulator.py, scripts/gen_phase6_fixtures.py, tests/test_paper_parity.py
