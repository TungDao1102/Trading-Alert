# Verification V5_invariants
| ID | Outcome | Final severity | Duplicate of | One-line reason |
|---|---|---|---|---|
| F-301 | CONFIRMED | HIGH (not CRITICAL) | - | With baseline-v3 the LONG zone runs S-0.6ATR..S+0.6ATR while SL = S-0.2ATR (1/3 of the zone is past the stop). The stop is 0.2 ATR (0.133% on BTC) from the zone-mid limit, and the swing window includes the evaluated bar, so a new 20-bar low triggers a "pullback". Sizing still bounds loss to the budget plus stop slippage, and no live path exists yet. |
| F-302 | CONFIRMED | HIGH (CRITICAL-class once composed; not CRITICAL today) | - | Probe: the same approved plan, hash and approval, with `candidate_position_side="SHORT"` or `constraint_snapshot.symbol="XRPUSDT"`, returns OK and places SELL@101 + BUY-stop@98 (or XRPUSDT orders). No symbol, side or SL-geometry cross-check exists. No runtime caller exists today. |

## F-301
- Outcome / final severity: CONFIRMED, HIGH. Does not qualify as CRITICAL.
- Independent evidence:
  - `src/core/planner.py:105-114` (trend-pullback LONG): zone = `swing_low ± zone_tolerance_atr*ATR` and SL = `swing_low - sl_buffer`. `planner.py:378-379` sets `entry_min = zone_lower - entry_buffer` and `entry_max = zone_upper + entry_buffer`. `planner.py:383` sets `entry_ref` = mid = swing_low. SHORT mirrors this at `planner.py:160-169`.
  - `params/trend-pullback/baseline-v3.toml`: zone_tolerance_atr=0.5, entry_buffer_atr=0.1, sl_buffer_atr=0.2, minimum_rr=2.0, risk_rate=0.005, fees 2+5 bps, slip 1 bp.
  - `src/core/features.py:187`: `window = candles[i - lookback + 1 : i + 1]`, which includes bar i. `src/core/strategy.py:157-158` fires LONG when `support_lower <= last.low <= support_upper`, both built from that same swing_low.
  - Probe `tmp/verify_V5_invariants/probe_f301.py` (S=60000, H=62000, ATR=400, baseline-v3):
    - `entry_min=59760 entry_max=60240 entry_ref(limit)=60000 SL=59920 TP1=62000`
    - `entry_min < SL: True; share of zone beyond SL = 0.333`
    - `stop distance = 80 = 0.2 ATR = 0.133%; RR=25`. The minimum_rr=2 gate practically never fires.
    - `modeled cost/unit=48 -> cost/stop = 0.60`
    - `equity 1000: budget 5.00, qty 0.0391 BTC, notional 2344 (2.34x); extra 0.2%/0.5% stop slippage -> loss 9.69/16.72`. `equity 500: 4.84/8.36 vs budget 2.50`.
    - 20 bars with the last low at a new minimum 59800: `swing_low at last bar = 59800 == last bar low -> in support zone: True`.
- Counter-checks:
  - Live and risk use only the zone mid (`execution/placement.py:143`, `risk/gating.py:71`), so no live limit is ever placed below the SL. The "33% beyond stop" part is a plan/zone-semantics defect, not a direct order-price defect.
  - It does reach the backtest. `src/backtest/simulator.py:449` treats "zone touched" as `bar.low <= entry_max` and then fills at `entry_ref` (`:479-482`). A LONG therefore gets filled at S even when the low stayed up to 0.6 ATR above S. These are phantom, optimistic fills that inflate research evidence.
  - Searched src and params for a minimum-stop-distance or cost-to-risk guard (`min_stop|stop_distance|cost_to_risk|max_cost`): none exist. Costs only shrink quantity (`risk/gating.py:100`).
  - Family sheet `docs/research/families/trend-pullback.md` L86 says the stop goes "on the wrong side of the structure that justified the entry". §5 row 2 (L116-117) says "a swing is confirmed at the close of bar t+N … Decision-making uses confirmed swings only". The code violates both. L152 ("S2 ATR buffer below swing low") is literally satisfied, which is the only spec ambiguity. The sheet is marked HYPOTHESIS/NOT FROZEN. I could not find the "Corrected Rule 3" text anywhere in the snapshot docs.
- Notes / CRITICAL assessment:
  - Loss per trade is still sized to the stop plus modeled costs.
  - Reaching several times the intended risk needs roughly 0.3-0.5% STOP_MARKET slippage on a live-5 symbol. That is a stress event, not a routine path, and in dollars it is $10-17 on $1,000.
  - No approve-to-execute composition exists. Not CRITICAL.
  - Keep HIGH: the defect corrupts the strategy's economics (cost is about 60% of risk, entries into new lows, phantom backtest fills) and therefore the kill-gate evidence.

## F-302
- Outcome / final severity: CONFIRMED, HIGH. It is CRITICAL-class (wrong-direction or wrong-symbol live order) the moment a runtime composition calls it, but not CRITICAL today because it is unreachable.
- Independent evidence:
  - `src/domain/trade_plan.py:59-78`: TradePlan has no `symbol` or `direction` field.
  - `src/execution/manager.py`:
    - `:444-445`: gates use `candidate_symbol=risk_kwargs["constraint_snapshot"].symbol` and `candidate_position_side=risk_kwargs["candidate_position_side"]`.
    - `:470,497-498`: `entry_side = "BUY" if candidate_side == "LONG" else "SELL"`.
    - `:512,547`: the order symbol is `constraint_snapshot.symbol`.
    - The only symbol check is `_require_live5_symbol` (`:56-60,457`), which is a whitelist, not a comparison with the plan.
  - `_check_approval_authorizes_plan` (`:212-253`) compares only plan_hash, trade_plan_id and expiry.
  - `risk/gating.py:99` and `risk/sizing.py:59` use `abs(entry_ref - SL)`, so a flipped side sizes identically and passes.
  - Probe `tmp/verify_V5_invariants/probe_f302.py` reuses the phase-9 golden fixture `tests/fixtures/phase9/placement_sequences/input.json` (BTCUSDT LONG, zone 100-102, SL 98, equity 1000):
    - baseline -> `OK`: place_entry BUY 3.311 @101; SL SELL trigger 98.
    - side flipped (`"SHORT"`) -> `OK`: place_entry **SELL** 3.311 @101; SL **BUY** trigger 98. The stop sits below a short entry, so it would trigger or be rejected immediately.
    - symbol swapped (`XRPUSDT`) -> `OK`: place_entry BUY 3.311 **XRPUSDT** @101; SL SELL XRPUSDT trigger 98.
- Counter-checks:
  - Searched non-test code for callers of `execute_approved_plan(`: none. Only `tests/test_execution_manager.py` and `tests/test_execution_attach.py` call it, so the path is library-level only.
  - `plan_hash` covers `signal_id` (`planner.py:52-77`), and `make_signal_id` includes symbol and direction (`strategy.py`). The approved identity therefore does bind symbol and direction, but the manager never loads the Signal to compare.
  - `attach_protectives_to_fill` (`manager.py:809-946`) takes `candidate_position_side` and `constraint_snapshot.symbol` from the caller in the same way. Same root; the claim scope includes it.
  - The cited "INV-044" text does not exist in the snapshot docs. The claim stands on the approval-safety constraint (the approved plan must be the thing placed).
- Notes:
  - Fix direction: derive side from SL-vs-entry geometry and/or load the Signal by `trade_plan.signal_id`, then reject on any mismatch with `constraint_snapshot.symbol` or `candidate_position_side` before Gate 4.
  - Once M1-M4 composition lands, re-rate this as CRITICAL if the check is still missing.
