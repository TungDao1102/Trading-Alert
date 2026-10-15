# 16 S-B-interval: regeneration inventory for SIMULATOR_SEMANTICS_VERSION 2.0.0 to 2.1.0

Quick 261014-nnl, plan 07, Task 1. Status: NOT APPROVED. This file is an inventory only. It is the input to the user's decision in Task 2 and to D071 in plan 09. Nothing in it is an approval, and nothing was regenerated.

Run on 2026-10-15 in C:/Users/admin/Music/Trading, branch develop, base HEAD e0ec481. The bump was applied to `src/backtest/semantics.py` in the working tree only (one line: `SIMULATOR_SEMANTICS_VERSION = "2.1.0"`), used to run the suite twice (once whole, once on the failing files with `--tb=line` to read each failure's cause), and reverted with `git checkout -- src/backtest/semantics.py`. After the revert `git diff --quiet HEAD -- src tests params scripts` exits 0. No fixture, golden, params file, `src/paper` file or `holdout_consumed.json` was touched. No ExperimentRecord was written outside pytest tmp_path (the suite's own tmp_path use). No Holdout read, no O-03, no manifest freeze, no push.

## 1. Verdict on the stop condition

No semantics leak. Every one of the 103 failing tests is one of the three classes. In addition, a direct before/after comparison (section 3) of 26 committed case-input fixtures plus 2 captured cases, run under the constant patched to 2.0.0 and to 2.1.0 in every importing module, shows that the only fields that move are `run_summary.simulator_semantics_version` and `trades[].trade_id`. No price, time, count, event, cost, quantity or note field moves, and no `settlement_count` key appears.

## 2. Counts per class (suite: `.venv/Scripts/python -m pytest -m "not docker" -q -rf -p no:cacheprovider`, bump applied)

Total failing tests: 103. Unbumped baseline on the same host: exit 0, no failure.

| Class | Failing tests | Distinct artifacts to change |
| --- | --- | --- |
| VERSION_PIN | 6 | 7 literal lines in 6 test files (the 7th, tests/test_analytics_files.py:507, sits in a test that currently fails earlier, on the stored record) |
| DERIVED_DIGEST | 9 | 9 digests in tests/test_backtest_simulator.py `REGRESSION_SNAPSHOTS` + the same 9 digests in tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md (documentary copy, asserted by no test) |
| STORED_RECORD | 88 | 1 file: tests/fixtures/phase10/loaders/evidence_sample.json (1 literal `simulator_semantics_version`; see 4.3 for the stale `experiment_id`) |
| Other (leak) | 0 | none |

Other counts: 7056 tests collected under `-m "not docker"`; under the bump 103 failed, 471 skipped, 6482 passed (derived by subtraction; the repository `addopts = "-q"` plus `-q` prints no summary line). Skips on this host: 453 need a database (TEST_DATABASE_URL not set), 12 need `shellcheck` (not installed here), 6 are Windows file-mode or symlink skips. Plan 06's evidence shows 459 skipped from another host; the 12-test difference is the missing `shellcheck`, confirmed by `-rs` on the unbumped tree, and is unrelated to the bump.

## 3. Captured 2.0.0 outputs and the leak check

Cases (no `terminal_settlements` key in either; both assert it). Built from existing test helpers:
- `scripted_tracer`: `tests.test_backtest_engine.tracer_case()`, scripted LONG, fill 10:01, stopped out 10:40, 1 trade.
- `strategy_trigger_no_declaration`: `tests.test_backtest_engine_strategy.trigger_case()[0]`, strategy front-end on the phase 6 trigger-bar fixture, 1 trade (SL).

Output = `src.backtest.engine.simulate(case, risk_fn=src.risk.gating.evaluate_risk)`. Serialization for the hash: `json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()`. The captured bytes are saved outside the repo in the scratchpad (`.../scratchpad/cap/<case>.2.0.0.json`, script `.../scratchpad/capture_cases.py`); two separate runs gave identical hashes.

| Case | Bytes | sha256 of the 2.0.0 output |
| --- | --- | --- |
| scripted_tracer | 2148 | be6cd8a6cbcf390de87bf14863e097974989907e9f3657d8c9d89f91123cfcf1 |
| strategy_trigger_no_declaration | 2269 | 4635c92d2456094adf96765fd6dfedd47d2f6a6cedab7c8f8c064562f78f9266 |

Under 2.1.0 the same cases have the same byte length and differ in exactly two paths each: `/run_summary/simulator_semantics_version` and `/trades[0]/trade_id`. Design test 10 (plan 07 Task 3) must patch `SIMULATOR_SEMANTICS_VERSION` in all four modules that bind it by name: `src.backtest.semantics`, `src.backtest.records`, `src.backtest.engine`, `src.backtest.experiment` (the leak check below did exactly that and the patch reached trade_id and run_summary).

Leak check over every committed `backtest-case/2` fixture (script `.../scratchpad/leakcheck.py`, each case run under 2.0.0 and 2.1.0, deep diff of the whole output):

- 26 cases: phase14 (16 hand-derived goldens), phase6 (7 cases + 2 baselines), phase7/parity_overlapping_history.
- Result: 26 differences of `/run_summary/simulator_semantics_version`, 30 differences of `/trades[]/trade_id` (one per trade record), 0 other differences. Verdict list `OTHER []`.

## 4. Failing items, by class

### 4.1 VERSION_PIN (6 failing tests, 7 lines)

Each asserts the literal `"2.0.0"` for the constant or a record field derived from it. Regeneration path: none to run; the literal is the constant, so the re-pin is a one-token edit to `"2.1.0"` (allowed by plan 07: "re-pin each VERSION_PIN literal"). No hash or id is involved.

| # | File:line | Failing test | Change |
| --- | --- | --- | --- |
| 1 | tests/test_backtest_engine.py:169 | test_output_carries_summary_hashes_and_symbols | `== "2.0.0"` to `== "2.1.0"` |
| 2 | tests/test_backtest_experiment.py:803 | test_assemble_binds_the_run_summary_into_typed_fields | same |
| 3 | tests/test_backtest_experiment.py:1202 | test_the_record_serializes_without_the_research_gate_keys | same |
| 4 | tests/test_backtest_lifecycle.py:154 | test_phase_constants_pin_the_user_resolved_tp1_policy | same |
| 5 | tests/test_backtest_run_summary.py:167 | test_run_facts_echo_the_protocol_constants_and_the_inputs | same |
| 6 | tests/test_backtest_terminal_settlement.py:200 | test_vocabulary_constants_are_pinned | same |
| (7) | tests/test_analytics_files.py:507 | test_the_v2_sample_carries_every_typed_experiment_field_and_validated_trades | same; counted under STORED_RECORD because the test fails on the load first |

Plan 07 front matter gap: item 6 is in `tests/test_backtest_terminal_settlement.py`, which is NOT in `files_modified` of plan 07 (a file added by plan 03). Item list for 4.2 also needs `tests/test_backtest_simulator.py`, also absent. See section 8.

### 4.2 DERIVED_DIGEST (9 failing tests)

Test: `tests/test_backtest_simulator.py::test_phase6_case_matches_its_regression_snapshot[<name>]`. Each pins `sha256_hex` of the whole run output of one phase 6 fixture; the output holds `trade_id` and `run_summary.simulator_semantics_version`, so each digest moves. The scenario tuples (entry kind, exit kind, fallback flag, touch count) pass unchanged. The inputs (`input.json`) carry no version, so they do not move.

Cases: intrabar_both_touched, intrabar_both_touched_short, intrabar_missing_fallback, limit_touch_no_fill, limit_partial_fill, limit_expiry, invalidation_cancels_entry, baselines/no_trade, baselines/simple_trend.

Places that hold each digest:
- tests/test_backtest_simulator.py `REGRESSION_SNAPSHOTS` (lines about 316 to 353), asserted.
- tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md, table column 3, same 9 digests, documentary: no test asserts the digest values there (only the case names), so it goes stale silently if not updated.
- docs/DECISIONS.md and `.planning` summaries quote the same digests: HISTORY, unchanged.

Regeneration path: the test's own build path, as stated in the test comment ("re-pin by printing `_digest(run(case))`"). Not `scripts/gen_phase6_fixtures.py`: that writes inputs only and the inputs do not move (verified: the 9 inputs run under 2.0.0 reproduce today's pinned digests, and gen_phase6 / gen_phase14 / `_regen_phase4_expectations.py` / `_compute_phase4_fixtures.py` produce nothing version-derived).

Exact command (prints name and digest; verified on the unbumped tree: 9 names, 0 mismatch against the current pins; under the bump it prints the new values):

```
.venv/Scripts/python -I -c "import sys; sys.path.insert(0,'.'); from tests.test_backtest_simulator import REGRESSION_SNAPSHOTS,_case,_digest; from src.backtest.simulator import run; [print(n,_digest(run(_case(n)))) for n in sorted(REGRESSION_SNAPSHOTS)]"
```

Application proposal for Task 3: a throwaway script (not committed) that reads the old digest of each name from `REGRESSION_SNAPSHOTS`, computes the new digest with the line above, and substitutes old to new by exact string match in the two files, asserting each old digest occurs exactly once in each file. No digest is typed.

### 4.3 STORED_RECORD (88 failing tests, one file)

Artifact: tests/fixtures/phase10/loaders/evidence_sample.json (`analytics-evidence/2`, `evidence_class` fixture). `backtest[0].experiment.simulator_semantics_version` is `"2.0.0"` (line 73); `ExperimentRecord.__post_init__` now refuses it (`IncompleteExperimentRecord`, surfaced as `EvidenceFileError: backtest[0]: invalid experiment record (IncompleteExperimentRecord)`), so every test that loads the sample fails at the load.

Failing tests by file: tests/test_analytics_cli.py 44, tests/test_analytics_files.py 24 (23 plus the one that also holds the VERSION_PIN line 507), tests/test_paper_shadow_evidence_export.py 10, tests/test_killgate_guard.py 6, tests/test_soak_evidence_export.py 2, tests/test_paper_test_signal_rehearsal.py 1, tests/test_terminal_settlement_consumers.py 1. Their failure text is always the IncompleteExperimentRecord refusal or an assertion on the CLI output that carries it ("Report not produced: backtest[0]: invalid experiment record ..."). Verified: a copy of the sample with only that field set to 2.1.0 loads under the bump (scratchpad copy, not the repo file).

Findings that bear on the regeneration path:
1. The trades in the sample are hand-built (`trade_id` T-1, T-2), not engine output, so no trade id in it moves.
2. The sample has no committed generator. Its `experiment_id` (`e3bb209d...`, three occurrences: lines 32, 177, 194) was written by an uncommitted scratch script in plan 14-15. Since quick 261011-mi1 (`data_manifest_hash` joined the experiment identity) it is already NOT what `assemble` would produce: it equals `sha256_hex` of the identity payload WITHOUT the `data_manifest_hash` key, strategy_id trend-pullback, version 2.0.0 (checked by recomputation; with the key present it does not match). The loader does not recompute the id, and mi1 deliberately kept the fixture unchanged (its B5 test requires `data_manifest_hash is None` on it). So `assemble` cannot rebuild this record (it requires a manifest hash).
3. Serialization of the file in the index is exactly `json.dumps(doc, sort_keys=True, indent=2) + "\n"`, LF (the working copy is CRLF through autocrlf). A rewrite with that serialization is byte-stable (verified on a scratch copy: no-op under 2.0.0).

Options for the user (the decision belongs to Task 2):
- S1, minimal (recommended): set only `backtest[0].experiment.simulator_semantics_version` to the code constant, read from `src.backtest.semantics`, not typed; `experiment_id` stays at the value it already has (stale since mi1, unread by any code). One-line diff in the fixture. Command (verified as a no-op under 2.0.0 and as a version-only rewrite on a scratch copy):
  ```
  .venv/Scripts/python -I -c "import json,sys; sys.path.insert(0,'.'); from pathlib import Path; from src.backtest.semantics import SIMULATOR_SEMANTICS_VERSION as V; p=Path(sys.argv[1]); d=json.loads(p.read_text(encoding='utf-8')); d['backtest'][0]['experiment']['simulator_semantics_version']=V; p.write_bytes((json.dumps(d,sort_keys=True,indent=2)+chr(10)).encode())" tests/fixtures/phase10/loaders/evidence_sample.json
  ```
- S2: S1 plus recompute `experiment_id` (3 occurrences) by the legacy payload formula with version 2.1.0. No committed code builds that id; it would be a bespoke script, and it would still not equal what `assemble` yields today. Changes the id the CLI and report tests print, if any pins an id prefix (none found by grep of the id literal outside the fixture).
- S3: rebuild the sample through `assemble` with a manifest hash. This changes the fixture shape (new key, new id), reopens plan mi1's B5 test and is a bigger change than a version effect. Not recommended inside this plan.

Latent member of this class (skipped here, no TEST_DATABASE_URL): `tests/test_soak_evidence_export.py::test_the_pg_source_exports_every_record_stored_on_postgresql` (about line 819) builds its analytics inputs through `_backtest_part()` from the shadow-export tests, which reads this sample, so it will need S1 as well. Not run, so unverified.

## 5. Code comments that state the current version (proposed historical wording)

Wording for all: "2.0.0 at the time; the version moved to 2.1.0 with the terminal settlement, D070". Executed in Task 3 only.

| File:lines | Current text | Proposed |
| --- | --- | --- |
| src/backtest/semantics.py:19-23 (WR-05 note, review WR-05 of plan 14-17) | "... the hashes derived from them, while this version stays 2.0.0 because no price, time, cost, count or event moves." | "... the hashes derived from them, while the version stayed 2.0.0 at the time because no price, time, cost, count or event moved (2.0.0 at the time; the version moved to 2.1.0 with the terminal settlement, D070)." |
| src/backtest/lifecycle.py:32-36 (docstring "Digest consequence (WR-05)") | "... no price, time, cost, count or event moves, and `SIMULATOR_SEMANTICS_VERSION` stays 2.0.0." | "... no price, time, cost, count or event moves, and `SIMULATOR_SEMANTICS_VERSION` stayed 2.0.0 at the time (2.0.0 at the time; the version moved to 2.1.0 with the terminal settlement, D070)." |
| src/backtest/semantics.py:88-92 (not in the plan's list; found) | "Vocabulary only: SIMULATOR_SEMANTICS_VERSION is bumped in plan 07, after the regeneration inventory is approved." | "Vocabulary only when added; SIMULATOR_SEMANTICS_VERSION moved to 2.1.0 in plan 07 (D070) after the regeneration inventory was approved." |

Other mentions of the constant in `src/` (experiment.py, engine.py, records.py, lifecycle.py:102, semantics.py:5 and :27) state no number and need no change.

## 6. Docs mentions of the 2.0.0 simulator version: HISTORY (unchanged in plan 07)

Count: 8 lines in 3 files that state `simulator_semantics_version` 2.0.0.
- docs/backtest/BACKTEST_SPEC.md:35 (WR-05 exception sentence "stays 2.0.0").
- docs/research/RESEARCH_PROTOCOL.md:31, :35, :39, :43 (migration paragraphs v2.0.0 to v2.3.0 name "`simulator_semantics_version` 2.0.0"), :441 (change log row v2.0.0).
- docs/DECISIONS.md:56 (D052 row, two mentions).

Correction to the plan text: the other lines the plan listed (BACKTEST_SPEC.md:14, RISK_MANAGEMENT.md:62, GEOMETRY_AUDIT.md:129 and :157) say "protocol v2.0.0" or "RESEARCH_PROTOCOL v2.0.0", which is the research protocol version, not the simulator version. They are also HISTORY and untouched. The D053 row and the DOC_STATUS log (lines 61 and 62) name protocol versions only. Plan 09 adds the in-force statement. `.planning/phases/16-paper-runtime-composition/decisions/16-AMEND-v2.4.0-DRAFT.md` (lines 129 and 139) already says the version moves 2.0.0 to 2.1.0; not edited here.

## 7. Passing but version-sensitive (no failure under the bump)

1. tests/fixtures/phase6/REGRESSION_SNAPSHOTS.md: the 9 documentary digests are stale after the bump and no test notices (see 4.2).
2. tests/test_backtest_experiment.py:948-958 and :1363 monkeypatch the constant to "2.0.1" and pass under 2.1.0 (2.0.1 differs from 2.1.0 too). No change needed; they would keep working after the re-pin.
3. tests/test_analytics_files.py:539 and tests/test_backtest_experiment.py:975, :1081 use "1.0.0" as the wrong value; unaffected.
4. tests/test_backtest_goldens.py (16 hand-derived goldens) compares selected fields and never `trade_id` or the version: passes, and the leak check confirms its inputs only move in the two version-derived fields.
5. Phase 7 `parity_overlapping_history/expected.json` (verdict digest and parameter_set_hash) passes unchanged: its digest does not hash the trade id.
6. Skipped on this host (no TEST_DATABASE_URL): `tests/test_soak_evidence_export.py` PostgreSQL test (probably STORED_RECORD, see 4.3). The other 451 database skips are persistence, runtime-state and similar tests with no engine-output or version dependency found by grep (the two files that mention backtest words, tests/test_analytics_store.py and tests/test_kill_gate_docs.py, do not load the sample); the one in `tests/test_paper_test_signal_rehearsal.py` runs the shadow rehearsal and does not read the sample.
7. `src/adapters/analytics_files.py:115` lists `simulator_semantics_version` as a required experiment key (a key name, not a value): no change.
8. No stored ExperimentRecord, `experiment_id` or run summary exists in `params/`, `docs/research/*.json`, `data/` or any committed non-test JSON (grep of tracked files for `simulator_semantics_version` outside `.py`, tests/fixtures and docs found only markdown and the one sample).

## 8. Notes for plan 07 Task 3 and for the approval

- `files_modified` of plan 07 does not list `tests/test_backtest_simulator.py` (9 digests) or `tests/test_backtest_terminal_settlement.py` (pin at :200). Both must be edited or Task 3 cannot go green; the user's approval should name them.
- tests/test_analytics_files.py is in `files_modified` and needs only the :507 literal if S1 is chosen; the fixture is under `tests/fixtures/` (allowed by the plan's note).
- No script in `scripts/` needs to run. Generators `gen_phase6_fixtures.py` and `gen_phase14_fixtures.py` write inputs only (no version, no trade id), and Phase 4 generators feed features that did not move.
- Expected post-regeneration state: 0 failures, driven by 6 literal re-pins (7 lines), 9 computed digests in 2 files, 1 computed field in 1 fixture (S1).
- Paper decisions and fills: untouched. `tests/test_paper_shadow_fill.py` and `tests/test_backtest_funding.py` pass under the bump, as the plan expects.
