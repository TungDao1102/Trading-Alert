---
phase: "20"
slug: "reconcile-safe-mode-hardening"
# status lifecycle: draft (seeded by plan-phase) -> validated (set by validate-phase section 6)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: "2026-10-21"
---

# Phase 20 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from the Validation Architecture section of `20-RESEARCH.md`. Where `20-REVIEW-RESOLUTIONS.md`
> adds a task (T-A transition guard, T-B result API, T-D gate persistence, T-F symbol guard), its
> tests are added to the map by the planner. Evidence labels: nothing here is `[DEMO]`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >= 9, pytest-asyncio >= 1.4 (`asyncio_mode = "auto"`), pytest-xdist >= 3.8.0 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | the single targeted test file(s) of the task, `uv run pytest <file> -x -q` |
| **Wave command** | `uv run pytest -m "not docker" -n 4 tests/test_reconcile*.py tests/test_safe_mode*.py tests/test_risk_first_spill.py tests/test_protection*.py tests/test_emergency_close*.py tests/test_alerts.py tests/test_drills.py` plus `uv run ruff check && uv run mypy src` |
| **Full suite command** | `uv run pytest -m "not docker"` sequential with `TEST_DATABASE_URL` set and `TRADING_CI_STRICT=1` (recorded-gate form); `-n 4` for development |
| **Static gates** | `uv run ruff check && uv run ruff format --check`, `uv run mypy src`, `uv lock --check`, `uv run python scripts/verify_decision_alignment.py all` |
| **Estimated runtime** | quick: seconds; full suite: about 9-10 min with `-n 4` (AGENTS.md) |

`pytest` reads `TEST_DATABASE_URL` from the process environment only; unset means the `*_pg.py`
files silently skip. Subagents run only their own tests; the orchestrator runs the full suite once
per phase (AGENTS.md).

---

## Sampling Rate

- **After every task commit:** the targeted test file(s) of that task.
- **After every plan wave:** the wave command above.
- **Before `/gsd-verify-work`:** full suite green on a clean tracked tree.
- **Max feedback latency:** about 60 seconds for a targeted file.

---

## Per-Task Verification Map

The planner replaces the Task and Plan columns with real ids. Requirement rows below are the
minimum the plans must cover (from `20-RESEARCH.md`, corrected by `20-REVIEW-RESOLUTIONS.md`).

| Area | Plan | Requirement | Secure behavior | Test type | Automated command | File exists |
|------|------|-------------|-----------------|-----------|-------------------|-------------|
| Config keys (T-H) | 20-01 | EXEC-02, OPS-05 | seven new keys NOT_CONFIGURED with provenance; require_live_ready names them; cadence check; no numeric default | unit | `uv run pytest -m "not docker" tests/test_no_unratified_defaults.py tests/test_phase18_gate.py tests/test_execution_limits.py tests/test_binance_limits_ratified_file.py -x` | update |
| Transition guard (T-A) | 20-02, 20-09, 20-17 | RISK-03 | illegal edge rejected without state or `seq` change and journaled; `CLOSE_REQUIRED` never downgraded; `UNPROTECTED` not cleared without evidence; valid replay passes, corrupt replay fails closed | unit | `uv run pytest -m "not docker" tests/test_protection_transitions.py tests/test_transitions.py -x` | W0 |
| Result API (T-B) | 20-03 | EXEC-02 | `REJECTED` + `RECONCILED_ABSENT` / `NEVER_SENT` persist in the in-memory and PG stores through one shared contract test; `exchange_status` unchanged | unit + PG | `uv run pytest -m "not docker" tests/test_intent_result_contract.py tests/test_intent_result_contract_pg.py -x` | W0 |
| Compare v2 | 20-04 | EXEC-02 | doubled, sign-flipped (LONG and SHORT), bound boundary, foreign, TP-only, no-stop and duplicate-id fixtures are divergences; missing local side/bound data or a None source never yields agreement; over-fill below the bound documented as invisible; clean fixture agrees; a resting-entry protective is not an orphan; SUMMARY "D-01a bound check evidence" cited at O-F | unit (pure) | `uv run pytest -m "not docker" tests/test_reconcile_compare_v2.py -x` | W0 |
| Enum and glossary | 20-05, 20-20, 20-24 | G3-005 | `ENTRY_WITHOUT_PROTECTIVE` promoted; GLOSSARY 9.3 and 9.4 parity including the new ownership-conflict reason | unit | `uv run pytest -m "not docker" tests/test_domain_enums.py tests/test_decision_alignment_bookkeeping.py -x` | update |
| SAFE_MODE durability (T-E, D-14) | 20-06 | OPS-01 | persisted on enter; unreadable store means in SAFE_MODE; restart never exits | unit + PG | `uv run pytest -m "not docker" tests/test_safe_mode_persistence.py tests/test_safe_mode_persistence_pg.py -x` | W0 |
| Gate persistence (T-D) | 20-07 | RISK-03 | active 418 and 429 restored; expired restriction ignored; bootstrapped first install not locked, missing file never read as fresh install; loss and corruption after initialization fail closed; one persisted quarantine deadline reused by every restart (a2); expiry opens but is not health; state and quarantine persistence failures fail closed (no end, alert); no bypass for reduce-only | unit | `uv run pytest -m "not docker" tests/test_gate_restart.py -x` | W0 |
| Risk-first spill (D-16) | 20-08 | OPS-01 | DB outage never blocks disable, cancel or close; journal always raising; spill replay idempotent; missing, corrupt or conflicting spill reported | unit | `uv run pytest -m "not docker" tests/test_risk_first_spill.py -x` | W0 |
| Supervision after PROTECTED (D-07) | 20-09 | RISK-03 | lost stop after PROTECTED decided by position (D077); never re-placed; price invariant on every STOP_LOSS placement | unit + fake exchange | `uv run pytest -m "not docker" tests/test_protection_supervision.py -x` | W0 |
| UNKNOWN entry (T-C, D-11) | 20-10 | EXEC-02 | each missing condition keeps `UNKNOWN`; full protocol closes; `INTENDED` path; F5 skip | unit + PG | `uv run pytest -m "not docker" tests/test_intent_recovery_unknown_entry.py tests/test_intent_recovery.py -x` | W0 |
| Cancel verification | 20-11 | F-502, RISK-03 | `-2011` verified by query; FILLED after cancel is not canceled; manual close cancels legs only after two flat reads | unit | `uv run pytest -m "not docker" tests/test_cancel_verification.py tests/test_manual_controls.py -x` | W0 |
| Tick loop | 20-12, 20-16, 20-21 | EXEC-02 | three sources read, SAFE_MODE entered, only orphans swept, stop-lost delegated, reads skipped under a gate restriction; stale feed, stream and auth handling; risk-reducing first | unit + fake exchange | `uv run pytest -m "not docker" tests/test_reconcile_loop.py tests/test_reconcile_classify.py tests/test_feed_freshness.py tests/test_reconcile_stream_divergences.py tests/test_reconcile_queue_order.py -x` | W0 |
| Alerts | 20-13, 20-22 | OPS-05 | each event reaches the sink; journal first; message retried, order never; dedupe; no secret in text; matrix row per alert states the producer (wired or not) | unit | `uv run pytest -m "not docker" tests/test_alerts.py tests/test_alert_producers.py tests/test_alerts_ops05_matrix.py -x` | W0 |
| Pending actions (Q4) | 20-14 | RISK-03 | 429/418 pending actions persisted, resolved by current state, superseded by `CLOSE_REQUIRED`, stale stop never sent | unit + PG | `uv run pytest -m "not docker" tests/test_pending_actions.py tests/test_pending_actions_pg.py -x` | W0 |
| SAFE_MODE exit (T-E, D-15) | 20-15, 20-25 | OPS-01 | exit needs operator id, readable local source, fresh Binance reads, clean compare, nothing blocking; rows 6-7 per O-B; each failure case has its own test | unit | `uv run pytest -m "not docker" tests/test_safe_mode_exit_operator.py -x` | W0 |
| Manual controls | 20-17 | EXEC-06 | five controls obey D-06 and D-16; operator id recorded; the protect control has no placement of its own (only the coordinator's never-confirmed same-id rule at the plan stop) and sends nothing after a confirmed stop was lost, in CLOSE_REQUIRED / CLOSE_FAILED or on an unknown stop history (D077, owner direction 1) | unit | `uv run pytest -m "not docker" tests/test_manual_controls.py -x` | W0 |
| Emergency close filters (Q3) | 20-18 | RISK-03 | stored filters flagged stale for a close only; none means stays `CLOSE_REQUIRED` + alert; quantity floored | unit + PG | `uv run pytest -m "not docker" tests/test_emergency_close_filters.py tests/test_lot_filters_pg.py -x` | W0 |
| Rebuild and startup (D-08, D-30) | 20-19 | RISK-03, OPS-01 | clocks from durable times; lost stops stay lost; an unknown or ambiguous stop history never permits a re-placement (D077 handling, SAFE_MODE); corrupt replay fails closed; pending close attempts restored; spill missing/corrupt/conflicting handled | unit | `uv run pytest -m "not docker" tests/test_protection_rebuild.py tests/test_startup_recovery.py -x` | W0 |
| Symbol guard (T-F) | 20-20 | EXEC-02 | more than one active plan or ambiguous ownership for a symbol enters SAFE_MODE with its own reason; unreadable local data fails closed | unit | `uv run pytest -m "not docker" tests/test_symbol_ownership.py -x` | W0 |
| Drills | 20-23 | OPS-01 | UNPROTECTED, STALE_FEED and MANUAL_CLOSE drills; `OUTCOME_SAFE_MODE_BLOCKED` emitted; the old no-place outcome retired | unit | `uv run pytest -m "not docker" tests/test_drills.py tests/test_reconcile.py -x` | rewrite |
| Guards | 20-23 | all | no wall clock, no `float`, no SDK and no placement call in new `src/reconcile` and ops modules; new limit keys guarded and `NOT_CONFIGURED` | AST | `uv run pytest -m "not docker" tests/test_phase20_gate.py tests/test_no_unratified_defaults.py -x` | W0 |
| Docs and wording | 20-24, 20-26 | all | GLOSSARY / canonical docs match the code; criterion 2 and RISK-03 wording only after O-A | gate | `uv run python scripts/verify_decision_alignment.py all` | update |
| Gap closure, execution lane | 20-27 | EXEC-02, RISK-03 | evidence-row identity independent of observation time; gate refusal reaches NOT_SENT; manual close cancels legs when flat; stop confirmed through the open-algo-orders listing; `-4116` is exists-awaiting-REST; `-5040` definitive | unit + PG | `uv run pytest -m "not docker" tests/test_emergency_close_gate_refusal.py tests/test_protection_demo_shapes.py tests/test_intent_recovery_unknown_entry.py tests/test_manual_controls.py tests/test_exchange_errors.py -x` | W0 |
| Gap closure, reconcile lane | 20-28 | OPS-01, EXEC-02, OPS-05 | no SAFE_MODE re-entry rows for an unchanged reason; TP1 fill is not UNSYNCED_ALGO; exit runs the ownership check and needs a complete restore; stale resting-entry alert (alert only) | unit | `uv run pytest -m "not docker" tests/test_safe_mode_reentry.py tests/test_reconcile_tp1_fill.py tests/test_reconcile_stale_entry.py tests/test_safe_mode_exit_operator.py -x` | W0 |
| Gap closure, ops lane | 20-29 | OPS-01 | unreadable spill directory fails closed; overflow and recursion in the gate state file are corrupt, not crashes; failed save retried; supervisor bounded on an unknown gate | unit | `uv run pytest -m "not docker" tests/test_risk_first_spill.py tests/test_startup_recovery.py tests/test_gate_restart.py tests/test_rest_gate_cli.py tests/test_userdata_supervisor.py -x` | W0 |
| Gap closure, small fixes | 20-30 | OPS-01, EXEC-02 | a feed time ahead of the clock is stale; an implausible persisted gate deadline is untrusted; pause sleeps sliced | unit | `uv run pytest -m "not docker" tests/test_feed_freshness_skew.py tests/test_gate_restore_bounds.py tests/test_userdata_supervisor_pause_slices.py -x` | W0 |
| Gap closure, resting entry | 20-31 | OPS-01, EXEC-02 | an unfilled resting entry is not ENTRY_WITHOUT_PROTECTIVE and does not block the operator exit; a filled or vanished entry still is flagged; the deadline step still makes its same-id attempt | unit | `uv run pytest -m "not docker" tests/test_reconcile_classify.py tests/test_safe_mode_exit_operator.py tests/test_protection_deadline_attempt.py -x` | W0 |

Test file names are working names from the research; the planner may rename them.

---

## Wave 0 Requirements

- [x] `tests/support/reconcile_doubles.py` - recording alert sink, journal that can raise on demand, temp-dir spill, local-intent builders, a fake restriction source.
- [x] Extend `tests/support/fake_binance_exchange.py` - seed an exchange-only order, a doubled or negative position, duplicate client ids; model "absent" versus "filled" on cancel.
- [x] Extend `tests/support/execution_limits.py` - the new `NOT_CONFIGURED` key set (test-only values).
- [x] Shared contract-test base for the in-memory and PG intent stores (T-B).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Manual close outside the system: do `closePosition` legs auto-cancel (A1, G4-035) | EXEC-02 | Observed on Demo 2026-10-22 (both legs end `EXPIRED`); the orphan-sweep path was not exercised on Demo | none further unless the owner wants the orphan case |
| GTD expiry reaches a terminal state (A2) | EXEC-02 | Not confirmed on Demo (entry still `NEW` 840 s after `goodTillDate`); the scheduled cancel is a Phase 24 blocker | owner Demo probe with a longer wait |
| A4 (reduce-only MARKET cannot flip a position), P5 stop rejection, P3, `rm` of ALGO_UPDATE | EXEC-02, RISK-03 | never probed | owner Demo probe, Phase 25 |
| The 11 Demo probes and the numeric `NOT_CONFIGURED` limits | all | owner decision plus Demo evidence | `19-OWNER-GAPS.md` section 2 |
| ROADMAP criterion 2 and REQUIREMENTS RISK-03 wording (O-A) | RISK-03 | owner accepted 2026-10-22 (recorded in the 20-26 SUMMARY) | none |

Everything else has an automated check. No claim in this phase is `[DEMO]`.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency under 60s for a targeted file
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-10-23 at library level (fakes and local PostgreSQL; nothing `[DEMO]`). Every file named in the map exists and the full suite passed on `develop` HEAD `2be65c97`-era code (13234 passed, 20 skipped, 0 failed, run before plan 20-31; 20-31 ran its own 1237 tests); the gate files passed 112 under `TRADING_CI_STRICT=1` with PostgreSQL. Compliance covers library-level behavior only: wiring into a running process is Phase 24 and Demo-only items stay in Manual-Only.

## Validation Audit 2026-10-23

| Metric | Count |
|--------|-------|
| Gaps found | 0 (every mapped test file exists; Wave 0 items present) |
| Rows added | 5 (gap plans 20-27 to 20-31) |
| Resolved | 0 |
| Escalated to Manual-Only | 1 (A4 / P5 / P3 / `rm`) |
