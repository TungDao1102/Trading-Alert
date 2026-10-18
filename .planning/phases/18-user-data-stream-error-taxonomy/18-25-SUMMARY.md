base: 5dcbd296eb661ad8a4c950b8284dc8824cd4df0a

---
phase: 18-user-data-stream-error-taxonomy
plan: 25
subsystem: documents (SOURCES.md, BINANCE.md, EXECUTION_SPEC.md) and the D055 evidence draft
status: complete
tags: [binance, demo-observed, docs, EXEC-01, EXEC-02, EXEC-05, D-17, D-19, D-20]
requires:
  - 18-18 (Demo smoke evidence), 18-20 (Demo probe evidence), 18-21 (code table), 18-26 (error-code row of SOURCES.md, taxonomy decision of 2026-10-17)
provides:
  - docs/SOURCES.md subsection "Demo-observed facts (Phase 18 smoke and probe, 2026-10-16)" (21 rows) and the Phase 17 pointer sentence
  - tests/test_sources_phase18_section.py Demo label rule with negative controls
  - docs/integration/BINANCE.md section 5 Demo-observed list, F-056 paragraph restated, new section 6.2
  - docs/trading/EXECUTION_SPEC.md new section 6.2 and demo-observed protective-order facts in 6.1
  - docs/DOC_STATUS.md one dated line
  - decisions/18-DRAFT-D055-evidence-for-user.md (draft, not a decision)
affects: [Phase 19 and 20 consumers of the documents]
key-files:
  created:
    - .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DRAFT-D055-evidence-for-user.md
  modified:
    - docs/SOURCES.md
    - tests/test_sources_phase18_section.py
    - docs/integration/BINANCE.md
    - docs/trading/EXECUTION_SPEC.md
    - docs/DOC_STATUS.md
decisions:
  - "No DECISIONS row: D055 stays OPEN (D-17); the draft chooses nothing"
metrics:
  completed: 2026-10-18
actuals:
  tokens: 12000
  tasks: 3
  commits: 3
plan_head_before: 5dcbd296eb661ad8a4c950b8284dc8824cd4df0a
plan_head_after: fc1c255a2f7f4152ba55336e02fba29e7e045fdb
---

# Phase 18 Plan 25: Demo-observed facts in the documents, and the D055 evidence draft Summary

The smoke and probe facts of 2026-10-16 are now in the documents as demo-observed, not mainnet statements: 21 rows in a new SOURCES.md subsection (each citing its evidence JSON file and check-file item, accepted by a structure test that allows the Demo labels there only), the restated BINANCE.md and EXECUTION_SPEC.md statements, the new sections 6.2 (error classification; stream as a hint), and a D055 evidence draft that opens "DRAFT FOR THE USER. NOT A DECISION." and chooses nothing.

## Evidence decision (from the files)

SMOKE_RAN true (decision file has no `option: postpone`, check file has no "smoke postponed by the user"); PROBE_RAN true (same test on `18-DEC-O-18-03.md` and `18-probe-check.txt`). No postponed-run shape was needed in the documents (the test accepts it and a negative control proves it).

## Commits (all on develop, explicit paths, nothing pushed)

| Commit | Message | Content |
|---|---|---|
| afcfe5e | docs(18-25): record the Demo smoke and probe facts as demo-observed SOURCES rows | Task 1 (tracer): subsection, Phase 17 pointer, `-1125 assumed` wording of the keepalive row and register items 3, 4, 5, structure test |
| aedb3b5 | docs(18-25): BINANCE.md and EXECUTION_SPEC.md state the demo-observed facts and the stream's role | Task 2 |
| fc1c255 | docs(18-25): D055 evidence draft for the user (not a decision) | Task 3 |

## Coordination with plan 18-26 (followed)

- The error-code row of "Facts read for Phase 18" is untouched: `git diff 5dcbd29..HEAD -- docs/SOURCES.md` contains no line of it, and the marker "Re-read 2026-10-17" occurs once, as before. `tests/test_exchange_errors.py` (pins to `ERROR_TABLE_READ_DATE` / `ERROR_TABLE_REREAD_DATE`) passes.
- The "-1125 assumed" sentences of the keepalive row and of register item 5 were updated from the smoke (items 3 and 4 got a Demo update clause too); each keeps "still UNVERIFIED" where a documentation page, not Demo, is the question.
- The Demo rows print no error category: they print (http class, code, message) and point to `src/domain/exchange_errors.py` and the error-code row, because `evidence/18-probe-check.txt` prints the categories of the table before 18-26 (it shows -1106 and -4016 as UNKNOWN_EXCHANGE_ERROR; the code now classifies them, with -4024, as REJECTED_DEFINITIVE on placement only). BINANCE.md section 6.2 lists no code either; it points to the module, the SOURCES row and `18-DEC-TAXONOMY-CODES.md`. The DOC_STATUS line names the 18-26 SOURCES edit.
- No statement in the new text says a rejected protective order is protected; section 6.2 repeats open item (b) of 18-26 (SAFE_MODE is not derived from `safe_mode_eligible`; the manager enters SAFE_MODE on any unconfirmed protective leg).

## Tests (TDD for the tracer)

- RED (tests first, unchanged documents): `tests/test_sources_phase18_section.py`: 8 of the new tests failed (subsection absent, Phase 17 pointer absent, the negative controls that need the subsection).
- GREEN after the subsection: all pass. Added 11 tests: run flags from the files, subsection accepted, subsection placement and date, and negative controls (Demo label in a main row, missing "not verified on mainnet", unknown evidence file, missing evidence file name of the right family, missing subsection, postponed shape and invented rows, postponed smoke leaves no smoke row, Phase 17 pointer). The `_phase18_rows` helper now excludes the subsection; `_rows` also skips the header "Source (evidence file)".
- Two negative controls needed a correction of the test itself on first run (the mutation hit the intro paragraph instead of a row; the source cell still named the `.txt` check file); fixed in the test, not in the documents.

## Verification

- Task verify blocks: `tests/test_sources_phase18_section.py tests/test_decision_alignment_exchange.py tests/test_decision_alignment_bookkeeping.py` pass; the wider doc-gate set (`test_algo_status`, `test_exchange_errors`, `test_phase18_gate`, `test_userdata_router`, `test_decision_alignment_protocol`, `test_deploy_docs`, `test_kill_gate_docs`, `test_research_gate_negative`, `test_research_protocol_v250/v260`) passes.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS all after each task and at the end.
- Strict gate (final tree, HEAD fc1c255 before this SUMMARY, PostgreSQL container healthy, `TEST_DATABASE_URL` already in the environment): `TRADING_CI_STRICT=1 uv run pytest -m "not docker" -q -rs`: exit 0; 10314 passed, 6 skipped, 0 failed (counted from the progress lines, as in 18-26: 10303 + the 11 new tests). The 6 skips are the Windows platform skips (symlinks 1, NTFS file modes 1, deploy heartbeat file modes 4). `uv run ruff check`: passed. `uv run ruff format --check`: 629 files already formatted. `uv run mypy src`: no issues in 202 source files. `uv lock --check`: Resolved 60 packages.
- `git diff 5dcbd29..HEAD` over `src scripts params tests/support tests/fixtures docs/DECISIONS.md .planning/STATE.md .planning/ROADMAP.md` and the evidence directory prints nothing; the changed files are exactly the six declared ones. The Phase 11 SOURCES section is unchanged (`test_phase11_section_unchanged`, pinned sha256). EXECUTION_SPEC.md gained no developers.binance.com URL (EX-06 passes). BINANCE.md has 9 `verify against current Binance docs` markers (minimum 3).

## Proposed ROADMAP correction (NOT applied; ROADMAP.md was not edited)

**1. Phase 19 criterion 4** (`.planning/ROADMAP.md` line 955; probe source: `evidence/18-probe-check.txt`, case below_min_notional_reduce_only_leg, Demo only, demo-observed, not mainnet).

- Old text: "TP legs are quantized with MARKET_LOT_SIZE, and there is no MIN_NOTIONAL check on reduce-only legs. The system falls back to a single TP when a leg is below minQty (F-208, F-307, F-056)."
- Proposed text: "TP legs are quantized to the filters read from exchangeInfo (LOT_SIZE; MARKET_LOT_SIZE for a triggered market exit, which the Demo probe did not observe). A reduce-only STOP_MARKET below MIN_NOTIONAL was accepted at placement on Demo (demo-observed, not mainnet; the probe did not observe it trigger or execute and did not test a take-profit leg), so the system does not rely on a MIN_NOTIONAL exemption for reduce-only legs and treats a rejection of such a leg as a possible failure. The system falls back to a single TP when a leg is below minQty (F-208, F-307, F-056)."
- Source line: `evidence/18-probe-check.txt`: "below-minimum-notional reduce-only leg: with the position open, a reduce-only STOP_MARKET of quantity 0.0001 (notional 7.890670 against min_notional 50) was ACCEPTED (status NEW)"; "partial fill and market-lot-size: ... the out-of-range question is NOT_OBSERVED because the optional case was off".
- Why: the probe does not contradict the statement "no MIN_NOTIONAL check on reduce-only legs" for a Demo stop placement, but it does not establish it for take-profit legs, for execution at trigger, or on mainnet, and it says nothing about MARKET_LOT_SIZE. D055 outcome still governs criteria 1, 3 and 4 as the ROADMAP's inherited item already says.

**2. Phase 18 criterion text:** no probe-driven correction is proposed (criterion 2's questions were answered: not-found codes -2013, duplicate `clientAlgoId` -4116, id reuse accepted after CANCELED and, for a normal order, after FILLED). One observation that does not come from a re-read: criterion 3 lists "Demo / testnet / live selection", while the user's decision O-18-01 left TESTNET NOT_CONFIGURED (`18-DEC-O-18-01.md`); the criterion text could say "Demo / live selection (testnet not configured by user decision)". Left to the owner; the ROADMAP's stale Phase 18 status lines are for the phase-closing step.

## Deviations from Plan

None in behavior or scope. Notes:
- Commits are on `develop` at the caller's explicit instruction (the HEAD-safety text for agent branches does not apply to this session; no ref was force-moved), same as plan 18-26.
- `.planning/STATE.md` and `.planning/ROADMAP.md` were not updated, and no `state`/`roadmap` verb was run, per the caller's instruction; requirement completion marks (EXEC-01, EXEC-02, EXEC-05) were not made for the same reason.
- The tracer step touched the existing keepalive row, register items 3, 4 and 5 and the Phase 17 paragraph in addition to the new subsection, as the coordination note directs for the "-1125 assumed" sentences; the Phase 11 section and the error-code row are byte-identical.
- BINANCE.md section 7 keeps the heading words "Unverified audit claims (F-056)" and "Phase 19" because the gate test `test_binance_doc_states_audit_claims_as_unverified` pins them; the paragraph now reports what the probe answered (Demo only) under that heading.
- `.env` could not be read (secret-read guard); `TEST_DATABASE_URL` was already set in the session environment, so the strict gate ran with PostgreSQL.
- Untracked items (`.gsd/`, `.planning/milestone.lock`, `package.json`, `package-lock.json`, `docs/research/experiments/research-run-1-v2-3-0/`) were never staged or touched.

## Open items

- D055 stays OPEN; the draft is the user's input. No DECISIONS row; if the owner wants one the next free number must be recomputed.
- The proposed ROADMAP correction above awaits the owner.
- Not observed on Demo and therefore not claimed: partial fill, the triggered lifecycle and child order identity, MARKET_LOT_SIZE above the maximum, id reuse after a FILLED algo order, a duplicate normal-order client id while the first is open.
- 18-26 open items (a) to (d) are unchanged and not restated as decided.

## Known Stubs

None.

## Threat Flags

None (documents and one test only; T-18-69 and T-18-74 mitigations: NOT A DECISION first line, no DECISIONS or ROADMAP diff, Demo labels accepted only inside the subsection with negative controls, docs gates after every task, Phase 11 section pinned).

## Self-Check: PASSED

- Files exist: `18-DRAFT-D055-evidence-for-user.md`, `docs/SOURCES.md`, `tests/test_sources_phase18_section.py`, `docs/integration/BINANCE.md`, `docs/trading/EXECUTION_SPEC.md`, `docs/DOC_STATUS.md`.
- Commits exist: afcfe5e, aedb3b5, fc1c255.
