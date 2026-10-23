---
phase: 21-account-equity-daily-loss
plan: 14
subsystem: testing
tags: [gate, deferred-register, docs, glossary, risk-management, risk-01, risk-02, exec-01, ops-02]
requires:
  - phase: 21-01..21-13, 21-15, 21-16
    provides: "the Phase 21 modules, tests and owner records the gate pins"
provides:
  - "tests/test_phase21_gate.py: the structural Phase 21 gate (PHASE21_PURE_MODULES, PHASE21_EXECUTION_MODULES, REQUIREMENT_TESTS)"
  - ".planning/phases/21-account-equity-daily-loss/21-DEFERRED.md: owner items O-1 to O-6 and every unbuilt piece with its owner"
  - "RISK_MANAGEMENT section 8 'Live implementation (Phase 21)' and section 12 equity_used note; GLOSSARY 9.3 six codes and section 14"
affects: [phase-22, phase-24, phase-26]
tech-stack:
  added: []
  patterns: ["structural gate mirroring tests/test_phase20_gate.py: ast guards over the real tree, requirement-to-test names resolved with ast and never imported"]
key-files:
  created:
    - tests/test_phase21_gate.py
    - .planning/phases/21-account-equity-daily-loss/21-DEFERRED.md
  modified:
    - tests/test_domain_no_float.py
    - docs/trading/RISK_MANAGEMENT.md
    - docs/GLOSSARY.md
key-decisions:
  - "No requirement status changed: requirements.mark-complete skipped by plan rule; EXEC-01 and OPS-02 stay Pending, OPS-02 is not claimed (owner attestation, D-21)"
  - "The owner's O-2 answer (option A, TRADES_WITH_UNVERIFIED_FUNDING) is cited from 21-OWNER-DECISIONS.md, not reinterpreted; the pre-canary FUNDING_FEE check is recorded as an OPEN assistant recommendation"
status: complete
actuals:
  tokens: 11100
  tasks: 2
  commits: 2
plan_head_before: adc67ddcc68b31c9e7da538d685f5ba34dd897a6
plan_head_after: f28950f312fcd3503a92df7f21aad73bf4930aae
requirements-completed: []
completed: 2026-10-23
---

# Phase 21 Plan 14: Phase 21 gate, deferred register and canonical docs Summary

**A structural gate over the real tree pins the Phase 21 invariants, `21-DEFERRED.md` names every owner item (O-1 to O-6) and unbuilt piece with its owner, and RISK_MANAGEMENT and GLOSSARY describe the live equity, daily loss and reservation code without changing a rule.**

requirements.mark-complete skipped by plan rule. `.planning/REQUIREMENTS.md`, STATE.md and ROADMAP.md are not edited by this plan.

## What was built

- `tests/test_phase21_gate.py` (commit f28950f3), 10 invariants, 18 test cases:
  - the three `src/risk` modules read no clock, build no float, import no client and hold no `"USDT"` literal; the four `src/execution` modules read no clock, import no `src.adapters`, `src.persistence`, `binance*` or `sqlalchemy`, and hold no `"USDT"` literal;
  - `account.max_equity_age_ms` is `NOT_CONFIGURED` (value and provenance), not alert-only, and listed by `unset_keys()`;
  - `RejectionReason` has 21 members; `LIVE_NET_PNL_SEMANTICS_VERIFIED` and `FUNDING_SOURCE_VERIFIED` are False; `daily_stop` is in `_EXPIRY_TRIGGERS`; the Alembic head is `0011_risk_reservations`; the OPS05 rows DAILY_STOP and DAILY_LOSS_WARNING name `src/execution/daily_stop.py`;
  - no JSON under `tests/fixtures/phase21` has the key `accountAlias` at any depth (spelled once as a constant);
  - `REQUIREMENT_TESTS` maps RISK-01 (10 tests), RISK-02 (22), EXEC-01 (4), OPS-02 (5) to real test functions, resolved with `ast`;
  - `21-OWNER-DECISIONS.md` and `21-DEFERRED.md` each name O-1 to O-6.
- `tests/test_domain_no_float.py` (CRLF kept): `src/risk/live_equity.py`, `daily_loss.py`, `reservations.py` added to `SCANNED_FILES`.
- `21-DEFERRED.md` (commit ae06cad3): header (fakes, local PostgreSQL and recorded Demo payloads only; nothing wired; nothing complete; no DECISIONS row), Owner items table (O-1 to O-6, O-2 quoted as decided "option A", pre-canary check recorded as OPEN recommendation), Deferred items table (Phase 24 wiring with the release mappings for every terminal plan state and the `mark_placed` / `mark_open` ordering, REST cadence and weights with no number, funding-source evidence, D-11 conversion, TP1 scaling, cluster membership F-908/F-014, operator acknowledgement path, symbols outside the universe, wallet-delta gate, Demo rehearsal equity, Phase 22 snapshot, G2-042, backlog 999.3, DATA_MODEL 2.21 `release_requested_in`), and "Requirement status after Phase 21".
- `docs/trading/RISK_MANAGEMENT.md` (CRLF kept): section 8 paragraph "Live implementation (Phase 21)" (equity field `totalMarginBalance`, demo-observed, not mainnet; persisted day state; most-adverse rule; sticky latch; reservation; `daily_stop` cancel with stops kept; "no rule changed"); one sentence in section 12 on `equity_used`.
- `docs/GLOSSARY.md` (CRLF kept): 9.3 rows DAY_STATE_MISSING, DAY_STATE_UNREADABLE, DAY_BASE_UNAVAILABLE, DAILY_LOSS_UNKNOWN, DAY_THRESHOLDS_INVALID, FUNDING_SOURCE_UNVERIFIED; `LIMITS_NOT_CONFIGURED` now says fifteen required of sixteen keys; new section 14 with ReservationStatus, the nine ReleaseReason values (terminal plan state and `RELEASE_SOURCE_STATUSES`), ComponentKind, ComponentSource, FundingPolicy.

## Verification (executed)

- `uv run pytest -m "not docker" tests/test_phase21_gate.py tests/test_domain_no_float.py tests/test_transitions.py tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_decision_alignment_ops_risk.py tests/test_decision_alignment_bookkeeping.py`: all passed.
- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_exit_evidence_pg.py` with `TEST_DATABASE_URL` set in the process environment (value not read): 31 passed, no skip.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS. `uv run ruff check`, `uv run ruff format --check`: clean. `uv run mypy src`: no issues (246 files). `uv lock --check`: clean.
- `git diff --exit-code -- docs/DECISIONS.md params config/binance pyproject.toml uv.lock`: exit 0.
- The full suite was not run (the orchestrator runs it once for the phase).

## Deviations from Plan

### Auto-fixed Issues

None in production code. One correction of a carried-in claim, recorded rather than fixed:

**1. [Rule 1 - Doc claim] "docs/DOC_STATUS.md and docs/GLOSSARY.md still say 'fourteen' signed methods" does not match the files**
- **Found during:** Task 2
- **Issue:** The 21-08 SUMMARY (and the orchestrator brief) say these two docs say "fourteen" signed methods. Neither does; the only "fourteen" in them counts the execution limit keys (GLOSSARY 9.3 `LIMITS_NOT_CONFIGURED`; DOC_STATUS line 77, a dated Phase 20 log line). The signed registry is sixteen in `src/adapters/binance_usdm.py`.
- **Fix:** GLOSSARY row corrected to the true key count (fifteen required of sixteen, as the plan asks); DOC_STATUS line 77 left alone (history); the mismatch is a row in `21-DEFERRED.md`.
- **Files modified:** `docs/GLOSSARY.md`, `21-DEFERRED.md`
- **Commit:** ae06cad3

### Order of commits

The documentation commit (`21-DEFERRED.md`, RISK_MANAGEMENT, GLOSSARY) precedes the gate-test commit because the gate's invariant 10 requires `21-DEFERRED.md` to exist; the plan lists the tasks the other way round. No content differs.

## Authentication gates

None.

## Known Stubs

None. No stub pattern in the files created or modified.

## Threat Flags

None. No network endpoint, auth path, file access or schema change was added; the plan adds a test and documents.

## Items carried for the owner

O-1, O-3, O-4, O-5, O-6 are OPEN; O-2 is decided (option A). The assistant-recommended pre-canary FUNDING_FEE check is an OPEN recommendation, not an owner decision; on 2026-10-23 Demo income returned one COMMISSION row and no FUNDING_FEE row (`19-OWNER-GAPS.md` section 2b; demo-observed, not mainnet). `demo_account_snapshots()` in `tests/support/account_fakes.py` is async. `DATA_MODEL.md` section 2.21 does not list `PgRiskReservationStore.release_requested_in` (21-DEFERRED).

## Self-Check: PASSED

- FOUND: tests/test_phase21_gate.py, 21-DEFERRED.md, docs/GLOSSARY.md and docs/trading/RISK_MANAGEMENT.md edits, tests/test_domain_no_float.py edit
- FOUND commits: ae06cad3, f28950f3 (ancestors of HEAD)
