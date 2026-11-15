---
phase: 22-leverage-margin-liquidation-guard
plan: 16
subsystem: gate-and-registers
status: complete
tags: [gate, owner-decisions, deferred, glossary, risk-management, execution-spec, demo-observed]
requirements-addressed: [RISK-01, RISK-02, EXEC-01, EXEC-02]
requires:
  - phase: 22
    provides: "plans 22-01 to 22-15 (modules, adapter reads and changes, migration 0012, gate 5f2, the owner Demo run of 2026-10-24)"
provides:
  - "tests/test_phase22_gate.py: the structural Phase 22 gate (purity, literals, constants, limit keys, enum, plain codes and GLOSSARY rows, head, shadow surface, error table, wiring facts, built-but-not-active pins, REQUIREMENT_TESTS, owner records, Demo labels)"
  - "22-OWNER-DECISIONS.md (O-1 to O-4 OPEN) and 22-DEFERRED.md (owner items, Demo cases, deferred items, requirement status)"
  - "RISK_MANAGEMENT sections 9 and 12, EXECUTION_SPEC section 8, GLOSSARY 9.1, 9.3 and new section 15"
affects: [phase-24-composition]
tech-stack:
  added: []
  patterns: ["pin a built-but-inactive piece so Phase 24 must change the gate on purpose"]
key-files:
  created:
    - tests/test_phase22_gate.py
    - .planning/phases/22-leverage-margin-liquidation-guard/22-OWNER-DECISIONS.md
    - .planning/phases/22-leverage-margin-liquidation-guard/22-DEFERRED.md
  modified:
    - docs/trading/RISK_MANAGEMENT.md
    - docs/trading/EXECUTION_SPEC.md
    - docs/GLOSSARY.md
key-decisions:
  - "The gate pins two inactive pieces, not only constants: nothing in src/ calls register_request or passes required_margin (outside the claims reader), and nothing in src/ or scripts/ passes liquidation_watch to a coordinator or builds a LiquidationWatch. A Phase 24 composition fails these tests until the gate and 22-DEFERRED.md are updated on purpose."
  - "The six Demo cases are recorded as RUN on 2026-10-24 (single samples), each with the part no run covered marked NOT RUN; criteria 1, 2 and 3 are stated NOT Demo-proven beyond what 22-DEMO-RESULTS.md says."
duration: ~45 min
completed: 2026-10-24
commits: 2
plan_head_before: 9354cea976f761c0e593f5a75b0d18df54309ae3
plan_head_after: 3d0db72fe19a48704722725d16842b45f1023c72
actuals:
  tokens: 17000
  tasks: 2
  commits: 2
---

# Phase 22 Plan 16: Phase 22 gate, owner and deferred registers, canonical documents Summary

**One structural gate keeps the Phase 22 invariants from drifting (no hard-coded bracket, rate or leverage, the netting constant False, the three margin limits `NOT_CONFIGURED`, the enum at 21, the head at 0012), and two registers plus three canonical documents say what was built, what is open and what no Demo run has proven, without changing a rule or setting an owner number.**

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 2 (done first, see Deviations) | 20750fc6 | `22-OWNER-DECISIONS.md`, `22-DEFERRED.md`, RISK_MANAGEMENT sections 9 and 12, EXECUTION_SPEC section 8, GLOSSARY 9.1, 9.3 and section 15 |
| 1 | 3d0db72f | `tests/test_phase22_gate.py` |

`commits: 2` is the measured `git rev-list --count plan_head_before..HEAD` from the persisted ledger; the SUMMARY commit follows. Requirements: `requirements.mark-complete` skipped by plan rule.

## What was built

- **Gate** (`tests/test_phase22_gate.py`, 29 tests, 815 lines after `ruff format`). Mirrors the Phase 21 gate. Pure modules `src/risk/liquidation.py` and `src/risk/margin_check.py`: no clock, no float, no forbidden import, no `USDT`, and no numeric literal outside {0, 1, 10000} (int, float and `Decimal("text")` arguments are all scanned); both are in `SCANNED_FILES` of `tests/test_domain_no_float.py`. The four execution modules: no clock, no adapter, store, SDK or sqlalchemy import, no `USDT`. Constants: `TARGET_LEVERAGE` 5, `TARGET_MARGIN_TYPE` `ISOLATED`, `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` False, `LiquidationFailurePolicy` exactly two members. The three `margin.*` keys: value and provenance `NOT_CONFIGURED`, not alert-only, in `unset_keys()`. The Phase 21 key is read from the file, not pinned to a number. `RejectionReason` has 21 members and none of the eleven plain codes or three blocked reasons is one; each is a module-level string of its module and has one row in GLOSSARY 9.3 with its module and the right status; 9.1 lists exactly the enum. Head `0012_reservation_margin` (via `alembic_head_revision()`); `change_margin_type` and `change_initial_leverage` on the shadow `ORDER_SURFACE` (read with ast); the nine error codes REJECTED_DEFINITIVE on PLACEMENT and absent on every other kind; `ProtectionCoordinator.__init__` has `liquidation_watch` defaulting to None; `LivePlacementContext.margin_guard` has no default; in `manager.py` the position-mode read precedes the single `margin_guard.evaluate(` call, which precedes the hand-off record. `REQUIREMENT_TESTS` maps RISK-01, RISK-02, EXEC-01 and EXEC-02 to 52 named tests resolved with ast by exact name (never imported or run). O-1 to O-4 are named, recorded `Status: OPEN` in the owner file; the deferred register names every SJ3 case, `NOT Demo-proven`, `NOT active`, `required_margin` and `register_request`; the evidence plan names every SJ3 case and "not Demo-proven"; the fixture README keeps `RECORDED_DEMO` and "demo-observed, not mainnet".
- **22-OWNER-DECISIONS.md**: O-1 to O-4 each OPEN with the built default, who decides, the source, and (O-1, O-2, O-3) the Demo fact of 2026-10-24 stated as a fact and not as a decision. No number written for any item; ends with "The assistant recorded these items and decided none of them."
- **22-DEFERRED.md**: header with the two facts the reader must not lose (nothing writes `required_margin`; `liquidation_watch` is built and tested but NOT active), the owner-item table, the six Demo cases (what each settles, what was observed, what is still NOT RUN), the criteria status after the run, 17 deferred items with owner phase or decision, and the requirement status (nothing marked complete; EXEC-01 and EXEC-02 Pending; RISK-01 and RISK-02 unchanged; G3-001 closed by SOURCES.md, G4-039 delivered for the in-memory snapshot only).
- **Documents** (text added, nothing removed except the replaced counts and the INSUFFICIENT_MARGIN sentence): RISK_MANAGEMENT section 9 gains the buffer-home deviation note (the registry-parameter wording stays) and "Live implementation (Phase 22)"; section 12 gains one sentence (guard-supplied values go to the in-memory snapshot, the persisted row is untouched). EXECUTION_SPEC section 8 gains the re-confirmation sentence (worded as cited from the research, not re-fetched, matching `SOURCES.md`; the link and the verify marker are unchanged) and the margin-guard-gate paragraph. GLOSSARY: INSUFFICIENT_MARGIN sentence now true to the code, `LIMITS_NOT_CONFIGURED` counts corrected to nineteen keys / eighteen required / one alert-only, fourteen rows in 9.3, and "15. Margin guard vocabulary (Phase 22)" (policy, watch actions, branch code, journal event, alert reasons).

## Wording rules of the plan-check addenda

1. `22-DEFERRED.md`, the RISK_MANAGEMENT paragraph and the gate (invariant 13 and its docstring) state that nothing in Phase 22 writes `required_margin`: the Phase 24 issuer calls `register_request`; until then every RESERVED or PLACED row reads as an unknown margin and a plan placed while another claim exists is refused `UNCERTAIN_ACCOUNT_STATE`. The approved-but-unplaced-plans part of criterion 3 is described as proven on fakes and the PostgreSQL claims reader only; criterion 3 is never described as complete.
2. `22-DEFERRED.md`, `22-OWNER-DECISIONS.md` (O-4), the RISK_MANAGEMENT paragraph and the gate (invariants 10 and 14) state that `liquidation_watch` is built and tested but NOT active; EXEC-02 and D-12 are not active until Phase 24 composes it.

## Verification

| Command | Result |
|---------|--------|
| `uv run python scripts/verify_decision_alignment.py all` | ALL_PASS |
| `uv run pytest -m "not docker" tests/test_phase22_gate.py tests/test_domain_no_float.py` | passed |
| `uv run pytest -m "not docker"` on `test_transitions`, gate files 18 to 21, `test_decision_alignment_{ops_risk,bookkeeping,exchange,authority}`, `test_agents_md` and the other test files that read GLOSSARY, RISK_MANAGEMENT or EXECUTION_SPEC | passed |
| `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_exit_evidence_pg.py -x` (TEST_DATABASE_URL set) | passed |
| `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, `uv lock --check` | clean |
| `git diff --exit-code -- docs/DECISIONS.md params config/binance pyproject.toml uv.lock .planning/REQUIREMENTS.md` | exit 0 |
| `git log --grep="^[a-z]*(22-[0-9]*):" -- .planning/REQUIREMENTS.md` | prints nothing |

The full suite was not run (the orchestrator runs it once per phase). Evidence label: executed structural tests; documents checked by the decision-alignment gate and the doc tests. Line endings kept (the three docs are CRLF in the working tree and were edited with a bytes-aware script; the new files are LF).

## Deviations from Plan

### Process

**1. Task 2 was committed before Task 1.** The gate reads GLOSSARY 9.3, `22-OWNER-DECISIONS.md` and `22-DEFERRED.md`, so a gate committed first would fail on the missing documents. The documents went first (20750fc6), the gate second (3d0db72f); each commit is green on its own. Content of both tasks is as planned.

### Wording

**2. The Demo cases are not all "NOT RUN".** The plan was written before the owner's run. The owner ran the six cases on 2026-10-24, so `22-DEFERRED.md` records them as run (single samples, demo-observed, not mainnet) and marks the uncovered part of each NOT RUN (-4048 and -4046, a lower bracket's leverage code, more netting samples, a short or higher-tier liquidation sample). Criteria 1, 2 and 3 are stated NOT Demo-proven, and nothing says more than `22-DEMO-RESULTS.md`. `22-DEMO-RESULTS.md` still says "the guard itself (plan 22-11) is not built yet"; it was written before wave 3 and is left unedited (it is the owner-run record).
**3. `LIQUIDATION_PRICE_DIFFERS` has a status of "proposed canonical, promote in Phase 24 (calibration reason, never a refusal)".** It is a verdict and alert reason, not a refusal; the prefix keeps the 9.3 convention and the parenthesis keeps it honest.
**4. Extra gate invariants** beyond the plan's list: the two built-but-not-active pins (13, 14), the SJ3 case names in the register (19), and `Status: OPEN` per owner section (17), to implement the addenda as tests.

### Auto-fixed Issues

None in production code. No earlier plan left a gap that failed a gate test.

## Known Stubs

None. (The pieces Phase 22 builds but does not wire are listed in `22-DEFERRED.md`, not stubs.)

## Threat Flags

None. No new network endpoint, auth path, file access or schema change; the plan edits tests, registers and documents only. T-22-59 to T-22-61 mitigated as planned (one row per owner item and Demo case, criteria stated NOT Demo-proven, gate pins, text added not replaced, `DECISIONS.md`, `params`, `config/binance`, `REQUIREMENTS.md`, `pyproject.toml` and `uv.lock` diff-checked clean).

## Self-Check: PASSED

- `tests/test_phase22_gate.py`, `22-OWNER-DECISIONS.md` and `22-DEFERRED.md` exist; `grep -c "^## O-[1-4]"` prints 4 and the O-row count in `22-DEFERRED.md` prints 4; the "Live implementation (Phase 22)" paragraph and the "## 15. Margin guard vocabulary" heading each occur once.
- Commits 20750fc6 and 3d0db72f are ancestors of HEAD.
