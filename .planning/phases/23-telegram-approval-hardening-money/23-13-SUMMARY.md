---
phase: 23-telegram-approval-hardening-money
plan: 13
subsystem: docs
status: complete
tags: [documentation, gate-test, glossary, decisions, trust-model, owner-register]
requirements-addressed: [APRV-01, APRV-02, PAPER-02]
requires: [23-01, 23-02, 23-03, 23-04, 23-05, 23-06, 23-07, 23-08, 23-09, 23-10, 23-11, 23-12]
provides:
  - "tests/test_phase23_gate.py: 32 structural invariants of the phase (vocabulary, purity, import bans, required allow-list, error handler, head 0014, message texts, requirement-to-test map, document facts)"
  - "docs/GLOSSARY.md section 9.3: 19 rows for the plain codes and outcome labels Phase 23 added; 9.1 and RejectionReason unchanged (21 members)"
  - "docs/integration/TELEGRAM.md: user and private-chat gate, Token trust model (F-127), money block, UTC times and the D025 / O-3 note, Phase 23 rules of section 6"
  - "docs/DECISIONS.md D088 and docs/data/DATA_MODEL.md 2.5: the G4-042 rule, owner answer O-2 (a) of 2026-10-26"
  - "23-OWNER-CHECKS.md: owner-run checks A1, G2-014, A2 and every owner question with the default built"
affects: [phase-24]
key-files:
  created:
    - tests/test_phase23_gate.py
    - .planning/phases/23-telegram-approval-hardening-money/23-OWNER-CHECKS.md
  modified:
    - docs/GLOSSARY.md
    - docs/integration/TELEGRAM.md
    - docs/data/DATA_MODEL.md
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - docs/operations/DEPLOY_GUIDE.vi.md
    - tests/test_phase20_gate.py
    - .planning/phases/23-telegram-approval-hardening-money/23-VALIDATION.md
key-decisions:
  - "D088 written because the owner answered O-2 with option (a) on 2026-10-26 (23-08-SUMMARY.md); the row quotes the owner's reply verbatim and says that (a) was the recommended option."
  - "GLOSSARY 9.3 carries Phase 23's codes as plain strings; the one-sentence introduction states the deliberate amendment of D-15 (orchestrator resolution 7), 21 enum members stay."
metrics:
  completed: 2026-10-27
commits: 5
plan_head_before: 88446137ce76e5915badb11c35f9e364939f21af
plan_head_after: c8bf785403cfdd1b4dcfd8062ba2c880e013b502
actuals:
  tokens: 40000
  tasks: 3
  commits: 5
---

# Phase 23 Plan 13: Close the phase in the canonical documents, one gate test, the owner register Summary

The trust model and every Phase 23 rule are in the canonical documents, every new plain code has its GLOSSARY 9.3 row, the G4-042 rule is recorded as D088 exactly as the owner answered, one gate test pins the phase, and the owner has one file of what only the owner can check or decide.

## What was built

- **Task 1 (tracer; RED `0ed97907`, GREEN `8305fd58`).** `tests/test_phase23_gate.py` in the style of the Phase 22 gate. GLOSSARY 9.3 gained 19 rows (`USER_ID_UNAVAILABLE`, `CHAT_NOT_PRIVATE`, `USER_NOT_AUTHORIZED`, `APPROVAL_STORE_FAILURE`, `ALREADY_DECIDED`, `CALLBACK_HANDLER_ERROR`, `CONFIRM_INPUTS_UNAVAILABLE`, `CONFIRM_INPUTS_MISMATCH`, `MONEY_AT_STAKE_MISSING`, `USER_MISMATCH`, `CHAT_MISMATCH`, `NO_CONFIRM_CONTEXT`, `RECHECK_ERROR`, `CONFIRM_TTL_ELAPSED`, `CARD_DELIVERY_FAILED`, `RUNTIME_RESTART`, `CONFIRM_ALREADY_EXPIRED`, `VALIDITY_RULE_ERROR` and the outcome label `LEFT_PENDING_SIBLING_DECIDED`) and one sentence in the introduction. `VALIDITY_RULE_ERROR` is not in the plan's list; it is a plain code of plan 23-12 that appears on the card. The diff of `docs/GLOSSARY.md` is 20 added lines and one changed intro line; no existing row changed. The RED commit failed exactly the two GLOSSARY tests.
- **Task 2 (`b55220d2`).** TELEGRAM.md section 3 (second gate, order of the checks, startup refusal, O-1 and O-4, G2-014) and the subsection "Token trust model (F-127)" with the five facts; section 4 (SIMULATE now carries the quantity, the money block lines in order, UTC times with the D025 / O-3 note); section 6 (one message with two buttons, the final edit with an empty keyboard and A1, stale taps from stored state with the G4-032 reply, the RetryAfter bound of 30 s and 3 attempts, error handling and A2, the DEMO/LIVE two-step confirm, "not composed yet"). DECISIONS D088 (next free number, re-checked at HEAD: the last row was D087), a DATA_MODEL 2.5 paragraph, one DOC_STATUS line, and DEPLOY_GUIDE.vi.md (a Vietnamese bullet for `TELEGRAM_AUTHORIZED_USER_IDS` and the stale "user-id check is Phase 23, chưa xây" sentence replaced). The gate test gained the document invariants (trust model heading, D088 row, DOC_STATUS line, no allow-list value next to the variable).
- **Task 3 (`c8bf7854`).** `23-OWNER-CHECKS.md` (three owner-run checks NOT_REHEARSED; 12 owner questions with default built, implementing file and status; the wording left behind by O-2; the two failing guard tests; the requirement-status note) and the `23-VALIDATION.md` sign-off (status column from the SUMMARY files, Wave 0 ticked, `nyquist_compliant: true`, `wave_0_complete: true`).
- **Fix `685bf707`.** See deviation 1.

## Verification (executed 2026-10-27)

- `uv run pytest -m "not docker" tests/test_phase23_gate.py tests/test_phase21_gate.py tests/test_phase22_gate.py tests/test_phase20_gate.py tests/test_domain_enums.py tests/test_deploy_guide_vi.py tests/test_decision_alignment_bookkeeping.py tests/test_agents_md.py`: all passed. The wider set of every per-task command of `23-VALIDATION.md` that needs no PostgreSQL plus the Phase 19 to 22 gates, run with `-n 4`: all passed after deviation 1.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS. `uv run ruff check` and `ruff format --check` on the two touched test files: clean.
- `git diff --exit-code` against the plan start for `pyproject.toml`, `uv.lock`, `AGENTS.md`, `params`, `config`, `docs/research/RESEARCH_PROTOCOL.md` and `docs/trading/RISK_MANAGEMENT.md`: exit 0 (no dependency change, T-23-SC; no gated document edited, T-23-43).
- Line endings: every edited `docs/` file stays `i/lf w/crlf`; numstat of the docs edits: DECISIONS 1/0, DOC_STATUS 1/0, DATA_MODEL 2/0, TELEGRAM 40/1, DEPLOY_GUIDE.vi 2/1, GLOSSARY 20/1. Edits were made bytes-aware with scripts that assert pure CRLF; none of the added text holds a backslash.
- Not run: the PostgreSQL files of rows 23-04 and 23-08 (the VALIDATION status for them cites the plans' own SUMMARY runs), the full suite (the orchestrator runs it once).
- Evidence label: documentation and a structural gate [DESIGN]; the owner-run checks stay NOT_REHEARSED.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `tests/test_phase20_gate.py` pins the exact list of DECISIONS rows after D078**
- **Found during:** Task 2 verification run (`test_invariant_6_decisions_gained_no_row_and_d055_stays_open`).
- **Issue:** the list ends at D087; the new D088 row made it fail. The file is not in the plan's `files_modified`; the same update was made when D087 was added.
- **Fix:** D088 added to the pinned list and to the failure message (bytes-aware, CRLF kept, 14 added and 2 deleted lines).
- **Files modified:** tests/test_phase20_gate.py
- **Commit:** 685bf707

### Plan deviations recorded

**2. [Scope] `VALIDITY_RULE_ERROR` got a 9.3 row** (19 rows, not 18 as the plan's list implies); the gate pins it with the other codes.
**3. [Process] Gate test pins by `ast` and generator output.** The "no `Asia/Ho_Chi_Minh` and no `Display:`" invariant reads the generated goldens (`render_all()` of `scripts/gen_phase23_fixtures.py`, which `tests/test_phase23_fixtures.py` ties to the real formatters) instead of calling `format_approve`, `format_simulate` and `format_approval_request` directly. The SHADOW pair is checked through `format_time_pair`.
**4. [Process] `git add` of a docs path under an ignored-looking directory** printed a hint for `docs/data` once; the file is tracked and was staged normally (the first `git add` of the batch had already staged the others; no `-f` was used).
**5. [Environment] A heredoc to the Python interpreter hung once** (the command timed out in the background; it changed nothing). The two long-line fixes were then made with the edit tool.

## Open items for the orchestrator and the owner

- **Two guard tests fail on HEAD and are not caused by this plan** (`deferred-items.md`, re-run today): `tests/test_no_unratified_defaults.py::test_no_canonical_key_gets_a_numeric_constant_in_src_or_scripts` (`RETRY_AFTER_CAP_SECONDS` in `src/adapters/telegram_notify.py`, plan 23-07) and `tests/test_modeled_costs_none_guard.py::test_consumer_audit_is_pinned_and_fails_when_a_new_reader_appears` (`build_money_at_stake`, plan 23-02). The full-suite run will report both until their pinned lists are updated after an audit. They are registered in `23-OWNER-CHECKS.md` and the VALIDATION sign-off names them.
- Stale wording left on purpose (O-2): the `RestartReport` docstring in `src/paper/shadow.py` and the comment near `src/paper/shadow_runtime.py` line 1121.
- Requirement status recorded, not changed (the plan says to skip `requirements.mark-complete`): APRV-01 and APRV-02 stay Complete (Phase 8), PAPER-02 stays Pending (Phase 16 closes it). `STATE.md` and `ROADMAP.md` were not touched (the orchestrator records progress).

## Known Stubs

None. The documents describe library pieces that no running process uses until Phase 24; this is stated in TELEGRAM.md ("Not composed yet") and in `23-OWNER-CHECKS.md`.

## Threat Flags

None. T-23-41 mitigated (D088 written only because 23-08-SUMMARY.md records answer (a), with the owner's reply quoted), T-23-42 mitigated (the documents name the variable only; a gate test rejects `TELEGRAM_AUTHORIZED_USER_IDS=<digit>`), T-23-43 mitigated (no gated file edited; alignment gate ALL_PASS; GL-03 keeps 9.1 equal to the enum), T-23-SC mitigated (no dependency change).

## Self-Check: PASSED

- FOUND: tests/test_phase23_gate.py, 23-OWNER-CHECKS.md, `### Token trust model (F-127)` in docs/integration/TELEGRAM.md, one `| D088 |` row in docs/DECISIONS.md.
- FOUND commits (ancestors of HEAD): 0ed97907, 8305fd58, b55220d2, 685bf707, c8bf7854.
