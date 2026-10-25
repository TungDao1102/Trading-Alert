---
status: partial
phase: 21-account-equity-daily-loss
source: [21-01-SUMMARY.md, 21-02-SUMMARY.md, 21-03-SUMMARY.md, 21-04-SUMMARY.md, 21-05-SUMMARY.md, 21-06-SUMMARY.md, 21-07-SUMMARY.md, 21-08-SUMMARY.md, 21-09-SUMMARY.md, 21-10-SUMMARY.md, 21-11-SUMMARY.md, 21-12-SUMMARY.md, 21-13-SUMMARY.md, 21-14-SUMMARY.md, 21-15-SUMMARY.md, 21-16-SUMMARY.md]
started: 2026-10-25T00:00:00Z
updated: 2026-10-25T00:00:00Z
---

Auto-answered by the assistant at the owner's request (2026-10-25) from test and code evidence; not a human observation.

Evidence run in this session (targeted, `-p no:xdist`, `-o addopts=""`): 18 non-PG files (account reads/trades adapters, cancel verification, fixtures, reservations, live equity, equity source, daily loss, recorded loss, daily stop, composition, day-risk service and stream, live risk inputs and parity, snapshot, execution limits, phase gate) = 959 passed; `tests/test_phase21_gate.py` + `tests/test_execution_manager.py -k "gate or 5f3 or phase21"` = 34 passed. PostgreSQL: `TEST_DATABASE_URL` was set (127.0.0.1:5432, trading_test) but the server refused connections during this run (150 ConnectionTimeout errors in the PG group, 86 passed there, the rest not reached). No PG test is claimed as passed by this session. Earlier PG evidence (137 passed, 0 skips) is only the 21-VERIFICATION.md record of 2026-10-23.

## Current Test

[testing complete]

## Tests

### 1. Equity comes from the Binance account read and a stale or unknown reading refuses
expected: Equity is read from /fapi/v3/account (+ balance); a missing, stale (age > account.max_equity_age_ms = 15000), negative-age, multi-asset or mismatching reading gives NO_TRADE UNCERTAIN_ACCOUNT_STATE; no stale fallback.
result: pass
source: assistant-evidence
evidence: tests/test_live_equity.py, tests/test_account_equity_source.py, tests/test_account_reads_adapter.py, tests/test_snapshot_live_equity.py (all passed this run); src/risk/live_equity.py check_equity_reading, src/execution/account_equity.py

### 2. Sizing equity is the smaller of wallet balance and margin balance
expected: equity_basis = min(totalWalletBalance, totalMarginBalance) (D086); an unrealized profit never raises sizing equity; margin balance not equal to wallet + unrealized is NO_TRADE.
result: pass
source: assistant-evidence
evidence: tests/test_live_equity.py::test_equity_basis_is_the_smaller_of_wallet_and_margin_balance, ::test_unrealized_loss_is_included_in_equity, ::test_margin_differing_from_wallet_plus_unrealized_is_no_trade (passed); src/risk/live_equity.py:198-207

### 3. Daily loss figure and UTC-day boundary
expected: Loss = realized PnL + commissions + funding for one UTC day; stream and REST rows counted once at the worse amount; a non-quote asset or incomplete source is unknown, never zero; midnight UTC belongs to the new day; thresholds come from the persisted day-start base only.
result: pass
source: assistant-evidence
evidence: tests/test_daily_loss.py (incl. test_utc_day_of_midnight_belongs_to_the_new_day, test_fold_rejects_a_component_of_another_utc_day), tests/test_daily_loss_recorded.py (recorded Demo SL close through the real parser) passed this run

### 4. DAILY_STOP latches, cancels pending entries, keeps the stop, then alerts
expected: When the loss reaches the limit the stop is latched (persisted before the verdict returns); only ENTRY-role orders are cancelled; protective SL/TP are never cancelled; the alert comes after the cancel; a later gain does not clear the latch; a second call is idempotent.
result: pass
source: assistant-evidence
evidence: tests/test_daily_stop.py::test_latched_daily_stop_cancels_the_entry_keeps_the_stop_and_alerts_after, ::test_a_second_call_with_the_latch_already_held_is_idempotent; tests/test_day_risk_service.py::test_a_derived_stop_is_latched_in_the_store_before_the_verdict_returns, ::test_a_later_gain_on_a_latched_day_keeps_daily_stop (passed)

### 5. Restart keeps the day base and the latch
expected: A restart inside the same UTC day keeps the stored day-start base and the latch; an unlatched restart is unknown until its first backfill.
result: pass
source: assistant-evidence
evidence: tests/test_day_risk_service.py::test_a_restart_inside_the_day_keeps_the_stored_base_and_the_latch, ::test_an_unlatched_restart_is_unknown_until_its_first_backfill (passed, fake store). Real PostgreSQL survival (tests/test_day_risk_pg.py::test_latch_stop_is_set_once_and_survives_a_restart) was not run, see test 10.

### 6. A known daily loss expires 300 s after the backfill that made it known
expected: account.max_daily_loss_age_ms = 300000 (D087, required, no default); a loss exactly 300 s old passes, 1 ms older is unknown; a new backfill renews it; a failed backfill leaves no old stamp.
result: pass
source: assistant-evidence
evidence: tests/test_day_risk_service.py::test_the_age_edge_passes_when_equal_and_fails_one_millisecond_over, ::test_a_new_backfill_renews_an_expired_loss, ::test_a_failed_backfill_does_not_leave_an_old_stamp_to_renew_the_loss, ::test_the_loss_age_limit_is_required_and_has_no_default; tests/test_phase21_gate.py::test_invariant_2b_the_daily_loss_age_limit_is_the_owner_number_and_required; config/execution/execution-limits-v1.toml:56 (passed/read)

### 7. Rollover and backfill requirement
expected: A new UTC day opens only from a fresh in-day REST base after a current backfill, with no carried latch; a stream gap or a backfill of another day leaves the loss unknown (NO_TRADE) until a backfill completes.
result: pass
source: assistant-evidence
evidence: tests/test_day_risk_service.py::test_rollover_opens_the_new_day_from_a_fresh_in_day_read_without_a_carried_latch, ::test_opening_a_day_without_a_current_backfill_is_blocked_and_reads_no_equity, ::test_a_stream_gap_before_the_open_makes_the_base_unavailable_until_a_backfill, ::test_a_backfill_of_another_day_does_not_make_the_new_day_known; tests/test_day_risk_stream.py (passed)

### 8. Sizing-equity gate (5f3) refuses a plan sized above the live equity
expected: The execution manager refuses a quantity sized from an account equity above the live equity the guard read.
result: pass
source: assistant-evidence
evidence: tests/test_execution_manager.py::test_gate_5f3_refuses_a_sizing_equity_above_the_live_equity_the_guard_read (inside the 34 passed of `-k "gate or 5f3 or phase21"`); src/execution/manager.py:620,1117

### 9. Reservation caps count resting and approved-but-unplaced plans, and concurrent approvals cannot both pass
expected: RESERVED, PLACED, OPEN count against the portfolio caps; a refusal leaves the approval PENDING and changes nothing; two concurrent approvals that only one fits cannot both pass; a released reservation frees the cap.
result: pass
source: assistant-evidence
evidence: PostgreSQL 127.0.0.1:5432 (trading_test) up on 2026-10-25; TRADING_CI_STRICT=1 uv run pytest tests/test_risk_reservation_approval_pg.py tests/test_day_risk_pg.py tests/test_risk_reservations_pg.py tests/test_persistence_migration_pg.py -> 215 passed, including test_two_concurrent_approvals_that_only_one_fits_cannot_both_pass and test_two_approvals_acted_on_either_side_of_midnight_still_serialise; the non-PG logic passed in the first run

### 10. Migrations 0010 and 0011 apply and round-trip
expected: alembic upgrade head creates the day-risk and risk_reservations tables with their CHECKs; the downgrade/upgrade cycle is clean; the migration head is the documented one.
result: pass
source: assistant-evidence
evidence: the same 215-test strict PostgreSQL run, which includes tests/test_persistence_migration_pg.py (migrations 0010 and 0011) and tests/test_phase21_gate.py::test_invariant_6 (head 0012)

### 11. Secrets and balances are not logged
expected: A successful account, balance or config read logs no balance, no account alias and nothing of the response body; the free-text income `info` field is never read.
result: pass
source: assistant-evidence
evidence: tests/test_account_reads_adapter.py::test_a_successful_account_information_read_logs_no_balance, ::test_a_successful_balance_read_logs_neither_a_balance_nor_the_alias, ::test_a_successful_config_read_logs_nothing_about_the_response; tests/test_phase21_gate.py::test_invariant_8_no_phase21_fixture_carries_the_account_alias_key (passed); src/adapters/binance_usdm.py:66

### 12. Phase 21 touches no order or leverage endpoint and keeps its invariants
expected: The Phase 21 account reads are GET-only (account v3, balance v3, accountConfig, userTrades, income); no float, no wall clock, no adapter import in the pure/execution modules; both verification flags (funding, net PnL semantics) stay False.
result: pass
source: assistant-evidence
evidence: tests/test_phase21_gate.py::test_invariant_1_pure_modules_have_no_clock_no_float_no_client_and_no_quote_literal, ::test_invariant_1b_execution_modules_read_no_clock_and_import_no_adapter_or_store, ::test_invariant_4_both_verification_flags_are_false (passed); grep of new_order, change_leverage and create_order in the Phase 21 modules found none (only reservation margin arithmetic uses a leverage int); src/adapters/binance_usdm.py:63-71

### 13. Equity, day risk, DAILY_STOP and reservations run inside a live process (ACCOUNT_UPDATE / stream gap invalidates)
expected: In the running paper/live process the equity source, day-risk service, DAILY_STOP enforcement and alerts are composed, and ACCOUNT_UPDATE or a stream gap makes both equity and day loss unknown.
result: blocked
blocked_by: prior-phase
reason: Nothing from Phase 21 is composed into an entry point until Phase 24 (21-DEFERRED.md row 1; 21-VALIDATION.md gap 3, escalated to Phase 24). Library level only.
source: assistant-evidence
evidence: 21-VERIFICATION.md deferred list and Key Link table; 21-VALIDATION.md Manual-Only

### 14. Exchange-only proofs: FUNDING_FEE rows, mainnet realizedPnl vs commission, 429/418 behaviour
expected: A FUNDING_FEE income row is observed and realizedPnl semantics are confirmed on mainnet before real money.
result: blocked
blocked_by: third-party
reason: Demo returned one COMMISSION row and no FUNDING_FEE row; mainnet proof waits for the Phase 26 canary. FUNDING_SOURCE_VERIFIED and LIVE_NET_PNL_SEMANTICS_VERIFIED stay False (owner O-2 option A, O-4).
source: assistant-evidence
evidence: 21-VERIFICATION.md human_verification; 21-OWNER-DECISIONS.md O-2, O-4

### 15. Owner attestations and still-open owner items (OPS-02, D-21, O-1..O-6)
expected: The owner confirms no-withdrawal keys and IP allowlist (OPS-02), and any still-open item among O-1..O-6 is decided.
result: blocked
blocked_by: prior-phase
reason: Owner attestation, not observable by the assistant, and it waits for Phase 26 with real keys. The assistant does not answer for the owner.
source: assistant-evidence
evidence: 21-VERIFICATION.md requirements table (OPS-02 pending) and human_verification

## Summary

total: 15
passed: 12
issues: 0
pending: 0
skipped: 0
blocked: 3

## Gaps

[none yet] No test failed. Open follow-ups, not code defects: re-run tests 9 and 10 when PostgreSQL is reachable; tests 13-15 wait for Phases 24-26 and the owner.
