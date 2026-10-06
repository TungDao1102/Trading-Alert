---
phase: 15-strategy-geometry-correction
plan: 15
subsystem: research-readiness
tags: [readiness, geometry-audit, d054, decisions, regeneration-inventory, smoke, census]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "15-08 ratified baseline-v6 sets, 15-09 -v4 baselines, 15-07 geometry census, 15-13 universal validator, 15-14 sheet records, all 15-xx regeneration inventories"
provides:
  - "scripts/smoke_backtest_realdata.py defaults --parameter-set-id to baseline-v6"
  - "docs/research/GEOMETRY_AUDIT.md final: no PARAMETER verdict, every FIX row names its implementing function, and a 'Re-run readiness (criterion 4)' section with real smoke digests and census counts per family"
  - "docs/DECISIONS.md D054 directly after D053: audit outcome, kept deviations, sheet-text basis, provenance, new keys and sets, compiled regeneration inventory, protocol answer, limitations, readiness"
  - "Doc and table-order tests for the audit and for D054"
affects: []

actuals:
  tokens: 20800
  tasks: 3
  commits: 3
plan_head_before: 2a679b2a13f5a5d8c9b073909e5489298b08347e
plan_head_after: 3c31af7e136a0e81376617edac49c5744e96bc1a

key-files:
  modified:
    - scripts/smoke_backtest_realdata.py
    - docs/research/GEOMETRY_AUDIT.md
    - docs/DECISIONS.md
    - tests/test_geometry_audit_doc.py
    - tests/test_decision_alignment_bookkeeping.py
    - tests/test_kill_gate_docs.py
    - .planning/ROADMAP.md

key-decisions:
  - "Readiness is verified, not asserted: three families, two Phase-14 engine runs each on 30 days and on 90 days, equal digests, census invariant_violations 0"
  - "No amendment of RESEARCH_PROTOCOL v2.0.0 is needed (it governs method; its migration paragraph already names the Phase 15 sets as the evidence-bearing lineage)"
  - "No parameter value was chosen or changed from smoke or census results (D-17)"

requirements-completed: [STRAT-01, STRAT-02]

duration: ~2h (three concurrent 90-day smoke runs dominated wall time)
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 15: Re-run readiness, final geometry audit and D054 Summary

**All three baseline-v6 sets run on the Phase-14 engine twice with equal digests and zero geometry invariant violations (30-day and 90-day BTCUSDT windows), the geometry audit is final with no PARAMETER verdict left, and D054 records the whole phase once with the compiled regeneration inventory.**

## Accomplishments

- Task 1 (tracer, e019701): `scripts/smoke_backtest_realdata.py` now defaults `--parameter-set-id` to `baseline-v6`. trend-pullback ran on 30 days to 2026-10-01 (two engine runs, exit 0, `digests_match=true`) and the census on the same set reported `invariant_violations: 0`. The F8 definition and the first readiness row were written before any expansion. `tests/test_smoke_backtest_cli.py` and `tests/test_geometry_census.py`: 46 passed.
- Task 2 (de1014f): the same commands for breakout-retest and range-mr; the PARAMETER row (B breakout) became MATCH at the ratified value 1 (basis STRUCTURAL, sheet B1); the eight FIX rows name their implementing functions; the seven DEVIATION rows all cite D054; the readiness section was completed with the protocol answer, what a re-run still needs and the PLACEHOLDER note. `tests/test_geometry_audit_doc.py` gained four tests (no PARAMETER row and B breakout MATCH, DEVIATION rows cite D054, each FIX row names a function that exists in `src/core`, one digest row per family with `invariant_violations 0`).
- Task 3 (3c31af7): D054 added directly after D053, plus `test_real_table_reaches_d054` and `test_d054_geometry_row_present`, the ROADMAP pointer line and the supplementary 90-day rows of the audit.

## Readiness evidence

Inputs: local `data/raw`, BTCUSDT, windows ending 2026-10-01, equity 1000, risk rate 0.005, constraint row from 14-14-SUMMARY (tick 0.10, step 0.001, min_qty 0.001, min_notional 50, observed 2026-10-05T08:18:37+00:00) as a JSON file in the session scratchpad (not in the repo; no database, no network). The row is back-extrapolated (D-30): valid as plumbing and invariant evidence, not as strategy evaluation. No count below is strategy performance and no value was changed because of it (D-17).

Smoke command per family: `.venv/Scripts/python scripts/smoke_backtest_realdata.py --symbol BTCUSDT --days 30 --end-day 2026-10-01 --strategy-id <family> --parameter-set-id baseline-v6 --constraints-json <scratch file>`. Every run printed `digests_match=true` and exited 0.

| Family | Window | Runtime run 1 / run 2 (s) | Digest (both runs equal) | trade_count | no_trade_counts |
|---|---|---|---|---|---|
| trend-pullback | 30 days | 123.118 / 78.919 | 52ae9d503a3ab28f5da96e765ee13550c67d7794c30ded9e2f09dd7a1badb5c3 | 0 | {"NO_TRADE_REGIME":3,"WARMUP_INSUFFICIENT":717} |
| breakout-retest | 30 days | 112.442 / 71.883 | cc5629fd6d2e6488206aa7345b1da46bf0e878fe683aa09756f49d3e297f0aef | 0 | {"NO_TRADE_REGIME":3,"WARMUP_INSUFFICIENT":717} |
| range-mr | 30 days | 113.386 / 71.873 | dea333ac3e3f0e9fb167e0ae4e9975cdfd5828a93939ddd9fed98e9e8fb04cde | 0 | {"NO_TRADE_REGIME":3,"WARMUP_INSUFFICIENT":717} |
| trend-pullback | 90 days | 593.514 / 543.265 | 9473c7954fe44ec12924296713a466574575d3f39ff20a51e85cfd0888ab5f66 | 174 | {"CONFLICT_WITH_OPEN_POSITION":79,"COST_TO_RISK_EXCEEDED":88,"NO_TRADE_REGIME":1111,"RR_TOO_LOW":40,"STALE_SETUP":1,"STOP_TOO_TIGHT":15,"WARMUP_INSUFFICIENT":796} |
| breakout-retest | 90 days | 678.508 / 551.333 | de9cc44f53479351baef90f00508e3601a2d81f364c859bd936b395a99a8d034 | 34 | {"CONFLICT_WITH_OPEN_POSITION":2,"COST_TO_RISK_EXCEEDED":25,"NO_TRADE_REGIME":1328,"STOP_TOO_TIGHT":2,"WARMUP_INSUFFICIENT":796} |
| range-mr | 90 days | 578.400 / 524.868 | 6b7251a45262da10e925f3db2224078921819ff3ed2a5042de373e0db8e98723 | 39 | {"COST_TO_RISK_EXCEEDED":27,"NO_TRADE_REGIME":1325,"RR_TOO_LOW":7,"STOP_TOO_TIGHT":5,"WARMUP_INSUFFICIENT":796} |

The 30-day and 90-day windows share `dataset_id` 3ba0132e... and 2063b8ca... respectively across families. Every `no_trade_counts` key was checked programmatically against `RejectionReason` plus the feature-layer codes plus the engine counter `CONFLICT_WITH_OPEN_POSITION` (see Deviations, item 1). The 90-day runs ran three at a time, so their runtimes are not comparable with 14-14. The 30-day window cannot fill the 1000-bar strategy window (717 of 720 bars are `WARMUP_INSUFFICIENT`), which is why the 90-day runs were added: they put 174, 34 and 39 simulated trades through the engine.

Census command per family: `.venv/Scripts/python scripts/geometry_census.py --strategy-id <family> --parameter-set-id baseline-v6 --symbols BTCUSDT --days 30 --end-day 2026-10-01` (exit 0 each). Total line, trend-pullback: `"guard_other": {}, "guard_pass": 54, "guard_reject": {"COST_TO_RISK_EXCEEDED": 68, "STOP_TOO_TIGHT": 1}, "invariant_violations": 0, "parameter_set_hash": "2c4f1528b00f1b1e48c76040bbd6cc218a25eec21c521d8b68da86ee4811360f", "plans": 123, "setups": 148`.

| Family | setups | plans | planner NO_TRADE | guard reject | guard pass | invariant_violations |
|---|---|---|---|---|---|---|
| trend-pullback | 148 | 123 | RR_TOO_LOW 24, STALE_SETUP 1 | COST_TO_RISK_EXCEEDED 68, STOP_TOO_TIGHT 1 | 54 | 0 |
| breakout-retest | 20 | 20 | none | COST_TO_RISK_EXCEEDED 16, STOP_TOO_TIGHT 1 | 3 | 0 |
| range-mr | 19 | 14 | RR_TOO_LOW 5 | COST_TO_RISK_EXCEEDED 12, STOP_TOO_TIGHT 2 | 0 | 0 |

These equal the BTCUSDT rows of the 15-08 post-ratification census. The property test (`tests/test_geometry_property.py`, 25 passed) is green.

## Regeneration inventory

Compiled once in D054 item (e) (`docs/DECISIONS.md`, row `| D054 |`), from the 15-01..15-14 SUMMARY inventories and git: five new pins in `tests/fixtures/phase4/parameters.json` (20 to 25 entries), the Phase 4 signal ids, trade plan ids, plan hashes and blob hashes, nine Phase 6 fixture inputs and the Phase 7 parity input with their old and new simulator digests, the parity digest and parameter_set_hash, the three family sheet sha256 values before and after, and the NOT MOVED list. This plan itself moved no fixture, pin or hash.

## Task Commits

1. Task 1 (tracer): `e019701` smoke default baseline-v6 and the trend-pullback readiness row
2. Task 2: `de1014f` final audit verdicts, three-family readiness rows, doc tests
3. Task 3: `3c31af7` D054 row, order tests, ROADMAP pointer, supplementary 90-day rows

## Deviations from Plan

**1. [Rule 1 - Plan wording] The F8 allowed-code set had to name one more code**
- **Found during:** the 90-day runs (Task 3).
- **Issue:** the plan text says every `no_trade_counts` key must be a `RejectionReason` value or a feature-layer code. The engine also reports `CONFLICT_WITH_OPEN_POSITION` (D-32, `semantics.NO_TRADE_CONFLICT`), which is deliberately not a `RejectionReason`; it appears on the 90-day trend-pullback (79), and breakout-retest (2) runs.
- **Fix:** the F8 definition in `GEOMETRY_AUDIT.md` names it as the engine's one documented counter, and D054 item (h) says so. No code changed.
- **Commit:** 3c31af7.

**2. [Rule 1 - Source discrepancy] 15-11-SUMMARY swapped two blob-hash labels**
- **Found during:** compiling the D054 inventory.
- **Issue:** the 15-11 SUMMARY lists the old blob hash of `expected_signals.json` as `a55a7024...` and of `expected_plans.json` as `34ebf3f5...`. `git rev-parse <15fbaf8>^:<path>` gives the opposite: expected_signals.json 34ebf3f5... and expected_plans.json a55a7024... (new values 212f56a6... and d7547c8a... agree).
- **Fix:** D054 uses the git values and says the SUMMARY printed them swapped. The 15-11 SUMMARY itself was not edited.
- **Commit:** 3c31af7.

**3. [Addition, no plan item] 90-day supplementary smoke**
- The plan specifies 30 days. Because a 30-day window leaves 717 of 720 bars at `WARMUP_INSUFFICIENT`, it proves plumbing and determinism but drives no plan through the simulator. The same commands with `--days 90` were run as a supplement and recorded beside the 30-day rows; the plan's required rows are unchanged.

**4. [Test shape] The doc test compares function names against `src/core` rather than a free-form check**
- Each FIX row's resolution must name the function listed in the plan, and the test also asserts `def <name>(` exists in `src/core`. Stricter than the plan's "names a function".

No auth gates, no package installs, no architectural changes.

## Issues and observations carried in D054 (not fixed here)

- TP1 inside the far half of the entry zone is not rejected (15-04 observation); a one-line tightening in `_geometry_rejection` if the user wants it.
- The docstring of `src/risk/gating.py` `_plan_geometry_is_valid` is stale (says a stop inside the zone is deliberately not rejected); not edited here.
- The planner has no tick size; a stop within one tick of the zone edge relies on `sl_buffer_atr` x ATR.
- The three -v4 override values carry basis DECISION ref D054 as ratified at 15-08; the checkpoint text gave no separate basis (flagged by 15-08).
- PostgreSQL tests (19 files skipped without `TEST_DATABASE_URL`, 20 of the 22 `test_plan_hash_roundtrip_pg.py` tests) and the Docker/bootstrap tests (`test_bootstrap`, `test_deploy_backup_scripts`, `test_docker_backup_drill`, `test_docker_backup_remote`, `test_docker_cutover`, `test_docker_image`; Git Bash hang) were not run locally; CI confirms. `.env` was not read.
- Research re-run itself: out of scope. What it still needs is listed in the audit readiness section and D054 item (h): candidate-set freeze step, data window and split, universe research-universe-v1 (12 symbols), unmeasured trade-floor reachability (never lowered), point-in-time constraints, and the PLACEHOLDER values that keep baseline-v6 out of paper freezing.

## Verification

- Plan-named tests: `tests/test_smoke_backtest_cli.py tests/test_geometry_census.py` (46 passed); `tests/test_geometry_audit_doc.py` plus the authority, exchange and protocol decision-alignment files (174 passed); `tests/test_decision_alignment_bookkeeping.py tests/test_kill_gate_docs.py tests/test_decision_alignment_protocol.py tests/test_geometry_audit_doc.py` (100 passed); `python -m scripts.decision_alignment.params` PA-01..PA-08 ok.
- File-by-file sweep over 194 files (6 excluded Git Bash hang files): 4393 passed, 0 failed, 430 skipped (previous 15-13 figure 4387 plus the 6 new tests). One file, `test_decision_alignment_bookkeeping.py`, failed inside the sweep only because the sweep reached it before the D054 row was committed; re-run after the commit: 46 passed.
- `ruff check src tests scripts`, `ruff format --check src tests scripts` (388 files) and `mypy src` (149 files): clean.

## Known Stubs

None. No stub, placeholder text or empty data path was added by this plan.

## Threat Flags

None. The plan adds no endpoint, auth path or file access beyond a read-only local run; the constraints JSON lives in the scratchpad, not in the repository.

## Self-Check: PASSED

- FOUND: scripts/smoke_backtest_realdata.py (`default="baseline-v6"` present), docs/research/GEOMETRY_AUDIT.md ("Re-run readiness (criterion 4)"), docs/DECISIONS.md (`| D054 |` on the line after `| D053 |`), tests/test_geometry_audit_doc.py, tests/test_decision_alignment_bookkeeping.py, tests/test_kill_gate_docs.py, .planning/ROADMAP.md ("Readiness evidence")
- FOUND commits: e019701, de1014f, 3c31af7
- `grep -c "| PARAMETER |" docs/research/GEOMETRY_AUDIT.md` prints 0
