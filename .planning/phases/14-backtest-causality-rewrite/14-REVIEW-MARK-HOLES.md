---
phase: 14-backtest-causality-rewrite
reviewed: 2026-10-07T00:00:00Z
depth: deep
files_reviewed: 3
files_reviewed_list:
  - src/backtest/lifecycle.py
  - tests/test_backtest_exits.py
  - tests/test_backtest_mark_hole_coverage.py
findings:
  critical: 0
  warning: 5
  info: 3
  total: 8
status: issues_found
---

# Phase 14 (plan 14-17): Code Review Report - mark-hole coverage notes

**Reviewed:** 2026-10-07
**Depth:** deep
**Files Reviewed:** 3 (plus cross-reads of `src/backtest/engine.py`, `exits.py`, `records.py`, `report.py`, `series.py`, `semantics.py`, `docs/backtest/BACKTEST_SPEC.md`, plan 14-17 SUMMARY)
**Status:** issues_found

## Summary

Diff reviewed: `git diff 0cccae5..HEAD` over `src/backtest`, the two test files and BACKTEST_SPEC. `tests/test_backtest_mark_hole_coverage.py` (12 tests) and `tests/test_backtest_exits.py` (36 tests) pass, `mypy src/backtest/lifecycle.py` is clean.

No critical defect found. The core claim holds under tracing:

- **Annotation-only (focus 1).** The only writes of the new code are `mark_settled_through_utc` and `coverage_note` (via `replace`). `resolve_mark_minute`, `resolve_fallback_hour` and `end_of_data_exit` never read either field (grep of `exits.py`: `coverage_note` appears only as the output field of `FallbackResolution`). Legs, events, `fallback_applied`, phase, prices and times are untouched. `run_summary` is built from `fallback_applied`, `exit_kind`, counts only, and `report.build` computes percent from `fallback_applied` only, so percent, `fallback_count` and `run_summary` cannot move. The marker is not in `records.py` `to_dict` (explicit dict, line 319 area), so hole-free runs have byte-identical trade payloads: `_join_notes(None, [])` returns `None` and an existing non-empty note is returned unchanged.
- **Minute arithmetic (focus 2).** Mark series are validated aligned and strictly ascending with no overlap (`series.validate_minute_series`), so `next_open - settled <= 1 min` is an exact continuity test, `max()` is a harmless extra guard, and unsorted input cannot reach it. `data_end + 1 ms - 1 min` floored is correct for data end on an exact minute (11:00:00.000 -> last whole 10:59), at 10:59:59.999 (-> 10:59), at 10:59:59.998 (-> 10:58) and mid-minute 10:45:20 (-> 10:44). All datetimes come from UTC-validated candles; no naive/aware mixing path. No float.
- **Marker monotonic / no skipped minutes (focus 3).** Marker only increases (`max`, fallback moves it to bar end, `_fill` sets it before any walk). Straddle note is disjoint from the in-loop notes and from the fallback region (`settled` is the last walked minute strictly before `first_missing`; if the loop breaks at once it yields an empty span). I found no false negative or false positive in the walked-minute logic.

What remains is bounded: unbounded note growth, test gaps that leave the new boundary arithmetic partly unproven, a documented double note that contradicts the stated path-independence, and spec text that is imprecise or silent on the digest consequence.

## Warnings

### WR-01: coverage_note grows without bound and repeats a ~120 character boilerplate per hole

**File:** `src/backtest/lifecycle.py:362-374` (and `:513-518`, `:589-591`)
**Issue:** Every gap appends a full note `mark_price_1m_missing_from_<iso>_to_<iso>; stop and targets not evaluated minute by minute for the missing minutes` (about 180 characters) to `PlanState.coverage_note`, joined with ` | `. There is no time stop (BACKTEST_SPEC section 4: "carried until SL, TP2 or data end"), so a position held for weeks across real Binance mark-series holes (maintenance windows, collector gaps) accumulates one note per hole. The string is copied into every `replace` on each advance, stored in the trade record, hashed into the experiment/trade digests, and `report.build` puts the whole string into `coverage_notes` (a sorted set of full strings, `report.py:859`) and the JSON/markdown sidecars. Nothing validates or caps the length. This is a robustness/maintainability defect of the new feature: a single bad dataset makes the evidence report unreadable and the trade payload large.
**Fix:** Keep notes compact and bounded, deterministically. For example emit only the span in the per-hole entry and put the explanatory sentence once, or cap the number of listed spans and append a count:
```python
_MAX_LISTED_HOLES = 20
# store spans (first, last) in a tuple field and render once in finalize/record build:
# "mark_price_1m_missing: N spans, first 11:20..11:29, ... (+K more); stop and targets not evaluated ..."
```
Any cap must be deterministic (first N spans plus a count), and a test with, say, 200 holes should pin the length.

### WR-02: Boundary arithmetic is only partly proven by the tests (surviving mutations)

**File:** `tests/test_backtest_mark_hole_coverage.py:251-267`, `:270-297`; `src/backtest/lifecycle.py:586`
**Issue:** (a) The `+ timedelta(milliseconds=1)` term in `last_whole = _grid_floor(data_end_utc + 1 ms - _MINUTE)` is untested: the END_OF_DATA test uses data ends `at(11,0)`, `at(10,30)` and `10:45:20`. For all three, `_grid_floor(data_end - 1 min)` gives the same value as the implemented formula (10:59, 10:29, 10:44). Removing the `+1 ms` therefore passes every test, yet it would drop the last whole minute when the data end is `...:59.999` (the canonical close-time convention used by candles in these tests): data end 10:59:59.999 with marks to 10:58 would wrongly report no hole. I derived this by hand; a mutation of that term survives. (b) `test_hour_by_hour_and_one_window_give_the_same_state_and_notes` cuts windows only at hour ends where holes lie strictly inside a window. The behaviour the SUMMARY claims ("same notes however windows are cut") for a hole that spans a window cut (for example 10:55-11:04 with a cut at 10:59:59.999) is not exercised. (c) No test combines a trailing hole after a closing-bar fallback (marker set by the fallback block) with END_OF_DATA, and no test covers a hole that ends exactly at the data end with data end on a `:59.999` close.
**Fix:** Add (1) `_closed_at_data_end(marks_end=at(10,59), data_end=close_of(at(10,59)))` expecting a note for `(10:59, 10:59)`; (2) the same with data end `close_of(at(10,58))` and marks to 10:59 expecting none; (3) a stepped-versus-one-window case with a hole straddling a cut; (4) a bar window with a fallback followed by END_OF_DATA with marks ending early.

### WR-03: The documented double note contradicts the "path-independent" claim and the note text for the same minutes

**File:** `tests/test_backtest_mark_hole_coverage.py:326-353`; `src/backtest/lifecycle.py:485-532`; `.planning/.../14-17-SUMMARY.md` (tech-stack pattern "same notes however windows are cut")
**Issue:** When a mid-bar window (`bar=None`) walks a minute after a hole, the hole is noted as "stop and targets not evaluated minute by minute"; the later closing-bar window then resolves the same minutes by fallback and notes them again as "resolved_at_strategy_bar_close ... from the trade-price bar range, stop first". The trade's `coverage_note` therefore says the same minutes were both not evaluated and resolved, and its content depends on where windows were cut. The path-independence claim only holds for `bar=None` windows (the one test that checks it). In the engine, mid-bar windows for an open symbol come from off-grid window ends (scripted plans, the data end), so the effect is narrow, but the note is part of the trade bytes and digests, so a different window set gives different digests for the same trade. The test pins the double note as intended behaviour, which freezes the inconsistency.
**Fix:** Either (a) suppress the continuity note for a span that a later closing-bar scan of the same bar will claim (only note spans lying wholly before the bar region, which is what `straddle` already does), or (b) keep it but reword the continuity note so it cannot contradict the fallback note, and narrow the SUMMARY/docs claim to "same notes for `bar=None` windows". State the window-cut dependence in the module docstring.

### WR-04: BACKTEST_SPEC paragraph misdescribes the fill-minute rule

**File:** `docs/backtest/BACKTEST_SPEC.md:35`
**Issue:** The text says a note is made when "the minute before the fill minute and the first walked minute are more than one minute apart". Read literally, a hole-free position (fill minute F present, first walked minute F+1) has the minute before the fill (F-1) and the first walked minute (F+1) two minutes apart, so every position would be annotated. The code (`lifecycle.py:213`, `:444-445`) uses the fill minute itself as the settled point when its mark exists, and only falls back to F-1 (so the fill minute is reported missing) when the fill-minute mark is absent. The paragraph also does not say that the fill-minute check evaluates the stop only, nor that the span before a bar region is noted separately from the bar fallback (test E).
**Fix:** Reword: "...are more than one minute apart, counting the fill minute as walked when its mark price exists and as missing otherwise...".

### WR-05: Digest consequence for hole-bearing runs is not stated where the identity is defined, and the semantics version is not bumped

**File:** `src/backtest/semantics.py:5-9,19`, `docs/backtest/BACKTEST_SPEC.md:35,154`; `src/backtest/lifecycle.py` module docstring
**Issue:** `semantics.py` defines `SIMULATOR_SEMANTICS_VERSION` as the experiment identity ("a record produced by v1 can never be compared with v2") and BACKTEST_SPEC section 10 repeats that a record from an old simulator cannot be compared with a new one. For input with a mark hole inside a position's life, the new code changes the trade payload (`coverage_note`) and therefore every hash derived from it, while the version stays `2.0.0`. Two such runs from before and after plan 14-17 carry the same identity but different digests. The honest statement exists only in the planning SUMMARY and `deferred-items.md` ("the semantics version is unchanged", "no non-test experiment record exists"); neither the spec paragraph nor the lifecycle docstring says that hole-bearing runs change bytes. Reasoning "nothing priced or booked changes" is defensible for the version, but the identity guarantee as written in the spec is then not literally true.
**Fix:** Add one sentence to the BACKTEST_SPEC paragraph (and the `lifecycle.py` docstring): "A run with such a hole carries the note, so its trade bytes and derived digests differ from a run of the earlier code; `simulator_semantics_version` is unchanged because nothing priced or booked changes." Alternatively bump to `2.0.1` if the identity must stay literally unique.

## Info

### IN-01: Test D resets the marker on both sides, loosening its whole-state comparison

**File:** `tests/test_backtest_mark_hole_coverage.py:168-170`
**Issue:** `replace(final, coverage_note=None, mark_settled_through_utc=None) == replace(control, mark_settled_through_utc=None)` blanks the marker. In this scenario both runs walk to the stop minute 11:40 and hold the same marker, so the reset is unnecessary and hides a possible difference. Test C two functions earlier compares with the marker intact.
**Fix:** Drop the marker reset (compare `replace(final, coverage_note=None) == control`), or assert `final.mark_settled_through_utc == control.mark_settled_through_utc` explicitly.

### IN-02: `finalize_at_data_end` can emit a misleading trailing note for a state not advanced to the data end

**File:** `src/backtest/lifecycle.py:567-592`
**Issue:** The docstring states the position "is expected to have been advanced through `data_end_utc` first". If a caller finalizes an OPEN state with a marker earlier than the data end (the function is public and the existing lifecycle tests call it directly), the note reports every unwalked minute as having no mark price, which is a false positive. Only the engine guarantees the precondition. Not reachable from the engine, but the function neither checks nor documents the wording effect.
**Fix:** Keep as is but add a test pinning the intended behaviour for a non-advanced state, or note in the docstring that minutes not yet walked are reported as missing.

### IN-03: Trailing note does not tell the reader the END_OF_DATA price is stale

**File:** `src/backtest/lifecycle.py:362-368`, `:586-591`
**Issue:** With a trailing hole, `end_of_data_exit` prices the forced close at the last existing mark minute before the hole. The shared note text ("stop and targets not evaluated minute by minute for the missing minutes") is accurate but does not say that the exit price comes from before the hole, which is the fact an evidence reader needs for END_OF_DATA trades.
**Fix:** Use a distinct trailing wording, for example "...; END_OF_DATA close priced at the last mark minute before the missing minutes".

---

_Reviewed: 2026-10-07_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
