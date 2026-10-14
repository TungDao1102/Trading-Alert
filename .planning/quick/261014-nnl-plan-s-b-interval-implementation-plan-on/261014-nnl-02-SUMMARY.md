---
phase: quick-261014-nnl
plan: 02
subsystem: research manifest / runner / terminal settlement
tags: [s-b-interval, manifest, terminal-settlements, evidence-check, guard, tdd]
requires: ["01", "03"]
provides:
  - "src/research/manifest.py: EvidenceFile, TerminalSettlement, DatasetManifest.terminal_settlements (default empty, last field), cross-validation and the Validation/Holdout guard, canonical omission, loader support"
  - "src/research/run.py: terminal_settlement_case_rows, check_terminal_settlement_evidence, wiring in _run_split and run_research"
affects: [quick-261014-nnl plans 04, 05, 06]
key-files:
  created:
    - tests/test_research_terminal_settlement_manifest.py
  modified:
    - src/research/manifest.py
    - src/research/run.py
decisions:
  - "The settlement is a separate optional manifest entry keyed by symbol; TerminalDeclaration keeps its four fields and carries T; the entry carries no T of its own"
  - "canonical() adds terminal_settlements only when non-empty; an undeclared manifest hashes to the value captured from the code before this plan (567af7e5...)"
  - "A Decimal in an entry must be in canonical spelling (same digit tuple as canonical_decimal_text), because the hash writes str(value); this still admits tiny ticks such as 1E-7"
  - "The loader refuses an empty terminal_settlements list (omit the key), so one manifest has one file form"
  - "Rows reach only a window with start < T < end; _check_manifest_against_store is unchanged"
  - "The runner check runs after _load_constraints and before _check_manifest_against_store, confined to repo_root, sha256 first, then a full recompute"
requirements-completed: []
status: complete
commits: 6
plan_head_before: 60f75b2def3979932778240552daa56edf900af6
plan_head_after: 7c84c3599d414df315f6df55316c0e25c7693d73
actuals:
  tokens: 19400   # chars/4 over the diff 60f75b2..HEAD (src and tests)
  tasks: 3
  commits: 6
metrics:
  completed: 2026-10-14
---

# Phase quick-261014-nnl Plan 02: Manifest terminal_settlements, builder rule and evidence check Summary

A hashed, cross-validated `terminal_settlements` manifest entry now exists (REEF row tested in memory only), a settlement whose declared terminal is not strictly inside Development is refused at construction, only the window containing T receives case rows, and the runner recomputes every stored bound from the committed evidence bytes before any simulation.

## Task results

| Task | Name | Commits | Result |
|------|------|---------|--------|
| 1 | TerminalSettlement entry, cross-validation, guard, canonical omission, loader (design test 2) | fab81c4 (RED), b51e259 (GREEN) | RED: ImportError at collection (EvidenceFile missing); GREEN: manifest, runner and known-gap tests pass |
| 2 | Builder rule: only the window containing T gets case rows | 8a59c93 (RED), d51f867 (GREEN) | RED: ImportError (terminal_settlement_case_rows missing); GREEN: the 3 named tests pass plus the run-split and symbol-order tests |
| 3 | Runner fail-closed evidence check | f837043 (RED), 7c84c35 (GREEN) | RED: ImportError (check_terminal_settlement_evidence missing); GREEN: tamper, missing, re-hash, path-escape and before-simulation tests pass |

## What was built

- `manifest.py`: frozen `EvidenceFile(path, sha256)` (clean posix repo-relative path, no backslash, drive, `..`, `.`, empty segment; sha256 lowercase hex64) and frozen `TerminalSettlement` with the 19 interface fields. Its `__post_init__` checks: closed vocabulary (kind, recorded_evaluation from `src.backtest.semantics`), minute-aligned UTC `bound_window_start_utc`, `samples_per_minute` the int 60 (not bool, not float), canonical finite positive Decimals aligned to the tick, nominal fractions as reduced "p/q" text, `tick_widened_bounds(nominal) == (index_lower, index_upper)`, `union_bounds(...) == (price_lower, price_upper)` (each mismatch names its field), `price_lower < price_upper`, evidence files typed, supporting evidence tuple sorted by path and unique, non-empty condition, `official_confirmation is None`.
- `DatasetManifest.terminal_settlements` (last field, default `()`): per entry, the symbol needs a `known_gaps` declaration, one entry per symbol, `development_start_utc < T < validation_start_utc` (the T-at-or-after-validation text says the settlement would reach Validation or Holdout), T minute-aligned, window start before T. `canonical()` adds the key only when non-empty.
- Loader: top-level key set is the old set or the old set plus `terminal_settlements`; strict row and evidence keys; decimals must already be in canonical text; `samples_per_minute` must be a JSON int; floats are refused by the existing `parse_float` hook; an empty list is refused.
- `run.py`: `terminal_settlement_case_rows(manifest, window)` (rows in symbol order, all strings, bounds via `canonical_decimal_text`), `_run_split` passes `terminal_settlements=` only when rows exist, `check_terminal_settlement_evidence(manifest, repo_root)` and its call in `run_research`; docstrings updated with the new refusal order.

## Verification

- `pytest tests/test_research_terminal_settlement_manifest.py tests/test_research_runner.py tests/test_research_known_gap_reason.py`: all pass, existing runner and known-gap tests unedited.
- Undeclared manifest hash is pinned to `567af7e5924dfe6c79f976858b95566e7020055e2d220ec16f4f55940280b806`, captured by running the pre-change `DatasetManifest` at base 60f75b2 before any edit.
- `mypy src`: no issues in 185 files. `ruff check` and `ruff format --check`: clean.
- `pytest -m "not docker"` (whole suite, including the AST purity and no-float guards): exit 0, no failure and no error; the expected DB-dependent tests skip without `TEST_DATABASE_URL`. `ruff check`, `ruff format --check` (539 files), `mypy src` (185 files) and `uv lock --check` are clean.
- `git diff --name-status 60f75b2 HEAD`: two source modifications and one added test file; no deletion; nothing under params/, src/paper/, docs/, .gsd/, package files; no existing test file touched; `TerminalDeclaration`, `src/data/case_input.py`, `holdout_consumed.json` untouched.

## Deviations from Plan

1. [Test correction] One RED-commit test (`test_the_stored_union_cannot_hide_a_wider_index_bound`) assumed the manifest alone can see a trade-candle value that contradicts the evidence. That is not checkable from the row; the row is self-consistent and only the evidence recompute can refuse it. The test was removed in the Task 1 GREEN commit and replaced by `test_a_self_consistent_manifest_row_that_the_evidence_contradicts_is_refused` in Task 3 (runner check).
2. [Bug found by test] The first canonical-text rule (`canonical_decimal_text(v) == str(v)`) would have refused a tick of 1E-7 (str gives `1E-7`). The rule is now "same digit tuple as the canonical spelling", which keeps the hash text unique per number and still admits small ticks. Fixed before the Task 1 GREEN commit.
3. [Judgement] The loader refuses an empty `terminal_settlements` list (plan silent): an empty list and an absent key would be two file forms of one hash, and the case parser (plan 03) already refuses an empty list. Row tests also cover it.
4. [Judgement] `_evidence_bytes` refuses a rooted or drive-letter path on every platform, not only where `resolve()` escapes the root, so the path-confinement result does not depend on the OS.
5. [Process] RED commits failed at collection (ImportError of the new names), the same shape as plan 03 Task 1 RED. The test-file edits that went with each GREEN commit were the removal in item 1 and two test-helper fixes found while turning the tests green (a `None` rows parameter and the 1E-7 tick case).
6. The branch is `develop`, which the generic executor protected-branch assertion lists; committing there was directed by the caller and the plan, on the main tree with no worktree.

No stubs. No threat flags beyond the plan's threat model (T-nnl-07, T-nnl-08, T-nnl-09 mitigated: arithmetic cross-checks inside the hash, sha256 plus recompute with path confinement before any simulation, guard plus rows only for the window containing T).

## Not done (by scope)

Plans 04 to 10, any manifest file (the REEF row exists only inside tests), freeze of research-run-1 manifests, O-03, Holdout reads, ExperimentRecord outside pytest tmp_path, engine or consumer changes, version bump (2.0.0 stays), protocol text, `holdout_consumed.json`, ROADMAP and STATE updates.

## Self-Check: PASSED

The three files exist, the six commits are in `git log`, and `commits: 6` was measured with `git rev-list --count` from the persisted ledger (base 60f75b2).
