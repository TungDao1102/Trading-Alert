# 04-04 SUMMARY — Breakout-Retest + Range-MR Slices + Phase Gate

**Plan:** 04-04 (Wave 3, depends on 04-02, 04-03)
**Status:** Complete
**Requirements:** STRAT-02, STRAT-03

## Objective

Land breakout-retest and range-mr as parallel slices on the proven tracer harness per D-05, then close the phase gate. All three families exist as hypotheses with real expectations; no winner declared.

## Tasks

### 1. Breakout-retest evaluate branch (tdd) ✓

- Branch dispatched on `strategy_id == "breakout-retest"` in `src/core/strategy.py`.
- Breakout detection on closed-bar structure from shared `compute_features` zones; confirmation over `breakout_confirmation_bars` closed bars; retest countdown starts at the breakout-bar close (retest on the breakout bar itself never counts); acceptance within `retest_window_bars` (5) and depth `retest_depth_atr` (0.3) × ATR; volume confirmation against `breakout_volume_threshold` (1.5) where the fixture provides volume.
- `setup_type` BREAKOUT_RETEST_LONG/SHORT, fingerprint per the 04-03 locked key list, `make_signal_id` (no cross-family collisions).
- Commit: `ddbad67` (Family B branch with TDD pin).

### 2. Range mean-reversion evaluate branch (tdd) ✓

- Branch dispatched on `strategy_id == "range-mr"`.
- Range from clustered swings (`zone_min_touches` 2, half-width `zone_tolerance_atr` × ATR); touch counting on closed bars only; aging cutoff at `zone_aging_bars` (50); regime filter over `regime_filter_lookback` (50) 1H bars requiring neutral; range-break invalidation on 1H close beyond edge by more than `range_break_buffer_atr` (0.2) × ATR — invalidate, never redraw; TP mode per the 04-03 checkpoint decision.
- NEUTRAL regime passes the regime gate for range-mr only (all other families still NO_TRADE on NEUTRAL).
- Zero winner-language tokens in code, comments, tests, fixtures.
- Commit: `c44128f` (Family C branch with TDD pin).

### 3. Family fixtures + per-family determinism + phase gate ✓

- `tests/fixtures/phase4/candles.csv` extended with B/C decision windows (1060 1H + 1000 4H); `expected_signals.json` / `expected_plans.json` extended with B/C expectations.
- One-off generator scripts (`scripts/_extend_phase4_candles_bc.py`, `_compute_phase4_fixtures_bc.py`, `_check_fixtures.py`) deleted after use (04-01 precedent).
- Phase-gate repair (orchestrator close-out): the grown fixture's intentional gap blocks poisoned shared-stream consumers — 9 planner tests (DATA_STALE via full-4H context) + 2 determinism canaries (leaky/stateful perturbations masked by gap poison). Fix: each suite truncates to its first contiguous block (1H: 250 bars, 4H: 500 bars — the pre-04-04 layout); B/C windows remain for family tests. Touched: `test_core_planner.py` (4H truncation), `test_no_lookahead.py`, `test_prefix_invariance.py`, `test_candle_close_timing.py` (first-block truncation in `_split_phase4_by_timeframe`).
- mypy strict clean over `src/core` (fixed unused-ignore in `types.py`, bare `list` in `_find_retest_bar` + `FeatureOutput` import).
- `ruff check` clean on all touched files (one pre-existing I001 late-import block in `types.py:307` left intact — circular-import avoidance; `ruff format --check` fails repo-wide including phase-3 files, pre-existing style drift, not introduced here).

## Verification

- `uv run pytest tests/test_core_strategy_breakout_retest.py tests/test_core_strategy_range_mr.py -q` → green.
- Full suite `uv run pytest tests/ -q` → 283 passed, 5 skipped, 0 failed.
- `uv run mypy src/core/` → clean.
- No-winner rule: three hypotheses, no ranking language.

## Deviations

- `tests/test_core_strategy_trend_pullback.py` (named in plan frontmatter/verify) was never created by earlier waves; trend-pullback per-family coverage lives in `test_core_tracer.py` + `test_core_planner.py` + `test_core_features.py` (all green). No new file created to avoid redundancy.
- Shared-suite truncation edits touch 04-02/04-03 test files (documented above as the phase-gate repair); no production-behavior files outside 04-04 scope were modified for the repair.

## Follow-ups (out of scope)

- `ruff format --check` repo-wide drift (phase-3 files included) — needs a dedicated formatting pass, not a phase-4 behavior change.
- `.planning/phases/03-domain-registry-fixtures/03-VERIFICATION.md` present untracked (phase-3 leftover) — left untouched.
