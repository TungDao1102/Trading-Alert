---
phase: 15-strategy-geometry-correction
reviewed: 2026-10-06T00:00:00Z
depth: deep
files_reviewed: 11
files_reviewed_list:
  - src/core/pivots.py
  - src/core/planner.py
  - src/core/strategy.py
  - src/domain/rationale.py
  - src/domain/registry.py
  - src/paper/freeze.py
  - scripts/geometry_census.py
  - scripts/gen_phase6_fixtures.py
  - scripts/_regen_phase4_expectations.py
  - scripts/decision_alignment/params.py
  - scripts/smoke_backtest_realdata.py
findings:
  critical: 0
  warning: 1
  info: 6
  total: 7
status: issues_found
---

# Phase 15: Code Review Report

**Reviewed:** 2026-10-06
**Depth:** deep (cross-file: strategy detectors, planner, registry, freeze path, scripts, and the callers in `src/backtest/engine.py`, `src/paper/loop.py`, `src/risk/gating.py`, `src/execution/*`)
**Files Reviewed:** 11
**Status:** issues_found

## Summary

The phase 15 code is largely sound. Ruff and mypy are clean on every changed `src/` file, and `scripts.decision_alignment.params.run()` reports PA-01..PA-08 all ok. That means the pinned parameter hashes of the older sets did not move, so registry hash neutrality holds.

Questions in the brief, answered against the source:

1. **Pivots (`src/core/pivots.py`).** The tie rule is correct: non-strict on the left, strict on the right. Two equal extremes yield one pivot, the right one. A pivot at `t` and one at `t-1` cannot both exist, because the left side is non-strict and the right side is strict. The candidate range `[max(left, i-lookback+1), i-right]` guarantees `t+right <= i` and `t-left >= 0`. Fewer than `left+right+1` bars gives an empty range and `None`. Prefix-invariance holds.
2. **Strategy (`src/core/strategy.py`).**
   - The Family B lower bound `max(bcb+1, n-1-rw)` is exact. The retest scan covers `[i+1, i+rw]`, so bar `n-1` is reachable only when `i >= n-1-rw`. The `bcb+1` term keeps `ref_prev` non-negative.
   - No reference level or ATR comes from bar `n-1` in Family B or C.
   - The direction gate is consistent between `evaluate` (derived from the regime) and `plan` (derived from `signal.direction`).
   - The legacy path is byte-identical to `bbb4bca`. I diffed the old scan and the old range-mr detector.
   - The Family C pivot regime treats ties as NEUTRAL and returns NO_TRADE when fewer than two pivots of either kind exist.
   - One real hole exists: WR-01 below.
3. **Planner (`src/core/planner.py`).**
   - `_geometry_rejection` boundaries are as specified: strict `stop < entry_min` (D-06), touching the stop counts as INVALIDATED (D-07), and equality passes `min_stop_atr` (D-08).
   - The validator runs exactly once, after `quantize_for_storage` and before the RR gate.
   - With ATR equal to 0, the stop equals `entry_min` in all three families, so the plan is rejected with STOP_TOO_TIGHT.
   - `risk > 0` is guaranteed once D-06 passes, so there is no division by zero.
   - Switching RR from `abs()` to the signed leg changes legacy outputs only where TP1 was on the loss side. For positive legs the values are identical.
   - The entry limit is placed at the zone mid and the SL trigger is tick-snapped toward the entry. Risk sizing uses the adverse edge, which is conservative. I found no path where tick snapping puts the stop inside the zone under the Phase 12 `min_stop_distance_rate` guard.
4. **Rationale and freeze.** `pin_stream_epoch` refuses any set with a missing or incomplete rationale or a PLACEHOLDER key, unless `allow_unrationalized=True`. No module under `src/` passes `True`. Decimal-vs-string comparison is sound (see IN-05 for cosmetic gaps). See IN-01 for the enforcement-point caveat.
5. **Registry (`src/domain/registry.py`).**
   - Ranges are enforced for `pivot_left_bars` and `pivot_right_bars` (1..50), `geometry_version` (`{1}`), and `min_stop_atr` (0, 10]. They are enforced through `_check_value_range`, which runs for INT and DECIMAL keys. bool is rejected earlier.
   - `tp_mode` is a closed set.
   - The ambient-key rejection extends automatically to the new keys. I found no existing ambient config that collides.
   - WR-01 is the one missing cross-key check.
6. **Scripts.** `geometry_census.py` is Decimal-only (no float anywhere) and reads no network and no secrets. It never writes under `params/`; `--registry-root` is read-only and the global is restored in `finally`. `gen_phase6_fixtures.py` and `_regen_phase4_expectations.py` write only under `tests/fixtures`.
7. **Consumers.** Nothing outside `strategy.py` and `planner.py` references `_detect_*`, `SetupLevels`, or the pivot functions. The 4-tuple wrappers keep the old shape. The backtest engine and paper loop pass planner reject codes straight into `_reject`/`no_trade_records`, and all three codes used are existing `RejectionReason` values. `STRATEGY_WINDOW_BARS=1000` and `CONTEXT_WINDOW_BARS=300` comfortably cover `regime_filter_lookback=50` plus pivot widths.

No Critical findings. The one Warning is a registry validation gap that lets a misconfigured set crash the pure core instead of failing closed.

## Warnings

### WR-01: Registry accepts a range-mr geometry set whose `regime_filter_lookback` is below `pivot_right_bars + 1`; `evaluate()` then raises `ValueError`

**File:** `src/domain/registry.py:470-480` (missing check); raise site `src/core/pivots.py:51-52` via `src/core/strategy.py:141-149`

**Issue:** `_check_geometry_keys` enforces `pivot_right_bars + 1 <= swing_lookback`. For range-mr, though, the only pivot consumer is `_resolve_regime_pivots`, and it uses `regime_filter_lookback` as the pivot lookback, not `swing_lookback`. `pivots._validate` raises `ValueError("pivot lookback must be >= right + 1 ...")` when that lookback is too small. No registry rule relates `regime_filter_lookback` to the pivot widths.

Failure scenario, reproduced: copy `params/range-mr/baseline-v6.toml`, set `regime_filter_lookback = 2` (with `pivot_right_bars = 3`) and load it. `load_parameter_set` returns the set without error. `evaluate()` on the `range_mr_long_window` fixture then raises `ValueError: pivot lookback must be >= right + 1 (4), got 2`.

The exception escapes the pure strategy function. In `src/backtest/engine.py:_evaluate_strategy` there is no handler, so the whole backtest run aborts instead of recording NO_TRADE for the bar. This breaks the fail-closed rule, and `plan()`'s docstring says it never raises.

**Fix:** Add the matching rule to `_check_geometry_keys`, using the same message style as the swing rule:

```python
if (
    has_right
    and strategy_id == "range-mr"
    and "regime_filter_lookback" in params
    and params["pivot_right_bars"] + 1 > int(params["regime_filter_lookback"])
):
    raise StrategyKeyOutsideRegistry(
        f"{path}: pivot_right_bars + 1 ({params['pivot_right_bars'] + 1}) must not exceed "
        f"regime_filter_lookback ({params['regime_filter_lookback']})"
    )
```

Optionally also map a `ValueError` from `_resolve_regime_pivots` to `NO_TRADE_REGIME` in `evaluate` as defense in depth. Add a registry test with `regime_filter_lookback = pivot_right_bars`.

## Info

### IN-01: The PLACEHOLDER/rationale gate has no production caller, and the paper loop bypasses it

**File:** `src/paper/freeze.py:406`, `src/paper/loop.py:342`

**Issue:** `_require_rationalized` runs only inside `pin_stream_epoch`. Nothing under `src/` calls `pin_stream_epoch` (grep: only the definition and the `src/paper/__init__.py` export). `run_paper_tick`, the only paper entry point, calls `load_parameter_set` directly and runs any set, including PLACEHOLDER-bearing `baseline-v6`. The Phase 7 parity fixture deliberately uses `baseline-v6`, so this is consistent today. But the "research-only, refused for paper" guarantee in the v6 file headers is not enforced anywhere a live or paper stream could actually start.

`allow_unrationalized` is a public keyword argument of a production function, documented as test-only. Today it is unreachable from `src/`, which is good, but only convention keeps it that way.

**Fix:** When the live or paper stream start-up lands, make it call `pin_stream_epoch`. Consider moving the escape hatch behind a test-only helper (for example a private `_pin_stream_epoch_unchecked`) so the public signature cannot weaken the gate. Add a test that greps `src/` for `allow_unrationalized=True`.

### IN-02: `INVALIDATED` now carries two meanings (planner D-07 reject and approval/binding invalidation)

**File:** `src/core/planner.py:378-379`

**Issue:** The planner emits `INVALIDATED` when the signal bar already traded through the stop. `src/approval/binding.py` and `src/adapters/telegram_callbacks.py` use the same code for stale or mismatched approvals. Backtest reject records and analytics counters key on `reason_code` only, so a "plan never created because the signal bar hit the stop" is indistinguishable from "approval invalidated". The brief requires reusing existing codes, so this is an accepted trade-off. It limits post-hoc explainability of the decision lineage.

**Fix:** Keep the code, but add a distinguishing field to the planner reject record (for example `stage="planner"`, which the paper loop already records) and mention it in the analytics docs. If a new code is ever allowed, add `STOP_ALREADY_HIT`.

### IN-03: `geometry_census` evaluates one extra bar at the window start

**File:** `scripts/geometry_census.py:428`

**Issue:** `_evaluated_indices` keeps bars with `start_utc <= close_time_utc <= end_utc`. A 1H bar closing at exactly `start_utc` (open 23:00 of the previous day) is included. `--days N` therefore evaluates `24*N + 1` bars, one of which opened before the window. The counts are for the documented "whole UTC days", so this is off by one bar. Impact is small and it is deterministic, but the count semantics should be exact for a census meant to inform a parameter decision.

**Fix:** Use `start_utc < bar.close_time_utc <= end_utc`, or filter on `open_time_utc >= start_utc`.

### IN-04: Regression snapshots are regenerated from the code under test; the script uses bare `assert` for control flow

**File:** `scripts/_regen_phase4_expectations.py:71-84`

**Issue:** `expected_signals.json` and `expected_plans.json` are produced by running the current `evaluate` and `plan`, so they pin whatever the code does, bug or not. The docstring says the output is "printed for hand-verification", which is a manual step. The three snapshot windows are all LONG, so no SHORT plan is pinned by this fixture. The `assert not result.is_no_trade` and `assert signal is not None` lines vanish under `python -O` and would then fail later with an unhelpful `AttributeError` or write a bad file.

**Fix:** Replace the asserts with explicit `raise SystemExit(...)` or `RuntimeError`. Add a SHORT window per family, or cite a test that independently recomputes the geometry (as `tests/test_phase6_fixture_geometry.py` does for the Phase 6 cases).

### IN-05: Rationale checker accepts non-ASCII digits in `ref` and `value`

**File:** `src/domain/rationale.py:105, 161, 119`

**Issue:** `_D_NUMBER = re.compile(r"D\d{3}")` uses `\d`, which matches Unicode decimal digits in a `str` pattern, so `D٠٥٤` passes `fullmatch`. `Decimal(recorded)` likewise accepts Unicode digits and surrounding whitespace, so a recorded value that is not byte-equal to the parameter text can still compare equal. This is cosmetic today, because the files are hand-reviewed. It does weaken a gate whose purpose is to make the provenance trail machine-checkable.

**Fix:** Use `re.compile(r"D[0-9]{3}")` (or `re.ASCII`) and reject `recorded` that is not ASCII (`recorded.isascii()`).

### IN-06: Minor maintainability items

**File:** `src/domain/rationale.py:75-102` and `:71`; `src/risk/gating.py:43-53`; `scripts/gen_phase6_fixtures.py:684-688`

**Issue:**
- `load_rationale`, the strict reader, is used only by tests. It validates less than `check_rationale` (no basis or ref rules), so two validators of one file can disagree.
- `rationale._parameters` calls the private `registry._parse_and_validate`, a coupling to an underscore symbol across modules.
- `gating._plan_geometry_is_valid`'s docstring still says a stop inside the zone is deliberately not rejected because the Phase 6 fixtures emit such plans. That is now false, because the planner rejects them. This is the known stale docstring.
- `gen_phase6_fixtures._write_payload` calls `build_v6_payloads()` once per key, so every `write_*` rebuilds all ten payloads. The output is correct, only wasteful.

**Fix:**
- Delete `load_rationale`, or have `check_rationale` build on it.
- Expose a public `registry.parse_parameters(path)` wrapper.
- Update the docstring.
- Build the payload dict once in `main()` and pass it down.

---

_Reviewed: 2026-10-06_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
