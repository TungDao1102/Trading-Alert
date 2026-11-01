---
phase: 24-live-runtime-composition-demo
plan: 29
subsystem: demo-smoke
status: partial
tags: [demo-smoke, composed-process, d33, d016, d022, d023, d034, evidence, owner-checklist, phase-24]
requirements-addressed: [EXEC-01, EXEC-02, EXEC-03, OPS-03]
requires: [24-27, 24-27B]
provides:
  - "scripts/demo_rehearsal.py: scenario smoke (default) = the D-33 sequence over build_wiring + run_start_sequence; SmokeEnv, ConsoleOwner, demo_guarded_sdk_factory, admit_smoke_environment, run_composed_smoke, build_smoke_attestation"
  - "tests/support/live_smoke_env.py: build_fake_smoke_env (the composed process on the Binance-semantics fake, fake presses, SYNTHETIC)"
  - "tests/test_live_demo_smoke.py: 13 tests; tests/test_demo_rehearsal_safety.py and _flow.py rewritten onto the composed smoke"
  - "src/live/runtime.default_assemble(sdk_factory=...), DemoSmokeSignalSource.peek()"
affects: [24-30, 24-33, 25]
key-files:
  created:
    - tests/support/live_smoke_env.py
    - tests/test_live_demo_smoke.py
  modified:
    - scripts/demo_rehearsal.py
    - src/live/wiring.py
    - src/live/runtime.py
    - src/live/signal_source.py
    - tests/support/live_composed_rig.py
    - tests/shadow_fakes.py
    - tests/test_demo_rehearsal_flow.py
    - tests/test_demo_rehearsal_safety.py
key-decisions:
  - "The smoke OBSERVES the composed process: build_wiring (SDK factory re-checks the Demo host), run_start_sequence, then bounded waits on the stores and the coordinator view. It never steps the coordinator, never calls a placement function. The Demo injector is the process's own /demo_signal handler (DemoSignalCommand.handle) called as the authorized owner."
  - "The owner presses APPROVE/CONFIRM and types /safemode_exit + /confirm on the live Demo bot (ConsoleOwner prints one OPERATOR line per action); the same flow runs in tests with FakeOwner calling the runner's own handlers."
  - "Fake mode is the default run (no --execute): SYNTHETIC on every step, attestation SYNTHETIC_NOT_OBSERVED, exchange_orders empty. Only the owner's --execute run can produce OBSERVED."
  - "The SAFE_MODE drill runs LAST (deviation from the D-33 order): a second request is refused at the card while a position, plan or open approval exists on the symbol, and a refused CONFIRM leaves its reservation counted (F4)."
  - "Remaining src change kept minimal: wiring.py demo_degraded_allowed=True in DEMO (F2); default_assemble gets an optional sdk_factory; DemoSmokeSignalSource.peek()."
plan_head_before: 3360e659f6e6b026fa7d3a6a68dc9d2e742ebb45
plan_head_after: eb53173885ddc64697028049767ed542bee6ede0
commits: 5
actuals:
  tokens: 190000
  tasks: 3
  commits: 5
completed: 2026-11-01
---

# Phase 24 Plan 29: the Demo smoke over the composed process Summary

**PLAN PARTIAL.** The script, its fake-mode end-to-end test, the evidence fields and the safety guards are done and tested (13 tests in `tests/test_live_demo_smoke.py`, the rewritten rehearsal flow and safety suites, the wave-7 wiring suites). Four composition findings (F1 to F4 below) surfaced while driving the REAL start sequence on the fakes; two are worked around in the smoke, one is fixed (F2), and F3 will stop the owner's Demo run at the restart step. Nothing here was run against Binance or Telegram; every Demo step stays NOT_OBSERVED.

## What was built

### Task 1 (tracer): the whole D-33 sequence on fakes through the composed process

`scripts/demo_rehearsal.py` scenario `smoke` (now the default; `taps` is kept, `far` and `fill` are gone):

1. `start`: `default_assemble(..., sdk_factory=demo_guarded_sdk_factory)` then `run_start_sequence`; `check_wiring` must be empty.
2. `startup_safe_mode_exit` and `demo_enable` (F1, below).
3. `signal` (the process's `/demo_signal` handler, called as the owner), `card`, `approve` (owner press), `confirm_entry` (owner press; ONE GTD LIMIT, no entry-time stop, D079), `stream_fill`, `stop_confirmed` (REST), `tp_legs` (TP1/TP2, D-21), `reconcile_clean`.
4. `restart_rehydrate` (first process shut down in order, a second wiring over the same stores, same start sequence), `replays_place_nothing` (the first card's APPROVE and CONFIRM pressed again), `close_cleanup` (operator close), `account_clean`.
5. `safe_mode_drill` (enter, the owner's CONFIRM is refused, operator exit through `/safemode_exit` + `/confirm`).

Every wait is bounded (`--approval-timeout-seconds`, default 300 s, polled every 2 s). The fake run (`tests/support/live_smoke_env.py`) builds the real `build_wiring` composition (rig of 24-27B) and replaces only: the database (in-memory stores), the exchange orders/prices (Binance-semantics fake), the websocket (the supervisor is put in LIVE by hand), the PTB application, the clock, and the owner's presses. It runs the real start sequence with three port substitutions (alembic revision, stream start, scheduler start).

### Task 2: the evidence the owner run must capture, and nothing secret

`details` of the evidence file: `order_ids` (per step: `demo_order_ids`, `client_order_ids`, `algo_client_ids`), `user_data_url_form` (configured stream base, documented path form `/private/ws/<LISTEN_KEY_REDACTED>`, the key replaced by a fixed marker; the SDK owns the transport, D-16, so the form is documented-not-observed), `commission_rates` per tracked symbol (D-22), `fill_pnl_sample` (`realized_pnl` and `commission` side by side from `userTrades`, note "evidence only, D086": `LIVE_NET_PNL_SEMANTICS_VERIFIED` stays False), `entry_price_raw` (the value as the adapter hands it over after the string/Decimal conversion of 24-34; the raw SDK float is not reachable past the boundary), `cancel_query_lag_observations` (after the close, four polls 0.5 s apart per leg of `query_algo_order_by_client`: found/status), `user_data_liveness` (the supervisor's own last event/ping/pong times, sampled; reuse of the process's supervisor, no new probe), `start_sequences`, `entry_acked`, `operator_instructions`, `evidence_kind` (`SYNTHETIC` or `DEMO_OBSERVED`). `attestation_map.composed_smoke` is OBSERVED only for a PASSED step of an executed run, SYNTHETIC_NOT_OBSERVED for a fake one. Seeded sentinels (API key, secret, bot token) never reach the file or stdout (test).

### Task 3: guards and the old tests

- `demo_guarded_sdk_factory` is the SDK factory handed to `build_wiring`: DEMO only (LIVE and TESTNET never reach the SDK builder), and the host is re-read from the built client (`DemoHostViolation` otherwise).
- `admit_smoke_environment` = the live process's own `parse_live_environment` plus "mode must be DEMO": LIVE mode, `BINANCE_LIVE_*`, the shadow bot's token, a missing variable or a `NOT_CONFIGURED` limit refuse before any network call, naming variables or keys only.
- `--execute` needs a terminal and the phrase `DEMO SMOKE BTCUSDT`, before admission.
- `RehearsalAlertSink` and every construction of the coordinator/closer in the script are gone (a source test asserts it); `git grep -n "RehearsalAlertSink(" -- scripts src` prints nothing; `_drive_protection` no longer exists.
- `run_health_checks` in the taps preflight now passes `HealthRuntimeMode.DEMO, demo_degraded_allowed=True` (the 24-22 note): the legacy no-mode path has no caller left in `scripts`. It stays in `src/ops/health.py` (outside this plan's files; `tests/test_execution_health.py` and others still call it).

## Findings from driving the real start sequence (the reason this is PARTIAL)

| # | Finding | Effect on the owner run | Status |
|---|---|---|---|
| F1 | D-08 step 8 (reconcile tick) runs before step 9 (stream start), so the first tick sees the user-data feed silent and enters SAFE_MODE `STALE_FEED`; HEALTH and ENABLE are then skipped (`BLOCKED_SAFE_MODE`). Every start, including a restart, lands DISABLED in SAFE_MODE. | Entries cannot open until the operator exits SAFE_MODE AND something enables entries. There is no `/enable` command. | WORKED AROUND in the smoke: after the stream is LIVE the owner exits (`/safemode_exit`), then the smoke calls `enable_demo` itself with a fresh health verdict (the same function `_enable` uses). Pinned by a test that flips if the order changes. **Owner decision needed (below).** |
| F2 | `LiveHealthProducer(demo_degraded_allowed=False)` in `wiring.py`, while `last_closed_candle_time` is DEGRADED by design ("no candle feed"). In DEMO the verdict could never be OK, so no DEMO start could ever enable entries (`HEALTH_NOT_OK failing=[last_closed_candle_time]`). | Blocks criterion 2 outright. | FIXED (Rule 1): `demo_degraded_allowed=self.config.mode is Environment.DEMO` (D056 2, explicit Demo mode; LIVE can never carry it). Test pins it. |
| F3 | Nothing in `src` records the plan constraint snapshot (`PgPlanConstraintSnapshotStore.record` has no caller). After a restart, `restored_plans_builder` raises `RestoreSourceMissing` for any live ENTRY row: recovery fails (`COORDINATOR_RESTORED`, SAFE_MODE `DB_FAILURE`), the coordinator stays unrestored. | The owner run will fail at `restart_rehydrate` with the position OPEN but PROTECTED (stop and TPs live on Demo). A real restart with a live position would also leave it unmanaged by the process. | NOT FIXED (architectural: the snapshot is write-once and the verified one exists only after the manager's margin guard, so the writer belongs in the Phase 19/20 write-ahead path; Rule 4). The fake env writes the coordinator's own snapshot before the restart as a labelled TEST_ONLY gap fill; with `persist_snapshots=False` a test pins the real failure. |
| F4 | `release_reason_for_plan` / `release_reason_for_placement_refusal` have no caller in `src`: an approved plan whose placement is refused (SAFE_MODE, any non-final refusal) keeps its reservation counted, and the plan stays APPROVED until expiry, so the next entry is refused (`CLUSTER_CAP_REJECT`; and the card of any request on the symbol is refused while an approval is open). | Why the SAFE_MODE drill runs last. In operation a refused CONFIRM blocks the symbol until a restart/expiry handled by hand. | NOT FIXED (needs the plan-expiry sweep task, a new scheduler task and a store release path; Rule 4). Pinned by a test. |

## Deviations from Plan

1. **[Rule 1] F2 fixed in `src/live/wiring.py`** (one line, outside the plan's file list): without it the smoke cannot enable entries in any DEMO start.
2. **[Rule 3] Small src additions outside the file list:** `default_assemble(sdk_factory=None)` (the Demo-host guard must wrap the factory the wiring uses; default unchanged), `DemoSmokeSignalSource.peek()` (read the queued request's ids without taking it).
3. **[Order] The SAFE_MODE drill is last, not between reconcile and restart** (F4 above). The drill still enters SAFE_MODE, shows a CONFIRM refused (plan APPROVED, no intent row, no open order), and exits through `/safemode_exit`; it then waits for nothing: the run ends.
4. **[Scope] `far` and `fill` scenarios, `build_live_context`, `RehearsalAlertSink`, the margin-guard plumbing (`margin_guard`, `margin_guard_factory`, `MARGIN_GUARD_*`), `execution_limits`/`drift_limits`/`snapshot_live_inputs` of `RunContext`/`main`, `run_order_scenario`, `_fill_flow`, `_drive_protection` and friends were REMOVED.** The composed process builds its own margin guard, coordinator, closer and alert sink. `taps` is kept (no order, no coordinator).
5. **[Tests removed with reason]** from `tests/test_demo_rehearsal_flow.py`, all pinning the hand-stepped path whose code is gone (their behaviours live in the composed tracers `tests/test_live_composed_tracer.py`, `tests/test_live_stream_to_protection.py`, `tests/test_live_wiring.py`): `test_order_scenarios_reach_the_entry_against_the_fakes_own_mark`, `test_a_mark_past_the_zone_cushion_is_still_refused`, `test_a_far_mark_above_the_zone_is_the_favorable_side_and_reaches_the_entry`, `test_a_last_price_below_the_zone_is_refused_with_the_mark_inside`, `test_constraint_drift_between_plan_and_execution_aborts`, `test_far_scenario_sequence_and_cleanup`, `test_far_scenario_entry_no_longer_new_leaves_the_position_for_the_operator`, the four `test_fill_scenario_*`, `test_the_dry_run_fill_scenario_attaches_nothing`, `test_enablement_is_in_process_only`, `test_build_live_context_*` (3), `test_a_bar_close_that_cannot_be_read_is_none_not_a_guess`, `test_the_alert_sink_records_the_alert_and_an_operator_instruction`, `test_committed_not_configured_limits_abort_before_any_mutation`, `test_committed_limits_end_the_main_run_as_aborted_no_order`, `test_one_unset_limit_names_only_that_key`, `test_the_dry_run_far_scenario_reads_the_mark_price_and_still_sends_nothing`, the margin-guard group (`test_a_refusing_margin_guard_*`, `test_an_executed_run_without_a_margin_guard_*`, `test_the_main_run_without_a_margin_guard_*`, `test_a_real_guard_over_the_guarded_adapter_*` (2), `test_build_context_*` (3), `test_main_in_dry_run_builds_the_guard_once_*`, `test_a_scripted_margin_guard_is_still_accepted_directly`) and the helpers behind them; `test_skp_tap_against_the_approve_approval_is_rejected`, `test_exchange_failure_is_recorded_honestly`, `test_sdk_error_code_and_text_are_recorded_but_other_errors_stay_type_only` (a place_entry through the guarded adapter no longer exists in the script). Rewritten: the health/taps/derivation tests now use `scenario="taps"`; `test_evidence_is_deterministic` asserts the taps evidence; the key-14 helper `_committed_limits_with_key_14_unset` is KEPT and used by `test_committed_limits_are_complete_so_a_key_14_clear_is_what_refuses_the_smoke` (the committed file is complete since D091: the helper's only unset key is `stale_feed.max_user_data_silence_ms`; a limits file with that key cleared refuses the smoke naming it).
   In `tests/test_demo_rehearsal_safety.py` the `far` scenario argv became `taps`, the execute-gate test uses `smoke` and the phrase `DEMO SMOKE BTCUSDT`, and eight tests of the guards were added.
6. **[Test infra]** `tests/shadow_fakes.py InMemoryShadowStores` gained `get_signal`/`get_trade_plan` (the open-approvals reader of the sender calls them; its absence was a fake gap, not a production one); `tests/support/live_composed_rig.py` gained a startable fake application and a restart over the same stores, clock and exchange.
7. **[Not done]** the RUNBOOK was not touched (the plan does not list it); the owner checklist is below. The legacy no-mode path of `run_health_checks` stays in `src/ops/health.py`.

## Owner checklist (the owner runs `--execute`; the assistant never does)

Read first: with F3 open, the executed run is expected to stop FAILED at `restart_rehydrate` with an open, protected position on Demo. Run it anyway only if you accept that, or fix F3 first (decision below). Everything up to `reconcile_clean` is valid Demo evidence even then.

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

Dry run first (fakes, no network, writes a `DRYRUN` file labelled SYNTHETIC; it must end `outcome: COMPLETE`):

```bash
uv run python -m scripts.demo_rehearsal
```

The Demo smoke. On the very first install of this host (no `logs/live/rest_gate_state.json`) add `--initialize-gate-state`; otherwise leave it out. Run from the repository root (the state directory is relative). Type exactly `DEMO SMOKE BTCUSDT` at the prompt:

```bash
uv run python -m scripts.demo_rehearsal --execute --initialize-gate-state
```

```bash
uv run python -m scripts.demo_rehearsal --execute
```

While it runs it prints `OPERATOR:` lines; do exactly what each says on the LIVE Demo bot chat, within the 300 s per wait:

1. `/safemode_exit`, then send the `/confirm <token>` line the bot answers with (start-up, because of F1).
2. Tap APPROVE on the card, then CONFIRM on the prompt that follows (one GTD LIMIT entry on BTCUSDT Demo).
3. Wait. The script waits for the fill on the stream, the stop, the TPs, reconcile.
4. After the restart: `/safemode_exit` and `/confirm <token>` again (F1), then tap APPROVE and CONFIRM on the FIRST card again (replays; they must place nothing).
5. The drill: APPROVE on the new card, then CONFIRM (SAFE_MODE is on; it must be refused), then `/safemode_exit` and `/confirm <token>`.

If the script stops FAILED, open the Binance Demo UI and close any BTCUSDT position and cancel any order by hand (the script prints an `OPERATOR:` line saying so).

Afterwards, the evidence file is under `.planning/phases/24-live-runtime-composition-demo/evidence/` (`09-DEMO-REHEARSAL-EVIDENCE-smoke-<time>.json`). Check, by name, that `evidence_kind` is `DEMO_OBSERVED`, `details.order_ids` has the entry, stop and TP ids, `details.user_data_url_form`, `details.commission_rates`, `details.fill_pnl_sample`, `details.entry_price_raw`, `details.cancel_query_lag_observations` and `details.user_data_liveness` (the observed ping/pong times; the supervisor's own samples), and that `attestation_map.composed_smoke` shows `OBSERVED` for each PASSED step.

Ping/pong silence measurement (the long read-only probe that already exists; run it separately, with the smoke finished and nothing else on the Demo account; type `DEMO SILENCE PROBE`):

```bash
uv run python -m scripts.user_data_silence_probe --minutes 45 --execute
```

## Open owner questions

1. **F1 order.** Should the start sequence start the stream before the first reconcile tick (or the first tick tolerate a not-yet-started stream), so a clean start is not parked in SAFE_MODE? Today every start, including a crash restart, needs an operator exit plus an enable that has no command. Recommendation: a plan that moves STREAM before RECONCILE and keeps SAFE_MODE for a real divergence only; until then the smoke's workaround stands.
2. **F3 snapshot writer.** Approve a plan that records the verified plan constraint snapshot (write-once) in the write-ahead path before the entry is acknowledged, so a restart can rehydrate. Without it the owner run cannot complete D-33's restart step, and a real restart with a live position fails closed.
3. **F4 reservation release.** Approve the plan-expiry sweep (a scheduler task calling `release_reason_for_plan` and `release_reason_for_placement_refusal`) so a refused CONFIRM does not block the symbol until a restart.
4. **Executed run now or after F3?** Run plan 24-33 on the current code (stops at the restart step; evidence up to `reconcile_clean` is valid), or wait for F3. Recommendation: wait for F3, then run once.

## Verification

- `uv run pytest -m "not docker"`: `tests/test_live_demo_smoke.py` (13), `tests/test_demo_rehearsal_safety.py`, `tests/test_demo_rehearsal_flow.py`, `tests/test_live_wiring.py` and the wave-7 live suites (`test_live_*`, `test_paper_shadow*`, `test_confirm*`, `test_approval*`, phase 18/19/20/22 gates, `test_no_unratified_defaults`, `test_agents_md`, `test_domain_no_float`): pass. No PostgreSQL, no `TEST_DATABASE_URL`, no network, no `--execute`. The smoke tests were repeated under `-n 4` load to rule out timing flakes (the fake env drains the placement task at the virtual instant of the press).
- `uv run ruff check`, `uv run ruff format --check` on every touched file, `uv run mypy src` (290 files), `uv lock --check`, `git diff --exit-code -- pyproject.toml uv.lock`, `scripts/verify_decision_alignment.py all`: clean.
- Not run: the full suite, any `_pg` test, the executed smoke. The real-environment path (`_real_smoke_env_factory`, `ConsoleOwner`, `demo_guarded_sdk_factory`, the admission) is covered with seams only; its first contact with Binance and Telegram is the owner's run. Unproven there: that `/safemode_exit` is accepted right after start on real feeds (readiness rows), the real fill timing for the marketable GTD LIMIT, and the real liquidation price the B6 check reads on Demo (the fake supplies a TEST_ONLY one).

## Known Stubs

None that reach an order path. The fake env's TEST_ONLY values (liquidation price, snapshot gap fill, scripted `userTrades` row, prices) are in `tests/support/live_smoke_env.py` and labelled.

## Threat Flags

None new. T-24-91 (mainnet): the SDK factory is DEMO-only and re-reads the host, LIVE credentials/mode refuse (tests). T-24-92 (secrets): sentinels absent from file and stdout; the listen key is a fixed marker. T-24-93 (fake reported as Demo): SYNTHETIC labels, `SYNTHETIC_NOT_OBSERVED`, empty `exchange_orders` in a dry run. T-24-SC: `pyproject.toml` and `uv.lock` unchanged.

## Self-Check: PASSED

- FOUND: scripts/demo_rehearsal.py, tests/support/live_smoke_env.py, tests/test_live_demo_smoke.py, tests/test_demo_rehearsal_flow.py, tests/test_demo_rehearsal_safety.py
- FOUND commits 9dc542c3, 5cf8e00b, d78721c7, 8485ad95, eb531738 (ancestors of HEAD)
