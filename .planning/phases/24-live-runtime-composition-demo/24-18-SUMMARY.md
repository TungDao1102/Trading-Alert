---
phase: 24-live-runtime-composition-demo
plan: 18
subsystem: live
status: complete
tags: [user-data-stream, protection, fan-out, d-14, d-15, store-executor]
requirements-addressed: [EXEC-02, EXEC-01]
requires: [24-03, 24-05, 24-12]
provides:
  - "src/live/stream.py: StreamBundle, StreamSinks, build_stream, make_fill_fanout, make_fills_fallback, make_protection_step"
affects: [24-19, 24-26, 24-27]
tech-stack:
  added: []
  patterns:
    - "one synchronous fill sink that fans out in memory and schedules the only store write on the StoreExecutor writer"
    - "fire-and-forget tasks kept in a set and drained on shutdown; failures journaled by member and exception class only"
key-files:
  created:
    - src/live/stream.py
    - tests/test_live_stream_to_protection.py
  modified:
    - tests/test_phase18_gate.py
    - tests/test_userdata_supervisor.py
key-decisions:
  - "The listen-key port is the one already built with the shared gate in ExchangeBundle (plan 24-12); build_stream reuses it instead of constructing a second SdkListenKeyPort."
  - "A stream gap (supervisor state UNKNOWN) invalidates the equity source and the day-loss service with STREAM_GAP; a fill invalidates the equity with ACCOUNT_UPDATE (STREAM_GAP when the fill is after_gap)."
  - "A fill whose day-loss write cannot be scheduled or fails makes the day loss unknown (fail closed) instead of being skipped."
  - "make_protection_step runs WOKEN_STEP_PASSES=3 consecutive passes after a fill (place stop, confirm by REST, post-fill liquidation comparison); a periodic tick stays one pass."
metrics:
  tasks: 3
  commits: 1
plan_head_before: f76eacb857742886d156e121945fda992c59873c
plan_head_after: d46c025d4b8eced2c83815600bd7a794f56d0441
commits: 1
actuals:
  tokens: 60000
  tasks: 3
  commits: 1
completed: 2026-10-31
---

# Phase 24 Plan 18: User-data stream to the protection coordinator Summary

`build_stream` composes transport, adapter, supervisor (shared gate) and the Phase 18 router over the live client-id index, with one non-blocking fill fan-out (coordinator, protection wake, equity invalidation, day-loss write on the writer thread), so a fill frame at the transport edge ends in a REST-confirmed stop with no manual call and before the first periodic tick.

## What was built

- `src/live/stream.py`
  - `build_stream(*, exchange, stream_limits, clock, sleep, journal, index, coordinator, equity, day_risk, executor, snapshot_provider, sinks, session_id, ...)` returns a frozen `StreamBundle` (supervisor, router, adapter, wake event, fan-out, fallback, supervisor failure reasons). It starts nothing and makes no network call; `supervisor.start()` belongs to the start sequence (24-26). Optional hooks: `fills_reader`, `on_state_change`, `on_snapshot`, `on_failure`; test seams: `stream_configuration`, `ws_client_factory`, `ws_client`.
  - `StreamSinks`: the five router sinks other than the fill sink (status hint, exchange state, algo, account, divergence), supplied by the persistence/feeds plan (24-19).
  - `FillFanout` (`make_fill_fanout`): never raises, never blocks. Order: `coordinator.fill_sink`, wake event set, `equity.invalidate(reason=...)`, `day_risk.ingest_fill` scheduled as a task that awaits `StoreExecutor.write`. A raising member is counted (`member_failures`) and journaled as `FILL_FANOUT_MEMBER_FAILED` with `{member, error_class}` only (the row is written through the writer too). With no running loop, or a failed day-loss write, `day_risk.invalidate` makes the loss unknown.
  - `FillsFallback` (`make_fills_fallback`): returns `()` at once, schedules the injected async reader as a task, de-duplicates in-flight order ids, delivers the fills to the fan-out as `REST_FALLBACK`, journals a failed read as `FILLS_FALLBACK_READ_FAILED` (class name only).
  - `route_event` wraps `router.route` so an exception (for example a failing journal) is journaled as `STREAM_ROUTE_FAILED` and never reaches the supervisor loop.
  - `make_protection_step(coordinator, fanout)`: the scheduler body of the protection task (one pass per tick, `WOKEN_STEP_PASSES` passes after a fill).
- `tests/test_live_stream_to_protection.py` (18 tests, all SYNTHETIC frames, virtual time, `asyncio.sleep` forbidden).
- `tests/test_phase18_gate.py`: invariant 2 allow-list (`SUPERVISOR_IMPORTERS_ALLOWED`, reason D-14, exact-match assertion), a negative control with a seeded module under `tmp_path`, and `REST_HOLDERS_OUTSIDE_THE_LIVE_GATE` (data jobs, paper runtime, four scripts; reason "different process by design (D-15)"; files must exist and none may be under `src/live/`). CRLF kept (646 of 646 lines).

## Verification

- `uv run pytest -m "not docker"` on `test_live_stream_to_protection`, `test_phase18_gate`, `test_protection_router_rig`, `test_userdata_router`, `test_userdata_supervisor`, `test_userdata_rig`, `test_live_ast_guards`, `test_live_tracer`, `test_day_risk_stream`, `test_no_unratified_defaults`: all pass. Also `test_phase19..22_gate`, `test_paper_shadow_isolation`, `test_binance_usdm_source_guard`: pass.
- Tracer: a SYNTHETIC ORDER_TRADE_UPDATE emitted by the fake SDK stream client after CONFIRM placed one entry; with the protection tick set one virtual hour away, the stop is placed at the fill instant (asserted earlier than the first periodic tick), exactly one stop, the plan ends REST-confirmed (PROTECTED/COMPLETE), `blocks_new_entries()` is false, one `place_entry`.
- Mutation check: removing the wake from the fan-out fails the tracer, the liquidation test and five fan-out tests.
- An unknown client id is a router divergence: no fill reaches the fan-out, no wake, zero stops.
- D-24 activation: a coordinator built with the real `LiquidationWatch` (24-16) runs its post-fill comparison from the stream path and closes the position (one critical alert).
- The REST listen-key call goes through the shared gate: with a 418 recorded by another holder, `start_user_data_stream` is never called and the supervisor reports `RATE_LIMIT_BAN_ACTIVE`.
- `uv run mypy src/live` clean (15 files); `ruff check` and `ruff format --check` clean on the touched files; `pyproject.toml` and `uv.lock` unchanged.
- Not run (by instruction): PostgreSQL tests, the full suite.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] A second copy of Phase 18 invariant 2 lives in `tests/test_userdata_supervisor.py`**
- **Found during:** verification (`test_no_src_module_imports_the_supervisor` failed once `src/live/stream.py` imported the supervisor).
- **Fix:** one allow-list line for `src/live/stream.py` with a comment pointing at the gate. The plan lists this test file in its verification section but not in `files_modified`; no other Wave 4 plan names it.
- **Commit:** d46c025d

**2. [Rule 2 - Missing critical functionality] `make_protection_step`, the gap invalidation and the route-failure wrapper**
- The plan names only `build_stream`, `make_fill_fanout`, `make_fills_fallback`. A periodic-only scheduler call after the wake would place the stop but confirm it only at the next period (one pass places, the next confirms), which would leave the plan `blocks_new_entries()` for a whole tick and delay the D-24 check; so the step body runs three passes after a fill. The gap invalidation is required by the `invalidate` docstrings of the equity and day-loss services ("Phase 24 wires ... every stream gap"). Both live in `src/live/stream.py`.

**3. [Rule 3 - Blocking] The "known-gap REST holders list" did not exist in `tests/test_phase18_gate.py`**
- The known gap is only described in the docstring of `src/adapters/binance_ratelimit_gate.py`. The gate file now carries the list as `REST_HOLDERS_OUTSIDE_THE_LIVE_GATE`.

### Plan details that did not apply as written

- The plan says `build_stream` assembles `SdkListenKeyPort`; the exchange bundle (24-12) already owns that port on the shared gate, so it is reused (one construction site).

## Hand-off notes

- **24-27 (composition):** the protection `TaskSpec` must use `run=make_protection_step(coordinator, bundle.fanout)` and `wake=bundle.wake`; on shutdown await `bundle.fanout.drain()` before `executor.aclose()`. `StreamSinks` come from 24-19 (persistence writers, divergence queue). `bundle.supervisor.start()` runs after the gate restore (24-26).
- **No production REST fills reader exists.** `UserTradeRow` (`user_trades_in_window`) has no price, quantity or side, so it cannot become a `FillEvent`. `fills_reader` is therefore optional and, unset, the fallback schedules nothing; the router's FILL_TOTAL_MISMATCH divergence is then the only trace. A later plan must add the reader (or accept the divergence path) and wire it into `build_stream`.
- The three consecutive passes after a fill touch REST back to back (stop placement, then the confirm listing). The Demo smoke should show that the listing already contains the new stop; if not, the periodic tick confirms it, which is the earlier behaviour.
- No DECISIONS row is needed from this plan (D-14 and D-15 are CONTEXT decisions).

## Known Stubs

None.

## Threat Flags

None. T-24-51 (blocking sink): memory-only fan-out plus writer scheduling, held-writer test. T-24-52: wake event, virtual-time assertion. T-24-53: unknown ids become router divergences (test). T-24-SC: `pyproject.toml` and `uv.lock` unchanged.

## Self-Check: PASSED

- FOUND: src/live/stream.py, tests/test_live_stream_to_protection.py, tests/test_phase18_gate.py, tests/test_userdata_supervisor.py
- FOUND commit d46c025d (ancestor of HEAD)
