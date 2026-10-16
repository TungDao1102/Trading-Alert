---
quick_id: 261015-mvq
date: 2026-10-15
type: quick
autonomous: true
files_modified:
  - src/core/features.py
  - tests/test_core_features_last_bar_equivalence.py
---

# 261015-mvq: compute_features computes the last bar only (byte-identical)

## Authority
User words (2026-10-15): "ok theo khuyến nghị, áp dụng và giữ 2.1.0". Basis: scratchpad candidate `fast_bench/fast_features.py`;
evidence `equiv/` (Opus 5.5 stage tests: 90,280 real-data comparisons, 34 repo test files 1,176 passed in both control and candidate,
end-to-end engine hashes equal for a01 and b01; c01 not tested) and the adversarial review (differences D1-D5, none reachable from real callers).
Decisions fixed by the user: keep `SIMULATOR_SEMANTICS_VERSION` 2.1.0; do NOT touch `true_range` (D1 accepted).

## Task 1 - rewrite the body of `compute_features` (src/core/features.py)
- Compute only the last bar: EMA 20/50/200 and ATR as Decimal recurrences over the window, swing high/low as one window max/min, zone from the last ATR and swing, all inside ONE `localcontext` with `prec = _PREC`.
- Keep the order of checks and exceptions of the old body: empty, symbol/interval, timestamps, `int(swing_lookback)` and zone tolerance parse, EMAs, then `int(atr_period)` and the ATR period check, then the swing lookback check, zone, then `_expected_bar_duration` and gaps.
- Keep every existing helper unchanged (`_ema_series`, `_atr_series`, `_swing_series`, `_zone_series`, `ema_update`, `true_range`). Do not change the signature or the returned `FeatureFrame`.
- Gap rule at the last bar: a warm-up invalid feature keeps WARMUP_INSUFFICIENT; a valid one becomes GAP_IN_SOURCE.

## Task 2 - regression test (tests/test_core_features_last_bar_equivalence.py)
- Hold the OLD body as a reference function inside the test (it uses the unchanged series helpers) and compare `a == b and repr(a) == repr(b)` over seeded synthetic candles: warm-up lengths 1..260, full 1000- and 300-bar windows, one and two gaps, several parameter sets loaded from the registry, many-digit prices, flat bars; and compare exception type and message for invalid inputs and double-invalid parameters.

## Verification
- New test and `tests/test_core_features.py tests/test_no_lookahead.py tests/test_core_tracer.py tests/test_core_planner.py tests/test_domain_boundary.py tests/test_core_strategy*.py tests/test_planner_geometry.py tests/test_rationale.py tests/test_paper_*.py` pass; full `pytest -m "not docker"`, `ruff check`, `ruff format --check`, `mypy src` green; `SIMULATOR_SEMANTICS_VERSION` still 2.1.0.
- Two independent reviewers read the diff before commit. No push. No manifest, Holdout, ExperimentRecord or protocol change.
