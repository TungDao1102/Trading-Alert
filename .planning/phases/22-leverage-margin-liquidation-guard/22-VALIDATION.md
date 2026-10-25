---
phase: "22"
slug: leverage-margin-liquidation-guard
status: validated
nyquist_compliant: true
wave_0_complete: true
created: "2026-10-25"
---

# Phase 22 — Validation Strategy

> Per-phase validation contract. Audited after execution (State B: no prior VALIDATION.md).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (asyncio_mode = auto) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest -m "not docker" <files> -p no:xdist -o addopts="" -q` |
| **PG run command** | `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_risk_reservation_margin_pg.py -p no:xdist -o addopts="" -q` (needs `TEST_DATABASE_URL`) |
| **Full suite command** | `uv run pytest -m "not docker" -n 4` |
| **Estimated runtime** | about 11 s for the audit files; the full suite is 9 to 10 min |

---

## Sampling Rate

- **After every task commit:** the quick run command on the touched files
- **After every plan wave:** the files of that wave's plans (map below)
- **Before verify-work:** full suite once per phase (orchestrator)
- **Max feedback latency:** about 11 s

---

## Per-Task Verification Map

Command for every row: `uv run pytest -m "not docker" <files> -p no:xdist -o addopts="" -q` (files under `tests/`).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Files | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------|-------------|--------|
| 22-01 | 01 | 1 | recorded Demo fixtures, leverage/margin adapter reads | fail closed | fixtures are generated, reads typed | unit | `test_phase22_fixtures.py`, `test_leverage_margin_adapter.py` | yes | green |
| 22-02 | 02 | 1 | execution limits keys | fail closed | NOT_CONFIGURED stays refused | unit | `test_execution_limits.py` | yes | green |
| 22-03 | 03 | 1 | -4046/-4048 error mapping | fail closed | typed exchange errors | unit | `test_exchange_errors.py` | yes | green |
| 22-04 | 04 | 1 | margin check | fail closed | claims, headroom, UNKNOWN refuses | unit | `test_margin_check.py` | yes | green |
| 22-05 | 05 | 2 | Demo probe cases (SJ3) | DRY_RUN rule | probe cases | unit | `test_demo_probe_sj3_cases.py` | yes | green |
| 22-06 | 06 | 2 | signed calls | secrets | signed-call policy | unit | `test_leverage_margin_adapter.py`, `test_binance_usdm_signed_calls.py` | yes | green |
| 22-07 | 07 | 2 | liquidation price (criterion 2) | fail closed | goldens plus independent first-crossing oracle, 300 cases | unit | `test_liquidation_price.py`, `test_liquidation_price_oracle.py` | yes | green |
| 22-08 | 08 | 2 | reservation margin trio and claims reader | fail closed | derived margin; claims feed the verdict end to end on PG | integration (PG) | `test_risk_reservations.py`, `test_risk_reservation_margin_pg.py` | yes | green |
| 22-09 | 09 | 3 | SJ3 Demo cases | DRY_RUN rule | probe cases | unit | `test_demo_probe_sj3_cases.py` | yes | green |
| 22-10 | 10 | 3 | account reads and equity | fail closed | equity source | unit | `test_account_reads_adapter.py`, `test_account_equity_source.py`, `test_live_equity.py` | yes | green |
| 22-11 | 11 | 3 | symbol config guard | D035 | verified margin type and leverage | unit | `test_symbol_config_guard.py` | yes | green |
| 22-12 | 12 | 3 | bracket cache | fail closed | stale brackets refused | unit | `test_bracket_cache.py` | yes | green |
| 22-13 | 13 | 4 | post-fill liquidation watch | O-4 policy | CLOSE_POSITION closes, ALERT_ONLY alerts once, restored plan not closed | unit | `test_liquidation_watch.py`, `test_protection_liquidation.py`, `test_protection_rebuild.py` | yes | green |
| 22-14 | 14 | 4 | margin guard | fail closed | MarginGuard end to end | unit | `test_margin_guard.py` | yes | green |
| 22-15 | 15 | 5 | manager wiring, snapshot, rehearsal | DRY_RUN rule | `_symbol_is_flat` truth table, factory in DRY_RUN sends no POST | unit/integration | `test_execution_manager.py`, `test_snapshot_margin_leverage.py`, `test_demo_rehearsal_flow.py`, `test_demo_rehearsal_safety.py` | yes | green |
| 22-16 | 16 | 5 | phase gate invariants | machine-enforced | AST and invariant guards | gate | `test_phase22_gate.py` | yes | green |
| RF-WR-01 | fix | 6 | no config POST for a pure-refused plan | fail closed | `test_a_plan_refused_by_a_pure_check_leaves_the_recorded_account_untouched` | unit | `test_margin_guard.py` | yes | green |
| RF-WR-02 | fix | 6 | aged mark refused before the consume | fail closed | `test_a_mark_price_that_ages_during_the_guard_is_refused_before_the_consume` | unit | `test_execution_manager.py` | yes | green |
| RF-WR-03 | fix | 6 | restored plan without leverage not closed | no false close | `test_a_missing_leverage_does_not_decide_a_passing_exchange_value`; audit: `test_a_plan_restored_through_the_rebuild_path_without_a_leverage_is_not_closed` | unit | `test_liquidation_watch.py`, `test_protection_liquidation.py` | yes | green |
| RF-WR-04 | fix | 6 | ALERT_ONLY never closes | O-4 | `test_alert_only_policy_alerts_instead_of_closing_on_the_error_paths`; audit: `test_alert_only_with_the_real_watch_alerts_once_inside_the_buffer_and_never_closes` | unit | `test_protection_liquidation.py` | yes | green |
| RF-WR-05 | fix | 6 | OK_DIFFERS raises no alert | N/A | `test_ok_differs_journals_both_exact_prices_and_raises_no_alert` | unit | `test_protection_liquidation.py` | yes | green |
| RF-WR-06 | fix | 6 | claim circuit: derived amount, ack instant | fail closed | `test_invariant_21_the_claim_amount_is_derived_and_the_placed_instant_is_the_ack` (contract only; see Manual-Only) | gate | `test_phase22_gate.py` | yes | green |
| RF-WR-07 | fix | 6 | required_margin = quantity x price / leverage | fail closed | `test_margin_for_reservation_is_quantity_times_price_over_leverage`, `test_a_stored_margin_that_differs_from_the_derived_one_reads_as_an_unknown_claim`, audit PG tests (consistent peer reduces headroom; None or inconsistent peer gives UNCERTAIN_ACCOUNT_STATE) | unit/PG | `test_risk_reservations.py`, `test_risk_reservation_margin_pg.py` | yes | green |
| RF-WR-08 | fix | 6 | guard built over the GuardedAdapter, no POST in DRY_RUN | DRY_RUN rule | `test_a_real_guard_over_the_guarded_adapter_sends_no_post_in_a_dry_run`; audit: `test_main_in_dry_run_builds_the_guard_once_over_the_guarded_adapter_and_sends_no_post` | integration | `test_demo_rehearsal_flow.py` | yes | green |
| RF-WR-09 | fix | 6 | 5x cap inside MarginGuard | D035 | `test_construction_refuses_a_target_leverage_above_the_d035_cap` | unit | `test_margin_guard.py` | yes | green |

*Status: green = ran and passed. Audit run of the 6 touched files with `TRADING_CI_STRICT=1` and `TEST_DATABASE_URL` set: `325 passed in 10.93s`.*

Audit additions (commit `7fa14af3`): `tests/test_liquidation_price_oracle.py`; ALERT_ONLY and restored-plan tests in `tests/test_protection_liquidation.py` (helper `_restart(liquidation_watch=...)` in `tests/test_protection_rebuild.py`); three PG claims-to-verdict tests; `_symbol_is_flat` truth table; `main()` with `margin_guard_factory` in DRY_RUN.

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `placed_at_utc` stamped at the exchange ack | WR-06 | No src caller of `mark_placed` until Phase 24; contract only by docstring and gate invariant 21 | Re-check when Phase 24 wires placement |
| DB-level per-symbol arbiter across processes | claims race | Needs a migration; owner decision or Phase 24 | Phase 24 |
| Criteria 1 to 3 through the guard on Demo | criteria 1-3 | Exchange-only proof | Owner-run Demo probe |
| Short and higher-tier isolated `liquidationPrice` samples | liquidation formula | Exchange-only; the oracle proves agreement with the closed form's own condition, not with the exchange | Owner-run Demo samples |
| Real -4048 / -4046 payloads | error mapping | Exchange-only | Owner-run Demo |
| `availableBalance` netting (A1) | claims | Exchange-only | Mainnet sample at Phase 26 canary |
| Any mainnet behavior | all | No mainnet use | Phase 26 |

---

## Validation Sign-Off

- [x] All tasks have automated verify
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15 s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-10-25

## Validation Audit 2026-10-25

| Metric | Count |
|---|---|
| Gaps found | 8 |
| Resolved | 6 |
| Escalated | 0 |
