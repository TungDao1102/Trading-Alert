---
phase: 06-backtest-simulator-experiment-registry
reviewed: 2026-09-26T12:00:00Z
depth: deep
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
  critical: 12
  warning: 14
  info: 6
  total: 32
status: issues_found
---

# Phase 06: Code Review Report

**Reviewed:** 2026-09-26T12:00:00Z
**Depth:** deep
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Deep re-review of the Phase 6 backtest package (simulator ↔ costs ↔ risk/sizing
parity, experiment ↔ registry identity, report ↔ core `_decimal` helpers,
fixture generator ↔ fixtures ↔ tests), upgrading the prior standard-depth
06-REVIEW.md (8 critical / 10 warning / 4 info). **All 22 prior findings
re-verified against current source and confirmed still open** — every cited
line still matches; no fix landed between reviews. The deep pass adds 4 new
Critical (CR-09–CR-12), 4 new Warnings (WR-11–WR-14), and 2 new Info (IN-05,
IN-06) covering cross-file defects the standard pass missed: forged
`cost_model_hash` acceptance, fixture-vs-registry `strategy_version`
divergence, baseline TOMLs missing required detector keys on the
identical-simulator path, and unvalidated `resamples`/`probable` producing
bogus intervals. The architecture (pure modules, frozen dataclasses,
canonical hashing) remains sound, but the 12 Critical defects break
correctness, identity, or reproducibility claims and must be fixed before
this code gates any selection decision.

## Critical Issues

### CR-01: Empty intrabar list crashes with IndexError instead of failing closed

**File:** `src/backtest/simulator.py:156-222`
**Issue:** `resolve_intrabar` treats `None` as missing (fallback) but an empty
list `[]` falls through the `for` loop and hits `intrabar[-1].close` (line
219), raising `IndexError`. An empty 1m payload (valid JSON, zero candles) is
the most likely real-world shape of "no coverage" and must resolve to the
SL-first fallback with `fallback_applied=True`, never crash the whole run.
Still open — lines 176-222 unchanged.
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
**Issue:** `_make_record` hashes only `{trade_plan_id, entry_kind,
entry_price, exit_kind, exit_price, outcome_kind, reason_code}`. It does not
bind `symbol`, `bar.close_time_utc`, `quantity`, or `partial_fill_fraction`.
Two fills of the same plan at different fractions (0.5 vs 0.9) share
`entry_kind="PARTIAL_FILL"` and the same price, hence the same `trade_id`;
patched fields (`symbol`, `parameter_set_hash`, `realized_risk`) are applied
AFTER the ID is computed, so the ID does not cover the record's own content.
Still open — payload dict unchanged.
**Fix:**
```python
payload = {
    "trade_plan_id": trade_plan.trade_plan_id,
    "symbol": bar_symbol,
    "bar_close_time_utc": bar_close_iso,
    "entry_kind": entry_kind,
    "entry_price": entry_price,
    "quantity": quantity,
    "exit_kind": exit_kind,
    "exit_price": exit_price,
    "outcome_kind": outcome_kind,
    "reason_code": reason_code,
}
```

### CR-03: reproduce/verify_experiment tripwire is tautological and corrupts types

**File:** `src/backtest/experiment.py:236-275`
**Issue:** (a) `reproduce()` never reads `record` — it runs whatever
`simulator_inputs` it is handed. (b) `verify_experiment()` calls
`reproduce()` twice with the SAME dict, so cross-version engine drift is
undetectable — the check always passes. (c) `TradeRecord(**t)` rebuilds from
`to_dict()` output (Decimals stringified, datetimes ISO strings), so the
reconstructed record holds `str` where the type says `Decimal | None` /
`datetime | None`. Still open — lines 236-275 unchanged.
**Fix:**
```python
def reproduce(record, *, simulator_inputs):
    # 1. Assert inputs bind to the record (parameter_set_id/hash,
    #    strategy_version, cost_model_hash must match); else raise
    #    ExperimentReproducibilityBroken.
    # 2. Parse each trade dict back to typed fields (Decimal(...),
    #    datetime.fromisoformat(...)) before constructing TradeRecord.
def verify_experiment(record, *, simulator_inputs):
    # Compare reproduce digest against the record's stored result
    # digest (persisted at assemble time), not a second identical run.
```

### CR-04: Expiry gate uses one global fixture clock for every bar

**File:** `src/backtest/simulator.py:647, 312, 747-753`
**Issue:** `_entry_now_utc = now_utc` is captured once from the fixture and
reused for every bar's `_resolve_entry` expiry check, while `evaluate_risk`
correctly receives `now_utc=bar.close_time_utc` (line 722). In any multi-bar
backtest the fixture `now_utc` is the END of the dataset, so every early-bar
signal whose `expiry_utc` predates the dataset end resolves `EXPIRED` even
though its limit window was open at its own bar time. Still open — the
rationalizing comment on lines 642-646 and the global clock are unchanged.
**Fix:**
```python
entry_record = _resolve_entry(
    ...,
    now_utc=bar.close_time_utc,  # same clock passed to evaluate_risk
    ...,
)
```

### CR-05: build_cost_model destroys trailing precision for Decimal inputs

**File:** `src/backtest/costs.py:118-134`
**Issue:** `Decimal(str(cost_dict[k]))` round-trips through `str()`. For
string inputs (`"0.00020"`) precision survives, but for `Decimal` inputs —
exactly what `ParameterSet.params` holds after registry normalization —
`str(Decimal("0.00020"))` is `"0.0002"`, silently dropping the trailing zero
before hashing. Two construction paths, two hashes, one "canonical"
`cost_model_hash`. Still open — lines 126-133 unchanged.
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
**Issue:** The `identity_payload` contains `strategy_version`,
`parameter_set_hash`, `data_snapshot_id`, `code_version`,
`cost_model_hash`, time range, and universe hash — but NOT `run_type` or
`strategy_id`. A `CANDIDATE` and a `BASELINE_NO_TRADE` run over otherwise
identical inputs, or two strategies sharing `strategy_version="v2.0.0"`,
produce the SAME `experiment_id`. Still open — payload keys unchanged.
**Fix:**
```python
identity_payload = {
    "strategy_id": strategy_id,
    "strategy_version": strategy_version,
    "parameter_set_hash": ...,
    "data_snapshot_id": ...,
    "code_version": ...,
    "cost_model_hash": ...,
    "run_type": run_type,
    ...
}
```

### CR-07: Baseline runners guarantee nothing — degenerated-params claim is unenforced

**File:** `src/backtest/experiment.py:293-320`
**Issue:** `baseline_no_trade` / `baseline_simple_trend` docstrings promise
"minimum_rr=100 forces every plan to fail" / "looser config emits
single-direction trades", but the bodies just call `simulator_run` and
filter. No check on `parameter_set_id`, no assertion on `minimum_rr`, no
registry cross-check. Passing candidate params to `baseline_no_trade`
returns filled trades mislabeled as a baseline. Still open — bodies
unchanged.
**Fix:**
```python
def baseline_no_trade(case_input):
    ps = load_parameter_set(case_input["strategy_id"], case_input["parameter_set_id"])
    assert Decimal(str(ps.params["minimum_rr"])) >= Decimal("100"), "not a no-trade baseline"
    ...
```

### CR-08: Report digest defaults to wall-clock time — rebuilds are non-reproducible

**File:** `src/backtest/report.py:552-553`
**Issue:** `build()` defaults `built_at_utc=None` to `datetime.now(UTC)`,
and `UncertaintyReport.digest()` includes `built_at_utc` (line 363). Two
builds of the same trades/seeds at different times hash differently.
Tests mask this by always passing `_FIXED_BUILT_AT_UTC`. Still open — the
`None` default and digest inclusion are unchanged.
**Fix:**
```python
def build(*, ..., built_at_utc: datetime) -> UncertaintyReport:
    _require_utc_aware(built_at_utc, "built_at_utc")  # no None default
```

### CR-09: CostModel accepts a forged non-empty cost_model_hash without verification (NEW, deep)

**File:** `src/backtest/costs.py:104-110`, `src/backtest/experiment.py:168-228`
**Issue:** `__post_init__` recomputes the hash ONLY when
`cost_model_hash == ""`. Any caller passing a non-empty string — including
a hash copied from a different cost assumption — is accepted blindly, and
`assemble()` hashes that untrusted value straight into `experiment_id`.
Cross-file effect: the registry→cost identity chain (D-02 + Pitfall 7) rests
on caller honesty. A fixture whose `cost_model` values disagree with its
pinned hash silently poisons experiment identity with zero fail-closed
signal.
**Fix:**
```python
# In __post_init__, always recompute and compare:
expected = sha256_hex({k: getattr(self, k) for k in COST_KEYS})
if self.cost_model_hash == "":
    object.__setattr__(self, "cost_model_hash", expected)
elif self.cost_model_hash != expected:
    raise ValueError(f"cost_model_hash mismatch: {self.cost_model_hash!r} != {expected!r}")
```

### CR-10: Fixture strategy_version never bound to the registry version (NEW, deep)

**File:** `src/backtest/simulator.py:628-650, 675-680`
**Issue:** `run()` reads `strategy_version` from the fixture dict and passes
it to `strategy.evaluate`, while `load_parameter_set()` returns a
`ParameterSet` carrying the registry's own `strategy_version` — which is
used only for reject-record bookkeeping, never compared. A fixture claiming
`strategy_version="v2.0.0"` replayed against a registry file bumped to
`"v3.0.0"` (or vice versa) replays silently under a hybrid identity:
`parameter_set_hash` from the registry, `strategy_version` from the caller.
The six-field identity then attests to a combination that was never
versioned together.
**Fix:**
```python
parameter_set = load_parameter_set(strategy_id, parameter_set_id)
if parameter_set.strategy_version != strategy_version:
    raise ValueError(
        f"fixture strategy_version={strategy_version!r} != "
        f"registry strategy_version={parameter_set.strategy_version!r}"
    )
```

### CR-11: Baseline TOMLs miss required detector keys — identical-simulator replay raises KeyError (NEW, deep)

**File:** `params/trend-pullback/baseline-no-trade-v1.toml`, `params/trend-pullback/baseline-simple-trend-v1.toml`, `src/core/strategy.py:237-245, 395-403`, `src/core/features.py:269`
**Issue:** Cross-file trace: `strategy.py` reads `params["retest_window_bars"]`,
`params["atr_period"]`, `params["touch_tolerance_atr"]`,
`params["zone_min_touches"]` via direct indexing (KeyError when absent), but
neither baseline TOML defines ANY of `atr_period`, `touch_tolerance_atr`,
`retest_window_bars`, `retest_depth_atr`, `zone_min_touches`,
`zone_aging_bars`, `range_break_buffer_atr`, `regime_filter_lookback`, or the
four Phase-6 string cost keys. Whitelist membership (`STRATEGY_KEYS`) is not
presence: both files load cleanly yet crash (or silently degrade, via the
`.get("atr_period", _ATR_PERIOD_FALLBACK)` silent default in
`features.py:269` — itself a D-06 violation) the moment the
"identical simulator" touches a code path needing those keys. The BACKTEST_SPEC
§9 baseline gate cannot execute end-to-end on the shipped files for every
strategy path.
**Fix:**
```python
# Add every key the simulator's transitive closure indexes directly:
# atr_period, touch_tolerance_atr, retest_window_bars, retest_depth_atr,
# breakout_volume_threshold, zone_min_touches, zone_aging_bars,
# range_break_buffer_atr, regime_filter_lookback, funding_treatment,
# slippage_model, spread_fill_assumptions, partial_fill_fraction
# — and replace the features.py .get() fallback with direct indexing.
```

### CR-12: Unvalidated resamples/probable yield a bogus [0,0] interval instead of failing closed (NEW, deep)

**File:** `src/backtest/report.py:541-640`
**Issue:** `build()` never validates `resamples` or `probable` upfront;
`probable` range is checked only inside `_sample_block_length` per draw
(fail-late after partial work). Worse, `resamples=0` with `n_r >= 2` takes
the bootstrap branch, computes `resampled_means=[]`, then
`_quantile([], ...)` returns `Decimal("0")` for both bounds — producing a
confident-looking `BootstrapInterval(lower=0, upper=0)` over real data. A
zero-resample "uncertainty" section is a silent correctness lie, not an
absent section.
**Fix:**
```python
if not isinstance(resamples, int) or isinstance(resamples, bool) or resamples < 100:
    raise ReportBuildError(f"resamples must be int >= 100, got {resamples!r}")
if not (Decimal("0") < probable <= Decimal("1")):
    raise ReportBuildError(f"probable must be in (0, 1], got {probable!r}")
```

## Warnings

### WR-01: Closed-snapshot prefix built from unsorted input order

**File:** `src/backtest/simulator.py:659, 665-666`
**Issue:** Iteration is over `sorted_bars` but each bar's `closed_setup` /
`closed_context` is filtered from the ORIGINAL unsorted lists, preserving
input file order rather than time order. Out-of-order fixtures break
prefix-invariance. Still open.
**Fix:** Sort once up front and slice by index instead of re-filtering the
unsorted lists.

### WR-02: TP2 silently dropped — intrabar only resolves SL/TP1/EOD

**File:** `src/backtest/simulator.py:156-222, 286-289`
**Issue:** `IntrabarOutcome.exit_kind` documents `"SL" | "TP1" | "TP2" |
"EOD"` but `resolve_intrabar` only returns SL/TP1/EOD and `_parse_tp1` only
reads `tp1` — while `planner.py:398-417` provably emits a `tp2` leg per
plan. The TP2 leg never realizes; no error, no note. Still open.
**Fix:** Implement TP2 resolution (parse full TP ladder, walk intrabar
against SL/TP1/TP2) or remove TP2 from the documented enums.

### WR-03: Funding/slippage-model/spread assumptions hardcoded away

**File:** `src/backtest/simulator.py:576-577`, `src/backtest/costs.py:142-162`
**Issue:** `_apply_costs` sets `funding = Decimal("0")` unconditionally;
`slippage_model` and `spread_fill_assumptions` are validated but never read;
`modeled_costs_per_unit` is side-independent despite taking `side`. Hashed
cost assumptions do not affect realized PnL. Still open.
**Fix:** Wire each hashed assumption into the math or narrow `COST_KEYS` to
what the simulator consumes; at minimum branch funding on
`funding_treatment`.

### WR-04: Baseline TOMLs omit 4 of 7 cost keys — cost truth lives in two places

**File:** `params/trend-pullback/baseline-no-trade-v1.toml`, `params/trend-pullback/baseline-simple-trend-v1.toml`
**Issue:** Both files carry only `fee_rate_entry/fee_rate_exit/
expected_slippage` and omit `funding_treatment`, `slippage_model`,
`spread_fill_assumptions`, `partial_fill_fraction`. The simulator's
`CostModel` comes from the fixture dict, not the registry, so
`parameter_set_hash` and `cost_model_hash` are computed from disjoint
sources. Still open — both files unchanged. (Now compounded by CR-11,
which shows the omission extends to detector keys.)
**Fix:** Add the four missing keys to both baseline TOMLs and document
which source is canonical when they disagree.

### WR-05: Intrabar coverage percent truncated to integer

**File:** `src/backtest/report.py:783`
**Issue:** `coverage_pct = _q((n_trades - fallback_count) * 100 // n_trades)`
uses integer `//` before quantizing, flooring e.g. 2/3 coverage to `66`.
Tests cover only 100%/0% extremes. Still open.
**Fix:**
```python
coverage_pct = _div(_q((n_trades - fallback_count) * 100), _q(n_trades))
```

### WR-06: Bootstrap means and drawdown resamples share the identical RNG stream

**File:** `src/backtest/report.py:625-646`
**Issue:** `_stationary_block_bootstrap_means(..., seed)` and
`_resample_drawdowns(..., seed)` each construct `random.Random(seed)` from
the SAME seed, so both stages consume the identical pseudo-random sequence.
The drawdown distribution is deterministically coupled to the expectancy
resample. Still open.
**Fix:** Thread a single `random.Random(seed)` through both stages, or
derive `drawdown_seed = seed + 1` with a comment.

### WR-07: Report statistics bypass the pinned-precision helpers

**File:** `src/backtest/report.py:379-538`
**Issue:** `_decimal_mean` (`total / _q(n)`), `_decimal_median`
(`(a+b) / Decimal("2")`), `_quantile`, and `_max_drawdown` use raw Decimal
operators under the ambient context instead of `_div/_add/_sub/_mul` with
`prec=28`. Results can differ at the last ulp across contexts/hosts.
Still open — `report.py` still imports only `_div, _q`.
**Fix:** Route every op through the pinned helpers.

### WR-08: Fixture generator crashes on a fresh clone — per-case dirs never created

**File:** `scripts/gen_phase6_fixtures.py:361-536`
**Issue:** `main()` creates only `FIXTURE_ROOT`, but each writer does
`(FIXTURE_ROOT / "<case>" / "input.json").write_text(...)` without creating
`<case>/`. Every writer raises `FileNotFoundError` on a fresh checkout.
Still open — no `mkdir` added to any writer.
**Fix:**
```python
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(...)
```

### WR-09: Registry resolution is CWD-dependent

**File:** `src/domain/registry.py:41`, `src/backtest/simulator.py:650`
**Issue:** `REGISTRY_ROOT = Path("params")` resolves against the process CWD.
Running the simulator from any directory other than the repo root raises
`UnregisteredParameterSet` for registered sets. Still open.
**Fix:** Resolve `REGISTRY_ROOT` from `Path(__file__).resolve().parents[2] /
"params"` (or inject the root as a parameter).

### WR-10: Zero-risk trades vanish from the R distribution while counts keep them

**File:** `src/backtest/report.py:407-416`
**Issue:** `_r_multiple` returns `None` when `realized_risk == 0`, so those
trades are excluded from `r_values`, win/loss/zero counts, stability,
plateau, and bootstrap — yet `counts.trade_count` includes them. No note.
Still open.
**Fix:** Count risk-zero exclusions explicitly and surface them in
`insufficient_data_note` (or reject risk-zero fills upstream fail-closed).

### WR-11: _make_record symbol placeholder leaks the string "Decimal" (NEW, deep)

**File:** `src/backtest/simulator.py:515-516`
**Issue:** `symbol=trade_plan.entry_min_price.__class__.__name__` evaluates
to the literal string `"Decimal"` on every `_resolve_entry` record. Today it
is masked because `run()` overwrites it via `_patch_record_metadata` — but
the ID is computed BEFORE the patch, and any future caller using
`_make_record` directly (tests, replay tooling) gets `symbol="Decimal"` in
typed output with no error. A placeholder that type-checks as `str` while
being semantically always-wrong is worse than a required parameter.
**Fix:** Pass `symbol: str` explicitly into `_make_record` (from
`bar.symbol`) and delete the `__class__.__name__` expression.

### WR-12: Exit timestamp is the trigger-bar close, not the intrabar exit minute (NEW, deep)

**File:** `src/backtest/simulator.py:776-783`
**Issue:** `_make_filled_record(..., exit_time_utc=bar.close_time_utc)` stamps
every fill with the strategy-bar close even though `resolve_intrabar` walked
specific 1m candles to decide the exit. Cross-file effect: `report._quarter`
buckets all exits to the trigger quarter, stability slices inherit the
coarseness, and any future holding-time or funding-accrual math starts from
a wrong anchor. The 1m resolution precision is computed then discarded.
**Fix:** Return the deciding 1m candle's `close_time_utc` from
`resolve_intrabar` (extend `IntrabarOutcome`) and use it as `exit_time_utc`.

### WR-13: Slippage units diverge between the sized gate and the realized PnL (NEW, deep)

**File:** `src/backtest/simulator.py:571-577`, `src/backtest/costs.py:142-162`, `src/risk/sizing.py:41`
**Issue:** `modeled_costs_per_unit = fee_entry + fee_exit + slippage`
(dimensionless rates) feeds `risk_per_unit = sl_distance + costs` in both
sizing and the simulator (parity holds), but `_apply_costs` then computes
`slippage = quantity * expected_slippage` (quote-per-unit, no price factor)
while fees are `price * quantity * rate`. The realized slippage is off from
the sized assumption by a price-scale factor (~1e2 for BTC fixtures): the
gate sizes as if slippage were a rate added to a price distance, then the
fill deducts it as a per-unit quote amount. Parity is preserved (both sides
share the formula) but both sides disagree with the realized deduction.
Flagged Warning (not Critical) because the fix belongs in `src/risk/`
jointly per prior IN-04, not in this phase alone.
**Fix:** No phase-local change; open a cross-phase item reconciling
`risk_per_unit` units (rate × reference-price vs raw rate) with identical
logic in backtest/paper/live, and make `_apply_costs` slippage
`price * quantity * rate` to match the fee legs.

### WR-14: Parse boundary accepts float-typed JSON numbers and naive datetimes (NEW, deep)

**File:** `src/backtest/simulator.py:230-260, 628-640`
**Issue:** `_parse_candle` / `_parse_account_state` /
`_parse_constraint_snapshot` build `Decimal(row["open"])`-style values
directly: a JSON number decoded as Python `float` (e.g. `1.1`) becomes
`Decimal(1.1000000000000000888…)` binary noise instead of failing closed,
and `datetime.fromisoformat` accepts naive strings while the module's own
`_require_utc_aware` (lines 48-52) is never called on the parse path. The
D-12 helpers exist but no parse function invokes them (prior IN-01); the
deep impact is concrete — float noise in `open/high/low/close` propagates
through strategy → planner → sizing identically in backtest AND live replay,
so the contamination is deterministic but wrong.
**Fix:** Call `_require_utc_aware` on every parsed datetime and route every
money/rate field through a `Decimal(str(v))`-with-`float`-rejection coercion
(or `_require_decimal` after explicit string conversion).

## Info

### IN-01: Validation helpers defined but never called on the parse path

**File:** `src/backtest/simulator.py:42-57, 230-260`
**Issue:** `_require_decimal`, `_require_utc_aware`, `_require_non_empty`
are defined but no parse function calls them. Still open. (Now elevated in
concrete impact by WR-14.)
**Fix:** Call the helpers at each parse boundary, or delete them if
`src.core.types` validation owns the boundary.

### IN-02: Tests mask the defects they should catch

**File:** `tests/test_backtest_simulator.py:326-400`, `tests/test_backtest_experiment.py:161-198, 337-371`, `tests/test_backtest_report.py:101-134`
**Issue:** (a) Cost-parity test re-derives the formula by hand instead of
calling `costs.modeled_costs_per_unit`. (b) No-lookahead test appends a
post-horizon candle AFTER the exit was decided on 1m candle 0. (c)
Reproduce/verify tests use `simulator_inputs={}` (stub path only). (d)
Pinned-digest test can be hand-fitted with no provenance mechanism. Still
open — all four patterns unchanged.
**Fix:** Call the real cost function; craft a lookahead test where the
appended candle is the ONLY touch; reproduce through a real fixture with a
stored digest; document digest-generation provenance.

### IN-03: Fixture 4H context is price-discontinuous with the 1H trigger

**File:** `scripts/gen_phase6_fixtures.py:121-208`
**Issue:** LONG 4H context trends 100→199.60 while the 1H trigger sits at
121–125; SHORT context ends at 150.50 while the 1H trigger sits at
125–128.50. Economically incoherent across timeframes; weakens regime-gate
coverage. Still open.
**Fix:** Anchor the 4H last bar's price window to the 1H trigger window and
assert the regime label in the test, not just the trade count.

### IN-04: modeled_costs_per_unit adds rates to price distances (parity preserved, semantics suspect)

**File:** `src/backtest/costs.py:142-162`, `src/risk/sizing.py:41`, `src/risk/gating.py:100`
**Issue:** Dimensionless rates added to `sl_distance` (price units). Parity
holds; any fix belongs in `src/risk/` cross-phase. Still open. (Now
compounded by WR-13 on the realized-deduction side.)
**Fix:** No change in this phase; open a cross-phase item.

### IN-05: ttl_seconds truncated through int() (NEW, deep)

**File:** `src/backtest/simulator.py:640`
**Issue:** `ttl = timedelta(seconds=int(case_input["ttl_seconds"]))` silently
truncates fractional TTLs (`"3600.9"` → 3600s) and raises a bare `ValueError`
on non-numeric strings instead of the project's fail-closed vocabulary.
The risk gate then enforces a different TTL than the registry's
`constraint_snapshot_ttl_seconds` implies, with no diagnostic.
**Fix:**
```python
ttl = timedelta(seconds=int(Decimal(str(case_input["ttl_seconds"]))))
# or reject non-integral TTLs fail-closed with a named error.
```

### IN-06: verify_parameter_set binds identity to any absolute path outside params/ (NEW, deep)

**File:** `src/domain/registry.py:412-432`
**Issue:** `verify_parameter_set` derives `strategy_id`/`parameter_set_id`
from `path.parent.name`/`path.stem` and validates only the segment charset —
never that the path lives under `REGISTRY_ROOT`. Verifying
`/tmp/attacker/trend-pullback/baseline-v2.toml` "passes" under the attacker's
directory identity, so a copied/renamed file verifies under path identity
without any anchor to the registry root. Read-only impact (no write), hence
Info, but the path-identity guarantee in the docstring over-claims.
**Fix:** Resolve the path and require it to be relative to `REGISTRY_ROOT`
before deriving identity segments.

---

_Reviewed: 2026-09-26T12:00:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
