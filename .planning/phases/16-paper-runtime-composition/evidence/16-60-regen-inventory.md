# 16-60: regeneration inventory for SIMULATOR_SEMANTICS_VERSION 2.1.0 to 2.2.0

Plan 16-60, Task 2 (B3-CR-01, research warm-up). Authorized by 16-DEC-V250 item 1 (the user, 2026-10-16: "a deliberate regeneration with an inventory like D053 and quick 261014-nnl"); no further approval is asked. This file is the input to D074 (task 4). Pattern: `evidence/16-S-B-interval-regen-inventory.md` (2.0.0 to 2.1.0, D070).

Run on 2026-10-17 in C:/Users/daotu/OneDrive/Documents/Trading-Alert, branch develop, base commit f51a5e18aa170cf40ab58b085f3643643802736b. The working tree held the Task 1 changes (the `RESEARCH_WARMUP_SPAN` constant, `warmup_start` and the cold-start line in `src/research/run.py`, the `data_window_start_utc` keyword of `CaseInputData.to_case_input`, `tests/test_research_warmup.py`). The bump (`SIMULATOR_SEMANTICS_VERSION = "2.2.0"`) was applied in the working tree; nothing of src or tests is committed by this task. No ExperimentRecord was written outside pytest tmp_path, no Holdout read, no push, no network. The 240 records of research run 1 were not read, regenerated or edited.

## 1. Verdict on the stop condition

No semantics leak. All 106 failing tests are one of the classes VERSION_PIN, DERIVED_DIGEST or STORED_RECORD (no WARMUP_BEHAVIOUR failure occurred: the existing research runner, checkpoint, terminal-settlement and feasibility tests use synthetic stores whose Development window is as long as every fold's available history, so the clamp at `development_start_utc` leaves their expectations unchanged). The leak check (section 3) over 28 cases shows that the only fields that move are `run_summary.simulator_semantics_version` and `trades[].trade_id`: **only version string and trade_id differ**.

The engine, the case parser, the simulator and the risk path are not changed by this plan. The only behaviour change is in `src/research/run.py` (what the runner puts into a case), which no engine fixture exercises.

## 2. Counts per class (suite: `.venv/Scripts/python -m pytest -m "not docker" -q -rf -p no:cacheprovider`, bump applied, before any regeneration)

Total failing tests: 106. Baseline: the full gate of plan 16-62 at the base commit was green (evidence/16-62-gate.txt); the Task 1 working-tree changes were run without the bump against the research, case-input and checkpoint test files (all pass).

| Class | Failing tests | Distinct artifacts to change |
| --- | --- | --- |
| VERSION_PIN | 9 | 6 literal lines in 6 test files (tests that assert the constant or a record field derived from it) + the version-regression witness `tests/test_semantics_version_regression.py` (3 tests; rewritten to compare 2.2.0 with each earlier version) |
| DERIVED_DIGEST | 9 | 9 digests in `tests/test_backtest_simulator.py` `REGRESSION_SNAPSHOTS` + the same 9 digests in `tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md` (documentary copy) |
| STORED_RECORD | 88 | 1 file: `tests/fixtures/phase10/loaders/evidence_sample.json` (1 literal `simulator_semantics_version`; plus the pin at `tests/test_analytics_files.py:507`, counted here because that test fails on the load first) |
| WARMUP_BEHAVIOUR | 0 | none |
| Other (leak) | 0 | none |

STORED_RECORD failing tests by file: tests/test_analytics_cli.py 44, tests/test_analytics_files.py 24, tests/test_paper_shadow_evidence_export.py 10, tests/test_killgate_guard.py 6, tests/test_soak_evidence_export.py 2, tests/test_paper_test_signal_rehearsal.py 1, tests/test_terminal_settlement_consumers.py 1. Each fails at the load of the sample with `IncompleteExperimentRecord` (the refusal of a record whose `simulator_semantics_version` is not current, `src/backtest/experiment.py` `ExperimentRecord.__post_init__`), or on a CLI assertion that carries that refusal text.

## 3. Captured outputs and the leak check

Cases (no `terminal_settlements` key in either; the script asserts it), built from the same committed helpers as design test 10: `scripted_tracer` = `tests.test_backtest_engine.tracer_case()`, `strategy_trigger_no_declaration` = `tests.test_backtest_engine_strategy.trigger_case()[0]`. Output = `src.backtest.engine.simulate(case, risk_fn=src.risk.gating.evaluate_risk)`; serialization for the hash: `json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()`. The captured bytes are kept outside the repo in the scratchpad; two separate runs of the 2.1.0 capture gave identical hashes.

| Case | Bytes | sha256 of the 2.1.0 output (captured before the bump) | sha256 of the 2.2.0 output |
| --- | --- | --- | --- |
| scripted_tracer | 2148 | 8b9b0d596afb78d863e526dfd394e0f306c754871e27c3dff0272a4f6c76e320 | e97d716138bb97e870aa8c28f1abf78db759a8c3266298c9306fc5e9e774c817 |
| strategy_trigger_no_declaration | 2269 | 6130a3dd9102a16928a1692acde7c164f5a0b3b1e147a53f939f99801c2c1e87 | 95a35ac1bc44e883bc7ad62841774bdbabeb0c23881854d23d8cb70aaf59f5be |

The 2.0.0 hashes of the earlier inventory (be6cd8a6... and 4635c92d...) are still reproduced by the current engine with the constant patched to 2.0.0; `tests/test_semantics_version_regression.py` now asserts both earlier versions against the current one.

Leak check: every committed `backtest-case/2` input under `tests/fixtures/phase14` (16 hand-derived goldens), `tests/fixtures/phase6` (7 cases + 2 baselines) and `tests/fixtures/phase7` (`parity_overlapping_history`), 26 cases, plus the two captured cases, 28 in all; each run under 2.1.0 and under 2.2.0 with `SIMULATOR_SEMANTICS_VERSION` patched in every module that binds it by name (`src.backtest.semantics`, `records`, `engine`, `experiment`), and a deep diff of the whole output.

Result of the leak check: `cases=28 version_diffs=28 trade_id_diffs=32 other=[]`. That is 28 differences of `/run_summary/simulator_semantics_version`, 32 differences of `/trades[]/trade_id` (one per trade record), and 0 other differences: only version string and trade_id differ.

## 4. Failing items, by class, each with its regeneration path

### 4.1 VERSION_PIN (9 failing tests, 6 literal lines + 1 rewritten witness)

Each asserts the literal `"2.1.0"` for the constant or a record field derived from it. The literal is the constant, so the re-pin is a one-token edit to `"2.2.0"`; no hash or id is involved.

| # | File:line | Failing test | Change |
| --- | --- | --- | --- |
| 1 | tests/test_backtest_engine.py:169 | test_output_carries_summary_hashes_and_symbols | `== "2.1.0"` to `== "2.2.0"` |
| 2 | tests/test_backtest_experiment.py:803 | test_assemble_binds_the_run_summary_into_typed_fields | same |
| 3 | tests/test_backtest_experiment.py:1202 | test_the_record_serializes_without_the_research_gate_keys | same |
| 4 | tests/test_backtest_lifecycle.py:154 | test_phase_constants_pin_the_user_resolved_tp1_policy | same |
| 5 | tests/test_backtest_run_summary.py:167 | test_run_facts_echo_the_protocol_constants_and_the_inputs | same |
| 6 | tests/test_backtest_terminal_settlement.py:200 | test_vocabulary_constants_are_pinned | same |
| (7) | tests/test_analytics_files.py:507 | test_the_v2_sample_carries_every_typed_experiment_field_and_validated_trades | same; counted under STORED_RECORD because the test fails on the load first |
| W | tests/test_semantics_version_regression.py (3 failing tests: test_semantics_version_is_2_1_0, and the two parametrized no-declaration tests) | the design test 10 witness | rewritten: `NEW_VERSION = "2.2.0"`; the no-declaration test is parametrized over the earlier versions 2.0.0 and 2.1.0 with the recorded hashes of section 3; it proves 2.2.0 differs from each only in the version string and trade_id |

### 4.2 DERIVED_DIGEST (9 failing tests)

Test: `tests/test_backtest_simulator.py::test_phase6_case_matches_its_regression_snapshot[<name>]`. Each pins `sha256_hex` of the whole run output of one phase 6 fixture; the output holds `trade_id` and `run_summary.simulator_semantics_version`, so each digest moves. The scenario tuples (entry kind, exit kind, fallback flag, touch count) pass unchanged.

Cases: intrabar_both_touched, intrabar_both_touched_short, intrabar_missing_fallback, limit_touch_no_fill, limit_partial_fill, limit_expiry, invalidation_cancels_entry, baselines/no_trade, baselines/simple_trend.

Places that hold each digest: `tests/test_backtest_simulator.py` `REGRESSION_SNAPSHOTS` (asserted) and `tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md` (documentary, asserted by no test). `docs/DECISIONS.md` and `.planning` summaries quote the old digests: HISTORY, unchanged.

Regeneration path (the test's own build path, as its comment says: re-pin by printing `_digest(run(case))`): a throwaway script outside the repo reads each old digest from `REGRESSION_SNAPSHOTS`, computes `_digest(run(_case(name)))`, and substitutes old by new in the two files by exact string match, asserting each old digest occurs exactly once in each file. No digest is typed. 9 substitutions in each of the 2 files (old to new, first 12 hex digits):

- baselines/no_trade 77c6ae78953b to 9196d272105b
- baselines/simple_trend c2f666cf9ec8 to 8eafebff3009
- intrabar_both_touched e8c9d088237b to d680ad5c27b7
- intrabar_both_touched_short e8c0b476d80e to 9d3b70d6b873
- intrabar_missing_fallback 82f5760925f2 to f15cf66d1a9d
- invalidation_cancels_entry ff399025c794 to 1bd01918f0ce
- limit_expiry 3575aa670d66 to 8659ac4b3eb9
- limit_partial_fill 0249a1fde923 to b9e0894ee38f
- limit_touch_no_fill 96d7fce9fc69 to 895714437aee

### 4.3 STORED_RECORD (88 failing tests, one file)

Artifact: `tests/fixtures/phase10/loaders/evidence_sample.json` (`analytics-evidence/2`). `backtest[0].experiment.simulator_semantics_version` was `"2.1.0"`; the current `ExperimentRecord` refuses it. The trades in the sample are hand-built (`trade_id` T-1, T-2), not engine output, so no trade id in it moves; its `experiment_id` is unread by any code and stays as the earlier inventory (4.3 there, option S1) decided.

Regeneration path (the earlier inventory's S1 command, version read from the code constant, not typed; the rewrite uses `json.dumps(doc, sort_keys=True, indent=2) + "\n"`, which is byte-stable on this file):

```
.venv/Scripts/python -I -c "import json,sys; sys.path.insert(0,'.'); from pathlib import Path; from src.backtest.semantics import SIMULATOR_SEMANTICS_VERSION as V; p=Path(sys.argv[1]); d=json.loads(p.read_text(encoding='utf-8')); d['backtest'][0]['experiment']['simulator_semantics_version']=V; p.write_bytes((json.dumps(d,sort_keys=True,indent=2)+chr(10)).encode())" tests/fixtures/phase10/loaders/evidence_sample.json
```

Result: a one-line diff (`"2.1.0"` to `"2.2.0"`). The `tests/test_analytics_files.py:507` pin is in the VERSION_PIN table.

## 5. Code comments that state the current version

`src/backtest/semantics.py` carries the version comment: it now records 2.2.0 (plan 16-60, D073) next to the earlier historical wording (2.0.0 and 2.1.0 mentions there are already historical). Other mentions in `src/` state no number.

## 6. Docs mentions of 2.1.0: HISTORY (unchanged by Task 2)

Docs lines that name simulator semantics 2.1.0 (protocol migration paragraphs, the D070 and D071 rows, the DOC_STATUS log, BACKTEST_SPEC history lines) are history and stay. Task 4 adds the in-force statements (protocol v2.5.0, D073, D074, BACKTEST_SPEC, DOC_STATUS) in the landing commit.

## 7. Passing but version-sensitive

1. `tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md` documentary digests: regenerated with the test file (4.2) because no test notices a stale copy.
2. `tests/test_analytics_slices.py` and `tests/fixtures/phase10/low_n_slices/*`, `tests/fixtures/phase6/report_slices/input.json` carry "2.1.0" as a slice-label string, not as the simulator constant: unchanged and passing.
3. `tests/test_kill_gate_docs.py` names "v2.1.0" as a protocol version in a decision-row witness: protocol history, unchanged.
4. `tests/test_backtest_goldens.py` (16 hand-derived goldens) never compares `trade_id` or the version and passes unchanged; the Phase 7 parity expected file passes unchanged.

## 8. Result after regeneration

Regeneration applied in the working tree (6 pins, 9 + 9 digests, 1 fixture literal, the rewritten witness). Full suite on the working tree, as its own step: see the line below.

Result: `.venv/Scripts/python -m pytest -m "not docker" -q -rf -rs -p no:cacheprovider` on the working tree (TEST_DATABASE_URL set, so the database tests ran): exit 0, 10129 passed, 6 skipped (3 skip reasons: symlinks unavailable on Windows, NTFS cannot represent POSIX modes, file modes do not exist on Windows), 0 failed. `ruff check`, `ruff format --check` and `mypy src` are clean on the files of Task 1 (the full gate is Task 4). The leak-check script, the capture script and the regeneration script are throwaway scripts in the session scratchpad; none is committed.
