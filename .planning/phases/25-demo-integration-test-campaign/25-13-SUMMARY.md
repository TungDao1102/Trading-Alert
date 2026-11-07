---
phase: 25-demo-integration-test-campaign
plan: 13
subsystem: demo-scenarios
tags: [D-04, D-05, D-06, D-07, S08, S17, S09, stream-loss, listen-key, stale-feed, clock-skew, drift-guard, tdd, EXEC-02, OPS-01]
requires: [25-02, 25-08, 25-09, 25-10, 25-11, 25-12]
provides:
  - "tests/support/demo_scenarios/s08_stream_loss.py: S08 run(env, recorder, *, trigger=None, early_confirm=False), the trigger seam (ScriptedStreamTrigger / DemoStreamTrigger), install_scripted_stream, StateWatcher and shared helpers (card_and_approve, expire_plan, ticks, leave_safe_mode, health_verdict, failing_checks, record_gap)"
  - "tests/support/demo_scenarios/s17_stale_feed.py: S17 run(env, recorder), stale_age(limits), stale_alerts"
  - "tests/support/demo_scenarios/s09_clock_skew.py: S09 run(env, recorder) over an already skewed env, skew_for, loaded_drift_limits, install_twin_skew, drift_answer"
  - "three CI twins (tests/test_demo_twin_s08_stream_loss.py, _s17_stale_feed.py, _s09_clock_skew.py) and three owner-run demo tests (tests/demo/test_demo_s08_..., _s17_..., _s09_...)"
affects: [25-17, 25-19]
tech-stack:
  added: []
  patterns:
    - "one scenario is one async run(env, recorder) shared by the CI twin and the owner's Demo test"
    - "the composed process's REAL UserDataSupervisor runs over a scripted SupervisedAdapter on the twin; only the websocket edge is a fake"
    - "an injected trigger is DEMO_FAULT_INJECTED, the reaction carries the env label, anything not produced is NOT_OBSERVED"
    - "limits-derived numbers only: stale age and clock skew are computed from the loaded limits, never a literal"
key-files:
  created:
    - tests/support/demo_scenarios/s08_stream_loss.py
    - tests/support/demo_scenarios/s17_stale_feed.py
    - tests/support/demo_scenarios/s09_clock_skew.py
    - tests/test_demo_twin_s08_stream_loss.py
    - tests/test_demo_twin_s17_stale_feed.py
    - tests/test_demo_twin_s09_clock_skew.py
    - tests/demo/test_demo_s08_stream_loss.py
    - tests/demo/test_demo_s17_stale_feed.py
    - tests/demo/test_demo_s09_clock_skew.py
  modified: []
key-decisions:
  - "S08 twin: instead of setting the supervisor state by hand (the plan's wording), the process's real supervisor is started over a scripted SupervisedAdapter (`install_scripted_stream` replaces only `start_stream` in the env's ports). A hand-set state skips the state sink (`state_changed`), which is what invalidates the equity and the day loss on a gap; an early probe with a hand-set state wrongly showed an entry being placed during a gap. With the real supervisor the twin shows the real mechanisms."
  - "S08 Demo drop: the supervisor has no public rebuild(), and `adapter.rebuild()` alone is ignored by the supervisor (an old-epoch close with an open connection is stale). The trigger is the event the adapter's listener posts for a closed socket, for the CURRENT epoch, put into the supervisor's own `_on_connection_event`; the supervisor then runs its own rebuild, keepalive proof and REST snapshot. Labelled DEMO_FAULT_INJECTED."
  - "S08 listenKey expiry on Demo needs TRADING_DEMO_SLOW=1. With the loaded limits (keepalive 1800 s, tolerance 1) the supervisor re-keys after the first failed keepalive, so failing the keepalive is expected to show KEEPALIVE_FAILURES, not a real listenKeyExpired (research assumption A4 is unlikely to hold). The slow path returns what it saw; only a reported LISTEN_KEY_EXPIRED counts as observed."
  - "S08 is run twice on the twin in one scenario (a refusal cycle, then a catch-up cycle): a plan holds the symbol, so a CONFIRM during the gap and a resting entry whose order changes during the gap cannot coexist in one cycle."
  - "The scenario asks for `request_resync()` itself after a halted stream (finding F1) and counts it in `resync_requested_by_scenario`."
  - "S17 injects the stale mark at two readers: the public reader (health check and reconcile feed check) and the signed adapter's `get_mark_price` (the pre-placement/CONFIRM-recheck reader, as S03 found). The reconcile feed check judges only symbols of active plans, so the SAFE_MODE STALE_FEED reaction needs a resting entry: phase A (no plan: health FAIL + CONFIRM refused), phase B (resting entry: SAFE_MODE STALE_FEED + STALE_DATA alert, fresh mark does not leave SAFE_MODE, operator exit, entries allowed)."
  - "S09 twin: `build_fake_scenario_env` refuses a clock offset, so the twin answers `server_time` as clock minus the skew through `FaultEdge.override` (the real measurement and guard run) and routes `place_entry` through the real adapter's own `_require_entries_allowed()` first, because the fake serves `place_entry`. The twin's SDK stand-in has no `check_server_time`, so without the skew the twin's guard reports MEASUREMENT_FAILED; that is why the smoke skips the drift check on a synthetic env."
  - "S09 starts with `start_tolerant` (25-12), not `dr._bring_up`, which stops at a blocked guard before any card."
requirements-completed: [EXEC-02, OPS-01]
status: complete
duration: about 3h (estimate; start time was not recorded)
completed: 2026-11-07
commits: 6
plan_head_before: e9e09756a667aaa76260820adf42ac1f260ecd2c
plan_head_after: acc877be6fc8cf7aa477dd6e501fb06627af49fe
actuals:
  tokens: 23700
  tasks: 3
  commits: 6
---

# Phase 25 Plan 13: S08 stream loss, S17 stale feed, S09 clock skew Summary

The feed and clock scenarios of the Demo campaign, each as a shared `run(env, recorder)`, a CI twin on the fake composed process and an owner-run demo test. S08 shows that a lost user-data stream never lets an entry through and is reconciled when it returns (and that a `listenKeyExpired` restarts the stream once); S17 shows a stale mark fails closed with the reaction journaled; S09 shows a skewed clock is blocked by the real drift guard before anything is sent. Nothing under `src`, `scripts`, `pyproject.toml`, `uv.lock`, `harness.py`, `catalog.py` or `fault_edge.py` changed.

## Commits

| Task | RED | GREEN |
|------|-----|-------|
| 1 (tracer): S08 stream drop and listenKey expiry | 69f808cf | 5119ecc8 |
| 2: S17 stale feed drill | 1bf2e661 | a2139893 |
| 3: S09 clock skew | 38736227 | acc877be |

RED means the twin and demo test were committed while the scenario module was absent (collection error confirmed for S08 and S17; for S09 the module was likewise absent). Two RED commits (S08 twin, S09 twin) carried one ruff E501 line each in a docstring or `reason=` string; both were fixed in the matching GREEN commit.

## What each scenario asserts

**S08** (`s08_stream_loss.run(env, recorder, *, trigger=None, early_confirm=False)`): clean start, start, a `StateWatcher` records every `(state, reason)` the supervisor reports; baseline LIVE and health OK.
- Twin cycle 1 (stream held down): the injected close gives UNKNOWN (CONNECTION_CLOSED); `ws_connection_state` and `user_data_stream_state` FAIL and the verdict is no-trade; a `far` request is approved and confirmed during the gap: zero `place_entry`, the placement is refused (`RECONCILIATION_REQUIRED`); the silence/halt entered SAFE_MODE `USER_DATA_STREAM_HALTED` (silence bound 5791 ms on the twin); `/safemode_exit` is refused while the stream is not LIVE (refusal `STREAM_NOT_LIVE`, exit row 7); after twice the reconnect delay bound the stream is still UNKNOWN with no new transition and no new rebuild (finding F1); the reconnect is released, `request_resync()` is asked for, the stream passes UNKNOWN, SYNCING, LIVE; the operator exit leaves SAFE_MODE; a new `far` entry is placed and acknowledged (entries allowed after the documented exit).
- Twin cycle 2: drop again, the resting entry is cancelled on the fake behind the stream's back (no frame queued); the REST reconcile moves the plan to ENTRY_ENDED_NO_FILL while the stream is still down, REST snapshot calls grow after the resync; exit SAFE_MODE; expire the plan.
- Expiry: a `listenKeyExpired` item is queued, the supervisor reports UNKNOWN (LISTEN_KEY_EXPIRED), SYNCING, LIVE (exactly one LIVE entry, one rekey call), the after-gap REST snapshot ran, SAFE_MODE stays off. Ends COMPLETE.
- `early_confirm=True` (twin): CONFIRM right after the drop, before any reconcile tick: refused `UNCERTAIN_ACCOUNT_STATE` (the gap invalidated the equity, STREAM_GAP), SAFE_MODE not yet on, zero `place_entry`.
- Demo: place a `far` entry, inject the close, wait until the supervisor reports UNKNOWN and LIVE again, record the states, require an after-gap REST snapshot, then the expiry step (NOT_OBSERVED with the reason unless `TRADING_DEMO_SLOW=1`), cancel the entry, `account_clean`. The four gap steps (health in gap, entry in gap, silence, no self resync) are recorded NOT_OBSERVED: the supervisor rebuilds within seconds, so the outcome is always COMPLETE_WITH_GAPS on Demo.

**S17** (`s17_stale_feed.run`): `stale_age(limits)` is twice the larger of `stale_feed.max_mark_price_age_ms` and `pre_placement.max_mark_price_age_ms` (an unset bound raises `ValueError`; twin: 8642 ms). Phase A: a request is derived and approved while fresh; stale marks are armed at both readers (`FaultEdge.stale_mark` and `override("get_mark_price")`); `market_feed_freshness` FAILs; the CONFIRM is refused (twin: `DEMO_CONFIRM_EXPIRED`, `MARK_PRICE_UNAVAILABLE`, from the approval core's recheck), zero `place_entry`. Phase B: with a resting entry a stale public reading makes SAFE_MODE `STALE_FEED` and an `OPERATIONAL_ALERT` `STALE_DATA` (`MARK_PRICE_STALE`); after the fault the feed check passes and SAFE_MODE stays; the operator exit leaves it, health is OK, entries are not blocked; entry cancelled, `account_clean`. Injection step `label_for(env, injected=True)`, reactions the env label.

**S09** (`s09_clock_skew.run`): `skew_for(limits)` is twice the larger drift limit (twin: 1752 ms against 432 ahead and 876 behind). `start_tolerant`, then `ClockDriftGuard.blocked_reason` must be set (twin: measured offset 1752 ms, `OUT_OF_LIMITS`, not within limits); a request is approved and confirmed: no order, algo order or position, and the refusal is journaled (twin: `LIVE_PLACEMENT_OUTCOME` `ENTRY_REFUSED_BEFORE_SEND`, the real `EntriesBlocked` PreSendRefusal); `minus_1021_seen` records a pending re-measure (assumption A3) and the nothing-placed check holds either way; `account_clean`. The skew step is DEMO_FAULT_INJECTED on Demo, the guard and the refusal the env label.

## REUSES per twin

| Twin | REUSES |
|---|---|
| `tests/test_demo_twin_s08_stream_loss.py` | `tests/test_userdata_supervisor.py::test_tracer_start_live_close_unknown_rebuild_snapshot_live_after_gap`, `::test_listen_key_expired_event_rekeys_and_resyncs`, `tests/test_live_stream_to_protection.py::test_a_gap_makes_the_equity_and_the_day_loss_unknown`, `tests/test_reconcile_stream_divergences.py::test_a_halted_supervisor_is_a_divergence_enters_user_data_stream_halted_and_alerts`, `tests/test_live_feed_source.py::test_silence_beyond_the_limit_is_stale_even_when_the_stream_says_live` |
| `tests/test_demo_twin_s17_stale_feed.py` | `tests/test_live_feed_source.py::test_silence_beyond_the_limit_is_stale_even_when_the_stream_says_live`, `::test_the_loop_judges_a_dead_feed_through_the_live_feed_source`, `tests/test_feed_freshness.py::test_only_the_asked_symbols_are_judged`, `tests/test_drills.py::test_stale_feed_drill_enters_safe_mode_through_the_loops_feed_check` |
| `tests/test_demo_twin_s09_clock_skew.py` | `tests/test_clock_drift.py::test_an_out_of_limit_measurement_is_a_successful_verdict_outside_limits`, `::test_a_minus_1021_never_re_enables_entries_by_itself`, `tests/test_live_demo_smoke.py::test_a_start_whose_clock_drift_guard_blocks_entries_stops_before_any_card` |

Each twin has a test that checks every referenced test name exists in its file; the plan's REUSES AST one-liner exits 0 (checked for S17).

## Verification

- `uv run pytest -m "not docker" tests/test_demo_twin_s08_stream_loss.py tests/test_demo_twin_s17_stale_feed.py tests/test_demo_twin_s09_clock_skew.py tests/test_demo_marker_guard.py -x -q`: passed (54 tests).
- With `tests/demo`, `test_demo_same_code_path.py`, `test_demo_harness.py`, `test_demo_env_factory.py`, `test_no_unratified_defaults.py`, `test_fault_edge.py`, `test_demo_evidence_index.py` and the S01-S07 and S18 twins: 433 passed, 14 skipped (all 14 are demo tests, none passed), 1 xfailed (the S07 finding of plan 25-12). `TRADING_CI_STRICT=1` collection of `tests/demo` exits 0.
- Scoped `ruff check`, `ruff format --check` on the nine files: clean. `uv run mypy src`: no issues (291 files). `uv lock --check`: ok.
- `git diff --exit-code -- src scripts pyproject.toml uv.lock tests/support/demo_scenarios/harness.py tests/support/demo_scenarios/catalog.py tests/support/fault_edge.py` exits 0.
- No `pytest -m demo`, no `--execute`, no signed or network call, no `.env` read. The nine new files are LF.

## Deviations from Plan

**1. [Mechanism, inside latitude] S08's twin runs the real supervisor over a scripted adapter.** The plan's wording ("supervisor state set as go_live does, in reverse; frame routing") would skip the state sink and the supervisor's own recovery, and showed a wrong result in a probe. See key-decisions. The twin-only part is the `SupervisedAdapter` (the websocket edge) and the private patch `supervisor._adapter = adapter`.

**2. [Plan wording, no code change] "The health verdict refuses new entries" is not what `src` does.** The health verdict is journaled and consulted only by the start sequence and `enable_demo`; no runtime path turns a RED verdict into a refusal. What refuses a CONFIRM during a gap is (a) the equity the gap invalidated (`UNCERTAIN_ACCOUNT_STATE`, immediately) and (b) SAFE_MODE after the halt or the silence (`RECONCILIATION_REQUIRED`). The scenarios assert and record those, plus the health verdict as an observation.

**3. [Plan wording] S08 Demo trigger is not `await supervisor.rebuild()`.** See key-decisions (no public `rebuild()` on the supervisor; the injected close event for the current epoch makes the supervisor run its own rebuild). It uses the private `_on_connection_event`.

**4. [Plan wording] The listenKey expiry on Demo cannot be provoked by failing the keepalive alone.** Loaded limits give tolerance 1, so a re-key (KEEPALIVE_FAILURES) comes first. The step stays NOT_OBSERVED unless the owner sets `TRADING_DEMO_SLOW=1`, and even then a real expiry event is not expected.

**5. [Scope choice] S17 and S09 are shaped by what the code reads.** S17 needs two readers and two phases (see key-decisions). S09's twin needs the server-time answer and the guard shim.

**6. [Shared helpers] The scenarios import helpers from `s03_crossed_stop.py`, `s04_stop_rejected.py`, `s06_replay.py`, `s07_restart_cuts.py` and `s08_stream_loss.py`.** The catalog names only the nine files of the plan.

## Findings

**F1 (behaviour gap, not fixed; no src change allowed here): nothing in `src` ever calls `UserDataSupervisor.request_resync()`.** After a recovery halts (reconnect exhausted, a ban, a hard listenKey failure) the supervisor reports `on_failure` once and then waits for `request_resync()`; `rg request_resync src` finds only its definition and comments. The twin shows it: after the halt the stream stays UNKNOWN for twice the reconnect delay bound with no new transition and no new rebuild. Consequences: SAFE_MODE `USER_DATA_STREAM_HALTED` cannot be left through `/safemode_exit` (exit row 7, `STREAM_NOT_LIVE`) until the process restarts, and the stream never recovers on its own after a longer outage. The interim stop procedure (RUNBOOK 22.5) is the only way out. The scenario calls `request_resync()` itself and counts it (`resync_requested_by_scenario`). Whether the live process should request a resync (for example from the reconcile loop or an operator command) is an owner decision with its own DECISIONS row. The owner should expect this on a real Demo outage during the soak.

**F2 (observation): the health verdict is observational at runtime.** D056 item 1 and the D102 sentence "in LIVE a DEGRADED verdict ... blocks new entries once enabled" are carried by the verdict itself; the only consumers are the start sequence and `enable_demo`. Entries during a degraded state are refused by other mechanisms (equity invalidation on a stream gap; SAFE_MODE from the reconcile loop; the CONFIRM recheck for a stale mark), as S08 and S17 show. LIVE is disabled, so there is no live consequence today; the owner may want the D102 wording checked before Phase 26.

**F3 (observation): stale marks reach SAFE_MODE only for active plans.** `ReconcileLoop._check_feeds` judges the symbols of active protection plans, so a stale public reading with no plan only fails the health check; entries are refused by the CONFIRM recheck (`MARK_PRICE_UNAVAILABLE`), which reads `adapter.get_mark_price`. Both are by design; S17 covers both.

**F4 (observation, twin fidelity): the twin's drift measurement fails without help.** The composed rig's SDK stand-in has no `check_server_time`, so its guard reports MEASUREMENT_FAILED and the fake serves `place_entry`; the drift guard's `EntriesBlocked` is never on the twin's path. S09's twin therefore answers the server time and calls the real adapter's guard method itself (stated in the module). The real adapter's own enforcement is covered by `tests/test_binance_usdm_*` and `tests/test_clock_drift.py`, not by this twin.

No xfail was needed. No other twin exposed a defect in `src`.

## Not covered by an agent-run test

Everything below first runs in the owner's session (`pytest -m demo`, `TRADING_DEMO_RUN=1`); agents never connect to Demo:

- The three demo tests only collect and skip. The supervisor's own rebuild after the injected close event on the real adapter (the real keepalive proof, the real new websocket, the real REST snapshot, the real `stream.adapter.epoch`) and the private `_on_connection_event` seam against the real supervisor are unobserved; the twin's supervisor is the real class over a scripted edge. The `StateWatcher` patch of `supervisor._on_state_change` is untested against the real PostgreSQL-backed process.
- S08 Demo: the states the real supervisor passes through (UNKNOWN, SYNCING, LIVE) for SAFE_MODE exit row 7 (D-07) are recorded, not asserted beyond UNKNOWN then LIVE. The gap steps are NOT_OBSERVED by design. The slow expiry path (`TRADING_DEMO_SLOW=1`, keepalive failures through `SdkFaults`, wait of twice the keepalive interval) is code that no test runs; it is checked only by the not-set branch and by reading.
- S17 Demo: the stale-mark injection at the real public reader and the real `get_mark_price` (the `FaultEdge` over the real adapter), the real CONFIRM recheck reason, the durable SAFE_MODE STALE_FEED on the PostgreSQL store and its operator exit are unobserved. The refusal event and reason are recorded, not pinned on Demo.
- S09 Demo: assumption A3 (the SDK stamps from the system clock, so signed calls survive an injected process clock) is untested; `clock_offset` also shifts card and approval clocks of the process (the skew is about one second). The real server-time measurement against Binance and the real `EntriesBlocked` refusal are unobserved. The exchange-side -1021 stays with the owner opt-in probe.
- The S08 twin shows a halted stream with no self resync only because nothing calls `request_resync()` (F1); a future src change that does would change the twin step `halted_stream_waits_for_resync` on purpose.

## Known Stubs

None.

## Threat Flags

None. T-25-30 (S08 asserts refusal while the stream is down, REST catch-up and the exit after LIVE; S17 asserts a stale mark is refused and reaches SAFE_MODE; each with a negative control), T-25-31 (S09 asserts the drift guard blocks entries and that nothing is placed; a pending -1021 is recorded) and T-25-SC (no package added; `pyproject.toml` and `uv.lock` unchanged) hold.

## Self-Check: PASSED

The nine created files exist; commits 69f808cf, 5119ecc8, 1bf2e661, a2139893, 38736227 and acc877be are ancestors of HEAD; `git rev-list --count e9e09756..acc877be` is 6.
