# Verification V4_docs_plan
| ID | Outcome | Final severity | Duplicate of | One-line reason |
|---|---|---|---|---|
| F-001 | DOWNGRADED | MEDIUM | - | Real: code adds dimensionless rate sum (0.0008) to a quote-price SL distance, so costs are ignored. But the overrun is 8-16% of a 0.5% budget ($0.32-0.64 on $800) in the probe, and the research doc does not drop costs (it lists fees/slippage as adjustments). |
| F-007 | CONFIRMED | HIGH | - | No live-price check between APPROVE and placement. If price has crossed the SL, the LIMIT fills at once, the MARK_PRICE STOP_MARKET is rejected, and the code only enters SAFE_MODE and cancels the already-filled entry. Nothing closes the position (no rescue, by design). |
| F-008 | REJECTED | - | - | The SL (CONDITIONAL STOP_MARKET, closePosition=true) is placed right after the entry is acknowledged, before any fill. Only TP1/TP2 wait for the fill, so a bot outage at fill time does not leave the position without a stop. |
| F-022 | CONFIRMED | HIGH | - | The protocol text says what is claimed: numeric thresholds are proposed only after Validation evidence from 3 or more families, "passing" is a recorded human decision, and no multiple-testing or trial-count penalty exists anywhere in docs or src. |
| F-903 | DOWNGRADED | MEDIUM | F-022 | The text exists (01-RESEARCH:226 calls numeric gates set before data "overfitting commitments"), but it is the planning origin of F-022, not a separate defect. Pitfall 2 (line 237-238) is about parameter values and is correct. |
| F-953 | DOWNGRADED | MEDIUM | - | Real: enable() accepts WITHIN_BUDGET and needs no passing candidate or paper-exit verdict. Paper exit thresholds are only qualitative, and the soak is blocked. Today it is unreachable: LiveEnablementController and execute_approved_plan have no importers in src/ (audit M2), and 09-04 is blocked on a human gate. |
| F-954 | DOWNGRADED | MEDIUM | - | Real sequencing gap: P11-P15 come after Phase 9, with no "live blocked until P11-P15" rule, and P11 only depends on P10. It is planning order only: no live path is wired (M2), and the soak cannot start (07-04 WS blocker). |

## F-001
- Outcome / final severity: DOWNGRADED, MEDIUM.
- Independent evidence:
  - The doc is ambiguous: `docs/trading/RISK_MANAGEMENT.md:21` reads `risk_per_unit = worst_case_distance_to_SL + modeled_costs`, with no unit on the cost term.
  - The code shows the unit bug:
    - `src/risk/sizing.py:59-60` computes `sl_distance = abs(entry_ref - stop_loss_price)` and `risk_per_unit = _add(sl_distance, costs)`.
    - `src/backtest/costs.py:184-206` has a docstring saying "per-unit cost in quote currency", but it returns `fee_rate_entry + fee_rate_exit + expected_slippage`, which is a rate.
    - The same quantity feeds `src/risk/gating.py:100` (live, via `evaluate_risk`) and `src/paper/loop.py:504`.
  - Probe (`tmp/verify_V4_docs_plan/p.py`), using baseline-v3 fees 0.0002/0.0005 and slippage 0.0001, $800 equity, 0.5% risk: costs_per_unit comes out as 0.0008.
    - 1% SL on BTC at 60000: realized loss at SL is 4.3176 against 4.000 allowed (+7.94%).
    - 0.5% SL: 4.6376 (+15.94%).
- Counter-checks:
  - `docs/research/TRADING_STRATEGY_RESEARCH.md:551-561` gives `quantity = risk_budget / abs(entry - stop)` and then says it must be adjusted for fees, slippage and funding. So the claim that the research doc "drops costs entirely" is overstated.
  - The planning already records this bug as the Phase 11 goal (`.planning/ROADMAP.md:357`).
- Notes: The mechanism is right, but the consequence is a bounded, proportional overrun (roughly cost / SL distance), not a loss-of-capital event. For a $500-1,000 account it moves 0.5% risk to about 0.54-0.58% per trade, and aggregate risk under the 1.0% cap to about 1.16%. That is MEDIUM.

## F-007
- Outcome / final severity: CONFIRMED, HIGH.
- Independent evidence:
  - `src/execution/manager.py` `execute_approved_plan` runs these gates: binding, approval-authorizes-plan, enablement, SAFE_MODE, `evaluate_risk`, `decide_placement` (headroom, stale constraints, uncertain state, portfolio). None of them reads the current mark or last price.
  - The code then places a GTC LIMIT at the zone mid (lines ~466-509). Right after that it places a STOP_MARKET SL with `working_type="MARK_PRICE"` and `close_position=True`.
  - If the SL is not confirmed (lines ~547-565), the code enters SAFE_MODE, calls `expire_pending_entry` (a cancel), and returns ENTRY_WITHOUT_PROTECTIVE.
  - A cancel cannot undo a fill that has already happened. `src/reconcile/sweeper.py:5` and `src/execution/fill_monitor.py:24` both say the system never places rescue protection.
  - A grep for mark/last-price reads in `src/execution` finds nothing. Adapter `mark_price` fields exist only in position and collector models.
  - Exactly this gap is Phase 15 in `.planning/ROADMAP.md:399` ("a live-price-vs-SL check was not confirmed in execute_approved_plan").
- Counter-checks: Approval expiry (4h, `signal_expiry_hours = 4` in baseline-v3), plan-hash staleness and invalidation checks are all based on the plan or on closed candles. None of them catches an intrabar cross of the SL inside the 4h window.
- Trading consequence (LONG case), when mark < SL at APPROVE time:
  - The BUY LIMIT at the zone mid is marketable and fills immediately as taker.
  - A SELL STOP_MARKET with trigger > mark is rejected by Binance ("Order would immediately trigger").
  - The result is a naked position already past its invalidation, left alone until the human acts.
  - The other case, price leaving the zone upward, just leaves the order resting and is harmless. So the SL-cross case is what carries the severity.
- Notes: The path is not reachable yet (M2: manager has no importers in src/), but it is the only designed live path, so HIGH stands.

## F-008
- Outcome / final severity: REJECTED.
- Counter-evidence:
  - `src/execution/manager.py` places the SL leg (`_place_protective_leg`, role STOP_LOSS, CONDITIONAL STOP_MARKET, `close_position: True`) straight after `_place_entry_no_blind_retry` returns acknowledged or found. It does not wait for a fill. The comment calls it "the pre-fill safety net".
  - TP1/TP2 are attached to the actual fill by `attach_protectives_to_fill`, which adopts the existing SL by its deterministic id.
  - `docs/trading/EXECUTION_SPEC.md:18-20` orders the steps "Place entry, then Place/attach protective exits". §6 (lines 89-98) is a check after fill that the stop exists, not a rule that it may only be placed after the fill.
- Counter-checks:
  - A closePosition=true STOP_MARKET works independently of position size, so partial fills are covered.
  - The residual window is only the round trip between the entry ack and the SL request. If the SL fails, SAFE_MODE follows (see F-007 for the case where the entry has already filled).
  - Bot death while the LIMIT rests leaves the SL on Binance. That is an orphan-SL risk (swept later), not an unprotected position.
- Notes: Binance accepting a closePosition CONDITIONAL order with no position open is standard behavior. A testnet placement would confirm it definitively, but it does not change the verdict.

## F-022
- Outcome / final severity: CONFIRMED, HIGH.
- Independent evidence (`docs/research/RESEARCH_PROTOCOL.md`):
  - Lines 205-213: thresholds stay "TBD until the methodology is exercised on real data". "After ≥3 independently specified families ... have produced Validation evidence, then and only then are candidate numerical thresholds proposed".
  - Line 236: "a family's passing status is a recorded human decision with a decision reference, never computed."
  - Line 24: every numeric gate is TBD until exercised on real data.
- Counter-checks:
  - A grep for multiple-testing, deflated, Bonferroni, reality check, data-snooping, trial count and number of trials in docs/, src/, PROJECT.md and REQUIREMENTS.md finds nothing.
  - The "selection bias" hits (`METRICS.md:85`, `approval_delay.py`) are about approval-delay, not selecting among trials.
  - Partial mitigations exist: the final holdout is reserved and not for choosing parameters (line 46), the 10 methodology gates, and block-bootstrap reporting. But nothing requires thresholds to be frozen before the holdout is read, and nothing counts or penalizes trials.
- Notes: Thresholds set after seeing Validation, plus a human pass decision, plus many variants and sweeps is the main way a false-positive edge reaches live capital. That is the core risk to this project's stated value, so HIGH stands.

## F-903
- Outcome / final severity: DOWNGRADED, MEDIUM. DUPLICATE_OF F-022.
- Independent evidence: `.planning/phases/01-research-formalization/01-RESEARCH.md:226` says: "Acceptance numbers | Invented thresholds (e.g. 'expectancy > 0.2R') | BACKTEST_SPEC 'thresholds TBD' + interval reporting | Numeric gates before data are overfitting commitments".
- Counter-checks: Pitfall 2 (lines 237-238) targets parameter values (ATR multipliers, RR minima, expiry hours) and explicitly keeps "gates" frozen as methodology. Only the Don't-Hand-Roll row mislabels pre-registered acceptance thresholds as overfitting.
- Notes: This is the planning origin of F-022. The governing defect is in the frozen protocol, so it is folded there and not counted separately.

## F-953
- Outcome / final severity: DOWNGRADED, MEDIUM.
- Independent evidence:
  - `src/execution/enablement.py:188-219` has `enable()`. It requires a passing health verdict and an isinstance KillGateState, and it refuses only INSUFFICIENT_EDGE. WITHIN_BUDGET and PASSING_CANDIDATE both flip the flag.
  - The docstring (lines 177-179) calls the separate human decision record "a process requirement", not something code checks.
  - Soak status: `.planning/STATE.md:176`, `:241` and `:250` say the 07-04 WS connect path is unwired and the "Soak must NOT start until live WS smoke passes". `v0.3-MILESTONE-AUDIT.md` M3 says the paper journal is never written.
  - `docs/implementation/IMPLEMENTATION_PLAN.md:96-100` defines the paper exit gate only qualitatively ("minimum forward evidence defined by the actual signal frequency").
- Counter-checks:
  - A grep shows `LiveEnablementController(` and `execute_approved_plan` have zero importers in src/ outside their own modules (audit M2).
  - 09-04 is blocked on a human testnet/LIVE-TAP gate (`STATE.md:212`).
- Notes: The defect is real (a negative-only gate that the single operator can pass with zero evidence), but no live order path exists today, and the worst case is bounded by 0.5% per-trade risk on a $500-1,000 account. MEDIUM, and it should become a blocker before M2 is wired.

## F-954
- Outcome / final severity: DOWNGRADED, MEDIUM.
- Independent evidence (`.planning/ROADMAP.md`):
  - Phase 9 (lines 286-306) is unchecked, with 4/4 plans executed; its remaining 09-04 checkpoint is a blocking human gate.
  - Phase 11 depends on Phase 10 (line 358), Phase 12 on 11, Phase 13 on 12, Phase 14 on 12/13, and Phase 15 on 12.
  - No text in phases 9-15 blocks live enablement until P11-P15 are verified. P11 states that golden fixtures and experiment hashes will change, and it is not ordered before the paper soak epoch.
- Counter-checks: The soak cannot start (07-04 WS blocker), and there is no composed live path (M2). So today the sequencing cannot produce a live order or a contaminated soak epoch.
- Notes: A real planning gap, cheap to fix by adding a dependency and gate. It is not a present money path, so MEDIUM.
