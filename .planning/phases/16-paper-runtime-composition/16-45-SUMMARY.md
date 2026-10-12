---
phase: 16-paper-runtime-composition
plan: 45
subsystem: research preregistration (closure-chain step O-02, L-10)
tags: [hypothesis, parameter-grid, preregistration, registered, o-02]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plans 16-40 (runtime and SHADOW chain proven) and 16-13 (src/research/register.py candidate validator)"
provides:
  - "docs/research/preregistration/research-run-1-hypothesis.md: the approved hypothesis (approve-with-changes, 16-DEC-O-02); the DRAFT file is kept unchanged as history"
  - "docs/research/preregistration/research-run-1-grid-{trend-pullback,breakout-retest,range-mr}.json: three preregistered ParameterGrid files, 16 points each"
  - "params/<family>/research-run-1-<a|b|c><01..16>.toml: 48 immutable, rationalized, PLACEHOLDER-free parameter sets, each pinned in tests/fixtures/phase4/parameters.json"
affects: [16-46 (research run; needs a separate O-03 user authorization AND the cross-family multiplicity blocker resolved)]

requirements-completed: []

status: Tasks 1-3 done, preregistration registered, NOT authorized to run; blocker: cross-family multiplicity
actuals:
  tokens: 180000
  tasks: 3
  commits: 8
plan_head_before: 0501acd6bd75249e1e6b0754e92e3494fc7bb7a5
plan_head_after: 3f8a843b3190feab3916e90646efb55d29319880
commits: 8

tech-stack:
  added: []
  patterns:
    - "One ParameterGrid file per family: a grid binds one strategy_id and the runner loads every point under it"
    - "strategy_version stays v5.0.0 for parameter-only variants of the baseline-v6 code and geometry"

key-files:
  created:
    - docs/research/preregistration/research-run-1-hypothesis.md
    - docs/research/preregistration/research-run-1-grid-trend-pullback.json
    - docs/research/preregistration/research-run-1-grid-breakout-retest.json
    - docs/research/preregistration/research-run-1-grid-range-mr.json
    - params/trend-pullback/research-run-1-a01.toml (to a16; 16 files)
    - params/breakout-retest/research-run-1-b01.toml (to b16; 16 files)
    - params/range-mr/research-run-1-c01.toml (to c16; 16 files)
    - tests/test_research_run1_registration.py
  modified:
    - tests/fixtures/phase4/parameters.json (48 pin entries added, no existing entry changed)
    - tests/test_registry.py
    - tests/test_rationale.py
    - tests/test_decision_alignment_params.py
    - tests/test_analytics_files.py

key-decisions:
  - "Scope per O-02: all three families, 16-point 2x2x2x2 grid each (48 points); max_cost_to_risk 0.15 fixed; signal_expiry_hours {4, 8}; constraint_snapshot_ttl_seconds 2400 (DECISION, O-07)"
  - "strategy_version stays v5.0.0: same code and geometry as baseline-v6, the points differ in parameter values only"
  - "Approval and registration are not an authorization to run research; cross-family multiplicity must be resolved first"

patterns-established: []

requirements: [PAPER-01]
---

# Phase 16 Plan 45: Hypothesis and parameter grid Summary

Status: Tasks 1-3 done, preregistration registered, NOT authorized to run; blocker: cross-family multiplicity. No requirement is complete: `requirements-completed` is empty.

The user decided O-02 as approve-with-changes (`decisions/16-DEC-O-02.md`, 2026-10-12). Task 3 registered the approved preregistration: the approved hypothesis, three grid files, 48 new immutable parameter sets and their pins. Nothing was run: no simulator, no research run, no holdout read, no network, no `.env` read. Approval is not an authorization to run research.

Plan base (HEAD before Task 1): `0501acd6bd75249e1e6b0754e92e3494fc7bb7a5`.

## Commits (this plan)

| Commit | What |
|---|---|
| `e9eb307` | Task 1: agent DRAFT of the hypothesis and grid (kept unchanged as history) |
| `37ab452` | Task 1: summary of the tracer |
| `d171a3c` | Task 2: user decision O-02 approve-with-changes (recorded by the orchestrator) |
| `e98d147` | Task 3 RED: `tests/test_research_run1_registration.py` (28 tests, failing: artifacts absent) |
| `bcdc19a` | Task 3: approved hypothesis `research-run-1-hypothesis.md` |
| `3f8a843` | Task 3 GREEN: 3 grid files, 48 sets, 48 pins, knock-on test updates |

The frontmatter `commits: 8` is the measured `git rev-list --count 0501acd..3f8a843`; two of the eight (`f7c94e1`, `f2ea782`) are 16-50 docs commits made on the same branch meanwhile and are not part of this plan, so the plan's own commits before this summary are the six above.

## What was registered

- **Hypothesis** `docs/research/preregistration/research-run-1-hypothesis.md`: no DRAFT line; states the approval by the user per `decisions/16-DEC-O-02.md` with the date 2026-10-12 and that the approval is not an authorization to run research. It states the expiry semantics (plan expiry = source close + `signal_expiry_hours`; the CONFIRM card TTL of D041, 60 s default and configurable, is distinct from plan expiry and from reservation, Q-C; CONFIRM neither revives an expired plan nor restarts its clock; a reservation never outlives the original plan expiry), the `constraint_snapshot_ttl_seconds` 2400 nuance (changes the parameter-set hash only; the simulator uses `timedelta(0)` at `src/backtest/engine.py:755`, the paper runtime takes the TTL from the runtime configuration at `src/paper/runtime.py:830`; the simulator does not apply 2400) and a Blockers section. `RESEARCH_PROTOCOL.md` was not edited.
- **Grids** (one per family; see Deviations): `grid_hash` values

| Family | Grid file | grid hash |
|---|---|---|
| trend-pullback | `docs/research/preregistration/research-run-1-grid-trend-pullback.json` | `13207b306df9a2bc1d580df456b1e6a3d3478eff82c5eb1ff6ac6a9daac14411` |
| breakout-retest | `docs/research/preregistration/research-run-1-grid-breakout-retest.json` | `2ed8577ea225b294eaaa82c4478fee6dbf2b3d5a76eca8f967b5d769171c4069` |
| range-mr | `docs/research/preregistration/research-run-1-grid-range-mr.json` | `3388fceb664ba7999477070ef9d49f15ccff0b073d3587ad58351dd5c5d297c6` |

- **New set ids (48):** `trend-pullback/research-run-1-a01..a16`, `breakout-retest/research-run-1-b01..b16`, `range-mr/research-run-1-c01..c16`. Point 01 of each family is described in its file and in the hypothesis as "Matches the baseline-v6 seed values except for `constraint_snapshot_ttl_seconds`." (verified by test). Varied axes: A pivot width (3, 5; left = right), `zone_tolerance_atr` (0.5, 1.0), `sl_buffer_atr` (0.2, 0.5), `signal_expiry_hours` (4, 8); B `retest_window_bars` (5, 10), `retest_depth_atr` (0.3, 0.6), `zone_tolerance_atr` (0.5, 1.0), `signal_expiry_hours` (4, 8); C `regime_filter_lookback` (50, 100), `zone_min_touches` (2, 3), `range_break_buffer_atr` (0.2, 0.5), `signal_expiry_hours` (4, 8). The per-point loader hashes are in the grid files and the pin file.
- **Labels:** the draft's labels, with the single change `constraint_snapshot_ttl_seconds` 2400 DECISION (O-07). No PLACEHOLDER label anywhere.

## Verification (exact outputs)

- `python -m src.research.register --list-grid --grid <each of the three grid files>`: 16 lines `STRUCTURALLY_VALID` per file, 0 `STRUCTURALLY_INVALID`.
- `tests/test_registry_gate.py tests/test_paper_start_gate.py tests/test_research_register.py`: 102 passed.
- `tests/test_research_run1_registration.py` (new, TDD): RED at `e98d147` (failing before the artifacts existed); GREEN: 28 passed.
- Knock-on files that enumerate `params/` or the pin file (`tests/test_registry.py`, `test_rationale.py`, `test_decision_alignment_params.py`, `test_analytics_files.py`, `test_fixture_harness.py`, `test_planner_geometry.py`, `test_phase6_fixture_geometry.py`, `test_kill_gate_families.py`): 616 passed, 1 skipped.
- The registry-gate negative-test list not already covered (`test_kill_gate_docs.py`, `test_kill_gate_clock.py`, `test_research_gate_negative.py`, `test_decision_alignment*.py`): 424 passed.
- `scripts/verify_decision_alignment.py all`: ALL_PASS.
- `git diff --name-only --diff-filter=MDR 0501acd6bd75249e1e6b0754e92e3494fc7bb7a5 -- params/`: empty (only added files under `params/`).
- `ruff check` and `ruff format --check` on the five test files touched: clean. The full suite was not run.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] One grid file per family instead of one `research-run-1-grid.json`**
- **Found during:** Task 3
- **Issue:** `ParameterGrid` has a single `strategy_id`; `load_grid` rejects other keys, `register._point_structure`/`_matching_points` and the runner (`src/research/run.py`) resolve every point under that one id. A single grid for three families cannot be expressed in the format, and a non-grid file with the planned name would fail the plan's own `--list-grid` check.
- **Fix:** three grid files `research-run-1-grid-<family>.json`; the hypothesis section 7 lists them with their hashes.
- **Commit:** `3f8a843`

**2. [Rule 3 - Blocking] Tests that enumerate `params/` or the pin file extended**
- **Found during:** Task 3 verification
- **Issue:** adding sets broke five existing assertions: the pin count in `tests/test_decision_alignment_params.py` (25), the exact pin key set in the same file, the Phase 15 geometry-key whitelist in `tests/test_registry.py`, the "has a rationale only if Phase 15" assertion in `tests/test_rationale.py`, and the expected candidate hashes per family in `tests/test_analytics_files.py`.
- **Fix:** each assertion now includes the 48 research-run-1 ids (73 pins). No assertion was weakened for any other set.
- **Commit:** `3f8a843`

**3. [Registry rule] DECISION ref for the O-07 TTL is `D063`**
- **Found during:** Task 3
- **Issue:** `src/domain/rationale.py` requires the `ref` of a DECISION label to be of the form `D<3 digits>`; O-07 is a phase decision record and no DECISIONS.md row carries the value 2400.
- **Fix:** label DECISION as instructed; `ref = "D063"` (item 1 of D063 makes O-07 a user-owned ratification) and the rationale text names "O-07" and `decisions/16-DEC-O-07.md`. No value changed. If a DECISIONS.md row for the 2400 is wanted, that is a separate user decision; the registered set files must not be edited to cite it.

### strategy_version question (settled)

`strategy_version` stays `v5.0.0` for all 48 sets: the strategy code and geometry are those of `baseline-v6`, the grid points differ in parameter values only (the precedent is `baseline-no-trade-v4` and `baseline-simple-trend-v4` at the same version), and the TTL change does not change behaviour (hash only). A lineage (protocol holdout marker) is `strategy_id` plus `strategy_version`, so one lineage per family covers its 16 points.

### Family C structural-rule question (settled, no problem found)

The registry rules `pivot_right_bars + 1 <= swing_lookback` and `pivot_right_bars + 1 <= regime_filter_lookback` hold for every point (4 <= 20, 4 <= 50 and 4 <= 100); `zone_aging_bars` has no registry range rule (the detector needs 71 setup bars of warm-up, a runtime fact). All 16 Family C points load and are STRUCTURALLY_VALID. No draft combination was invalid and no value was changed.

## Remaining blockers (nothing may proceed past registration)

1. **Cross-family multiplicity** (`RESEARCH_PROTOCOL.md` line ~250: Holm per family only, about 14% worst-case across three families): needs a user decision or a protocol amendment before O-03 and before any research execution. "At least one family PASSES" is not an overall confirmation.
2. **O-03 authorization** is a separate user command for every real run (dataset window, universe, split dates, manifest, constraint source, feasibility). The holdout must not be read or consumed in the feasibility gate.
3. **`constraint_snapshot_ttl_seconds` is not wired into the simulator**; wiring it needs its own decision and plan (semantics and digest review).
4. Variant budget headroom: the registry now holds 22 (trend-pullback), 22 (breakout-retest) and 21 (range-mr) non-baseline candidate sets per family (older `baseline-v1..v6` plus 16 new); the protocol budget of 25 counts variants evaluated, and the grid evaluates 16 per family. Registering more candidate sets later needs care.

## Known Stubs

None.

## Threat Flags

None. No network, auth or schema surface added. T-16-101 (values from results or tuned): mitigated, the grid was drafted before any result, approved by the user, and registered hash-locked and pinned. T-16-102 (committed set edited in place): mitigated, the `params/` diff against the plan base shows only added files.

## Self-Check: PASSED

- 48 set files, 3 grid files, the hypothesis, the new test file and the 48 pin entries exist; commits `e98d147`, `bcdc19a`, `3f8a843` exist; the checks above pass.
- Not done by design: ROADMAP.md and STATE.md updates, any research run, any authorization of one.
