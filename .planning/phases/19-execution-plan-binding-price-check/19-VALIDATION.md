---
phase: "19"
slug: "execution-plan-binding-price-check"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: "2026-10-19"
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths `tests`, marker `docker`) |
| **Quick run command** | `uv run pytest -m "not docker" <the task's test files> -x` (the `<automated>` command of each task below) |
| **Phase suite command** | `uv run pytest -m "not docker" tests/test_execution_*.py tests/test_binance_*.py tests/test_protection_*.py tests/test_pre_placement.py tests/test_tp_sizing.py tests/test_market_lot_split.py tests/test_emergency_market_close.py tests/test_fake_exchange_v2.py tests/test_no_unratified_defaults.py tests/test_phase18_gate.py tests/test_phase19_gate.py -x` |
| **Full suite command** | `uv run pytest -m "not docker"` (with `TEST_DATABASE_URL` set to the local PostgreSQL 17 test server), then `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, `uv lock --check` |
| **Estimated runtime** | quick command seconds; full suite several minutes (about ten thousand tests at the Phase 16/18 counts; measure, never recall) |

---

## Sampling Rate

- **After every task commit:** run the task's `<automated>` commands (targeted pytest plus `uv run mypy src` / `uv run ruff check` where listed).
- **After every plan wave:** run the phase suite command plus `uv run ruff check` and `uv run mypy src`.
- **Before `/gsd-verify-work`:** full suite green with `TEST_DATABASE_URL` set (no skipped `_pg` test), `ruff format --check` and `uv lock --check` clean.
- **Max feedback latency:** one targeted pytest run per task (seconds); PG tasks carry a `TEST_DATABASE_URL` precondition and fail on a skipped `_pg` test.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 19-01-01 | 01 | 1 | EXEC-01 | T-19-02 | NOT_CONFIGURED limits refuse live readiness, keys named | unit | `uv run pytest -m "not docker" tests/test_execution_limits.py -x` | ✅ | ✅ green |
| 19-01-02 | 01 | 1 | EXEC-01 | T-19-03 | malformed limits refused by name, never by value | unit | `uv run pytest -m "not docker" tests/test_execution_limits.py -x` | ✅ | ✅ green |
| 19-01-03 | 01 | 1 | EXEC-01 | T-19-01 | no numeric default for the four keys in src/scripts | static scan | `uv run pytest -m "not docker" tests/test_no_unratified_defaults.py tests/test_phase18_gate.py tests/test_execution_limits.py tests/test_binance_limits_ratified_file.py -x` | ✅ | ✅ green |
| 19-02-01 | 02 | 1 | APRV-02, APRV-01 | T-19-05 | hash re-derived with the frozen algorithm; symbol/side from Signal | unit | `uv run pytest -m "not docker" tests/test_execution_binding.py tests/test_core_planner.py -x` | ✅ | ✅ green |
| 19-02-02 | 02 | 1 | APRV-01, RISK-04 | T-19-04, T-19-06 | caller symbol/side/quantity mismatch refused, never clipped | unit grid | `uv run pytest -m "not docker" tests/test_execution_binding.py -x` | ✅ | ✅ green |
| 19-02-03 | 02 | 1 | EXEC-01 | T-19-04 | snapped stop reaching the zone edge refused (G4-020) | unit grid | `uv run pytest -m "not docker" tests/test_execution_binding.py tests/test_execution_price_ticks.py -x` | ✅ | ✅ green |
| 19-03-01 | 03 | 1 | EXEC-01 | T-19-07, T-19-08 | crossed/outside/stale mark price refuses | unit | `uv run pytest -m "not docker" tests/test_pre_placement.py -x` | ✅ | ✅ green |
| 19-03-02 | 03 | 1 | EXEC-01 | T-19-07 | status deny-list, distinct invalidation code, GTD floor | unit + parity | `uv run pytest -m "not docker" tests/test_pre_placement.py tests/test_backtest_entry.py -x` | ✅ | ✅ green |
| 19-03-03 | 03 | 1 | RISK-04 | T-19-09 | busy symbol / unprotected position / Hedge refuse | unit | `uv run pytest -m "not docker" tests/test_pre_placement.py -x` | ✅ | ✅ green |
| 19-04-01 | 04 | 1 | EXEC-01 | T-19-10 | one valid MARKET part within limits | unit | `uv run pytest -m "not docker" tests/test_market_lot_split.py -x` | ✅ | ✅ green |
| 19-04-02 | 04 | 1 | EXEC-01 | T-19-10, T-19-11 | split above max, impossible part reported | exhaustive grid | `uv run pytest -m "not docker" tests/test_market_lot_split.py -x` | ✅ | ✅ green |
| 19-04-03 | 04 | 1 | EXEC-01 | T-19-11 | floor-only quantizer, unknown filters give None | unit | `uv run pytest -m "not docker" tests/test_market_lot_split.py tests/test_constraint_snapshot.py -x` | ✅ | ✅ green |
| 19-05-01 | 05 | 1 | EXEC-01 | T-19-12 | mark price validated, never fabricated; gate refusal sends nothing | unit (fake SDK) | `uv run pytest -m "not docker" tests/test_live_mark_price_adapter.py -x` | ✅ | ✅ green |
| 19-05-02 | 05 | 1 | EXEC-01 | T-19-13 | GTD needs goodTillDate; GTC wire unchanged | unit (fake SDK) | `uv run pytest -m "not docker" tests/test_binance_entry_gtd.py tests/test_binance_usdm_source_guard.py tests/test_execution_adapter_contract.py tests/test_binance_usdm_signed_calls.py -x` | ✅ | ✅ green |
| 19-05-03 | 05 | 1 | EXEC-01 | T-19-12 | executed quantity on probe, None when absent | unit | `uv run pytest -m "not docker" tests/test_binance_entry_gtd.py tests/test_execution_manager.py tests/test_execution_exactly_once_pg.py -x` | ✅ | ✅ green |
| 19-06-01 | 06 | 1 | EXEC-02 | T-19-16 | owner confirms the one-way schema door | checkpoint:decision (blocking-human) | n/a (owner answer recorded in SUMMARY) | n/a | ⚠️ manual |
| 19-06-02 | 06 | 1 | EXEC-02 | T-19-15 | column + CHECK, ORM parity, head-agnostic tests | PG | `uv run pytest -m "not docker" tests/test_pg_fixture_guard.py tests/test_execution_exactly_once_pg.py tests/test_persistence_migration_pg.py -x -rs` | ✅ | ✅ green |
| 19-06-03 | 06 | 1 | EXEC-02 | T-19-16 | reversible, data-bearing 0004 -> 0005 | PG | `uv run pytest -m "not docker" tests/test_persistence_migration_pg.py -x -rs` | ✅ | ✅ green |
| 19-07-01 | 07 | 2 | EXEC-01 | T-19-17 | TP legs from the real position | unit | `uv run pytest -m "not docker" tests/test_tp_sizing.py -x` | ✅ | ✅ green |
| 19-07-02 | 07 | 2 | EXEC-01 | T-19-17 | minQty/MIN_NOTIONAL refusal, no fallback (O-03); Hedge payloads offline | unit grid | `uv run pytest -m "not docker" tests/test_tp_sizing.py -x` | ✅ | ✅ green |
| 19-07-03 | 07 | 2 | EXEC-07 | T-19-18 | byte-identical to the frozen sizing; fraction unchanged | regression | `uv run pytest -m "not docker" tests/test_tp_sizing.py tests/test_execution_modes.py tests/test_backtest_exits.py -x` | ✅ | ✅ green |
| 19-08-01 | 08 | 2 | EXEC-01 | T-19-19, T-19-20 | single reduce-only MARKET close, not blocked by drift guard | unit (fake SDK) | `uv run pytest -m "not docker" tests/test_binance_market_close_adapter.py tests/test_binance_usdm_source_guard.py tests/test_paper_shadow_isolation.py -x` | ✅ | ✅ green |
| 19-08-02 | 08 | 2 | EXEC-01 | T-19-21 | pre-send refusals carry the PreSendRefusal marker | unit | `uv run pytest -m "not docker" tests/test_binance_market_close_adapter.py tests/test_exchange_errors.py tests/test_binance_ratelimit_gate.py tests/test_binance_usdm_signed_calls.py tests/test_binance_usdm_error_routing.py -x` | ✅ | ✅ green |
| 19-08-03 | 08 | 2 | EXEC-01 | T-19-19 | live lot filters or raise | unit | `uv run pytest -m "not docker" tests/test_binance_market_close_adapter.py tests/test_symbol_filters_extra.py -x` | ✅ | ✅ green |
| 19-09-01 | 09 | 2 | EXEC-02 | T-19-22 | sized risk stored at consume and read back | PG | `uv run pytest -m "not docker" tests/test_realized_risk_persistence_pg.py tests/test_analytics_live_outcomes.py -x -rs` | ✅ | ✅ green |
| 19-09-02 | 09 | 2 | EXEC-01 | T-19-23 | TP intent quantity across store and five doubles | PG + unit | `uv run pytest -m "not docker" tests/test_realized_risk_persistence_pg.py tests/test_execution_manager.py tests/test_intent_recovery.py tests/test_execution_write_ahead_pg.py tests/test_execution_exactly_once_pg.py tests/test_intent_recovery_pg.py tests/test_persistence_approvals_pg.py -x -rs` | ✅ | ✅ green |
| 19-09-03 | 09 | 2 | EXEC-02 | T-19-22 | CHECK and store parity | PG | `uv run pytest -m "not docker" tests/test_realized_risk_persistence_pg.py tests/test_analytics_live_outcomes.py tests/test_analytics_purity.py -x -rs` | ✅ | ✅ green |
| 19-10-01 | 10 | 3 | EXEC-01 | T-19-24 | fake binds real signatures; partial fill; -4509 flat | unit | `uv run pytest -m "not docker" tests/test_fake_exchange_v2.py tests/test_execution_exactly_once_pg.py tests/test_execution_write_ahead_pg.py -x` | ✅ | ✅ green |
| 19-10-02 | 10 | 3 | EXEC-01 | T-19-25 | exchange answers with provenance labels | unit | `uv run pytest -m "not docker" tests/test_fake_exchange_v2.py -x` | ✅ | ✅ green |
| 19-10-03 | 10 | 3 | EXEC-01 | T-19-24 | deterministic race gates | unit | `uv run pytest -m "not docker" tests/test_fake_exchange_v2.py -x` | ✅ | ✅ green |
| 19-11-01 | 11 | 4 | EXEC-01, EXEC-02 | T-19-26, T-19-27 | fill -> stop + cancel together -> REST-confirmed PROTECTED | async + fake | `uv run pytest -m "not docker" tests/test_protection_coordinator.py -x` | ✅ | ✅ green |
| 19-11-02 | 11 | 4 | EXEC-01, RISK-04 | T-19-26, T-19-28 | REST-only fill, zero-fill terminal, start-together proof | async + fake | `uv run pytest -m "not docker" tests/test_protection_coordinator.py -x` | ✅ | ✅ green |
| 19-11-03 | 11 | 4 | EXEC-01 | T-19-26 | stream frame through the router into protection | rig | `uv run pytest -m "not docker" tests/test_protection_router_rig.py tests/test_protection_coordinator.py tests/test_userdata_rig.py -x` | ✅ | ✅ green |
| 19-12-01 | 12 | 5 | EXEC-01 | T-19-30 | one-part reduce-only close by deterministic id | async + fake | `uv run pytest -m "not docker" tests/test_emergency_market_close.py tests/test_execution_emergency.py -x` | ✅ | ✅ green |
| 19-12-02 | 12 | 5 | EXEC-01 | T-19-30 | split parts, impossible part -> SAFE_MODE + alert | async + fake | `uv run pytest -m "not docker" tests/test_emergency_market_close.py -x` | ✅ | ✅ green |
| 19-12-03 | 12 | 5 | EXEC-01, RISK-04 | T-19-29, T-19-31 | query before resend, no duplicate close, refusal not sent | async + fake | `uv run pytest -m "not docker" tests/test_emergency_market_close.py tests/test_binance_usdm_source_guard.py -x` | ✅ | ✅ green |
| 19-13-01 | 13 | 6 | APRV-01, APRV-02 | T-19-32 | binding gate before any adapter call; replay first | unit | `uv run pytest -m "not docker" tests/test_execution_manager.py -x` | ✅ | ✅ green |
| 19-13-02 | 13 | 6 | EXEC-01, RISK-04 | T-19-33, T-19-34 | pre-placement refusals never consume the approval; Hedge refused | unit | `uv run pytest -m "not docker" tests/test_execution_manager.py tests/test_execution_modes.py tests/test_execution_attach.py tests/test_exchange_error_rejections.py -x` | ✅ | ✅ green |
| 19-13-03 | 13 | 6 | EXEC-01 | T-19-34 | rehearsal aborts before mutation while limits unset | integration (fakes) | `uv run pytest -m "not docker" tests/test_demo_rehearsal_flow.py tests/test_demo_rehearsal_safety.py tests/test_execution_manager.py -x` | ✅ | ✅ green |
| 19-14-01 | 14 | 6 | EXEC-01 | T-19-35, T-19-37 | B5 -2021 -> CLOSE_REQUIRED -> flat, no blind resend | async race | `uv run pytest -m "not docker" tests/test_protection_branches.py tests/test_protection_coordinator.py -x` | ✅ | ✅ green |
| 19-14-02 | 14 | 6 | EXEC-01, EXEC-02 | T-19-35 | B1/B2/B3 deadlines on virtual time | async race | `uv run pytest -m "not docker" tests/test_protection_branches.py -x` | ✅ | ✅ green |
| 19-14-03 | 14 | 6 | RISK-04 | T-19-36, T-19-38 | B4 never re-places the stop; -4509; Q4 refusal journaled | async race | `uv run pytest -m "not docker" tests/test_protection_branches.py tests/test_protection_coordinator.py tests/test_emergency_market_close.py -x` | ✅ | ✅ green |
| 19-15-01 | 15 | 7 | EXEC-01 | T-19-39, T-19-41 | GTD entry, no entry-time stop, hand-off or SAFE_MODE | unit | `uv run pytest -m "not docker" tests/test_execution_manager.py -x` | ✅ | ✅ green |
| 19-15-02 | 15 | 7 | EXEC-01 | T-19-40 | pre-send refusal NO_TRADE without SAFE_MODE/UNKNOWN | unit | `uv run pytest -m "not docker" tests/test_execution_manager.py tests/test_exchange_error_rejections.py tests/test_binance_usdm_source_guard.py tests/test_protection_branches.py -x` | ✅ | ✅ green |
| 19-15-03 | 15 | 7 | EXEC-02, APRV-02 | T-19-39 | write-ahead rows for the new flow; replay unchanged | PG + rehearsal | `uv run pytest -m "not docker" tests/test_execution_write_ahead_pg.py tests/test_approval_replay_pg.py tests/test_execution_exactly_once_pg.py tests/test_demo_rehearsal_flow.py tests/test_demo_rehearsal_safety.py -x -rs` | ✅ | ✅ green |
| 19-16-01 | 16 | 8 | EXEC-01, APRV-01 | T-19-42 | attach adopts confirmed stop, TP from real position | unit + fake | `uv run pytest -m "not docker" tests/test_execution_attach.py tests/test_exchange_error_rejections.py tests/test_binance_usdm_signed_calls.py -x` | ✅ | ✅ green |
| 19-16-02 | 16 | 8 | EXEC-01, EXEC-07 | T-19-43, T-19-44 | snapshot gate, TP_UNAVAILABLE, no TP1 resize, exit sweep | async + fake | `uv run pytest -m "not docker" tests/test_protection_take_profits.py tests/test_protection_branches.py tests/test_protection_coordinator.py tests/test_execution_attach.py -x` | ✅ | ✅ green |
| 19-16-03 | 16 | 8 | EXEC-01 | T-19-42 | rehearsal fill flow through the coordinator | integration (fakes) | `uv run pytest -m "not docker" tests/test_demo_rehearsal_flow.py tests/test_demo_rehearsal_safety.py -x` | ✅ | ✅ green |
| 19-17-01 | 17 | 9 | all six | T-19-45, T-19-46 | structural gate, purity, secret posture | static | `uv run pytest -m "not docker" tests/test_phase19_gate.py tests/test_execution_secret_posture.py tests/test_phase18_gate.py -x` | ✅ | ✅ green |
| 19-17-02 | 17 | 9 | EXEC-01 | T-19-45 | GLOSSARY 9.3/9.4 rows, enum unchanged | doc gate | `uv run python scripts/verify_decision_alignment.py glossary` | ✅ | ✅ green |
| 19-17-03 | 17 | 9 | EXEC-07 | T-19-45 | owner-gap register complete; EXEC-07 Pending note | doc gate + human-check | `uv run python scripts/verify_decision_alignment.py reqs` | ✅ | ✅ green |
| WR-01-a | review-fix 4 | post | APRV-01, RISK-04 | WR-01 (D078) | approved quantity stored on the approval row and bound at placement; NULL/unequal refused | unit + PG | `uv run pytest -m "not docker" tests/test_execution_binding.py tests/test_persistence_approvals_pg.py tests/test_persistence_migration_pg.py -x` | ✅ | ✅ green |
| WR-01-b | quick q2d | post | APRV-01, RISK-04 | WR-01 (D078 (7)) | consume re-reads the stored quantity under FOR UPDATE; inconsistent value enters SAFE_MODE, NULL does not | PG + unit | `uv run pytest -m "not docker" tests/test_consume_approved_quantity_pg.py tests/test_execution_manager.py -x` | ✅ | ✅ green |
| WR-01-c | quick r3b | post | APRV-01 | WR-01 (D078 (6)) | APPROVE and Demo messages show the stored quantity; Demo refuses an approval without one | unit | `uv run pytest -m "not docker" tests/test_approval_message.py tests/test_paper_shadow_messages.py tests/test_demo_rehearsal_flow.py -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

No separate Wave 0 plan: each new test file is created RED by the task that needs it (TDD mode). Shared test infrastructure is built before its consumers:

- [x] `tests/support/execution_limits.py` — TEST_ONLY limits (plan 19-01, wave 1)
- [x] `tests/support/fake_binance_exchange.py` v2 — positions, partial fills, -4509, MARKET close, race gates (plan 19-10, wave 3; consumers 19-11 onward)
- [x] `tests/support/protection_doubles.py` — RecordingAlerts, ScriptedEmergencyCloser, resting_entry_for_tests (plan 19-11, wave 4)
- [x] `tests/support/intent_store_fakes.py` — five doubles with the new Protocol parameters (plan 19-09, wave 2)
- [x] `tests/pg_support.py` `alembic_head_revision()` — head-agnostic migration tests (plan 19-06, wave 1)
- [ ] Framework install: none (no package added by this phase).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Owner confirms the migration 0005 schema door | EXEC-02 (D-22) | one-way schema change; plan 19-06 Task 1 is a blocking-human decision checkpoint | answer "column-on-entry-intent" or "defer-d22"; the answer is recorded in 19-06-SUMMARY.md |
| Owner reviews the owner-gap register | all six | O-01..O-05, Q3-Q5 are owner decisions; harvested `<human-check>` of plan 19-17 Task 3 | read 19-OWNER-GAPS.md; confirm every open item is listed and none is presented as solved |
| 11 Demo probes of 19-NOTES.md (closePosition with a position open, real stop trigger, partial fill, entry rejected/canceled/expired, stop rejected and stream lost, close by another mechanism, fill/cancel/trigger race, -2021 after a fill, emergency MARKET close, TP1 from the real fill, cleanup) | EXEC-01, EXEC-02 (Demo-proven evidence, Phases 24/25) | O-05: the owner runs every `--execute`; no executor runs a Binance mutation | owner-run with scripts/demo_probe.py or the rehearsal, evidence recorded by the owner; these settle A2-A6 and A8 and gate the D055 closure (O-01) |

Offline behaviors of criteria 1-4 all have automated verification; Demo and mainnet behavior is not claimed by this phase.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 19s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** {pending / approved YYYY-MM-DD}

## Validation Audit 2026-10-20

| Metric | Count |
|---|---|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |
