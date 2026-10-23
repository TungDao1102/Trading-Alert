---
phase: 21-account-equity-daily-loss
verified: 2026-10-23T00:00:00Z
status: human_needed
score: 3/3 roadmap success criteria verified at library level (0 behavior-unverified, 0 gaps)
covered_files:
  - .planning/phases/21-account-equity-daily-loss/21-01-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-01-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-02-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-02-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-03-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-03-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-04-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-04-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-05-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-05-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-06-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-06-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-07-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-07-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-08-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-08-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-09-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-09-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-10-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-10-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-11-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-11-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-12-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-12-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-13-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-13-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-14-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-14-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-15-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-15-SUMMARY.md
  - .planning/phases/21-account-equity-daily-loss/21-16-PLAN.md
  - .planning/phases/21-account-equity-daily-loss/21-16-SUMMARY.md
  - src/adapters/binance_usdm.py
  - src/db/alembic/versions/0010_daily_risk_state.py
  - src/db/alembic/versions/0011_risk_reservations.py
  - src/execution/account_equity.py
  - src/execution/daily_stop.py
  - src/execution/day_risk_service.py
  - src/execution/execution_limits.py
  - src/execution/live_risk_inputs.py
  - src/persistence/day_risk.py
  - src/persistence/risk_reservations.py
  - src/risk/daily_loss.py
  - src/risk/live_equity.py
  - src/risk/reservations.py
  - tests/test_phase21_gate.py
covered_digest: "v3:sha256:0f3f83e61a67eb71c889538b5739044b010585f2f09f71d8b23c491c53a43ad3"
behavior_unverified: 0
overrides_applied: 0
gaps: []
deferred:
  - truth: "Equity source, day-risk service, DAILY_STOP enforcement, reservation calls and alert producers run inside a live process"
    addressed_in: "Phase 24"
    evidence: "21-CONTEXT.md out of scope and 21-DEFERRED.md row 1; no entry point constructs any of them (grep of src, scripts, deploy)"
  - truth: "Mainnet/Demo proof of realizedPnl-versus-commission (G2-042) and of FUNDING_FEE income rows"
    addressed_in: "Phase 24 / 26"
    evidence: "ROADMAP inherited item G2-042; 21-DEFERRED.md rows 'Funding-source evidence' and 'Mainnet verification'"
  - truth: "Margin type and leverage in the plan constraint snapshot (snapshot COMPLETE)"
    addressed_in: "Phase 22"
    evidence: "ROADMAP Phase 22 goal; tests/test_snapshot_live_equity.py shows INCOMPLETE until then"
human_verification:
  - test: "O-1: set a value for `account.max_equity_age_ms` (and a day-row retention) in config/execution/execution-limits-v1.toml"
    expected: "Owner number recorded with provenance; until then LiveEquitySource refuses to construct (ExecutionLimitsNotConfigured), so live equity is NO_TRADE by design"
    why_human: "Owner-only number; the code carries no default and the key is NOT_CONFIGURED"
  - test: "O-3, O-4, O-5, O-6: owner decisions (multi-asset margin, hard stop on unverified realizedPnl, equity basis vs backtest, latch vs backtest)"
    expected: "Each decided in a DECISIONS row or left at the built default"
    why_human: "OPEN by design in 21-OWNER-DECISIONS.md; the verifier does not decide them"
  - test: "Pre-canary funding check (assistant recommendation under O-2, which the owner decided as option A): observe one FUNDING_FEE income row, or hold a small Demo position across a funding settlement, or reconcile wallet balance against the loss components"
    expected: "Evidence that funding is counted before real money; `FUNDING_SOURCE_VERIFIED` changes only with a DECISIONS row"
    why_human: "Needs a running Demo process and exchange time; Demo income returned one COMMISSION row and no FUNDING_FEE row on 2026-10-23 (demo-observed, not mainnet)"
---

# Phase 21: Account Equity + Daily Loss from Binance - Verification Report

**Phase Goal:** Sizing and DAILY_STOP use Binance-canonical equity and the D033 daily-loss definition, never a caller-supplied constant.
**Verified:** 2026-10-23, HEAD 90d10ef7 (branch develop)
**Status:** human_needed
**Re-verification:** No, initial verification

## Scope and evidence labels

Everything below is judged at library level. Nothing Phase 21 built is composed into a running process (grep of `src/`, `scripts/`, `deploy/` finds the new classes only in their own modules, `src/ops/alerts.py` and tests). Phase 24 owns composition. Evidence is of three kinds and none is `[DEMO]` proof of a running process:

- `[TEST-FAKE]` executed tests with scripted readers, an in-memory day store and fake SDK;
- `[TEST-PG]` executed tests on a local PostgreSQL (`TEST_DATABASE_URL` set, 0 skips);
- `[RECORDED]` recorded Demo payloads replayed through the real adapter or parser. Demo facts are demo-observed, not mainnet.

## Goal Achievement

### Observable Truths (ROADMAP success criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Equity comes from `/fapi/v3/account` or `/fapi/v3/balance` plus ACCOUNT_UPDATE, field chosen and documented; unknown or stale equity is NO_TRADE (F-012) | VERIFIED (library level) | Adapter reads `account_information_v3`, `futures_account_balance_v3`, `futures_account_configuration` with strict Decimal parse (`src/adapters/binance_usdm.py:1624-1706`). Field `totalMarginBalance` chosen in `src/risk/live_equity.py:10-16` (`equity_basis`, line 177) and documented in `docs/trading/RISK_MANAGEMENT.md:121`. `check_equity_reading` (`live_equity.py:190-226`) returns NO_TRADE `UNCERTAIN_ACCOUNT_STATE` for missing, stale (age > max or negative), multi-asset, identity mismatch, missing quote or balance row, non-positive equity. ACCOUNT_UPDATE is used as an invalidation trigger, REST stays the truth (`src/execution/account_equity.py:192-205`, `invalidate`); this is the D-01 reading of "plus ACCOUNT_UPDATE" because the event carries deltas, not margin balance. Age bound is the owner key `account.max_equity_age_ms`, NOT_CONFIGURED, required; the source refuses to build while unset (`account_equity.py:127-129`). Snapshot test shows live equity plus stubbed Phase 22 inputs (`tests/test_snapshot_live_equity.py`). [TEST-FAKE][RECORDED] |
| 2 | Daily loss follows D033 (UTC day; realized PnL + commissions + funding; base equity at day start; persisted); at DAILY_STOP pending entries are cancelled and protective SLs kept (F-013, F-963) | VERIFIED (library level) | Fold: `fold_daily_loss` (`src/risk/daily_loss.py:262-340`) sums FILL_PNL, MINUS commission and FUNDING, stream and REST counted once at the most adverse amount, non-quote asset or incomplete sources give unknown, never zero. Thresholds only from the persisted day-start base (`day_thresholds`, line 342-354; no current-equity argument). Sticky latch checked first (`evaluate_day_state`, line 465-480). Persistence: migration `0010_daily_risk_state` (revision chain 0009 to 0010 to 0011), `PgDayRiskStore.open_day` never moves a stored base, `latch_stop` set once (`src/persistence/day_risk.py:147-215`). Service opens the day only from a fresh REST base inside the day, blocks on missing or unreadable state with exposure, persists the latch before returning the verdict (`src/execution/day_risk_service.py:358-470`). DAILY_STOP action: `enforce_daily_state` cancels only ENTRY-role orders of placed plans via `expire_pending_entry(trigger_reason="daily_stop")`, no stop or take-profit cancel path exists in the module, cancel before alert (`src/execution/daily_stop.py:99-281`). `[TEST-FAKE][TEST-PG][RECORDED]` (SL close replayed through the real parser, `tests/test_daily_loss_recorded.py`). Funding counted under owner decision O-2 option A (`TRADES_WITH_UNVERIFIED_FUNDING`, label `FUNDING_SOURCE_UNVERIFIED`, flag `FUNDING_SOURCE_VERIFIED` False). |
| 3 | Portfolio caps count resting entries and approved-but-unplaced plans; approvals reserve risk atomically (F-407, F-955) | VERIFIED (library level) | Counted statuses RESERVED, PLACED, OPEN (`src/risk/reservations.py:54-56`), verdict goes through the shared `check_portfolio` (`reservation_verdict`, line 241-303). Table `risk_reservations` with CHECKs (migration 0011). `reserve_in` locks the day row `FOR UPDATE`, reads counted rows and flips REQUESTED to RESERVED in the caller's transaction, or raises `ReservationRefused` and changes nothing (`src/persistence/risk_reservations.py:267-340`). `make_reserving_save_atomic` composes decision and reservation in one transaction, rollback leaves the approval PENDING (line 477-535). Two-connection race and refusal rollbacks: `tests/test_risk_reservation_approval_pg.py` [TEST-PG], passing. Release table `RELEASE_SOURCE_STATUSES` covers every terminal plan state; mappings in `src/execution/live_risk_inputs.py:194-318`. A DB error or missing request/day row refuses the approval (fail closed, D-17). |

Score: 3/3 truths verified at library level; 0 present-but-behavior-unverified (the transitions and invariants are exercised by named tests listed below).

### Behavior evidence (single files run, no full suite)

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Latch, cancel-not-stop, fold, equity, adapters, parity, gate | `uv run pytest -m "not docker" tests/test_phase21_gate.py tests/test_live_equity.py tests/test_account_equity_source.py tests/test_daily_loss.py tests/test_daily_loss_recorded.py tests/test_daily_stop.py tests/test_day_risk_service.py tests/test_day_risk_stream.py tests/test_live_risk_inputs.py tests/test_live_risk_parity.py tests/test_risk_reservations.py tests/test_snapshot_live_equity.py tests/test_account_reads_adapter.py tests/test_account_trades_adapter.py tests/test_phase21_fixtures.py tests/test_paper_shadow_reservations.py tests/test_paper_shadow_isolation.py` | all passed (696 tests, 0 failures) | PASS |
| PostgreSQL day store, reservations, approval race | `uv run pytest -m "not docker" tests/test_day_risk_pg.py tests/test_risk_reservations_pg.py tests/test_risk_reservation_approval_pg.py tests/test_paper_shadow_reservations_pg.py -rs` | 137 passed, no skip lines | PASS |
| Docs/code gate | `uv run python scripts/verify_decision_alignment.py all` | ALL_PASS | PASS |
| Lint and types | `uv run ruff check src/risk src/execution src/persistence src/adapters/binance_usdm.py`; `uv run mypy src` | no issues, 246 files | PASS |

The known failure `test_paper_shadow_isolation` (five unclassified read-only account methods) is fixed by 90d10ef7 (6 lines in the test control only) and passes here.

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `src/risk/live_equity.py` | VERIFIED | Substantive, pure, imported by `account_equity.py` and `live_risk_inputs.py` |
| `src/risk/daily_loss.py` | VERIFIED | Substantive, used by service, store, builder, daily_stop |
| `src/risk/reservations.py` | VERIFIED | Used by store and builder |
| `src/execution/account_equity.py` | VERIFIED (library) / not composed | Constructed only in tests until Phase 24 |
| `src/execution/day_risk_service.py` | VERIFIED (library) / not composed | Same |
| `src/execution/daily_stop.py` | VERIFIED (library) / not composed | Named by `OPS05_MATRIX` in `src/ops/alerts.py`; not called by any entry point |
| `src/execution/live_risk_inputs.py` | VERIFIED (library) / not composed | `execute_approved_plan` still takes `risk_kwargs` from its caller by design |
| `src/persistence/day_risk.py`, `risk_reservations.py` | VERIFIED | Migrations 0010 and 0011 present, chained, real downgrade |
| `config/execution/execution-limits-v1.toml` key `account.max_equity_age_ms` | VERIFIED as NOT_CONFIGURED | Required, owner value open (O-1) |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `LiveEquitySource.refresh` | adapter `account_*_snapshot` | `AccountReadPort` | WIRED (library) |
| `LiveDayRiskService` | `PgDayRiskStore`, reader, equity source | ports | WIRED (library) |
| `make_reserving_save_atomic` | `PgApprovalStore.save_atomic(after_decide=hook)` | one transaction | WIRED (library), proven on PostgreSQL |
| `reserve_in` | `check_portfolio` | `reservation_verdict` | WIRED |
| user-data router `ACCOUNT_UPDATE` / supervisor gap flag | `invalidate`, `ingest_fill` | none yet | NOT WIRED, deferred to Phase 24 (declared in 21-DEFERRED.md) |
| Any entry point | any Phase 21 service | none | NOT COMPOSED, Phase 24 |

### Requirements Coverage

| Requirement | Status | Note |
|-------------|--------|------|
| RISK-01, RISK-02 | Not changed by this phase | `.planning/REQUIREMENTS.md` shows both Complete from Phase 5; Phase 21 did not edit the file (`git log` last touches are pre-Phase 21) and this report marks nothing complete |
| EXEC-01 | Pending | Demo/mainnet proof of live equity in the snapshot and daily stop belong to Phases 24-26 |
| OPS-02 | Pending | Owner attestation (no-withdrawal keys, IP allowlist); Demo account config reported `canWithdraw` true (demo-observed, not mainnet) |

### Anti-Patterns Found

No TBD, FIXME, XXX, TODO or HACK markers and no `float(` in any Phase 21 source file. `params/**`, `docs/DECISIONS.md`, `src/backtest/`, `src/core/` and `src/risk/portfolio.py` are unchanged since the phase plan commit. `LIVE_NET_PNL_SEMANTICS_VERIFIED` and `FUNDING_SOURCE_VERIFIED` are both False (pinned by `test_phase21_gate.py`).

### Advisory observations (not gaps; for the Phase 24 composition review)

1. DAILY_STOP alert is delivered once. `alerts_due` is non-empty only on the evaluation that latches (`daily_loss.py:465-505`, `latch_now` path); later evaluations return `alerts_due=()`. If the alert sink fails or the process dies between `latch_stop` and the emit, `_emit` swallows the failure (`daily_stop.py:188-206`) and the alert is not re-sent. The latch and the entry cancels are unaffected. Same for the WARNING alert (stamped before it is emitted, `day_risk_service.py` `mark_warning_alerted`). Criterion 2 does not require alert redelivery (D-13), so this is a warning only.
2. Every ACCOUNT_UPDATE and every stream gap makes the day loss unknown until the next REST backfill completes (`day_risk_service.py:invalidate`), and `reserve_in` needs today's day row to exist and `daily_loss_quote` to be known. This is conservative (NO_TRADE), but it makes trading availability depend on the backfill cadence, which is unset and `[NOT_TESTED]` (21-DEFERRED.md). Phase 24 must pick and test a cadence.
3. A held latch answers DAILY_STOP even when the loss is unknown, and entry cancels are retried on each later call (`enforce_daily_state`); no scheduler calls it yet.
4. F-908/F-014 membership: `CLUSTER_SYMBOLS` stays hard-coded without BNB; a registry change needs a new parameter set, new `strategy_version` and a DECISIONS row (owner). Not a ROADMAP success criterion.

### Human Verification Required

See frontmatter `human_verification`. In short: the owner items O-1, O-3, O-4, O-5, O-6 stay OPEN by design (O-2 is decided: "option A", verbatim in `21-OWNER-DECISIONS.md`, not reinterpreted), and the pre-canary funding check recommended under O-2 is an open assistant recommendation, not an owner decision. None of these is a code gap.

### Gaps Summary

No gaps against the three success criteria at library level. The phase builds and tests the pieces; the goal "sizing and DAILY_STOP use Binance-canonical equity ... never a caller-supplied constant" holds only once Phase 24 composes them, because `execute_approved_plan` still receives its risk inputs from its caller. Status is `human_needed` because owner-only numbers and decisions remain open and the funding evidence is unobserved; it is not `gaps_found`.

---

_Verified: 2026-10-23_
_Verifier: Claude (gsd-verifier, Sonnet 5.5)_
