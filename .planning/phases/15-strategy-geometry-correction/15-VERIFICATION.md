---
phase: 15-strategy-geometry-correction
verified: 2026-10-06T00:00:00Z
status: human_needed
score: 4/4 must-haves verified
covered_files:
  - .planning/phases/15-strategy-geometry-correction/15-01-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-01-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-02-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-02-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-03-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-03-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-04-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-04-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-05-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-05-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-06-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-06-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-07-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-07-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-08-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-08-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-09-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-09-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-10-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-10-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-11-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-11-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-12-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-12-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-13-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-13-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-14-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-14-SUMMARY.md
  - .planning/phases/15-strategy-geometry-correction/15-15-PLAN.md
  - .planning/phases/15-strategy-geometry-correction/15-15-SUMMARY.md
  - docs/research/GEOMETRY_AUDIT.md
  - params/breakout-retest/baseline-v6.toml
  - params/range-mr/baseline-v6.toml
  - params/trend-pullback/baseline-no-trade-v4.toml
  - params/trend-pullback/baseline-simple-trend-v4.toml
  - params/trend-pullback/baseline-v6.toml
  - src/core/pivots.py
  - src/core/planner.py
  - src/core/strategy.py
  - src/domain/rationale.py
  - src/domain/registry.py
  - src/paper/freeze.py
covered_digest: "v2:sha256:577659e88a84d1166ea1f6cededd02c3408c3042b8f6c053589c020e79d1d7dd"
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Decide whether the planner should also reject a TP1 that lies on the profit side of the entry reference but inside the far half of the entry zone"
    expected: "Either a recorded decision to keep the current rule (TP1 only has to be strictly on the profit side of the entry_ref midpoint) or a one-line tightening of _geometry_rejection in src/core/planner.py with a test"
    why_human: "Safety/geometry rule with money impact. D054 item (g) and the 15-04 observation deliberately left it for a user decision. The verifier did not choose it."
  - test: "Confirm the DECISION/D054 basis recorded for the three -v4 override values (baseline-no-trade-v4 minimum_rr 100; baseline-simple-trend-v4 zone_tolerance_atr 1.0 and minimum_rr 0.5)"
    expected: "User accepts the DECISION/D054 labels, or names a different basis"
    why_human: "Parameter provenance is a parameter choice. The 15-08 checkpoint text gave no basis for these three values; the basis was taken from the wording of plan 15-09 and was flagged in the 15-08 SUMMARY for user attention. D054 records them as ratified with the single reply 'ratify', which the verifier can only read in the SUMMARY, not independently confirm."
  - test: "Acknowledge that baseline-v6 (16/29, 17/31, 22/36 PLACEHOLDER keys) and both -v4 sets (15 and 14 PLACEHOLDER keys) are research-only, and that the PLACEHOLDER refusal gate has no production caller yet (review IN-01)"
    expected: "Accepted for Phase 15; Phase 16 start-up must call pin_stream_epoch (or an equivalent) so the refusal is enforced where a stream starts"
    why_human: "Accepting PLACEHOLDER-grade parameter values and deferring gate wiring is a risk acceptance. pin_stream_epoch refuses these sets when called, but nothing under src/ calls it, and run_paper_tick loads any set."
---

# Phase 15: Strategy Geometry Correction Verification Report

**Phase Goal:** Each family's implemented geometry matches its family sheet and is economically sane before any research run is trusted.
**Verified:** 2026-10-06
**Status:** human_needed (all four ROADMAP criteria are met in the code; three decisions are left to the user)
**Re-verification:** No, initial verification

## Goal Achievement

### Observable Truths (ROADMAP success criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Trend-pullback: SL outside the entry zone with a minimum ATR distance; swings use confirmed pivots only, excluding the evaluated bar, so a setup cannot fire on a new 20-bar low (F-301) | VERIFIED | `src/core/pivots.py` read in full: candidates `t <= i - right`, so the evaluated bar only confirms; tie rule non-strict left / strict right; `None` when no pivot, no trailing-extreme fallback; `_validate` rejects `lookback < right + 1`. `src/core/strategy.py::_detect_pivot_setup` (line 214) uses it, no fallback; wired from `evaluate` (line 854) behind `geometry_version`. `src/core/planner.py::_pivot_geometry` puts the stop at `zone_lower - entry_buffer - sl_buffer` (LONG) / `zone_upper + entry_buffer + sl_buffer` (SHORT), i.e. beyond the outer edge of the whole entry zone. `_geometry_rejection` is called once for every plan (planner.py:592), on quantized stored prices, before the RR gate: STOP_TOO_TIGHT if SL not strictly outside the zone, INVALIDATED if the signal bar traded through SL, STOP_TOO_TIGHT if below `min_stop_atr` x ATR (when the key is present), RR_TOO_LOW if TP1 not on the profit side. Tests pass: `test_core_pivots` (17, incl. evaluated-bar-never-the-level, 300-bar prefix invariance, poisoned later candles), `test_core_strategy_geometry` (7, incl. p9 regression "new low beyond tolerance does not signal"), `test_planner_geometry` (88), `test_geometry_property` (25). |
| 2 | Implemented geometries of all three families match the sheets' Stage baselines, or a DECISIONS entry records the deviation (F-113) | VERIFIED | `docs/research/GEOMETRY_AUDIT.md`: 20 family-cell rows, final, no PARAMETER verdict left (5 MATCH, 8 FIX, 7 DEVIATION, matching D054 item (a)). Each FIX row names its implementing function and each exists (`pivot_at`, `_detect_pivot_setup`, `_pivot_geometry`, `_breakout_retest_geometry`, `_range_mr_geometry`, `_resolve_regime_pivots`, `_detect_breakout_retest_levels`/`_find_retest_bar`, `tp_mode` T_MID). D054 in `docs/DECISIONS.md` (line 58) lists all 7 deviations with reasons. `tests/test_geometry_audit_doc.py` (20) passes. Family sheets carry "3.2 Implemented as (Phase 15, D054)" in all three files. GLOSSARY and CONFIGURATION key table updated (geometry_version, pivot_left_bars, pivot_right_bars, tp_mode, min_stop_atr). |
| 3 | New versioned parameter sets record a rationale for every value; no fixture seed values (F-909) | VERIFIED | Loaded all five new sets through the real registry: baseline-v6 trend-pullback hash 2c4f1528 (29 params), breakout-retest 289d47ac (31), range-mr c9023e47 (36), baseline-no-trade-v4 98e541ee (29), baseline-simple-trend-v4 27f4c18b (29); `check_rationale` returns 0 problems for all five; hashes equal D054 and `tests/fixtures/phase4/parameters.json`. Every value carries a basis from STRUCTURAL/COST_GUARD/DECISION/EXPERIMENT/PLACEHOLDER. Values with no empirical or structural basis are labelled PLACEHOLDER (16, 17, 22, 15, 14 keys), not passed off as tuned. `git diff bbb4bca..HEAD -- params` shows only 5 added files; all 20 older sets are byte-untouched. Tests pass: `test_rationale` (34), `test_registry` (167 incl. WR-01 cross-key rule), `test_registry_gate`, `test_decision_alignment_params` (58), `python -m scripts.decision_alignment.params` PA-01..PA-08 all ok. |
| 4 | Research re-run under protocol v2.0.0 is ready on the Phase-14 engine (run itself out of scope) | VERIFIED | GEOMETRY_AUDIT.md "Re-run readiness" defines the F8 check and records, per family, two smoke runs with equal digests, only canonical no-trade codes, and census `invariant_violations 0`; D054 (h) repeats it and lists what the re-run still needs. No backtest or re-run was started by the verifier; the recorded smoke/census runs were not re-executed (data-dependent, minutes each). The machine-checkable parts were re-run: `test_geometry_census` (30), `test_geometry_property` (25), `test_backtest_determinism` (16), `test_backtest_simulator` (63), `test_backtest_engine_strategy` (11), `test_backtest_experiment`, `test_cost_parity`, `test_paper_parity`, `test_phase6_fixture_geometry` (CRLF normalization fix F12 holds) all pass. |

**Score:** 4/4 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/core/pivots.py` | confirmed pivots, pure, prefix-invariant | VERIFIED | 120 lines, wired from strategy.py and planner.py (18 callers per codegraph) |
| `src/core/planner.py` | corrected geometry per family + shared validator | VERIFIED | `_pivot_geometry`, `_breakout_retest_geometry`, `_range_mr_geometry`, `_geometry_rejection` all present and on the plan path |
| `src/core/strategy.py` | pivot setup, anchored B, pivot regime C | VERIFIED | gated on `geometry_version`; legacy path kept byte for byte |
| `src/domain/rationale.py`, `src/domain/registry.py` | rationale check; optional keys with ranges | VERIFIED | 0 rationale problems on the five sets; WR-01 fix present |
| `src/paper/freeze.py` | PLACEHOLDER refusal | VERIFIED (not wired in prod) | `_require_rationalized` raises `UnrationalizedParameterSet`; see IN-01 |
| `params/**/baseline-v6.toml`, `-v4` sets | 5 new sets | VERIFIED | hashes match pins |
| `docs/research/GEOMETRY_AUDIT.md`, D054, sheets | audit and deviations | VERIFIED | see truth 2 |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `evaluate` | `_detect_pivot_setup` | `geometry_version(parameter_set)` branch, strategy.py:853-854 | WIRED |
| `plan` | `_geometry_rejection` | single call, planner.py:592, after quantization, before RR gate | WIRED (all sets, legacy included) |
| `_pivot_geometry` | `pivot_at` | same setup candles as the detector | WIRED |
| `pin_stream_epoch` | `_require_rationalized` | freeze.py:342-351 | WIRED inside the function; the function itself has no production caller (IN-01) |

### Behavioral Spot-Checks (file by file, never the full suite)

All passed unless noted. test_core_pivots 17, test_core_strategy_geometry 7, test_planner_geometry 88, test_registry 167, test_registry_gate 7, test_rationale 34, test_paper_freeze 10, test_kill_gate_docs 10, test_decision_alignment_params 58, test_decision_alignment_bookkeeping 46, test_geometry_audit_doc 20, test_core_strategy_breakout_retest 30, test_core_strategy_range_mr 36, test_core_planner 17, test_geometry_property 25, test_geometry_census 30, test_analytics_files (1 skip, pre-existing), test_phase6_fixture_geometry, test_backtest_simulator, test_backtest_engine_strategy, test_backtest_experiment, test_cost_parity, test_cost_per_unit, test_domain_no_float, test_paper_parity, test_backtest_determinism. Also `ruff check`, `ruff format --check` (388 files) and `mypy src` (149 files) clean.

Not run, need CI: PostgreSQL tests (skipped without `TEST_DATABASE_URL`, including 20 of 22 in `tests/test_plan_hash_roundtrip_pg.py`), and docker/bootstrap/deploy tests (test_bootstrap, test_deploy_backup_scripts, test_docker_*).

### Requirements Coverage

STRAT-01 and STRAT-02 are listed for Phase 15 in ROADMAP; REQUIREMENTS.md maps both to Phase 4 (Complete). The Phase 15 plans re-touch the same engine, and the behavior in those requirements (closed-candle features, pure strategy function, deterministic SignalIds) is still covered: prefix invariance, determinism and SignalId tests pass. No orphaned requirement. No change to REQUIREMENTS.md is needed.

### Anti-Patterns Found

None blocking. No TBD/FIXME/XXX in any file modified by the phase source, scripts or params.

### Known Caveats Confirmed (reported, not hidden)

| Caveat | Confirmed | Evidence |
|--------|-----------|----------|
| PLACEHOLDER-heavy v6 sets are research-only and refused at `pin_stream_epoch` | Yes, with the IN-01 limit | 16/29, 17/31, 22/36 (v6) and 15, 14 (-v4) PLACEHOLDER keys. The refusal exists and is tested, but nothing under `src/` calls `pin_stream_epoch`, and `run_paper_tick` loads any set. Enforcement belongs to the Phase 16 start-up. |
| TP1 inside the far half of the entry zone is not rejected | Yes | `_geometry_rejection` only requires TP1 strictly on the profit side of `entry_ref`. Left for a user decision (human item 1). |
| Signed-leg RR now affects all sets | Yes | planner.py:~618: `tp1_leg = tp1 - entry_ref` (LONG) / `entry_ref - tp1` (SHORT), RR gate uses the signed leg. |
| Legacy Family A plans are now STOP_TOO_TIGHT | Yes | Validator is universal (called for every set); D054 (c) records it; legacy tests migrated in 15-13. |
| 6 Info review findings (IN-01..06) open | Yes | `15-REVIEW-DISPOSITION.md`: WR-01 fixed (e0593a6), IN-01..06 `open`. None blocks a criterion. |
| TDD gate: 15-09 and 15-10 lack `test(15-NN)` RED commits | Yes (advisory) | `git log` shows `test(15-NN)` commits for plans 02-07 and 11-13 only. 15-09 describes its RED step inside a feature commit (a1aac86); 15-10 and 15-09 are parameter/fixture-generator plans. Process note only; behavior is covered by tests that pass now. |

### Human Verification Required

1. **TP1 far-half-of-zone rule.** Test: decide whether to reject a TP1 that is on the profit side of the entry reference but inside the far half of the entry zone. Expected: a recorded keep, or a one-line tightening in `_geometry_rejection` plus a test. Why human: money/safety rule, deliberately deferred by D054 (g).
2. **Basis of the three -v4 overrides.** Test: confirm DECISION/D054 for baseline-no-trade-v4 `minimum_rr` 100 and baseline-simple-trend-v4 `zone_tolerance_atr` 1.0, `minimum_rr` 0.5. Expected: accepted or re-labelled. Why human: parameter provenance; flagged in 15-08 SUMMARY; the "ratify" reply is only evidenced by SUMMARY text.
3. **Risk acceptance of PLACEHOLDER-grade sets and the unwired refusal gate (IN-01).** Expected: accepted for Phase 15, with the Phase 16 stream start-up required to call `pin_stream_epoch`. Why human: risk acceptance.

### Gaps Summary

No gaps. Every ROADMAP criterion is backed by code and by passing targeted tests. The status is `human_needed` only because three decisions were explicitly reserved for the user and the verifier must not resolve them. The research re-run itself, PostgreSQL tests and docker/bootstrap tests are outside what was run here.

---

_Verified: 2026-10-06_
_Verifier: Claude (gsd-verifier)_
