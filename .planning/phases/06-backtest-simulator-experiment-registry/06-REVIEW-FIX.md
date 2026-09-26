---
phase: 06-backtest-simulator-experiment-registry
fixed_at: 2026-09-26T12:00:00Z
review_path: .planning/phases/06-backtest-simulator-experiment-registry/06-REVIEW.md
iteration: 1
findings_in_scope: 26
fixed: 23
skipped: 3
status: partial
---

# Phase 06: Code Review Fix Report

**Fixed at:** 2026-09-26T12:00:00Z
**Source review:** .planning/phases/06-backtest-simulator-experiment-registry/06-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 26 (12 Critical + 14 Warning; 6 Info out of scope)
- Fixed: 23
- Skipped: 3 (CR-04, WR-03, WR-13 — each with a recorded reason below)

**Verification environment:** main checkout (`workflow.use_worktrees=false`, no
isolated worktree). Per-fix verification: source re-read (Tier 1, all) +
`ast.parse` syntax check (Tier 2, all Python files) + targeted runtime checks
for CR-01/02/03/05/07/09/10, WR-06/08/10/12/14 and the TOML loads. No
`node -c`/`tsc` applicability (Python repo). Full phase-6 subset
(`test_backtest_simulator`, `test_backtest_experiment`, `test_backtest_report`,
`test_domain_no_float`): **23 passed / 13 failed — byte-identical to the
pre-fix baseline**. All 13 failures are `ModuleNotFoundError: No module named
'structlog'` raised at `src/risk/quantization.py:207`, a file this fix run
never touched; the environment's system Python (3.14.3) lacks the project's
pinned dependencies. No previously-passing test regressed, including the
pinned `EXPECTED_REPORT_DIGEST` (`864aab05…f033ee91` still matches — the
WR-06 stream split leaves this fixture's p05/p50/p95 drawdown quantiles
unchanged, WR-07's prec-28 helpers equal the ambient default precision, WR-05
computes the same 90% on this fixture, and WR-10 finds no risk-zero trades in
it, so no `expected.json` churn was required).

## Fixed Issues

### CR-01: Empty intrabar list crashes with IndexError instead of failing closed

**Files modified:** `src/backtest/simulator.py`
**Commit:** 488bcd0
**Applied fix:** `resolve_intrabar` now treats `None` **and** `[]` as missing
coverage (`if intrabar is None or len(intrabar) == 0`), returning the SL-first
fallback with `fallback_applied=True` / `coverage_note="1m_intrabar_missing"`.
Runtime-checked for LONG/SHORT × None/[].

### CR-02: Trade-ID payload omits bar time, symbol, and quantity

**Files modified:** `src/backtest/simulator.py`
**Commit:** 73ede4d (shared with WR-11)
**Applied fix:** `_make_record` takes explicit `symbol: str` and
`bar_close_time_utc: datetime` (validated non-empty / UTC-aware) and the ID
payload now binds `symbol`, `bar_close_time_utc`, and `quantity` alongside the
plan/price/kind fields. All 6 `_resolve_entry` call sites pass
`bar.symbol` / `bar.close_time_utc`. Runtime-checked: fraction-only,
bar-only, and symbol-only variations all change the ID; identical inputs
re-hash identically.

### CR-03: reproduce/verify_experiment tripwire is tautological and corrupts types

**Files modified:** `src/backtest/experiment.py`
**Commit:** 9e582d7
**Applied fix:** (a) `_check_inputs_bind_record` fails closed with
`ExperimentReproducibilityBroken` unless `parameter_set_id`,
`strategy_version`, registry `parameter_set_hash`, and `cost_model_hash` all
match the record. (b) `verify_experiment` compares the reproduce digest
against the record's stored `trades_digest` (parsed from
`result_summary_json`) when present — detecting cross-version drift — and
keeps the double-run determinism check. (c) New `_trade_from_dict` parses
every money field back to `Decimal` and every timestamp to UTC-aware
`datetime` before constructing `TradeRecord`; `reproduce` and both baseline
runners use it instead of `TradeRecord(**t)`. The empty-`simulator_inputs`
stub path (`[]` / `None`) is preserved because three existing tests pin it.
Runtime-checked: typed rebuild, version-mismatch rejection, stored-digest
mismatch detection, stored-digest match acceptance.

### CR-05: build_cost_model destroys trailing precision for Decimal inputs

**Files modified:** `src/backtest/costs.py`
**Commit:** a7e7db4
**Applied fix:** New `_coerce_decimal` returns `Decimal` inputs as-is (never
`str()` round-trip), keeps string spellings exact, accepts exact ints, and
rejects bools/floats fail-closed. `build_cost_model` and `__post_init__`
validation use it. Runtime-checked: `"0.00020"` vs `"0.0002"` hashes still
differ (existing Beh.7 preserved) while `Decimal("0.00020")` and
`"0.00020"` now hash identically.

### CR-06: experiment_id omits run_type and strategy_id

**Files modified:** `src/backtest/experiment.py`
**Commit:** 64a8b12
**Applied fix:** `identity_payload` now includes `strategy_id` and `run_type`.
Existing tests assert stability/format only (no pinned IDs), so no test churn.

### CR-07: Baseline runners guarantee nothing

**Files modified:** `src/backtest/experiment.py`
**Commit:** c314667
**Applied fix:** New `_require_baseline_params` loads the case's registry set
and enforces `minimum_rr >= 100` for `baseline_no_trade` and
`minimum_rr < 2` for `baseline_simple_trend`, raising `ValueError`
fail-closed otherwise. Runtime-checked against both baseline fixtures
(pass) and against `baseline-v2` / cross-kind misuse (rejected).

### CR-08: Report digest defaults to wall-clock time

**Files modified:** `src/backtest/report.py`
**Commit:** c50b295 (shared with CR-12)
**Applied fix:** `built_at_utc: datetime` is now a required keyword (no `None`
default, no `datetime.now(UTC)`); UTC-awareness enforced at entry. The sole
in-repo caller (report tests) always passes an explicit timestamp; removed the
now-unused `UTC` import. Signature introspection + naive-datetime rejection
runtime-checked.

### CR-09: CostModel accepts a forged non-empty cost_model_hash (NEW, deep)

**Files modified:** `src/backtest/costs.py`
**Commit:** 903cd49
**Applied fix:** `__post_init__` always recomputes the expected hash: fills it
when empty, raises `ValueError` on mismatch when provided.
Runtime-checked: forged 64-hex rejected, matching hash accepted,
`build_cost_model` (empty-hash path) unaffected.

### CR-10: Fixture strategy_version never bound to the registry version (NEW, deep)

**Files modified:** `src/backtest/simulator.py`
**Commit:** fecc33f
**Applied fix:** `run()` raises `ValueError` fail-closed when the fixture's
`strategy_version` differs from the loaded registry set's version, so the
identity tuple can never attest to an unversioned hybrid. All shipped
fixtures declare `v2.0.0` matching the registry.

### CR-11: Baseline TOMLs miss required detector keys (NEW, deep)

**Files modified:** `params/trend-pullback/baseline-no-trade-v1.toml`, `params/trend-pullback/baseline-simple-trend-v1.toml`
**Commit:** 177fd57 (shared with WR-04)
**Applied fix:** Added `atr_period = 14` (matches sibling `breakout-retest` /
`range-mr` `baseline-v2` sets) plus the four cost keys (see WR-04). Scoping
note: the review's "every strategy path" over-claims — `strategy.evaluate`
dispatches by family and the trend-pullback path only ever indexes
`zone_tolerance_atr`/`swing_lookback`/`breakout_confirmation_bars`/
`entry_buffer_atr`/`sl_buffer_atr`/`minimum_rr`/`signal_expiry_hours`
(all present; planner reads verified by grep) plus `atr_period` via the
`features.py` fallback. Family B/C keys (`retest_*`, `zone_*`,
`range_break_buffer_atr`, `regime_filter_lookback`, `touch_tolerance_atr`)
are never indexed on this path, so adding them would pollute
`parameter_set_hash` with behavior-neutral keys — deliberately omitted. The
`features.py` `.get("atr_period", 14)` fallback itself is intentionally left
in place: converting it to direct indexing would `KeyError` the pinned,
already-referenced `trend-pullback/baseline-v2` set (D-04: never mutate a
referenced set), which requires a versioned registry migration, out of scope
here. Both files load and validate via `load_parameter_set`.

### CR-12: Unvalidated resamples/probable yield a bogus [0,0] interval (NEW, deep)

**Files modified:** `src/backtest/report.py`
**Commit:** c50b295 (shared with CR-08)
**Applied fix:** Upfront `ReportBuildError` unless `resamples` is `int`
(non-bool) `>= 100` and `probable` is `Decimal` in `(0, 1]`. Runtime-checked
for `0`, `50`, `True`, `0`, `1.5`.

### WR-01: Closed-snapshot prefix built from unsorted input order

**Files modified:** `src/backtest/simulator.py`
**Commit:** ff3dd56
**Applied fix:** `closed_setup` is now an index slice of the pre-sorted bar
list; context bars are sorted once up front (`sorted_context`) and filtered
by time. Out-of-order fixture input yields time-ordered, prefix-invariant
snapshots.

### WR-02: TP2 silently dropped

**Files modified:** `src/backtest/simulator.py`
**Commit:** 2e192cc
**Applied fix:** Took the review-sanctioned minimal option: narrowed the
documented `exit_kind` enums (`IntrabarOutcome` field comment +
`TradeRecord` docstring) to `"SL" | "TP1" | "EOD"` and recorded the
single-exit scope explicitly (planner's TP2 runner leg is not modeled; TP1
exit is conservative). Full ladder modeling (partial TP1 + runner) is a
design-level change with PnL/report consequences that cannot be validated
while simulator tests are structlog-blocked — left as a tracked limitation,
no longer a silent one.

### WR-04: Baseline TOMLs omit 4 of 7 cost keys

**Files modified:** `params/trend-pullback/baseline-no-trade-v1.toml`, `params/trend-pullback/baseline-simple-trend-v1.toml`
**Commit:** 177fd57 (shared with CR-11)
**Applied fix:** Added `funding_treatment = "ADDITIVE"`,
`slippage_model = "FIXED_BPS"`, `spread_fill_assumptions = "FULL_FILL"`,
`partial_fill_fraction = 1.0` to both files, with in-file provenance
comments. Canonical source: `COST_MODEL` in
`scripts/gen_phase6_fixtures.py`, which is the runtime dict the simulator
hashes into `cost_model_hash` (fixture inputs already carry all seven keys,
verified by inspection of `baselines/*/input.json`).

### WR-05: Intrabar coverage percent truncated to integer

**Files modified:** `src/backtest/report.py`
**Commit:** 1a70e23
**Applied fix:** Exact `_div(_q((n_trades - fallback_count) * 100),
_q(n_trades))` under the pinned context instead of integer `//`.

### WR-06: Bootstrap means and drawdown resamples share the identical RNG stream

**Files modified:** `src/backtest/report.py`
**Commit:** 173f55e
**Applied fix:** Drawdown stage runs on `bootstrap_seed + 1` with an
explanatory comment. Runtime-checked: raw streams differ across seeds while
this fixture's p05/p50/p95 quantiles (and hence the pinned digest) are
unaffected.

### WR-07: Report statistics bypass the pinned-precision helpers

**Files modified:** `src/backtest/report.py`
**Commit:** 3803cd7
**Applied fix:** `_decimal_mean` / `_decimal_median` / `_decimal_pstdev` /
`_max_drawdown` / `_quantile` / `_sample_block_length` arithmetic and the two
baseline-delta subtractions route through `_add` / `_sub` / `_mul` / `_div`.
One deliberate exception, commented at the site: `q**length` (no pinned
power helper exists; base and subtrahend still route through `_sub`).

### WR-08: Fixture generator crashes on a fresh clone

**Files modified:** `scripts/gen_phase6_fixtures.py`
**Commit:** 2aa9d69
**Applied fix:** `path.parent.mkdir(parents=True, exist_ok=True)` before all
7 writers. Runtime-checked by regenerating into an empty temp root (7/7 case
dirs with `input.json`).

### WR-09: Registry resolution is CWD-dependent

**Files modified:** `src/domain/registry.py`
**Commit:** 0cbacc3
**Applied fix:** `REGISTRY_ROOT = Path(__file__).resolve().parents[2] /
"params"`. Runtime-checked from the repo root and from `C:\` (loads
`trend-pullback/baseline-v2` in both).

### WR-10: Zero-risk trades vanish from the R distribution while counts keep them

**Files modified:** `src/backtest/report.py`
**Commit:** 98c464d
**Applied fix:** New `_has_zero_risk` counter tracks explicit
`realized_risk == 0` exclusions; any count is appended to
`insufficient_data_note` (standalone or joined to the existing note).
Runtime-checked: note appears with one zero-risk trade, absent without.

### WR-11: _make_record symbol placeholder leaks the string "Decimal" (NEW, deep)

**Files modified:** `src/backtest/simulator.py`
**Commit:** 73ede4d (shared with CR-02)
**Applied fix:** `symbol` is now a required explicit `_make_record`
parameter (validates non-empty); the `__class__.__name__` expression is
deleted. `_patch_record_metadata` still overwrites with `bar.symbol`, so
runtime records are unchanged in value but no caller can ever emit
`symbol="Decimal"` again. Covered by the CR-02 runtime check.

### WR-12: Exit timestamp is the trigger-bar close, not the intrabar exit minute (NEW, deep)

**Files modified:** `src/backtest/simulator.py`
**Commit:** 9f5a87d
**Applied fix:** `IntrabarOutcome` carries `exit_time_utc` (deciding 1m
candle's close; `None` on the missing-data fallback); `run()` stamps fills
with it, keeping `bar.close_time_utc` only for the fallback anchor.
Runtime-checked: SL touch on candle 2 stamps candle 2's close, EOD stamps
the last close, fallback yields `None`.

### WR-14: Parse boundary accepts float-typed JSON numbers and naive datetimes (NEW, deep)

**Files modified:** `src/backtest/simulator.py`
**Commit:** 1e510d3
**Applied fix:** New `_coerce_money` (Decimal passthrough, exact int/str,
fail-closed on bool/float/other) used by all four parse functions plus
`run()`'s `daily_loss_quote`; new `_parse_utc_aware` (ISO parse +
`_require_utc_aware`) used for every parsed timestamp including
`run()`'s `now_utc`. The no-float AST guard (`test_domain_no_float`) still
passes. Runtime-checked: float money, naive datetimes, and float account
fields rejected; string fixtures parse.

## Skipped Issues

### CR-04: Expiry gate uses one global fixture clock for every bar

**File:** `src/backtest/simulator.py:647, 312, 747-753`
**Reason:** Applying the suggested one-liner (`now_utc=bar.close_time_utc`)
makes `EXPIRED` unreachable and breaks the pinned `limit_expiry` test with no
possible fixture repair: a plan's `expiry_utc` is `source_close +
signal_expiry_hours` where `source_close` is the trigger bar's own close, so
`bar.close >= expiry` is never true for same-bar plans, and plans are never
carried across bars. Both clocks are defensible-but-wrong; the real fix is a
cross-bar plan lifecycle (carry-forward + per-bar expiry evaluation), which is
a design decision beyond review-fix scope. Needs a planner/simulator design
call before any code change.
**Original issue:** fixture `now_utc` (dataset end) reused for every bar's
expiry check while `evaluate_risk` receives `bar.close_time_utc`.

### WR-03: Funding/slippage-model/spread assumptions hardcoded away

**File:** `src/backtest/simulator.py:576-577`, `src/backtest/costs.py:142-162`
**Reason:** The review itself prescribes no phase-local change (narrow
`COST_KEYS` vs. wire assumptions into math is a semantics decision shared
with `src/risk/`, per IN-04/WR-13). Wiring `funding_treatment` into realized
PnL unilaterally would fork backtest semantics from paper/live. Opened as a
cross-phase item; no code touched.
**Original issue:** `funding = 0` unconditional; `slippage_model` /
`spread_fill_assumptions` validated but never read; per-unit costs
side-independent.

### WR-13: Slippage units diverge between the sized gate and the realized PnL (NEW, deep)

**File:** `src/backtest/simulator.py:571-577`, `src/backtest/costs.py:142-162`, `src/risk/sizing.py:41`
**Reason:** The review explicitly prescribes "No phase-local change" —
reconciling `risk_per_unit` units (rate × reference-price vs raw rate) with
identical logic in backtest/paper/live belongs to `src/risk/` jointly with
IN-04. Changing `_apply_costs` slippage to `price * quantity * rate` here
alone would break sizing parity the suite pins. Opened as a cross-phase
item; no code touched.
**Original issue:** sized slippage treated as a rate added to a price
distance while realized slippage deducts as per-unit quote amount
(price-scale factor divergence).

---

_Fixed: 2026-09-26T12:00:00Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_
