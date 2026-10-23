---
phase: 20-reconcile-safe-mode-hardening
verified: 2026-10-23T12:00:00Z
status: human_needed
score: 13/14 must-haves verified
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
covered_digest: "v2:sha256:6b74576201b4340b0c8e6f4627f95ef2403e09c8f5acee8f9ebdc50f77eac52e"
behavior_unverified: 1
overrides_applied: 0
behavior_unverified_items:
  - truth: "Criterion 2 clause (1): the step that reaches the max_unprotected_ms deadline still makes its same-id stop attempt before it escalates (D034 clause (1))"
    test: "Drive a never-confirmed, REST-absent stop (by-id and listing both deny it) to the deadline step and count place_algo_protective calls before and after that step"
    expected: "Exactly one more same-id placement at plan price on the deadline step, then CLOSE_REQUIRED with branch B2_STOP_UNCONFIRMED"
    why_human: "The code does this (src/execution/protection.py:1919-1934, the ABSENT re-place runs before the deadline check) and an ad-hoc run by this verifier confirmed 1 -> 2 placements and CLOSE_REQUIRED, but no test in the repo asserts it: test_when_neither_read_ever_shows_the_stop_there_is_one_attempt_per_step_then_b2 (tests/test_protection_demo_shapes.py:287) stops counting before the deadline step. A regression would pass the suite. Add the assertion, or accept the ad-hoc evidence."
human_verification:
  - test: "Decide the receiving phase and the code change for Pass 2 ENTRY_WITHOUT_PROTECTIVE on a resting entry"
    expected: "ROADMAP (Phase 24 or an earlier plan) names who changes src/reconcile/compare.py:578-595 and the pinned test tests/test_reconcile_classify.py:404, before the reconcile loop is composed"
    why_human: "Under D079 a resting GTD entry has no stop until a fill. Pass 2 still flags every open local ENTRY with no protective as ENTRY_WITHOUT_PROTECTIVE (CRITICAL UNPROTECTED_POSITION alert plus SAFE_MODE), and the operator exit runs the same compare, so it would refuse while any entry rests. 20-DEFERRED.md lists it as 'Phase 24 (proposed), unassigned until the owner confirms'. Fail closed and honestly deferred, but it makes the loop unusable with a resting entry once composed."
  - test: "Carry the Phase 20 deferrals into Phase 24 planning"
    expected: "Phase 24 planning reads 20-DEFERRED.md sections 'Deferred items' and 'Blockers carried to Phase 24', or ROADMAP Phase 24 inherited items are extended"
    why_human: "ROADMAP Phase 24 inherits only P20-GATE-WIRING, G4-029 and D058 from Phase 20. About 30 further rows say 'Phase 24' only inside 20-DEFERRED.md (scheduled cancel of an unfilled entry at plan expiry, second-plan refusal, alert-producer wiring, FeedSource liveness, ReconcileLoop(feed_clock_skew=), exit_safe_mode composition, WR-A4, WR-B5, WR-B7, WR-C5 to WR-C8 and others). Phase 21 already picked up its row (21-CONTEXT D-13)."
  - test: "Run the Demo-only items the owner holds"
    expected: "A2 (GTD expiry), A4, P5 stop rejection, 11 Demo probes (O-05), real-host drill rehearsal (Phases 25/26)"
    why_human: "Every Phase 20 result is a test with fakes or local PostgreSQL. Nothing is [DEMO]; the register labels them [NOT_TESTED]."
  - test: "Run /gsd-validate-phase 20 or record why not"
    expected: "20-VALIDATION.md leaves status: draft / nyquist_compliant: false"
    why_human: ".planning/config.json has workflow.nyquist_validation = true, and the file was seeded and never validated."
---

# Phase 20: Reconcile + SAFE_MODE Hardening + Alerts Verification Report

**Phase Goal:** Reconciliation sees every dangerous divergence. A protective stop is never canceled or left missing. SAFE_MODE survives restarts, and exiting it needs an operator. A DB outage never blocks risk-reducing actions.
**Verified:** 2026-10-23
**Status:** human_needed
**Re-verification:** No, initial verification
**Evidence labels:** library level with fakes and local PostgreSQL. Nothing is `[DEMO]`, nothing is composed into a running process, live placement stays disabled. Requirements stay Pending.

## Method

Read the code at HEAD 31c1cd2e for every criterion and every claimed review fix, mapped each to the tests that exercise it, and ran one ad-hoc behavioural check (scratch file outside the repo, nothing in the repo changed). The full suite was not rerun, per the caller's instruction (13234 passed, 20 skipped, 0 failed; gates 112 passed under TRADING_CI_STRICT=1; mypy, ruff, format, decision alignment and `uv lock --check` clean).

## Goal Achievement

### Observable Truths (ROADMAP success criteria, split into checkable parts)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: compare runs a reverse pass over exchange orders, compares signed amounts per position, requires a STOP for every open position; doubled, sign-flipped, foreign, TP-only are divergences (F-701) | VERIFIED | `src/reconcile/compare.py:276-744`: Pass 3 bound/sign check `_check_position_bound` (:889-931, sign first, then `abs(amount) > bound`), `_check_stop` (:963-984, TP_ONLY vs POSITION_WITHOUT_STOP), Pass 4 reverse pass (:702-718, FOREIGN_ORDER / UNTRACKED_SYSTEM_ORDER, never sweepable), duplicate ids (:356-379). Tests: `tests/test_reconcile_compare_v2.py` (:169-209 foreign, :389-448 sign and bound, :552-586 stop, :697-734 orphan). The bound check cannot see an over-fill below the intended quantity: honest, deferred (Phase 24, Order rows) |
| 2 | SC2 (F-401): a protective of a plan whose entry rests or is partially filled is never an orphan | VERIFIED | `compare.py:439-455,477-478` (`resting_entry_plans` from local status and exchange ids); tests `test_reconcile_compare_v2.py:697-734` |
| 3 | SC2: every positive fill leads to the protection flow within `max_unprotected_ms`; no new entry opens while unprotected exposure exists | VERIFIED (library) | `protection.py:1396-1411` (first fill: stop and entry-cancel together), `:1944-1951` deadline, `:871-892` `blocks_new_entries` (BLOCKING_STATES, restore pending, any PENDING row, unreadable store = True), consumed at `manager.py:917-919` (exception = blocked). Key `max_unprotected_ms` is NOT_CONFIGURED (owner, O-04), so live placement refuses: honest |
| 4 | SC2 (1): a never-confirmed stop that this step's own REST query proved absent is placed again under the same client id from the plan stop-loss, at most one attempt per step | VERIFIED | `protection.py:1919-1928` (ABSENT only, `probe_first=False`), `:1645-1723` `_place_stop` uses `entry.sl_trigger_price` and `_stop_client_id`; listing cross-check `:2053-2095`; tests `test_protection_branches.py:307-333`, `test_protection_demo_shapes.py:172-210,287-311` |
| 5 | SC2 (1) clause: the step that reaches the deadline still makes its attempt before it escalates | PRESENT_BEHAVIOR_UNVERIFIED | Code order is right (`protection.py:1919-1934`). Ad-hoc run by this verifier: 1 -> 2 placements on the deadline step, state CLOSE_REQUIRED. No repo test asserts it. See behavior_unverified_items |
| 6 | SC2 (2): a definitively rejected or unacknowledged stop is never resent: CLOSE_REQUIRED, reduce-only close, alert | VERIFIED | `protection.py:1413-1429` (REJECTED -> B5, `record_result REJECTED`, `_enter_close_required`), `:2413-2458` (SAFE_MODE, CRITICAL alert, PROTECTIVE_REJECTED for B5, then `_attempt_close`); `place_market_close` is reduce-only (`binance_usdm.py:1209+`). Tests `test_protection_branches.py:72-124`. `-4116` is "exists, awaiting REST", not B5 (`:1432-1443`) |
| 7 | SC2 (3, D077): a stop confirmed ACTIVE and later lost is never re-placed, automatically or by an operator; exposure = CLOSE_REQUIRED + reduce-only close; unreadable or flat-with-entry-open = UNPROTECTED, escalating from first detection | VERIFIED | `protection.py:1968-2022` `_on_stop_lost` (`stop_lost_at` set once), `:2024-2044` `_supervise_stop`, `:1907-1936` `_confirm` never reaches `_place_stop` when `stop_lost`, `:2053-2095` cross-check skipped only when by-id was seen; operator path `:1137-1177` refuses (`CODE_REPLACEMENT_FORBIDDEN_STOP_LOST`). Tests `test_protection_stop_lost.py:106-296`, `test_manual_controls.py:887,908` |
| 8 | SC2 (4): stop unconfirmed at `max_unprotected_ms` -> CLOSE_REQUIRED; closer reads the position itself; two consecutive zero reads send no order; FLAT only with the entry terminal | VERIFIED | `protection.py:1932-1934,2485-2521`; `emergency_close.py:499-679` (reads position, sizes from REST, `_refuse_unconfirmed_flat`, never resends an unproven attempt); tests `test_emergency_market_close.py:454-512` |
| 9 | SC2: WR-07 ordering: protective legs cancelled only with zero fills or after two consecutive fresh flat reads with the entry terminal | VERIFIED | Only three cancel sites exist (grep of `cancel_algo_order`): coordinator `_sweep` after FLAT with evidence (`protection.py:2523-2553`), `manager.py:2344-2388` `_protectives_keep_reason` (two reads, entry terminal incl. FILLED after WR-A3), sweeper after two zero reads. IN-A2 (guard lacks PROTECTED/COMPLETE/TP_UNAVAILABLE) is latent: all three callers pass the evidence |
| 10 | SC3: SAFE_MODE is persisted and needs an operator id to exit (F-711, F-127) | VERIFIED (library) | `safe_mode.py:315-346` fail-closed load (`SAFE_MODE_STATE_UNREADABLE`), `:443-515` persist on enter, `:569-716` `exit_safe_mode` (row 1 operator id, fresh reads, compare, readiness, gate, stream; journal, then store, then memory); no other exit path in `src` (grep). `PgSafeModeStateStore` append-only. Tests `test_safe_mode_persistence*.py`, `test_safe_mode_exit_operator.py`. Not composed: no production code builds a `SafeModeController` (Phase 24) |
| 11 | SC3: risk-reducing actions execute first and are journaled afterwards with a fallback (F-702) | VERIFIED | `src/ops/risk_first.py:81-137` (`act_then_record`, `record_after`, spill fallback, `AuditRecordLost` only when both fail); used by `manager.py:2087,2094,2112,2514`, `enablement.py:317`. Limits kept honest in the register: the write-ahead is a blocking fsync before the action (WR-C7) and the coordinator's CRITICAL alert is journaled before the close (WR-C8) |
| 12 | SC3: the -2011 cancel result is verified by a post-cancel query (F-502) | VERIFIED | `src/execution/cancel_verification.py:70-140` (`confirm_entry_cancel`, `confirm_algo_cancel`; not-found for an entry is UNKNOWN, never a cancel); `manager.py` returns the verdict; tests `test_cancel_verification.py` |
| 13 | SC4: alerts for unprotected position, divergence, foreign order, DAILY_STOP, stale data, auth failure (F-106) | VERIFIED for 5 of 6, DAILY_STOP deferred | `src/ops/alerts.py:94-120` closed event contract, `OPS05_MATRIX` (:754-910, 15 rows), producers `classify.py:104-165`, `loop.py:701-727` (AUTH_FAILURE), stale data via the feed check. DAILY_STOP and daily-loss WARNING have a contract and a test trigger only (`alerts.py:891-910`); receiving phase 21, accepted in `21-CONTEXT.md` D-13. Nothing is wired in a process (Phase 24) |
| 14 | SC5: tests asserting the old rules ("reconciler never places") are rewritten (F-604) | VERIFIED | `20-23-SUMMARY.md` "Rewritten old-rule tests"; `tests/test_drills.py:1105` `test_reconcile_never_places_and_delegated_stops_keep_the_plan_price`; narrowed static guard kept; `tests/test_phase20_gate.py:303` pins the name. Grep finds no remaining "reconciler never places" assertion |

**Score:** 13/14 truths verified; 1 present-but-behavior-unverified.

### Review findings claimed fixed: checked in code, not in the SUMMARYs

| Finding | Claim | Result | Where |
|---------|-------|--------|-------|
| CR-C1 | `scan()` no longer reads an unreadable spill as empty | FIXED | `src/ops/spill.py:238-250` catches only `FileNotFoundError`; `src/reconcile/startup.py:167-182,320-324` maps a raise to `readable=False`, SAFE_MODE `RESTORE_INCONSISTENT`, no replay of an unreadable spill. Tests `test_risk_first_spill.py:666-701`, `test_startup_recovery.py:591`. Residual: constructor re-creates a missing directory (`spill.py:193-197`), recorded in the register |
| WR-A1 | UNKNOWN entry can close after a failed finalize | FIXED | `intent_recovery.py:722-755` content-hash id per observation |
| WR-A2 | REST-gate refusal at any closer read is `NOT_SENT` | FIXED | `emergency_close.py:521-527,546-550,591-592,654-657` and the second flat read |
| WR-A3 | manual close removes legs of a filled flat plan | FIXED | `manager.py:2344-2388` (extra `confirm_entry_cancel`, FILLED lets legs go, PARTIALLY_FILLED keeps) |
| WR-B1 | no SAFE_MODE churn on standing reasons | FIXED | `safe_mode.py:443-531` assertion rounds; `tests/test_safe_mode_reentry.py` |
| WR-B2 | normal TP1 fill is not `UNSYNCED_ALGO` | FIXED within stated limit | `compare.py:509-513,770-805`, `local_intent.py:258-264`; a partially filled plan hides an externally cancelled TP1 (stated, stop and TP2 still required) |
| WR-B3, WR-B4 | exit runs the ownership check; exit refuses while restore incomplete | FIXED | `safe_mode.py:642-681,732-763,855-880`; `ExitReadiness.restore_complete` required field |
| WR-B6 | feed time in the future is stale | FIXED | `feed_freshness.py:127-137,150-158`; zero allowance by default |
| WR-C1 | `decode_record` is total | FIXED | `rest_gate_state.py:70-102` |
| WR-C2 | failed gate save is retried | FIXED | `binance_ratelimit_gate.py:476-517`, called from `check()`/`record()` |
| WR-C3 | implausible persisted deadline untrusted; pause sleeps sliced | FIXED, total wait uncapped (register says so) | `binance_ratelimit_gate.py:415-460`, `binance_userdata_supervisor.py:685-689` |
| WR-C4 | gate with no known end stops spinning | FIXED | `binance_userdata_supervisor.py:665-684` |
| WR-C9 | directory fsync, exclusive initialize | FIXED, `[NOT_TESTED]` on POSIX | `rest_gate_state.py:143-201` |

All 34 review findings are accounted for: 13 closed above (plus the `-4116`, `-5040` and stop-confirmation items), the rest are rows in 20-DEFERRED.md ("Review findings not fixed in Phase 20"). IN-A3 sits in the merge-findings row. No finding is missing from the register.

### Deferred Items

Items not met by Phase 20 and covered by a later phase (Step 9b). They do not change the status.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Reconcile loop, startup recovery, alert sink, SAFE_MODE controller, REST gate store have no production caller | Phase 24 | ROADMAP Phase 24 SC1 ("composition root wires every link that has no production caller today ... reconcile, sweeper and health schedulers") and inherited items P20-GATE-WIRING, G4-029 |
| 2 | DAILY_STOP and daily-loss WARNING producers | Phase 21 | `21-CONTEXT.md` D-13 |
| 3 | Demo evidence: A2, A4, P5, stream states, manual-close, 11 probes | Phases 24/25/26 | ROADMAP P20-DEMO (Phase 25) and `20-DEFERRED.md` "Needs a connected machine" |
| 4 | Positions table, fills ledger, exact signed compare, Order rows (D-13, D-01a, D-29) | Phase 24 | `20-DEFERRED.md` rows 13-15 (register only, see warning W3) |
| 5 | Operator authentication / Telegram commands | Phases 23/24 | ROADMAP P20-OPS-REMOTE; owner confirmed 2026-10-23 |

### Required Artifacts and Key Links

| Artifact | Status | Details |
|----------|--------|---------|
| `src/reconcile/compare.py`, `classify.py`, `local_intent.py`, `loop.py`, `safe_mode.py`, `startup.py`, `sweeper.py`, `feed_freshness.py` | VERIFIED (substantive, tested) | Wired into each other; no production caller of `ReconcileLoop`, `run_startup_recovery`, `SafeModeController` anywhere in `src`/`scripts` (grep). Intended: deferred row 1 |
| `src/execution/protection.py`, `emergency_close.py`, `cancel_verification.py`, `pending_actions.py`, `protection_rebuild.py`, `protection_replay.py` | VERIFIED | `ProtectionCoordinator` is wired to `live_context.protection_registry` and `manager.py:917,1159,1228`; the coordinator's own `step()` has no scheduler (Phase 24) |
| `src/ops/alerts.py`, `risk_first.py`, `spill.py`, `rest_gate_state.py`, `rest_gate_cli.py` | VERIFIED | Alert sink and sender not constructed anywhere in `src` (deferred row 1) |
| `src/adapters/binance_ratelimit_gate.py`, `binance_userdata_supervisor.py` | VERIFIED | Gate persistence has no composition (every real gate is `LEGACY_IN_MEMORY`, register row) |
| Migrations 0007, 0008, 0009 | VERIFIED | Chain intact per lane B review; `test_persistence_exit_evidence_pg` and PG gates passed under strict |
| `config/execution/execution-limits-v1.toml` | VERIFIED | 15 keys `NOT_CONFIGURED` (14 required + 1 alert-only); live path refuses |

Key link: coordinator -> manager pre-placement (`blocks_new_entries`), loop -> coordinator (`notify_divergence`, `protections`), loop -> sweeper, controller -> store, sink -> journal-first: all WIRED inside the library. Library -> running process: NOT WIRED by design (Phase 24).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Deadline step makes its same-id attempt then escalates | scratch pytest outside the repo importing `tests.test_protection_demo_shapes` helpers (`PYTHONPATH=. uv run pytest <scratchpad>/test_scratch_deadline.py`) | `PLACES 1 2`, state CLOSE_REQUIRED, 1 passed | PASS (ad-hoc only, not a repo test) |
| Repo state unchanged by the check | `git status --short` | only the four pre-existing entries | PASS |

### Probe Execution

SKIPPED: Phase 20 declares no `probe-*.sh`; shellcheck failures (13) are environmental per the caller.

### Requirements Coverage

| Requirement | Source Plans | Status | Evidence |
|-------------|--------------|--------|----------|
| EXEC-02 | 20-01, 03, 04, 09, 10, 12, 14, 16, 21 | Library-level SATISFIED, stays Pending | REQUIREMENTS.md still `[ ]` and traceability "Pending"; Demo evidence and composition are Phases 24-26 |
| OPS-01 | 20-06, 07, 12, 15, 16, 25 | Library-level SATISFIED, stays Pending | same; real-host drill rehearsal not done |
| RISK-03 | 20-02, 07, 09, 14, 18, 21, 26 | Library-level SATISFIED, stays Pending | wording aligned to D077 by 20-26 (owner "approved"); D077 P6 behaviour observed on Demo 2026-10-22 only for A3 |
| EXEC-06 | 20-08, 11, 17 | Library-level SATISFIED, stays Pending | five controls in `EXEC06_CONTROLS` (`manager.py:2634-2644`); no command surface or authentication |
| OPS-05 | 20-01, 13, 16, 22, 26 | PARTIAL, stays Pending | DAILY_STOP/WARNING producers are Phase 21; no producer wired in a process |

No requirement is marked complete. `git diff 567dd8af..HEAD` on REQUIREMENTS.md changes only wording of RISK-03, EXEC-01 and OPS-05, all `[ ]`. All SUMMARY `requirements-addressed` fields say "addressed", none "completed". No orphaned requirement IDs (ROADMAP lists exactly the five).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `docs/operations/RUNBOOK.md` | 937, 941 | `TBD` with a "Phase 24" pointer, added by plan 20-24 | Warning | The debt-marker gate reads TBD in a modified file as a blocker unless it cites an issue, PR or DEF id. These are prose in a runbook, the project's own rule is "missing contract => TBD" (AGENTS.md), and they name Phase 24. Judged non-blocking, flagged for the caller's call |
| `src/reconcile/compare.py` | 578-595 | Pre-Phase-19 rule: every open local ENTRY needs a protective | Warning | See human_verification 1 |
| `src/reconcile/compare.py` | 638 | `symbol=raw_symbol` (IN-B1) | Info | A row with an empty symbol raises and the tick reads it as API_DEGRADATION; fail closed, deferred |

No `FIXME` or `XXX` and no stub returns found in the Phase 20 source files. `TODO`/`HACK`/`PLACEHOLDER` hits are the provenance label name only.

## Warnings (none is a must-have failure)

- **W1. Resting-entry false positive (most consequential).** `compare.py:578-595` still emits `ENTRY_WITHOUT_PROTECTIVE` for every resting entry. Classified CRITICAL `UNPROTECTED_POSITION` with SAFE_MODE (`classify.py:114-118`); the operator exit compare runs the same rule, so it refuses while any entry rests. Pinned by `tests/test_reconcile_classify.py:404`. Disclosed in 20-DEFERRED.md row 35 and the Phase 24 blocker table, but the receiving phase is "proposed, unassigned".
- **W2. Untested criterion clause.** Truth 5 above.
- **W3. Receiving-phase traceability.** ROADMAP Phase 24 carries 3 Phase 20 items; the others live only in 20-DEFERRED.md. Phase 24 has no CONTEXT yet.
- **W4. Bookkeeping stale.** ROADMAP.md:1047-1080 shows plans 20-07..20-26 unchecked, 20-27..20-30 not listed, progress "6/26" (:1035, :1375); STATE.md says `current_plan: 7`. The orchestrator owns these updates.
- **W5. Register counts stale.** `20-DEFERRED.md:67` says `OPS05_MATRIX` has fourteen rows, it has 15 since plan 20-28 (STALE_ENTRY_ORDER). `:29` says fourteen NOT_CONFIGURED keys, there are 15 (14 required + the alert-only `reconcile.entry_stale_grace_ms`). RUNBOOK 21.1 does not name `SYMBOL_OWNERSHIP_CONFLICT`, `RESTORE_NOT_COMPLETE` or `local_active_plans` (register row 137 already says so).
- **W6. Nyquist.** `20-VALIDATION.md` is `status: draft`, `nyquist_compliant: false` with `nyquist_validation: true`.
- **W7. 20-REVIEW.md header** still reads `status: issues_found`, 1 critical; closure is recorded only in 20-DEFERRED.md and the 20-27..20-30 SUMMARYs (no REVIEW-FIX file).
- **W8. Observation, outside the criteria.** A gate-restricted tick (`loop.py:650-666`) only journals `RECONCILE_SKIPPED_GATE`; no operator alert is raised for a multi-day 418 skip. Related to the owner-open Q4; not in OPS-05's list.

## Human Verification Required

### 1. Resting-entry rule (W1)
**Test:** Owner decides the receiving phase and the fix for Pass 2 on a resting entry.
**Expected:** A ROADMAP line or a plan names the change to `src/reconcile/compare.py:578-595` and the pinned test.
**Why human:** needs an owner decision on the rule; the register leaves it unassigned.

### 2. Phase 24 inheritance (W3)
**Test:** Add the Phase 20 "Phase 24" rows and the decision-audit blockers to Phase 24's inherited items, or confirm Phase 24 planning will read 20-DEFERRED.md.
**Expected:** No row of 20-DEFERRED.md depends on memory.
**Why human:** roadmap edit belongs to the owner/orchestrator.

### 3. Add the deadline-step assertion or accept the ad-hoc evidence (truth 5)
**Test:** Extend `test_when_neither_read_ever_shows_the_stop_there_is_one_attempt_per_step_then_b2` with a placement count across the deadline step.
**Expected:** `_places` rises by one on that step, state CLOSE_REQUIRED.
**Why human:** source of the criterion's accepted wording is the owner (O-A); a test change is a follow-up plan.

### 4. Demo-only and real-host items
**Test:** Owner runs A2, A4, P5 and the real-host drills as listed in 20-DEFERRED.md.
**Expected:** results recorded with `[DEMO]` labels.
**Why human:** this machine cannot reach Binance.

### 5. Nyquist validation (W6)
**Test:** `/gsd-validate-phase 20`, or record a waiver.

## Gaps Summary

No must-have is FAILED and no artifact is missing or a stub. The status is `human_needed`, not `passed`, because one criterion clause has no behavioural test and four decisions or runs belong to the owner. The largest real risk is not a Phase 20 defect against its criteria but a design interaction: the delivered reconcile compare conflicts with the D079 fill-driven model for resting entries (W1), and the loop that would expose it is deliberately not composed yet. No requirement should be marked complete on this evidence.

---

_Verified: 2026-10-23_
_Verifier: Claude (gsd-verifier)_
