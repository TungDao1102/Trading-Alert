---
phase: 16-paper-runtime-composition
plan: 26
subsystem: paper-runtime / live loop composition
tags: [paper-runtime, asyncio, bounded-queue, tick-stats, exchange-info, clock-skew, healthcheck, q-d, fail-closed]

requires:
  - phase: 16-paper-runtime-composition
    provides: "16-22 entrypoint, start gate, ExitCode table, RuntimeConfig; 16-24 BarPipeline (held bars, dropped bars, history-only rule); 16-08 PaperSupervisor sinks; 16-16 RuntimeStatePort; 16-03 credential-free public adapter; 16-01 PaperWsAdapter"
provides:
  - "src/paper/runtime.py: run_admitted, LoopWiring, RuntimeFailClosed, --healthcheck, clock_skew_ms in RUNTIME_START"
  - "src/paper/market_inputs.py: ConstraintProvider, refresh_forever, make_context_factory, RiskInputsProvider (port only), measure_clock_skew, make_sibling_fetcher, PublicDataLike"
  - "src/paper/runtime_config.py: keys nothing reads are refused (no unused threshold)"
  - "config/paper/README.md: healthcheck and unknown-key rule, still no value"
affects: [16-29 restart and warm-up, 16-31 SHADOW wiring (binds the risk-inputs port), 16-27 O-07 table, 16-32 compose, 16-34 config file, 16-40 16-43 16-44 real runtime evidence]

actuals:
  tokens: 21335
  tasks: 3
  commits: 6
plan_head_before: b03a280c46a98e52ca42c3480e1f210a41d70f28
plan_head_after: 13e5a1a810048a698ccfb7e2740ff791e867f69b
commits: 6

tech-stack:
  added: []
  patterns:
    - "SDK callbacks only call queue.put_nowait or schedule an off-loop write; one consumer task drains the queue and runs the pipeline in asyncio.to_thread through the one synchronous state port"
    - "Fail closed without RUNTIME_STOP: the loop stores the first failure, unsubscribes and closes the adapter, then main exits 7 so the restart reads the open START as a crash"
    - "Point-in-time constraint snapshots: a bar is judged with the latest exchangeInfo snapshot observed at or before its close; age and negative age become the existing STALE_CONSTRAINTS verdict"
    - "Test and composition seams as one frozen LoopWiring (production binds only the risk-inputs port)"

key-files:
  created:
    - src/paper/market_inputs.py
    - tests/test_paper_runtime_loop.py
    - tests/test_paper_market_inputs.py
  modified:
    - src/paper/runtime.py
    - src/paper/runtime_config.py
    - config/paper/README.md

key-decisions:
  - "The WS callbacks are four methods named _sink_* that only enqueue (put_nowait) or schedule a record task; an AST test proves none of them touches the state port, to_thread or the store"
  - "A full queue, a failed record write, a pipeline error or a stop-waiter error stops the loop closed: unsubscribe, close, no RUNTIME_STOP, exit 7 (ExitCode.FAIL_CLOSED_RUNTIME, restartable)"
  - "PAPER_TICK_STATS is written once per consumer batch; the duration is two readings of the injected monotonic function around the BarPipeline.handle call and reaches only _tick_stats_record (AST test); the stored value is clamped at zero"
  - "Constraint snapshots are selected point-in-time (latest observed at or before the bar close, otherwise the earliest retained, which is future-dated and so STALE): a snapshot refreshed one second after a close must not make every bar stale"
  - "A refresh is stamped with the injected clock read before the request, is all-or-nothing across the configured symbols, and a failed periodic refresh keeps the old snapshot (it ages into STALE_CONSTRAINTS)"
  - "The first exchangeInfo refresh and the clock-skew request must succeed, otherwise the process exits 7 (fail closed); the skew has no threshold (D-35)"
  - "Q-D (history-only) is honoured in configuration by refusing every key nothing reads, not by naming the key, because plan 16-24 has a test that greps src/ for that key name"
  - "Healthy = the latest RUNTIME_START is open and the last processed closed bar is no older than healthcheck_max_bar_age_seconds; a start with no bar yet is healthy for one maximum age; every start-gate refusal condition and an empty allowlist report unhealthy"
  - "Without a bound risk-inputs port (and without the test seams) main refuses with CONFIG_NOT_RATIFIED before RUNTIME_START; the port has no default implementation anywhere in src/paper (AST test)"

requirements-completed: []

coverage:
  - id: D1
    description: "A closed kline travels SDK message -> supervisor sink -> bounded queue -> consumer -> BarPipeline (to_thread) -> PAPER_BAR_PROCESSED, forming updates never enter, and a requested stop unsubscribes every stream, closes the adapter and returns 0 with RUNTIME_STOP"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_loop.py#test_a_closed_kline_reaches_a_heartbeat_record_and_the_stop_is_clean"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_loop.py#test_forming_updates_never_reach_the_queue_or_the_journal"
        status: pass
    human_judgment: false
  - id: D2
    description: "A blocking store never delays the receive loop and the queue drains afterwards; callbacks never touch the store (AST); supervisor gap and connection sinks become PAPER_GAP, WS_DISCONNECT and WS_RECONNECT records; held bars are re-submitted at their deadline"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_loop.py#test_a_blocking_store_never_delays_the_receive_loop_and_the_queue_drains"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_loop.py#test_supervisor_gap_and_connection_sinks_become_journal_records"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_loop.py#test_held_bars_are_resubmitted_when_the_clock_reaches_their_deadline"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_loop.py#test_no_sdk_callback_touches_the_state_port_directly"
        status: pass
    human_judgment: false
  - id: D3
    description: "A full queue exits 7 with a logged reason, leaves the START open and still closes the adapter; one PAPER_TICK_STATS per batch carries counts, drops by reason, injected-clock tick time, monotonic duration and queue depth, and the monotonic value feeds nothing else (AST)"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_loop.py#test_a_full_queue_stops_the_process_with_the_fail_closed_exit_code"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_loop.py#test_every_batch_writes_one_tick_stats_record_with_measured_duration"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_loop.py#test_the_monotonic_reading_feeds_only_the_tick_stats_record"
        status: pass
    human_judgment: false
  - id: D4
    description: "Exchange constraints only from public exchangeInfo, refreshed at the ratified period, ttl from the ratified configuration, STALE_CONSTRAINTS through evaluate_risk when old or future-dated, no fallback snapshot; equity and risk rate from [account]; positions and daily loss only through the required port; skew measured once and recorded"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_market_inputs.py#test_a_failed_refresh_keeps_the_old_snapshot_and_it_goes_stale"
        status: pass
      - kind: unit
        ref: "tests/test_paper_market_inputs.py#test_a_bar_is_judged_with_the_snapshot_observed_at_or_before_its_close"
        status: pass
      - kind: unit
        ref: "tests/test_paper_market_inputs.py#test_a_production_shaped_run_refreshes_exchange_info_at_the_configured_period"
        status: pass
      - kind: unit
        ref: "tests/test_paper_market_inputs.py#test_omitting_the_risk_inputs_port_is_a_type_error"
        status: pass
      - kind: unit
        ref: "tests/test_paper_market_inputs.py#test_src_has_no_default_implementation_of_the_risk_inputs_port"
        status: pass
      - kind: unit
        ref: "tests/test_paper_market_inputs.py#test_runtime_start_records_the_measured_skew_and_reads_server_time_once"
        status: pass
      - kind: unit
        ref: "tests/test_paper_market_inputs.py#test_time_is_read_only_through_the_one_clock_and_the_one_monotonic_function"
        status: pass
    human_judgment: false
  - id: D5
    description: "--healthcheck is healthy only while the last processed closed bar is younger than the ratified maximum age; a start with no bar, a stopped process, a held refusal, an empty allowlist and an unratified configuration are unhealthy; no environment value is printed; Q-D history-only leaves no age key and refuses any key nothing reads"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_loop.py#test_healthy_while_the_last_processed_bar_is_younger_than_the_maximum_age"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_loop.py#test_a_held_refusal_is_never_reported_healthy"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_loop.py#test_the_healthcheck_never_prints_an_environment_value"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_loop.py#test_q_d_option_history_only_means_no_age_key_anywhere"
        status: pass
    human_judgment: false
  - id: D6
    description: "The composed loop against the real Binance feed, a real PostgreSQL store and a real stop signal (not exercised here; fake-level green never closes PAPER-01, SC9)"
    requirement: PAPER-01
    human_judgment: true
    rationale: "Real runtime evidence comes from the trial soak (plans 16-40, 16-43, 16-44); every collaborator in these tests is a fake"

duration: about 15 minutes of work in one session
completed: 2026-10-10
status: complete
---

# Phase 16 Plan 26: Live loop composition Summary

**`run_admitted` now composes the credential-free public adapter, `PaperWsAdapter`, `PaperSupervisor`, one bounded asyncio queue, one consumer task and the `BarPipeline` into one process: callbacks only enqueue, every write and the whole tick run off the event loop, a full queue or a failed write fails closed with exit 7, every batch leaves a `PAPER_TICK_STATS` record, the start records the clock skew against Binance server time, and `--healthcheck` is healthy only while closed bars keep being processed.**

## Accomplishments

- **Tracer (Task 1):** an SDK-shaped fake handle message becomes a `PAPER_BAR_PROCESSED` record through supervisor sink, `queue.put_nowait`, the consumer and `BarPipeline.handle` in `asyncio.to_thread`; the stop unsubscribes every stream, closes the adapter, returns 0 and `main` records `RUNTIME_STOP`. Supervisor gaps and connection events are written as records by scheduled off-loop tasks. Held 1h bars are re-submitted when the injected clock reaches their deadline. A blocking store test proves delivering further messages never waits for the store (research P10).
- **Tick statistics (research P20, A10):** one `PAPER_TICK_STATS` per consumer batch with `batch_seq`, `bars_in`, `evaluated`, `held`, `duplicates`, `dropped_total`, `dropped_by_reason` (a host clock running behind shows as `{"FUTURE_CLOSE": n}`), `duration_ms` from two readings of the injected monotonic function, and `queue_depth_before`; `occurred_at_utc` is the injected tick time. The monotonic value is passed only into `_tick_stats_record` (AST test) and decides nothing.
- **Fail closed:** a full queue, a failed record write, a pipeline error or an error of the stop waiter stores the first failure, stops the loop, unsubscribes and closes the adapter, writes no `RUNTIME_STOP` and ends the process with `ExitCode.FAIL_CLOSED_RUNTIME` (7), so the restart reads the open START as a crash gap. The reason is logged and printed; for an arbitrary exception only its type name is reported, never its message.
- **Market inputs (Task 2):** `ConstraintProvider` builds `ConstraintSnapshot`s from the public `exchangeInfo` only, refreshes at `exchange_info_refresh_seconds` (`refresh_forever`), and the `BarContext` ttl is `constraint_snapshot_ttl_seconds`; an old or future-dated snapshot gives the existing `STALE_CONSTRAINTS` verdict through the real `evaluate_risk` (tested at the exact ttl boundary). `make_context_factory` takes the cost model from the registry slice of the pinned set (the source `run_paper_tick` binds), the absolute thresholds from registry rates times the initial equity, equity and risk rate from `[account]`, and open positions and the daily loss from the required `RiskInputsProvider` port (omitting it is a `TypeError`; an AST test proves src has no implementation). The start measures host minus server time once (`clock_skew_ms` in `RUNTIME_START` and in the log, no threshold).
- **Healthcheck (Task 3):** `python -m src.paper.runtime --healthcheck` prints `healthy` and exits 0 only while the latest `RUNTIME_START` is open and the last processed closed bar is no older than `healthcheck_max_bar_age_seconds`. A start with no bar yet is healthy for one maximum age. A stopped process, a trade-capable variable, an unratified configuration, a non-admitted or mismatching set, no pinned epoch and an empty allowlist all exit 1, so a container held after a refusal is reported unhealthy at once. Only names of variables are ever printed.
- **Q-D configuration part:** the recorded option is `history-only`, so no age key exists. `load_runtime_config` now refuses any key that is not part of the contract (`<section>.<key> (unknown key: nothing reads it)`); a test reads `16-DEC-Q-D.md` and fails loudly if the option ever changes, telling the next plan to add the required key. The README lists no such key and documents the probe and the unknown-key rule without any value.

## RED Evidence

- **Task 1** (`db2ac6d`): 10 tests failed individually at test run with `AttributeError: module 'src.paper.runtime' has no attribute 'LoopWiring'` (the module under test is imported as a module so collection succeeds); GREEN `11f20b2`: 10 passed, stable over three repeated runs.
- **Task 2** (`f801d84`): 14 tests failed (`AttributeError` on `market_inputs.ConstraintProvider` and friends; the production-shaped main tests failed with `paper runtime failed closed (exit 7): no BarContext factory is bound`). The AST clock test passed at RED because the Task 1 code already obeyed it. GREEN `66bcdfa`.
- **Task 3** (`a797e44`): 10 tests failed (`SystemExit(2)` for the unknown `--healthcheck` flag, the missing README text, no unknown-key refusal). GREEN `13e5a1a`.

## Task Commits

1. **Task 1 (tracer):** `db2ac6d` (test, RED), `11f20b2` (feat, GREEN)
2. **Task 2:** `f801d84` (test, RED), `66bcdfa` (feat, GREEN)
3. **Task 3:** `a797e44` (test, RED), `13e5a1a` (feat, GREEN)

The ledger count `git rev-list --count plan_head_before..HEAD` is larger than 6 because plan 16-25 committed to the same branch at the same time; `commits: 6` counts this plan's own commits.

## Verification

- Plan commands: `tests/test_paper_runtime_loop.py` (20 tests), `tests/test_paper_market_inputs.py` (17 tests), `test_paper_runtime_compose.py`, `test_paper_runtime_env.py`, `test_paper_start_gate.py`, `test_paper_runtime_admission.py`, `test_paper_runtime_pipeline.py`, `test_domain_no_float.py` pass; `mypy src` clean (177 files); `ruff check src tests` and `ruff format --check` clean for the files this plan touches.
- Fake-level green never closes PAPER-01 (SC9); the real feed, store and stop signal are exercised by plans 16-40, 16-43 and 16-44.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug prevented] Point-in-time constraint snapshots instead of "the latest snapshot"**
- **Found during:** Task 2 design, from `evaluate_risk` (`now_utc` is the bar close; a snapshot observed after the close has negative age and fails closed).
- **Issue:** a periodic refresh that lands even one second after a bar close would make every bar `STALE_CONSTRAINTS`.
- **Fix:** `ConstraintProvider` keeps a bounded history and `snapshot_for(symbol, close)` returns the latest snapshot observed at or before the close (otherwise the earliest, which stays future-dated and therefore stale). The staleness verdict is unchanged and still comes from `evaluate_risk`.
- **Files modified:** src/paper/market_inputs.py; **Commit:** 66bcdfa

**2. [Rule 2 - Missing critical] The unknown-key refusal replaces a named Q-D key check**
- **Issue:** the plan asks the key to be refused when Q-D did not choose fresh-within-bound, but plan 16-24 has a test that greps `src/` for the key name, so src cannot mention it.
- **Fix:** every key outside the contract is refused (`_refuse_unknown_keys`), which covers the Q-D key and any other unused threshold; the named key appears only in tests.
- **Files modified:** src/paper/runtime_config.py; **Commit:** 13e5a1a

**3. [Rule 2 - Missing critical] Refusal when the risk-inputs port is not bound**
- **Issue:** the port has no default in src (plan text), so the production default path cannot build a `BarContext`.
- **Fix:** `main` refuses with `CONFIG_NOT_RATIFIED` before `RUNTIME_START` when neither the port nor a test seam (`pipeline`, `context_factory`) is bound, with a reason that names plan 16-31 (holdable with `--hold-on-refusal`). `run_admitted` repeats the check as `RuntimeFailClosed`.
- **Commit:** 66bcdfa

**4. [Rule 3 - Blocking] Composition seams not named in the plan**
- `main(..., wiring=LoopWiring)` and the frozen `LoopWiring` (SDK client and factory, public adapter, risk-inputs port, context factory, pipeline, stop waiter, monotonic function, sleep, queue size) are the only way to drive the composed loop with fakes. Production passes only the risk-inputs port (plan 16-31). `market_inputs.py` was created in Task 1 (sibling fetcher, public-adapter protocol) because the pipeline needs `fetch_4h_bar` from the first run.
- **Commit:** 11f20b2

**5. [Rule 2 - Missing critical] Default queue size and snapshot history are implementation values**
- `QUEUE_MAXSIZE` (inbound bars) and `_SNAPSHOTS_PER_SYMBOL` (retained snapshots) are commented as implementation values, not thresholds (CONTEXT, Claude's discretion); a full queue is never absorbed.

**Total deviations:** 5 (1 Rule 1, 3 Rule 2, 1 Rule 3). **Impact:** no ratified decision changed; `src/paper/loop.py`, the pipeline, the supervisor and the backtest are untouched.

## Known Stubs

- The risk-inputs port (`RiskInputsProvider`) has no implementation by design; `main` refuses to start the live path until plan 16-31 binds it to the SHADOW ledger. Not recorded in `.planning/WINDOWS.md` (`gsd_run windows append` is not available to this executor); plan 16-31 resolves it.

## Points for the next plans

- **Plan 16-29 (restart and warm-up):** `run_admitted` starts with empty `BarBuffers` and does not seed the supervisor cursor (`record_close`) or run a REST warm-up. Until 16-29 every live bar is a recorded feed-gate reject (`WARMUP_INSUFFICIENT`) and a reconnect before the first live bar logs `paper.supervisor.no_last_close` and recovers nothing. The pipeline's `_seen` set is also in memory only (16-24 note).
- **Plan 16-31:** bind `RiskInputsProvider` (`open_positions(at_utc)` and `daily_loss_quote(at_utc)`, both asked at the bar close from the worker thread) and pass it as `LoopWiring.risk_inputs`; the tick runs it inside `asyncio.to_thread`, so a blocking ledger read is allowed.
- **Plan 16-27 (O-07 table):** `QUEUE_MAXSIZE` and `_SNAPSHOTS_PER_SYMBOL` are implementation values, not user numbers; `exchange_info_refresh_seconds` should stay below `constraint_snapshot_ttl_seconds` (the admission-rig values do not, and are test values); `healthcheck_max_bar_age_seconds` must exceed one bar interval (the container probe would otherwise flap).
- **Plan 16-32 (compose):** the probe is `python -m src.paper.runtime --healthcheck` (same environment and `--pinned-state` as the service); the stop path (SIGTERM) unsubscribes and closes before the process exits, so the stop grace period only has to cover one in-flight batch.
- **Plan 16-25 / coverage readers:** `PAPER_TICK_STATS` ids are `paper:<epoch>:tick:<tick_ms>:<batch_seq>`; `batch_seq` restarts at zero after a restart, so two ticks in the same millisecond and sequence would collide only if their payloads also differed.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: blocking-wait | src/paper/market_inputs.py | `make_sibling_fetcher` waits for a REST call from the tick's worker thread without an invented timeout (the SDK's own request timeout applies). A hung call would hold one worker thread and delay shutdown; the event loop is never blocked. |

Threat register: T-16-60 (callbacks only enqueue, store and tick in `asyncio.to_thread`, blocking-store test, full queue fails closed), T-16-61 (constraints only from exchangeInfo, ttl and cadence from the configuration, STALE_CONSTRAINTS on age, no fallback snapshot) and T-16-62 (healthcheck tied to processed-bar age) are mitigated as planned.

## Self-Check: PASSED

- Created files exist: `src/paper/market_inputs.py`, `tests/test_paper_runtime_loop.py`, `tests/test_paper_market_inputs.py`.
- Commits found: db2ac6d, 11f20b2, f801d84, 66bcdfa, a797e44, 13e5a1a.
- No secret written; STATE.md and ROADMAP.md untouched.
