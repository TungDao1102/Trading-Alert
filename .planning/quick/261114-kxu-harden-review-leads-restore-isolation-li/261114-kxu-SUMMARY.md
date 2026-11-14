---
phase: quick-261114-kxu
plan: 01
subsystem: restart-restore, protection, backup, live-scheduler, binance-adapter-audit
tags: [restore-isolation, liquidation-check, backup-path-safety, child-env-whitelist, stall-watchdog, adapter-audit]
requires: []
provides:
  - "PartialRestore + per-entry isolation in the restart restore (healthy plans restored, bad ones -> SAFE_MODE RESTORE_INCONSISTENT)"
  - "Post-fill liquidation check survives a flat positionRisk read (bounded at 3)"
  - "Backup root/manifest-key refusal and child_env whitelist for pg_dump, pg_restore, alembic, rclone"
  - "Observe-only scheduler stall watchdog (TaskSpec.stall_after_seconds, TaskEvent kind stall)"
affects: [src/reconcile/startup.py, src/live/startup.py, src/execution/protection.py, src/ops/backup.py, src/ops/backup_remote.py, src/live/scheduler.py]
tech-stack:
  added: []
  patterns: ["per-row fault isolation with a typed partial-result exception", "child-process env whitelist", "observe-only watchdog sibling task"]
key-files:
  created: []
  modified:
    - src/reconcile/startup.py
    - src/live/startup.py
    - src/execution/protection.py
    - src/ops/backup.py
    - src/ops/backup_remote.py
    - src/live/scheduler.py
    - tests/test_live_restart_rehydrate.py
    - tests/test_startup_recovery.py
    - tests/test_live_start_sequence.py
    - tests/test_protection_liquidation.py
    - tests/test_backup.py
    - tests/test_backup_restore.py
    - tests/test_backup_remote.py
    - tests/test_live_scheduler.py
    - tests/test_live_wiring_parts.py
decisions: []
metrics:
  duration: "about 1h 40m"
  completed: 2026-11-14
status: complete
commits: 4
plan_head_before: cac77fb6e6a439fc72aae91c99d5851ea2bc555a
plan_head_after: 8c1d3335c4035119faf849e70ac4c9c9b1db7b12
actuals:
  tokens: 10500    # chars/4 over the changed lines of src/ and tests/ (git diff, +/- lines only)
  tasks: 5
  commits: 4       # MEASURED: git rev-list --count cac77fb6..HEAD
---

# Phase quick-261114-kxu Plan 01: Harden review leads Summary

Four fail-closed hardenings (per-entry restart-restore isolation, a flat-read-tolerant post-fill liquidation check, backup path safety with a whitelisted child environment, an observe-only scheduler stall watchdog) and a read-only audit of the order-write functions of `src/adapters/binance_usdm.py`.

## Commits

| Task | Commit | Message |
| ---- | ------ | ------- |
| 1 | 53d5926b | fix(quick-261114-kxu): isolate each restorable entry in the restart restore |
| 2 | 6afe408e | fix(quick-261114-kxu): keep the post-fill liquidation check pending across flat position reads |
| 3 | 06dc8171 | fix(quick-261114-kxu): refuse escaping backup roots and manifest keys, whitelist child env |
| 4 | 8c1d3335 | feat(quick-261114-kxu): observe-only stall watchdog for live scheduler tasks |
| 5 | none (read-only audit, gates, this SUMMARY) | |

All four carry the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Nothing was pushed or merged.

## Task 1: restore isolation

**What changed.** `restored_plans_builder` (src/live/startup.py) wraps each entry in `try/except _ROW_FAULTS` (RestoreSourceMissing, ValueError, TypeError, LookupError, ArithmeticError); a faulty row is logged by ids and class name only and skipped; the client-id index is filled for the healthy plans; then `PartialRestore(plans, n)` is raised. `run_startup_recovery` (src/reconcile/startup.py) catches `PartialRestore` before the generic clause, restores the healthy plans, then fails COORDINATOR_RESTORED once with SAFE_MODE `RESTORE_INCONSISTENT`. `StartupReport.plans_unrestorable` is the new last field. A store outage (any class outside `_ROW_FAULTS`, tested with OSError; `StoreUnavailable` derives from `PersistenceError(Exception)`, so it is outside the family too) still fails the whole build: `DB_FAILURE`, nothing restored, `restore_complete` False.

**RED (honest note).** The reconcile-side change (`PartialRestore`, step 4a branch) was written before the first test run. RED was recorded in two ways: (1) with both src files at HEAD the three test modules failed at collection (`ImportError: cannot import name 'PartialRestore' from 'src.reconcile.startup'`); (2) with the new reconcile code and `src/live/startup.py` at HEAD the behavior tests failed:
```
FAILED tests/test_live_restart_rehydrate.py::test_a_restorable_entry_without_its_plan_or_snapshot_is_isolated
FAILED tests/test_live_restart_rehydrate.py::test_one_corrupt_row_does_not_stop_the_healthy_plan_from_being_restored[no-plan]
FAILED tests/test_live_restart_rehydrate.py::test_one_corrupt_row_does_not_stop_the_healthy_plan_from_being_restored[row-refused]
E   src.live.startup.RestoreSourceMissing: a restorable entry has no persisted plan or snapshot
E   ValueError: the entry row does not carry the deterministic client id of its plan
```
**GREEN.** `tests/test_live_restart_rehydrate.py tests/test_startup_recovery.py tests/test_live_start_sequence.py tests/test_live_replay_restart.py tests/test_demo_twin_s07_restart_cuts.py tests/test_phase24_gate.py`: all pass (one xfail in the set, no skips reported). `tests/test_live_replay_restart_pg.py` was not part of the verify command and needs `TEST_DATABASE_URL` (it would skip without it); it was not run.

**Test deviation from the plan text.** The plan says new entries "stay blocked" via `coordinator.blocks_new_entries()`. After a partial restore the coordinator is restored (`restore_complete` True) and `blocks_new_entries()` is False; the block is SAFE_MODE. The tests therefore assert `restart.safe_mode.in_safe_mode` and `safe_mode.guard_new_entries(None).is_no_trade` (RECONCILIATION_REQUIRED). For the store outage the coordinator-level block (`blocks_new_entries()` True, `restore_complete` False) is asserted as before.

### Report (a): what the process does after `StartupStepFailed` at RECOVERY

- The recovery step body raises `StartupStepFailed(CODE_RECOVERY_INCOMPLETE, SAFE_MODE_RESTORE_INCONSISTENT)` when `report.failed_steps` is non-empty or `not report.restore_complete` (src/live/startup.py:988).
- `HOLD_STEPS` = CONFIG, GATE, ALEMBIC, SAFE_MODE, ENABLEMENT (src/live/startup.py:180-182). RECOVERY is not a hold step, so `_Run.run` takes the `StartupStepFailed` branch to `degrade` (src/live/startup.py:801-806), not `hold`.
- `degrade` appends the step to `degraded`, calls `enter_safe_mode` (which returns early when SAFE_MODE is already on, as it is after the recovery entered `RESTORE_INCONSISTENT`; src/live/startup.py:760-772) and journals the step FAILED (774-778).
- `admitted=held is None` (src/live/startup.py:1102): the process is admitted, in SAFE_MODE, with RECOVERY in `degraded_steps`. Stream, bot and scheduler start (monitoring continues). `_enable` skips HEALTH and ENABLE when `run.degraded` or SAFE_MODE is set (src/live/startup.py:1052-1065), so placement is never enabled; this is the parametrized case `recovery-builder-partial` of `tests/test_live_start_sequence.py` (admitted, in SAFE_MODE, RECOVERY degraded, ENABLE SKIPPED).
- `--hold-on-refusal` (src/live/runtime.py) applies only to a held start: the runner path is `if not outcome.admitted:` (src/live/runtime.py:565-570). A degraded RECOVERY is admitted, so the process keeps running; exiting SAFE_MODE stays an operator action (RUNBOOK 21.1).

### Report (b): reconcile behavior for an exchange position whose plan was not restored

- The coordinator has no tracked plan for it and the client-id index has no entry for its order ids (the builder skipped the row before `rebuild_client_id_index`), so a stream fill of that entry is an unknown order for the router, not a known fill. This is the residual risk: nothing places a stop for that plan. SAFE_MODE blocks new entries only; it does not cancel a resting entry and does not touch the position.
- ORPHAN_PROTECTIVE needs no exchange position to be false: `compare.py` emits it only when the protective has "no matching local position AND no exchange position" (`is_protective and not has_position and not entry_is_resting`, src/reconcile/compare.py:497-519). With an exchange position present the stop is never an ORPHAN_PROTECTIVE, so it is never swept. The sweeper only acts on `diff.orphan_protectives` (src/reconcile/loop.py:810-812) and its policy is `SWEEP_ORPHAN` for that kind alone (src/reconcile/classify.py:101-105).
- What the untracked position produces: the compare reports position divergences (UNSYNCED_POSITION "exchange position with no matching local intent", src/reconcile/compare.py:544 and 653; or POSITION_WITHOUT_STOP / TP_ONLY_POSITION, compare.py:1007-1024, depending on the local inputs). Each enters its own SAFE_MODE reason and sends an alert (ALERT_DIVERGENCE or ALERT_UNPROTECTED_POSITION, src/reconcile/classify.py:101-120). The DELEGATE_TO_COORDINATOR kinds find no owner among the tracked plans (`_owner_of`, src/reconcile/loop.py:1562-1585) and are counted `undelegated` (loop.py:797-803). So the operator is alerted and SAFE_MODE is already on with `RESTORE_INCONSISTENT`; the stop and the position are left to the operator (RUNBOOK section 21 manual orders).
- One behavior change to know: after a partial restore `restore_complete` is True, so the reconcile loop runs ticks (it skips with `RECONCILE_SKIPPED_RESTORE_PENDING` only while restore is incomplete, src/reconcile/loop.py:566-568). Before this change a single bad row left the coordinator unrestored, the loop skipped, and no plan (healthy or not) was supervised. I did not run a full position-with-unrestored-plan scenario; the divergence kind depends on the compare's local inputs.

### Report (c): is a DECISIONS row needed?

Grepped `docs/DECISIONS.md`, `docs/operations/RUNBOOK.md`, `docs/GLOSSARY.md`, `docs/DOC_STATUS.md`, `AGENTS.md` for `RestoreSourceMissing`, `COORDINATOR_RESTORED`, `restored_plans_builder`, `PartialRestore`, restore with `DB_FAILURE`, `RESTORE_INCONSISTENT`. No canonical text states the old all-or-nothing behavior as a rule:
- `docs/DECISIONS.md` D095 (line 99) mentions `RestoreSourceMissing` only as the historical basis of the snapshot-recorder decision ("the recovery failed closed"); it stays true for the missing-snapshot case in the sense that SAFE_MODE is entered and entries are blocked.
- RUNBOOK 22.2: "a failure elsewhere continues in SAFE_MODE with entries blocked and monitoring running": still true.
- `docs/GLOSSARY.md:307` defines `RESTORE_INCONSISTENT` as "restart recovery found local state that cannot be trusted: an unreadable or corrupt spill, a replay conflict, a stop history the journal cannot establish, a plan restored in a state its rows contradict". A restorable entry that cannot be rebuilt now also enters it.

So no row is required; the owner may want one because the restore semantics changed from all-or-nothing to per-entry. Proposed text, if wanted (docs not edited):

> D110 | Restart restore isolates each restorable ENTRY row (quick 261114-kxu) | Proposed | The restart restore rebuilds each restorable ENTRY row on its own. A fault of one row (no persisted plan or snapshot, a row the rebuild refuses, a malformed value) is skipped and counted; the healthy plans are restored and stay supervised; recovery then enters SAFE_MODE `RESTORE_INCONSISTENT` (entries blocked, monitoring continues, exit is manual). A fault of the store itself (any other exception class) keeps the earlier behavior: nothing is restored, SAFE_MODE `DB_FAILURE`, `restore_complete` False. A plan that was not restored has no stop placed by the coordinator and its order ids are unknown to the stream router; the operator is alerted by the reconcile divergences and decides by hand. Source: `.planning/quick/261114-kxu-harden-review-leads-restore-isolation-li/261114-kxu-SUMMARY.md`.

Doc line to update with it: GLOSSARY.md:307, append "a restorable entry whose persisted plan or snapshot cannot be rebuilt (the other plans are still restored)".

## Task 2: liquidation check across flat reads

**What changed.** `_check_liquidation_once` (src/execution/protection.py) sets `liquidation_checked` only when a non-flat row is read. A flat row increments `_Tracked.liquidation_flat_reads`; at `LIQUIDATION_FLAT_READS_LIMIT` (3, a structural retry bound, not an owner number) the plan is marked checked without a watch call and one `PROTECTION_LIQUIDATION_SKIPPED_FLAT` note (payload `flat_reads`) is journaled. An unreadable read neither counts nor resets. The old test `test_a_flat_position_marks_the_plan_checked_without_asking_the_watch` was replaced by three tests.

**Test design note.** Zeroing `fake.positions[...]` also loses the fake's stop (the plan goes FLAT), so the tests script only the liquidation check's own positionRisk read (first read of each step) with a `_PositionReads` helper; the fake's position and stop stay open, which models a lagging positionRisk.

**RED** (behavior reverted to HEAD, new tests kept):
```
E       AssertionError: assert True is False            (flat read marked the plan checked)
E       AssertionError: assert [] == ['PROTECTION_...SKIPPED_FLAT']
E       AssertionError: assert 0 == 2                    (liquidation_flat_reads)
FAILED ...::test_a_flat_read_does_not_end_the_check_a_later_position_is_judged
FAILED ...::test_three_consecutive_flat_reads_end_the_check_with_one_journal_note
FAILED ...::test_an_unreadable_read_between_flat_reads_neither_counts_nor_resets
```
**GREEN.** `tests/test_protection_liquidation.py` 33 passed; `tests/test_phase22_gate.py tests/test_phase24_gate.py tests/test_protection_coordinator.py tests/test_protection_supervision.py tests/test_protection_take_profits.py tests/test_protection_rebuild.py tests/test_live_stream_to_protection.py tests/test_protection_stop_lost.py` pass.

## Task 3: backup path safety and child environment

**What changed.** `backup()` calls `_checked_parquet_roots` first (before `mkdir` and before pg_dump): ValueError for a root whose name is empty, `.` or `..`, or whose resolved path equals, lies inside or contains the resolved bundle root. `run_drill()` calls `_check_root_name` for every root before any delete. `prune_bundle()` raises ValueError ("refusing prune: N manifest keys escape the bundle root") when any key is unsafe (`_is_unsafe_key`) or resolves outside the bundle, before touching anything; the unlink loop keeps a containment check. New `child_env(prefixes, extra, environ)` whitelist (`_CHILD_ENV_NAMES`) replaces the four `{**os.environ, ...}` spreads: pg_dump and pg_restore use `prefixes=("PG",)`, `extra=target.env`; the alembic migrate child `extra={"DATABASE_URL": url}`; `make_rclone_runner` `prefixes=("RCLONE_",)`, `extra={**mapped, **extra}`.

**RED.** Run against HEAD with a timeout; the four path-overlap parametrizations that need an unrefused `backup()` (root `.`, `..`, the bundle itself, a directory containing the bundle) were NOT run in RED, because unrefused they copy a tree into itself and `.` copies the whole repository into a tmp directory (the first RED attempt hung for that reason and was stopped; it only wrote under pytest tmp directories). The other new tests failed as expected:
```
E   Failed: DID NOT RAISE ValueError      (x3: prune_refuses[dotdot|absolute|backslash])
E   AttributeError: module 'src.ops.backup' has no attribute 'child_env'   (x2)
E   AssertionError: BINANCE_DEMO_API_SECRET reached the child environment
E   AssertionError: assert ('DATABASE_URL' not in {...})                    (rclone runner)
FAILED tests/test_backup.py::test_drill_refuses_a_root_named_dotdot_before_deleting_anything
```
**GREEN.** `tests/test_backup.py tests/test_backup_restore.py tests/test_backup_remote.py tests/test_backup_retention.py tests/test_backup_lock.py tests/test_backup_gate.py` all pass (`-m "not docker"`), plus `tests/test_deploy_backup_scripts.py tests/test_deploy_compose.py tests/test_deploy_migrate.py tests/test_evidence_remote.py tests/test_soak_runbook.py`. The docker-marked backup tests were not run.

**Acceptance greps:** `**os.environ` outside comments: backup.py 0 (baseline 3), backup_remote.py 0 (baseline 1); `def child_env` 1; `child_env(` in backup_remote.py 1; `_checked_parquet_roots` 2.

### Env-variable check (what a child reads that the whitelist could drop)

Checked `deploy/*.sh`, `docker-compose.yml`, `Dockerfile`, `docs/operations/RUNBOOK.md` (grep for `PG_DUMP_BIN`, `PG_RESTORE_BIN`, `RCLONE_BIN`, `PGSSL`, `PGSERVICE`, `PGPASSFILE`, `PGHOST`, `LD_LIBRARY_PATH`, `SSL_CERT`, `HTTPS_PROXY`, `RCLONE_`) and `src/db/alembic/env.py`:
- No deploy script or compose service sets a variable that pg_dump, pg_restore, rclone or alembic read from the child environment and the whitelist drops. `PG_DUMP_BIN`, `PG_RESTORE_BIN` and `RCLONE_BIN` are read by this process, not by the child. The backup and ops compose services pass `*database-env` and the backup env file to the Python process, which maps what the children need explicitly.
- `src/db/alembic/env.py:29` reads only `DATABASE_URL`, which the migrate runner passes in `extra`.
- Any `PG*` variable of the parent (for example `PGSSLMODE`, `PGSSLROOTCERT`) and any `RCLONE_*` variable (for rclone) still passes through by prefix, so operator tuning keeps working. Nothing was added to `_CHILD_ENV_NAMES` beyond the plan's list. A host that sets a library path (`LD_LIBRARY_PATH`) for the pg client would lose it; none is configured in this repository.

### Lead (not fixed): scripts/export_soak_evidence.py

`scripts/export_soak_evidence.py:848` has the same full-environment spread (`env={**os.environ, **env}` for its rclone child). It is outside this plan's file list; the same `child_env(prefixes=("RCLONE_",), extra=env)` would close it. Reading `os.environ` at 1211 is a separate, harmless read of the mapping.

## Task 4: stall watchdog

**What changed.** `TaskEventKind` gains `"stall"`; `TaskSpec.stall_after_seconds: float | None = None` (finite and > 0, else ValueError naming the task; validated with `math.isfinite`, no `float(...)`). `Scheduler._loop` starts a sibling watchdog task only when the bound is set; it awaits the injected sleep, logs one `_LOGGER.error` line (task name and bound) and records one `TaskEvent(kind="stall")` through a shielded `_record_stall` (a raising `record` is logged by class name and never stops the loop). The loop keeps awaiting `spec.run()` directly; a `finally` cancels and gathers the watchdog. The run is never cancelled or cut short; no asyncio timeout helper is named in code or docstrings. Default None: same sleeps and journal as before (the existing tests pass unchanged, including `sorted(set(time.sleeps)) == [15.0, 60.0]`).

**RED:** `TypeError: TaskSpec.__init__() got an unexpected keyword argument 'stall_after_seconds'` (9 tests of `tests/test_live_scheduler.py`). The `tests/test_live_wiring_parts.py` stall-journal test passes before and after at runtime (the kind is only a `Literal` annotation); it pins the journal row shape.

**GREEN.** `tests/test_live_scheduler.py tests/test_live_ast_guards.py tests/test_live_wiring_parts.py tests/test_live_wiring.py tests/test_phase24_gate.py` pass. Acceptance: `stall_after_seconds` appears 7 times in src/live/scheduler.py (at least 3); `wait_for` outside comments 0; `git diff --quiet HEAD -- src/live/wiring.py` clean (wiring untouched).

### Why no Telegram alert and no wiring value (and what the owner would decide)

- No wiring value: no config home for a stall bound exists (`grep -n "stall\|watchdog"` in `src/execution/execution_limits.py` and `config/execution/execution-limits-v1.toml` returns nothing) and D-12 forbids a cadence number in code. The protection task therefore keeps the default None; the watchdog is built and tested but dormant in production until the owner sets a value.
- No alert: the production record path is `LiveWiring._record_task` -> `task_event_journal` (src/live/wiring_parts.py:218): a journal row only. `ALERT_EVENTS` in `src/ops/alerts.py` is a closed contract (the OPS-05 matrix) pinned by `tests/test_alerts.py` and `tests/test_alert_wording.py` (22 events).

**Proposal TASK_STALLED (alert), for the owner:** a new HIGH alert event `TASK_STALLED` in `ALERT_EVENTS` (src/ops/alerts.py ~96), wording along the lines of "A live task has been running longer than its bound and was not stopped (task name only). Check the process; a placement in flight is never re-sent.", a GLOSSARY entry, a SECURITY_AND_OPERATIONS 5.1 matrix row, a DECISIONS row (the closed contract change), and updates to the two pinned tests (`tests/test_alerts.py`, `tests/test_alert_wording.py`). Wire the scheduler `record` path to raise that alert for `kind == "stall"` only.

**Proposal NOT_CONFIGURED stall key, for the owner:** a new limit key, for example `scheduler.protection_stall_after_ms`, `NOT_CONFIGURED` in `config/execution/execution-limits-v1.toml` until the owner sets a value, read in `LiveCadences.from_limits` (src/live/scheduler.py) and passed as `stall_after_seconds` to the protection `TaskSpec` where `LiveWiring` builds its specs (src/live/wiring.py). An unset key keeps the watchdog off (today's behavior).

## Task 5: audit of the order-write functions of src/adapters/binance_usdm.py (read-only)

No file under `src/adapters/` changed (`git diff --quiet HEAD -- src/adapters/binance_usdm.py` is clean). Evidence is file:line at HEAD 8c1d3335. SDK facts were read from the installed `binance_sdk_derivatives_trading_usds_futures` (enums and `new_order` signature): the SDK itself only raises `RequiredError` for a None required argument and converts enums with `Enum(value)` (ValueError for a value outside the enum); it does no range check. In the table, "enum" means the adapter builds the SDK enum from the raw string as an argument expression, so an unknown value raises ValueError before `_sdk_call` runs and nothing is sent. `_sdk_call` (binance_usdm.py:883) adds the signed-policy requirement and the shared REST gate for every function.

| Function | Check | Status (present/absent/delegated) | Evidence (file:line) | Risk if absent | Recommendation |
| -------- | ----- | ------ | -------- | -------------- | -------------- |
| cancel_normal_order (1178) | symbol non-empty; orig_client_order_id non-empty / format | absent | 1178-1235 (no argument check; SDK only rejects None) | An empty id reaches the exchange and fails there (-1102 class); no wrong order can be cancelled by it | Add a non-empty text check, same wording as `change_margin_type` (1895) |
| cancel_normal_order | cancel idempotence, bounded retry | present | `_cancel_retrying` (917), ORDER_ABSENT is success (1226-1235) | n/a | none |
| cancel_algo_order (1237) | client_algo_id non-empty; symbol | absent; symbol accepted but NOT sent | 1262-1268: SDK `cancel_algo_order(algo_id, client_algo_id, recv_window)` has no symbol parameter | `symbol` is dead documentation: a wrong symbol is never caught; an empty id fails at the exchange | Validate the id as text; either use `symbol` (cross-check by the caller's probe) or drop it from the signature in a reviewed change |
| place_entry (1299) | quantity positive | absent (type and finiteness delegated to `_decimal_to_wire`, 678-697) | 1386; upstream quantity: manager.py:944 `sized.quantity`, bound `<= approved` and `approved > 0` at manager.py:950-960 | A zero or negative Decimal reaches the exchange (rejected there); no size inflation, the bound is upstream | Add `quantity > 0` here so the adapter is safe on its own |
| place_entry | price positive when sent | absent | 1387; upstream manager.py:929 `quantize_price` | Same as above | Add `price > 0` |
| place_entry | side within BUY/SELL | present (enum) | 1382 `NewOrderSideEnum(side)`; manager.py:947 side from the bound plan | n/a | none |
| place_entry | order type | present by construction | 1383 `NewOrderTypeEnum.LIMIT` hard-coded | n/a | none |
| place_entry | time in force allow-list | absent: the enum also accepts IOC, FOK, GTX, RPI | 1385 `NewOrderTimeInForceEnum(time_in_force)`; docstring 1325 says GTC or GTD; manager passes "GTD" (manager.py:1339-1346) | A caller bug could send IOC/FOK/GTX/RPI; semantics differ (an IOC entry never rests) | Allow-list GTC/GTD in the adapter |
| place_entry | GTD / goodTillDate consistency | present | 1350-1357 (int not bool; GTD requires it; refused with any other TIF); "does not range-check" stated at 1331-1334 | A GTD time in the past is rejected by Binance | Range check stays in the pure core (manager.py:1182 `good_till_date_ms`) |
| place_entry | reduceOnly vs closePosition | present by construction | no `reduce_only` or `close_position` parameter in the signature (1299-1310) | n/a | none |
| place_entry | symbol non-empty; position_side allow-list | absent: `position_side` is passed as a raw string to the SDK | 1384 (raw); manager.py:1072 hard-codes "BOTH" | An unexpected value is rejected by the exchange | Validate against BOTH/LONG/SHORT as `place_market_close` does (1434) |
| place_entry | client order id format / length | absent (delegated) | 1388; id from `derive_client_order_id` (order_ids.py:107, 36 chars); manager.py:919 | A bad id is rejected by the exchange; the deterministic derivation is the real guard | Optional: reuse the 1..36 check of `place_market_close` (1447-1454) |
| place_entry | Decimal-only wire | present | `_decimal_to_wire` (678-697): TypeError for non-Decimal (float), ValueError non-finite, fixed-point `format(value, "f")` | n/a | none |
| place_entry | drift guard and policy before any call | present | 1362-1363 `_require_signed_policy`, `_require_entries_allowed` | n/a | none |
| place_market_close (1394) | side BUY/SELL; position_side; side closes the leg (SELL on LONG, BUY on SHORT) | present | 1432-1442 | n/a | none |
| place_market_close | quantity Decimal, finite, > 0 | present | 1443-1446 | n/a | none |
| place_market_close | client id 1..36 chars | present | 1447-1454 (`_MAX_CLIENT_ORDER_ID_LEN` 231) | n/a | none |
| place_market_close | reduceOnly One-way; order type | present | 1464-1466 (`reduce_only=TRUE` when BOTH), 1472 `MARKET` hard-coded | Hedge sends no reduceOnly (documented, V1 One-way only) | none |
| place_market_close | symbol non-empty | absent | 1470 (raw) | Rejected by the exchange | Add the non-empty check |
| place_algo_protective (1480) | closePosition with quantity or reduceOnly | present | 1547-1551 | n/a | none |
| place_algo_protective | non-close leg needs an explicit quantity | present | 1552-1555 | n/a | none |
| place_algo_protective | quantity > 0 when given; trigger_price > 0 | absent (Decimal/finite via `_decimal_to_wire`) | 1571, 1575; upstream: stop trigger positive in `RestingEntry.__post_init__` (protection.py:565-571), call sites protection.py:1971-1984 and manager.py:1938 | A zero or negative trigger/quantity reaches the exchange | Add positivity checks |
| place_algo_protective | order type allow-list (STOP_MARKET, TAKE_PROFIT_MARKET) | absent: `NewAlgoOrderTypeEnum` accepts LIMIT, MARKET, STOP, STOP_MARKET, TAKE_PROFIT, TAKE_PROFIT_MARKET, TRAILING_STOP_MARKET | 1569; docstring 1513 says two types; callers hard-code "STOP_MARKET" (protection.py:1971-1984) | A caller bug could send a TRAILING or LIMIT algo type with closePosition | Allow-list the two types in the adapter |
| place_algo_protective | closePosition on a non-stop type | not an error: close-all is documented for SL and TP2 (1516) | 1516, 1547 | n/a | none |
| place_algo_protective | side enum; algo type CONDITIONAL; working type | present (enums) | 1566-1568, 1576 (`NewAlgoOrderWorkingTypeEnum`: MARK_PRICE/CONTRACT_PRICE); RestingEntry working type equals the snapshot's (protection.py:573-574) | n/a | none |
| place_algo_protective | symbol non-empty; position_side allow-list; client_algo_id format | absent (delegated) | 1567, 1570, 1578; id from `derive_algo_client_id` (order_ids.py:138) | Rejected by the exchange | Validate as `place_market_close` does |
| place_algo_protective | single attempt, no retry | present | 1558-1562 | n/a | none |
| change_margin_type (1879) | symbol non-empty; margin_type exactly ISOLATED or CROSSED | present | 1895-1898, enum 1907 | n/a | none |
| change_initial_leverage (1910) | symbol non-empty; leverage int (not bool), at least 1 | present | 1925-1930 | n/a | none |
| change_initial_leverage | upper cap | delegated, by design | docstring 1918-1922: the cap is symbol-specific; guard compares with the D035 cap and the bracket (D-02) | n/a | none |

Findings in order of weight: (1) `place_algo_protective` and `place_entry` accept SDK enum values wider than the documented set (algo type incl. TRAILING_STOP_MARKET and LIMIT; time in force incl. IOC, FOK, GTX, RPI); the callers hard-code the right values, so this is defense in depth, not a live bug. (2) Positivity of quantity, price and trigger is checked only for `place_market_close`; the other write calls rely on upstream quantization and the plan binding (manager.py:944-960). (3) `cancel_algo_order` ignores its `symbol`. (4) Symbol and client-id shape are unchecked for four of the seven functions; the exchange rejects them. No decision is invented; every recommendation is text only.

## Gate results

- `uv run ruff check`: All checks passed.
- `uv run ruff format --check`: 1029 files already formatted.
- `uv run mypy src`: Success, no issues in 291 source files.
- Union of the four task test sets (`-m "not docker" -n 4`): all passed (one xfail). Run once: `tests/test_live_restart_rehydrate.py tests/test_startup_recovery.py tests/test_live_start_sequence.py tests/test_live_replay_restart.py tests/test_demo_twin_s07_restart_cuts.py tests/test_phase24_gate.py tests/test_protection_liquidation.py tests/test_backup.py tests/test_backup_restore.py tests/test_backup_remote.py tests/test_backup_retention.py tests/test_backup_lock.py tests/test_backup_gate.py tests/test_live_scheduler.py tests/test_live_ast_guards.py tests/test_live_wiring_parts.py tests/test_live_wiring.py`.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS (no docs were edited).
- The full suite was not run (orchestrator's job). Not run: `*_pg.py` files (no `TEST_DATABASE_URL` use), docker-marked tests, `pytest -m demo`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test design] Task 2 tests script the liquidation check's own read instead of zeroing `fake.positions`**
- **Found during:** Task 2
- **Issue:** Setting the fake's position to 0 also makes its stop disappear and the plan goes FLAT, so the plan never reaches a second liquidation check (the old test passed for that reason, not because of the flag). The attach-take-profits step also reads positionRisk, so a plain read script was consumed by the wrong caller.
- **Fix:** `_PositionReads` scripts only the first positionRisk read of each step (the check's own); the fake position and stop stay open.
- **Files modified:** tests/test_protection_liquidation.py
- **Commit:** 6afe408e

**2. [Rule 1 - Test expectation] Task 1 "stays blocked" is asserted through SAFE_MODE, not `blocks_new_entries()`**
- **Found during:** Task 1
- **Issue:** After a partial restore the coordinator is restored, so `blocks_new_entries()` is False; the block is SAFE_MODE.
- **Fix:** assert `safe_mode.in_safe_mode` and `guard_new_entries(None).is_no_trade`; the outage test keeps the coordinator-level assertions.
- **Files modified:** tests/test_live_restart_rehydrate.py
- **Commit:** 53d5926b

### Process notes (not code deviations)
- The Task 1 reconcile-side code was written before the first test run (RED recorded afterwards, see Task 1).
- The Task 3 RED run omitted the four destructive path-overlap parametrizations on purpose (see Task 3).

## Deferred / out of scope

- `tests/test_phase20_gate.py::test_invariant_6_decisions_gained_no_row_and_d055_stays_open` fails on this tree: it pins the rows after D078 and now sees D108 and D109 (added by quick 261114-12e). Not caused by this plan and not touched; the file was not part of any task's verify command.
- `scripts/export_soak_evidence.py:848` full-environment spread (see Task 3).
- The partial-restore residual risk (a resting entry or position of an unrestored plan has no stop placed by the coordinator) is documented in report (b); closing it (for example cancelling the unrestorable resting entry) is an owner decision and not done here.

## Known Stubs

None.

## Threat Flags

None. New surface: one new log line (`live.restore.entry_unrestorable`: ids and class name only) and one scheduler log line (task name and bound); no endpoint, auth path or schema change.

## Self-Check: PASSED

- Commits 53d5926b, 6afe408e, 06dc8171, 8c1d3335 are ancestors of HEAD.
- Files named in the frontmatter exist; `src/adapters/binance_usdm.py` and `src/live/wiring.py` are unchanged against HEAD.
- `git status` shows no staged change to .gsd/, .planning/milestone.lock, .planning/config.json, .planning/STATE.md, .planning/state.json or .planning/REQUIREMENTS.md (they remain unstaged modifications from before this task).
