---
phase: 16-paper-runtime-composition
plan: 54
subsystem: research manifest / case-input builder (gap closure of 16-37-REEF-GAP-REASON)
tags: [manifest, known-gaps, terminal-declaration, delisted-capped, geometry, rev-04, rev-05, paper-01]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-06 (manifest, runner, run authorization), 16-12, 16-18, 16-28; decisions/16-DEC-GAP-REASON.md (KG-1 to KG-4, decided by the user on 2026-10-13)"
provides:
  - "TerminalDeclaration (symbol, reason DELISTED_CAPPED, terminal_at_utc, source_url) as the manifest known_gaps entry, inside the manifest hash"
  - "build_case_input_data(terminal_declarations=...): a gap of a declared symbol is acknowledged only when it is a trailing hole that follows the data geometry; CaseInputGapError names the failed condition"
  - "strict loader: closed key sets, required closed reason, https source on www.binance.com, UTC terminal instant, one declaration per symbol, symbol inside the universe; offline"
affects: [16-37 (Task 3 must write the manifest in this shape and its --build must produce the declaration), 16-41]

requirements-completed: []

status: complete
actuals:
  tokens: 11000
  tasks: 6
  commits: 3
plan_head_before: 61e3be076af49c769da332daa8e84471162ea715
plan_head_after: 62d379d3a2353185d2012549b57d6b354bdea8f8
commits: 3

tech-stack:
  added: []
  patterns:
    - "A manifest-level wrapper entry that is NOT a GapRange: GapRange, its equality, the sufficiency report, the cutover and the exported case input are unchanged"
    - "The acknowledgement rule is a pure function over the series' own observed instants (_terminal_refusal), read from the files by the builder, never from the declaration"

key-files:
  created:
    - tests/test_research_known_gap_reason.py
  modified:
    - src/data/case_input.py
    - src/research/manifest.py
    - src/research/run.py

key-decisions:
  - "KG-1 sufficiency-words narrowed to one value, DELISTED_CAPPED, required (recorded by the user)"
  - "KG-2 wrapper, emission n/a, version key none (recorded by the user)"
  - "KG-3 declaration-and-geometry (recorded by the user); the other variant (exact-and-geometry, 30 rows) was NOT built"
  - "KG-4 inline, host-list www.binance.com only, no network (recorded by the user)"
  - "Executor layout choices inside the recorded decisions: the declaration type lives in src/data/case_input.py (the manifest cannot be imported by src/data), the manifest holds declarations ONLY in known_gaps (a six-key row is refused), the reason is the cause (one field)"

patterns-established:
  - "An acknowledgement by rule is guarded by recomputing the geometry from the files, so a declaration can never widen what is acknowledged"

coverage:
  tests_added: 38
  mypy: clean (183 source files)
  ruff: clean
---

# Phase 16 Plan 54: Structured terminal declaration for manifest known gaps Summary

**A manifest known gap is now a per-symbol terminal declaration (reason DELISTED_CAPPED, terminal instant, official source, all inside the manifest hash) that the case-input builder honours only for trailing holes that follow the data geometry; an interior, unexplained or inconsistent hole is still refused, and the reason never reaches the case input or the record.**

PAPER-01 is addressed but `requirements-completed` stays EMPTY (SC9: PAPER-01 closes only on REAL soak evidence).

## What was built

The user decisions KG-1 to KG-4 were already recorded in `decisions/16-DEC-GAP-REASON.md` (commit 61e3be0, not edited here). Tasks 1-4 were not presented again; their verify greps were run against that file and all passed (`KG1 option: sufficiency-words`, `KG1 row-policy: required`, `KG2 option: wrapper`, `KG2 emission: n/a`, `KG2 version-key: none`, `KG3 option: declaration-and-geometry`, `KG4 option: inline`, `KG4 source-validation: host-list`, every `decided by: user`, and the incompatible pair field + declaration-and-geometry absent).

| Piece | Where | What |
|-------|-------|------|
| Entry type | `src/data/case_input.py` `TerminalDeclaration` | frozen: `symbol`, `reason` (closed vocabulary `TERMINAL_REASONS = {DELISTED_CAPPED}`), `terminal_at_utc` (UTC-aware), `source_url` |
| Acknowledgement rule | `src/data/case_input.py` `_terminal_refusal`, `_apply_terminal`, `_apply_allowed` | one function next to the exact-match rule; plain `GapRange` equality via `allow_gaps` is untouched |
| Builder keyword | `build_case_input_data(terminal_declarations=())` | default empty, so every existing caller is unchanged |
| Error | `CaseInputGapError(gaps, refusals=None)` | the message names the failed condition per refused gap; no new error type |
| Manifest | `src/research/manifest.py` | `known_gaps: tuple[TerminalDeclaration, ...]`; constants `KNOWN_GAP_REASONS`, `KNOWN_GAP_REASON_DELISTED_CAPPED`, `KNOWN_GAP_SOURCE_HOSTS = {"www.binance.com"}`; canonical form `{symbol, reason, terminal_at_utc, source_url}`; closed key sets; no version key; `known_gaps: []` canonical form is unchanged from before |
| Runner | `src/research/run.py` | both builder call sites (`_check_manifest_against_store`, `_run_split`) pass `terminal_declarations=manifest.known_gaps` instead of `allow_gaps=manifest.known_gaps`; the `excluded_periods` refusal is untouched |

### The KG-3 rule as implemented (`_terminal_refusal`)

For every detected gap of a declared symbol, in every one of the six builder calls, the gap is accepted only when ALL hold; the first failed condition is named in `CaseInputGapError`:

1. symbol and declaration match (a gap of a symbol without a declaration is never touched here);
2. the gap is trailing and ends exactly at the window end (an interior or leading hole means data after the gap start: "not trailing");
3. the series has no observation at or after `terminal_at_utc` (the last observed instant is read from the files, never from the declaration);
4. the gap start is the first slot after that last observation, or the window start for a series with no observation in the window ("first slot after the last observation"), and for non-funding series on the cadence grid;
5. `missing` equals the count recomputed from the data geometry ("missing count");
6. the gap start is at or after `terminal_at_utc` ("terminal timestamp is after the gap start").

The start is NOT forced to be the same instant across series (REEFUSDT-shaped store: 1h/1m/mark start at 09:00, 4h and funding at 12:00). `terminal_at_utc <= gap.start_utc` alone is not enough: the interior-gap test uses a declaration whose terminal equals the interior hole start and it is still refused.

## Which KG-3 variant was built

Only `declaration-and-geometry` (1 declaration per symbol). The `exact-and-geometry` variant (30 rows) was NOT built. KG-1 `required`: Task 6 Test 6 and the loader tests refuse a row without a reason, and the old six-key row shape is refused (no committed manifest used it).

## Task commits

| Task | Commit | Type | Content |
|------|--------|------|---------|
| 5 RED | `7a72b59` | test | tracer tests (manifest file, mismatching declaration, hash binding, strict loader, closed key set) |
| 5 GREEN | `8bc1485` | feat | `TerminalDeclaration`, geometry rule, loader, hash, runner call sites |
| 6 tests | `62d379d` | test | expansion tests (characterization, see below) |

Tasks 1-4: no commit by this run (decisions were committed as 61e3be0 before it).

## RED evidence

**Task 5 (tracer), RED run at `7a72b59`: 16 collected, 5 failed, 11 passed.**

- Failed for the intended reason: `test_tracer_manifest_file_is_loaded_hashed_and_acknowledged` and `test_the_hash_binds_the_terminal_fields` (`ManifestError: known gap has missing keys ['end_utc', 'interval', 'missing', 'series', 'start_utc'] and unknown keys ['reason', 'source_url', 'terminal_at_utc']`, the old six-key loader), and the three `test_a_mismatching_declaration_leaves_the_holes_unacknowledged[...]` cases (`AttributeError: module 'src.data.case_input' has no attribute 'TerminalDeclaration'`).
- Passed at RED, recorded as such: `test_without_a_declaration_the_same_holes_still_raise` (characterization: the existing builder already raises for the 5 holes) and the 9 `test_the_loader_refuses_a_malformed_declaration[...]` cases plus `test_the_closed_top_level_key_set_still_refuses_an_unknown_key`. The malformed-declaration cases pass at RED only because the old loader refuses every new-shape row; their guard value comes from the positive control (Test 1 loads a valid declaration at GREEN) and from Task 6's `test_the_loader_refuses_a_bad_field` and structural tests.
- GREEN `8bc1485`: 16 passed.

**Task 6 (expansion), run at `62d379d`: 22 added tests, 38 total, all passed on the first full run.** Honest record: Task 5 GREEN already implemented the whole recorded rule, so no Task 6 test was red against the production code; they are a characterization of that rule, not a RED. One run failed because of a wrong expectation in my own test (`test_the_geometry_check_accepts_a_consistent_gap_and_names_each_failure`: for data after the gap start the failing condition named first is the observation check, not the start check); the test was corrected, no production code changed. To show the tests have teeth, five mutations of `_terminal_refusal` (drop the trailing check, the missing-count check, the terminal-after-start check, the observation check, the start-geometry check) were applied one at a time and each made at least one test fail (trailing: 2, missing: 1, terminal: 3, observation: 2, start: 1); each mutation was reverted with `git checkout -- src/data/case_input.py` and the file is committed unmodified.

Required extra cases are covered: wrong `missing` count (unit check on a doctored gap, +1 and -1), data after the gap start (interior-gap store test and the doctored unit check), the REEFUSDT-shaped store with the partial 4h bar (the 08:00 bar exists, next missing slot 12:00) and 4h funding whose next slot is 12:00.

## Verification output

Task 5 verify (tests, then gates): `tests/test_research_known_gap_reason.py tests/test_research_runner.py tests/test_case_input_builder.py tests/test_coverage.py tests/test_sufficiency.py tests/test_cutover.py` all passed; `uv run mypy src`: `Success: no issues found in 183 source files`; `uv run ruff check`: `All checks passed!`; `uv run ruff format --check`: `531 files already formatted`.

Task 6 verify (17 test files: the new file, test_research_runner, test_case_input_builder, test_coverage, test_sufficiency, test_cutover, test_backtest_funding, test_backtest_engine, test_backtest_experiment, test_analytics_files, test_backtest_purity, test_domain_no_float, test_research_feasibility, test_research_run1_registration, test_research_register, test_quality_gates, test_decision_alignment_protocol): `595 passed, 1 skipped in 193.48s`; the new file alone: `38 passed`; mypy, ruff check and ruff format --check clean (as above); the forbidden-path and LF check printed `forbidden: [] crlf-in-blob: []` with exit 0 (files in the plan's commits: the plan and the decision file, `src/data/case_input.py`, `src/research/manifest.py`, `src/research/run.py`, `tests/test_research_known_gap_reason.py`; `src/data/coverage.py` is not among them, consistent with KG-2 wrapper).

Wider sweep: every `tests/test_*.py` that references `case_input` or `src.research` (including the paper, backtest, execution and reconcile suites that import the builder): `1623 passed, 2 skipped`. The known pre-existing `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments` did not fail in this run.

## Deviations from Plan

### Design choices inside the recorded decisions (not new decisions)

**1. [Layout] The declaration type lives in `src/data/case_input.py`, not in `manifest.py`.**
- **Why:** the builder (in `src/data`) takes the declarations and must not import `src.research`; the manifest imports the type. The vocabulary constants the plan places in the manifest are re-exported there (`KNOWN_GAP_REASONS`, `KNOWN_GAP_REASON_DELISTED_CAPPED`, `KNOWN_GAP_SOURCE_HOSTS`, with a comment naming plan 16-54 and KG-1/KG-4). The source host list and URL rule stay in `manifest.py` (the builder never looks at the URL).
- **Files:** `src/data/case_input.py`, `src/research/manifest.py`.

**2. [Layout] `known_gaps` holds terminal declarations only.**
- **Why:** KG-1 `required` ("a six-key row is refused", "a gap not explained by a valid terminal declaration is refused") plus the single reason value leave no kind of entry for an ordinary six-field row. The runner therefore passes no `allow_gaps`; the exact six-field match stays in the builder for direct callers and every existing test.

**3. [Naming] The user's "cause" (KG-4) and "reason" (KG-1) are one field, `reason`.** Both carry `DELISTED_CAPPED`, the sufficiency-report cause word. Flagged in the open points below.

**4. [Import] `src/data/case_input.py` imports the module-private `_observed_times_ms` from `src/data/coverage.py`** (same package, to read the series' own observed instants for the geometry check). `coverage.py` is not modified, per KG-2 wrapper.

**5. [Test technique] The hash pins compare the canonical dictionary and a sha256 computed by hand-written code in the test** (JSON of the literal dictionary), not a hex literal, so no value is derived from the code under test and none needs pasting after GREEN.

**6. [Process] Commits were made directly on `master`** as instructed (main tree, no worktree, `git.branching_strategy: none`); the generic "refuse to commit on a protected branch" assertion of the executor protocol does not apply to that instruction. The per-plan commit ledger `gsd-plan-head-before-16-54` was written before the first commit.

No Rule 1-3 auto-fixes were needed beyond a type-checker rename (a loop variable reused with another type in `_apply_terminal`, fixed before the GREEN commit).

**Total deviations:** 6 recorded choices, 0 auto-fixed bugs, no scope creep. Hard limits respected: nothing under `src/backtest`, `src/paper`, `src/risk`, `src/core`, `src/adapters`, `src/ops`, `src/data/sufficiency.py`, `src/data/coverage.py`, `params/`, `config/`, `tests/fixtures/`, `docs/`; `pyproject.toml` and `uv.lock` unchanged; no manifest, authorization or grid file written; no real REEFUSDT value (the tests use the synthetic symbols `DELISTUSDT` and `GONEUSDT`, the synthetic terminal 2026-03-04T09:00Z and the synthetic URL `https://www.binance.com/synthetic/test-only-terminal-notice`, never fetched; the host-list rejection case uses `example.invalid`); no float; no pre-existing test assertion edited.

## Doc items for their owners

No document was edited by this plan.

| File | Line | Proposed sentence | Owner |
|------|------|-------------------|-------|
| `docs/architecture/DATA_PIPELINE.md` | 185 (the sentence "A caller may pass `allow_gaps` entries equal to real gaps; those are recorded on the output.") | Append: "A research manifest does not list gaps by range: it declares, per symbol, that the symbol's data ends (`DELISTED_CAPPED`, a UTC terminal instant and an official source URL on `www.binance.com`, all inside the manifest hash). The builder (`terminal_declarations`) then accepts only the trailing holes of that symbol that run to exactly the window end, start on the series cadence at or after the terminal instant, have no data after the gap start, and carry the `missing` count recomputed from the files; an interior hole, a hole with data after it, or a hole whose count or start disagrees with the data stays unresolved and `CaseInputGapError` names the failed condition." The earlier sentence "entries equal to real gaps" then describes only the direct `allow_gaps` path. | architecture doc owner |
| `docs/DECISIONS.md` | D049 item (h) (row at line 53) or a new decision row | Addendum: "(h2) Manifest known gaps (plan 16-54, KG-1 to KG-4, user decisions of 2026-10-13): a manifest known gap is a per-symbol terminal declaration with the single reason DELISTED_CAPPED, a UTC terminal instant and an https source on www.binance.com, inside the manifest hash; GapRange is unchanged; the builder accepts it by data geometry, never for an interior hole; a hole not explained by a valid declaration is refused; no manifest version key." | decisions owner |
| `docs/DOC_STATUS.md` | change log (line 49 onward) | "2026-10-13 - DATA_PIPELINE.md section Building backtest inputs and DECISIONS.md D049 (h2): terminal declaration for manifest known gaps (plan 16-54)." | status owner |
| `docs/research/RESEARCH_PROTOCOL.md` | none | No change. Lines 39, 77, 137, 338-343 and 428 were re-read: none defines the manifest key set or the shape of an allowed gap; line 137 ("an explicit allowed-gap list, which is recorded on the output") stays true because the reason reaches a record only through the manifest hash it already carries (`data_manifest_hash`, route B) and is not added to the output. FROZEN v2.2.0 (L-15). | protocol owner |

## Threat model dispositions

| Threat | Disposition | Evidence |
|--------|-------------|----------|
| T-16-127 (a terminal reason covering an unexplained hole) | mitigated | interior-gap, stated-after, observation-at-or-after, wrong `missing`, data-after tests; five mutation checks |
| T-16-128 (fields edited without a new hash) | mitigated | `test_the_hash_binds_the_terminal_fields`, the literal canonical pins |
| T-16-129 (false terminal claim with an invented source) | accepted, residual | nothing is fetched; the real terminal instant and URL are the user's O-03b answer, re-verified by a human; `DELISTED_CAPPED` in the sufficiency report is a second, data-derived signal |
| T-16-130 (duplicate declarations) | mitigated | loader refuses two declarations per symbol (`more than one`); builder refuses the same (`one per symbol`) |
| T-16-131 (reason leaking into the case input or record) | mitigated | exported `allowed_gaps` rows keep exactly five keys, `parse_case_input` accepts them, the reason and the host do not appear in the case input; no file under `src/backtest` changed |
| T-16-132 (credentials in a source URL) | mitigated | the loader refuses user information, whitespace, a non-https scheme and any host outside the list; refusal messages never echo the value (tested with `secret` and `example.invalid`) |

## Points for the next plans

- **16-37 Task 3** must write the manifest in this shape: `known_gaps` is a list of `{symbol, reason, terminal_at_utc, source_url}` objects, no version key, and its `--build` command must produce the declaration. The real REEFUSDT `terminal_at_utc` (expected 2025-01-22T09:00:00Z by the local data, unproven) and the exact URL stay the user's O-03b answer; the known-gaps part of that answer takes this form.
- The open-position `FundingCoverageError` question for a symbol whose funding ends before the window end is NOT answered here (separate diagnostic, still open); no forced close and no loosening of funding coverage was added.
- A run-report line grouping known gaps by reason is not planned.
- `open_interest` is not requested by the runner; the geometry rule is generic over the series spec and was not exercised on that series.

## Open questions for the user

1. **Field naming:** KG-4 lists "terminal_at_utc, the exact source URL and the cause"; KG-1 calls the one value a "reason". The implementation has a single required field `reason` that carries `DELISTED_CAPPED` (the sufficiency-report cause word). If a separate `cause` field was intended, it is a new manifest shape and must be decided before 16-37 Task 3 freezes anything.
2. **Funding with fewer than two rows** (cadence rule): no new rule was invented. The cadence used for the geometry is the one the builder already infers for gap detection (`infer_funding_cadence_ms`: no or one observation defaults to 8h, so an empty window gets the label `8h` and the count `window length / 8h`); the geometry check recomputes with that same step, so it cannot disagree with detection. The empty-window case is tested (`8h`); a window with exactly one funding row is not tested separately.

## Known Stubs

None.

## Threat Flags

None. The only new surface is a source URL string in the manifest that is never fetched.

## Self-Check: PASSED

- FOUND: `tests/test_research_known_gap_reason.py`, `src/data/case_input.py`, `src/research/manifest.py`, `src/research/run.py`
- FOUND commits: `7a72b59`, `8bc1485`, `62d379d`
- `git rev-list --count 61e3be0..HEAD` = 3 at SUMMARY time (matches `commits: 3`)
- LF-only blobs verified through `git show HEAD:<path>` in the plan's verify command (`crlf-in-blob: []`)
