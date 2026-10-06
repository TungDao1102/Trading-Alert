---
phase: 15-strategy-geometry-correction
plan: 12
subsystem: backtest-fixtures
tags: [fixtures, geometry, regeneration, phase6, phase7, consumers, tracer]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "15-10 build_v6_payloads() and the '## v6 fixture facts' table; 15-11 planner tests; 15-08 ratified baseline-v6 / -v4 values"
provides:
  - "ten regenerated input.json files (nine Phase 6 cases, the Phase 7 parity input) written from build_v6_payloads(); generator reruns byte-identically"
  - "every consumer of those fixtures migrated in this plan: geometry check, engine-strategy, determinism, simulator hand literals and regression snapshots, paper parity, cost parity, experiment"
  - "tests/backtest_case_helpers.py phase6_case_identity and phase6_cost_model"
  - "re-pinned simulator regression digests and parity digest, with the Phase 15 regeneration note in REGRESSION_SNAPSHOTS.md"
affects: [15-13, 15-15]

actuals:
  tokens: 15439
  tasks: 3
  commits: 3
plan_head_before: 5ac7e0426767e92c841f9e4f04f2ab593cf74d98
plan_head_after: ec3a11560d61b48fdbcafe52cefd660e4151b80a

key-files:
  created: []
  modified:
    - scripts/gen_phase6_fixtures.py
    - tests/backtest_case_helpers.py
    - tests/test_phase6_fixture_geometry.py
    - tests/test_backtest_engine_strategy.py
    - tests/test_backtest_simulator.py
    - tests/test_paper_parity.py
    - tests/test_cost_parity.py
    - tests/test_backtest_experiment.py
    - tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md
    - tests/fixtures/phase7/parity_overlapping_history/expected.json
    - tests/fixtures/phase6/**/input.json (nine files)
    - tests/fixtures/phase7/parity_overlapping_history/input.json

key-decisions:
  - "No parameter, guard or registry value was chosen or tuned: every consumer literal was substituted from the 15-10 facts table or a quoted hand re-derivation; digests are engine pins, re-pinned only on cases proven by tests/test_phase6_fixture_scenarios.py"
  - "The generator's identity constants are the v6 ones (baseline-v6, v5.0.0, -v4 baselines) with no v5 constant left; funding mark_price is a parameter of the builder instead of a post-hoc rewrite"
  - "Tests that use baseline-v5 only for cost binding or assemble identity keep it (per-test table below)"

requirements-completed: [STRAT-02]

duration: ~2h
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 12: Phase 6 and Phase 7 fixtures regenerated, consumers migrated Summary

**The generator now writes exactly the `build_v6_payloads()` entries (legacy 1H builders, minute paths and v5 identity constants deleted), ten fixtures were regenerated on the corrected V-dip pivot geometry, and every consumer test moved in the same plan; the simulator digests all equal the 15-10 engine pins, the parity digest was re-pinned, and the suite shows 0 failures.**

## Accomplishments

- Task 1 (tracer, d007284): `scripts/gen_phase6_fixtures.py` shrank from 1050 to 786 lines. Every `write_*` function and `_write_baseline` calls `_write_payload(key)`, which writes `build_v6_payloads()[key]` under `FIXTURE_ROOT` (phase6) or `PHASE7_FIXTURE_ROOT` (phase7). The 4H context builders, `_bar_250`, `_minute_rows`, `COST_MODEL` (still the single top-level literal read by the CR-11 AST test) and the V-dip builders stay. The generator imports nothing from `src/` (`grep -cE "^[[:space:]]*(from|import) src"` prints 0). The module docstring numbers are the v6 planning-time illustrations. The committed-file geometry tests moved to `test_fixture_carries_phase15_identity` and `test_baseline_fixture_carries_phase15_identity` (baseline-v6 / v5.0.0; -v4 baselines at v5.0.0). `trigger_case` and the two other parameter-set loads in the engine-strategy tests read the identity from the fixture through `phase6_case_identity` and bind the fixture cost model. The engine finds the corrected signal end to end, tracer gate passed before Tasks 2 and 3 (`generator && pytest geometry scenarios engine_strategy determinism`: all green).
- Task 2 (308d6b5): simulator hand literals and regression snapshots on the regenerated fixtures; `REGRESSION_SNAPSHOTS.md` carries the "Phase 15 regeneration (D-19, D054)" note and digests.
- Task 3 (ec3a115): parity, cost parity and experiment on the regenerated fixtures, then the full suite.

## Regeneration inventory

### Regenerated fixtures (generator output, one command, rerun identical)

`tests/fixtures/phase6/{intrabar_both_touched, intrabar_both_touched_short, intrabar_missing_fallback, limit_touch_no_fill, limit_partial_fill, limit_expiry, invalidation_cancels_entry, baselines/no_trade, baselines/simple_trend}/input.json` and `tests/fixtures/phase7/parity_overlapping_history/input.json`. Re-pinned (hand edit): `tests/fixtures/phase7/parity_overlapping_history/expected.json`. Re-written: `tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md`.

Idempotence: the generator was run three times in the plan; `git status --porcelain tests/fixtures | md5sum` after run 1 and run 2 is `eb1e0f507945f856a373ae0e31d463c4` both times, and `sha256sum -c` of `intrabar_both_touched/input.json` is OK after the second run. After the final commit a further run leaves the tracked fixtures unchanged. Line endings: the generator writes explicit LF bytes; the working tree on this Windows checkout (`core.autocrlf=true`) shows LF files and git reports "LF will be replaced by CRLF" warnings on add, which is cosmetic; the content comparison test normalizes CRLF to LF on both sides (15-10 F12), so no spurious diff arises.

### Simulator regression digests (T-15-18, D054)

Scenario evidence is the `V6_SCENARIOS` tuple of `tests/test_phase6_fixture_scenarios.py` (that module passed, 10 parametrized cases, before and after every re-pin; `REGRESSION_SNAPSHOTS` tuples are identical to it, now asserted inside `test_phase6_case_matches_its_regression_snapshot`). Every new digest equals the 15-10 engine pin listed in that SUMMARY.

| Case | Scenario evidence (V6_SCENARIOS) | Old digest | New digest |
| --- | --- | --- | --- |
| intrabar_both_touched | ("ENTRY_FILLED", "SL", False, 0) | 8361c7ee192ec0b3d845b618118b81d702bc7325961efb710ef65357983d41bb | 04db4983b254951ec0eba4946787d415b0d9471ed259e6aec5ce88bb664433c3 |
| intrabar_both_touched_short | ("ENTRY_FILLED", "SL", False, 0) | 12ab88b86e5d676d53d486f71569cc32783752bb68117441811c61ef8dd2c6dc | 0d50102b4b8a567bc014f6b015ebb796e51611dd6dfd43d53c0874f95c40ee94 |
| intrabar_missing_fallback | ("ENTRY_FILLED", "SL", True, 0) | 8beeb6e4aee7ad546e259c4d8154fd4d4be1ed27b51f5dbea4492578adfb0dee | 7c7b3bf2dcf231eaf7c7fee43e9bbf6857195b80027eb80e6d1f1b66b5516a30 |
| limit_touch_no_fill | ("EXPIRED", None, False, 3) | 3d97433276538773911a9873f07760497f2c94dd6b7501201450af1488a73812 | 7458ac0e6f34cb50317e225bb004b55edeac97720193347c5ae06209c7f50c8c |
| limit_partial_fill | ("PARTIAL_FILL", "TP2", False, 0) | a51dfcddef59c29711e12a43bc1ae18269d8ecbab220ea8ace08d3c4b69969db | 3a7039dcf55851952dcc57918983a457d49710e12dd5534979477b340597f24a |
| limit_expiry | ("EXPIRED", None, False, 0) | f4a1733a2162d95430c8216792b672a6afda3eb77978becfdcca0bf1a3a3cf1c | fb60c4d61514ba557659de1ec713f5f5579b8fd60b1ec9b64a4d4a9e47120002 |
| invalidation_cancels_entry | ("INVALIDATION_CANCEL", None, False, 0) | 76856083699f1bac96d423336fc9c258282acd693ef9ccca4d0c876c587b9fcb | 74cea2d2bce3fee34ead91b2e568db41492ff391212eb82c9505f211ec22833e |
| baselines/no_trade | ("REJECT", None, False, 0) | none (not pinned before) | 79621110930faa9a355d087849a301b9b0dee105330397206d9213efb8c766c1 |
| baselines/simple_trend | ("ENTRY_FILLED", "SL", False, 0) | none (not pinned before) | 15f56a1a524d3c2361ac6cf077c82478c03446380bdaf0ed702cb5fb95689a41 |

The two baselines were added to `REGRESSION_SNAPSHOTS` so the table has one row per Phase 6 case and at least 9 regression-snapshot cases are collected (Task 2 `fails_when`).

### Parity digest (Phase 7)

| Field | Old | New |
| --- | --- | --- |
| `digest` (sha256 of the `(signal_id, reason_code)` projection) | d06c739aa73e0aec8033908086f25da78525ace4d422356a88fcfd4e2d4d3efe | 48a486fd7f3e3c40f217c21b5be526c53292a9a7c3f38c265d9766c6a256e347 |
| `strategy_version` | v4.0.0 | v5.0.0 |
| `parameter_set_hash` | 41ed39d4be10491abf614491aad7a9b0d35e1f52f5e894ff9d94fb2149ac3df9 | 2c4f1528b00f1b1e48c76040bbd6cc218a25eec21c521d8b68da86ee4811360f (the pin of baseline-v6 in tests/fixtures/phase4/parameters.json, equal to the simulator's) |
| `cost_model_hash` | 6d6c4e237ed0b56996ed344f4449b09a59c253a8d148af60e3aba1c8436f1caa | unchanged (the cost slice of baseline-v6 equals that of baseline-v5) |

Verified before pinning: paper loop and backtest both project to `[("607f38055093516e76144400176682398eba55182f65b129dfc8a8764dd851dd", "OK")]` (equal `(signal_id, reason_code)`), and `_assert_ledger_never_binds` holds (one OK verdict, no DAILY_STOP, no CONFLICT_WITH_OPEN_POSITION, no UNCERTAIN_ACCOUNT_STATE). The simulator payload digest for the parity input equals that of `intrabar_both_touched` (04db4983...), as 15-10 asserted.

### Substituted literals (T-15-21)

Fact references are rows of `15-10-SUMMARY.md` "## v6 fixture facts" (table "What changed against the baseline-v5 fixtures" = WC; per-case table = PC; money table = MT; geometry table = GT).

| Test (file) | Old literal | New literal | Fact |
| --- | --- | --- | --- |
| test_intrabar_both_touched_long_resolves_sl_first (simulator) | entry 121.50, exit 121.20 | 117.80, 116.50 | PC row 1, WC row 1 |
| test_intrabar_both_touched_short_resolves_sl_first | 128.50, 128.80 | 132.20, 133.50 | PC row 2, WC row 2 |
| test_intrabar_missing_mark_series... | exit 121.20; two records (`ENTRY_FILLED`, `PENDING_AT_DATA_END`), `trades[1]` assertion | exit 116.50; one record `["ENTRY_FILLED"]`; the `trades[1]` assertion is removed because the record no longer exists | PC row 3, WC row 4 (one record each) |
| test_limit_touch_no_fill... | planned_quantity 32.071 | 19.303 (3 touches unchanged) | PC row 4, WC row 4 |
| test_limit_partial_fill... | 32.071 / 16.035 / TP1 qty 8.017 / TP1 125.60 / TP2 129.70 | 19.303 / 9.651 / 4.825 / 123.20 / 128.60 | PC row 5, WC row 3 |
| test_invalidation_cancels_the_resting_entry... | two records (`INVALIDATION_CANCEL`, `PENDING_AT_DATA_END`) | one record `["INVALIDATION_CANCEL"]`, resolved_at 10:59:59 unchanged | PC row 7, WC row 4 |
| test_end_to_end_tp_ladder_costs_are_booked_per_leg | entry 121.50 x 16.035, TP1 125.60 x 8.017, TP2 129.70 x 8.018, gross 98.6173 | 117.80 x 9.651, 123.20 x 4.825, 128.60 x 4.826, gross 78.1758 | MT row 3 (gross_pnl 78.17580); hand one-liner below |
| test_guard_reason_flows_from_the_shared_helper... | `min_stop_distance_rate` 0.02 (fixture stop "about 1.1 percent") | 0.03 (fixture stop about 2.04 percent) | hand re-derivation below; not a facts-table row |
| test_per_leg_costs_for_a_stop_out... (cost parity) | 32.071 at 121.50, stop 121.20 | 19.303 at 117.80, stop 116.50 | PC row 1; MT row 1 (FILL -1.364336040, EXIT -26.892939600) |
| test_per_leg_costs_for_a_tp_ladder... (cost parity) | 16.035 / 8.017 / 8.018, 125.60 / 129.70, entry 121.50 | 9.651 / 4.825 / 4.826, 123.20 / 128.60, entry 117.80 | PC row 5; MT row 3 (FILL -0.682132680, TP1 25.698336000, EXIT 51.748425840) |
| test_cr03b_reproduced_trades... (experiment) | `baseline-simple-trend-v3` | `baseline-simple-trend-v4` | WC last row |
| test_verify_experiment_compares_the_v2_digest... (experiment) | 10:06 mark low "121.50" | "117.80" (above the stop trigger 115.60) | WC row 6 |
| test_trade_from_dict_round_trips_every_v2_field (experiment) | planned_quantity 20.598 | 11.566 | PC row 9 (simple_trend planned 11.566) |
| test_parity_expected_documentary_fields... (paper parity) | baseline-v5, v4.0.0 | baseline-v6, v5.0.0 | WC last row |

Hand re-derivations (Decimal one-liners, run in this plan):

```python
from decimal import Decimal as D
# TP ladder gross (simulator test): 4.825*(123.20-117.80) + 4.826*(128.60-117.80)
D('4.825')*(D('123.20')-D('117.80')) + D('4.826')*(D('128.60')-D('117.80'))   # 78.17580
# fees and slippage of the ladder: total notional 2351.95140
# 2351.95140*0.0005 = 1.175975700 (= entry_fee 0.568443900 + exit_fee 0.607531800), *0.0001 = 0.235195140 (MT row 3)
# stop rate at the adverse edge (guard-flow test)
(D('118.839620452456161478') - D('116.413839396725118030')) / D('118.839620452456161478')   # 0.02041222486655045293526520251
# per-leg bookings (cost parity), rates 0.0005 fee, 0.0001 entry slippage, 0.0003 stop slippage
# stop-out: FILL -1.364336040, EXIT -26.892939600
# ladder:   FILL -0.682132680, TP1 25.698336000, EXIT 51.748425840
```

The guard-flow threshold 0.03 keeps the test's intent (a configured minimum stop rate above the fixture's stop rate produces STOP_TOO_TIGHT); the old 0.02 would now sit below the 0.0204 stop rate and the case would plan normally. The asserted reason code is unchanged.

### Identity decision per migrated test

| Test or group | Identity after | Why |
| --- | --- | --- |
| engine-strategy `trigger_case`, `trigger_setup_result`, `test_a_no_trade_result_past_the_regime_gate_names_the_regime` | fixture identity (baseline-v6 / v5.0.0) through `phase6_case_identity`, cost model through `phase6_cost_model` | run the regenerated trigger case; Family A plan needed |
| engine-strategy window tests, scripted-plan tests (`make_case` defaults) | baseline-v5 / v4.0.0 kept | scripted or synthetic bars, identity only binds the cost model |
| determinism (through `trigger_case`) | follows `trigger_case`; no literal changed | no assertion depended on the old geometry |
| simulator tests that run a case | fixture identity (no spelled literal) | read from the input.json |
| `test_run_refuses_legacy_registry_set_without_guard_rates` (baseline-v4 / v3.0.0 over the fixture) and the registry guard-rate test near line 715 (baseline-v5 / v4) | unchanged | read registry sets, not fixture geometry |
| `test_cost_parity.py` per-leg tests | fixture identity (reads the case) | run the regenerated cases; `COST_MODEL_DICT` (8-key, cost-only) kept |
| `test_paper_parity.py` | baseline-v6 / v5.0.0 | parity input is a regenerated case |
| experiment: `_simple_trend_record`, `_load_bound_input` users | fixture identity (v4 baseline) | bind the case's own identity |
| experiment: `assemble_kwargs`-based identity tests (lines ~71, ~394, ~825, ~916), breakout-retest cost slice (~566), cr11 baseline-v3 list (~636) | baseline-v5 / v3 kept | identity assembly and cost binding only, no fixture geometry |

## Verification

- Counts (collected items before and after; function-definition counts unchanged): engine-strategy 11 / 11, determinism 16 / 16, simulator 61 / 63 (the two added baseline parameters; `def test_` count 40 / 40), paper parity 5 / 5, cost parity 9 / 9, experiment 86 / 86.
- Skip and xfail markers: `grep -rhoE "pytest\.mark\.(skip|xfail)|pytest\.skip\(" tests --include=*.py | wc -l` is 15 before Task 1 and 15 after Task 3.
- Plan verify (generator, then `pytest geometry scenarios simulator experiment determinism engine_strategy paper_parity cost_parity paper_closed_candle paper_feed_gates analytics_cli analytics_report`): `449 passed in 148.99s`, exit 0.
- `ruff check src tests scripts`: all checks passed. `ruff format --check src tests scripts`: 388 files already formatted. `mypy src`: no issues in 149 source files.
- Full suite result line: the pyproject `addopts = "-q"` suppresses the summary line when `-q` is added, and a single run exceeds the 10-minute foreground limit, so the suite was run file by file (each with a foreground timeout) and the per-file lines summed: **4292 passed, 0 failed, 0 errors, 430 skipped** over 193 test files. The 430 skips: 406 in the PostgreSQL-dependent `*_pg.py` files (they skip without `TEST_DATABASE_URL`; left to CI) and 24 in six other files that skip on missing PostgreSQL or shell tooling (`test_analytics_files`, `test_analytics_store`, `test_controller_rehydrate`, `test_deploy_scripts`, `test_persistence_engine_timeouts`, `test_pg_fixture_guard`), all unchanged by this plan.
- Not run (known, per the dispatch instructions): `tests/test_deploy_backup_scripts.py`, `tests/test_docker*.py` (four files) and `tests/test_bootstrap.py` (Git Bash driven, did not finish within 200 s, touches no fixture or backtest code).
- Pre-existing crash, unrelated: `tests/test_case_input_builder.py` aborts with a Windows access violation after 5 to 18 tests. It aborts identically on the untouched baseline commit 5ac7e04 (checked in a throwaway `git worktree`, removed afterwards), and it reads no file this plan changed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Missing helper] `phase6_cost_model(fixture)` added to tests/backtest_case_helpers.py**
- **Found during:** Task 1
- **Issue:** the plan says the fixture's cost_model is passed through `cost_overrides`, but `phase6_case_identity` returns only the identity triple.
- **Fix:** one more tiny helper reading `cost_model` from the fixture; no assertion changed.
- **Commit:** d007284

**2. [Rule 2 - Coverage] Baselines pinned and scenario equality asserted in the snapshot test**
- **Found during:** Task 2
- **Issue:** `REGRESSION_SNAPSHOTS` held only the seven candidate cases, while the plan requires one row per Phase 6 case and at least 9 collected regression-snapshot cases; "scenario tuples equal V6_SCENARIOS" was only true by inspection.
- **Fix:** added the two baseline entries and `assert scenario == V6_SCENARIOS[name]` inside the existing test (imports `V6_SCENARIOS`). The function count is unchanged, collected items 61 to 63.
- **Commit:** 308d6b5

**3. [Rule 1 - Consequence of the fixtures] Guard-flow threshold and two record counts**
- The 0.02 threshold in `test_guard_reason_flows...` and the follow-up record in the fallback and invalidation tests changed as described in the literal table; both map to the 15-10 facts or to a quoted re-derivation, and no assertion was weakened (the `trades[1]` assertion tested a record that the corrected geometry cannot produce, per 15-10 WC row 4).
- **Commit:** 308d6b5

### Generator interface change

`_build_input` now takes `mark_price` and `parameter_set_id` as required arguments and writes `strategy_version` v5.0.0 directly (the v6 builder no longer patches the payload afterwards). `build_v6_payloads()` output is byte-identical to 15-10 (all nine digests equal the 15-10 pins).

## Known Stubs

None.

## Threat Flags

None. T-15-18 mitigated: scenario tuples equal V6_SCENARIOS (asserted), digests re-pinned only while the scenario module passed, per-case old/new table above. T-15-21 mitigated: literals only from the 15-10 facts table or quoted re-derivations, function counts unchanged, no skip or xfail added (15 and 15), per-test identity table, suite green. T-15-SC accepted (no installs).

## Self-Check: PASSED

- FOUND: scripts/gen_phase6_fixtures.py (def `_write_payload`, `build_v6_payloads`), tests/backtest_case_helpers.py (def phase6_case_identity), tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md ("Phase 15 regeneration"), tests/test_paper_parity.py ("baseline-v6"), tests/test_phase6_fixture_geometry.py ("baseline-v6")
- FOUND: commits d007284, 308d6b5, ec3a115 on develop
