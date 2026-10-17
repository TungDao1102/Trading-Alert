# 16-63: regeneration inventory for SIMULATOR_SEMANTICS_VERSION 2.2.0 to 2.3.0

Plan 16-63, Task 2 (the planner rule that a plan whose TP2 is not a positive price is NO_TRADE RR_TOO_LOW). Authorized by the owner's decision of 2026-10-17 (words verbatim: "chọn A và đọc chặt, làm đi"): Option A and the strict reading of the header of `src/backtest/semantics.py` (the annotate-only exception covers only a change where "no price, time, cost, count or event moved"; a new NO_TRADE outcome moves counts and events). No further approval is asked for this inventory. This file is the input to D076 (Task 4). Pattern: `evidence/16-60-regen-inventory.md` (2.1.0 to 2.2.0, D074).

Run on 2026-10-17 in C:/Users/daotu/OneDrive/Documents/Trading-Alert, branch develop, base commit 3550d9c14565c517c88d5d1f972b05c5a070716d. The working tree held the Task 1 changes (the guard in `src/core/planner.py` and `tests/test_planner_tp2_positive.py`). The bump (`SIMULATOR_SEMANTICS_VERSION = "2.3.0"`) was applied in the working tree; nothing of src or tests is committed by this task (only this file). No ExperimentRecord was written outside pytest tmp_path, no Holdout read, no push, no network. The 240 records of research run 1 were not read, regenerated or edited.

## 1. Verdict on the stop condition

No semantics leak. All 108 failing tests of the first full run are one of the classes VERSION_PIN, DERIVED_DIGEST or STORED_RECORD; there is no STALE_AUTHORIZATION failure and no GUARD_BEHAVIOUR failure (no existing expectation moved because of the guard). The leak check (section 3) over 28 cases shows that the only fields that move are `run_summary.simulator_semantics_version` and `trades[].trade_id`: **only version string and trade_id differ**. The guard-reach check (section 3) counts 0 plans with a TP2 at or below zero in the committed fixtures and 0 differences against the HEAD planner on the same 28 cases.

## 2. Counts per class (suite: `.venv/Scripts/python -m pytest -m "not docker" -q -rf -p no:cacheprovider`, TEST_DATABASE_URL set, bump applied, before any regeneration)

Total failing tests: 108 (the first full run on the working tree). Baseline: the full gate with PostgreSQL of plan 16-61 at dce3195 was green (10229 passed, 6 skipped).

| Class | Failing tests | Distinct artifacts to change |
| --- | --- | --- |
| VERSION_PIN | 11 | 6 literal lines in 6 test files (tests that assert the constant or a record field derived from it) + the version-regression witness `tests/test_semantics_version_regression.py` (5 failing tests: `test_semantics_version_is_2_2_0` and the 4 parametrized no-declaration cases; rewritten to compare 2.3.0 with 2.0.0, 2.1.0 and 2.2.0) |
| DERIVED_DIGEST | 9 | 9 digests in `tests/test_backtest_simulator.py` `REGRESSION_SNAPSHOTS` + the same 9 digests in `tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md` (documentary copy) |
| STORED_RECORD | 88 | 1 file: `tests/fixtures/phase10/loaders/evidence_sample.json` (1 literal `simulator_semantics_version`; plus the pin at `tests/test_analytics_files.py:507`, counted here because that test fails on the load first) |
| STALE_AUTHORIZATION | 0 | none (no test expects a committed 2.2.0 authorization file to be accepted; the runner refusal `simulator_semantics_version_mismatch` is exercised in Task 5 on the real inputs) |
| GUARD_BEHAVIOUR | 0 | none |
| Other (leak) | 0 | none |

STORED_RECORD failing tests by file: tests/test_analytics_cli.py 44, tests/test_analytics_files.py 24, tests/test_paper_shadow_evidence_export.py 10, tests/test_killgate_guard.py 6, tests/test_soak_evidence_export.py 2, tests/test_paper_test_signal_rehearsal.py 1, tests/test_terminal_settlement_consumers.py 1 (sum 88). Each fails at the load of the sample with `IncompleteExperimentRecord` (the refusal of a record whose `simulator_semantics_version` is not current, `ExperimentRecord.__post_init__`), or on a CLI assertion that carries that refusal text. This is the same set as in the 2.1.0 to 2.2.0 inventory.

## 3. Captured outputs, the leak check and the guard-reach check

Cases (no `terminal_settlements` key in either; the script asserts it), built from the same committed helpers as design test 10: `scripted_tracer` = `tests.test_backtest_engine.tracer_case()`, `strategy_trigger_no_declaration` = `tests.test_backtest_engine_strategy.trigger_case()[0]`. Output = `src.backtest.engine.simulate(case, risk_fn=src.risk.gating.evaluate_risk)`; serialization for the hash: `json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()`.

Baseline equality (Task 2 step 1, with the guard in the working tree and the constant still 2.2.0): both outputs equal the recorded 2.2.0 values of the 16-60 inventory, so the guard moved nothing:

| Case | Bytes | sha256 of the 2.2.0 output (guard in tree, before the bump) | recorded 2.2.0 (16-60 inventory) | sha256 of the 2.3.0 output |
| --- | --- | --- | --- | --- |
| scripted_tracer | 2148 | e97d716138bb97e870aa8c28f1abf78db759a8c3266298c9306fc5e9e774c817 | e97d716138bb97e870aa8c28f1abf78db759a8c3266298c9306fc5e9e774c817 (equal) | bc9732fc66715fc423028f01ade187bd586d6193e30684ea710841818781fb23 |
| strategy_trigger_no_declaration | 2269 | 95a35ac1bc44e883bc7ad62841774bdbabeb0c23881854d23d8cb70aaf59f5be | 95a35ac1bc44e883bc7ad62841774bdbabeb0c23881854d23d8cb70aaf59f5be (equal) | 91253a186bceda77ef2c7c75d9bba0c8406d69742506ea5cf24bd2359cf5b479 |

Leak check: every committed `backtest-case/2` input under `tests/fixtures/phase14` (16 hand-derived goldens), `tests/fixtures/phase6` (7 cases + 2 baselines) and `tests/fixtures/phase7` (`parity_overlapping_history`), 26 cases, plus the two captured cases, 28 in all; each run through `src.backtest.simulator.run` (the captured two through `simulate`) under 2.2.0 and under 2.3.0 with `SIMULATOR_SEMANTICS_VERSION` patched in every module that binds it by name (`src.backtest.semantics`, `records`, `engine`, `experiment`), and a deep diff of the whole output (list indexes folded to `[]`).

Result of the leak check: `cases=28 (captured 2 + committed 26) version_diffs=28 trade_id_diffs=32 other=[]`. That is 28 differences of `/run_summary/simulator_semantics_version`, 32 differences of `/trades[]/trade_id` (one per trade record), and 0 other differences: only version string and trade_id differ. (Identical counts to the 2.1.0 to 2.2.0 check.)

Guard-reach check:

1. Static scan of every JSON file under `tests/fixtures` for a `tp2` key (plan inputs, scripted plans, expected plans, phase 4 and phase 14 and phase 15 sidecars) and for `take_profit_json` strings: 53 TP2 values in 32 JSON files; TP2 at or below zero: **0**.
2. Engine spy over the same 28 cases: 10 plans built by the planner, plans with TP2 at or below zero: **0**; RR_TOO_LOW reject records: 1 (a real RR below the floor, present before the guard as well, see 3).
3. The 28 cases run once with the current planner and once with the HEAD (2.2.0) planner module loaded from `git show HEAD:src/core/planner.py` and substituted for `engine.build_trade_plan`: `cases=28 identical_with_HEAD_planner=28 different=[]`. The guard is not reached by any committed case.

So the guard-reach count is 0 and a committed plan or case holding a TP2 at or below zero does not exist (a case holding one would have raised under 2.2.0).

## 4. Failing items, by class, each with its regeneration path

### 4.1 VERSION_PIN (11 failing tests, 6 literal lines + 1 rewritten witness)

Each asserts the literal `"2.2.0"` for the constant or a record field derived from it. The literal is the constant, so the re-pin is a one-token edit to `"2.3.0"`; no hash or id is involved. Command per row: edit that token on that line (done by a script that asserts the line holds exactly one `"2.2.0"`).

| # | File:line | Failing test | Change |
| --- | --- | --- | --- |
| 1 | tests/test_backtest_engine.py:169 | test_output_carries_summary_hashes_and_symbols | `== "2.2.0"` to `== "2.3.0"` |
| 2 | tests/test_backtest_experiment.py:803 | test_assemble_binds_the_run_summary_into_typed_fields | same |
| 3 | tests/test_backtest_experiment.py:1202 | test_the_record_serializes_without_the_research_gate_keys | same |
| 4 | tests/test_backtest_lifecycle.py:154 | test_phase_constants_pin_the_user_resolved_tp1_policy | same |
| 5 | tests/test_backtest_run_summary.py:167 | test_run_facts_echo_the_protocol_constants_and_the_inputs | same |
| 6 | tests/test_backtest_terminal_settlement.py:200 | test_vocabulary_constants_are_pinned | same |
| (7) | tests/test_analytics_files.py:507 | test_the_v2_sample_carries_every_typed_experiment_field_and_validated_trades | same; counted under STORED_RECORD because the test fails on the load first |
| W | tests/test_semantics_version_regression.py (5 failing tests) | the design test 10 witness | rewritten: `NEW_VERSION = "2.3.0"`; the no-declaration test is parametrized over 2.0.0, 2.1.0 and 2.2.0 with their recorded hashes (2.2.0: the two values of the table above); it proves 2.3.0 differs from each only in the version string and trade_id |

### 4.2 DERIVED_DIGEST (9 failing tests)

Test: `tests/test_backtest_simulator.py::test_phase6_case_matches_its_regression_snapshot[<name>]`. Each pins `sha256_hex` of the whole run output of one phase 6 fixture; the output holds `trade_id` and `run_summary.simulator_semantics_version`, so each digest moves. The scenario tuples (entry kind, exit kind, fallback flag, touch count) pass unchanged.

Places that hold each digest: `tests/test_backtest_simulator.py` `REGRESSION_SNAPSHOTS` (HEAD lines 320 to 352, asserted) and `tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md` (HEAD lines 18 to 26, documentary, asserted by no test). `docs/DECISIONS.md` and `.planning` summaries quote older digests: HISTORY, unchanged.

Regeneration path (the test's own build path): a throwaway script outside the repo reads each old digest from `REGRESSION_SNAPSHOTS`, computes `_digest(run(_case(name)))`, and substitutes old by new in the two files by exact byte match, asserting each old digest occurs exactly once in each file. No digest is typed. 9 substitutions in each of the 2 files (old to new, first 12 hex digits):

- baselines/no_trade 9196d272105b to 6989a2407e9f
- baselines/simple_trend 8eafebff3009 to 07473f67f123
- intrabar_both_touched d680ad5c27b7 to 7a2d1cefc323
- intrabar_both_touched_short 9d3b70d6b873 to db4d29381258
- intrabar_missing_fallback f15cf66d1a9d to 3faad7cf6914
- invalidation_cancels_entry 1bd01918f0ce to 41cd67566f3b
- limit_expiry 8659ac4b3eb9 to 682dccafffe9
- limit_partial_fill b9e0894ee38f to 6d50561ace4a
- limit_touch_no_fill 895714437aee to 3199a5d9a54b

### 4.3 STORED_RECORD (88 failing tests, one file)

Artifact: `tests/fixtures/phase10/loaders/evidence_sample.json` (`analytics-evidence/2`), line 73. `backtest[0].experiment.simulator_semantics_version` was `"2.2.0"`; the current `ExperimentRecord` refuses it. The trades in the sample are hand-built, not engine output, so no trade id in it moves; its `experiment_id` is unread by any code and stays as in the earlier inventories.

Regeneration path (the 16-60 inventory 4.3 command, version read from the code constant, not typed; byte-stable rewrite `json.dumps(doc, sort_keys=True, indent=2) + "\n"`):

```
.venv/Scripts/python -I -c "import json,sys; sys.path.insert(0,'.'); from pathlib import Path; from src.backtest.semantics import SIMULATOR_SEMANTICS_VERSION as V; p=Path(sys.argv[1]); d=json.loads(p.read_text(encoding='utf-8')); d['backtest'][0]['experiment']['simulator_semantics_version']=V; p.write_bytes((json.dumps(d,sort_keys=True,indent=2)+chr(10)).encode())" tests/fixtures/phase10/loaders/evidence_sample.json
```

Result: a one-line diff (`"2.2.0"` to `"2.3.0"`). The `tests/test_analytics_files.py:507` pin is in the VERSION_PIN table.

### 4.4 STALE_AUTHORIZATION (0) and GUARD_BEHAVIOUR (0)

No failing test belongs to either class. The three 2.2.0 authorization files and `16-DEC-RERUN-AUTH.md` are untouched. The runner refusal of the 2.2.0 files under 2.3.0 is recorded on the real inputs in Task 5.

## 5. Code comments that state the current version

`src/backtest/semantics.py` carries the version comment: it now records 2.3.0 (plan 16-63, D075) next to the 2.2.0 sentence, which stays. Other mentions in `src/` state no number.

## 6. Docs mentions of 2.2.0: HISTORY or in-force, handled by Task 4

Docs lines that name simulator semantics 2.2.0 or protocol v2.5.0 (protocol migration paragraphs, D073, D074, the DOC_STATUS log, BACKTEST_SPEC history lines) are history and stay. Task 4 adds the in-force statements (protocol v2.6.0, D075, D076, BACKTEST_SPEC pointers, DOC_STATUS) in the landing commit. `tests/test_research_protocol_v250.py:158` asserts `simulator_semantics_version: "2.2.0"` inside a D073 row: protocol history, passes, unchanged here.

## 7. Result after regeneration

Regeneration applied in the working tree (6 pins, 9 + 9 digests, 1 fixture literal, the rewritten witness). Full suite on the working tree, as its own step, `.venv/Scripts/python -m pytest -m "not docker" -q -rf -rs -p no:cacheprovider` with TEST_DATABASE_URL set (container `trading-postgres-1` healthy, connection checked before the run): exit 0, 10245 passed, 6 skipped (platform skips: symlinks unavailable on Windows, NTFS cannot represent POSIX modes, file modes do not exist on Windows x4), 0 failed, 0 errors. 10245 = 10229 of the 16-61 gate + 14 tests of `tests/test_planner_tp2_positive.py` + 2 added parametrized witness cases. `ruff check`, `ruff format --check` (627 files) and `mypy src` (202 files) are clean. The capture, leak-check, guard-reach, HEAD-planner comparison and regeneration scripts are throwaway scripts in the session scratchpad; none is committed.

Guard-failure path not used: nothing is on a side branch; HEAD is still 2.2.0 and the working tree holds Tasks 1 and 2.
