---
phase: 18-user-data-stream-error-taxonomy
fixed_at: 2026-10-19T00:00:00Z
review_path: .planning/phases/18-user-data-stream-error-taxonomy/18-REVIEW.md
iteration: 1
findings_in_scope: 33
fixed: 26
skipped: 7
status: partial
---

# Phase 18: Code Review Fix Report

**Fixed at:** 2026-10-19
**Source review:** `.planning/phases/18-user-data-stream-error-taxonomy/18-REVIEW.md`
**Iteration:** 1

The review has three parts (src/scripts/config, tests A, tests B) and finding ids repeat across
them, so every id below is written `<part>/<id>` (`src`, `tests-A`, `tests-B`).

**Summary:**
- Findings in scope (Critical and Warning): 33 (src 14, tests-A 11, tests-B 8)
- Fixed: 26 (one of them, src/CR-02, only in part)
- Skipped: 7 (six `needs owner decision` or design, one not reproducible)

**Verification environment:** all gates ran in the main checkout (`workflow.use_worktrees` is
`false`), not in an isolated worktree. Per fix: the targeted tests, `uv run ruff check`,
`uv run ruff format --check` and `uv run mypy src` (clean after every commit). `TEST_DATABASE_URL`
is set in this shell but the PostgreSQL server did not answer (tests hung at setup), so every
PostgreSQL-backed test was run with the variable unset and **skipped**. That includes the PG
modules that use the stateful exchange fake changed by tests-A/WR-09 and
`tests/test_persistence_exit_evidence_pg.py`; they need a run with a reachable database.
One full run at the end (`uv run pytest -m "not docker" -x`, `TEST_DATABASE_URL` unset, main
checkout): all tests reached 100 percent with exit code 0, no failure; `ruff check`,
`ruff format --check` (631 files) and `mypy src` (202 files) are clean.

## Fixed Issues

### src/CR-01: A position row with a missing `positionAmt` is read as flat

**Files modified:** `src/adapters/binance_usdm.py`, `tests/test_adapter_strictness.py`
**Commit:** ef90072
**Status:** fixed: requires human verification (a fail-closed condition)
**Applied fix:** `_row_to_position_snapshot` raises `ValueError` when `positionAmt` is missing and
when it is not finite, instead of producing `Decimal(0)`. Tests: a row with `position_amt=None`
raises; a signed and a zero amount still project. Not changed: `entry_price`,
`break_even_price` and `un_realized_profit` still default to `0` when absent (the orchestrator
scoped the fix to `positionAmt`; those three do not feed the flat decision).

### src/CR-02 (part): The stream can be LIVE with no working subscription

**Files modified:** `src/adapters/binance_userdata.py`, `src/adapters/binance_userdata_supervisor.py`,
`tests/test_userdata_supervisor.py`, `tests/test_user_data_smoke_dry_run.py`
**Commit:** f41cb79
**Status:** fixed in part: requires human verification
**Applied fix (the part that needs no decision):** `UserDataAdapter.rebuild()` now proves the
stored listenKey with a keepalive before resubscribing it, and a `ListenKeyInvalid` answer starts
a new key (as `rekey` does). The supervisor gates the rebuild (`_gated_rebuild`), so a pause or ban
is respected. Tests: the rebuild issues one keepalive; an expired key starts a second key and
the old name leaves the SDK stream map; a rebuild waits out a 429 pause. One existing dry-run
expectation changed from 2 to 3 keepalive calls (the rebuild after the forced drop).
**Not changed (see Skipped):** the SUBSCRIBE acknowledgement check, treating an `error` event after a
subscribe as a failed subscription, and the `stream_is_stale` verdict with the ratified
`max_liveness_age_seconds = "none"`.

### src/WR-04: A failing sink silently loses a fill, a status hint or an algo update

**Files modified:** `src/adapters/binance_userdata_router.py`, `tests/test_userdata_router.py`
**Commit:** ed749e1
**Status:** fixed: requires human verification
**Applied fix:** a raising sink (other than the divergence sink itself) now also emits a
`StreamDivergence` of the new kind `SINK_FAILURE` (sink name, order or algo identity, payload hash,
no exception text). A lost ALGO_UPDATE is no longer added to the seen set, so a redelivery is routed
again. Three existing expectations about the divergence list were updated; new tests cover the
divergence and the redelivery. Phase 20 has to map the new kind.

### src/WR-05: A crashed supervisor task is only logged; the stream stays LIVE

**Files modified:** `src/adapters/binance_userdata_supervisor.py`, `tests/test_userdata_supervisor.py`
**Commit:** f5d9203
**Status:** fixed: requires human verification
**Applied fix:** `_task_done` halts the supervisor (`TASK_DIED`: state UNKNOWN, `on_failure`) when a
pump, timer or control task ends with an exception and the supervisor is not stopping, and releases a
pending `start()`. The new test makes the keepalive timer crash and fails without the fix. A
dead control task still needs a new supervisor (a resync cannot run without it).

### src/WR-06: `start()` and `stop()` leak a listenKey and leave a dirty client

**Files modified:** `src/adapters/binance_userdata.py`, `tests/test_userdata_adapter.py`
**Commit:** 6b42f02
**Status:** fixed: requires human verification
**Applied fix:** `start()` keeps the key before the connect, so `stop(close_listen_key=True)` can
still DELETE it; the transport `connect` replaces a client that a failed attempt left connections
on; `stop()` attempts the DELETE in a `finally` and marks the adapter stopped only after the
transport closed. Three tests, each failing without the fix. **Not changed:** the epoch still
increments after the connect, because the supervisor treats the SDK's immediate `open` event during a
connect as stale by its old epoch.

### src/WR-07: The sweeper journals SDK exception text and misreports a successful cancel

**Files modified:** `src/reconcile/sweeper.py`, `tests/test_phase8_audit_reviewfix.py`
**Commit:** fa04481
**Applied fix:** failure events carry the exception type only (`probe_failed: <Type>`,
`cancel_failed: <Type>`); the post-image write is outside the cancel `try`, so a post-image failure
records `post_image_failed` and the orphan still counts as cancelled; failure-event writes are
best effort, so one journal error cannot end the sweep. Four tests.

### src/WR-09: `get_position_mode` turns a missing `dualSidePosition` into one-way

**Files modified:** `src/adapters/binance_usdm.py`, `tests/test_binance_usdm_error_routing.py`
**Commit:** d9bc922
**Applied fix:** a non-bool `dualSidePosition` raises `ValueError` instead of reading as ONE_WAY.

### src/WR-11: `SdkNoiseGuard` lets a listenKey-bearing SDK ERROR line through

**Files modified:** `src/adapters/binance_userdata.py`, `tests/test_userdata_adapter.py`
**Commit:** f8ed918
**Applied fix:** for SDK records at WARNING and above the guard replaces the message with its
scrubbed text (and clears the args), so the redaction no longer depends on each handler carrying a
filter. The test uses a handler without `RedactingFilter` and fails without the fix.

### tests-A/WR-01: Always-true assertion in the unregistered-handler test

**Files modified:** `tests/test_demo_probe_cases.py`
**Commit:** 3017f95
**Applied fix:** the `or` branch is gone; the test asserts the final account re-read (the last four
port calls) and the cleanup `remaining` block.

### tests-A/WR-02: Probe port fakes not bound to the `ProbePort` protocol

**Files modified:** `tests/probe_fakes.py`, `tests/test_demo_probe_cases.py`
**Commit:** de8c3d6
**Applied fix:** the three order methods of `FakeProbePort` and `RecordingProbePort` have the
protocol's explicit keyword-only signatures; a conformance test compares parameter name, kind and
default presence of every `ProbePort` method against both fakes and against `BinanceProbeAdapter`.
The fake now refuses an order for another symbol, and a reducing market order shrinks only a
position of the opposite side by its quantity.

### tests-A/WR-03: The probe SDK contract test leaves the two public reads unbound

**Files modified:** `tests/test_binance_probe_contract.py`
**Commit:** 43afd6a
**Applied fix:** `mark_price` and `symbol_filters` are in the recorded operations with scripted
payloads; the recorded-method set is the signed methods plus the two public reads; the plain-string
`interval` is a named, commented exception (the installed SDK copies it into the payload).

### tests-A/WR-04: Record parsing at import time

**Files modified:** `tests/test_binance_client_config.py`
**Commit:** e04e1e6
**Applied fix:** the DEMO streams URL is read inside the test; a `NOT_CONFIGURED` record skips that
one case.

### tests-A/WR-05: A test depends on the working directory

**Files modified:** `tests/test_binance_limits_ratified_file.py`
**Commit:** 48506dd
**Applied fix:** `load_binance_limits(LIMITS_FILE)`. Checked by running the module from `tests/`.

### tests-A/WR-07: The AST guards have bypasses

**Files modified:** `tests/support/ast_guards.py`, `tests/test_ast_guards.py` (new),
`tests/test_binance_usdm_source_guard.py`, `tests/test_binance_usdm_signed_calls.py`,
`tests/test_demo_probe_cases.py`, `tests/test_demo_probe_cli.py`
**Commit:** 6f73e5b
**Applied fix:** `wall_clock_calls` resolves import aliases and sees `loop.time()` and
`asyncio.get_running_loop().time()`; `message_text_reads` follows `except ... as name` and
exception-annotated parameters and flags `repr`, `format`, `.args`, `.msg`, `getattr(..., "error_message")`
and f-string interpolation outside logger calls; the send guard flags an alias of `rest_api` and
`getattr(<...>.rest_api, name)`; `_function_nodes` keys by qualified name; the probe CLI time guard
resolves `import ... as` and `from datetime import datetime as DT`. Each new rule has a negative
control; the real `src` and `scripts` files pass the stricter rules unchanged.

### tests-A/WR-08: The cancel-retry ceilings are not asserted

**Files modified:** `tests/test_binance_usdm_error_routing.py`
**Commit:** 7a9ad53
**Applied fix:** each recorded wait must lie between zero and its exponential bound capped at the wait
ceiling (the wait is `wait_random_exponential`, so a literal schedule such as `[1, 2]`, which the
review suggested, would be wrong); the four constants are pinned to 3, 30, 1 and 10; a far attempt
never exceeds the cap.

### tests-A/WR-09: The stateful exchange fake returns a different shape than the real adapter

**Files modified:** `tests/support/fake_binance_exchange.py`, `tests/test_fake_binance_semantics.py`
**Commit:** 391d6f5
**Applied fix:** the fake returns `EntryPlacementResult` and `AlgoPlacementResult`, and the query
`update_time_utc` moves on fill and cancel. **Not changed:** the manager's `order_id` fallback stays,
because other fakes (`tests/test_execution_manager.py`, `tests/test_execution_attach.py`) still answer
with dicts. The PG modules that use this fake were skipped (no database).

### tests-A/WR-10: Two refusal tests pass for any failure of the right type

**Files modified:** `tests/test_binance_limits.py`, `tests/test_binance_secret_redaction.py`
**Commit:** d2f09bf
**Applied fix:** the limits test keeps every other table valid and asserts the exact
`stream (must be a table)` text; the credential test asserts the variable name, the word
`repository` and that neither path nor file name is echoed.

### tests-A/WR-11: Tests whose names claim more than they check

**Files modified:** `tests/test_binance_ratelimit_gate.py`, `tests/test_demo_probe_evidence.py`,
`tests/test_demo_rehearsal_safety.py`
**Commit:** 1790147
**Applied fix:** a real eight-thread test on one gate; the status test is parametrized over all five
statuses; the live-orders test runs the rehearsal tracer and asserts nothing mutating was sent and
no enablement record exists.

### tests-B/WR-01: `test_connection_listener_failure_never_reaches_the_sdk` cannot fail

**Files modified:** `tests/test_userdata_adapter.py`
**Commit:** 348bb27
**Applied fix:** the test asserts the `userdata.connection_listener_failed` log entry; new tests call
the adapter and transport guards with no fake in the path and cover the connection sink, message sink
and enqueue branches.

### tests-B/WR-02: The Windows backslash branch is untested

**Files modified:** `tests/test_userdata_adapter.py`
**Commit:** d9a6b08
**Applied fix:** guard and bridge tests with backslash SDK pathnames (both SDK package markers) and a
foreign backslash path as the negative control.

### tests-B/WR-03: `test_phase18_evidence_is_reported_not_required` is a tautology

**Files modified:** `tests/test_phase18_gate.py`
**Commit:** cdb0340
**Applied fix:** presence is still only reported; the test now checks that the list has no duplicates,
does not overlap the required list, and holds relative paths under `.planning/` or `tests/fixtures/`.

### tests-B/WR-04: The unratified-default scan is bypassed by upper-case constants and positional arguments

**Files modified:** `tests/test_no_unratified_defaults.py`
**Commit:** 8aff92b
**Applied fix:** names are compared in lower case; a positional number given to one of the six limits
classes is reported; scanner self-tests for the new forms. No violation exists in `src` or `scripts`.

### tests-B/WR-05: Tests hard-require `.planning/` artifacts that GSD archives or strips

**Files modified:** `tests/test_phase18_gate.py`, `tests/test_sources_phase18_section.py`,
`tests/test_fake_binance_semantics.py`
**Commit:** 67333a3
**Applied fix:** the planning-dependent tests skip with a reason when the phase directory (or the
probe check file) is absent; the artifact inventory requires `.planning/` entries only while the
directory exists. **Not changed:** `test_invariant_8_d055_stays_open` (it fails the day D055 is closed)
and copying pinned evidence text into `tests/fixtures/phase18/`.

### tests-B/WR-06: `ROUTER_PATH` is relative to the working directory

**Files modified:** `tests/test_userdata_rig.py`
**Commit:** d0157e4
**Applied fix:** anchored on `Path(__file__).resolve().parents[1]`; run from `tests/` to check.

### tests-B/WR-07: The recorded-fixtures refusal test targets the real committed directory

**Files modified:** `tests/test_user_data_smoke_dry_run.py`
**Commit:** 00bef88
**Applied fix:** the module constant is monkeypatched to a stand-in directory under `tmp_path`; the
refusal is tested for the root, a sub-directory, a `..` spelling, a relative spelling (via chdir) and a
symlink (skipped on this Windows host); the stand-in must stay empty.

### tests-B/WR-08: The smoke evidence tests run without the no-network and no-sleep guard

**Files modified:** `tests/support/net_guard.py` (new), `tests/test_user_data_smoke_dry_run.py`,
`tests/test_user_data_smoke_evidence.py`
**Commit:** 9770c04
**Applied fix:** the guard is one shared function; the dry-run module uses it instead of its own copy
and the evidence module applies it (a `MonkeyPatch.context()` around the module-scoped dry run). The
CLI module keeps its own, different guard (it also blocks the SDK constructor).

## Skipped Issues

### src/CR-02 (remainder): SUBSCRIBE acknowledgement, error-after-subscribe, liveness verdict

**File:** `src/adapters/binance_userdata.py:539-558`, `src/adapters/binance_userdata_supervisor.py:585-590`,
`config/binance/binance-limits-v1.toml`
**Reason:** needs owner decision. `max_liveness_age_seconds = "none"` is a ratified value that cannot
be changed here, and `stream_is_stale` is unused by production code. The SUBSCRIBE acknowledgement
check (`LIST_SUBSCRIPTIONS`) rests on SDK internals that no live run has observed, so it cannot be
confirmed from the source alone.
**Original issue:** the SDK's SUBSCRIBE is fire-and-forget, so a stream can be LIVE with no
subscription.

### src/WR-01: The supervisor retries listenKey and snapshot calls after a 429

**File:** `src/adapters/binance_userdata_supervisor.py:285-287`, `:644-667`, `:794-833`
**Reason:** needs owner decision. The recorded amendment of 2026-10-16 says no call is retried because
of a 429, while the supervisor design (plan 18-14) deliberately waits out a pause and sends the call
again without consuming an attempt. Which of the two governs the supervisor's own recovery calls is a
429 retry policy question, and the fix changes tested supervisor behavior.
**Original issue:** `_retryable` retries `ListenKeyTransient(RATE_LIMITED)` and snapshot 429s.

### src/WR-02: The execution manager ignores the error taxonomy and retries a placement

**File:** `src/execution/manager.py:181`, `:201-254`, `:773-806`
**Reason:** needs owner decision. The second `place_entry` only happens after a probe by client id
reports definitive absence (the orchestrator confirmed this), and removing it or splitting pre-send
refusals from ambiguous answers changes the Phase 9 no-blind-retry design and the ENTRY_ABSENT and
SAFE_MODE outcomes. The test review (tests-B/IN-06) places the taxonomy wiring in Phase 19.
**Original issue:** every exception from `place_entry` is treated as ambiguous.

### src/WR-03: Out-of-order events cannot be ordered downstream

**File:** `src/adapters/binance_userdata_router.py:210-217`, `:550-557`, `:409-420`;
`src/persistence/entities.py:465-516`
**Reason:** needs owner decision. A monotonic status guard needs the event time stored (a column or
journal field, so a schema migration) and consumers in Phases 19 and 20; it is a design change, not a
local fix.
**Original issue:** `ExchangeStateUpdate` carries processing time; a late event overwrites a newer status.

### src/WR-08: HTTP `ClientError` is classified STATUS_UNKNOWN and therefore retryable

**File:** `src/domain/exchange_errors.py:570-581`, `:609-625`
**Reason:** needs owner decision. The class rule `CLIENT_OTHER -> STATUS_UNKNOWN` is part of the
recorded HTTP-class rules (plan 18-05, "other 4xx (408)") and is pinned by
`tests/test_exchange_errors.py` and `tests/test_sdk_error_mapping_contract.py`; changing the taxonomy is
a decision.
**Original issue:** every unhandled 4xx is retried as status-unknown.

### src/WR-10: Rate-limit response headers are never read

**File:** `src/adapters/binance_usdm.py:649-677`, `src/adapters/binance_public.py:281-298`,
`src/adapters/binance_probe.py:604-629`, `src/adapters/binance_userdata.py:234-254`
**Reason:** needs owner decision. A proactive pause needs a ratified fraction of the weight and
order-count limits, i.e. a new key in the limits file.
**Original issue:** the gate is purely reactive.

### src/WR-12: A 429 pause blocks protective placement and entry cancel

**File:** `src/adapters/binance_ratelimit_gate.py:1-30`, `:128-150`; `src/execution/manager.py:858-905`
**Reason:** needs owner decision. The fix is either a reduce-risk exemption from the pause or a durable
pending-cancel record, both new decisions; the review itself says to keep the decision and record the
choice in DECISIONS.
**Original issue:** during a pause the stop and the entry cancel are refused and the entry can fill
unprotected.

### tests-A/WR-06: Global logging state is reconfigured with no teardown

**File:** `tests/test_binance_secret_redaction.py:34-40, 246-251, 318-321`
**Reason:** not reproducible: `tests/conftest.py::_restore_logging_state` is an autouse fixture that
already restores structlog, the root handlers, filters, level and the excepthooks after every test, so
the stale-buffer scenario cannot occur. A teardown added to the module was tried and reverted.
**Original issue:** `configure_logging` leaves a stale handler and structlog configuration behind.

---

_Fixed: 2026-10-19_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
