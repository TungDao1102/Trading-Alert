# Verification V1_backtest
| ID | Outcome | Final severity | Duplicate of | One-line reason |
|---|---|---|---|---|
| F-901 | CONFIRMED | HIGH | — | Probe: the entry is stamped at the signal-bar close (09:59:59), and the SL exit comes from a 1m candle that closed at 09:00:59, before the entry. Plans are never carried to later bars. Phase-6 CR-04 was skipped and appears in none of phases 11-17. |
| F-120 | CONFIRMED | HIGH | F-901 | Same root defect as F-901. One sub-claim is overstated: 06-VERIFICATION already marks BKTS-01 PARTIAL/gaps_found and the milestone audit lists it as unsatisfied. Only 06-01-SUMMARY "[x] No-lookahead test" makes a false claim. |
| F-902 | CONFIRMED | HIGH | — | Probe: LONG zone [99,101], bar low 100.9, returns ENTRY_FILLED at 100, a price the bar never traded. Live places the LIMIT at the zone mid (placement.py:143). BACKTEST_SPEC §6 requires modeling "price touched vs actual fill". |
| F-601 | DOWNGRADED | MEDIUM | — | The test gap is real: the parity test recomputes the same rate-sum formula, and the golden SL loss of -103.59 against realized_risk 49.99 is never asserted. The root bug, with a regression test, is already scheduled as ROADMAP Phase 11, and 06-VERIFICATION IN-02a flagged the test. |
| F-602 | DOWNGRADED | MEDIUM | — | All sub-claims check out: 1m data sits inside the signal bar, 7/9 cases have no expected.json, `_load_expected` is dead, test_no_lookahead covers only `evaluate`, and paper parity compares (signal_id, reason_code) with no TP2. This is the test-side of F-901/F-902, and 06-VERIFICATION IN-02b partly flagged it. |

## F-901
- Outcome / final severity: CONFIRMED / HIGH
- Independent evidence:
  - `src/backtest/simulator.py` `run()` loop: strategy `evaluate`, `plan(created_at_utc=bar.close_time_utc)` and `evaluate_risk` all run on `bar`. Then `_resolve_entry(trade_plan=trade_plan, bar=bar, ...)` runs on the same bar, and `intrabar_key = f"{bar.symbol}|{bar.close_time_utc.isoformat()}"` feeds `resolve_intrabar`. There is no queue of pending plans and no loop over later bars. Each plan resolves within the iteration that created it.
  - `_resolve_entry`: invalidation uses the same bar's `close < open` (LONG), and the touch uses the same bar's `high/low`. `entry_time_utc=bar.close_time_utc`.
  - `resolve_intrabar` returns "EOD" at `intrabar[-1].close` when neither SL nor TP1 is touched, so the maximum holding time is one bar. Its docstring says the TP2 runner is not modeled.
  - Probe (`tmp/verify_V1_backtest/probe_run.py`, run on the snapshot fixtures):
    `intrabar_both_touched LONG entry 121.5 2026-09-11T09:59:59 exit SL 121.42 2026-09-11T09:00:59`. The exit precedes the entry by 59 minutes. SHORT and partial_fill show the same pattern.
  - 06-REVIEW-FIX.md "Skipped Issues / CR-04": "`bar.close >= expiry` is never true for same-bar plans, and plans are never carried across bars ... the real fix is a cross-bar plan lifecycle ... Needs a planner/simulator design call."
  - ROADMAP phases 11-17 (fee units, equity, leverage, margin, price check, notification, quote asset) contain no cross-bar lifecycle or CR-04 item. The Phase-6 CR-04 id appears only in the 06-* files.
- Counter-checks: I searched for any other entry point that carries plans (`run` is the only loop in simulator.py, and `_resolve_entry` is called once). I checked whether the "decision at close, fill from 1m after close" semantics could hold: the 1m key is the signal bar's own close, and the fixture 1m candles span 09:00-09:59 (gen_phase6_fixtures.py `trigger_open + i minutes`). BACKTEST_SPEC §3: "No ... future intrabar outcome may leak".
- Notes: The results are not reliably optimistic, but they are causally meaningless: the outcome is taken from data before the decision, and the holding period is capped at one bar. That invalidates any expectancy or kill-gate evidence the engine produces. It stays HIGH rather than CRITICAL because the simulator does not yet run on real data (milestone audit M4) and is not in the order path.

## F-120
- Outcome / final severity: CONFIRMED / HIGH, DUPLICATE_OF F-901
- Independent evidence: see F-901 (same lines, same probe). `entry_time_utc` is 09:59:59 and the exit is 09:00:59.
- Counter-checks: The sub-claim that "SUMMARY/VERIFICATION claim BKTS-01 and DOMN-03 hold" is only partly true:
  - 06-VERIFICATION.md reports `status: gaps_found` with BKTS-01 "⚠️ PARTIAL".
  - v0.3-MILESTONE-AUDIT.md:235 lists BKTS-01 as "**unsatisfied**".
  - REQUIREMENTS.md lists BKTS-01 and DOMN-03 as Pending.
  - However, 06-01-SUMMARY.md:112 ticks "[x] No-lookahead test". That test (test_backtest_simulator.py:366) cannot detect this defect: the exit is decided on 1m candle 0, which 06-VERIFICATION IN-02b itself notes.
  - None of the planning docs identify the same-bar causality defect. VERIFICATION's G3 covers only the expiry clock.
- Notes: The severity and core claim are correct. The "claims are false" framing should be narrowed to the SUMMARY checkbox.

## F-902
- Outcome / final severity: CONFIRMED / HIGH
- Independent evidence:
  - simulator.py `_resolve_entry`: `zone_touched = bar.high >= trade_plan.entry_min_price and bar.low <= trade_plan.entry_max_price`, followed by `entry_ref = (entry_min+entry_max)/2` as the fill price.
  - Probe `tmp/verify_V1_backtest/probe902.py`: a LONG plan with zone 99-101, bar O101.5 H103 L100.9 C102 gives `ENTRY_FILLED 100`, even though the bar's low was 100.9.
  - Live: `src/execution/placement.py:143` returns `_div(_add(entry_min_price, entry_max_price), 2)` as the limit price. A buy LIMIT at 100 would not fill on that bar.
  - docs/backtest/BACKTEST_SPEC.md §6 requires "price touched vs actual fill".
- Counter-checks: I found no later check of mid vs bar low/high in `_resolve_entry`. `partial_fill_fraction` scales quantity only, not the fill condition.
- Notes: This inflates both the fill rate and the entry quality, which biases expectancy upward. It is independent of F-901: a fix to F-901 that keeps this touch rule would still overfill.

## F-601
- Outcome / final severity: DOWNGRADED / MEDIUM
- Independent evidence:
  - The test at test_backtest_simulator.py:326-358 computes `expected_costs = fee_rate_entry + fee_rate_exit + expected_slippage`, the same formula as costs.py:201-204. It is a tautology.
  - sizing.py:60 computes `risk_per_unit = sl_distance + costs`, which adds a dimensionless rate to a quote/unit distance.
  - Probe on the golden `intrabar_both_touched` gives `realized_pnl -103.594` against `realized_risk 49.99998`: the SL loss is about 2.07x the allowed risk. No test asserts loss <= risk.
- Counter-checks: ROADMAP.md:357 (Phase 11) already records this bug as confirmed 2026-09-29 and schedules "multiply by entry reference price ... with a regression test". 06-VERIFICATION.md:184 (IN-02a) flagged "Parity test hand-derives costs".
- Notes: The missing oracle is real. It was downgraded because the underlying defect and its regression test are already scheduled. Recommend that Phase 11's regression test be the property "SL-exit loss incl. fees <= allowed risk (+tol)" and not a formula echo.

## F-602
- Outcome / final severity: DOWNGRADED / MEDIUM
- Independent evidence:
  - gen_phase6_fixtures.py: `trigger_open = BASE_OPEN + 249h`, and the 60 1m candles run from `trigger_open` onward. They are keyed by `_trigger_bar_close_key()`, the trigger bar's own close, so they fall inside the signal bar.
  - `find tests/fixtures/phase6`: 7 of 9 top-level cases have only `input.json`. The exceptions are `registry_identity` and `report_slices`; the baselines subdirs also have expected.json.
  - `_load_expected` is defined at test_backtest_simulator.py:35 and never called.
  - tests/test_no_lookahead.py imports only `src.core.strategy.evaluate` and `compute_features`.
  - test_paper_parity.py:111-166 projects to `(signal_id, reason_code)`. I found no TP2 or exit_kind comparison, and the simulator itself does not model TP2 (simulator.py:207-211).
- Counter-checks: I found no per-record `entry_time < exit_time` assertion anywhere in the tests (my probe shows exit_time < entry_time and no test catches it). 06-VERIFICATION IN-02b noted the weak no-lookahead test but did not require a causality oracle.
- Notes: Every part of the claim is accurate. It is the test-coverage side of F-901/F-902 (a related root, not an exact duplicate), and fixing F-901 forces most of these fixtures and tests to be rewritten anyway. That is why it is MEDIUM on its own.
