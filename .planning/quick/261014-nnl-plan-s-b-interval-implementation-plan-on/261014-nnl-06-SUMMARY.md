---
phase: quick-261014-nnl
plan: 06
subsystem: research runner / terminal settlement independence evidence
tags: [s-b-interval, integration, validation-independence, g1, plateau, prebump-evidence]
requires: ["02", "04", "05"]
provides:
  - "tests/test_research_terminal_settlement_integration.py: design tests 1 and 3 end to end through run_research (5 tests)"
  - ".planning/phases/16-paper-runtime-composition/evidence/16-S-B-interval-prebump-check.txt: pre-bump regression evidence at SIMULATOR_SEMANTICS_VERSION 2.0.0"
affects: [quick-261014-nnl plan 07]
key-files:
  created:
    - tests/test_research_terminal_settlement_integration.py
    - .planning/phases/16-paper-runtime-composition/evidence/16-S-B-interval-prebump-check.txt
  modified: []
decisions:
  - "Test 1 compares two manifests with disjoint synthetic bound sets ([94, 96] and [104, 106]); each has its own evidence bytes under its own tmp repo root with the same relative paths, so the runner evidence recompute passes for both"
  - "experiment_id and data_manifest_hash are removed from the record comparison and asserted to differ (D067), as clarified at planning"
  - "The AST allowlist of Development readers is a Counter equality (path, enclosing function, node kind -> count), so a second mention inside an allowed function also fails"
requirements-completed: []
status: complete
commits: 2
plan_head_before: b663fb6b7da8ecda17944b2b3341f8d515fbbf04
plan_head_after: 42b914b059fdf2d1478fd35b9241b1c5dbaccd51
actuals:
  tokens: 8400   # chars/4 over the diff b663fb6..HEAD (one test file, one evidence file)
  tasks: 3
  commits: 2
metrics:
  completed: 2026-10-14
---

# Phase quick-261014-nnl Plan 06: Validation independence and pre-bump evidence Summary

Through the real `run_research`, two manifests whose terminal-settlement bounds differ give byte-equal Validation case dicts, run summaries and experiment records (apart from `experiment_id` and `data_manifest_hash`), G1 lines and plateau summaries ignore every Development settlement mutation, and a full-suite pass at the unbumped 2.0.0 version with only added test files is recorded as evidence.

## Task results

| Task | Name | Commit | Result |
| ---- | ---- | ------ | ------ |
| 1 | Design test 1 (two manifests, lower vs upper bound set, through run_research) | 4366bb1 | 2 passed |
| 2 | Design test 3 (G1 and plateau Validation only; Development settlement reported apart; AST allowlist) | 4366bb1 (same file) | 3 passed |
| 3 | Pre-bump regression evidence | 42b914b | suite green, tests diff all `A`, version string 2.0.0 |

The plan adds no production code, so there is no RED step: the tests were written against the code of plans 02 to 05 and passed on the first complete run (no assertion had to be weakened or the code touched). Tasks 1 and 2 share one test file and one commit.

## What was built

- Synthetic world (module fixture, all under pytest tmp paths): a long-history symbol BTCUSDT and DELISTUSDT (REEFUSDT-shaped: data stops at T = 2026-03-04 09:00 inside Development, 4h funding, partial last day) published through the real publishers, a two-symbol constraint file, a `TerminalDeclaration` for DELISTUSDT, and the dataset id computed from the same builder call the runner makes.
- Synthetic evidence per run: 30 one-minute index klines for [T-30 min, T), one trade kline opening at T, one supporting file, all written under `tmp/<name>/repo/evidence/`. Bounds are derived by hand from the formulas (nominal base -/+ 0.5, tick 0.01 widening -/+ 0.51, trade candle base -/+ 1, union base -/+ 1) and the runner's own `check_terminal_settlement_evidence` recomputes them from the bytes, so both manifests are internally consistent with their evidence.
- `test_bounds_never_reach_validation_outputs_or_records`: a spy around `simulator.run` captures every case dict and output of two full `run_research` runs (5 windows each). Validation cases carry no `terminal_settlements` key and are byte-equal; Validation trades and run summaries are byte-equal and carry no `settlement_count`; Validation records are byte-equal after removing `experiment_id` and `data_manifest_hash`, which differ (and `data_manifest_hash` equals each manifest's own hash); the Development cases differ only in `terminal_settlements`.
- `test_the_bound_reaches_development_output`: the plan 03 scripted case (OPEN LONG and SHORT at T) settles at exactly the given lower or upper bound, and a different bound changes `exit_price` and `realized_pnl`; this is what makes test 1 non-vacuous.
- `test_g1_and_plateau_inputs_are_validation_records_only`: a two-point grid over the real records of the run, non-empty Validation folds (12 closed trades pooled), and six Development mutations (settlement at the lower bound, at the upper bound, two settlements, only a settlement, no trade, settlement removed again): `_plateau_summaries` is equal in all, and every `_feasibility_lines` line is equal except that the Development part of the line is allowed to differ while its Validation part (from `pooled_closed=` on) stays byte-equal.
- `test_development_settlement_is_reported_apart_and_never_counted_closed`: `development_settlement` 0 to 1, `development_closed` unchanged, pooled and fold figures and shortfalls unchanged, the rendered figure sits before the first Validation figure.
- `test_no_g2_g3_g4_producer_reads_development`: AST scan of `src/research/*.py` and `src/analytics/gates.py`; the mentions of the `DEVELOPMENT` name or string are exactly the four documented groups (manifest constant definition, its `__all__` entry, `research_splits`, run.py `_feasibility_lines` as reporting). No unexpected reader exists today, so the allowlist was not widened.

## Verification

- `pytest tests/test_research_terminal_settlement_integration.py`: 5 passed.
- Whole suite `uv run --frozen pytest -m "not docker"`: 6597 passed, 459 skipped (live-PostgreSQL and other conditional skips), 0 failed, exit 0 (plan 05 baseline 6592 + 5 new tests).
- `mypy src`: no issues in 185 files. `ruff check`, `ruff format --check` (542 files): clean. `uv lock --check`: resolved, no change.
- Evidence file verify command from the plan: base_commit line present, `git diff --name-status d186b9e HEAD -- tests` is seven `A` lines, no `M` or `D`; `git diff --stat d186b9e HEAD -- src/paper params tests/fixtures` is empty; `SIMULATOR_SEMANTICS_VERSION = "2.0.0"`.

## Pre-bump evidence

`.planning/phases/16-paper-runtime-composition/evidence/16-S-B-interval-prebump-check.txt` (committed 42b914b): `base_commit: d186b9e5193411cd5c27883a48182bf4eaa6b025`, `head_commit: 4366bb1d45facc29dd6b23d308e99f15ee0dc1bf`, gate outputs with exit statuses, the test-diff listing, the commit list of the plan set, and sha256 `ede1380809d2682c3317f3120151c6247f4807b2a6bc830bb5f72e0292baf981` of the new integration test file as committed (LF).

## Deviations from Plan

1. [Judgement] The synthetic strategy run produces no trade (only `no_trade_counts`: NO_TRADE_REGIME, WARMUP_INSUFFICIENT), so in test 1 the Validation trade lists are empty and their byte-equality is weak evidence by itself. The load-bearing equality is that of the Validation case dicts (equal simulator inputs, deterministic simulator) plus the engine-level test that the bound does reach a settled trade; the module docstring and the evidence file say so. The design 3 tests use non-empty Validation folds built from the existing `_gap_trade` helper, so their equalities are not about empty lists.
2. [Judgement] Test 1 keeps the Development outputs out of the equality comparison (only the case dicts are compared, as the plan states); the Development `settlement_count` is asserted present and 0, since no position is open at T in the synthetic strategy run.
3. [Plan wording] Tasks 1 and 2 share one test file, so they were committed together (4366bb1) rather than as two commits; the second of the three verify commands in the plan (>= 5 passed) is met by that file.
4. [Environment] `uv run --frozen` was used for the gates (no lock rewrite); `core.autocrlf=true` means git warns that LF becomes CRLF in the working copy, the committed blobs are LF (checked with `git show :file | grep -c $'\r'` = 0 for the test file; the evidence file has no CR).
5. The branch is `develop`, which the generic executor protected-branch assertion lists; committing there was directed by the caller and the plan, on the main tree with no worktree.

No auth gates. No stubs. No threat flags beyond the plan's threat model (T-nnl-15 mitigated by tests 1 and 3 through the runner and the AST allowlist; T-nnl-16 mitigated by the evidence file).

## Not done (by scope)

Plans 07 to 10: version bump (2.0.0 stays), regeneration, protocol text, `holdout_consumed.json`, the real REEF manifest file, ROADMAP and STATE updates. No production code and no existing test file was edited. Experiments and records existed only inside pytest tmp paths; no Holdout was read.

## Self-Check: PASSED

`tests/test_research_terminal_settlement_integration.py` and the evidence file exist, both commits (4366bb1, 42b914b) are in `git log`, and `commits: 2` was measured with `git rev-list --count` from the persisted ledger (base b663fb6).
