---
phase: 20-reconcile-safe-mode-hardening
verified: 2026-10-23T15:00:00Z
status: human_needed
score: 14/14 must-haves verified
covered_files:
  - .planning/phases/20-reconcile-safe-mode-hardening/20-01-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-01-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-02-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-02-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-03-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-03-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-04-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-04-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-05-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-05-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-06-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-06-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-07-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-07-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-08-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-08-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-09-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-09-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-10-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-10-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-11-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-11-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-12-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-12-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-13-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-13-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-14-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-14-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-15-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-15-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-16-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-16-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-17-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-17-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-18-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-18-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-19-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-19-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-20-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-20-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-21-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-21-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-22-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-22-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-23-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-23-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-24-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-24-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-25-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-25-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-26-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-26-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-27-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-27-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-28-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-28-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-29-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-29-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-30-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-30-SUMMARY.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-31-PLAN.md
  - .planning/phases/20-reconcile-safe-mode-hardening/20-31-SUMMARY.md
  - config/execution/README.md
  - config/execution/execution-limits-v1.toml
  - src/adapters/binance_probe.py
  - src/adapters/binance_public.py
  - src/adapters/binance_ratelimit_gate.py
  - src/adapters/binance_userdata_supervisor.py
  - src/db/alembic/versions/0007_intent_resolution_reason.py
  - src/db/alembic/versions/0008_pending_protective_actions.py
  - src/db/alembic/versions/0009_validated_lot_filters.py
  - src/db/models.py
  - src/domain/enums.py
  - src/domain/exchange_errors.py
  - src/domain/stream_records.py
  - src/domain/transitions.py
  - src/execution/cancel_verification.py
  - src/execution/emergency_close.py
  - src/execution/enablement.py
  - src/execution/execution_limits.py
  - src/execution/intent_recovery.py
  - src/execution/intent_store.py
  - src/execution/live_context.py
  - src/execution/lot_filter_source.py
  - src/execution/manager.py
  - src/execution/order_ids.py
  - src/execution/pending_actions.py
  - src/execution/protection.py
  - src/execution/protection_rebuild.py
  - src/execution/protection_replay.py
  - src/ops/alerts.py
  - src/ops/drills.py
  - src/ops/operator_evidence.py
  - src/ops/rest_gate_cli.py
  - src/ops/rest_gate_state.py
  - src/ops/risk_first.py
  - src/ops/spill.py
  - src/persistence/__init__.py
  - src/persistence/execution_state.py
  - src/persistence/lot_filters.py
  - src/persistence/pending_actions.py
  - src/persistence/safe_mode_store.py
  - src/reconcile/__init__.py
  - src/reconcile/classify.py
  - src/reconcile/compare.py
  - src/reconcile/feed_freshness.py
  - src/reconcile/local_intent.py
  - src/reconcile/loop.py
  - src/reconcile/safe_mode.py
  - src/reconcile/startup.py
  - src/reconcile/sweeper.py
covered_digest: "v2:sha256:7e92f512c0340079b7d438c2abbc813e2c94ec9e8e9a21572f430d9eed663fa8"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 13/14
  gaps_closed:
    - "W1: Pass 2 flagged every resting unfilled entry as ENTRY_WITHOUT_PROTECTIVE (closed by plan 20-31, src/reconcile/compare.py:824-845)"
    - "W2: the deadline-step same-id re-place attempt had no repo test (closed by tests/test_protection_deadline_attempt.py)"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Carry the Phase 20 deferrals into Phase 24 planning (W3, still open)"
    expected: "ROADMAP Phase 24 inherited items name 20-DEFERRED.md (sections 'Deferred items', 'Review findings not fixed in Phase 20', 'Blockers carried to Phase 24'), or Phase 24 planning is told to read it"
    why_human: "ROADMAP.md:1221-1239 still lists only P20-GATE-WIRING, G4-029 and D058 from Phase 20; no ROADMAP line and no file under .planning/phases/24-*/ (only 24-NOTES.md) mentions 20-DEFERRED.md. About 30 'Phase 24' rows exist only in the register. Phase 21 did pick up its own row (21-CONTEXT.md). A roadmap edit belongs to the owner or orchestrator."
  - test: "Run the Demo-only items the owner holds (UAT: 4 blocked)"
    expected: "A4, A8, P5/rm, P7, -4164, -2019, -1021, income history (quick 261023-sj2 cases), A2 with a longer gtd_expiry_wait_seconds, partial fill, real-host drill rehearsal (Phases 25/26)"
    why_human: "Every Phase 20 result is a test with fakes or local PostgreSQL; nothing is [DEMO] for these. The register labels them [NOT_TESTED]. 20-UAT.md status: partial (15 pass, 4 blocked)."
  - test: "Correct the stale bookkeeping and two stale register rows (W4, W5 remnants)"
    expected: "STATE.md body, ROADMAP plan count and list, 20-DEFERRED.md rows 35 and 138 match reality"
    why_human: "Docs owned by the orchestrator or owner; the verifier is read-only here. Details under Warnings."
---

# Phase 20: Reconcile + SAFE_MODE Hardening + Alerts Verification Report

**Phase Goal:** Reconciliation sees every dangerous divergence. A protective stop is never canceled or left missing. SAFE_MODE survives restarts, and exiting it needs an operator. A DB outage never blocks risk-reducing actions.
**Verified:** 2026-10-23 (HEAD cbf7362f)
**Status:** human_needed
**Re-verification:** Yes. Previous report: human_needed, 13/14 (W1 to W8). Full-depth re-check of the changed areas, regression check of the rest.
**Evidence labels:** library level with fakes and local PostgreSQL. Nothing is `[DEMO]` for Phase 20 behavior, nothing is composed into a running process, live placement stays disabled. Requirements stay Pending.

## Method

Read the code at HEAD for every criterion. `git diff 31c1cd2e HEAD --stat -- src` shows only three source files changed since the previous report: `src/reconcile/compare.py` (plan 20-31), `src/adapters/binance_probe.py` and `src/ops/operator_evidence.py` (quick 261023-sj2). `src/execution/protection.py` is unchanged, so the previous reading of criterion 2 stands and was re-checked at `protection.py:1905-1936`. Ran only four targeted test files (`tests/test_protection_deadline_attempt.py`, `tests/test_reconcile_classify.py`, `tests/test_reconcile_stale_entry.py`, `tests/test_reconcile.py`): all passed. The full suite was not rerun, per the caller. Fingerprint produced by `gsd-tools query verification.fingerprint` (111 files).

## Goal Achievement

### Observable Truths (ROADMAP Phase 20 success criteria, split into checkable parts)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: compare runs a reverse pass over exchange orders, compares signed amounts per position, requires a STOP for every open position; doubled, sign-flipped, foreign, TP-only are divergences (F-701) | VERIFIED (regression check) | `compare.py` Pass 3 (`_check_position_bound`, `_check_stop`), Pass 4 reverse pass, duplicate ids; `tests/test_reconcile_compare_v2.py`. Plan 20-31 touched only Pass 2 and added `exposed_symbols` (:576-581); Pass 3 and 4 unchanged. The bound check cannot see an over-fill below the intended quantity: honest, deferred (Phase 24, register rows 13-15) |
| 2 | SC2 (F-401): a protective of a plan whose entry rests or is partially filled is never an orphan | VERIFIED | `compare.py:444-460` `resting_entry_plans`, `:482-483` skip; `test_reconcile_compare_v2.py:697-734`; `tests/test_reconcile_loop.py:411`. Untouched by 20-31 |
| 3 | SC2: every positive fill leads to the protection flow within `max_unprotected_ms`; no new entry opens while unprotected exposure exists | VERIFIED (library) | `protection.py` first-fill path, deadline, `blocks_new_entries`, consumed by `manager.py` (unchanged since the previous report). `max_unprotected_ms` stays `NOT_CONFIGURED` (O-04): live placement refuses, honest |
| 4 | SC2 (1): a never-confirmed stop proved absent by this step's REST reads is placed again under the same client id from the plan stop-loss, at most one attempt per step | VERIFIED | `protection.py:1919-1928` (ABSENT only, `probe_first=False`), `tests/test_protection_branches.py:307-333`, `tests/test_protection_demo_shapes.py:172-210,287-311` |
| 5 | SC2 (1) clause: the step that reaches the deadline still makes its attempt before it escalates | VERIFIED (was PRESENT_BEHAVIOR_UNVERIFIED) | Code order: ABSENT re-place at `protection.py:1919-1928`, deadline check at `:1930-1934`. Now pinned by `tests/test_protection_deadline_attempt.py:42-57` (placement count +1 across the deadline step, state CLOSE_REQUIRED, last transition B2_STOP_UNCONFIRMED, same client id and plan trigger price on every call), `:60-72` (attempt precedes the close) and `:75-86` (stop listed: no attempt, no escalation). All 3 tests passed in this session |
| 6 | SC2 (2): a rejected or unacknowledged stop is never resent: CLOSE_REQUIRED, reduce-only close, alert | VERIFIED (regression) | `protection.py` B5 path, `test_protection_branches.py:72-124`; file unchanged |
| 7 | SC2 (3, D077): a stop confirmed ACTIVE and later lost is never re-placed (automatically or by operator); exposure = CLOSE_REQUIRED + reduce-only close | VERIFIED (regression) | `protection.py:1905-1916` (`stop_lost` goes to `_on_stop_lost`, never to `_place_stop`), `test_protection_stop_lost.py`, `test_manual_controls.py` |
| 8 | SC2 (4): stop unconfirmed at `max_unprotected_ms` -> CLOSE_REQUIRED; closer reads the position itself; two consecutive zero reads send no order; FLAT only with the entry terminal | VERIFIED (regression) | `protection.py:1930-1934`, `emergency_close.py`, `test_emergency_market_close.py:454-512` |
| 9 | SC2: WR-07 ordering: protective legs cancelled only with zero fills or after two consecutive fresh flat reads with the entry terminal | VERIFIED (regression) | three cancel sites unchanged (`protection.py` `_sweep`, `manager.py` `_protectives_keep_reason`, sweeper) |
| 10 | SC3: SAFE_MODE is persisted and needs an operator id to exit (F-711, F-127) | VERIFIED (library) | `safe_mode.py` fail-closed load, persist on enter, `exit_safe_mode` (no other exit path); unchanged. RUNBOOK 21.1 now names `SYMBOL_OWNERSHIP_CONFLICT`, `RESTORE_NOT_COMPLETE` and states the resting-entry rule. Not composed: no production code builds a `SafeModeController` (Phase 24) |
| 11 | SC3: risk-reducing actions execute first and are journaled afterwards with a fallback (F-702) | VERIFIED (regression) | `src/ops/risk_first.py`, used by `manager.py`, `enablement.py` |
| 12 | SC3: the -2011 cancel result is verified by a post-cancel query (F-502) | VERIFIED (regression) | `src/execution/cancel_verification.py`, `tests/test_cancel_verification.py` |
| 13 | SC4: alerts for unprotected position, divergence, foreign order, DAILY_STOP, stale data, auth failure (F-106) | VERIFIED for 5 of 6; DAILY_STOP deferred | `OPS05_MATRIX` has 15 rows; producers in `classify.py`, `loop.py`. DAILY_STOP and daily-loss WARNING are contract plus test trigger only, receiving phase 21 (`21-CONTEXT.md` D-13). Nothing wired in a process (Phase 24) |
| 14 | SC5: tests asserting the old rules ("reconciler never places") are rewritten (F-604) | VERIFIED (regression) | `tests/test_drills.py:1105`, `tests/test_phase20_gate.py:303`; no remaining old assertion |

**Score:** 14/14 truths verified; 0 present-but-behavior-unverified.

### Plan 20-31 rule, read in code (`src/reconcile/compare.py`)

`_entry_awaits_fill` (:824-845) returns True only when all three hold, and everything else keeps `ENTRY_WITHOUT_PROTECTIVE`:

1. local status is exactly `OrderStatus.NEW.value` (:841). The only local producer of NEW for an ENTRY is plan state AWAITING_FILL (`local_intent.py:106`; ENTRY_UNRESOLVED gives SUBMITTING, UNPROTECTED and PROTECTED_ENTRY_OPEN give PARTIALLY_FILLED, `local_intent.py:107-109`). A SENT or UNKNOWN row of an untracked plan is not NEW;
2. the entry's symbol is not in `exposed_symbols` (:843), built at :576-581 from every non-zero local position intent and every non-zero exchange position row (a non-Decimal garbage amount counts as non-zero via `_is_zero_like`, fail closed);
3. the exchange list has the order (`truth_normal is not None`) with `status == NEW` exactly (:845). An entry missing from the exchange keeps both `ENTRY_WITHOUT_PROTECTIVE` and `UNSYNCED_NORMAL` (the second pass at :613-627 is untouched).

The call site is :597-601 and still requires `not has_protective` first, so a plan that has a stop on the exchange is unaffected. Read-ordering race: an order read before a fill is covered by the position read showing exposure; a position read before a fill is covered by the order then leaving the book or showing PARTIALLY_FILLED. I found no hole. Note the first version of 20-31 (commit c87e79cf) also exempted an order absent from the exchange; commit a1def018 removed that, and the code at HEAD is the stricter form.

Pinning tests (all passed): `test_reconcile_classify.py:427` (agreement), `:434` (zero-amount row is not a fill), `:443` (tick: no SAFE_MODE, no alert), `:459` (tick: filled entry still alerts and enters SAFE_MODE), `:477` (position on symbol), `:488` (position on another symbol), `:497` (exchange status PARTIALLY_FILLED / FILLED / UNKNOWN / empty), `:508` and `:517` (missing from exchange), `:524` (SUBMITTING and SENT), `:540` (local status PARTIALLY_FILLED / SUBMITTING / PLANNED / None), `:561` (local position intent on the symbol), `:579` (other symbol protected). This covers the filled / partly filled / SENT / UNKNOWN / vanished set. The operator exit uses the same `compare` (RUNBOOK 21.1 states the consequence), so it no longer refuses on a plain resting entry.

Residual, stated in register row 136: a natural GTD expiry the coordinator has not yet seen shows `ENTRY_WITHOUT_PROTECTIVE` plus `UNSYNCED_NORMAL` for about one tick (fail closed); `OpenOrderSnapshot` has no executed-quantity field, so a NEW-status order cannot show a partial fill by quantity (Binance reports PARTIALLY_FILLED as the status, and any position on the symbol is exposure).

### Previous warnings W1 to W8

| W | Previous finding | Now | Evidence |
|---|------------------|-----|----------|
| W1 | resting-entry false positive | CLOSED | see above |
| W2 | deadline-step clause untested | CLOSED | `tests/test_protection_deadline_attempt.py`; the 20-31 SUMMARY says a temporary mutation of `protection.py` confirmed sensitivity (not re-run here) |
| W3 | Phase 24 inheritance only in the register | STILL OPEN | `ROADMAP.md:1239` is the last Phase 20 item under Phase 24; `20-DEFERRED` appears in ROADMAP only at P20-OPS-REMOTE (:1181), P20-GATE-WIRING (:1239) and P20-DEMO (:1282); the only phase-dir file naming the register is `21-CONTEXT.md`; `.planning/phases/24-*/` holds only `24-NOTES.md`. Needs an owner or orchestrator edit |
| W4 | stale ROADMAP and STATE bookkeeping | PARTLY CLOSED | ROADMAP: plans 20-01..20-30 are `[x]` (:1039-1086) and the progress row says "30/30 Executed, human_needed" (:1381); but plan 20-31 is not listed, and "30/30 plans executed (26 planned + 4 gap-closure)" (:1035) and :1381 should read 31 (27 + 4). Phase 20 stays `[ ]` at :57, correct. STATE.md frontmatter was updated (`status: verifying`, `current_plan: 30`) but the body is not: `STATE.md:34-39` still says "Phase 20 — EXECUTING, Current Plan: 7 (wave 2), Total Plans in Phase: 26, Status: Ready to execute, Last activity: 2026-10-21", progress 61%; `current_plan: 30` and `stopped_at: Phase 21 context gathered` also lag 20-31 |
| W5 | stale register counts | PARTLY CLOSED | `20-DEFERRED.md:29` (15 keys) and :67 (15 rows) are correct. `20-DEFERRED.md:138` still says "RUNBOOK 21.1 does not name `SYMBOL_OWNERSHIP_CONFLICT`, `RESTORE_NOT_COMPLETE` or `local_active_plans`"; RUNBOOK 21.1 (`docs/operations/RUNBOOK.md:928-929`) now names the first two and the active plans (commit 230b0dd1). The identifier `local_active_plans` itself is not spelled, the concept is |
| W6 | Nyquist not validated | CLOSED | `20-VALIDATION.md` header: `status: validated`, `nyquist_compliant: true`, `wave_0_complete: true` (commit 33ac7806) |
| W7 | 20-REVIEW header | CLOSED enough | `20-REVIEW.md:3` has a `closure_note` pointing at the 20-27..20-30 closures and the register; `status: issues_found` and `critical: 1` remain as the historical review result. Info only |
| W8 | gate-restricted tick raises no alert | STILL OPEN, observation | `loop.py:650-666` only journals `RECONCILE_SKIPPED_GATE`. The register covers "judges no feed" (row 39) but not the missing alert for a long 418 pause. Not in OPS-05's list; no criterion fails |

### Deferred register versus reality

Checked against the code: 15 NOT_CONFIGURED keys, 15 `OPS05_MATRIX` rows, the `feed_clock_skew` constructor argument (`loop.py:450-483`), RUNBOOK 21.1 text, rows 136 and 148-151. Two rows are contradicted by the current tree:

- **Row 35** (`20-DEFERRED.md:35`) still says Pass 2 "still applies the pre-Phase-19 rule" and that the pin is `test_observed_limit_a_resting_entry_with_no_fill_is_entry_without_protective`. That test no longer exists in `tests/` (it is named only in planning docs); the rule was changed by 20-31 and row 136 says CLOSED. Row 35 should be marked closed or removed.
- **Row 138** first clause is stale (see W5).

All other rows I spot-checked still match. No review finding is missing from the register. The register does not record W8 (no alert for a gate-restricted tick), and the new `_entry_awaits_fill` residual is only in row 136.

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Reconcile loop, startup recovery, alert sink, SAFE_MODE controller, REST gate store have no production caller | Phase 24 | ROADMAP Phase 24 SC1 and inherited P20-GATE-WIRING, G4-029 |
| 2 | DAILY_STOP and daily-loss WARNING producers | Phase 21 | `21-CONTEXT.md` D-13 |
| 3 | Demo evidence (A2, A4, A8, P5, P7, stream states, probes) | Phases 24/25/26 | ROADMAP P20-DEMO; register "Needs a connected machine" |
| 4 | Positions table, fills ledger, exact signed compare, Order rows | Phase 24 | register rows 13-15 (register only; see W3) |
| 5 | Operator authentication and Telegram commands | Phases 23/24 | ROADMAP P20-OPS-REMOTE; owner confirmed 2026-10-23 |

### Required Artifacts and Key Links

| Artifact | Status | Details |
|----------|--------|---------|
| `src/reconcile/compare.py` | VERIFIED | `_entry_awaits_fill` substantive (:824-845), wired at :597; tests exercise both branches |
| `src/reconcile/classify.py`, `local_intent.py`, `loop.py`, `safe_mode.py`, `startup.py`, `sweeper.py`, `feed_freshness.py` | VERIFIED | unchanged since the previous report; no production caller of `ReconcileLoop`, `run_startup_recovery`, `SafeModeController` by design (Phase 24) |
| `src/execution/protection.py`, `emergency_close.py`, `cancel_verification.py`, `pending_actions.py`, `protection_rebuild.py`, `protection_replay.py` | VERIFIED | unchanged |
| `src/ops/alerts.py`, `risk_first.py`, `spill.py`, `rest_gate_*.py` | VERIFIED | unchanged; alert sink not constructed in `src` (Phase 24) |
| `src/adapters/binance_probe.py`, `src/ops/operator_evidence.py`, `scripts/demo_probe.py` | Outside Phase 20 criteria | changed by quick 261023-sj2 (owner opt-in Demo probe cases); not read in depth, not on the decision path and not on any Phase 20 criterion; the caller reports their tests passed strict. The two `src` files are in `covered_files` so the digest is fresh |
| `config/execution/execution-limits-v1.toml` | VERIFIED | keys `NOT_CONFIGURED`; live path refuses |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Deadline step re-place, resting-entry rule, stale-entry alert, legacy reconcile | `uv run pytest tests/test_protection_deadline_attempt.py tests/test_reconcile_classify.py tests/test_reconcile_stale_entry.py tests/test_reconcile.py -q` | all passed (4 files, 0 failures) | PASS |
| No debt markers in changed sources | grep `TBD`, `FIXME`, `XXX` in compare.py, binance_probe.py, operator_evidence.py, scripts/demo_probe.py, the new test | no hits | PASS |

### Probe Execution

SKIPPED: Phase 20 declares no `probe-*.sh`.

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| EXEC-02 | Library-level SATISFIED, stays Pending | Demo evidence and composition are Phases 24-26 |
| OPS-01 | Library-level SATISFIED, stays Pending | real-host drill rehearsal not done; the resting-entry exit blocker is gone |
| RISK-03 | Library-level SATISFIED, stays Pending | wording aligned to D077; criterion 2 clause (1) now pinned by a test |
| EXEC-06 | Library-level SATISFIED, stays Pending | no command surface or authentication |
| OPS-05 | PARTIAL, stays Pending | DAILY_STOP and WARNING producers are Phase 21; nothing wired in a process |

No requirement is marked complete by this report. No orphaned requirement IDs.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `docs/operations/RUNBOOK.md` | ~937, ~941 | `TBD` with a "Phase 24" pointer (from plan 20-24) | Warning | prose in a runbook, project rule "missing contract => TBD"; unchanged judgment from the previous report, caller's call |
| `src/reconcile/compare.py` | 638 | `symbol=raw_symbol` (IN-B1) | Info | fail closed, deferred |

No FIXME or XXX; no stubs in the changed files.

## Warnings (none is a must-have failure)

- **N1 (W3, open).** Phase 24 inherits only three Phase 20 items in ROADMAP; the rest sit in `20-DEFERRED.md`.
- **N2 (W4 remnant).** STATE.md body (`STATE.md:34-39`) and ROADMAP plan count and list (`ROADMAP.md:1035`, `:1381`, missing 20-31 after `:1086`) are stale.
- **N3 (register).** `20-DEFERRED.md:35` and the first clause of `:138` contradict the tree; W8 is unregistered.
- **N4 (new, minor).** The GTD-expiry residual of the 20-31 rule (row 136): one tick of SAFE_MODE plus a CRITICAL alert if Binance expires an entry before the coordinator notices. Fail closed; the owner may prefer `UNSYNCED_NORMAL` only (one-line change).
- **N5.** The `20-UAT.md` session was run by the assistant, not the owner (the file says so); `pass` there means tests were run, not owner acceptance.

## Human Verification Required

1. **Phase 24 inheritance (N1).** Add the register sections to Phase 24 inherited items, or confirm Phase 24 planning will read `20-DEFERRED.md`.
2. **Demo-only and real-host items.** Owner runs the sj2 cases and the rest listed in the register; results recorded with `[DEMO]` labels.
3. **Bookkeeping and register rows (N2, N3).** Orchestrator or owner edit.

## Gaps Summary

No must-have is FAILED, no artifact is missing or a stub, and the two functional warnings of the previous report (W1 resting-entry rule, W2 untested deadline clause) are closed in code and tests, not just in SUMMARYs. The status stays `human_needed` because Phase 24 inheritance (W3) is unresolved, the Demo-only items belong to the owner, and bookkeeping and register text is still stale in places. No requirement should be marked complete on this evidence.

---

_Verified: 2026-10-23_
_Verifier: Claude (gsd-verifier)_
