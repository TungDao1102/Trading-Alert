---
phase: 13-research-data-foundation-fixes
plan: 11
subsystem: documentation-and-decision-gates
tags: [docs, sources, binance, data-model, data-pipeline, configuration, decisions, decision-alignment, requirements-gate]

requires:
  - phase: 13-research-data-foundation-fixes
    provides: "13-01..13-10 code: collect list, closed-day atomic publish, mark klines, archive fallback, funding history, backfill CLI, sufficiency report, case-input builder, freeze tool"
provides:
  - "docs/SOURCES.md 'Facts verified for Phase 13 (2026-09-30)': 13 rows with URL, date, method, confidence for every exchange fact Phase 13 relies on"
  - "docs/integration/BINANCE.md section 13 Historical market data (endpoints, weights, pacing, delisted-symbol handling, archive fallback, funding and OI)"
  - "docs/data/DATA_MODEL.md 2.13 Research Parquet datasets; docs/architecture/DATA_PIPELINE.md section 15; docs/configuration/CONFIGURATION.md runtime configuration of the Phase 13 data tools"
  - "docs/DECISIONS.md D049 and a DOC_STATUS change-log line"
  - "decision-alignment requirements gate mapping OPS-06 to Phase 13.1; scripts/verify_decision_alignment.py all ends ALL_PASS all"
affects: [13-12, 13-13, 13.1, 14, 16]

actuals:
  tokens: 9300
  tasks: 3
  commits: 3
plan_head_before: 456917ff22e2c89106d633c66c977d81d9e8433f
plan_head_after: 327c0786ad945bbf1868b759dc788ef83272712b

tech-stack:
  added: []
  patterns:
    - "Documentation appended (never reworded); CRLF line endings of the existing docs preserved"
    - "Exchange facts recorded with the honest retrieval method: SDK docstring plus live probe when the official page is behind a WAF challenge, live-probe-only behavior marked MEDIUM"
    - "Decision-alignment gate constants keyed by phase string so a decimal (inserted) phase can be named"

key-files:
  created: []
  modified:
    - docs/SOURCES.md
    - docs/integration/BINANCE.md
    - docs/data/DATA_MODEL.md
    - docs/architecture/DATA_PIPELINE.md
    - docs/configuration/CONFIGURATION.md
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - scripts/decision_alignment/bookkeeping.py
    - tests/test_decision_alignment_bookkeeping.py

key-decisions:
  - "D049 records the Phase 13 decisions, including D-22 (case-input builder in src/data/case_input.py, superseding the src/backtest location in D-17) and D-21 (1m stays at 12 months pending the sufficiency report); deferred owners are Phase 13.1, 14, 18 and 26"
  - "Facts read only from the SDK docstring or a live probe are MEDIUM confidence; only the public-data README (fetched) is HIGH"
  - "The requirements gate now names OPS-06 under Phase 13.1 (string phases, re.escape in the roadmap section regex) instead of reverting the planning docs"

patterns-established:
  - "Facts-verified tables carry one row per endpoint or behavior with URL, date, method and confidence, the same four columns as the Phase 11 and 12 sections"

requirements-completed: [DATA-01, DATA-02, DATA-03, DATA-04, BKTS-02]

coverage:
  - id: D1
    description: "SOURCES.md Phase 13 facts table and BINANCE.md section 13 record every exchange fact with URL, date, method and confidence; docs gate passes"
    requirement: DATA-01
    verification:
      - kind: command
        ref: ".venv/Scripts/python scripts/verify_decision_alignment.py docs (ALL_PASS docs)"
        status: pass
      - kind: unit
        ref: "tests/test_decision_alignment_exchange.py and tests/test_decision_alignment_authority.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "DATA_MODEL 2.13, DATA_PIPELINE section 15 and CONFIGURATION runtime settings describe the datasets, rules and CLIs as built"
    requirement: DATA-04
    verification:
      - kind: command
        ref: ".venv/Scripts/python scripts/verify_decision_alignment.py decisions (ALL_PASS decisions, DC-05 D045 notes intact)"
        status: pass
    human_judgment: true
    rationale: "Whether the prose is accurate and sufficient for Phases 13.1, 14 and 16 is a reader judgment; the gates only check that required tokens and D045 notes are still present."
  - id: D3
    description: "D049 row with D-22 and src/data/case_input.py, DOC_STATUS line, contiguous decision table"
    requirement: BKTS-02
    verification:
      - kind: command
        ref: "grep -n '^| D049 |' docs/DECISIONS.md (one line, contains D-22 and src/data/case_input.py); DC-01, DC-02 pass"
        status: pass
    human_judgment: false
  - id: D4
    description: "Requirements gate maps OPS-06 to Phase 13.1; the full dispatcher is green"
    requirement: BKTS-02
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_bookkeeping.py#test_thirteen_new_ids_are_registered_and_mapped"
        status: pass
      - kind: unit
        ref: "tests/test_decision_alignment_bookkeeping.py#test_roadmap_requirements_line_matches_decimal_phase_literally"
        status: pass
      - kind: command
        ref: ".venv/Scripts/python scripts/verify_decision_alignment.py all (ALL_PASS all, exit 0)"
        status: pass
    human_judgment: false

duration: 11min
completed: 2026-09-30
status: complete
---

# Phase 13 Plan 11: Phase 13 documentation, exchange-fact register and decision D049 Summary

**Every exchange fact Phase 13 relies on is recorded with source, date, method and confidence, the new datasets, pipeline rules and CLI settings are documented as built, D049 is in the decision log, and the requirements gate now maps OPS-06 to Phase 13.1 so `verify_decision_alignment.py all` ends `ALL_PASS all`.**

## Performance

- **Duration:** about 11 min (16:30Z to 16:42Z)
- **Tasks:** 3 (1 tracer, 2 auto)
- **Files modified:** 9 (0 created)

## Accomplishments

- **Facts register (tracer, then full).** The markPriceKlines row and BINANCE.md section 13 subsection were added first and the docs gate plus its two test modules re-run green; then 12 more rows: klines, exchangeInfo, the common-definition enums, fundingRate, openInterestHist, ticker/24hr, server time, delisted-symbol behavior, the data.binance.vision layout, the `.CHECKSUM` format, the bucket listing and the public-data README. Section 13 documents the endpoint and weight table, pacing, REST-first delisted handling with the archive fallback, and that the checksum is transport integrity only.
- **What the verification run actually established** (2026-09-30): exchangeInfo has 919 symbols (TRADING 787, SETTLING 131, PENDING_TRADING 1; PERPETUAL 702, TRADIFI_PERPETUAL 213); `fundingRate` serves 1000 rows and rejects 1001; `openInterestHist` rejects a startTime older than one month with -1130; of 33 sampled SETTLING perpetuals all still serve klines, of 8 sampled archive-only symbols 2 answer -1121; OMGUSDT serves flat zero-trade bars after its 2025-01-31 delivery; the archive zip's sha256 equals its `.CHECKSUM`.
- **Documents as built.** DATA_MODEL 2.13 (trade, mark, funding and OI layouts and columns, dataset identity recipe, collect list versus frozen universe, freeze report, sufficiency report and its exit-3 rule), DATA_PIPELINE section 15 (closed-day and atomic publish, zero-trade and precision, delivery cap, archive fallback, resume, case-input gap policy, supervisor seam) and CONFIGURATION (collector, collect-list proposer, backfill and freeze flags with defaults, refusal behavior, approval-hash rule). Flag names and defaults were taken from the CLIs' `--help` output, layouts and column names from the code.
- **D049 and gate fix.** D049 summarises D-01..D-29 with owners for the deferred items; `NEW_REQUIREMENTS` is now `dict[str, str]` with OPS-06 as `"13.1"`, and `_roadmap_requirements_line` escapes the phase.

## Task Commits

1. **Task 1 (tracer): Phase 13 exchange facts and BINANCE section 13** - `0d99b46` (docs)
2. **Task 2: data model, pipeline rules and runtime configuration** - `14150a7` (docs)
3. **Task 3: D049, DOC_STATUS line, OPS-06 mapping in the requirements gate** - `327c078` (docs; carries the gate code and test edits)

Tracer feedback gate: the tracer `<verify>` (docs gate plus the exchange and authority test modules) passed with only the markPriceKlines row and subsection, then the remaining rows were added and both re-run green (`ALL_PASS docs`).

## Files Created/Modified

- `docs/SOURCES.md`, `docs/integration/BINANCE.md` - facts register and section 13.
- `docs/data/DATA_MODEL.md`, `docs/architecture/DATA_PIPELINE.md`, `docs/configuration/CONFIGURATION.md` - datasets, rules, settings.
- `docs/DECISIONS.md`, `docs/DOC_STATUS.md` - D049 and the change-log line.
- `scripts/decision_alignment/bookkeeping.py`, `tests/test_decision_alignment_bookkeeping.py` - string phases, OPS-06 is 13.1, tests rewritten.

## Decisions Made

- D049 (see key-decisions). The status line states these are auto-mode defaults from CONTEXT that the user may override.
- The documents state the sufficiency report's limits plainly: depth only, no trade-count estimate, D043 floor untouched, `RESEARCH_PROTOCOL.md` diff empty.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Official documentation pages could not be read; facts grounded in SDK docstrings and live probes**
- **Found during:** Task 1
- **Issue:** Every developers.binance.com page (8 tried) answered HTTP 202 with an empty body (WAF challenge), as 13-04 had found; no WebFetch tool was available to this executor.
- **Fix:** Recorded each row's method honestly: installed SDK 17.4.0 docstrings (generated from those pages) for weights and limits, live public requests for observed behavior, the raw GitHub README (HTTP 200) for the archive. Nothing was recorded as documented that was only observed; live-probe-only behavior is labeled and MEDIUM. BINANCE.md section 13 carries the "verify against current Binance docs" marker. The response weight header was unusable this run (shared egress traffic), so weight tiers rest on the SDK docstring and 13-04's earlier observation.
- **Files modified:** docs/SOURCES.md, docs/integration/BINANCE.md
- **Commit:** 0d99b46

**2. [Rule 1 - Bug] A fourth test needed rewriting for string phases**
- **Found during:** Task 3
- **Issue:** The plan names three failing tests. `test_wrong_phase_fails_rq01` replaced `| OPS-06 | Phase 13 |` with `Phase 14`; once OPS-06 is Phase 13.1 that replace is a no-op and the test would fail after the fix (it had passed vacuously while the gate was red).
- **Fix:** Rewritten to replace `Phase 13.1` with `Phase 14`; assertions unchanged. Also added `test_roadmap_requirements_line_matches_decimal_phase_literally` (13.1 matches literally, 13 does not leak OPS-06, `13x1` does not match) and two assertions on the string phases in `test_thirteen_new_ids_are_registered_and_mapped`.
- **Files modified:** tests/test_decision_alignment_bookkeeping.py
- **Commit:** 327c078

**Total deviations:** 2 auto-fixed (1 Rule 1, 1 Rule 3). **Impact:** none on scope; both keep the plan's acceptance criteria.

## Requirements-gate drift (pre-existing, fixed here as the plan directs)

The confirm-first check ran `verify_decision_alignment.py reqs` before any edit: the only failures were RQ-01 `OPS-06 row is Phase 13.1, expected Phase 13` and RQ-04 `Phase 13 Requirements line lacks OPS-06` (exactly the two the plan names; nothing else failed, so the edit proceeded). Origin: commit `7ceede3` (2026-09-30, "insert Phase 13.1 Deployment & CI and trim infra from Phase 13"), which moved OPS-06 to Phase 13.1 in REQUIREMENTS.md and the roadmap without updating the gate constant. It was first logged by 13-01 in `deferred-items.md`; resolved here.

## Issues Encountered

- Pre-existing and untouched: the `src/paper/supervisor.py` transitive mypy error (`src/adapters/telegram_notify.py:287`) in `deferred-items.md`; not part of this plan.
- Files under `docs/` are CRLF; edits were made with scripts that insert CRLF text so no line-ending churn appears in the diffs (each diff is additions only).
- `.planning/config.json`, `.planning/milestone.lock`, `.planning/state.json` and `.gsd/` were pre-existing working-tree changes and were not staged.

## Known Stubs

None.

## Threat Flags

None. Documentation and a gate constant only; no network surface or trust boundary was added. T-13-48 (unverified facts): every row has URL, date, method and confidence; T-13-49 (decision gap): D049 with D-number cross references and DC gates green.

## User Setup Required

None.

## Next Phase Readiness

- 13-12 (operator freeze) and 13-13 (operator backfill run) can follow the documented CLI settings. The registered facts should be re-probed when the operator runs them, because which delisted symbols REST serves changes as Binance delists (13-RESEARCH validity for that fact was 7 days).
- Phase 14 finds the mark dataset layout and its trigger-series role in DATA_MODEL 2.13; Phase 13.1 finds its deferred items and owners in D049.
- Not done by design: `advance-plan` and requirement completion (13-12 and 13-13 still declare DATA-01..04 and BKTS-02).

## Self-Check: PASSED

- Modified files present: docs/SOURCES.md, docs/integration/BINANCE.md, docs/data/DATA_MODEL.md, docs/architecture/DATA_PIPELINE.md, docs/configuration/CONFIGURATION.md, docs/DECISIONS.md, docs/DOC_STATUS.md, scripts/decision_alignment/bookkeeping.py, tests/test_decision_alignment_bookkeeping.py.
- Commits present: 0d99b46, 14150a7, 327c078 (`git rev-list --count 456917f..HEAD` = 3 before this summary commit).
- Acceptance criteria re-run: `grep -n "Facts verified for Phase 13" docs/SOURCES.md` one line (rows for markPriceKlines, fundingRate, openInterestHist, exchangeInfo, ticker/24hr, data.binance.vision, CHECKSUM each dated 2026-09-30); `grep -n "^## 13\." docs/integration/BINANCE.md` one line; `grep -n "2.13 Research Parquet datasets"` and `dataset=mark_klines` in DATA_MODEL; `collect-list` in CONFIGURATION; `grep -n "^| D049 |"` one line containing D-22 and src/data/case_input.py; `grep -n '"OPS-06": "13.1"'` one line.
- Plan verification: `verify_decision_alignment.py all` prints `ALL_PASS all` (exit 0); `pytest tests/test_decision_alignment*.py` passes; `mypy scripts/decision_alignment` and `ruff check` on the two Python files are clean; `git diff 456917f..HEAD -- docs/research/RESEARCH_PROTOCOL.md` is empty.
