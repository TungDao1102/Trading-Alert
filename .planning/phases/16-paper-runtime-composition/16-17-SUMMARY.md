---
phase: 16-paper-runtime-composition
plan: 17
subsystem: paper-runtime / live-smoke tooling
tags: [websocket, smoke-test, evidence, binance-sdk, sources, redaction, virtual-clock]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-08 (async PaperSupervisor with sinks, event-driven recovery and REST backfill) and plan 16-01 (PaperWsAdapter with rebuild, last_rebuild, diagnostics, on_connection; SDK-shaped fakes)"
provides:
  - "scripts/paper_ws_smoke.py: public-data WS smoke recorder (--dry-run for CI, --live for plan 16-21 only) writing one scrubbed, atomic evidence file"
  - "check_evidence_schema (every measurement object carries a status) and check_forced_disconnect (fails the user-initiated close path with 'unsolicited path not proven'), both reused by plan 16-21 on the live file"
  - "tests/test_paper_ws_smoke_evidence.py: 60 offline tests (schema, redaction, unsolicited forced disconnect with negative control, SDK rotation on a faked clock, archive fetch, socket count, arrival latency, clock skew, REST 1m lag, AST guards)"
  - "docs/SOURCES.md: 'Facts read for Phase 16' section with 17 cited rows and the Connect row's 24-hour lifetime gap closed"
  - "PaperWsAdapter.sdk_connections(): read-only snapshot of the SDK connection objects"
affects: [16-21 live proof, 16-27 O-07 table, 16-43 trial soak, 16-25 closure rule]

actuals:
  tokens: 31700
  tasks: 4
  commits: 7
plan_head_before: 93103fbdb24580ebd86dfa8a830e39e782ca95dd
plan_head_after: c8ef31b012a37050cfda3e7f18ed7421b4509410
commits: 7

tech-stack:
  added: []
  patterns:
    - "One injected clock (RealClock or VirtualClock) for every sleep and timestamp; the virtual clock runs a single pump task that pops a timer heap, so concurrent sleepers stay ordered"
    - "A rig object holds everything environment-specific (fake versus real SDK); a fake rig is never labelled REAL_SMOKE, even in --live mode"
    - "Forced disconnect proves its path from data the SDK produced (stale stream names found by rebuild), not from the script's own say-so"
    - "Measurement functions never compare a measured value with a numeric literal (AST test)"

key-files:
  created:
    - scripts/paper_ws_smoke.py
    - tests/test_paper_ws_smoke_evidence.py
  modified:
    - docs/SOURCES.md
    - src/adapters/paper_ws.py

key-decisions:
  - "path_exercised is 'unsolicited' only when the first rebuild after the drop found stale stream names in the SDK global stream map AND no close API was called during the drop; the first RebuildReport after the drop is read through a delegating adapter wrapper because later rebuilds overwrite last_rebuild (a live drop of three sockets can trigger three rebuilds)"
  - "A fake rig is never REAL_SMOKE: proof_class is REAL_SMOKE only when mode is live AND the rig is the built-in live rig"
  - "--live checks BINANCE_* environment names before the operator flag (exit 3 before exit 2); only the NAME is ever printed"
  - "The SDK rotation timer override is applied in main around rig construction and the run, only in --live, and restored in a finally block; the 300 s floor is a tool guard, not a trading threshold"
  - "The archive fetch is requested by default (--no-archive-fetch turns it off) and only runs after a successful subscribe; network errors get one retry in --live only"
  - "Cursors are seeded with the last close before the exchange's now (server time), because a cursor seeded from a host clock that is ahead of Binance would drop the next real bar as a duplicate"

patterns-established:
  - "Pattern: smoke evidence objects use status OK / NOT_RUN / ERROR; a step that was not requested is NOT_RUN, never absent"
  - "Pattern: a negative control test drives the wrong close path and asserts the proof check rejects it"

requirements-completed: [PAPER-01]

coverage:
  - id: D1
    description: "The dry-run recorder composes PaperWsAdapter and PaperSupervisor over SDK-shaped fakes and writes one schema-valid, secret-scrubbed, atomically written evidence file; fake evidence is labelled proof_class FAKE"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_dry_run_writes_one_schema_valid_evidence_file"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_a_secret_in_a_recorded_error_is_scrubbed_before_the_write"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_the_post_write_scan_removes_a_file_that_fails_it"
        status: pass
    human_judgment: false
  - id: D2
    description: "--live refuses any BINANCE_* variable (exit 3, name only), needs the operator flag, never imports src.execution or names the order adapter, and a fake rig can never produce REAL_SMOKE evidence"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_live_refuses_when_any_binance_variable_is_present"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_the_script_imports_no_execution_module_and_never_names_the_order_adapter"
        status: pass
    human_judgment: false
  - id: D3
    description: "The forced disconnect goes through the unsolicited path (transport drop beneath the SDK, never the SDK close API), is proven by stale stream names found by rebuild, and the user-initiated path is rejected by check_forced_disconnect"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_forced_disconnect_goes_through_the_unsolicited_path_and_is_proven"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_the_user_initiated_close_path_is_not_accepted_as_proof"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_aiohttp_still_keeps_the_response_on_the_websocket_object"
        status: pass
    human_judgment: false
  - id: D4
    description: "The SDK 23 h rotation path (82800 s) is covered on a faked clock: no reconnect at 82799 s, exactly one at 82800 s with a REST verification backfill; the live override shortens the SDK timer for the smoke process only and restores it"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_exactly_one_reconnect_fires_at_the_sdk_rotation_interval_and_is_verified"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_live_sets_the_sdk_timer_for_the_run_only_and_restores_it"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_nothing_under_src_assigns_the_sdk_rotation_constant"
        status: pass
    human_judgment: false
  - id: D5
    description: "Measurement fields (SDK socket count, arrival latency and clock skew with future_close_events, REST 1m trade and mark lag, archive fetch) are recorded as observations and never compared with a numeric literal"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_the_rest_lag_probe_records_lag_equal_to_polls_times_the_poll_interval"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_no_measured_value_is_compared_with_a_numeric_literal"
        status: pass
      - kind: unit
        ref: "tests/test_paper_ws_smoke_evidence.py#test_the_archive_fetch_records_url_status_rows_and_sha256"
        status: pass
    human_judgment: false
  - id: D6
    description: "docs/SOURCES.md records every external fact Phase 16 relies on with URL, read date and a not-verified-live label, and closes the 24-hour-lifetime gap of the Connect row"
    requirement: PAPER-01
    verification:
      - kind: other
        ref: "python -c check of docs/SOURCES.md (Facts read for Phase 16, 24-hour, 2026-10-08) printed True"
        status: pass
    human_judgment: false
  - id: D7
    description: "That the real SDK on mainnet behaves as the dry run models it: ws_subscribe succeeds, closed events arrive, the transport drop takes the SDK's unsolicited branch and leaves stale stream names, the SDK reconnect works on a real socket, a data.binance.vision fetch succeeds, and the measured numbers (sockets, latency, skew, REST lag)"
    requirement: PAPER-01
    verification: []
    human_judgment: true
    rationale: "Everything here was proven against SDK-shaped fakes on a virtual clock (proof_class FAKE). The --live mode was never run by this plan; plan 16-21 runs it on the connected machine and applies check_evidence_schema and check_forced_disconnect to the real file (SC9: fake-level green never closes PAPER-01)."

duration: 35min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 17: Public-data WS smoke recorder and Phase 16 source facts Summary

**A single-command smoke recorder that drives `PaperWsAdapter` and `PaperSupervisor` on public market data (fakes on a virtual clock in CI, the real SDK in `--live` for plan 16-21), proves a forced disconnect went through the unsolicited close path from the stale stream names the rebuild found, records SDK rotation, socket count, arrival latency, clock skew, REST 1m trade/mark lag and one data.binance.vision fetch as redacted observations, and cites every external fact Phase 16 depends on in `docs/SOURCES.md`.**

## Performance

- **Duration:** about 35 min
- **Started:** 2026-10-09T13:33:42Z
- **Completed:** 2026-10-09T14:08Z
- **Tasks:** 4 (Task 1 tracer, Tasks 2 and 4 TDD auto, Task 3 docs)
- **Files:** 4 (2 created, 2 modified)

## Accomplishments

- Tracer: `main(["--dry-run", ...])` builds the adapter over an SDK-shaped fake client, runs the real supervisor, counts closed bars per interval at the supervisor sink, counts forming updates as dropped, and writes one JSON file through a scrub, temp-file, `os.replace`, post-write-scan writer that deletes the file if the scan fails. `check_evidence_schema` rejects any file in which a measurement object or its `status` is missing.
- Live guards: `--live` exits 3 when any `BINANCE_*` name is present (name only printed), exits 2 without `--i-am-on-the-connected-machine`, builds only a credential-free REST adapter and the default SDK stream client, and labels a fake rig `FAKE` even in live mode.
- Forced disconnect (research D3, P4): `transport-drop` closes the aiohttp response that backs each SDK connection (like a network failure), `ws-close` awaits `close()` on the aiohttp websocket; neither touches the SDK's close API (AST-enforced). The path is derived from the first `RebuildReport` after the drop. The negative control drives the fake's user-initiated `close_connection()` and `check_forced_disconnect` returns `unsolicited path not proven`.
- SDK rotation (research D2): the faked-clock test shows no reconnect at 82799 s and exactly one at 82800 s followed by a REST verification backfill; `--sdk-reconnect-interval-seconds` (floor 300) shortens the SDK timer for the live process only and restores it in a finally block (tested, including the failure path).
- Measurements: SDK socket count after connect and after rebuild (2 sockets is an observation, not a failure), per-interval arrival latency and `future_close_events` on the injected clock, clock skew at start and end (or an error string), and the REST 1m trade/mark lag probe with explicit measurement settings (no defaults), finished before the forced disconnect.
- Archive: one daily 1h data.binance.vision fetch through `fetch_archive_klines`, recording url, HTTP status, rows and the sha256 of the zip payload (a recording client wraps the stream); errors are recorded, not raised, with one retry in `--live` only.
- `docs/SOURCES.md`: 17 new rows (Binance streams and REST, Connect page facts, endpoint split, Telegram, SDK internals, GitHub Actions, AWS, rclone), each with URL, read date, "WebFetch summary, not verified live" and the UNVERIFIED sub-points; the Connect row now cites the 24-hour lifetime.

## RED Evidence

- **Task 1** (`8e9b3bb`): `ImportError: cannot import name 'paper_ws_smoke' from 'scripts'` at collection (the module did not exist), the same module-absent RED style plan 16-08 used.
- **Task 2** (`6dab464`): 22 of the 43 tests failed on the missing behaviour (`unrecognized arguments: --no-archive-fetch --sdk-reconnect-interval-seconds 600`, missing `SmokeRun`, `check_forced_disconnect`, `drop_connections`, `DryRunConfig.archive_mode`). The AST and contract pins (aiohttp attribute path, rotation constant, no close API in the script) already held and stay as regression guards.
- **Task 4** (`0c52468`): 12 of 60 tests failed (missing `connection_count`, arrival, skew and lag objects, `--rest-lag-*` options, measurement functions). The probe-settings usage test passed before the change for the wrong reason (`unrecognized arguments`) and now passes for the right one.

## Task Commits

1. **Task 1 (tracer): dry-run smoke through adapter and supervisor** - `8e9b3bb` (test, RED), `aefa770` (feat, GREEN)
2. **Task 2: live guards, forced disconnect, SDK rotation, archive fetch** - `6dab464` (test, RED), `f7f10f9` (feat, GREEN)
3. **Task 3: SOURCES.md facts for Phase 16** - `97fd2c9` (docs)
4. **Task 4: measurement fields** - `0c52468` (test, RED), `c8ef31b` (feat, GREEN)

**Plan metadata:** committed separately (docs: complete plan).

## Files Created/Modified

- `scripts/paper_ws_smoke.py` - the recorder: argparse CLI, clocks, evidence schema and validators, atomic scrubbed writer, observed WS adapter, live and dry-run rigs, `SmokeRun` steps, measurement functions
- `tests/test_paper_ws_smoke_evidence.py` - 60 tests
- `docs/SOURCES.md` - Phase 16 facts section and the updated Connect row
- `src/adapters/paper_ws.py` - `PaperWsAdapter.sdk_connections()` (see deviations)

## Decisions Made

See `key-decisions`. For plan 16-21: run `uv run python -m scripts.paper_ws_smoke --live --i-am-on-the-connected-machine --out <evidence dir> --intervals 1m,1h,4h --duration-seconds <N> --force-disconnect-after-seconds <N> --sdk-reconnect-interval-seconds <N >= 300> --rest-lag-probe-minutes <M> --rest-lag-poll-interval-ms <ms> --rest-lag-max-wait-seconds <s>` in a shell with no `BINANCE_*` variable, then apply `check_evidence_schema` and `check_forced_disconnect` to the file. The probe settings and durations are measurement settings chosen by that plan; this tool has no default for the probe settings.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] No public way to reach the SDK connection objects**
- **Found during:** Task 2 (live transport drop needs "every SDK connection of the adapter's client")
- **Issue:** `PaperWsAdapter` kept the client in a private attribute, so the script could only reach the connections through private access.
- **Fix:** added a read-only `PaperWsAdapter.sdk_connections() -> tuple[Any, ...]` with a docstring that restricts it to operator tooling, plus a test.
- **Files modified:** src/adapters/paper_ws.py (not in the plan's `files_modified`), tests/test_paper_ws_smoke_evidence.py
- **Commit:** f7f10f9

**2. [Rule 1 - Bug] Virtual clock ordered concurrent sleepers wrongly**
- **Found during:** Task 4 (the REST lag probe sleeps while the main loop sleeps; the probe saw 30000 ms instead of 750 ms)
- **Issue:** the first `VirtualClock` let every sleeper pump the timer heap, so one pump could pop the next timer before a coroutine woken by the previous timer had run.
- **Fix:** a single pump task pops timers in order and settles (several loop yields plus the supervisor's `wait_idle`) after each, so woken coroutines register their next sleep before time moves on.
- **Files modified:** scripts/paper_ws_smoke.py
- **Commit:** c8ef31b

**3. [Rule 1 - Bug, test only] Wrong expectation for a host clock behind the server**
- **Found during:** Task 4
- **Issue:** with the host 3 s behind the server a third 1m close is delivered inside the 150 s run, so the expected counts (3 future events, 2 one-minute closes) were wrong.
- **Fix:** the test now expects 4 future events and `{"1h": 1, "1m": 3}`; the code was right.
- **Commit:** c8ef31b

### Plan-shape choices (not defects)

- `ws_subscribe` is an object (`status`, `reason`, `subscribed_streams`) and `connection_count`, `arrival_latency_ms_by_interval`, `clock_skew_ms` and `rest_minute_lag` carry the sub-objects named in the plan's tests. Extra CLI options: `--recovery-wait-seconds` (a tool timeout for the close event after the drop), `--archive-fetch/--no-archive-fetch` (default on), `--archive-day`.
- `--duration-seconds` defaults to 600; the probe settings have no default, as planned.
- The dry-run rig and the fake archive host (an `httpx.MockTransport`) live in the script, with `tests.paper_ws_fakes` imported lazily so `--live` never loads test code.
- `close_api_calls` is the fake client's counter in a dry run and a script-level 0 in `--live` (the script never calls a close API, an AST test enforces it); the evidence says which source applied (`close_api_call_source`). The real proof in a live file is the stale stream names, which a user-initiated close cannot produce.
- The archive fetch and the probe run only after a successful subscribe.

---

**Total deviations:** 3 auto-fixed (1 Rule 3, 2 Rule 1). **Impact:** all within the smoke tooling; one small additive accessor in `src/adapters/paper_ws.py`; no threshold, retry constant or runtime behaviour changed; no package installed and `uv.lock` unchanged.

## Issues Encountered

- A shell heredoc carrying the Task 2 test appendix failed on quoting before any file was written; the appendix was written from a scratch file instead.
- `src/data/archive.py` imports `Kline` and `_row_to_kline` from `src.adapters.binance_usdm`, so importing the archive fetcher loads the order-adapter module. The smoke script never references or constructs `BinanceUsdmAdapter` (AST test) and never imports `src.execution`, but a later guard that scans transitive imports of anything composing the smoke would see that module (plan 16-38 should scan names, not module loading).

## Known Stubs

None.

## Known Limitations (for plans 16-21, 16-27, 16-43)

- `--live` was never run (by design); every behaviour above is proven against SDK-shaped fakes. Whether a transport drop of all three sockets triggers one rebuild or three, whether the SDK emits `close` during its rotation, and the real latency, skew, socket and REST-lag numbers are exactly what plan 16-21 must show. Coverage item D7 records this as needing a human.
- The lag probe measures against the host clock; read it together with `clock_skew_ms`.
- The pre-existing failure `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments` (logged in `deferred-items.md` by plan 16-15) still fails and was not touched.

## Threat Flags

None new. T-16-40 mitigated (BINANCE_* refusal with exit 3, operator flag, AST ban on `src.execution` imports and the order adapter name), T-16-41 mitigated (`src.ops.redaction` scrub, atomic write, post-write scan that deletes the file; tested with a seeded URL password, a Telegram-token shape and an environment secret value), T-16-113 mitigated (transport drop beneath the SDK, `path_exercised` derived from rebuild's stale stream names, negative control for the user-initiated path, SDK timer shortened for the smoke process only and restored in a finally block), T-16-SC accepted (no package installed).

## User Setup Required

None for this plan. Plan 16-21 needs a network path to `fstream.binance.com` that does not return 502 and a shell with no `BINANCE_*` variable.

## Next Phase Readiness

- Plan 16-21 can run the recorder on the connected machine and validate the file with `check_evidence_schema` and `check_forced_disconnect`; plan 16-25's closure rule can read `proof_class` (`FAKE` never closes PAPER-01); plan 16-27 can tabulate the observation fields for O-07.

## Verification

- `tests/test_paper_ws_smoke_evidence.py`: 60 passed. `tests/test_paper_ws_connect.py`, `tests/test_paper_ws_contract.py`: passed.
- Full `pytest -m "not docker"` (with the known `test_cost_parity` case deselected): exit 0, no failures (database-dependent tests skip without `TEST_DATABASE_URL`).
- `ruff check` and `ruff format --check` (470 files) clean; `mypy src` clean (163 files); the SOURCES.md verify command printed `True`.
- No file was deleted by any commit.

## Self-Check: PASSED

- FOUND: scripts/paper_ws_smoke.py, tests/test_paper_ws_smoke_evidence.py, docs/SOURCES.md, src/adapters/paper_ws.py
- FOUND commits: 8e9b3bb, aefa770, 6dab464, f7f10f9, 97fd2c9, 0c52468, c8ef31b
