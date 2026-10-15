---
quick_id: 261015-mvq
status: complete
date: 2026-10-15
commit: a64e6af
---

# 261015-mvq summary: compute_features computes the last bar only

## What changed
`src/core/features.py`: `compute_features` computes only the last bar's EMA 20/50/200, ATR, swing high/low and zone, in one `localcontext` at `_PREC` (28), through the new private helpers `_ema_last`, `_atr_last`, `_swing_last`. Same operand order and rounding points, same order of checks and exceptions, same gap rule at the last bar. The series helpers, `ema_update`, `true_range` and `__all__` are untouched. `SIMULATOR_SEMANTICS_VERSION` stays 2.1.0 (user decision: "ok theo khuyến nghị, áp dụng và giữ 2.1.0").

`tests/test_core_features_last_bar_equivalence.py` (37 tests): keeps the old body as a reference and compares `==` and `repr` (warm-up lengths 1..260, full 1000/300-bar windows, gaps, flat and many-digit prices, ATR periods, swing lookbacks, invalid inputs, double-invalid parameters, unsupported interval after the parameter checks).

## Evidence
- Scratchpad candidate `fast_bench/fast_features.py` and the Opus 5.5 stage tests in `equiv/`: 90,280 real-data comparisons (12 symbols, 1h/4h, 2024-10-03..2025-02-28) with 0 mismatches; 34 repo test files, 1,176 passed in both control and candidate; end-to-end engine hashes equal for a01 (289 records) and b01 (44 records), c01 not run (memory guard).
- Full suite after the change (`pytest -m "not docker"`): 6,622 passed, 471 skipped (453 PostgreSQL, 12 shellcheck, 6 Windows), exit 0; the 15 unsupported-interval tests were added afterwards and pass (37/37 in the new file). `ruff check`, `ruff format --check`, `mypy src` clean.
- Two independent Opus 5.5 reviews of the diff: no blocker. Review 1: one test gap (unsupported interval never reached), fixed. Review 2: no rule requires a strategy_version, SIMULATOR_SEMANTICS_VERSION, protocol or DECISIONS change; nothing pins the bytes of `features.py`.

## Accepted differences (user decision, recorded)
- D1: the old `true_range` ran `abs()` in the ambient decimal context; the new ATR runs it inside the pinned context. The results differ only under an ambient precision below 28, which nothing in the repo sets. `true_range` is not changed.
- Errors raised only from arithmetic at non-last bars (huge exponents, infinities) are no longer raised.

## Measured effect (probe scripts, not part of the repo)
Feature function alone about 14x on real 1000-bar windows; a01 30-day..68-day engine runs 9.7x faster, b01 3.4x. Full-run cost not re-measured.

## Not done
No push. No change to manifest, Holdout, ExperimentRecord, protocol or `true_range`. Nits left open: pin the context inside each helper, fix the module docstring wording, a precision-1 documentation test.
