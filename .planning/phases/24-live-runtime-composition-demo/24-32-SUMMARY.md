---
phase: 24-live-runtime-composition-demo
plan: 32
subsystem: tests
tags: [gate, register, validation, D-35, EXEC-01, EXEC-02, EXEC-03, OPS-02, OPS-03, OPS-04, APRV-01]
requires: [24-09, 24-31]
provides:
  - "tests/test_phase24_gate.py: inventory, purity, head, requirement map, D-01..D-35 decision map, register checks"
  - "24-DEFERRED.md: a status for every inherited item (20 ROADMAP ids, 5 earlier-section ids, 39 20-DEFERRED rows, 20 residuals)"
  - "24-VALIDATION.md: per-task statuses from one per-file run on 2026-11-07"
affects: [24-33]
key-files:
  created:
    - tests/test_phase24_gate.py
    - .planning/phases/24-live-runtime-composition-demo/24-DEFERRED.md
  modified:
    - .planning/phases/24-live-runtime-composition-demo/24-VALIDATION.md
key-decisions:
  - "No requirement is marked complete; EXEC-01, EXEC-02 and OPS-02 stay Pending until the owner's evidence (24-33). REQUIREMENTS.md is untouched."
  - "demo-observed is written only where the committed smoke evidence (21 of 21 steps, 2026-11-06) lists the step OBSERVED; everything that needs the host, a second Telegram account or healthchecks.io stays NOT_OBSERVED."
metrics:
  tasks: 3
  completed: 2026-11-07
status: complete
---

# Plan 24-32 summary

## The gate

`tests/test_phase24_gate.py` (94 tests) pins:

- the `src/live` inventory (26 modules, exact set) and the other Phase 24 files;
- purity: no `float(` constructor in `src/live`; the wall clock is read once, at the CLI edge `runtime.py`; `src/live` imports neither the paper runtime, tests nor scripts; no lower layer (core, risk, domain and the rest) imports `src.live`;
- Alembic head `0015_order_event_time` and live placement still disabled;
- `REQUIREMENT_TESTS`: APRV-01, EXEC-01, EXEC-02, EXEC-03, OPS-02, OPS-03, OPS-04, each with at least two named tests resolved by `ast`;
- `DECISION_EVIDENCE`: D-01 to D-35, each with its plan and at least one existing test function or document anchor; DECISIONS D098 to D107 exist once each and D097 is Accepted;
- the register: every inherited id of the ROADMAP Phase 24 entry, the five ids named from earlier sections (G4-034, G4-043, G2-019, T-05, T-06) and every 20-DEFERRED row that names Phase 24 has a status; test files named in the register exist; nothing claims a host or mainnet result.

## The register

`24-DEFERRED.md`: 88 table rows. Section A has the 20 ROADMAP inherited ids, B the 5 earlier ids, C the 39 20-DEFERRED rows (20D-01 to 20D-39), D the residuals (R-01 to R-20).

Not closed by Phase 24 (all named in the register, none hidden):
- OWNER: G2-014 (second account tap), G3-033 (VPS and host rows), R-14 (no re-issued CONFIRM card after a restart; recommendation accept for V1).
- DEFERRED: G2-042 (the smoke fill sample comes from an entry fill and cannot show whether realizedPnl excludes commission; the flag stays False, D086), the exact signed-quantity compare (Phase 25, Q16), the W8 re-alert number, WR-C6, WR-B7 and the lot-filter fallback age (owner numbers), UNTRACKED_SYSTEM_ORDER on a manual close with TP1 resting (R-15, owner 2026-11-07), the cosmetic INVALID_REASON text, the open_day side effect before LIVE, the start-sequence CLOCK_DRIFT step not gating on the limits, and the rows marked for the Phase 24 code review.
- ACCEPTED: R-10 (synchronous sink journal write), R-12 (D-34 rule, D107 Provisional), R-19 (the benign telegram_delivery warning at start).

## Validation

`24-VALIDATION.md` per-task statuses come from one run of every test file named in the final `<automated>` commands of the 99 task rows: 134 files, `-m "not docker" -n 4`, `TRADING_CI_STRICT=1`, `TEST_DATABASE_URL` set so the `*_pg.py` files ran. Result: 5201 tests: 5197 passed, 4 skipped, 0 failures, 0 errors; the 4 skips the heartbeat file-mode cases, which cannot run on Windows. `verify_decision_alignment.py all` printed ALL_PASS and the three inline `python -c` rows exited 0. This is a per-file run, not the recorded sequential gate and not the full suite (the orchestrator runs that once).

96 rows green. Not green: 24-35-T1 (docker-marked, not re-run), 24-33-T2 (owner run), 24-33-T3 (records the owner's results). `nyquist_compliant` and `wave_0_complete` stay false, as the plan requires; the owner approval line stays pending.

The command column of the validation table is the planner's draft; several test files were renamed since (for example `test_live_tracer.py` became `test_live_composed_tracer.py`). The PLAN.md files hold the final commands and a note under the table says so.

## Quick run (plan Task 3)

`uv run pytest -m "not docker" tests/test_phase24_gate.py tests/test_phase18_gate.py tests/test_phase23_gate.py tests/test_paper_shadow_isolation.py tests/test_live_ast_guards.py tests/test_live_wiring.py -x` gave: **299 passed in 19.32s**.

`git diff -- src pyproject.toml uv.lock` is empty; `.planning/REQUIREMENTS.md` was not touched by this plan.

## Fix found earlier in the wave

`test_phase18_gate::test_invariant_6` failed on `str(exc)` in the PreSendRefusal journal row of commit 35d6904f; fixed in commit 52b52958 before this plan (the journal now records the fixed `reason` code).
