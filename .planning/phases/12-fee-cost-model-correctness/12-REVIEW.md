---
phase: 12-fee-cost-model-correctness
reviewed: 2026-09-30T00:00:00Z
depth: deep
files_reviewed: 26
files_reviewed_list:
  - params/breakout-retest/baseline-v5.toml
  - params/range-mr/baseline-v5.toml
  - params/trend-pullback/baseline-no-trade-v3.toml
  - params/trend-pullback/baseline-simple-trend-v3.toml
  - params/trend-pullback/baseline-v5.toml
  - scripts/decision_alignment/bookkeeping.py
  - scripts/decision_alignment/params.py
  - scripts/gen_phase6_fixtures.py
  - scripts/verify_decision_alignment.py
  - src/adapters/binance_usdm.py
  - src/backtest/__init__.py
  - src/backtest/binding.py
  - src/backtest/costs.py
  - src/backtest/simulator.py
  - src/domain/enums.py
  - src/domain/registry.py
  - src/execution/manager.py
  - src/paper/freeze.py
  - src/paper/loop.py
  - src/risk/__init__.py
  - src/risk/cost_guards.py
  - src/risk/cost_rates.py
  - src/risk/gating.py
  - src/risk/live_commission.py
  - src/risk/sizing.py
  - src/risk/types.py
findings:
  critical: 0
  warning: 5
  info: 6
  total: 11
status: issues_found
---

# Phase 12: Code Review Report

**Reviewed:** 2026-09-30
**Depth:** deep
**Files Reviewed:** 26
**Status:** issues_found

## Summary

The core cost model is sound. The per-unit cost producer (`cost_rates.py`) is price-linear, Decimal-only and range-checked. The adverse-edge sizing in `gating.py` is consistent with `sizing.py` and `quantization.py`. The SizedResult cost trail survives `check_portfolio`, which passes the same object through. Fee handling is fail-closed: the adapter parse never turns an unknown rate into zero, `resolve_live_cost_rates` returns NO_TRADE for a missing, wrong-symbol or stale commission, and `cost_rates_from_model` refuses legacy 7-key models instead of defaulting the exit slippage. I checked the adapter against the installed SDK (`user_commission_rate(symbol, recv_window=None)`, Strict-str fields) and it matches. I found no place where a missing value silently becomes a zero fee or zero slippage. The eight legacy `cost_model_hash` values are asserted in tests, and the canonical-text rendering is correct for exponent, trailing-zero and negative-zero spellings.

There are no blockers. The five warnings are all defense-in-depth gaps, where a caller mistake or malformed input passes a check that should have stopped it. Two of them (WR-01, WR-02) touch the live money path, so I would fix them before Phase 24 wires the live path.

## Warnings

### WR-01: Live cost-rate gate trusts a string label, not the resolver's verified output

**File:** `src/execution/manager.py:438-442` (also `src/risk/cost_rates.py:55-78`, `src/risk/live_commission.py:152-162`)
**Issue:** Gate 4a only checks `cost_rates.fee_source == "ACCOUNT_MAX"`. `CostRates` is a public frozen dataclass, so any caller can build `CostRates(..., fee_source=FEE_SOURCE_ACCOUNT_MAX)` from the parameter fees and pass the gate without ever calling `resolve_live_cost_rates`. The manager also never checks that the commission is fresh at placement time. Freshness is checked once at resolution, against a TTL of up to 3600 s. Approval and placement happen later, and `now_utc` is not compared against the commission's `observed_at_utc`. The manager also cannot tell whether the commission was for `constraint_snapshot.symbol`. This is the F-962 protection the phase exists to add, and it depends on discipline outside the function. The docstring says the gate "never falls back to the parameter rate", but the check cannot prove that.
**Fix:** Make provenance unforgeable and re-check it at the point of use. Either of these works:
```python
# Option A: manager takes the observation and re-resolves with its own clock
res = resolve_live_cost_rates(
    parameter_rates=risk_kwargs["cost_rates"],   # PARAMETER-source rates
    account_commission=account_commission,        # required kwarg
    candidate_symbol=risk_kwargs["constraint_snapshot"].symbol,
    now_utc=now_utc, ttl=commission_ttl)
if res.is_no_trade:
    return ExecutionOutcome(True, res.reason_code)
risk_kwargs = {**risk_kwargs, "cost_rates": res.rates}
```
Option B keeps the current shape. `LiveCostRatesResult` carries `symbol` and `observed_at_utc`, the manager requires that object, and it re-runs the age and symbol test against its own `now_utc`.

### WR-02: Adverse-edge sizing does not validate plan geometry; `abs()` masks inverted or mismatched plans

**File:** `src/risk/gating.py:86-116` (and `src/risk/sizing.py:65`, `src/domain/trade_plan.py:80-105`)
**Issue:** The rule "LONG uses `entry_max`, SHORT uses `entry_min`, so loss at the stop is at most `allowed_risk`" only holds if `entry_min <= entry_max` and the stop lies beyond the far edge of the zone on the correct side. `TradePlan.__post_init__` checks types and UTC only, with no price positivity, ordering or side geometry. `size_and_quantize` takes `candidate_position_side` from the caller and uses `abs()` for the stop distance. Examples:
- A swapped zone (`entry_min > entry_max`) makes a LONG size off the lower price. The stop distance is too small and the quantity too large.
- A LONG whose stop sits inside the zone, or a candidate side that disagrees with the plan geometry, is sized without complaint.
The `abs()` hides the sign error that would otherwise show up.
**Fix:** Validate before sizing and return a NO_TRADE (or raise) on any violation:
```python
if trade_plan.entry_min_price > trade_plan.entry_max_price: -> EXCHANGE_CONSTRAINT
if side == "LONG"  and not trade_plan.stop_loss_price < trade_plan.entry_min_price: -> EXCHANGE_CONSTRAINT
if side == "SHORT" and not trade_plan.stop_loss_price > trade_plan.entry_max_price: -> EXCHANGE_CONSTRAINT
```
Fail closed with a reason code, so a malformed plan never reaches sizing.

### WR-03: `simulator.run` and `run_paper_tick` size with a fixture cost model that is never bound to the registry set

**File:** `src/backtest/simulator.py:750, 838-858`; `src/paper/loop.py:333, 508-524`
**Issue:** Both entry points build `cost_model` from `case_input["cost_model"]`. The guard thresholds come from `parameter_set.params` in the registry. Phase 12 makes this a two-source split within one `evaluate_risk` call. Fee and slippage rates come from the fixture dict, while `min_stop_distance_rate` and `max_cost_to_risk` come from the registry. `assert_cost_model_binds_registry` runs only in `experiment.assemble` (`experiment.py:208`) and `paper.freeze.pin_stream_epoch`. Neither `run` nor `run_paper_tick` calls it. Sizing can therefore use costs that disagree with the pinned `parameter_set_hash`, and the hash on the output record is the fixture's own. The reference to the `v5` registry identity does not enforce that the fixture agrees with it.
**Fix:** After `load_parameter_set` in both functions, add:
```python
assert_cost_model_binds_registry(parameter_set, cost_model)
```
This is cheap and raises `CostModelBindingMismatch` before any sizing.

### WR-04: Registry loader accepts NaN/Infinity for unranged decimal keys, and raises the wrong exception for ranged ones

**File:** `src/domain/registry.py:320-383` (`_check_value_range`, `_check_param_types`)
**Issue:** I loaded `baseline-v5.toml` with modified values. `risk_rate = nan`, `risk_rate = inf` and `minimum_rr = nan` all load successfully as `Decimal('NaN')` / `Decimal('Infinity')`. `max_cost_to_risk = nan` and `exit_slippage_rate = nan` raise `decimal.InvalidOperation` from `Decimal('NaN') < 0`, not `StrategyKeyOutsideRegistry`. Callers that catch the registry exception, and the PA-07 gate's `except Exception` message, do not get the documented contract. The new unit-error guard (F-028, D-04) is therefore not a complete input-validation boundary for exchange-sensitive values, and non-finite values still reach sizing and hashing.
**Fix:** Reject non-finite values first, for every `INT_KEYS` and `DECIMAL_KEYS` entry:
```python
number = Decimal(value)
if not number.is_finite():
    raise StrategyKeyOutsideRegistry(f"{path}: parameter {key!r} must be finite, got {value}")
```
Put this at the top of `_check_value_range` (or at the start of the numeric branch of `_check_param_types`).

### WR-05: Cost-guard input validation raises `InvalidOperation` and accepts floats/bools, contradicting the documented contract

**File:** `src/risk/cost_guards.py:26-50`; `src/backtest/costs.py:315-334`
**Issue:** `validate_guard_rates` documents "ValueError: a threshold is outside its range (NaN and infinity included)". I ran it: `Decimal('NaN')` raises `decimal.InvalidOperation`, not `ValueError`. Infinity does raise `ValueError`. `guard_rates_from_params` does `Decimal(str(params[key]))`. That accepts a float (`0.003` becomes `Decimal('0.003')`) despite the Decimal-only rule, and turns `True` into `InvalidOperation [ConversionSyntax]`. It also checks nothing about finiteness or range itself. The NaN/float case cannot be reached from the TOML registry today, but the helper takes a bare `Mapping`.
**Fix:** In `validate_guard_rates`, check `min_stop.is_finite()` and `max_ratio.is_finite()` before comparing, and raise `ValueError`. In `guard_rates_from_params`, require `isinstance(v, (Decimal, int)) and not isinstance(v, bool)`, and call `validate_guard_rates` on the result so bad values fail at the boundary with one exception type.

## Info

### IN-01: Adapter/resolver reject negative maker rates although the maker rate is unused; symbol argument not validated

**File:** `src/adapters/binance_usdm.py:1525-1559`, `src/risk/live_commission.py:60-66, 85`, `src/adapters/binance_usdm.py:1268-1304`
**Issue:**
- `_require_commission_rate` and `_require_rate` reject any negative rate. Binance market-maker tiers can have a negative (rebate) maker rate. The maker rate is carried but never used for sizing, so such an account can never fetch a valid commission and fails closed for no reason. This is low impact for the stated capital.
- `Decimal(value)` also accepts Unicode digits and underscores (`Decimal("1_0")` is 10, and Arabic-Indic digits parse). Strings from the exchange should be matched against `^\d+(\.\d+)?$` first.
- `user_commission_rate(symbol)` does not check that `symbol` is a non-empty uppercase string before spending a weight-20 call. The response-symbol check does fail closed on any mismatch.
**Fix:** Only require the taker rate to be non-negative and treat the maker rate as `abs(x) <= MAX_RATE`. Add an ASCII regex before `Decimal(...)`. Validate `symbol` up front.

### IN-02: `MAX_RATE` (0.01) is defined in four places

**File:** `src/domain/registry.py:140-141`, `src/risk/cost_rates.py:38`, `src/adapters/binance_usdm.py:1528`, `scripts/decision_alignment/params.py:135` (`PHASE12_MAX_RATE`)
**Issue:** The layering justification (adapter and domain cannot import risk) is fine, but four independent copies of a safety ceiling can drift. Only a comment ties them together.
**Fix:** Put the constant in a neutral module such as `src/core/` that domain, risk and adapters may all import, or add a test that asserts the four values are equal.

### IN-03: `cost_model_hash` "byte-locked" wording overstates what is preserved; no scheme marker in the payload

**File:** `src/backtest/costs.py:49, 92-105`; `src/domain/canonical.py:48-49`
**Issue:** The old hash ran `Decimal` values through `str()` and kept the spelling. The new payload uses canonical text. The eight registry hashes are unchanged (asserted per D047), but any hash computed before this change from a non-canonical spelling, such as a fixture `"1.0"` for `partial_fill_fraction`, now recomputes differently. `verify_experiment` would report that as `cost_model_hash != recorded`. D047 accepts this. The comment "every legacy seven-key model keeps its byte-locked hash" is only true for canonical spellings, and nothing in the payload lets a verifier tell an old-scheme hash from a new-scheme mismatch.
**Fix:** Reword the comment to "for canonical spellings". If persisted experiment records exist outside the regenerated fixtures, consider a payload version key so old-scheme records fail with a clear message.

### IN-04: Stale purity and docstring text

**File:** `src/backtest/__init__.py:3-7`, `src/backtest/costs.py:14-16`, `src/domain/enums.py:126-131`
**Issue:**
- The backtest package docstring says it imports "stdlib + Decimal + src/core/_decimal.py only". `costs.py` now imports `src.risk.cost_rates` and `src.domain.canonical`, and `binding.py` imports `src.domain.registry`.
- The `RejectionReason` docstring still says "Use the canonical enum names above".
**Fix:** Update the docstrings to match the real import graph.

### IN-05: Runtime invariants enforced with `assert`

**File:** `src/backtest/simulator.py:873-875`, `src/backtest/costs.py:79`
**Issue:** `assert sized.modeled_costs_per_unit is not None` guards a value that is passed into a Decimal-typed field on the next call. Under `python -O` the check disappears and `None` would flow into the TradeRecord. `_canonical_decimal_text` has a similar `assert isinstance(exponent, int)`.
**Fix:** Replace with explicit `if ... is None: raise RuntimeError(...)`.

### IN-06: Guard-rate loading in the simulator is lazy, so fail-closed behaviour depends on data; `min_stop_distance_rate` is dead config

**File:** `src/backtest/simulator.py:838-841`, `src/paper/loop.py:508-511`, params `baseline-*-v5.toml`
**Issue:**
- `cost_rates_from_model` and `guard_rates_from_params` run inside the per-bar loop, after a plan exists. A legacy set with no plan on any bar completes without error, while the same set with one plan raises `ValueError`. The failure depends on the market data.
- With `max_cost_to_risk = 0.15` and the 14 bps modeled round trip, the implied minimum stop is about 0.79% of price. `min_stop_distance_rate = 0.003` can never be the binding guard. The TOML headers record this for ratification. It is a knowingly redundant parameter, not a bug.
- `sl_distance == 0` returns `EXCHANGE_CONSTRAINT` from `size_position` rather than `STOP_TOO_TIGHT`. That is defensible, but the reason code is less informative for the zero-stop case.
**Fix:** Hoist both helper calls above the loop in both entry points so a legacy set fails on the first call. Resolve the ratification of D046 for the redundant floor, or drop it.

---

_Reviewed: 2026-09-30_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
