---
phase: 24-live-runtime-composition-demo
plan: 37
subsystem: live-composition
status: complete
tags: [start-order, stream-before-reconcile, plan-constraint-snapshot, reservation-release, release-sweep, owner-checklist, d094, d095, phase-24]
requirements-addressed: [EXEC-01, EXEC-02, EXEC-03, OPS-03]
requires: [24-26, 24-27, 24-27B, 24-29]
provides:
  - "src/live/startup.py: START_STEPS runs STREAM before RECONCILE (D094); STEP groups: STREAM and RECONCILE are group 8"
  - "src/live/wiring.py: _startup_reconcile_tick (marks first), LINK_SNAPSHOT_RECORDER, LINK_RESERVATION_RELEASE, TASK_RESERVATION_SWEEP, CompleteLiveWiring.releaser"
  - "src/execution/live_context.py: LivePlacementContext.snapshot_recorder (required); src/execution/manager.py calls it after the consume, before mark_sent (D095)"
  - "src/live/reservation_release.py: ReservationReleaser.sweep_once / release_refused, ExecutionService(on_refused=...)"
  - "src/persistence/risk_reservations.py: PgRiskReservationStore.list_unreleased"
  - "scripts/demo_rehearsal.py smoke: no startup /safemode_exit, no hand-made enable; steps reservation_released_on_close and drill_reservation_released"
affects: [24-30, 24-33, 25]
key-files:
  created:
    - src/live/reservation_release.py
    - tests/test_live_reservation_release.py
  modified:
    - src/live/startup.py
    - src/live/wiring.py
    - src/live/execution_service.py
    - src/live/risk_inputs.py
    - src/execution/live_context.py
    - src/execution/manager.py
    - src/persistence/risk_reservations.py
    - scripts/demo_rehearsal.py
    - docs/DECISIONS.md
    - docs/operations/RUNBOOK.md
    - tests/support/live_smoke_env.py
    - tests/support/live_store_set.py
    - tests/support/live_rig.py
    - tests/support/live_risk_rig.py
    - tests/test_live_demo_smoke.py
    - tests/test_live_start_sequence.py
    - tests/test_live_wiring.py
    - tests/test_execution_manager.py
    - tests/test_risk_reservations_pg.py
    - tests/test_phase20_gate.py
key-decisions:
  - "D094 (owner, 'theo đề xuất'): STREAM moves in front of RECONCILE. The supervisor's start returns once LIVE or halted, so the tick judges a live feed; the stream is still started only after RECOVERY, so the restored plans and the client-id index are complete before the first frame. A stream that raises or halts still continues in SAFE_MODE."
  - "The first tick of a start refreshes the marks of the tracked symbols first (refresh_marks never raises): a restart with a position would otherwise judge its mark price absent and park in STALE_FEED."
  - "D095 (owner): the VERIFIED snapshot (A8 margin type, leverage, equity) is recorded by a REQUIRED LivePlacementContext.snapshot_recorder, after the consume and before mark_sent. After the consume on purpose: a replayed CONFIRM never reaches the write, so the write-once row cannot meet a second, different snapshot. Phase 17-21 order otherwise unchanged; no ordering question arose."
  - "D095 (owner): a scheduler task releases unplaced reservations (release_reason_for_plan) and a CONFIRM refused before the consume releases at once when the refusal is final (release_reason_for_placement_refusal). SAFE_MODE and the other refusals are NOT final: the reservation stays counted until the plan expires (the mapping's own conservative rule)."
  - "F5 (Rule 2, not in the instruction, veto possible): the same sweep also releases a CONSUMED plan's reservation by its outcome: ENTRY_REJECTED, and POSITION_CLOSED / ENTRY_ENDED_NO_FILL read from the journal's PROTECTION_TRANSITION rows, after RESERVED to PLACED. Without it the executed plan's reservation stays RESERVED forever and the next entry (including the drill) is refused by the caps."
plan_head_before: dfa3517d91c172f575fb0cc5fbea6b47398999f6
plan_head_after: 6662a9dc7327c98ce849311ea5573fb08e9b55d7
commits: 2
actuals:
  tokens: 26000
  tasks: 4
  commits: 2
completed: 2026-11-01
---

# Phase 24 Plan 37: bridging fixes for the composition gaps F1, F3, F4 of plan 24-29 Summary

**PLAN COMPLETE.** The three composition gaps found by plan 24-29 are fixed and the fake Demo smoke now runs the whole D-33 sequence with no operator exit at start, no hand-made enable and no test-side gap fill. A fourth gap (F5) turned up while verifying F4 and is fixed in the same sweep; it is the one item to confirm or veto (see Open owner questions). Nothing was run against Binance or Telegram; no PostgreSQL, no `TEST_DATABASE_URL`, no `--execute`. A third commit adds this file.

## What was built

### F1 (D094): a clean start is enabled by the start sequence

- `START_STEPS` is now `... RECOVERY, STREAM, RECONCILE, CONFIRM_EXPIRY, ALERT_REQUEUE, BOT, SCHEDULER, HEALTH, ENABLE`. `STREAM` and `RECONCILE` are both group 8 of `START_STEP_GROUP`. D-08 of `24-CONTEXT.md` carries an amendment note; `docs/DECISIONS.md` has D094.
- D-08 fail-closed semantics are kept and tested: a stream that raises is degraded to SAFE_MODE `STARTUP_STREAM_FAILED`, the tick, the bot and the scheduler still run, nothing is enabled; a stream that halts is judged by the tick (`USER_DATA_STREAM_HALTED`). ENABLE stays the last step and runs only when nothing failed.
- The wiring binds `reconcile_tick` of the start ports to `_startup_reconcile_tick`: `refresh_marks` first, then the tick. Found by driving the fake restart: with a tracked plan the first tick judged the mark price absent (the scheduler's mark task had not run), so the restart landed in SAFE_MODE `STALE_FEED` even with the stream live.
- The smoke (`_bring_up`) no longer exits SAFE_MODE or enables by hand. A start that is not enabled stops the smoke at `demo_enable` / `restart_enable` and names the standing SAFE_MODE reason and the ENABLE row. The `startup_safe_mode_exit` step is gone from `_SMOKE_STEPS`.

### F3 (D095): the verified snapshot is durable before the entry is sent

- `LivePlacementContext.snapshot_recorder` is a REQUIRED callable (no `None` default: a context that forgot it would place entries a restart cannot rebuild). `execute_approved_plan` calls it once with the `verified_snapshot`, after `consume_and_record_entry_intent` returned consumed and before `mark_sent`. A `PersistenceError` (store down, `RowConflict`, `ParentRowMissing`) ends the placement as `RECONCILIATION_REQUIRED`: nothing sent, the INTENDED row unresolved, exactly like a failing `mark_sent`.
- `LiveRiskInputProducer(snapshot_recorder=...)` takes `stores.snapshots.record`; the wiring gate has a new link `plan_snapshot_recorder_in_the_write_ahead_path` (`producer._snapshot_recorder == stores.snapshots.record`) with a negative control.
- The persisted snapshot is now the COMPLETE one (A8 values included), which also closes hand-off 3 of plan 24-26: a restored plan no longer comes back with `margin_type`/`leverage`/`equity_used` unset.
- The TEST_ONLY snapshot gap fill and the `persist_snapshots` parameter of `build_fake_smoke_env` are removed. The old pin (`persist_snapshots=False` fails) is replaced by two meaningful tests: the smoke restart rehydrates with the snapshot the placement recorded, and a store that LOST the row (`drop_snapshots_before_restart=True`) still fails closed (SAFE_MODE `DB_FAILURE`).

### F4 (D095): reservations that will never be placed are released

- `src/live/reservation_release.py`: `ReservationReleaser`. `sweep_once(now)` is the body of the new scheduler task `reservation_release_sweep` (confirm-TTL cadence, no new number). `release_refused(approval_id, trade_plan_id, reason_code, now)` is the `on_refused` hook of `ExecutionService`, called after a producer `PlacementRefusal` and after a manager NO_TRADE.
- Plan path (no ENTRY intent row): `release_reason_for_plan`, so an approved plan whose expiry passed is released as PLAN_EXPIRED and EXPIRED / INVALIDATED / SUPERSEDED plans at once. Refusal path: `release_reason_for_placement_refusal`, PLACEMENT_REFUSED for the three final refusals; every other refusal (SAFE_MODE, a limit, a price) keeps the reservation counted until the sweep finds the plan expired.
- `PgRiskReservationStore.list_unreleased()` (REQUESTED, RESERVED, PLACED, OPEN). Wiring gate link `reservation_release_on_refusal_and_expiry` and the task name are pinned.
- The smoke gains `drill_reservation_released`: after the SAFE_MODE drill it waits for the drill plan to expire and shows that the sweep released its reservation with PLAN_EXPIRED.

### F5 (found while verifying F4; Rule 2)

`release_reason_for_entry_intent` and `release_reason_for_protection_state` had no caller either, and `mark_placed` / `mark_open` have none in `src/live`. So the reservation of any executed plan stays RESERVED for good, counted by the caps. The fake does not model the cap verdict (24-27B), which is why the smoke never saw it; against the real store the drill's second plan on BTCUSDT would be counted against the first plan's stale reservation and may hit `CLUSTER_CAP_REJECT` (the cluster cap is 0.005 of equity and one smoke trade is sized to a large share of it; whether it trips depends on the Demo equity, but the stale reservation is counted either way). The sweep therefore also handles a plan with an ENTRY intent row: REJECTED entry -> ENTRY_REJECTED; a `PROTECTION_TRANSITION` into FLAT or ENTRY_ENDED_NO_FILL in the journal (the D093 source, restart-safe, no coordinator coupling) -> POSITION_CLOSED / ENTRY_ENDED_NO_FILL, after `mark_placed` (the store allows those reasons only from PLACED or OPEN). SENT, UNKNOWN and ACKED entries with a live state, and the plan expiry of an executed plan, release nothing (tested). The smoke gains `reservation_released_on_close`.

## Deviations from Plan

There was no PLAN.md: this is an unplanned bridging plan from the orchestrator's instruction.

1. **[Rule 2] F5 added to the F4 sweep** (above). Owner may veto; D095 (3) records it. Risk note: the PLACED instant written by the sweep is later than the acknowledgement (22-REVIEW WR-06 says the safe direction for that instant is later), and the row is released in the same pass.
2. **[Rule 1] `_startup_reconcile_tick`** (marks first), found by driving the fake restart.
3. **[Scope] The SAFE_MODE drill is NOT moved back to the D-33 position** (between `reconcile_clean` and the restart). It is not possible: while the first position is open, a second request on BTCUSDT is refused at the card (`CONFLICT_WITH_OPEN_POSITION`, `ACTIVE_PLAN`, `PENDING_OR_APPROVED_APPROVAL`), which is the symbol rule and has nothing to do with the reservation, and the smoke trades one symbol. The drill stays after the close; its docstring says why. What F4 changed is that the drill no longer leaves a counted reservation behind (it ends with the proof that the sweep released it), so it no longer has to be last for that reason.
4. **[Process] One code commit instead of one per fix.** F1, F3 and F4 share `wiring.py`, `demo_rehearsal.py`, the smoke env and the tests, and interactive staging is not available; commit 1 is the whole code+tests change, commit 2 the docs, commit 3 this file.
5. **[Pins changed on purpose]** `tests/test_live_start_sequence.py` (`EXPECTED_CALLS` has `stream` before `reconcile`, labelled D094; two new tests: stream is up when the first tick judges the feed and sits after the recovery; a failing stream still runs the tick), `tests/test_live_wiring.py` (the pinned task set gains `reservation_release_sweep`; two negative controls), `tests/test_execution_manager.py` (the `LivePlacementContext` field set gains `snapshot_recorder`, required; helper passes a no-op), `tests/test_risk_reservations_pg.py` (method set gains `list_unreleased`; one PG test written, not run), `tests/test_phase20_gate.py` (the D-row list after D078 gains D094 and D095), `tests/test_live_demo_smoke.py` (the three 24-29 pin tests F1, F3, F4 are flipped as described). The Phase 22 gate invariants 13 and 14 and the AST guards (`tests/test_live_ast_guards.py`: `_place` still has no loop or retry, one `execute_approved_plan` call site) needed NO change and pass.
6. **[Test infra]** `InMemoryReservations` gained `release`, `list_unreleased`, `mark_open` (the double now follows `RELEASE_SOURCE_STATUSES`); `RigPlacementInputs` and the risk rig pass a recorder.
7. **[Docs]** `docs/DECISIONS.md` D094 and D095, one paragraph of `docs/operations/RUNBOOK.md` (start order, snapshot, release), the D-08 note in `24-CONTEXT.md`. STATE, ROADMAP, REQUIREMENTS and config were not touched.

## Owner checklist (the owner runs `--execute`; the assistant never does)

Changes against the 24-29 checklist: no start-up `/safemode_exit`, no restart `/safemode_exit`, and the run is expected to COMPLETE (the restart no longer fails). One longer wait at the end (the drill plan's expiry, about 15 minutes after its card).

Preparation, once:

```bash
git status --short
```

```bash
uv sync --frozen --extra dev
```

Stop every other process that uses the live bot token (one getUpdates consumer per token), the shadow/paper runtime on the same Demo account, and any other user-data stream on the Demo account (the listen key is an account singleton). Then set, in THIS shell session only (names only here, never write values into a file or chat): `LIVE_RUNTIME_MODE=DEMO`, `BINANCE_DEMO_API_KEY`, `BINANCE_DEMO_API_SECRET`, `TELEGRAM_LIVE_BOT_TOKEN`, `TELEGRAM_LIVE_AUTHORIZED_CHAT_ID`, `TELEGRAM_AUTHORIZED_USER_IDS`, `DATABASE_URL` (the Demo database, NOT a `_test` database). Do NOT set `BINANCE_LIVE_*` or `TELEGRAM_BOT_TOKEN`. Check the names without printing values:

```bash
uv run python -c "import os; print(sorted(k for k in os.environ if k.startswith(('BINANCE_', 'TELEGRAM_', 'LIVE_RUNTIME', 'DATABASE_URL'))))"
```

```bash
uv run alembic upgrade head
```

Dry run first (fakes, no network, writes a `DRYRUN` file labelled SYNTHETIC; it must end `outcome: COMPLETE` and list `demo_enable`, `reservation_released_on_close` and `drill_reservation_released` as PASSED):

```bash
uv run python -m scripts.demo_rehearsal
```

The Demo smoke. On the very first install of this host (no `logs/live/rest_gate_state.json`) use the first command, otherwise the second. Run from the repository root (the state directory is relative). Type exactly `DEMO SMOKE BTCUSDT` at the prompt:

```bash
uv run python -m scripts.demo_rehearsal --execute --initialize-gate-state
```

```bash
uv run python -m scripts.demo_rehearsal --execute
```

While it runs it prints `OPERATOR:` lines; do exactly what each says on the LIVE Demo bot chat, within the 300 s per wait:

1. Tap APPROVE on the card, then CONFIRM on the prompt that follows (one GTD LIMIT entry on BTCUSDT Demo). There is NO `/safemode_exit` before this: if the script stops at `demo_enable` the start was not clean; read the SAFE_MODE reason it prints.
2. Wait. The script waits for the fill on the stream, the stop, the TPs, reconcile.
3. After the restart there is again no exit. Tap APPROVE and CONFIRM on the FIRST card again (replays; they must place nothing).
4. The script closes the position by the operator close and waits for the sweep to release the reservation (`reservation_released_on_close`).
5. The drill: APPROVE on the new card, then CONFIRM (SAFE_MODE is on; it must be refused), then `/safemode_exit` and send the `/confirm <token>` line the bot answers with.
6. Wait about 15 minutes with the script running (the drill plan's expiry: 300 s approval timeout plus the 10 minute margin, counted from the drill card). It ends with `drill_reservation_released`; do not stop it.

If the script stops FAILED, open the Binance Demo UI and close any BTCUSDT position and cancel any order by hand (the script prints an `OPERATOR:` line saying so).

Afterwards, the evidence file is under `.planning/phases/24-live-runtime-composition-demo/evidence/` (`09-DEMO-REHEARSAL-EVIDENCE-smoke-<time>.json`). Check, by name, that `evidence_kind` is `DEMO_OBSERVED`, `details.order_ids` has the entry, stop and TP ids, `details.user_data_url_form`, `details.commission_rates`, `details.fill_pnl_sample`, `details.entry_price_raw`, `details.cancel_query_lag_observations` and `details.user_data_liveness`, that `details.start_sequences` shows STREAM before RECONCILE and `HEALTH=OK, ENABLE=OK` for BOTH starts (`start` and `restart`) with empty `safe_mode_reasons`, and that `attestation_map.composed_smoke` shows `OBSERVED` for each PASSED step.

Ping/pong silence measurement (the long read-only probe; run it separately, with the smoke finished and nothing else on the Demo account; type `DEMO SILENCE PROBE`):

```bash
uv run python -m scripts.user_data_silence_probe --minutes 45 --execute
```

## Open owner questions

1. **F5 (confirm or veto).** The sweep also releases the reservation of an executed plan by its outcome (ENTRY_REJECTED; POSITION_CLOSED or ENTRY_ENDED_NO_FILL read from the journal, through PLACED). It was not in the instruction; without it the second trade on a cluster is refused for good. Recommendation: keep it. The alternative, if you prefer the lifecycle written the way the 21-DEFERRED row 26 describes (`mark_placed` before the entry POST, `mark_open` at the first fill, released by the coordinator), is a change in the Phase 19/20 write-ahead and protection path and needs its own plan.
2. **First contact with the real store.** `PgRiskReservationStore.list_unreleased` and its test, and the real `mark_placed` then `release(POSITION_CLOSED)` pair, are exercised only against the in-memory double here (the 21-12 PG tests cover `release` from PLACED, WR-10). The owner run is their first PostgreSQL contact; the new PG test `test_list_unreleased_reads_every_status_but_released_for_the_release_sweep` is written and was not run.

## Verification

- `uv run pytest -m "not docker" -n 4` over `tests/test_live_*.py`, `test_phase*_gate.py`, `test_demo_rehearsal*.py`, `test_execution_*.py`, `test_no_unratified_defaults.py`, `test_agents_md.py`, `test_domain_no_float.py`, `test_confirm*.py`, `test_approval*.py`, `test_startup_recovery.py`, `test_intent_recovery*.py`, `test_paper_shadow*.py`, `test_risk_reservation*.py`, `test_restorable_entries_pg.py`, `test_manual_controls.py`, `test_modeled_costs_none_guard.py`, `test_phase21_composition.py`, `test_doc*.py`, `test_reconcile*.py`, `test_decision*.py`: all pass except one pre-existing failure, `tests/test_execution_manager.py::test_the_committed_not_configured_limits_file_refuses_every_live_placement` (it reads only `config/execution/execution-limits-v1.toml`, which this plan does not touch, and asserts the file still has unset keys although the committed file has been complete since D089/D091; out of scope, logged here, not fixed).
- New and changed counts: `tests/test_live_reservation_release.py` 31, `tests/test_live_demo_smoke.py` 16, `tests/test_live_start_sequence.py` 51, `tests/test_live_wiring.py` 41.
- `uv run mypy src` (291 files), `uv run ruff check`, `uv run ruff format --check`, `uv lock --check`, `git diff --exit-code -- pyproject.toml uv.lock`, `uv run python scripts/verify_decision_alignment.py all`: clean.
- Not run: the full suite, any `_pg` test (they skip without `TEST_DATABASE_URL`, which was never set), the executed smoke. Unproven against the real systems: that the real Demo stream reaches LIVE inside the supervisor's own start (the fake puts the supervisor in LIVE by hand), the first real `refresh_marks` before the first tick, and the PostgreSQL release path above.

## Known Stubs

None. The TEST_ONLY values of the fake env are unchanged except that the snapshot gap fill is gone.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: write-path | src/execution/manager.py | One new store write in the placement path (the plan constraint snapshot). Fail closed: a failure sends nothing. Write-once and hash-verified by the store; placed after the consume so a replay cannot conflict with it. |
| threat_flag: risk-accounting | src/live/reservation_release.py | New writes to `risk_reservations` (release, and RESERVED to PLACED before a closed-position release). Mitigated: a row whose ENTRY intent exists is never released by the plan expiry or a refusal; SENT / UNKNOWN / ACKED entries with a live state stay counted; the store enforces `RELEASE_SOURCE_STATUSES`; a failed read keeps the row counted and the task unhealthy. |

## Self-Check: PASSED

- FOUND: src/live/reservation_release.py, tests/test_live_reservation_release.py, scripts/demo_rehearsal.py, src/live/startup.py
- FOUND commits 8b87645a, 6662a9dc (ancestors of HEAD)
