---
phase: 14-backtest-causality-rewrite
reviewed: 2026-10-05T00:00:00Z
depth: deep
files_reviewed: 34
files_reviewed_list:
  - scripts/decision_alignment/bookkeeping.py
  - scripts/decision_alignment/protocol.py
  - scripts/gen_phase14_fixtures.py
  - scripts/gen_phase6_fixtures.py
  - scripts/smoke_backtest_realdata.py
  - src/adapters/analytics_files.py
  - src/adapters/code_version.py
  - src/analytics/excursion.py
  - src/analytics/inputs.py
  - src/analytics/lifecycle.py
  - src/analytics/live_outcomes.py
  - src/backtest/__init__.py
  - src/backtest/case.py
  - src/backtest/constraints.py
  - src/backtest/costs.py
  - src/backtest/engine.py
  - src/backtest/entry.py
  - src/backtest/exits.py
  - src/backtest/experiment.py
  - src/backtest/funding.py
  - src/backtest/ledger.py
  - src/backtest/lifecycle.py
  - src/backtest/records.py
  - src/backtest/report.py
  - src/backtest/semantics.py
  - src/backtest/series.py
  - src/backtest/simulator.py
  - src/backtest/validator.py
  - src/core/strategy.py
  - src/core/types.py
  - src/data/case_input.py
  - src/data/metadata.py
  - src/data/minute_source.py
  - src/risk/realized_risk.py
findings:
  critical: 2
  warning: 11
  info: 8
  total: 21
status: issues_found
---

# Phase 14: Code Review Report

**Reviewed:** 2026-10-05
**Depth:** deep
**Files Reviewed:** 34
**Status:** issues_found

> Note: the reviewer subagent returned this report in its reply rather than writing the file; the orchestrator saved it verbatim.

## Summary

The v2 event-loop engine is carefully built. The main loop through `lifecycle.advance`, `exits`, `funding`, `ledger` and `records` holds up:
- Window handling is half-open on close times, so there is no double funding.
- Heap ordering by `(time, symbol, rank)` is deterministic.
- Signal-bar minutes are never read.
- Strategy and context windows are bisected on close time, so decisions at close T use only data up to T.
- Constraints are looked up point-in-time (see IN-03).

No look-ahead leak was found in the decision path. The problems are elsewhere:
- **Crash from the engine's own output (CR-01).** A mark-data hole in the last bar of the window aborts the whole run.
- **Experiment identity (CR-02).** `assemble` does not tie the engine run to the identity it attests.
- **Verification and evidence gaps.** The record validator, `reproduce`, the evidence loader and allowed-gap recording are weaker than their docstrings claim.
- **Value validation and optimism.** Non-finite values pass the parsers, and the hole fallback prices stops optimistically.

CR-01, CR-02, WR-01 and WR-07 were confirmed with scratch scripts. Existing backtest tests (engine, lifecycle, exits, records, ledger, experiment, report, goldens) pass, so none of these defects is caught by them.

## Critical Issues

### CR-01: END_OF_DATA exit can be dated before the plan's own TP1 leg and aborts the whole simulation

**File:** `src/backtest/exits.py:228-240`; also `src/backtest/lifecycle.py:497-504`, `src/backtest/engine.py:377-380,426-432`
**Issue:**
- `end_of_data_exit` dates the forced close at `last.close_time_utc`, the close of the last mark minute in `[entry, data_end]`. It never considers events the position already produced.
- If the last strategy bar before `data_end` has a mark hole and the trade-price bar range touches TP1, `resolve_fallback_hour` books TP1 at the bar close.
- The position is still open, so `finalize_at_data_end` then closes it at an earlier last-mark time.
- `exit_time < tp1_time`, so `build_trade_record` -> `validate_trade_record` raises `TradeRecordInvariantError` and the entire run produces no output.
- The heap also pops the earlier-dated EXIT before the later TP1. Without the validator, `_update_exposure` would fail in `ledger._find_exposure` (unknown exposure).

Reproduced: scripted LONG, signal at 08:59:59.999, fill at 09:05, mark series present only for 09:00-09:59, trade bar 10:00 high 104.5 (TP1 = 104), `data_end` = 11:00. Result: `TradeRecordInvariantError: tp1_time 2026-01-05T10:59:59.999 must be <= exit_time 2026-01-05T09:59:59.999`.

Real-data runs are exposed: a data window ends at midnight, the last bar's hole is rarely allowed, and with a stale mark the close is dated earlier.

**Fix:** Never date the forced close before the position's latest event. Clamp inside the leg (not only at the booking, as `_not_before_last_booking` does):
```python
# exits.py end_of_data_exit
floor_time = max(entry_time, state.tp1_time_utc or entry_time)
...
return ExitLeg(kind=EXIT_END_OF_DATA, price=last.close, quantity=remaining,
               time_utc=max(last.close_time_utc, floor_time))
```
Add a regression case to the Phase 14 goldens: mark hole in the final bar plus a TP1 touch.

### CR-02: `assemble` does not bind the engine run to the identity it attests

**File:** `src/backtest/experiment.py:578-712` (checks at 622-661, identity payload at 672-688)
**Issue:** The experiment record is the choke point for the six-field identity, but several identity inputs are never checked against each other.
- `strategy_version` is taken from the caller and never compared with `parameter_set.strategy_version`. The engine enforces that (`engine.py:840`), but `assemble` does not. Verified: `assemble(**assemble_kwargs(strategy_version="v999.0.0-bogus"))` succeeds and yields a new `experiment_id`.
- `assemble` accepts only `run_summary`, which carries no `parameter_set_hash`, `cost_model_hash`, `strategy_version` or `symbols`. A summary from a different parameter set or universe is accepted under this record's identity.
- `universe` (hashed into `universe_hash`) is free-form and never compared with the run's `symbols`.

**Fix:** Pass the whole engine output (or add `parameter_set_hash`, `cost_model_hash`, `strategy_version` and `symbols` to `run_summary`). In `assemble`, require:
- `parameter_set.strategy_version == strategy_version`
- `output["parameter_set_hash"] == parameter_set.parameter_set_hash`
- `output["cost_model_hash"] == cost_model.cost_model_hash`
- `sorted(universe) == output["symbols"]`

Raise `IncompleteExperimentRecord` on any mismatch.

## Warnings

### WR-01: The trade-record validator is documented as complete but misses most cross-field invariants

**File:** `src/backtest/validator.py:56-66,127-150`
**Issue:** `_validate_unfilled` checks only the three exit fields. `_validate_vocabulary` checks only that the kinds are in the vocabularies. Verified with `make_record` that all of these pass `validate_trade_record`:
- `entry_kind="ENTRY_FILLED"` with no fill (`entry_time_utc=None`)
- a filled record with `entry_kind="EXPIRED"`
- a filled record with no `exit_kind`, `exit_price` or `exit_time_utc`
- `PARTIAL_FILL` with `quantity == planned_quantity`
- an unfilled record carrying `realized_pnl`

`report._classify` and the evidence loader rely on this validator. A record with `outcome_kind="OK"` and a filled `entry_kind` but a missing `realized_risk` or `realized_pnl` is counted in `trade_count` yet silently dropped from the R distribution. That is what the "closed filled trades only" rule in plan 14-11 was meant to prevent. The zero-risk exclusion is the only counted one (`report.py:648`).

**Fix:** Add checks:
- filled kind <=> `entry_time`, `entry_price` and `quantity` present
- `PARTIAL_FILL` <=> `quantity < planned_quantity`
- a filled `outcome_kind == "OK"` record has `exit_kind`, `exit_price`, `exit_time`, `realized_pnl` and `realized_risk`
- an unfilled record has `quantity`, `realized_pnl` and other fill-derived fields all `None`

### WR-02: The evidence loader accepts trades that do not belong to the experiment

**File:** `src/adapters/analytics_files.py:621-631` (trades loaded at 479-499)
**Issue:** `_load_backtest_entry` loads `experiment`, `trades`, `contexts` and `flags` independently. The experiment's time range, `parameter_set_hash`, `strategy_version`, `end_of_data_count`, `fallback_count` and any stored `trades_digest` are not compared with the trades. The data window is known here, but `validate_trade_record` is called without it. Trades from another run can be paired with a candidate experiment and feed the kill gate. `reproducibility_verified` and the other flags are self-asserted booleans.

**Fix:** After loading, assert:
- every trade has the experiment's `strategy_version` and `parameter_set_hash`
- every symbol is in the research universe
- every `exit_time` and `signal_close` lies inside `[time_range_start_utc, time_range_end_utc]`
- the `fallback_applied` and `END_OF_DATA` counts equal the record's typed counts
- the recomputed trades digest equals `result_summary_json["trades_digest"]` when present

### WR-03: Reproducibility checks can pass vacuously

**File:** `src/backtest/experiment.py:940-941,985-996` (also 657-661, 918-919, 868-870)
**Issue:**
- `reproduce(record, simulator_inputs={})` returns `[]`, and `verify_experiment` then compares two empty digests and returns `None` ("reproducible") with no stored digest. The tripwire passes while checking nothing.
- A case that omits `dataset_id` skips the dataset binding in both `assemble` and `_check_run_binds_record`. Any data under the same window re-runs and passes. `dataset_id` is `None` unless the case carries one.
- `_check_inputs_bind_record` does `simulator_inputs["strategy_id"]` and `["cost_model"]`, so a missing key raises `KeyError` instead of `ExperimentReproducibilityBroken`. It also never checks `symbols` against `universe_hash`.

**Fix:**
- Raise `ExperimentReproducibilityBroken` for empty inputs.
- Require a non-null `dataset_id` equal to `record.data_snapshot_id` in both `assemble` and `reproduce`.
- Use `.get` and wrap missing keys in the same exception.

### WR-04: The mark-hole fallback prices stops optimistically and never flags gaps

**File:** `src/backtest/exits.py:203-205`
**Issue:** `_stop_leg` (mark path) books the adverse of trigger and minute open and sets `gap_through_stop`. `resolve_fallback_hour` always books the stop at `trigger` with no gap flag. For a position already open at the start of the bar, a bar that opens beyond the stop (gap down for a LONG) is priced as if the stop filled exactly at the trigger. This is the situation where a mark hole coincides with a gap, and the realized loss is understated.

**Fix:** When `state.entry_time_utc < bar.open_time_utc`, use `min(trigger, bar.open)` for a LONG (`max` for a SHORT) and set `gap_through_stop=price != trigger`. For a fill inside the bar the open is pre-fill and must not be used.

### WR-05: Acknowledged allowed gaps of non-funding series leave no trace in the experiment record

**File:** `src/backtest/engine.py:253-257,313-325,571-573`; `src/backtest/experiment.py:199-208`; `src/data/case_input.py:193-203`
**Issue:** `build_case_input_data(allow_gaps=...)` emits acknowledged gaps for the bar, 1m trade, 1m mark and open-interest series. The engine records only gaps used by the funding coverage check, and `RecordedGap` rejects any series other than funding. A run over data with acknowledged missing 1m minutes or strategy bars is recorded as having used no gaps. Only `fallback_count` is a partial proxy.

**Fix:** Record every acknowledged gap in `allowed_gaps_used`, or add a separate `allowed_gaps_acknowledged` field. Relax the `RecordedGap` series check accordingly.

### WR-06: Drawdown, bootstrap and stability use signal-close order, not realized-time order

**File:** `src/backtest/report.py:638-651,520-558,762-765`; `src/backtest/engine.py:309-312`
**Issue:** The engine sorts trades by `signal_close_utc`. `build` feeds `r_values` in input order to `_max_drawdown` and to the block-bootstrap resamples. With overlapping holding periods the signal order differs from the order in which results were realized, so the observed and resampled drawdowns and the block dependence are not the equity path. The excursion section already sorts by exit time (`excursion.py:286`).

**Fix:** In `build`, sort closed trades by `(exit_time_utc, trade_id)` before computing `r_values`.

### WR-07: Funding rows and minute rows accept non-finite values

**File:** `src/backtest/funding.py:66-74,102-122`; `src/backtest/series.py:147-155,173-204`
**Issue:** `case._decimal` checks `is_finite()`, but `parse_funding_row` and `parse_minute_row` do not. Verified:
- `funding_rate="NaN"` parses, and `funding_pnl` returns `NaN`. A NaN booking would reach the ledger equity, and the first `>` comparison then raises an opaque `InvalidOperation` mid-run.
- A minute row with `high="Infinity"` is accepted by `Candle`.

**Fix:** Reject non-finite values in `_parse_decimal` and `_parse_money`. Also require `mark_price > 0` when it is present on the funding row.

### WR-08: `weak_live_universe_rejection` is false when the live-5 universe has no trades

**File:** `src/backtest/report.py:829-836`
**Issue:** The flag requires `live5_slice.mean_r is not None`. If the research universe is positive and live-5 has zero R-valued trades (`insufficient_data=True`), the flag stays `False`. That is the "broader universe rescues a weak live universe" case BACKTEST_SPEC §10.1 forbids.

**Fix:** Treat `live5_slice.insufficient_data` (when research is positive) as a rejection, or expose a separate `live_universe_unproven` flag that the gate reads.

### WR-09: Mark holes outside the closing-bar window, and on the fill minute, are silently ignored

**File:** `src/backtest/lifecycle.py:312-332,429-447`
**Issue:** `_first_missing_mark_open` runs only when `bar is not None`, i.e. when the window ends at this symbol's own strategy-bar close, and it scans from `ceil(entry_time)`.
- A window that ends at another symbol's close, at a scripted close, or at a close where this symbol has no strategy bar (an allowed gap in the bar series) passes `bar=None`. Holes in its mark minutes are skipped with no fallback and no `fallback_applied` flag.
- The next window starts after them, so a stop touched in a missing minute is never detected.
- A hole exactly on the fill minute skips the fill-minute stop check, also unflagged.

**Fix:** Run the hole scan for every window that ends mid-bar too. At the next bar-close window, extend the scan back to the earliest un-scanned minute, or record a coverage note when minutes are skipped without a bar to fall back on.

### WR-10: `dataset_id` need not cover the 1m files the engine reads

**File:** `src/data/case_input.py:617-681` (series validation at 298-301)
**Issue:** `used` includes the 1m trade and mark partitions only when `intrabar_1m` or `mark_1m` is in `series`. `series` accepts any non-empty subset. `dataset_id` is what the engine copies into `run_summary` and what `assemble` binds. A case built with `series=("trade","funding")` still runs against a lazily supplied `ParquetMinuteSource` over 1m files that are not in the identity.

**Fix:** Require `{"trade","intrabar_1m","mark_1m","funding"} <= set(series)` for any case meant for the engine. Alternatively, always hash the 1m partitions in the case builder, as the module docstring claims.

### WR-11: Phase 6 fixture generator output is platform-dependent

**File:** `scripts/gen_phase6_fixtures.py:510-512`
**Issue:** `_write` uses `Path.write_text(json.dumps(..., indent=2), encoding="utf-8")`. On Windows this writes CRLF and writes no trailing newline. `gen_phase14_fixtures.render` correctly writes LF bytes with a trailing newline. `tests/test_phase6_fixture_geometry.py` compares generator bytes to committed bytes, so it passes only through git's autocrlf (the index has `i/lf`, the working copy `w/crlf`). It would fail on a Windows checkout with `core.autocrlf=false`.

**Fix:** Write `path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))`. Regenerate the fixtures once, since the added trailing newline changes every file.

## Info

### IN-01: Magic strings duplicate existing constants
**File:** `src/backtest/engine.py:115-118`
**Issue:** `_UNCERTAIN_ACCOUNT_STATE`, `_MIN_QTY_REJECT`, `_SOURCE_TIMEFRAME` and `_CONTEXT_TIMEFRAME` repeat `RejectionReason.UNCERTAIN_ACCOUNT_STATE.value`, `RejectionReason.MIN_QTY_REJECT.value`, `case.STRATEGY_INTERVAL` and `case.CONTEXT_INTERVAL`. `_require_utc` is also duplicated in `lifecycle`, `ledger`, `constraints` and `funding`.
**Fix:** Import the shared constants and helpers.

### IN-02: Arithmetic outside the pinned decimal context
**File:** `src/backtest/lifecycle.py:230`; `src/backtest/funding.py:146`; `src/backtest/engine.py:178`; `src/backtest/report.py:488`
**Issue:** `remaining - leg.quantity`, unary minus in `funding_pnl`, `value // step` and `q**length` run in the ambient context. The core rule is that every operation runs in `_add`/`_sub`/`_mul`/`_div`'s pinned prec-28 context. Inert at the default context, but breaks "regardless of ambient context".
**Fix:** Use `_sub`, `_sub(_ZERO, x)` and the helpers.

### IN-03: Point-in-time constraints back-extrapolate from the earliest recorded row, which may be after the bar
**File:** `src/backtest/constraints.py:187-189`; `src/data/metadata.py:95`
**Issue:** `refresh_symbol_metadata` stamps `observed_at` with the refresh time, so for a historical window every bar precedes the first row. The engine uses a row observed after the bar (future information about tick, step and notional) and reports it only as `constraints_extrapolated_count`. Documented (D-30), but a latent look-ahead path.
**Fix:** Make a non-zero `constraints_extrapolated_count` a visible caveat on the evidence. Consider a gate that fails when more than a configured fraction of trades are extrapolated.

### IN-04: Scripted plans do not guard against duplicate `signal_id`
**File:** `src/backtest/case.py:480,538-543`
**Issue:** `trade_plan_id = derive_child_id(signal_id, ...)`. Two scripted plans for different symbols with the same `signal_id` get the same plan id, and `ledger.register_exposure` then raises "already registered" mid-run. `plan_hash` also hashes raw Decimals, unlike the planner's canonical text (D-12).
**Fix:** Reject duplicate `signal_id`s at parse time. Hash `canonical_decimal_text` values.

### IN-05: Inconsistent kinds handling between modules
**File:** `src/analytics/lifecycle.py:46-56`; `src/backtest/experiment.py:765-770`; `src/backtest/experiment.py:379-381`
**Issue:**
- `_BACKTEST_UNFILLED_KINDS` still lists `TOUCH_NO_FILL`, but the validator in `normalize_backtest` refuses it, so that branch is unreachable.
- `_coerce_trade_decimal` converts floats via `str(value)` while the rest of the backtest refuses floats.
- `ExperimentRecord._validate_values` requires `funding_convention` but not `exit_slippage_rate`, so a legacy cost model that cannot size is accepted.

**Fix:** Remove the dead kind. Refuse floats. Require `exit_slippage_rate` in `cost_values`.

### IN-06: Report standard deviation is the population value and feeds a standard error
**File:** `src/backtest/report.py:414-423,722`
**Issue:** `_decimal_pstdev` divides by `n`, and `se_diagnostic = std / sqrt(n)` uses it. For small samples the standard error is understated by `sqrt(n/(n-1))`.
**Fix:** Use the sample standard deviation (`n - 1`) for the diagnostic.

### IN-07: Gate script nits
**File:** `scripts/decision_alignment/protocol.py:104,211`; `scripts/decision_alignment/bookkeeping.py:370-377`
**Issue:**
- `_HEX64 = re.compile(r"^[0-9a-f]{64}$")` with `.match` accepts a trailing newline.
- `check_no_human_pass` compares forbidden phrases case-sensitively, so "Recorded human decision" at a sentence start passes.
- `run_reqs` returns `ok=True` ("SKIP") for RQ-01..05 when `.planning` files are absent, so the gate passes vacuously.

**Fix:** Use `fullmatch`. Lower-case both sides in the forbidden-phrase check. Return a distinct `SKIP` outcome that a strict mode treats as failing.

### IN-08: Stale and latent items
**File:** `src/backtest/__init__.py:3-6`; `src/backtest/engine.py:657-667`
**Issue:**
- The package docstring claims stdlib-only purity, but it imports `experiment`, `binding` and `simulator`, which pull `src.domain.registry` and `src.risk.gating`.
- `_evaluate_strategy` passes `planned.reason_code` to `_reject` -> `build_reject_record`, which raises `ValueError` for any code outside `RejectionReason`. `planner.plan` can return a raw feature reason code such as `WARMUP_INSUFFICIENT`, so this is a latent run abort if the planner's feature gate ever disagrees with `evaluate`'s.
**Fix:** Update the docstring. Map non-enum planner reasons to `DATA_STALE`, as `strategy.evaluate` does, or count them as NO_TRADE instead of recording a reject.

---

_Reviewed: 2026-10-05_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
