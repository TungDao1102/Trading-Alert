---
phase: 16-paper-runtime-composition
plan: 56
subsystem: paper-runtime-feed
status: complete
tags: [paper-runtime, websocket, watchdog, fail-closed, liveness, heartbeat, configuration-v2, B1-CR-01, B1-WR-06, B1-WR-02, B1-WR-12, B1-WR-10]
requires: [16-55]
provides:
  - exhausted WebSocket rebuild ends the process with exit 7 after its REST backfill (on_fatal sink)
  - in-process feed-silence watchdog with one bounded recovery, then exit 7 (one _fail call)
  - SDK transport errors mapped to project errors for the paper path; one retry reaches them
  - state port engine via make_sync_engine; unreachable database at start exits 7
  - exchangeInfo strict only for the configured symbols on the paper path
  - loader refuses minute_close_lag_seconds = 0; consumer-domain check before RUNTIME_START
  - config/paper/paper-runtime-v2.toml (v1 values + [health] feed_silence_timeout_seconds 120)
  - src/paper/liveness.py and python -m src.paper.runtime --liveness
  - deploy/heartbeat.sh --target paper and the trading-soak-paper-heartbeat units
  - decision records 16-DEC-WS-WATCHDOG and 16-DEC-CLOSE-LAG-ZERO
affects: [16-43, 16-57, 16-59, 16-62]
tech-stack:
  added: []
  patterns:
    - "one connection-wide monotonic frame stamp written in the SDK handler (one attribute write)"
    - "one guard shared by two fail-closed routes so _fail runs exactly once"
    - "opt-in project transport errors per adapter instance (SDK types stay in src/adapters)"
    - "event-loop liveness stamp file read by an exec probe that drives an external ping"
key-files:
  created:
    - src/paper/liveness.py
    - config/paper/paper-runtime-v2.toml
    - deploy/systemd/trading-soak-paper-heartbeat.service
    - deploy/systemd/trading-soak-paper-heartbeat.timer
    - tests/test_paper_runtime_watchdog.py
    - tests/test_paper_runtime_liveness.py
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-WS-WATCHDOG.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-CLOSE-LAG-ZERO.md
  modified:
    - src/paper/supervisor.py
    - src/paper/runtime.py
    - src/paper/runtime_config.py
    - src/paper/live_minutes.py
    - src/paper/market_inputs.py
    - src/adapters/binance_public.py
    - deploy/heartbeat.sh
    - deploy/soak-image.sh
    - deploy/soak.env.example
    - config/paper/README.md
    - docs/operations/RUNBOOK.md
    - docs/operations/DEPLOY_GUIDE.vi.md
key-decisions:
  - "The SDK-error mapping is opt-in per BinancePublicMarketData instance (project_transport_errors=True, set by the paper composition root); the order adapter, the probe and the data jobs keep the SDK types that the Phase 18 error taxonomy classifies"
  - "The watchdog has its own injected sleep and monotonic clock seams (LoopWiring.watchdog_sleep, LoopWiring.feed_clock), so existing tests that inject the loop sleep or the tick-stats monotonic function are unaffected"
  - "[health] is a RuntimeHealthConfig, a subclass of HealthThresholds with the new required field; the coverage code and its tests are unchanged"
  - "The paper heartbeat install needs --soak-env-file, because the unit runs deploy/compose-soak.sh and the compose file needs the soak env file for interpolation"
duration: about 50 minutes
completed: 2026-10-16
commits: 5
plan_head_before: d781b65c97d4bea1955acd67226ec3b241910105
plan_head_after: 5114bdc8ae5c51dc6a7c9d184ab69f092127a323
actuals:
  tokens: 49700
  tasks: 4
  commits: 5
---

# Phase 16 Plan 56: Feed fails closed Summary

The paper feed now either recovers within the ratified bounds or ends the process with exit 7:
an exhausted rebuild and a silent connection both fail closed after their backfill, a silent
feed is caught in 120 s, and a separate paper heartbeat pings only while the event loop and the
feed are both alive.

## Tasks

| Task | Name | Commit |
| --- | --- | --- |
| 1 | Tracer: an exhausted WebSocket rebuild backfills, then exit 7 (B1-CR-01 exhaustion half) | abe6ebe |
| 2 | B1-WR-06, B1-WR-02, B1-WR-12: SDK errors, state engine, exchangeInfo per symbol | 21cb6ab |
| 3 | Step 0 records | d3e2cc3 |
| 3 | Watchdog with bounded recovery, zero close lag refused, configuration v2 | 63ffa58 |
| 4 | Liveness probe and the separate paper heartbeat | 5114bdc |

Commit count, measured: `git rev-list --count --first-parent d781b65..HEAD` is 6. That includes
the orchestrator's merge of phase-18 (6610bd6), which landed on `develop` during this plan; it
is not a 16-56 commit. The 16-56 commits are the five above. The plain `rev-list --count` is 96
because it counts the merged Phase 18 history.

## Re-check outcomes

All five findings held. Each re-check test failed before its fix:

- **B1-CR-01, exhaustion half.** The end-to-end test through `main` hung on the parent. The
  process stayed up after `reconnect_exhausted` and never failed. A bounded script wait now
  turns that into a failing exit-code assertion instead of a hang.
- **B1-WR-06.** Through the real adapter, a `binance_common.errors.ServerError` propagated out
  of `poll_once` with no retry. The default tuple `(TimeoutError, ConnectionError)` never
  matched an SDK error.
- **B1-WR-02.** A spy on `make_sync_engine` was never called by `_state_from_env`, which used a
  bare `create_engine(url, future=True)`.
  - On the parent, an unreachable database surfaced only later, through the lease path
    (`StoreUnavailable`, exit 7).
  - A `SessionTimeZoneNotUtc` was never detected at start.
- **B1-WR-12.** One malformed unrelated contract made `exchange_info()` raise. A
  `ConstraintProvider` refresh for five valid configured symbols then failed.
- **B1-WR-10.** `parse_runtime_config` accepted `minute_close_lag_seconds = 0`, while
  `LiveMinutePoller` raised "close_lag_seconds must be positive, got 0". This is recorded in
  16-DEC-CLOSE-LAG-ZERO.md.

## Recorded options

- `decisions/16-DEC-WS-WATCHDOG.md`:
  - `option: Q1-new-key`, with `[health]` and `feed_silence_timeout_seconds: 120` as their own
    lines; the configuration test binds these lines.
  - Corrections 2 and 5, verbatim.
  - The heading "Qualifying message (planning fact, not the owner's words)".
- `decisions/16-DEC-CLOSE-LAG-ZERO.md`: `option: Q2-reject-zero`, plus the B1-WR-10 re-check.

Both records carry `decided by: user`, `date: 2026-10-16`, the source (commit bdbdc11) and the
user's line verbatim. A script copied the reviewer sections byte for byte.

The stream re-check ran after the Phase 18 merge, with codegraph and a search of
`src/adapters/paper_ws.py`. The paper connection opens only `kline_candlestick_streams`, so only
kline frames qualify. No stamp was needed in `paper_ws.py`.

## Watchdog design

- **The stamp.** `PaperSupervisor._on_kline` first does
  `self._last_frame_monotonic = self._feed_clock()`, before the `is_closed` filter. It is one
  connection-wide attribute write per frame of any stream, forming updates included, with no I/O
  on the SDK thread. An AST test checks this.
- **The watchdog task.** `_LiveLoop._watch_feed` wakes through `LoopWiring.watchdog_sleep` at
  half of `config.health.feed_silence_timeout_seconds`. The bound comes only from the
  configuration; the AST test allows only the divisor 2 as a literal.
  - A silence longer than the bound measures from the last frame, or from the watchdog's start
    before the first frame. It starts `PaperSupervisor.recover_from_silence()` once per episode.
  - That call is the SDK `close` path: `WS_DISCONNECT`, live bars held, a bounded rebuild under
    the ratified `SUPERVISOR_MAX_*`, then a history-only backfill.
  - It is skipped when a recovery is already pending or rebuilding, so there is no double
    recovery.
  - A frame after the silence began ends the episode.
  - When the bound expires again with no frame, the loop fails closed with
    "market stream silent", exit 7 and no RUNTIME_STOP.
- **One fail-closed cause.** `_fail_feed` is the one guard shared by the watchdog's second
  deadline and the supervisor's `on_fatal` sink. It does nothing once a failure is stored, the
  stop event is set or the teardown has begun. The supervisor also never calls `on_fatal` while
  it is stopping.
  - Test 1b counts exactly one `_fail` call in both orders.
  - In the first order, the deadline passes while the rebuild is blocked, then the rebuild is
    released with a failure.
  - In the second order, the rebuild exhausts first, then the watchdog deadline is pushed past.
- **No late signal.** In the half-open test, the bar that closed during the silence reaches the
  pipeline as `REST_BACKFILL`. The pipeline treats such bars as history only (Q-D).
- **Ratified constants unchanged.** `SUPERVISOR_MAX_ATTEMPTS` 7, `SUPERVISOR_MAX_DELAY_SECONDS`
  120, `SUPERVISOR_WAIT_MULTIPLIER_SECONDS` 1 and `SUPERVISOR_WAIT_MAX_SECONDS` 60 are unchanged,
  and a guard test checks them.

## Liveness and heartbeat design

- **The stamp file.** On every wake, and once at its start, the watchdog writes
  `logs/paper/liveness-<container>.json` atomically, from the event loop. It holds the container
  name, the loop-alive time and the last-frame time. The last-frame wall time is derived from
  the feed clock, so the SDK handler stays a single attribute write.
- **The probe.** `--liveness` is handled before any start step, like `--healthcheck`. It exits 0
  only when all of these hold:
  - no held marker of this container exists;
  - a liveness file of this container exists;
  - the loop-alive and last-frame times are both within `feed_silence_timeout_seconds`.

  It prints `live`, or `not live: <reason>` on one line. It opens no database, network or
  Telegram client. `_liveness` was added to the exit-0 inventory of
  `tests/test_paper_runtime_held_state.py`.
- **The sender.** `deploy/heartbeat.sh --target paper` runs only
  `deploy/compose-soak.sh exec -T paper /app/.venv/bin/python -m src.paper.runtime --liveness`
  and pings only when the probe exits 0.
  - It has its own URL file (`/etc/trading/heartbeat-paper.url` or `HEARTBEAT_PAPER_URL_FILE`),
    its own credential (`heartbeat-paper-url`) and its own units.
  - `--install-timer` requires `--soak-env-file`. It refuses a `--url-file` that names the
    collector's file.
  - Every URL-secrecy and xtrace rule of the script applies to this target.
  - Without `--target`, the collector path is unchanged and all of its existing tests pass. The
    collector units are byte-unchanged since 5f8269b.
- **Documentation.** RUNBOOK 20.9 states the recorded numbers from 16-DEC-HUNG-RUNTIME: a 60 s
  interval on the timer, and a 60 s period and 120 s grace in the dashboard. It also says that:
  - the probe is the 120 s liveness, not the 3900 s bar-age healthcheck;
  - a held, hung or silent runtime sends no success ping;
  - the heartbeat is an alert, not proof of recovery.

  The DEPLOY_GUIDE has two new cards and five new section-14 rows.

## Deviations from Plan

1. **[Rule 4 resolved inside the plan's intent] Opt-in SDK-error mapping.** The Phase 18 merge
   (6610bd6) added a REST rate-limit gate and an error taxonomy to `binance_public.py` and
   `binance_usdm.py`. That taxonomy (`error_facts_from_exception`) classifies the SDK classes,
   for the order adapter delegations and for the probe.
   - Mapping the errors for every caller would have changed Phase 18 behaviour. So the mapping
     is opt-in through `BinancePublicMarketData(project_transport_errors=True)`.
   - Only the paper composition root (`_resolve_public`) sets it. A test checks this.
   - The gate still records a 429/418 before the mapping (tested).
   - No Phase 18 file was edited. 412 neighbouring tests passed, Phase 18 adapter and probe tests
     included.
2. **[Rule 3] Separate watchdog seams.** The plan says the watchdog wakes "through the injected
   sleep". It has its own `LoopWiring.watchdog_sleep` and `LoopWiring.feed_clock`. The shared
   loop sleep and the tick-stats monotonic function are asserted call by call by existing tests
   (refresh periods, FakeMonotonic readings). The AST rule "monotonic is called only in
   `_monotonic_ms`" holds, because the default is the reference `time.monotonic`, not a call.
3. **[Rule 3] `RuntimeHealthConfig`.** Adding a field to `HealthThresholds` would have changed the
   coverage contract and its tests. A frozen subclass carries the new required, strictly positive
   key instead.
4. **[Rule 2] Consumer-domain check.** `check_consumer_domains(config)` builds the
   `LiveMinutePoller` (no I/O) before RUNTIME_START. A future consumer that is narrower than the
   loader then refuses with exit 4, not 7 (Test 4).
5. **[Rule 2] SHADOW store construction.** `_shadow_from_env` errors at construction, which come
   from `make_sync_engine` in `_pg_shadow_stores`, also map to exit 7 with one line, never a
   traceback.
6. **[Rule 3] `--soak-env-file` for the paper install.** The unit sets `TRADING_ENV_FILE`, so
   that `deploy/compose-soak.sh` interpolates the soak env file.
7. **[Rule 3] Files outside the plan's list:**
   - `tests/test_paper_replay_inputs.py`: its fake `exchange_info` takes `symbols`.
   - `tests/test_paper_runtime_held_state.py`: `_liveness` added to the exit inventory.
   - `tests/test_paper_exit_evaluator.py`: its inline config also changed
     `minute_close_lag_seconds` from 0 to 5, which is now refused, besides gaining the new key.
   - `deploy/systemd/*` and `scripts/check_image_paths.py`: `check_image_paths.py` never named
     v1, so it is unchanged.
8. **Test value of the new key in the admission rig.** It is 300, so the watchdog never wakes on
   real time in the existing loop tests. The watchdog tests read the bound from that rig, never a
   literal.

## Verification

Commands use `uv run --frozen --extra dev`. Only targeted tests were run (memory-limited
machine).

- **Task 1:** watchdog, supervisor_backfill and runtime_loop: 55 passed.
- **Task 2:**
  - binance_public, live_minutes and market_inputs: 69 passed.
  - compose, shadow_isolation, replay_inputs and runtime_loop: 94 passed, 1 skipped.
  - Neighbouring tests (adapter_not_found_mapping, adapter_strictness, binance_probe,
    binance_probe_contract, ratelimit_gate, constraint_snapshot, symbol_filters_extra,
    universe_freeze, paper_shadow_runtime): 412 passed.
- **Task 3:**
  - The full verify set of 14 files: 452 passed, 13 skipped. The skips are 12 shellcheck tests
    and 1 `TEST_DATABASE_URL` test.
  - Neighbours (market_inputs, shadow_runtime, coverage, held_state, instance_guard, restart,
    shadow_isolation, deploy_docs, deploy_guide_vi): 284 passed.
  - The v1/v2 TOML check printed `True [('health', 'feed_silence_timeout_seconds')]`.
  - `git diff --quiet 5f8269b HEAD -- config/paper/paper-runtime-v1.toml params/` exits 0.
- **Task 4:** liveness, heartbeat, soak_runbook, deploy_docs, deploy_guide_vi, watchdog,
  held_state, runtime_loop and compose: 316 passed, 4 skipped (file-mode tests on Windows).
  `git diff --quiet 5f8269b HEAD -- deploy/systemd/trading-heartbeat.service deploy/systemd/trading-heartbeat.timer`
  exits 0.
- **Checks:** `ruff check src scripts tests` passed; `ruff format --check src scripts tests`
  reports 569 files formatted; `mypy src` found no issues in 202 files.
- **Not run here** (recorded in `.planning/WINDOWS.md`, entries 4 to 7):
  - the PostgreSQL test (no `TEST_DATABASE_URL`; Docker and PostgreSQL are off);
  - shellcheck (not installed);
  - live ping delivery, the systemd credential and the timer on the soak host;
  - the watchdog on a real half-open Binance connection.

## Owner actions (before plan 16-43)

- Create the second healthchecks.io check for the paper runtime, with a period of 60 s and a
  grace of 120 s. Then store its URL on the soak host with
  `sudo deploy/heartbeat.sh --target paper --set-url` (one line on standard input). Then install
  with
  `sudo deploy/heartbeat.sh --target paper --install-timer --interval-seconds 60 --soak-env-file <soak.env>`.
  The URL must never be written into the repository.
- Unchanged from 16-55: the separate soak backup bucket.

## Requirement status

PAPER-01 stays Pending. The plan lists it, but REQUIREMENTS.md closes it only when the Phase 16 criteria 1, 2 and 7 hold (D061 item J), which needs the trial soak of plan 16-43. The `requirements.mark-complete` call was reverted for that reason.

## Known Stubs

None.

## Threat Flags

| Flag | File | Description |
| --- | --- | --- |
| threat_flag: file-write | src/paper/liveness.py | New per-container file on the logs volume (container name and two times only; T-16-172) |
| threat_flag: secret-read | deploy/heartbeat.sh | The paper target reads its own root-only URL file or credential `heartbeat-paper-url` (T-16-173) |

## Self-Check: PASSED

- FOUND: src/paper/liveness.py, config/paper/paper-runtime-v2.toml, both paper heartbeat units,
  tests/test_paper_runtime_watchdog.py, tests/test_paper_runtime_liveness.py, both decision records
- FOUND commits: abe6ebe, 21cb6ab, d3e2cc3, 63ffa58, 5114bdc
