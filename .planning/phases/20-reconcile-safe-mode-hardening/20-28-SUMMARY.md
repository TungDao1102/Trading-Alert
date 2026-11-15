---
phase: 20-reconcile-safe-mode-hardening
plan: 28
subsystem: reconcile
tags: [reconcile, safe-mode, gap-closure, alerts, tp1, execution-limits]
requires: [20-12, 20-16, 20-20, 20-21, 20-25]
provides:
  - "SafeModeController assertion rounds: a standing reason writes no SAFE_MODE_REENTER row, no state version and no on_enter call (WR-B1)"
  - "LocalAlgoIntent.explained_when_position_below and compare._leg_absence_explained: a TP1 that filled is not UNSYNCED_ALGO (WR-B2)"
  - "exit_safe_mode passes local_active_plans to the compare; refusal codes SYMBOL_OWNERSHIP_CONFLICT (WR-B3) and RESTORE_NOT_COMPLETE (WR-B4)"
  - "ExitReadiness.restore_complete (required) and build_exit_readiness(restore_complete_fn=)"
  - "ReconcileLoop(entry_good_till=), alert STALE_ENTRY_ORDER, journal rows RECONCILE_STALE_ENTRY and RECONCILE_STALE_ENTRY_CHECK_SKIPPED, TickReport.stale_entries"
  - "owner key reconcile.entry_stale_grace_ms (NOT_CONFIGURED, alert only), ALERT_ONLY_LIMIT_KEYS, ExecutionLimits.unset_alert_only_keys()"
affects: [20-24, Phase 24 composition]
gap_closure: true
requirements-addressed: []
status: complete
commits: 4
plan_head_before: ffe13a74af95766f1b4911bbb98cd1083058ef06
plan_head_after: 3937c32bd451c8bb1259f5059f46bfbc0e6f0cb1
actuals:
  tokens: 30564   # chars/4 over `git diff ffe13a74 3937c32b` (122257 chars)
  tasks: 3
  commits: 4      # MEASURED: git rev-list --count ffe13a74..3937c32b (1 plan + 3 task commits; this summary is committed after)
key-files:
  created:
    - tests/test_safe_mode_reentry.py
    - tests/test_reconcile_tp1_fill.py
    - tests/test_reconcile_stale_entry.py
  modified:
    - src/reconcile/safe_mode.py
    - src/reconcile/compare.py
    - src/reconcile/local_intent.py
    - src/reconcile/loop.py
    - src/ops/alerts.py
    - src/ops/drills.py
    - src/execution/execution_limits.py
    - config/execution/execution-limits-v1.toml
    - config/execution/README.md
    - docs/GLOSSARY.md
key-decisions:
  - "WR-B1 is fixed inside SafeModeController with assertion rounds keyed by now_utc, not with an episode set, so a reason that leaves and returns still records and the last reason of a writing round (the most urgent one) stays persisted."
  - "WR-B2 uses the exchange position as the only signal that exists today; the partial-fill limit is stated, and the coordinator exposure that closes it is listed below."
  - "The stale-entry grace key is alert only: left out of unset_keys/require_live_ready so that an unset key skips one check instead of blocking the whole loop."
---

# Phase 20 Plan 28: reconcile gap closure (WR-B1..WR-B4, stale entry alert) Summary

Four review findings of `20-REVIEW.md` are fixed in the reconcile lane, each re-checked against the code first, and one new alert-only detection is added. Nothing is marked complete (`requirements-addressed: []`). Evidence is executed tests with fakes and local PostgreSQL; nothing is [DEMO]. The Demo facts below are quoted from the evidence files named in the task, not re-observed.

## Verification of each finding against the source

| Finding | Verdict | How it was checked |
|---|---|---|
| WR-B1 | Confirmed | RED loop-level test: a foreign order plus a silent user-data feed, 5 ticks, wrote 10 SAFE_MODE journal rows and 10 state saves (expected 2 and 2). |
| WR-B2 | Confirmed | RED: a COMPLETE plan with stop and TP2 resting, TP1 gone and the position at 0.004 of 0.008 was `UNSYNCED_ALGO` in `compare`, in the loop (SAFE_MODE) and at the operator exit. |
| WR-B3 | Confirmed | Old `safe_mode.py` (`git show ffe13a74:...`) run against two active plans on one symbol with a flat account: `ExitDecision(exited=True, refusals=())` (`/tmp/p20/28/b3_old.py`). |
| WR-B4 | Confirmed | Old `build_exit_readiness` over an empty (half-restored) `protections()` view returned `ExitReadiness(0, 0, 0)`; there was no `restore_complete` input. |

No finding was rejected. Two parts of the review's suggested fixes were not followed: WR-B1 uses assertion rounds instead of a cumulative episode set (a cumulative set would persist the least urgent reason when a new low-urgency reason joins a standing high-urgency one, and would never record a reason that leaves and returns); WR-B2 does not read a "TP1 consumed" flag because the coordinator exposes none.

## What was built

- **WR-B1 (`safe_mode.py`).** Calls of `enter_safe_mode` that carry one `now_utc` form a round (the loop passes one per tick). A reason the previous round asserted writes nothing again: no `SAFE_MODE_REENTER` row, no state save, no `on_enter` call. A new reason records; once a round has written, its later reasons re-assert, so the last reason of the round (the loop enters in ascending urgency) stays persisted. A reason that leaves and returns records again. A failed save is still retried by the next unchanged call. Rounds are forgotten at the operator exit. `_enter_calls` still counts every call, so the exit's race check is unchanged.
- **WR-B3.** `LocalIntentLike` has `active_plans`; the exit reads it, passes `local_active_plans` to the compare and refuses `SYMBOL_OWNERSHIP_CONFLICT` when the compare reports `AMBIGUOUS_POSITION_OWNER` (other dirt still gives `COMPARE_NOT_CLEAN`; both codes can appear). A local intent without a usable `active_plans` is `LOCAL_SOURCE_UNREADABLE`. A compare double that does not take the keyword is called without it (the default compare takes it).
- **WR-B4.** `ExitReadiness` has a fourth, required field `restore_complete` (no default, so no composition can forget it). `False` refuses `RESTORE_NOT_COMPLETE`; `None` or a non-bool refuses `READINESS_UNREADABLE`. `build_exit_readiness` takes `restore_complete_fn`; a provider that raises or answers a non-bool gives `None`.
- **WR-B2 (`local_intent.py`, `compare.py`).** The TP1 leg of a COMPLETE plan carries `explained_when_position_below` = the plan's intended quantity. `compare` reads an absent TP1 as a fill only when exactly one local position intent of the same plan and exactly one non-zero exchange position row exist for the symbol, the sides agree (LONG positive, SHORT negative) and `0 < abs(amount) < bound`. A full or larger position, no position, a second plan, a second row, the wrong side or a plan without a usable quantity keep `UNSYNCED_ALGO`. TP2 and the stop never carry the bound and stay required.
- **Stale resting entry (`loop.py`, `alerts.py`, limits, GLOSSARY).** `ReconcileLoop(entry_good_till=...)` (plan hash to UTC `goodTillDate`, supplied by the caller as for `UnknownEntryResolver`). A system ENTRY order owned by a local ENTRY intent, with exchange status exactly `NEW`, more than `reconcile.entry_stale_grace_ms` past its `goodTillDate` raises `STALE_ENTRY_ORDER` (HIGH, reason `ENTRY_NOT_EXPIRED_AFTER_GTD`) once while it stands (an undelivered alert is retried next tick; a return after leaving is alerted again) and journals `RECONCILE_STALE_ENTRY`. It enters no SAFE_MODE, cancels nothing, changes no plan state; a test also pins that `loop.py` calls no `cancel_*`, `place_*` or `new_*`. While the key is unset, one `RECONCILE_STALE_ENTRY_CHECK_SKIPPED` row says so; an unknown `goodTillDate` (None, naive, raising source) skips that order and says so once per order. A loop built without `entry_good_till` runs no check and journals nothing about it.

## RED evidence (honest)

- **WR-B1:** `tests/test_safe_mode_reentry.py` before the fix: 5 of 9 failed, among them the loop-level test (`assert (10, 10) == (2, 2)`). The 4 that passed before the fix (a reason that leaves and returns, the shrinking set, the re-entry after an exit, the failed-save retry) pin behavior that already held. Saved in `/tmp/p20/28/red-b1.txt`.
- **WR-B3 and WR-B4:** the extended `tests/test_safe_mode_exit_operator.py` could not be collected before the fix (`TypeError: ExitReadiness.__init__() got an unexpected keyword argument 'restore_complete'`, `/tmp/p20/28/red-b3b4.txt`), so the individual new tests were not seen failing one by one. The confirmation of the two findings is the run of the old module quoted above (`/tmp/p20/28/red-b3b4-old.txt`).
- **WR-B2:** `tests/test_reconcile_tp1_fill.py` before the fix: 10 of 19 failed (`/tmp/p20/28/red-b2.txt`); the "still a divergence" tests (full position, no position, wrong side, TP2/stop required in the old sense) passed already, as expected.
- **Stale entry:** `tests/test_reconcile_stale_entry.py` before the fix: at least 15 of 18 failed (missing key, event and loop argument; the saved log keeps only its last 15 lines). It passed on the first run after the implementation.
- The TDD commits are not split into test-then-implementation commits (the tests and the pins they needed were edited together per task); the RED runs above were made before each implementation.

## Verification actually run

- Three new test files and the extended ones: all pass. Wider run (every test file that mentions execution limits, OPS05, ExitReadiness, safe_mode, local_intent or reconcile; 87 files, `-m "not docker" -n 4`, `TRADING_CI_STRICT=1`, `TEST_DATABASE_URL` set): **3951 passed, 0 skipped, 0 failed**.
- `tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_persistence_exit_evidence_pg.py tests/test_agents_md.py`: pass (the exit-evidence PG test ran against local PostgreSQL).
- `uv run mypy src`: no issues (235 files). `uv run ruff check`: clean. `uv run ruff format --check`: 731 files already formatted. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS. `uv lock --check`: ok. `pyproject.toml` and `uv.lock` untouched.
- The full suite was not run (orchestrator's job).

## Pins changed

- `tests/test_phase18_gate.py` and `tests/test_no_unratified_defaults.py`: `GUARDED_NAMES` 50 to 52 (the new key text and field name).
- `tests/test_execution_limits.py`: reconcile section 4 to 5 keys, the committed file now has 30 `NOT_CONFIGURED` words (was 28), the key table test compares the 14 required keys plus the alert-only key, the all-unset round trip also sets the new field and checks `unset_alert_only_keys()`.
- `tests/support/execution_limits.py`: TEST_ONLY value 4747 for `reconcile.entry_stale_grace_ms`. `tests/support/reconcile_rig.py`: `build_rig(entry_good_till=)`.
- `tests/test_alerts.py` (event set plus `STALE_ENTRY_ORDER` HIGH) and `tests/test_alerts_ops05_matrix.py` (the new row and its own requirement source `owner request 2026-10-23 (stale entry)`).
- `ExitReadiness(a, b, c)` call sites got the fourth argument in `tests/test_safe_mode_exit_operator.py`, `tests/test_controller_rehydrate.py`, `tests/test_journal_failure_paths.py`, `tests/test_phase8_audit_reviewfix.py` (its `_LocalIntentStub` now has `active_plans`).

## Deviations from Plan

**1. [Rule 3 - Blocking] `src/ops/drills.py` edited (outside the named files).** Its default readiness `ExitReadiness(0, 0, 0)` would raise with the new required field; changed to `ExitReadiness(0, 0, 0, True)`. One line. The restore drill passes as before.

**2. [Owner decision applied with a stated interpretation] The stale-entry key does not block the live path.** The task says the key stays `NOT_CONFIGURED` and "the check is skipped and says so while the key is unset". The loop constructor calls `limits.require_live_ready()`, so a key counted like the other fourteen would stop the loop from being built at all, and "skipped" could never happen. The key is therefore in `ALERT_ONLY_LIMIT_KEYS`: loaded, validated and given a provenance label like every key, but left out of `unset_keys()` and `require_live_ready()`. No number is chosen. If the owner prefers it to block like the others, move it out of `ALERT_ONLY_LIMIT_KEYS` (the skip branch stays defensive).

**3. Docs.** Only `docs/GLOSSARY.md` section 9.4 got a row (`STALE_ENTRY_ORDER`, marked as an alert event and not a SAFE_MODE reason) plus one clause on the existing `SYMBOL_OWNERSHIP_CONFLICT` row; edited byte-aware, CRLF kept. `config/execution/README.md` and the TOML header describe the new key (they are the key list the tests parse). `docs/DECISIONS.md` and `docs/operations/RUNBOOK.md` were not edited. **RUNBOOK 21.1 is now stale**: it lists the seven exit rows and does not name `SYMBOL_OWNERSHIP_CONFLICT` (row 4) or `RESTORE_NOT_COMPLETE` (row 5) or the `local_active_plans` input; it needs a sentence in a later docs plan.

## Limits and what the coordinator would have to expose (WR-B2)

The fix reads the exchange position only. Known limit: for a plan whose entry only partly filled, the position is below the intended quantity from the start, so for that plan an absent TP1 is accepted although nothing shows the fill (an externally cancelled TP1 of a partial-fill plan is hidden; the stop and TP2 are still required, so the position stays protected). Also, `tp1_quantity` is not used: reconcile cannot compute "reduced by exactly the TP1 quantity".

To close the gap without editing reconcile logic again, `PlanProtection` (`src/execution/protection.py`, not edited here) would have to expose one of:
- `tp1_filled_at_utc` (or a `tp1_filled: bool`), set when a stream fill of the TP1 client id is seen (the Demo evidence shows the triggered child order carries the TP1 client id and ends FILLED). `derive_local_intent` could then drop the TP1 leg with no position inference at all.
- or `tp1_quantity: Decimal | None`, the quantity the TP1 leg was sent with; the bound in `derive_local_intent._positive_quantity(plan.entry_quantity)` would become `entry_quantity - tp1_quantity` (the "reduced by the TP1 quantity" rule).

The algo REST query by client id was considered and rejected as the signal: Demo answers `-2013` for up to about 90 s after a state change and `FINISHED` only later (`19-OWNER-GAPS.md` section 2a), so a first tick after the fill would still enter SAFE_MODE, and `FINISHED` means "filled or canceled" (D-07 class UNKNOWN by owner decision O-18-01).

## Findings for later plans

1. **Composition (Phase 24).** `build_exit_readiness(..., restore_complete_fn=lambda: coordinator.restore_complete)`; `local_intent_fn` must return the real `LocalIntent` (it carries `active_plans`); `ReconcileLoop(entry_good_till=)` must be bound to the intent store plus the plan expiry (the GTD the manager sends is `good_till_date_ms(trade_plan.expiry_utc)`). Add these to the Phase 24 composition note of `20-DEFERRED.md`.
2. **WR-B1 limits.** The rounds are keyed by `now_utc`; two real ticks with an identical `now_utc` behave like the old code (no regression, no gain). After a process restart the rounds are empty, so the first tick writes the set once. The per-divergence alerts of the loop (`_send_alert`) are still raised every tick and rely on the sink's dedupe window (unchanged, not in this finding).
3. **Merge notes for the other lanes.** This plan touches `src/execution/execution_limits.py`, `config/execution/*`, `tests/support/execution_limits.py`, `tests/test_execution_limits.py`, `tests/test_no_unratified_defaults.py` and `tests/test_phase18_gate.py` (the 50 to 52 pins). A lane that also adds a limits key needs to add its own count on top (and the TOML, README and TEST_ONLY value lines will conflict textually). `src/ops/drills.py` has a one-line change. `src/ops/alerts.py` has a new event and a matrix row.
4. The deferred register row "The persisted SAFE_MODE reason is the last one entered in a tick" stays accurate: the persisted reason is still the last of a writing round.
5. The deferred row about Pass 2 flagging a resting entry as `ENTRY_WITHOUT_PROTECTIVE` still stands; the stale-entry tests therefore allow that one pre-existing reason in `enter_calls` and assert that the stale check adds none of its own.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or schema; the new alert carries a fixed code, the symbol and the plan hash only, and the new journal rows carry ids and times.

## Self-Check: PASSED

- Files present: the three new test files, `20-28-PLAN.md`, this summary.
- Commits reachable from HEAD: feadc433, a6afa9e2, b7092d41, 3937c32b.
