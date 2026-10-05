---
phase: 14-backtest-causality-rewrite
plan: 16
subsystem: research-governance
tags: [research-protocol, decisions, amendment, void-evidence, regeneration-inventory, gate-code, tdd, docs]

requires:
  - phase: 14-backtest-causality-rewrite
    provides: "14-01..14-15: the v2 engine, funding, ledger, goldens, typed experiment record and evidence schema whose semantics this plan freezes in the protocol"
provides:
  - "docs/research/RESEARCH_PROTOCOL.md v2.0.0 (Frozen on 2026-09-19 unchanged, Amended on 2026-10-05, Supersedes v1.1.0, Migration paragraph, amendment-log entry, sections 2, 3 and 6 amended)"
  - "DECISIONS D052 (protocol v2.0.0 frozen; lifecycle, fill, exit ladder, funding, ledger, R, void evidence, evidence-store check) and D053 (Phase 14 regeneration inventory)"
  - "Header-driven version pins: scripts/decision_alignment/protocol.py (PR-08), bookkeeping.py (DC-03) and the version-bound tests read the protocol header instead of a literal"
  - "BACKTEST_SPEC, RISK_MANAGEMENT section 3 and 8, SOURCES (funding FAQ fact) describing the v2 semantics"
  - "VOID (Phase 14, D052) markers on Phase 6 evidence, REQUIREMENTS and ROADMAP; BKTS-01 re-verification evidence listed by test module"
affects: [15-strategy-geometry-research-runner, 26-go-live-readiness-gate]

requirements-completed: [BKTS-01, BKTS-02, DOMN-03, BKTS-04]

actuals:
  tokens: 28000
  tasks: 3
  commits: 5
plan_head_before: 9390ec87b64fd06c2b11592cb8d27012d21a58b1
plan_head_after: 5ae5ef839b7f76fd6f81f57bda31215e010711cf

tech-stack:
  added: []
  patterns:
    - "Version witnesses (header = DECISIONS 'protocol vX.Y.Z frozen' row = DOC_STATUS index line) are read from the header in gate code and tests, so an amendment cannot leave a stale literal"
    - "Void-not-delete: evidence is marked with a 'VOID (Phase N, Dxxx):' blockquote and the old text stays"

key-files:
  created: []
  modified:
    - docs/research/RESEARCH_PROTOCOL.md
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/backtest/BACKTEST_SPEC.md
    - docs/trading/RISK_MANAGEMENT.md
    - docs/SOURCES.md
    - docs/research/holdout_consumed.json
    - scripts/decision_alignment/protocol.py
    - scripts/decision_alignment/bookkeeping.py
    - tests/test_kill_gate_docs.py
    - tests/test_decision_alignment_protocol.py
    - tests/test_decision_alignment_bookkeeping.py
    - tests/test_research_gate_negative.py
    - .planning/ROADMAP.md
    - .planning/REQUIREMENTS.md
    - .planning/phases/06-backtest-simulator-experiment-registry/06-VERIFICATION.md
    - .planning/phases/06-backtest-simulator-experiment-registry/06-01-SUMMARY.md
    - .planning/phases/06-backtest-simulator-experiment-registry/06-03-SUMMARY.md
    - .planning/phases/14-backtest-causality-rewrite/deferred-items.md

key-decisions:
  - "Protocol amended to v2.0.0 (D052) by the D032/D043 procedure: Frozen on unchanged so the D013 clock is not restarted; thresholds, splits, kill-gate rule, identity tuple and the Quantization block untouched; v1.1.0 text preserved in git at 7a80af52146d7a8112cab3536143c179050a02d2"
  - "D052 records the paper-parity choice: the parity fixture is a single-signal history on which the engine ledger never binds; multi-signal histories diverge from paper by design (paper has no ledger)"
  - "D052 records, without deciding, two open items: modeled_costs_per_unit is None on v2 filled records, and no runner calls read_code_version plus assemble outside tests (both owed to the Phase 15 runner)"
  - "REQUIREMENTS traceability status cells stay exactly 'Complete' (the RQ-02/RQ-03 gates parse them); the void note sits on the checkbox rows and in one traceability note under the table"

patterns-established:
  - "DC-03 binds both the historic D043 row and the row of the current header version"

duration: about 1.5 h (start time was not captured)
completed: 2026-10-05
status: complete
---

# Phase 14 Plan 16: Protocol v2.0.0, D052/D053 and Void Evidence Summary

**The frozen research protocol is amended to v2.0.0 through the version-bound procedure, with D052 (the v2 simulator semantics and the void of all earlier backtest evidence) and D053 (every fixture, pin and hash that moved) recorded, the gate code and tests reading the version from the header, and Phase 6 evidence marked void without deleting anything.**

## Performance

- **Duration:** about 1.5 h (start time was not captured, estimate)
- **Completed:** 2026-10-05
- **Tasks:** 3 (Task 1 is the tracer)
- **Files modified:** 19 (18 in the five plan commits plus `deferred-items.md`)

## Accomplishments

- **Tracer, one commit (7af7a72):** protocol header v2.0.0 (`Frozen on` 2026-09-19 unchanged, `Amended on` 2026-10-05, `Supersedes` v1.1.0), `### Migration (v1.1.0 to v2.0.0)`, amendment-log entry, D052 directly after D051, DOC_STATUS index line and changelog, BACKTEST_SPEC pointer, `holdout_consumed.json` `protocol_version`, ROADMAP Phase 14 criterion 2 reworded to "until SL, TP2 or data end" (D-39). The research-gate freeze step, mirrored by the third `<automated>` verify, passes.
- **Header-driven pins:** `protocol.check_backtest_spec(text, protocol=None)` requires the BACKTEST_SPEC pointer to name the header version; `bookkeeping.check_decisions(..., protocol=None)` keeps asserting the D043 row and now also requires a row for the current header version (fails closed when the header has no version). `tests/test_kill_gate_docs.py`, `tests/test_decision_alignment_protocol.py`, `tests/test_decision_alignment_bookkeeping.py` and `tests/test_research_gate_negative.py` derive the version from the header; `Status`, `Frozen on` and `Supersedes v1.1.0` are asserted, `Amended on` must be a date.
- **Specs (dd2dd83):** protocol sections 2, 3 and 6 (funding sign and coverage, trade-through fills, mark-price triggers, TP ladder, stop-first, fill-minute rule, stop gap, fallback, expiry clock, CANDLE_CLOSE invalidation, DAILY_STOP, END_OF_DATA and PENDING_AT_DATA_END); BACKTEST_SPEC sections 2 to 6 and 11 (the v1 close-versus-open invalidation rule is recorded as replaced, D-35; the typed experiment-record fields are listed, D-22); RISK_MANAGEMENT section 3 (funding sign, open-quantity rule, included in net PnL and R, excluded from sizing) and section 8 (resting entries cancelled on DAILY_STOP, protective stops stay); SOURCES gains "Facts verified for Phase 14" with the Binance funding FAQ (id 360033525031, fetched 2026-10-04, MEDIUM, 15-second grace not modeled).
- **D053 and void markers (5ae5ef8):** D053 compiles the plan 14-01 to 14-15 SUMMARY inventories in the D048 style (cost_model_hash 3063dc39... to 6d6c4e23..., the phase 6 and phase 7 inputs, seven regression snapshot digests, report and render goldens, `analytics-evidence/2`, evidence sample, the NOT MOVED list). `VOID (Phase 14, D052):` notes on 06-VERIFICATION, 06-01 and 06-03 SUMMARY, the BKTS-01, BKTS-02 and DOMN-03 requirement rows plus a traceability note, and the ROADMAP Phase 6 line; Phase 15 criterion 4 now names protocol v2.0.0. No checkbox or status cell was flipped.

## Evidence-store check (2026-10-05, D-03)

- `docs/research/kill_gate_decisions.json`: `families` empty, `resets` empty, `recorded_terminal` null. No family decision cites old results.
- `docs/research/holdout_consumed.json`: `entries` empty (protocol_version now v2.0.0).
- `git ls-files` lists no experiment or backtest JSON, YAML, TOML, Parquet or CSV evidence file. The only evidence-shaped tracked file is `tests/fixtures/phase10/loaders/evidence_sample.json`, a synthetic sample regenerated by plan 14-15.
- `data/` is gitignored and holds `backup` and `raw` only; there is no `data/reports`.
- The three family sheets define metrics and gates but hold no results.
- Result: no record needed to be voided inside `docs/research` or the experiment store; the void is stated in D052 and marked in the Phase 6 artifacts, REQUIREMENTS and ROADMAP. This sentence is in D052.

## BKTS-01 re-verification evidence (by test module)

`tests/test_backtest_entry.py`, `tests/test_backtest_exits.py`, `tests/test_backtest_funding.py`, `tests/test_backtest_ledger.py`, `tests/test_backtest_expiry_clock.py`, `tests/test_backtest_goldens.py`, `tests/test_backtest_determinism.py`, `tests/test_backtest_chain.py`. All pass in the chunked run below. Listed in D052 and in the REQUIREMENTS rows.

## Gates and checks run (real results)

- `scripts/verify_decision_alignment.py all`: ALL_PASS (every PR, DC, RQ, GL, AU, EX, OR, UN, PA line PASS), after each of the three tasks.
- Version-bound set (`tests/test_kill_gate_docs.py`, `test_decision_alignment_protocol.py`, `test_decision_alignment_bookkeeping.py`, `test_research_gate_negative.py`, `test_decision_alignment.py`, `test_decision_alignment_authority.py`): all pass at the end.
- Research-gate freeze step (third automated verify of Task 1): header v2.0.0, DECISIONS row and DOC_STATUS index line all match.
- Full non-docker suite, run in 13 chunks of 15 test files with `-m "not docker" -x` (the whole-suite run is forbidden by the known Windows access violation): 3,571 passed, 431 skipped, 0 failed, 0 errors. No stray pytest process remains.
- `ruff check`: all checks passed; `ruff format --check`: 409 files already formatted; `mypy src`: no issues found in 147 source files (`mypy scripts/decision_alignment` also clean).
- Acceptance greps: `Frozen on` 2026-09-19, `Supersedes: v1.1.0`, Migration heading, `Pre-registered thresholds (v1.1.0)` present; one `| D052 |` and one `| D053 |` line in order; ROADMAP wording; the `### Quantization` block has no diff hunk (checked on `git diff -U0`), and PR-07 and AU gates pass; CANDLE_CLOSE, trade-through, END_OF_DATA, fundingTime, 360033525031, 2026-10-04 present; D052 appears four times in REQUIREMENTS.

## Task Commits

1. **Task 1 (tracer): protocol v2.0.0 through the gate** - `7a80af5` (test, RED), `7af7a72` (feat, GREEN)
2. **Task 2: specification text** - `dd2dd83` (docs)
3. **Task 3: D053, void markers, re-verification list** - `8322b29` (test, RED), `5ae5ef8` (docs, GREEN)

**Plan metadata:** committed separately after this file (docs: complete plan).

## Decisions Made

See `key-decisions`. D052 itself carries the full decision text, including the paper-parity choice, the strategy-lineage note, the incremental-feature-series deferral (re-time without tracemalloc first) and the two open items.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `tests/test_research_gate_negative.py` pinned the literal v1.1.0**
- **Found during:** Task 1 (GREEN run of the plan's own verify command, which includes the file)
- **Issue:** `test_real_decisions_without_d043_row_fails` removed the D043 row and `test_real_doc_status_reverted_to_old_version_fails` replaced `v1.1.0` by `v1.0.1`; at v2.0.0 neither mutation breaks the real triplet, so both failed. The file is not in the plan's `files_modified` but is in its verify command.
- **Fix:** both tests read the header version and mutate against it (the row of the header version is removed, the header version is replaced in the index line); renamed the first to `test_real_decisions_without_header_version_row_fails`. The synthetic-version tests are untouched.
- **Files modified:** `tests/test_research_gate_negative.py`
- **Commit:** `7af7a72`

**2. [Rule 3 - Blocking] REQUIREMENTS traceability cells could not carry the void note**
- **Found during:** Task 3 (gate run)
- **Issue:** appending the note to the `| BKTS-01 | Phase 6 | Complete |` cells broke RQ-02 and RQ-03 (they parse the table).
- **Fix:** kept the three status cells exactly `Complete`; the void note and the proving test modules are on the three checkbox rows and in one traceability note directly under the table.
- **Files modified:** `.planning/REQUIREMENTS.md`
- **Commit:** `5ae5ef8`

### Plan-text corrections (no behaviour change)

- The plan's verify runs `scripts/verify_decision_alignment.py` without an argument; the script needs a mode, so `all` was used.
- The plan's Task 3 verify runs the whole `pytest -m "not docker"`; the orchestrator forbids it (Windows access violation), so the suite was run in 13 chunks (result above).
- Added tests not named in the plan: a D053 row test and a table-reaches-D053 test (Task 3 RED), a header-driven BACKTEST_SPEC pointer test and a DC-03 current-version test (Task 1 RED).

**Total deviations:** 2 auto-fixed (Rule 3). **Impact:** none on the amended semantics; both keep a test honest after the version moved.

## TDD Gate Compliance

- Task 1 RED `7a80af5`: 16 tests failed (the new `protocol=` keyword raised `TypeError` in the bookkeeping helper; D052 row, header-version, DOC_STATUS and BACKTEST_SPEC-pointer tests failed on assertions). GREEN `7af7a72` turned them all green. `gsd_run check tdd-red-evidence` was not run.
- Task 2 is documentation only (no behavior-adding task, exempt); the gates and tests above cover it.
- Task 3 RED `8322b29`: the D053 row test and the table-reaches-D053 test failed (verified before the commit); GREEN `5ae5ef8`.
- No test or validator was weakened. The two edits in `tests/test_research_gate_negative.py` keep each mutation meaningful (verified by the tests passing only with the header-version row and index line present).

## Known Stubs

None. The plan edits documentation and gate code only.

## Threat Flags

None. No new endpoint, auth path, file access or schema at a trust boundary.

## Open items carried forward (also in `deferred-items.md`)

- `modeled_costs_per_unit` is `None` on v2 filled records; recorded in D052, not restored (nothing reads it, outside this plan's scope).
- No runner calls `read_code_version` plus `assemble` outside tests (Phase 15 runner).
- ROADMAP Phase 26 goal still says "a family has passed under protocol v1.1.0"; not in this plan's file list.
- `06-VERIFICATION.md` `covered_digest` is stale after the void notes (intended; the report is void).

## Self-Check: PASSED

- Files present: RESEARCH_PROTOCOL.md, DECISIONS.md, DOC_STATUS.md, BACKTEST_SPEC.md, RISK_MANAGEMENT.md, SOURCES.md, holdout_consumed.json, protocol.py, bookkeeping.py, the five test files, ROADMAP.md, REQUIREMENTS.md, the three Phase 6 artifacts (all FOUND).
- Commits found in `git log`: 7a80af5, 7af7a72, dd2dd83, 8322b29, 5ae5ef8.
