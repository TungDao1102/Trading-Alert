# Lane 3: business_invariants

Stage C (code). Findings are F-301..F-307. The code is judged against the stage-A "Corrected Rules for Code Audit" (`lanes/docs_trading_soundness.md`) and the "Exchange Facts for Code Audit" (`lanes/docs_exchange_facts.md`).

All probes live in `AUDIT/tmp/business_invariants/`.
- Each `pN_*.py` has its recorded output in `pN_*.out.txt`.
- How they were run: `PYTHONPATH=<SNAPSHOT>;. <repo .venv python> -B pN_*.py`.
- They import the snapshot code read-only. The snapshot and the original repo were verified clean afterwards.

## Scope

**Money and safety invariants.** Each was traced through every entry point:
- the backtest (`simulator.run`)
- paper (`paper.loop.run_paper_tick`)
- live (`execution.manager.execute_approved_plan` / `attach_protectives_to_fill`)
- approval intake (`telegram_callbacks.dispatch_callback` → `approval.replay.resolve_callback`)
- reconcile/SAFE_MODE (`reconcile.compare`, `sweeper`, `safe_mode`)
- drills
- analytics outcome normalizers

**Modules read in depth:**
- `src/risk/*`
- `src/backtest/costs.py`, `src/backtest/simulator.py`
- `src/core/planner.py`, `src/core/strategy.py` (trend-pullback path), `src/core/features.py` (swing/zone)
- `src/execution/*`
- `src/approval/*`, `src/domain/approval.py`, `src/domain/trade_plan.py`
- `src/adapters/telegram_callbacks.py`
- `src/reconcile/*`
- `src/paper/loop.py`
- `src/analytics/live_outcomes.py`, `src/analytics/gates.py`
- The placement/probe/position methods of `src/adapters/binance_usdm.py`

**Other inputs:**
- `params/trend-pullback/baseline-v3.toml`
- the fixture `exchange_info_sample.json` and the phase6/7/9 fixtures
- the 06/08/09 REVIEW files, for known-prior lookups

**Deduplication.** Before writing, I checked the findings already published by the parallel stage-C lanes (L2 F-2xx, L4 F-4xx, L5 F-5xx, L6 F-6xx, L7 F-7xx). Where my probe independently reproduced one of them, I recorded it under "Cross-lane confirmations" and did not issue a new ID.

## Coverage

| file | depth | note |
|---|---|---|
| src/risk/sizing.py | DEEP_READ | probe p1, p12 |
| src/risk/quantization.py | DEEP_READ | probe p1, p5 |
| src/risk/portfolio.py | DEEP_READ | probe p6, p12 |
| src/risk/gating.py | DEEP_READ | `positions_reconciled=True` hard-coded (L94, L120); live re-gates in `decide_placement` |
| src/risk/types.py | DEEP_READ | |
| src/risk/__init__.py | NORMAL_READ | |
| src/backtest/costs.py | DEEP_READ | P11 bug quantified (p1) |
| src/backtest/simulator.py | DEEP_READ | F-305, F-306, F-304 |
| src/backtest/experiment.py | NORMAL_READ | only fixture-driven callers of `simulator.run` |
| src/core/planner.py | DEEP_READ | F-301 |
| src/core/strategy.py | NORMAL_READ | trend-pullback `_detect_setup`, forming-bar gate, regime |
| src/core/features.py | NORMAL_READ | `_swing_series` trailing window includes the current bar |
| src/core/types.py | NORMAL_READ | AccountState, Candle, MarketSnapshot |
| src/core/_decimal.py | NORMAL_READ | |
| src/domain/trade_plan.py | DEEP_READ | no symbol/direction field (F-302) |
| src/domain/approval.py | DEEP_READ | |
| src/domain/enums.py | NORMAL_READ | TradePlanStatus |
| src/execution/manager.py | DEEP_READ | F-302, F-303, F-304; probe p13 |
| src/execution/placement.py | DEEP_READ | F-307; probe p5 |
| src/execution/gates.py | DEEP_READ | |
| src/execution/enablement.py | DEEP_READ | |
| src/execution/order_ids.py | NORMAL_READ | KNOWN F-951 |
| src/execution/fill_monitor.py | NORMAL_READ | |
| src/approval/binding.py | DEEP_READ | |
| src/approval/replay.py | DEEP_READ | |
| src/approval/tokens.py | DEEP_READ | |
| src/approval/mapping.py | NORMAL_READ | |
| src/adapters/telegram_callbacks.py | DEEP_READ | probe p10 (= L4 F-405) |
| src/adapters/telegram_notify.py | NORMAL_READ | format_approve (KNOWN P16) |
| src/adapters/binance_usdm.py | NORMAL_READ | place_entry, place_algo_protective, query_*_by_client, snapshot_positions |
| src/reconcile/compare.py | DEEP_READ | probe p3 (= L7 F-701), p4 (= L4 F-401) |
| src/reconcile/sweeper.py | DEEP_READ | probe p4 |
| src/reconcile/safe_mode.py | DEEP_READ | |
| src/paper/loop.py | DEEP_READ | same risk path as the backtest; no simulated fills |
| src/paper/journal.py, supervisor.py, resync.py, notify.py | METADATA_ONLY | grep for PnL/fee math: none |
| src/analytics/live_outcomes.py | NORMAL_READ | probe p8 (= L2 F-204) |
| src/analytics/gates.py | NORMAL_READ | |
| src/analytics/killgate.py | METADATA_ONLY | sticky logic skimmed; enable() link KNOWN F-953 |
| src/analytics/excursion.py, stats.py | METADATA_ONLY | R formula |
| src/ops/drills.py | NORMAL_READ | only composition of compare → sweeper → safe_mode |
| params/trend-pullback/baseline-v3.toml | DEEP_READ | |
| params/*/baseline-*.toml | METADATA_ONLY | grep of the cost/risk keys |
| tests/fixtures/exchange_info_sample.json | NORMAL_READ | tick/step/minQty/minNotional for the probes |
| tests/fixtures/phase6/*, phase7/*, phase9/placement_sequences | NORMAL_READ | probe inputs |
| tests/test_execution_manager.py | NORMAL_READ | helpers reused read-only by probe p13 |
| docs/research/families/trend-pullback.md | NORMAL_READ | swing/pivot definition (F-301) |
| docs/integration/TELEGRAM.md | NORMAL_READ | §3 approval binding |
| .planning/ROADMAP.md (P11–P17), 06-REVIEW WR-13, 08-REVIEW CR-01 | NORMAL_READ | known-prior checks |

## Verified Safe Areas

| Invariant / behavior | What I checked | Where | Why it holds |
|---|---|---|---|
| INV-055 Quantity is floored, never rounded up | `steps = raw // step; rounded = steps*step` in Decimal | `risk/quantization.py:188-189` | Positive operands, so truncation is a floor. p1 shows no rounded qty above raw. The planner never rounds (`planner.py:444-448`). |
| INV-057 minQty / minNotional reject | Fixed order: minQty → notional → utilization. No round-up. | `quantization.py:191-233` | p1: BTC $500 at SL 3% floors to 0.001, and notional $60 ≥ 50 passes. Nothing is ever lifted to minQty. |
| INV-056 60% utilization, correct metric | numerator `rounded × risk_per_unit`, denominator `allowed_risk` | `quantization.py:214-233` | Matches Corrected Rule 4. p8: BTC $500 SL 3% gives utilization 0.72 and is accepted. |
| Per-trade risk backstop | cluster-cap comparison `cluster_sum = cluster_open_risk + candidate_risk` | `portfolio.py:319-335` | It applies to every candidate, including non-cluster BNB (the candidate's own risk is always added). p12: a caller `risk_rate` of 0.0099 or 0.02 is rejected CLUSTER_CAP_REJECT for BNB and ETH. The mis-sourced `risk_rate` (planner WR-03 reads the caller's AccountState, not the registry) is therefore capped at `cluster_cap` = 0.5%. This corrects the nuance of F-908: BNB positions are not summed into the cluster, but a single BNB trade is still capped. |
| Daily state boundaries | inclusive `>=` for WARNING/DAILY_STOP | `portfolio.py:66-70` | Matches Corrected Rule 10's "≥". The rest of the rule (producer, UTC day, base, persistence) is KNOWN P12 / F-963. |
| Fail-closed on unknown daily loss, stale or future-dated constraints, malformed thresholds | `check_portfolio` + `decide_placement` | `portfolio.py:223-306`, `gates.py:159-218` | None loss → UNCERTAIN. Negative age → STALE. Bool/float thresholds → UNCERTAIN. |
| INV-086 stop never widened; tick rounding does not add risk | LONG limit floors, SHORT ceils. SL rounds toward the entry. TP rounds toward the entry. | `placement.py:199-218`, `manager.py:471-483` | The placed limit→SL distance is ≤ the sized mid→SL distance, so realized risk ≤ sized risk. p13 baseline: limit 101.00 (mid 101), SL 98.00. The rounding direction differs from Corrected Rule 6 (SL away from entry), but only in the safe direction. |
| INV-047 approval expiry | `now_utc >= expiry_utc` → APPROVAL_EXPIRED, checked at callback and again at placement with the placement clock | `binding.py:189-193`, `manager.py:363-372` | The boundary is inclusive, as Corrected Rule 21 requires. The minimum remaining validity is missing (KNOWN F-955). |
| Placement gate order: enablement, then SAFE_MODE, then risk, then placement gates | each is a required argument, and None raises | `manager.py:346-452` | An approved plan in SAFE_MODE or while disabled returns NO_TRADE before any adapter call. SAFE_MODE blocks only `execute_approved_plan`. The protective attach path is not blocked (Corrected Rule 24 direction). |
| INV-078 enablement default | `_disabled=True` in `__init__` | `enablement.py:354-358` | In memory. A restart re-disables (safe direction). WITHIN_BUDGET acceptance is KNOWN F-953. |
| Approval decision gate at placement | action, result and status must all be APPROVED; plan_hash, trade_plan_id and expiry must equal the plan's | `manager.py:212-256` | A SKIP/PENDING row with a valid token cannot place an order. |
| Replay-to-existing (in process) | per-token lock; a decided row is returned untouched | `replay.py:128-192` | Cross-process safety needs a store-level compare-and-set (L4 F-404). |
| INV-080/082 protective legs | CONDITIONAL STOP_MARKET/TAKE_PROFIT_MARKET; closePosition never combined with quantity or reduceOnly | `placement.py:278-459`, `binance_usdm.py:1077-1178` | Matches the A2 facts. workingType=MARK_PRICE is KNOWN F-958/L5 F-507. |
| Pre-fill SL exists at placement | `execute_approved_plan` places the close-all SL right after the entry ACK. An unconfirmed SL gives SAFE_MODE and an entry cancel. | `manager.py:545-580` | Mitigates F-008 by design. It is undone by the sweeper (L4 F-401, reproduced in p4). |
| INV-003/004 closed candles, no future bars in features | trailing swing/EMA/ATR; forming-bar gate | `features.py:166-195`, `strategy.py:79-91,610-626` | No right-side pivot look-ahead. The backtest same-bar fill is KNOWN F-120/F-901. |
| Direction geometry of breakout-retest and range-mr | the entry zone lies on the correct side of the SL for LONG and SHORT | `planner.py:115-145,170-196` | breakout: entry_min = edge − 0.1 ATR > SL = edge − 0.2 ATR. range-mr: the same. Only trend-pullback is wrong (F-301). |

## Known findings — code-level confirmation or correction (no new IDs)

- **Fee-unit bug (KNOWN P11 / F-001 / F-601).** p1 runs the real `evaluate_risk` with baseline-v3 costs. `modeled_costs_per_unit` returns 0.0008.
  - Real SL loss (fees on notional plus 1 bp exit slippage) divided by allowed risk:
    - 1.77–1.80 R at a 0.1% stop (BTC, ETH, SOL, BNB, $500 or $1000), with notional about 5× equity
    - 1.34–1.40 R at 0.2%
    - 1.11–1.16 R at 0.5%
    - 1.04–1.08 R at 1%
    - 0.74–1.03 R at 3%, where the qty floor dominates
  - **Correction to the P11 wording.** The error is price-dependent and changes sign. For XRPUSDT at price 0.5, the rate 0.0008 is larger than the true per-unit cost (about 0.0004), so the trade is under-sized: 0.69 R at a 0.1% stop and 0.78 R at 0.2%. "Costs are effectively ignored" holds only for high-priced symbols. The P11 regression test should include a low-price symbol.
  - The backtest-recorded SL loss differs from the true loss as well (column `btLoss$`). This is the known 06-REVIEW WR-13 slippage part, now F-306.
- **Duplicate entry after fill (KNOWN F-951/F-126, L6 F-603).** When `execute_approved_plan` runs again after the first entry has filled, the SL probe finds the existing `xa-…SL` NEW leg and adopts it (`manager.py:741-750`). The duplicate position is therefore covered by the same closePosition SL: the loss at the SL is 2× the planned R, not a naked position. TP1 stays sized to the first fill. L7 F-701, reproduced in p3, shows reconcile then reports `agreement=True` for 0.010 local against 0.020 on the exchange, so nothing flags the doubled risk.
- **Protective-leg rejection after a marketable fill (KNOWN F-007/F-952, L5 F-502).** Nothing new to add.
- **Daily loss (KNOWN P12/F-963).** Grep confirms that no module in `src/` produces `daily_loss_quote`. The backtest and paper read a constant from the case input (`simulator.py:717`, `loop.py:331`), and live takes whatever the caller passes. `resolve_absolute_thresholds` scales the daily thresholds by the equity passed at call time, not by start-of-day equity. DAILY_STOP is not persisted and cancels nothing.

## Cross-lane confirmations (independently reproduced; not re-issued)

| Other lane ID | My probe | Result |
|---|---|---|
| L4 F-401 (sweeper cancels the pre-fill SL of a resting entry) | p4 | A resting ENTRY plus its `xa-SL` with no position gives `ORPHAN_PROTECTIVE`. The sweeper cancels it. The next tick shows `ENTRY_WITHOUT_PROTECTIVE`. Every normal placement therefore also drives SAFE_MODE. SAFE_MODE does not cancel the resting entry, so it can fill naked (Corrected Rule 14). |
| L7 F-701 (compare blind to size and sign; TP-only counts as protected) | p3 | 0.010 against 0.020, 0.010 against 0.500, and +0.010 against −0.010 (BOTH) all give `agreement=True`. A TP1-only position also gives `agreement=True`. |
| L4 F-405 (SKIP can never succeed) | p10 | `SKP:` on the stored-APPROVE row gives INVALIDATED. `APR:` gives APPROVED. |
| L2 F-203 (qty re-sized at placement, not bound to the approval) | p13 baseline | The repo's own golden phase9 fixture places qty **3.311**, while the approved plan's `quantity_after_rounding` is **0.500** (6.6×). |
| L2 F-204 (R denominator differs) | p8 | For the same SL loss: backtest R −1.000, live R −0.720 (BTC $500 SL 3%) or −0.960 (BTC SL 1%). |
| L2 F-208 (TP legs re-quantized with MIN_NOTIONAL / LOT_SIZE) | p5 | The consequence is reported as F-307. |

## Findings

### F-301 — trend-pullback baseline geometry: the stop sits inside the entry zone, only 0.2 ATR from the limit, and "pullback to support" fires on bars that make a new 20-bar low

- **ID:** F-301
- **Severity:** HIGH
- **Confidence:** CONFIRMED (end-to-end probe)
- **Classification:** DEFECT
- **Category:** strategy/planner geometry, sizing
- **Component:** core/features, core/strategy, core/planner
- **File:** `src/core/planner.py` · **Lines:** 105-114, 160-169, 378-409 (also `src/core/features.py:166-195`, `src/core/strategy.py:128-162`)
- **Invariant:** INV-041, INV-042, INV-053, INV-054; Corrected Rules 2, 3, 6
- **Phase/commit:** 04 / 63ca176
- **Known-prior:** Root cause is the doc/plan decisions F-909 (tracer values 0.5/0.2/0.1 ATR adopted with no rationale) and F-113 (geometry ≠ family sheet). The code facts below are NEW. They compound with KNOWN P11 (costs) and P13 (no leverage cap).

**Evidence:**
- `_long_geometry` for trend-pullback returns `(swing_low + half, swing_low − half, swing_low − sl_buffer, swing_high)` with `half = zone_tolerance_atr × ATR` (`planner.py:105-114`). `plan()` then widens the zone: `entry_min = zone_lower − entry_buffer`, `entry_max = zone_upper + entry_buffer` (`:378-379`).
- baseline-v3 has `zone_tolerance_atr = 0.5`, `entry_buffer_atr = 0.1`, `sl_buffer_atr = 0.2`. So:
  - entry_min = swing_low − 0.6 ATR
  - SL = swing_low − 0.2 ATR
  - mid = swing_low
- `_swing_series` takes `min(low)` over `candles[i−lookback+1 .. i]`, which includes the evaluated bar (`features.py:174-187`).
- `_detect_setup` fires LONG when `support_lower <= last.low <= support_upper` (`strategy.py:157`). A bar that prints a new 20-bar low has `last.low == swing_low` and always qualifies.
- The family sheet requires confirmed pivots, "Decisions … no unclosed pivots, no current-candle high/low" and "A swing is confirmed at the close of the bar at t + N" (`docs/research/families/trend-pullback.md:18,116-118`).

**Probes:**
- p2, with ATR 300 on BTC:
  - LONG zone 58820–59180, SL 58940. SL inside the entry zone = True: 33% of the zone lies beyond the SL.
  - Risk = 60 = 0.2 ATR = 0.102% of price. RR = 41.7.
  - SHORT is symmetric.
- p9, the full `strategy.evaluate` → `planner.plan` → `evaluate_risk` path on synthetic candles:
  - 300 rising 1H bars, then one bar breaking 150 below every prior 19-bar low, with a bullish 4H regime.
  - Output: `LONG TREND_PULLBACK_LONG`, zone 52590.9–52689.1, SL 52623.6 (inside the zone), RR 23.8.
  - Sized qty 0.305 BTC gives notional 16,055 USDT, which is 16.1× the $1000 equity.
  - Fees alone at the SL are 11.24 USDT against an allowed risk of 5.00. The real SL loss is about 16.2 USDT (3.2 R).

**Expected:**
- The stop lies beyond the whole entry zone (Corrected Rule 6: SL away from the entry).
- The setup level is a confirmed prior swing, not the current bar.
- A minimum stop distance or cost-to-risk ceiling rejects stops where fees dominate (Corrected Rule 3).

**Actual:**
- One third of the planned "valid entry" zone is already past the stop.
- The stop is a fixed 0.2 ATR from the limit, typically 0.05–0.2% on 1H.
- The RR gate never binds, because TP1 = the 20-bar high sits many stop-widths away.
- The detector treats a breakdown to a new low as a "pullback to support".
- Sizing then produces multi-× notional where the fee drag is 1.4–3.2× the risk budget (together with KNOWN P11).

**Reproduction:** `python -B tmp/business_invariants/p2_geometry.py` and `p9_trend_pullback_new_low.py` (outputs in the `.out.txt` files).

**Impact:**
- Every trend-pullback (baseline-v3) signal in paper and live has a stop inside its own zone, at noise distance.
- Losses at the SL routinely exceed the 0.5% budget by 40–220% (after P11 is fixed, sizing will shrink, but the stop placement and signal semantics stay wrong).
- Notional of 5–16× equity with no leverage/margin guard (KNOWN P13/P14) invites -2019 rejections or liquidation-before-SL at account-default leverage.
- Research results for Family A describe a different setup ("new-low breakdown with a 0.2 ATR stop") from the documented hypothesis.

**Why tests miss it:**
- Planner fixtures pin the computed numbers (golden outputs are regenerated from src, L6 F-608).
- No test asserts `SL < entry_min` for LONG or `SL > entry_max` for SHORT.
- No test checks that the swing excludes the current bar.
- No test bounds stop distance or notional.

**Remediation:**
- Require `SL < entry_min` (LONG) / `SL > entry_max` (SHORT) as a planner invariant, else NO_TRADE.
- Place the SL beyond the zone edge: `zone_lower − entry_buffer − sl_buffer`.
- Compute swings from confirmed pivots, excluding the current bar (right-lookback N), per the family sheet.
- Add Corrected Rule 3 (cost-to-risk ceiling) and a minimum stop distance in ATR and in % of price.
- Create a new parameter set / strategy version and re-run the research.

### F-302 — The order's symbol and side come from caller-supplied risk inputs; the approved TradePlan carries neither, and nothing re-checks SL geometry at placement

- **ID:** F-302
- **Severity:** HIGH
- **Confidence:** CONFIRMED (probe p13, using the repo's phase9 harness)
- **Classification:** GAP
- **Category:** approval binding / execution safety
- **Component:** domain/trade_plan, execution/manager
- **File:** `src/execution/manager.py` · **Lines:** 212-256, 455-560 (also `src/domain/trade_plan.py:46-78`, `src/risk/sizing.py:59`)
- **Invariant:** INV-041 (plan carries direction), INV-044 (approval bound to the exact plan), INV-049, INV-010
- **Phase/commit:** 03/09 / 63ca176
- **Known-prior:** NEW. Related: L2 F-203 (qty not bound), F-127(d) (token tautology).

**Evidence:**
- `TradePlan` has no `symbol` and no `direction` field (`trade_plan.py:61-80`).
- `_check_approval_authorizes_plan` compares only plan_hash, trade_plan_id and expiry (`manager.py:249-255`).
- The order symbol is `constraint_snapshot.symbol` from `risk_kwargs` (`:456-457, 512`).
- The side is `risk_kwargs["candidate_position_side"]` (`:470, 489-490`).
- `size_position` uses `abs(entry_ref − SL)`, so it is sign-agnostic (`sizing.py:59`). No check anywhere requires SL < entry for LONG or SL > entry for SHORT after the planner.

**Probe p13** (unchanged golden plan/approval/callback, only risk_kwargs mutated) returns `outcome=OK` in each case:
- Baseline: BUY 3.311 @101.00, SL SELL trigger 98.00.
- `candidate_position_side` flipped to SHORT: SELL 3.311 @101.00 plus a BUY STOP_MARKET trigger 98.00, which is below the entry, i.e. on the profit side.
- The constraint snapshot swapped to ETHUSDT: the same prices placed on ETHUSDT.

**Expected:**
- The approved, hashed plan (or its signal) fixes the symbol and direction.
- Execution derives both from the approved plan and rejects when the caller's constraint snapshot, side or SL geometry disagree (INV-044 "a mismatch on any of them rejects").

**Actual:** One composition mistake places an unapproved instrument or side under a valid approval. Examples: a snapshot cache keyed wrongly, or a direction taken from the wrong signal.
- A flipped LONG→SHORT plan whose zone is below the market sends a marketable SELL limit.
- It then sends a BUY "stop" below the price. Binance rejects it as would-immediately-trigger, or it closes at a profit-side level.
- The result is a naked short. Cancelling the entry is too late once it has filled (F-007/L5 F-502 path).

**Reproduction:** `python -B tmp/business_invariants/p13_symbol_side_unbound.py`.

**Impact:**
- This is defense-in-depth for real money.
- The runtime composition (M1–M4) that will build `risk_kwargs` does not exist yet. The gap is therefore latent, but it removes the last check between a wiring bug and an unsafe order.

**Why tests miss it:** Tests build `risk_kwargs` from the same fixture as the plan. No negative test mutates the symbol or side.

**Remediation:**
- Add `symbol` and `direction` to `TradePlan` and to `plan_hash`, or load the Signal by `signal_id` inside execution.
- Assert `constraint_snapshot.symbol == plan.symbol` and `candidate_position_side == plan.direction`.
- Assert the side-consistent geometry (LONG: SL < entry_min ≤ limit ≤ entry_max < TP1; SHORT mirrored), else NO_TRADE.

### F-303 — The portfolio gate admits a second plan on a symbol that already has an open position; in one-way mode an opposite plan silently nets it out

- **ID:** F-303
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED (probe p6)
- **Classification:** GAP
- **Category:** portfolio limits / position mode
- **Component:** risk/portfolio, execution/manager
- **File:** `src/risk/portfolio.py` · **Lines:** 317-358 (also `src/execution/manager.py:502, 509-520`)
- **Invariant:** INV-063, INV-064, INV-065, INV-083; Corrected Rules 9, 17
- **Phase/commit:** 05/09 / 63ca176
- **Known-prior:** NEW. Related: F-908/F-014 (cluster definition), L4 F-407 (no lock).

**Evidence:**
- The cluster sum counts only open positions with `position_side == candidate_position_side` (`portfolio.py:322-327`).
- The aggregate cap and count allow a second position (1% and 2).
- No symbol-uniqueness rule exists anywhere in `src/risk` or `src/execution` (grep).
- In one-way mode the entry is sent with `positionSide=BOTH` and no reduceOnly (`manager.py:502, 514`).
- p6, $1000 equity:
  - open BTC LONG (risk $5) plus candidate BTC SHORT ($4.9) gives `is_no_trade=False OK`
  - open BNB LONG plus candidate BNB LONG gives OK
  - open BNB LONG plus candidate BNB SHORT gives OK

**Expected:** At most one strategy position/plan per symbol. An opposite-direction plan on an open symbol is NO_TRADE in one-way mode (Corrected Rule 17 supports one-way only).

**Actual:**
- A SHORT entry of qty q against a LONG q position flattens it at the SHORT limit price. The user believes a new short is open.
- Plan A's closePosition SL/TP2 and plan B's closePosition SL stay armed against a different net position.
- The open-risk ledger counts $9.9 of risk on a flat book.
- The duplicate same-direction BNB case stacks size under two different SLs, both closePosition (the first to trigger closes both).

**Reproduction:** `python -B tmp/business_invariants/p6_same_symbol.py`.

**Impact:**
- An unplanned realized PnL and orphaned protectives.
- The journal and caps disagree with the exchange.
- F-701 (compare ignores size and sign) means reconciliation will not flag it.

**Why tests miss it:** Portfolio fixtures use distinct symbols or the same side.

**Remediation:** Add a symbol-level gate: reject a candidate whose symbol has an open position, a working entry or an approved-unplaced plan (both directions). Evaluate it under the serialized lock of Corrected Rule 9.

### F-304 — Live placement never checks TradePlan.status or evaluates the plan's invalidation rule; the backtest uses a different invalidation proxy

- **ID:** F-304
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED (code trace + grep)
- **Classification:** GAP
- **Category:** invalidation / plan lifecycle / parity
- **Component:** execution/manager, backtest/simulator
- **File:** `src/execution/manager.py` · **Lines:** 212-256, 362-452 (also `src/backtest/simulator.py:393-446`, `src/core/planner.py:425-433`)
- **Invariant:** INV-021 (order placement reads the plan status), INV-106 (closed-candle invalidation), INV-049, INV-012
- **Phase/commit:** 04/06/09 / 63ca176
- **Known-prior:** Partly overlaps KNOWN P15/F-007 (a live-price check against the SL), which is a different check (price, not the candle-close rule). The backtest red-candle proxy is quoted inside F-120/F-901 evidence but not reported as a parity defect. NEW as stated.

**Evidence:**
- The planner writes `invalidation_rule_json = {"basis":"CANDLE_CLOSE","level":str(stop_loss),...}` (`planner.py:425-433`).
- Grep: `invalidation_rule_json` is never read outside the planner, fixtures and mappers.
- `TradePlanStatus.INVALIDATED/SUPERSEDED/EXPIRED` is never read in `src/execution` or `src/approval` (grep `TradePlanStatus\.` shows no hits there).
- `_check_approval_authorizes_plan` checks only the Approval's status (`manager.py:241-248`).
- The backtest instead cancels on bar colour: `if direction == "LONG": if bar.close < bar.open: INVALIDATION_CANCEL` (`simulator.py:393-419`). This is unrelated to the plan's close-beyond-level rule.

**Expected:**
- Until expiry, a plan whose invalidation condition fired (a 1H close beyond the level) is INVALIDATED and cannot be placed or kept resting.
- Backtest, paper and live evaluate the same rule.

**Actual:**
- Live: an approved plan is placed up to expiry even if a candle already closed through the invalidation level. There is no invalidation monitor and no status check.
- Backtest: any bearish signal bar cancels a LONG, and a bullish bar cancels a SHORT, regardless of level.

**Reproduction:** `grep -rn "invalidation_rule_json\|TradePlanStatus\." src/` and read `simulator.py:393-446`.

**Impact:**
- Live places setups the strategy itself would have invalidated.
- Backtest trade selection differs systematically from live semantics (research validity, INV-012).

**Why tests miss it:** No test gives `execute_approved_plan` an INVALIDATED plan. Simulator invalidation tests pin the colour rule.

**Remediation:**
- Enforce `plan.status == APPROVED`/READY and evaluate `invalidation_rule_json` on the latest closed candle at placement, and periodically while the entry rests (cancel via `expire_pending_entry("invalidation")`).
- Implement the same rule in the simulator.

### F-305 — The backtest cannot run over history: one constraint snapshot with a 1 h TTL is judged against each bar's close, and the portfolio state is frozen for the whole run

- **ID:** F-305
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED (probe p7)
- **Classification:** DEFECT
- **Category:** backtest/live parity, research validity
- **Component:** backtest/simulator
- **File:** `src/backtest/simulator.py` · **Lines:** 713-719, 807-821 (also `src/risk/portfolio.py:296-306`)
- **Invariant:** INV-058, INV-012, INV-060, INV-063..066
- **Phase/commit:** 06 / 63ca176
- **Known-prior:** Related: the skipped 06-REVIEW CR-04 (run-level `now_utc` expiry clock, cited in F-901/F-120). The TTL/state issue is NEW.

**Evidence:**
- `evaluate_risk(... constraint_snapshot=constraint_snapshot, now_utc=bar.close_time_utc, ttl=ttl ...)` uses one snapshot per run (`simulator.py:714, 807-816`).
- `check_portfolio` rejects when `age > ttl or age < 0` (`portfolio.py:296-306`), with `ttl_seconds = 3600` in the fixtures and the registry.
- p7, on the real `phase6/intrabar_both_touched` case (250 bars, 2026-09-01..09-11):
  - as shipped, with observed 1 h before the only signal bar: `ENTRY_FILLED`
  - with the snapshot dated after the history (2026-09-29): `REJECT STALE_CONSTRAINTS`
  - with the snapshot at the start of the history: `REJECT STALE_CONSTRAINTS`
- `open_positions`, `daily_loss_quote` and `account_state` are parsed once (`:713-717`) and never updated as simulated trades fill or lose. Equity never compounds, and DAILY_STOP, the caps and the position count can never bind.

**Expected:**
- Point-in-time constraints: the metadata version with `observed_at ≤ bar` is chosen per bar, as `src/data/metadata.py` documents, without a wall-clock TTL in historical mode.
- The simulated portfolio (open risk, daily realized loss, equity) evolves with the simulated trades, so the same gates act as live.

**Actual:**
- A multi-month backtest either rejects every signal outside a 1 h window as STALE_CONSTRAINTS, or the operator must fake `metadata_observed_at_utc` per bar.
- Portfolio and daily gates are inert in research.

**Reproduction:** `python -B tmp/business_invariants/p7_backtest_ttl.py`.

**Impact:**
- The canonical backtest (the only acceptance evidence) cannot produce a valid historical run without an undocumented workaround.
- Where it does run, it overstates trade count and ignores daily-stop and cap behavior that live will enforce.

**Why tests miss it:** Every phase6 fixture pins `metadata_observed_at_utc` 1 h before its single signal bar and uses an empty position list.

**Remediation:**
- In historical mode, select `ConstraintSnapshot` by `observed_at ≤ bar.close` from versioned metadata, and drop the wall-clock TTL (keep TTL for live).
- Carry a simulated portfolio ledger (open risk per symbol and side, UTC-day realized loss, and optionally equity) through the loop, and feed it to `evaluate_risk`.

### F-306 — Backtest PnL deducts slippage as `quantity × rate` (no price factor); the skipped 06-REVIEW WR-13 is not in the P11 fix scope

- **ID:** F-306
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED (code + p1 column `btLoss$`)
- **Classification:** DEFECT
- **Category:** cost model units (backtest PnL)
- **Component:** backtest/simulator
- **File:** `src/backtest/simulator.py` · **Lines:** 650-661
- **Invariant:** INV-105, INV-011, INV-058; Corrected Rules 8, 19
- **Phase/commit:** 06 / 63ca176
- **Known-prior:** KNOWN 06-REVIEW WR-13 (skipped, "open a cross-phase item"). ORPHANED: the ROADMAP P11 goal (`ROADMAP.md:357`) fixes only `modeled_costs_per_unit`/sizing and does not mention `_apply_costs`. Related to F-962 (P11 scope) and F-004 (slippage model).

**Evidence:**
- `entry_fee = entry_price × qty × fee_rate_entry` and `exit_fee = exit_price × qty × fee_rate_exit` are correct.
- But `slippage = _mul(quantity, cost_model.expected_slippage)`, with the comment "(in quote currency)" (`simulator.py:650-654`).
- `expected_slippage = 0.0001  # 1 bps` (baseline-v3).
- Per unit, the code deducts 0.0001 USDT, against the correct 1 bp × price:

| Symbol | Price | Correct per unit | Ratio |
|---|---|---|---|
| BTC | 60,000 | 6.0 USDT | 60,000× under |
| ETH | 2,500 | 0.25 USDT | 2,500× under |
| XRP | 0.5 | 0.00005 USDT | 2× over |

- Per trade: BTC qty 0.008 carries 0.0000008 USDT of slippage instead of 0.48 USDT.
- p1 `btLoss$` versus `realSL$`, for example BTC $1000 at a 0.1% stop: 8.464 vs 8.961.

**Expected:** Slippage in quote = price × qty × rate on every taker fill, with the stop exit ≥ 2–5 bps plus a 3× stress run (Corrected Rule 19). The same unit is used in sizing and PnL.

**Actual:** Slippage is effectively zero for every live-5 symbol except XRP. The recorded net PnL, and hence expectancy and kill-gate evidence, is optimistic.

**Reproduction:** p1 output. Hand-check: `simulator._apply_costs` for qty 0.008, price 60000 gives `slippage_amount = 0.0000008`.

**Impact:**
- Research net R is biased upward by the missing slippage (0.1 bp × notional per side is not modeled).
- After P11 fixes sizing only, backtest PnL and sizing will disagree on units.

**Why tests miss it:** The phase6 fixtures use prices near 100, where the mistake is about 100× but tiny in absolute terms. No oracle compares the formula with price × qty × rate (L6 F-601).

**Remediation:** Add `_apply_costs` to the P11 scope. Compute `slippage = (entry_price + exit_price) × qty × slip_rate`, or per leg with a separate exit-stop rate, and regenerate the fixtures deliberately.

### F-307 — Fills that risk sizing accepted can fail protective TP sizing, which forces ENTRY_WITHOUT_PROTECTIVE and SAFE_MODE instead of a single-TP fallback

- **ID:** F-307
- **Severity:** LOW
- **Confidence:** CONFIRMED (probe p5)
- **Classification:** DEFECT
- **Category:** protective sizing / availability
- **Component:** execution/placement, execution/manager
- **File:** `src/execution/placement.py` · **Lines:** 221-275, 396-410 (also `src/execution/manager.py:920-933`)
- **Invariant:** INV-084, INV-057; Corrected Rule 16 ("If any leg is below minQty, use a single TP")
- **Phase/commit:** 09 / 63ca176
- **Known-prior:** The code duplication is L2 F-208, and the MIN_NOTIONAL-on-reduce-only point is A2's fact. The SAFE_MODE consequence and the quantification are NEW.

**Evidence:**
- `size_protectives_to_filled_qty` floors `filled × tp1_fraction` and rejects on `< min_quantity` or `× tp1 < min_notional` (`placement.py:397-410`).
- Binance exempts reduce-only orders from MIN_NOTIONAL (A2), so the notional arm is spurious for the reduce-only TP1.
- On a reject, `attach_protectives_to_fill` places only the SL and forces `ENTRY_WITHOUT_PROTECTIVE` plus SAFE_MODE (`manager.py:927-933, 870-900`).
- p5, with tp1 fraction 0.5 as used by the tests: 3 of 69 risk-accepted grid points hit this case:
  - BTC $500 at SL 3%: qty 0.001
  - BTC $500 at SL 4%: qty 0.001
  - BTC $1000 at SL 5%: qty 0.001
  - In each, the entry is accepted and TP sizing returns `MIN_QTY_REJECT`, then SAFE_MODE.
- Any partial fill smaller than 2 × minQty does the same.

**Expected:**
- If TP1 is below minQty, fall back to a single close-all TP (TP2) plus the SL.
- Do not apply MIN_NOTIONAL to reduce-only legs.
- Use MARKET_LOT_SIZE for triggered *_MARKET legs.

**Actual:** A protected position with a working SL halts all new entries (SAFE_MODE) and gets no TP at all.

**Reproduction:** `python -B tmp/business_invariants/p5_tp1_after_sizing.py`.

**Impact:**
- Routine at $500 on BTC and on small partial fills.
- The system parks in SAFE_MODE (in memory, auto-exit per L7 F-711) with an untaken target.
- Not a naked-position risk.

**Why tests miss it:** Attach tests use fills well above 2 × minQty.

**Remediation:**
- Implement the Corrected Rule 16 fallback.
- Drop the notional gate for reduce-only legs.
- Also check TP feasibility at plan/risk time, so infeasible ladders are resolved before the entry.

## Open Questions

1. **Composition owner (cross-lane L2).** F-302, F-303, F-304, the daily-loss producer and portfolio-ledger input all depend on who builds `risk_kwargs`/`gate_kwargs` at runtime (M1–M4 are missing). The fix phase for runtime composition should own:
   - the symbol/side/geometry assertions
   - the symbol-uniqueness gate
   - the invalidation monitor
2. **F-301 scope.** Is `baseline-v3` the parameter set intended for the paper soak epoch (F-957 says candidate sets use it)? If so, F-301 should block the soak start, together with P11.
3. **Kill gate (not deeply audited here).** I only skimmed `killgate.evaluate` sticky logic. The enable() link is KNOWN F-953. L6 F-604 covers the tests that assert it.
4. **Paper.** `run_paper_tick` shares the backtest risk path, but has no simulated fills or portfolio ledger. The paper-vs-backtest parity of F-305's frozen state therefore cannot yet be measured. Recheck when the 07-02 simulated-fill path exists.
5. **SL `workingType`.** The rounding of the SL toward the entry (safe for risk) combined with a MARK_PRICE trigger (KNOWN F-958/L5 F-507) means the stop in live differs from the backtest stop on two axes. Any P11/P13 re-baseline should fix both together.
