---
phase: 06-backtest-simulator-experiment-registry
reviewed: 2026-09-26T00:00:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - src/backtest/__init__.py
  - src/backtest/costs.py
  - src/backtest/simulator.py
  - src/backtest/experiment.py
  - src/backtest/report.py
  - src/domain/registry.py
  - scripts/gen_phase6_fixtures.py
  - params/trend-pullback/baseline-no-trade-v1.toml
  - params/trend-pullback/baseline-simple-trend-v1.toml
  - tests/test_backtest_simulator.py
  - tests/test_backtest_experiment.py
  - tests/test_backtest_report.py
  - tests/test_domain_no_float.py
findings:
  critical: 8
  warning: 10
  info: 4
  total: 22
status: issues_found
---

# Phase 06: Code Review Report

**Reviewed:** 2026-09-26T00:00:00Z
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Reviewed the Phase 6 backtest package (`simulator.py`, `costs.py`, `experiment.py`, `report.py`), the `registry.py` touch-point, both baseline TOMLs, the fixture generator, and all four test files at standard depth with focus on determinism, lookahead, fail-closed gaps, Decimal discipline, quantization parity, and content-hash identity. The architecture is sound (pure modules, frozen dataclasses, canonical hashing), but the review finds 8 Critical defects that break correctness or reproducibility claims: an `IndexError` crash on empty intrabar, trade-ID collisions, a tautological reproduce/verify tripwire, a global-clock expiry gate that mis-resolves multi-bar backtests, trailing-precision destruction on the registry→cost path, experiment-ID collisions across run_type/strategy, unenforced baseline guarantees, and a wall-clock default inside the report digest. A further 10 Warnings and 4 Info items cover dropped TP2, funding hardcoding, integer-truncated coverage, coupled bootstrap RNG streams, unpinned Decimal arithmetic, CWD-dependent registry resolution, and weak tests that mask several of the above.

## Critical Issues

### CR-01: Empty intrabar list crashes with IndexError instead of failing closed

**File:** `src/backtest/simulator.py:156-222`
**Issue:** `resolve_intrabar` treats `None` as missing (fallback) but an empty list `[]` falls through the `for` loop and hits `intrabar[-1].close` (line 219), raising `IndexError`. An empty 1m payload (valid JSON, zero candles) is the most likely real-world shape of "no coverage" and must resolve to the SL-first fallback with `fallback_applied=True`, never crash the whole run. The simulator's fail-closed contract (D-01 + Phase-2 D-09) is violated on this edge.
**Fix:**
```python
if intrabar is None or len(intrabar) == 0:
    return IntrabarOutcome(
        exit_kind="SL",
        price=stop_loss,
        fallback_applied=True,
        coverage_note="1m_intrabar_missing",
    )
```

### CR-02: Trade-ID payload omits bar time, symbol, and quantity — collisions across bars/fractions

**File:** `src/backtest/simulator.py:500-509`
**Issue:** `_make_record` hashes only `{trade_plan_id, entry_kind, entry_price, exit_kind, exit_price, outcome_kind, reason_code}`. It does not bind `symbol`, `bar.close_time_utc`, `quantity`, or `partial_fill_fraction`. Consequences: (a) two fills of the same plan at different fractions (0.5 vs 0.9) share `entry_kind="PARTIAL_FILL"` and the same price, hence the same `trade_id`; (b) any planner that reuses a `trade_plan_id` across bars yields duplicate trade IDs; (c) the patched fields (`symbol`, `parameter_set_hash`, `realized_risk`, `modeled_costs_per_unit` via `_patch_record_metadata`) are applied AFTER the ID is computed, so the ID does not cover the record's own content. Content-hash identity is broken.
**Fix:**
```python
payload = {
    "trade_plan_id": trade_plan.trade_plan_id,
    "symbol": direction_symbol,  # pass bar.symbol in
    "bar_close_time_utc": bar_close_iso,  # pass in, do not hash without time
    "entry_kind": entry_kind,
    "entry_price": entry_price,
    "quantity": quantity,
    "exit_kind": exit_kind,
    "exit_price": exit_price,
    "outcome_kind": outcome_kind,
    "reason_code": reason_code,
}
# Compute trade_id AFTER all patched fields are known, or include them in payload.
```

### CR-03: reproduce/verify_experiment tripwire is tautological and corrupts types

**File:** `src/backtest/experiment.py:236-275`
**Issue:** Three compounding defects: (a) `reproduce()` never reads `record` — it runs whatever `simulator_inputs` it is handed, so "re-running the recorded six-field tuple" is unimplemented; passing candidate inputs with a baseline record still "reproduces". (b) `verify_experiment()` calls `reproduce()` twice with the SAME dict, so it can only ever compare the simulator against itself in-process; cross-version engine drift (the stated purpose, "runtime tripwire") is undetectable — the check always passes. (c) `reproduce()` rebuilds records via `TradeRecord(**t)` where `t` comes from `run()`'s `to_dict()` (Decimals already stringified, datetimes already ISO strings). The reconstructed `TradeRecord` therefore holds `str` where the type says `Decimal | None`/`datetime | None`, with no parsing. Downstream `to_dict()` then passes strings through unchanged, so digests look stable while the objects are mistyped (breaks `_apply_costs`-style arithmetic and any `isinstance Decimal` guard on a reproduced record).
**Fix:**
```python
def reproduce(record, *, simulator_inputs):
    # 1. Assert inputs bind to the record: parameter_set_id/hash,
    #    strategy_version, cost_model_hash must match record fields;
    #    raise ExperimentReproducibilityBroken otherwise.
    # 2. Run simulator, then parse each trade dict back to typed
    #    fields (Decimal(...), datetime.fromisoformat(...)) before
    #    constructing TradeRecord.
def verify_experiment(record, *, simulator_inputs):
    # Compare reproduce digest against the record's stored
    # result digest (persisted at assemble time), not against a
    # second identical in-process run.
```

### CR-04: Expiry gate uses one global fixture clock for every bar

**File:** `src/backtest/simulator.py:647, 312, 747-753`
**Issue:** `_entry_now_utc = now_utc` is captured once from the fixture and reused for every bar's `_resolve_entry` expiry check (`now_utc >= trade_plan.expiry_utc`), while `evaluate_risk` correctly receives `now_utc=bar.close_time_utc` (line 722). In any multi-bar backtest the fixture `now_utc` is the END of the dataset, so every early-bar signal whose `expiry_utc` (source close + `signal_expiry_hours`) predates the dataset end resolves `EXPIRED` even though its limit window was open at its own bar time. Single-trigger fixtures pass (trigger close + 4h > fixture now), masking the bug. The comment on lines 642-646 rationalizes the global clock as intentional ("WR"), but the effect is systematic over-expiry of early signals — a correctness defect, and a clock inconsistency between the risk gate and the entry gate on the same bar.
**Fix:**
```python
# Resolve expiry against the bar being replayed, not the fixture wall clock:
entry_record = _resolve_entry(
    ...,
    now_utc=bar.close_time_utc,  # same clock passed to evaluate_risk
    ...,
)
```

### CR-05: build_cost_model destroys trailing precision for Decimal inputs

**File:** `src/backtest/costs.py:118-134`
**Issue:** `Decimal(str(cost_dict[k]))` round-trips through `str()`. For string inputs (`"0.00020"`) precision survives, so the precision-discipline test passes; but for `Decimal` inputs — exactly what `ParameterSet.params` holds after registry normalization (`Decimal("0.00020")` preserved via raw-string parsing) — `str(Decimal("0.00020"))` is `"0.0002"`, silently dropping the trailing zero before hashing. The registry preserves `1.50 ≠ 1.5` (D-12) while the cost path collapses them, so a cost model built from the registry hashes differently from the same model built from TOML strings. Two construction paths, two hashes, one "canonical" `cost_model_hash`.
**Fix:**
```python
def _coerce_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value  # never round-trip through str()
    if isinstance(value, str):
        return Decimal(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    raise TypeError(...)
```

### CR-06: experiment_id omits run_type and strategy_id — cross-experiment collisions

**File:** `src/backtest/experiment.py:202-212`
**Issue:** The `identity_payload` hashed into `experiment_id` contains `strategy_version`, `parameter_set_hash`, `data_snapshot_id`, `code_version`, `cost_model_hash`, time range, and universe hash — but NOT `run_type` or `strategy_id`. A `CANDIDATE` and a `BASELINE_NO_TRADE` run over otherwise identical inputs, or two different strategies sharing `strategy_version="v2.0.0"`, produce the SAME `experiment_id` while meaning different things. The six-field identity claim in the module docstring is not what is hashed.
**Fix:**
```python
identity_payload = {
    "strategy_id": strategy_id,
    "strategy_version": strategy_version,
    "parameter_set_hash": ...,
    "data_snapshot_id": ...,
    "code_version": ...,
    "cost_model_hash": ...,
    "run_type": run_type,  # CANDIDATE vs baselines must differ
    ...
}
```

### CR-07: Baseline runners guarantee nothing — degenerated-params claim is unenforced

**File:** `src/backtest/experiment.py:293-320`
**Issue:** `baseline_no_trade` and `baseline_simple_trend` docstrings promise "minimum_rr=100 forces every plan to fail" / "looser config emits single-direction trades", but the bodies just call `simulator_run(case_input)` and filter. There is no check that `case_input["parameter_set_id"]` is the baseline set, no assertion on `minimum_rr`, no registry cross-check. Passing candidate params to `baseline_no_trade` returns filled trades mislabeled as a baseline comparison — the BACKTEST_SPEC §9 gate rests on caller discipline with zero fail-closed enforcement.
**Fix:**
```python
def baseline_no_trade(case_input):
    ps = load_parameter_set(case_input["strategy_id"], case_input["parameter_set_id"])
    assert Decimal(str(ps.params["minimum_rr"])) >= Decimal("100"), "not a no-trade baseline"
    ...
```

### CR-08: Report digest defaults to wall-clock time — rebuilds are non-reproducible

**File:** `src/backtest/report.py:552-553`
**Issue:** `build()` defaults `built_at_utc=None` to `datetime.now(UTC)`, and `UncertaintyReport.digest()` includes `built_at_utc` (line 363). Any two builds of the same trades/seeds at different times hash differently, violating the determinism requirement (same inputs = byte-identical outputs). Tests mask this by always passing `_FIXED_BUILT_AT_UTC`. A "pure" module must not read the wall clock on its digest path; the timestamp must be an explicit required input (fail closed when absent).
**Fix:**
```python
def build(*, ..., built_at_utc: datetime) -> UncertaintyReport:
    _require_utc_aware(built_at_utc, "built_at_utc")  # no None default
```

## Warnings

### WR-01: Closed-snapshot prefix built from unsorted input order

**File:** `src/backtest/simulator.py:659, 665-666`
**Issue:** Iteration is over `sorted_bars` but each bar's `closed_setup`/`closed_context` is filtered from the ORIGINAL unsorted `strategy_bars`/`context_bars` lists, preserving input file order rather than time order. If a fixture ever lists bars out of order, `strategy.evaluate` sees a differently-ordered prefix per bar than a sorted replay would, breaking prefix-invariance. Also O(n²) re-filter per bar (out of scope for perf, but the order-dependence is a correctness smell).
**Fix:** Sort once up front (`strategy_bars_sorted`, `context_bars_sorted`) and slice by index instead of re-filtering the unsorted lists.

### WR-02: TP2 silently dropped — intrabar only resolves SL/TP1/EOD

**File:** `src/backtest/simulator.py:156-222, 286-289`
**Issue:** `IntrabarOutcome.exit_kind` documents `"SL" | "TP1" | "TP2" | "EOD"` and `TradeRecord.exit_kind` repeats TP2, but `resolve_intrabar` only ever returns SL/TP1/EOD and `_parse_tp1` only reads `tp1` from `take_profit_json`. A plan with a TP2 leg never realizes it; there is no error, no note, no coverage flag — the leg is silently ignored in PnL.
**Fix:** Either implement TP2 resolution (parse full TP ladder, walk intrabar against SL/TP1/TP2) or remove TP2 from the documented enums so the gap is explicit.

### WR-03: Funding/slippage-model/spread assumptions hardcoded away

**File:** `src/backtest/simulator.py:576-577`, `src/backtest/costs.py:142-162`
**Issue:** `_apply_costs` sets `funding = Decimal("0")` unconditionally while `funding_treatment="ADDITIVE"` is recorded on the cost model and hashed; `slippage_model` and `spread_fill_assumptions` are validated as non-empty strings but never read. `modeled_costs_per_unit` is side-independent despite taking `side` (raises on bad side, then ignores it). The hashed cost assumptions therefore do not affect realized PnL — two cost models differing only in funding/slippage semantics hash differently yet simulate identically.
**Fix:** Wire each hashed assumption into the math or narrow `COST_KEYS` to what the simulator actually consumes; at minimum branch funding on `funding_treatment` instead of hardcoding zero.

### WR-04: Baseline TOMLs omit 4 of 7 cost keys — cost truth lives in two places

**File:** `params/trend-pullback/baseline-no-trade-v1.toml`, `params/trend-pullback/baseline-simple-trend-v1.toml`
**Issue:** Both files carry only `fee_rate_entry/fee_rate_exit/expected_slippage` and omit `funding_treatment`, `slippage_model`, `spread_fill_assumptions`, `partial_fill_fraction` (all in `STRATEGY_KEYS` since plan 06-02). They still load (whitelist ≠ required), but the simulator's `CostModel` comes from the fixture `cost_model` dict, not the registry — so `parameter_set_hash` and `cost_model_hash` are computed from disjoint sources. The plan-06-02 goal ("cost assumptions versioned so two experiments with different constants cannot share a hash") holds only if callers keep the two files in sync manually.
**Fix:** Add the four missing keys to both baseline TOMLs (values matching the fixture `COST_MODEL`) and document which source is canonical when they disagree.

### WR-05: Intrabar coverage percent truncated to integer

**File:** `src/backtest/report.py:783`
**Issue:** `coverage_pct = _q((n_trades - fallback_count) * 100 // n_trades)` uses integer `//` before quantizing, flooring e.g. 2/3 coverage to `66` instead of `66.67`. Tests only cover the 100%/0% extremes so the truncation is invisible. Exchange-sensitive reporting should use exact Decimal division (`_div`) consistent with the rest of the module.
**Fix:**
```python
coverage_pct = _div(_q((n_trades - fallback_count) * 100), _q(n_trades))
```

### WR-06: Bootstrap means and drawdown resamples share the identical RNG stream

**File:** `src/backtest/report.py:625-646`
**Issue:** `_stationary_block_bootstrap_means(..., seed)` and `_resample_drawdowns(..., seed)` each construct `random.Random(seed)` from the SAME seed, so both resampling stages consume the identical pseudo-random sequence. The drawdown distribution is not an independent resample — it is deterministically coupled to the expectancy resample. Statistically the two sections should either share one continued stream or use domain-separated seeds (e.g. `seed` and `seed ^ 0x9E3779B9`).
**Fix:** Thread a single `random.Random(seed)` through both stages, or derive `drawdown_seed = seed + 1` with a comment.

### WR-07: Report statistics bypass the pinned-precision helpers

**File:** `src/backtest/report.py:379-538`
**Issue:** The module claims the Phase-4 D-10 purity precedent, but `_decimal_mean` (`total / _q(n)`), `_decimal_median` (`(a+b) / Decimal("2")`), `_quantile` (`* frac`, `q * _q(last_idx)`), and `_max_drawdown` (`cum + _q(r)`, `peak - cum`) use raw Decimal operators under the ambient context instead of `_div/_add/_sub/_mul` with `prec=28`. Results can differ from core-computed values at the last ulp across contexts/hosts. `report.py` imports only `_div, _q` from `src.core._decimal` — `_add/_sub/_mul` are available and unused.
**Fix:** Route every op in `_decimal_mean/_decimal_median/_decimal_pstdev/_quantile/_max_drawdown` through the pinned helpers.

### WR-08: Fixture generator crashes on a fresh clone — per-case dirs never created

**File:** `scripts/gen_phase6_fixtures.py:361-536`
**Issue:** `main()` creates only `FIXTURE_ROOT`, but each writer does `(FIXTURE_ROOT / "<case>" / "input.json").write_text(...)` without creating `<case>/`. On a fresh checkout (no `tests/fixtures/phase6/*/`) every writer raises `FileNotFoundError`. The "re-running it regenerates byte-identical fixtures" claim fails on the first run.
**Fix:**
```python
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(...)
```

### WR-09: Registry resolution is CWD-dependent

**File:** `src/domain/registry.py:41`, `src/backtest/simulator.py:650`
**Issue:** `REGISTRY_ROOT = Path("params")` resolves against the process CWD. Running the simulator from any directory other than the repo root (tests run from root today) raises `UnregisteredParameterSet` for registered sets. Deterministic tooling should anchor to the repo root (e.g. resolve relative to the importing file) or accept an explicit root.
**Fix:** Resolve `REGISTRY_ROOT` from `Path(__file__).resolve().parents[2] / "params"` (or inject the root as a parameter).

### WR-10: Zero-risk trades vanish from the R distribution while counts keep them

**File:** `src/backtest/report.py:407-416`
**Issue:** `_r_multiple` returns `None` when `realized_risk == 0`, so those trades are excluded from `r_values`, `win/loss/zero` counts, stability, plateau, and bootstrap — yet `counts.trade_count` includes them. A run with many zero-risk fills reports `trade_count=N` with an R distribution over fewer observations and no note. At minimum the insufficient-data accounting should mention excluded zero-risk trades.
**Fix:** Count risk-zero exclusions explicitly and surface them in `insufficient_data_note` (or reject risk-zero fills upstream fail-closed).

## Info

### IN-01: Validation helpers defined but never called on the parse path

**File:** `src/backtest/simulator.py:42-57, 230-260`
**Issue:** `_require_decimal`, `_require_utc_aware`, `_require_non_empty` are defined ("local copies, D-12 fail-closed") but `_parse_candle`, `_parse_account_state`, `_parse_constraint_snapshot`, and the `run()` top-level (`now_utc`, `daily_loss_quote`, `ttl_seconds`) never call them. Naive datetimes (`datetime.fromisoformat` without TZ check), float-typed JSON numbers (`Decimal(0.5)` binary noise via `Decimal(row["open"])` on a float), and empty strings pass silently into the pure core.
**Fix:** Call the helpers at each parse boundary, or delete them if `src.core.types` validation is intended to own the boundary.

### IN-02: Tests mask the defects they should catch

**File:** `tests/test_backtest_simulator.py:326-400`, `tests/test_backtest_experiment.py:161-198, 337-371`, `tests/test_backtest_report.py:101-134`
**Issue:** (a) The cost-parity test (Beh. 11) re-derives `fee_entry + fee_exit + slippage` by hand instead of calling `costs.modeled_costs_per_unit`, so parity with `src/risk/sizing.py` is asserted against a copy, not the function. (b) The no-lookahead test appends a post-horizon candle AFTER the exit was already decided on the first 1m candle (SL on candle 0) — it cannot detect a leak that reads ahead within the deciding window. (c) Reproduce/verify tests use `simulator_inputs={}` (empty), which early-returns `[]` — they exercise the stub path, never a real replay. (d) The pinned-digest test depends on `expected.json` being filled at GREEN with no mechanism shown to prevent hand-fitting the digest to the implementation.
**Fix:** Call the real cost function in the parity test; craft a lookahead test where the appended candle is the ONLY touch; reproduce through a real fixture with digest comparison against a stored expectation; document digest-generation provenance.

### IN-03: Fixture 4H context is price-discontinuous with the 1H trigger

**File:** `scripts/gen_phase6_fixtures.py:121-208`
**Issue:** The LONG 4H context trends 100→199.60 while the 1H trigger bar sits at 121–125; the SHORT context ends at 150.50 while the 1H trigger sits at 125–128.50. The regime filter may still pass, but the fixtures are economically incoherent across timeframes, which weakens their power to catch regime-gate bugs (a wrong regime decision still yields "1 trade" and passes).
**Fix:** Anchor the 4H最后一个 bar's price window to the 1H trigger window (sameshock continuity) and assert the regime label in the test, not just the trade count.

### IN-04: modeled_costs_per_unit adds rates to price distances (parity preserved, semantics suspect)

**File:** `src/backtest/costs.py:142-162`, `src/risk/sizing.py:41`, `src/risk/gating.py:100`
**Issue:** `modeled_costs_per_unit = fee_rate_entry + fee_rate_exit + expected_slippage` (dimensionless rates, ~0.0008) is added to `sl_distance` (price units) in `risk_per_unit`. The simulator faithfully mirrors the sizing formula (parity holds — good), but dimensionally a rate is being added to a price. `_apply_costs` correctly computes fees as `price × qty × rate`. Flagged as Info (not Warning) because the backtest's contract is parity with sizing, and any fix belongs in `src/risk/` with a cross-phase migration, not in this phase alone.
**Fix:** No change in this phase; open a cross-phase item to reconcile `risk_per_unit` units (rate×reference-price vs raw rate) with identical logic in backtest/paper/live.

---

_Reviewed: 2026-09-26T00:00:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
