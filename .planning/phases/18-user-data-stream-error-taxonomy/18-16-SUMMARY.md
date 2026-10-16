---
phase: 18-user-data-stream-error-taxonomy
plan: 16
subsystem: scripts/operator-tools, ops/operator-evidence
status: complete
tags: [smoke, user-data-stream, demo, evidence, dry-run, operator-tool, EXEC-05, OPS-02, D-04, D-15, D-18, T-18-47, T-18-48, T-18-49, T-18-50]
requires: [18-04, 18-09, 18-11, 18-13, 18-14]
provides:
  - src/ops/operator_evidence.py (EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_ABORTED, jsonable, write_evidence_atomic, confirm_execute, ConfirmationRefused, DemoOrderLimits, DemoOrderLimitsRefused, load_demo_order_limits with kinds "smoke" and "probe", OPTIONAL_CASE_KEYS, sha256_lf)
  - scripts/user_data_smoke.py (EVIDENCE_SCHEMA, SmokeConfig, SmokeRig, build_dry_run_rig, build_live_rig, DryRunScenario, run_smoke, check_smoke_evidence, smoke_acceptance_verdict, plan_far_order, scan_for_secrets, main)
  - tests/test_operator_evidence.py, tests/test_user_data_smoke_dry_run.py, tests/test_user_data_smoke_evidence.py, tests/test_user_data_smoke_cli.py
affects:
  - plan 18-17 and 18-23 (demo probe consumes write_evidence_atomic, confirm_execute and load_demo_order_limits(kind="probe") unchanged)
  - plan 18-18 (blocking-human: runs `--execute` on Demo, re-checks the committed file with check_smoke_evidence and smoke_acceptance_verdict)
  - plan 18-19 (adds `--transport direct` to this script)
tech-stack:
  added: []
  patterns:
    - the dry run drives the identical pipeline (real adapter, port, transport, supervisor, public reader) over SDK-shaped fakes, with SDK REST calls inlined and virtual time moved only when in-loop work has settled
    - fake frames go through the SDK module global parse_user_event, so the raw-frame tap sees dry-run frames exactly as live ones
    - acceptance verdict computed from the document and stored in it; every verdict entry carries the proof class
key-files:
  created:
    - src/ops/operator_evidence.py
    - scripts/user_data_smoke.py
    - tests/test_operator_evidence.py
    - tests/test_user_data_smoke_dry_run.py
    - tests/test_user_data_smoke_evidence.py
    - tests/test_user_data_smoke_cli.py
    - .planning/phases/18-user-data-stream-error-taxonomy/deferred-items.md
  modified: []
decisions:
  - "write_evidence_atomic scrubs with the given redactor AND the process redactor (runtime-registered keys, secrets and listenKeys), before the write and in the post-write re-scan"
  - "jsonable refuses a float, a naive datetime and any unknown type instead of falling back to str()"
  - "The account must be flat on the symbol before the smoke; otherwise the run aborts (exit 3) before any order, so the after-state check means something"
  - "Keepalive acceptance (d) is one explicit PUT through the adapter right after LIVE; the supervisor's own keepalive timer (1800 s) is not waited for"
  - "The live transport configuration uses the ratified stream.sdk_reconnect_delay_ms and stream.sdk_reconnect_attempts (not wired anywhere before)"
  - "Observation f is one direct PUT on the SDK REST object after the stream's DELETE, through the shared gate, recording (http_class, int code, category) only"
  - "TESTNET is accepted by the parser (the plan's choices) but refused with exit 2 while its row is NOT_CONFIGURED, before any prompt"
metrics:
  duration: "about 30 minutes (2026-10-16T07:30Z to 08:00Z)"
  completed: 2026-10-16
  tasks: 3
  files: 7
estimate:
  tokens: 104000
  tasks: 3
actuals:
  tokens: 49000
  tasks: 3
  commits: 7
plan_head_before: 2d701179bdabd7232abe1ef4e8e6b79fe3bb1b75
plan_head_after: 2a05a8c29cf2e44b6a87b8210ace0c8499cf7c97
---

# Phase 18 Plan 16: Connected-machine user-data smoke and offline dry run Summary

`scripts/user_data_smoke.py` is the operator tool that plan 18-18 runs on Demo. It composes the project's `UserDataAdapter`, `SdkListenKeyPort`, guarded `SdkUserDataTransport` and `UserDataSupervisor`. It places and cancels one far LIMIT BUY, records whether typed `ORDER_TRADE_UPDATE` NEW and CANCELED arrive through the SDK `user_data` route (`sdk_route_delivery`), forces a transport drop and measures the UNKNOWN to snapshot to LIVE recovery, and observes what a PUT answers after the DELETE. It writes one scrubbed `user-data-smoke-evidence/schema-1` file. By default the identical pipeline runs offline over the SDK-shaped fakes on virtual time (`proof_class` FAKE), and that dry run already passes acceptance a, b, c, d, e, g and h, with f OBSERVED. The shared module `src/ops/operator_evidence.py` provides the atomic scrubbed write, the typed confirmation and the owner's order-limits loader (smoke and probe kinds).

Nothing in this plan contacted Binance: every run was a dry run or a test.

## Commits

`commits: 7` is measured as `git rev-list --count 2d70117..2a05a8c`. Plan 18-15 committed on the same `phase-18` branch at the same time, and 3 of those 7 commits are its (7a79c57, 70db815, e0ecc61). This plan's commits are:

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | e960017 | shared operator-evidence module; the smoke script with the dry rig, the run and the evidence document; operator-evidence tests and the dry-run tracer |
| 2 | 968bc58 | dry-run scenarios, the schema checker with a negative control per rule, verdict tables a to h, the one-gate source tests, the aiohttp pin |
| 3 | 4122658 | the CLI safety-gate tests and the `configure_output` seam of `main` |
| cleanup | 2a05a8c | drop an unused `SmokeRun` parameter |

## What was built

- **`src/ops/operator_evidence.py`** (standard library plus `src.ops.redaction`, no SDK):
  - Exit codes are 0, 1, 2 and 3.
  - `jsonable` turns Decimal into plain text and an aware datetime into UTC ISO text. It maps any Enum to its value and turns dataclasses, mappings and sequences into JSON data recursively. It refuses a float, a naive datetime and anything else.
  - `write_evidence_atomic` writes sorted-key ASCII JSON with LF line endings. It scrubs first, writes a `mkstemp` temp file, then uses `os.replace` into a name that does not exist yet (`-2`, `-3`). It re-reads and re-scans the file; if the scan still finds something, it deletes the file and raises `RuntimeError`. The stem must be a plain file name.
  - `confirm_execute`.
  - `DemoOrderLimits` has no defaults. Fields the kind does not use are explicitly None.
  - `load_demo_order_limits(path, kind=)` handles both kinds:
    - smoke: `order.symbol/quantity/far_price_fraction`, `waits.event_wait_seconds/cleanup_timeout_seconds`.
    - probe: adds `max_notional_quote` and `case_timeout_seconds`, plus the three `optional_cases` booleans. `market_lot_probe_quantity` is required exactly when `market_lot_size_out_of_range` is true.
    - Decimal values are plain decimal strings. `far_price_fraction` must be strictly between 0 and 1. Any missing, unknown or malformed key or section is refused, and the message names keys only.
  - `sha256_lf`.
- **`scripts/user_data_smoke.py`**:
  - **Parser.** It raises `UsageError` and sets `allow_abbrev=False`. The options are `--environment` (DEMO or TESTNET, required), `--limits-file` (default: the ratified file), `--smoke-limits-file` (required), `--evidence-dir`, `--fixtures-dir` and `--execute`. Plans 18-17 and 18-23 consume the probe kind and plan 18-19 adds `--transport direct`.
  - **Steps.** The run records 13 step records in order: preflight, account_before, stream_start, keepalive, order_place, order_new_event, order_cancel, order_canceled_event, forced_drop, account_after, stop_and_delete_then_put, log_scan and evidence_write.
    - Preflight runs the environment guard. It then measures drift with `measure_clock_drift` against the ratified drift limits, through the gated `BinancePublicMarketData`; a failed or out-of-limit measurement aborts with exit 3. It then reads the exchange filters and the mark price.
    - The far price is `floor_tick(mark * far_price_fraction)`. The order is refused when the price is outside the PERCENT_PRICE band or the band is not published, the quantity is below the minimum, above the maximum or off the step grid, the notional is below the minimum, or the symbol is not TRADING.
  - **Cleanup.** Cleanup always runs. It cancels the order (bounded by `cleanup_timeout_seconds`) if the order was attempted and not yet confirmed cancelled, then reads the account state after the run, then stops with `close_listen_key=True`, then makes the direct PUT.
  - **Live rig.** `build_live_rig`:
    - checks that the row is configured;
    - loads credentials with `credential_spec_for` and `load_api_credentials`, using `refuse_if_present=(LIVE spec,)`;
    - builds the client with `build_sdk_client` (REST and WS_STREAMS, the ratified client limits);
    - checks every stage and every call with a guard: `assert_environment(bundle)` plus the transport's streams URL against the row;
    - builds ONE `RestRateLimitGate` and shares it with `BinanceUsdmAdapter` (with `signed_call_policy`), `BinancePublicMarketData`, `SdkListenKeyPort` and the supervisor;
    - wraps the transport with `GuardedTransport`, which re-asserts the environment before each connect, resubscribe and rebuild;
    - calls `install_sdk_noise_guard()`;
    - drops the transport with `_drop_transport`, which closes `connection.websocket._response` of the private connection.
  - **Dry rig.** `build_dry_run_rig` uses ONE gate on virtual time. The real port, transport, adapter, supervisor and public reader run over `FakeUserDataWsClient`, a `FakeRestUserDataApi` subclass that answers the configured SDK error after the DELETE, a fake public REST object and the fake order port `DryRunOrders`. The fake order port emits frames through `parse_user_event`, exactly as the SDK receive loop does.
  - **Checks.** `check_smoke_evidence` and `smoke_acceptance_verdict` are implemented as the plan states; every verdict entry carries the `proof_class`.
  - **Banner.** The run prints a start banner about the account-singleton listenKey (P7), and the same sentence is in `notes`.
  - **Log scan.** It covers stdout, stderr and the root logs (through a handler with `RedactingFilter`) plus the evidence draft. It searches for the key, the secret and the listenKey values the run holds, and for `signature=` followed by 64 hex characters, and records counts only.
  - **Fixtures.** With `--fixtures-dir`, frames are written to `<mode>-<NNN>-<event>.json` through the same scrub. `provenance.md` labels them RECORDED_DEMO for executed runs and FAKE_DRYRUN for dry runs. A dry run aimed at `tests/fixtures/phase18/recorded_demo` is refused.

## Verification

All commands ran with `UV_OFFLINE=1 uv run --frozen --extra dev`. The full suite was not run (memory limit).

- Plan verification: `pytest -m "not docker" tests/test_operator_evidence.py tests/test_user_data_smoke_dry_run.py tests/test_user_data_smoke_evidence.py tests/test_user_data_smoke_cli.py tests/test_demo_rehearsal_safety.py -x` gave **274 passed**:

  | File | Passed |
  |------|--------|
  | `test_operator_evidence.py` | 72 |
  | `test_user_data_smoke_dry_run.py` | 17 |
  | `test_user_data_smoke_evidence.py` | 110 |
  | `test_user_data_smoke_cli.py` | 40 |
  | `test_demo_rehearsal_safety.py` | 35 |

- Neighbouring structural scans also passed: `test_no_unratified_defaults`, `test_binance_client_config` (the SDK construction-site allow-list), `test_execution_secret_posture`, `test_env_example`, `test_binance_secret_redaction`, `test_redaction`, `test_paper_ws_smoke_evidence`, `test_userdata_adapter`, `test_userdata_supervisor`, `test_code_version`, `test_kill_gate_clock` and `test_paper_shadow_isolation`.
- `ruff check`: all checks passed. `ruff format --check`: 599 files already formatted. `mypy src`: no issues in 199 source files. `uv lock --check`: resolved 60 packages, unchanged.
- Mutation check: with `refuse_if_present=()` in `build_live_rig`, the LIVE-variable refusal tests fail. The source was restored from a scratch copy.
- The dry-run tests patch `asyncio.sleep`, `socket.getaddrinfo`, `socket.create_connection`, `BaseEventLoop.create_connection`, `requests.Session.request` and `build_sdk_client` to fail. `socket.socket` is replaced by a subclass that refuses any non-loopback connect (see deviation 1).

## TDD Gate Compliance

- **Task 1.** The tests failed first (ImportError, `src.ops.operator_evidence` missing), and passed after the module and script were written. The tracer gate re-ran the Task 1 verify end to end and it passed (78 tests).
- **Task 2.** The script was written whole in Task 1, so the Task 2 scenario and verdict tests passed on their first run; they were not watched failing. The mutation check above and the negative controls of every checker rule stand in for that red step.
- **Task 3.** One CLI test failed first on a test bug (two separate AST parses compared by node identity) and was fixed. The `configure_output` seam was added so that no test runs the process-wide `configure_logging`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `socket.socket` cannot simply be patched to fail on Windows**
- **Found during:** Task 1 (tracer).
- **Issue:** the Windows Proactor event loop builds its self-pipe from `socket.socketpair()`. That falls back to a loopback `socket.socket`, so `asyncio.run` itself failed under a blanket patch.
- **Fix:** the tests replace `socket.socket` with a subclass that refuses every connect to a non-loopback address. They also make `socket.getaddrinfo`, `socket.create_connection` and `BaseEventLoop.create_connection` fail, so any path to a network host still fails.
- **Files:** tests/test_user_data_smoke_dry_run.py, tests/test_user_data_smoke_cli.py. **Commit:** e960017, 4122658.

**2. [Rule 3 - Blocking] The dry run inlines the SDK REST calls of the fakes**
- **Issue:** `SdkListenKeyPort`, `BinancePublicMarketData` and the signed helper call `asyncio.to_thread`. A real worker thread would let virtual time move while a fake call is still pending, for example a spurious snapshot deadline.
- **Fix:** during a dry run only, `_dry_run_patches` swaps `asyncio.to_thread` for an inline call and installs a fresh SDK stream map. Both are restored afterwards (tested). Executed runs are unaffected.
- **Commit:** e960017.

**3. [Rule 2 - Correctness] Abort when the symbol is not flat before the smoke**
- **Issue:** if an order or position already exists, the after-state check cannot tell what the smoke left behind.
- **Fix:** `account_before` aborts (exit 3) before any order when the symbol has an open order, an algo order or a position. Tested.
- **Commit:** e960017.

**4. [Rule 2 - Security] The evidence scrub also uses the process redactor**
- **Issue:** `Redactor.from_environ` does not include runtime-registered secrets, such as listenKeys and keys read from `_FILE` files.
- **Fix:** `write_evidence_atomic` scrubs and re-scans with both. Tested.
- **Commit:** e960017.

**5. [Rule 3] `main` gains the `configure_output` seam**
- **Issue:** an executed run calls `configure_logging` (global structlog, root handler, excepthooks) before loading credentials. The CLI tests reach that point.
- **Fix:** the seam replaces `configure_logging` in tests.
- **Commit:** 4122658.

### Interpretation notes

- **Test file scope.** `tests/support/limits.py` must not be imported by scripts (`test_no_unratified_defaults`). The dry run therefore loads the ratified limits file (the `--limits-file` default), and the tests read numbers from it instead of using literals.
- **Fakes.** The fake public REST object and the fake order port live in the script's dry-run section, because the plan creates no new test-support module. The listenKey and WebSocket fakes and the frame builder are loaded lazily from `tests/userdata_fakes.py` and `tests/support/userdata_frames.py`.
- **`SKIPPED_DRY_RUN`.** It is an allowed step status but no step uses it. Every step runs over the fakes in a dry run.
- **mypy.** `mypy scripts/user_data_smoke.py` (outside the `mypy src` gate) still reports about 17 errors. Most are the SDK pydantic models' snake_case keyword arguments, which the repository's tests use the same way.

## Findings (not changed: outside the plan's files)

- **Credential names.** `.env.example` (lines 70-71) and `scripts/demo_rehearsal.py` (`ENV_BINANCE_KEY`, `ENV_BINANCE_SECRET`) still name the Demo key `BINANCE_TESTNET_API_KEY` and `BINANCE_TESTNET_API_SECRET`. The ratified DEMO names are `BINANCE_DEMO_API_KEY` and `BINANCE_DEMO_API_SECRET`, and the smoke reads only those (or their `_FILE` forms). The operator of plan 18-18 must export the DEMO names. This is recorded in `deferred-items.md` for a later plan.
- **SDK reconnect limits.** `stream.sdk_reconnect_delay_ms` and `stream.sdk_reconnect_attempts` were not wired anywhere before this plan. The live rig of the smoke now passes them to `ConfigurationWebSocketStreams`. The production composition (Phases 24 and 25) still has to wire them.

## Known Stubs

None. The dry-run fake values (`DRY_RUN_FAKE_*`) are labelled FAKE and only ever produce `proof_class` FAKE evidence.

## Threat Flags

None beyond the plan's register. T-18-47 to T-18-50 are mitigated as listed: there is no credential or host option, the run executes only after the gate and the phrase, refusals happen before any client is built, the scrub runs before and after the write, the dry run cannot reach the network, and there is exactly one far order with cleanup in the finally path.

## Self-Check: PASSED

The six created source and test files and `deferred-items.md` exist. Commits e960017, 968bc58, 4122658 and 2a05a8c are on `phase-18`.
