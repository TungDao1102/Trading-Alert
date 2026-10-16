---
phase: 18-user-data-stream-error-taxonomy
plan: 15
subsystem: adapters/user-data-stream
status: complete
tags: [router, user-data-stream, ORDER_TRADE_UPDATE, ALGO_UPDATE, ACCOUNT_UPDATE, fill-totals, replay, EXEC-05, EXEC-02, D-05, D-06, D-07, D-08, D-21, T-18-43, T-18-44, T-18-45, T-18-46, T-18-77]
requires: [18-03, 18-06, 18-08, 18-11, 18-14]
provides:
  - src/adapters/binance_userdata_router.py (UserDataRouter, KnownOrder, OrderLookup, JournalRecorder, TrustedItem, FillTotalsTracker, RouteResult, RoutedFill, FillSource, ExchangeStateUpdate, OrderStatusHint, AlgoRoute, StreamDivergence, StreamDivergenceKind, ALGO_STATUS_DIAGNOSTIC, ACCOUNT_CONFIG_HINT, ROUTER_SINK_FAILURE, TERMINAL_NOT_FILLED_STATUSES)
  - tests/support/stream_sinks.py (RecordingSinks, RecordingJournal, FakeOrderLookup, make_router, SINK_NAMES)
  - tests/test_userdata_rig.py, tests/test_userdata_router.py, tests/test_userdata_replay.py
affects:
  - Phase 20 (maps StreamDivergence onto the reconciler's closed divergence vocabulary; wires the status hint, exchange-state update and ExitEvidence into persistence; liveness)
  - Phase 24 (process wiring: supervisor on_event bound to router.route, real sinks, PgJournalStore as the journal)
  - plans 18-18 / 18-20 / 18-21 (live smoke, probe and recorded frames may refine the ALGO_UPDATE lifecycle key and the child-order identity of a triggered algo order)
tech-stack:
  added: []
  patterns:
    - every outcome handed to an injected plain-callable sink; sinks isolated by a try per call, the journal never isolated (fail closed)
    - journal ids remembered per router instance only after the journal accepted them, so a redelivery after a journal failure is not lost
    - ALGO_UPDATE lifecycle key without is_activated and the event/transaction times; duplicates counted, never routed
    - accumulated-quantity check only on the largest z seen per order; REST fills fallback once per (order, z)
    - deterministic fingerprints (canonical JSON of type and fields, Decimal and datetime as text)
key-files:
  created:
    - src/adapters/binance_userdata_router.py
    - tests/support/stream_sinks.py
    - tests/test_userdata_rig.py
    - tests/test_userdata_router.py
    - tests/test_userdata_replay.py
  modified: []
decisions:
  - "The fill sink receives RoutedFill(fill, source, after_gap) rather than a bare FillEvent, so the gap flag and the source (USER_DATA_EVENT or REST_FALLBACK) reach the consumer; fold_fills consumes RoutedFill.fill"
  - "route() accepts a structural TrustedItem Protocol (outcome, received_at_utc, after_gap) instead of importing TrustedEvent, keeping the router's imports to the plan's list (the supervisor module pulls in the SDK); TrustedEvent satisfies it"
  - "The router remembers the journal ids it wrote in its session and does not re-send a duplicate: stream_anomaly_event puts the observation time in the payload, and PgJournalStore raises JournalConflict for the same id with a different payload"
  - "An unknown algo id is journaled as an UNKNOWN_ORDER anomaly (field o.caid) and surfaced as UNKNOWN_STREAM_ALGO; its payload hash is taken over the lifecycle key, not the whole event"
  - "The ALGO_STATUS_DIAGNOSTIC is written for known and unknown algo ids whenever rm is present; its payload carries no time, so a replay in the same session never conflicts"
  - "A newest-first TRADE (z larger than the unique sum because older trades are still in flight) is reported as FILL_TOTAL_MISMATCH and answered by the REST fallback; the plan only exempts older events, and the replay test proves the view is unchanged"
  - "No journal record links order_id (a foreign key to orders): the local order id travels in the sink records instead, so a journal write can never fail on a missing parent row"
metrics:
  duration: "about 12 minutes of execution (2026-10-16T07:30Z to 07:42Z)"
  completed: 2026-10-16
  tasks: 3
  files: 5
estimate:
  tokens: 100000
  tasks: 3
actuals:
  tokens: 24450
  tasks: 3
  commits: 3
plan_head_before: dd5f288fad241c608a0090b422d8e4d8f2649748
plan_head_after: 70db815e93ec165cccb990c1dd15913f3b3934ab
---

# Phase 18 Plan 15: User-data event router Summary

`UserDataRouter` turns every trusted stream outcome into a destination: stream TRADEs of known orders become `FillEvent`s for the unchanged `fold_fills`; known-order updates become an exchange-state update and a status hint with `USER_DATA_EVENT` evidence; ALGO_UPDATEs are de-duplicated per lifecycle update and routed with their ratified class; ACCOUNT_UPDATE deltas pass through unchanged. Every surprise is journaled with a deterministic id and surfaced as a `StreamDivergence`. A replay rig proves that 30 delivery orders, replays and a dropped frame all give the same position view.

Plan revision: revised 2026-10-16 to de-duplicate the trailing-stop ALGO_UPDATE pair (`ia` false, then true) per the Binance change log of 2026-08-21. That fact is a WebFetch summary and has not been verified live; the smoke or the probe may refine the lifecycle key.

All frames in these tests are SYNTHETIC (`FRAME_LABEL = "SYNTHETIC_FROM_SDK_MODEL"`). The SDK-shaped messages are built from the installed SDK 17.4.0 models. Passing these tests is not evidence of how live Binance frames behave.

## Task Commits

| Task | Name | Commit | Files |
|---|---|---|---|
| 1 (tracer) | SDK-shaped TRADE frame through adapter, supervisor and router to a folded position view | 2d70117 | src/adapters/binance_userdata_router.py, tests/support/stream_sinks.py, tests/test_userdata_rig.py |
| 2 | Router completeness: fill totals, status hints with evidence, algo routing with class and rm diagnostic, account deltas, anomalies and divergences | 7a79c57 | src/adapters/binance_userdata_router.py, tests/support/stream_sinks.py, tests/test_userdata_router.py |
| 3 | Replay proof: reorder, duplicate and replay give one position view; key-space negative control | 70db815 | tests/test_userdata_replay.py |

The ledger range `dd5f288..70db815` holds exactly these 3 commits. The parallel executor of plan 18-16 had committed nothing on the branch by then.

## What Was Built

- **Router (`src/adapters/binance_userdata_router.py`).**
  - **Construction.** `UserDataRouter(*, order_lookup, journal, session_id, clock, fill_sink, status_hint_sink, exchange_state_sink, algo_sink, account_sink, divergence_sink, fills_fallback)`. Every argument is keyword-only and required. The session id must be non-empty and at most 128 characters.
  - **Return value.** `route(item)` returns a frozen `RouteResult` with `handled`, `kind` and counters: fills, fallback calls and fills, exchange states, status hints, algo routes, account events, config hints, diagnostics, anomalies, divergences, `duplicate_algo_updates`, `listen_key_expired`, `ignored` and `sink_failures`. It never raises, except when the journal fails.
- **Order updates.**
  - **Unknown client order id.** The router produces no fill and no state. It journals an UNKNOWN_ORDER anomaly (field `o.c`, no client id in the payload) and emits an `UNKNOWN_STREAM_ORDER` divergence.
  - **Known order.** The router sends `ExchangeStateUpdate(local_order_id, exchange_status, exchange_order_id, now_utc=clock())`. It also sends `OrderStatusHint` with `ExitEvidence(USER_DATA_EVENT, reference "<x>:<i>:<t or none>", correlation_id=session)`, marked `terminal_not_filled` for CANCELED, EXPIRED and EXPIRED_IN_MATCH. A TRADE with a positive `l` also produces a `RoutedFill`.
- **`FillTotalsTracker`.**
  - **Check.** When an event's `z` is at least the largest seen and differs from the sum of the unique `l` values, the router journals FILL_TOTAL_MISMATCH and emits `STREAM_FILL_TOTAL_MISMATCH`. It then calls `fills_fallback(order_id)` once per (order, z). The returned REST fills go to the fill sink as `REST_FALLBACK` and are added to the tracker.
  - **Older events.** An event older than the largest `z` seen is never checked.
- **ALGO_UPDATE.**
  - **De-duplication.** The lifecycle key is (caid, aid, X, ai, aq, rm). A second event with the same key goes nowhere and counts 1 in `duplicate_algo_updates`.
  - **Unknown id.** An unknown id gives an anomaly (field `o.caid`) and an `UNKNOWN_STREAM_ALGO` divergence.
  - **Known id.** A known id gives an `AlgoRoute` with `classify_algo_status`. A TERMINAL_FAILED class also gives a `STREAM_ALGO_TERMINAL_FAILED` divergence.
  - **`rm` diagnostic.** `rm` gives an `ALGO_STATUS_DIAGNOSTIC` journal record: scrubbed through `src.ops.redaction.scrub` and capped at 200 characters. Its id is deterministic per (session, algo id, status, reason sha256).
- **Account and other events.**
  - **ACCOUNT_UPDATE.** The event reaches the account sink as the same object. Nothing is computed from it.
  - **ACCOUNT_CONFIG_UPDATE.** It is journaled as an `ACCOUNT_CONFIG_HINT` with symbol, leverage and multi_assets as text.
  - **listenKeyExpired and ignored events.** They only increase counters.
- **Anomalies.**
  - **StreamAnomaly outcomes.** Every one is journaled through `stream_anomaly_event`, with the session id as the correlation. It is surfaced as a `STREAM_ANOMALY` divergence carrying the kind, the payload hash and `after_gap`.
  - **Unexpected objects.** An object that is not a stream outcome is journaled as UNRECOGNIZED_ENVELOPE and surfaced, with `handled=False`.
- **Failures.**
  - **Failing sink.** A raising sink is journaled as a `ROUTER_SINK_FAILURE` record. The record holds the sink name and the exception type, never the message. Routing then continues with the next sink.
  - **Failing journal.** The router re-raises. Journal ids, the ALGO_UPDATE key and the reported (order, z) are remembered only after the journal accepted the record, so a redelivery is handled in full.
- **Test fakes (`tests/support/stream_sinks.py`).**
  - `RecordingSinks` has one list per sink, a configurable REST fallback and named failing sinks.
  - `RecordingJournal` mirrors `PgJournalStore`. A replay of an identical record is a no-op. The same id with a different payload raises `JournalReplayConflict`.
  - `FakeOrderLookup` answers lookups from dicts, and `make_router` builds a router over the fakes.

## Verification

All commands ran as `UV_OFFLINE=1 uv run --frozen --extra dev ...`. The suite ran only on targeted files; the full suite was not run.

- **Task 1 verify** (rig plus supervisor files): 47 passed. Red first: `ModuleNotFoundError` for the router module.
- **Tracer feedback gate.** The verify is automated only. It was re-run after the commit and passed, and expansion continued.
- **Task 2 verify** (router plus rig files): 85 passed. Red: the test file run against the Task 1 module fails with `ImportError: cannot import name 'ACCOUNT_CONFIG_HINT'`.
- **Mutation check.** With `is_activated` added to the ALGO_UPDATE lifecycle key, 4 tests fail: both orders of the trailing-stop pair, the TERMINAL_FAILED pair and the unknown-algo pair. The source was restored from a scratch copy afterwards.
- **Task 3 verify** (replay, partials and attach files): passed. `test_execution_partials.py` and `test_execution_attach.py` are unchanged.
- **Plan verification and acceptance set.** The events, parsers, router, rig, replay and supervisor files, plus partials and attach, ran together: 535 passed. Tests per file:

  | File | Tests |
  |------|-------|
  | `test_userdata_router.py` | 79 |
  | `test_userdata_rig.py` | 6 |
  | `test_userdata_replay.py` | 9 |

- **`mypy src`:** no issues in 199 source files.
- **`ruff check`.** It reports 1 finding, E501 in `src/ops/operator_evidence.py:73`. **`ruff format --check`** reports 2 files to reformat: `src/ops/operator_evidence.py` and `tests/test_operator_evidence.py`. All three findings are in uncommitted files of the parallel plan 18-16, which this plan does not touch. Run on this plan's five files only, both commands pass.
- **`uv lock --check`:** resolved, unchanged.
- **Plan acceptance points.**
  - The rig asserts the LIVE fill once with `after_gap=False`, and the gap fill once with `after_gap=True` after the second snapshot. While the snapshot was running, the fill sink still held only the first fill. The folded view equals the plain-order view, and `asyncio.sleep` was never called.
  - The AST guards find no `src.persistence`, `src.paper` or `binance*` import, no wall-clock read and no `float()` in the router. Its `src` imports are limited to the event module, the fill monitor, `src.domain.*` and `src.ops.redaction`.
  - The listenKey test routes four frames carrying `SYNTHETIC_LISTEN_KEY`: one valid, one with E missing, one with a mistyped E and one with an unknown event name. The key does not appear in any sink record, journal call, payload or `RouteResult` repr.
  - The five named ALGO_UPDATE de-duplication tests exist and pass. A sixth test pins that a TRIGGERED update carrying `ai`/`aq` is a new lifecycle update.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Duplicate anomaly frames would have failed against the real journal**
- **Found during:** Task 2.
- **Issue:** `stream_anomaly_event` (plan 18-08) keeps the id stable but puts `observed_at_utc` in `payload_json`. `PgJournalStore.append` compares `payload_json` on a replay, so the same frame received at a different time raises `JournalConflict`. Because the router re-raises journal failures, every duplicate anomalous frame would have halted routing.
- **Fix:** the router writes each journal id at most once per instance (one session), and only after the journal accepted it. `RecordingJournal` reproduces the conflict, and `test_the_same_anomaly_twice_in_a_session_is_one_journal_record` receives the duplicate 9 s later.
- **Files:** `src/adapters/binance_userdata_router.py`, `tests/support/stream_sinks.py`.
- **Commit:** 7a79c57.

**2. [Rule 2 - Correctness] Redelivery after a journal failure is not lost**
- **Issue:** the de-duplication state (ALGO_UPDATE key, reported (order, z), journal ids) is set only after the journal accepted the record. Otherwise a journal failure would have turned the redelivered frame into a "duplicate".
- **Tests:** `test_a_failing_journal_is_re_raised_and_nothing_is_lost` and `test_a_failing_journal_on_an_algo_update_leaves_the_lifecycle_key_unseen`.
- **Commit:** 7a79c57.

**3. [Rule 3 - Blocking] Sink record shapes**
- **Issue:** the plan names a fill sink "receiving a FillEvent with after_gap". A `FillEvent` has no gap flag.
- **Fix:** the sink receives `RoutedFill(fill, source, after_gap)`. The exchange-state sink receives a frozen `ExchangeStateUpdate` instead of a tuple.
- **Commit:** 2d70117.

**4. [Rule 3 - Blocking] `route` typed against a structural `TrustedItem` Protocol**
- **Issue:** importing `TrustedEvent` from the supervisor would pull `binance_userdata` and the SDK into the router. That would break the plan's import list.
- **Fix:** `TrustedEvent` satisfies the Protocol structurally, and every test passes real `TrustedEvent` objects.
- **Commit:** 2d70117.

**5. [Rule 2 - Hardening] Extra guards beyond the plan**
- **Validation and fail-closed handling:**
  - Fallback results must be `FillEvent`s; anything else is recorded as a `fills_fallback` sink failure.
  - The session id is length-capped.
  - An unexpected non-outcome object is journaled and surfaced instead of being ignored.
  - The sink-failure detail holds the exception type only.
- **Extra tests:**
  - "dropped latest frame is invisible to the total check" pins the documented limit.
  - The replay file checks itself with an AST guard: no clock, no random, no network import.
- **Commit:** 7a79c57 and 70db815.

### Interpretation notes

- **Newest-first TRADEs.** A TRADE whose `z` is ahead of the unique sum because earlier trades have not arrived yet is reported as a mismatch and answered by REST. The plan exempts only events older than the largest `z`. In the permutation test, many of the 30 orderings take this path, and the view is identical in all of them.
- **Anomaly divergences.** Each delivery of an anomalous frame still emits a divergence, while the journal record is written once. The plan requires one journal record per duplicate anomaly; only ALGO_UPDATE de-duplication requires one divergence.
- **Test class names.** `TestOnlySinkFailure` and `TestOnlyJournalFailure` were renamed to `InjectedSinkFailure` and `InjectedJournalFailure` before commit, because pytest tries to collect `Test*` classes.

## Known Stubs

None.

## Threat Flags

None. The router adds no endpoint, credential path or schema. The journal event types ALGO_STATUS_DIAGNOSTIC and ACCOUNT_CONFIG_HINT are new text values in the existing `journal_events` table; they add no column or migration. The threats are mitigated as the register states:
- **T-18-43:** unknown ids create no state, and the z check calls the REST fallback.
- **T-18-44:** covered by the permutation, replay and key-space controls.
- **T-18-45:** `rm` is scrubbed and capped, anomaly records carry hashes and field names, and the listenKey test passes.
- **T-18-46:** every anomaly and sink failure is journaled, and a failing journal re-raises.
- **T-18-77:** covered by the five named tests plus the mutation check.
- **T-18-SC:** no package was installed or changed.

## Open Issues

- **Triggered algo orders.** The child ORDER_TRADE_UPDATE of a triggered protective order has a client order id the lookup may not know (research P14). Until the probe records `c` and `i` of the child, each such update becomes an UNKNOWN_ORDER anomaly with an `UNKNOWN_STREAM_ORDER` divergence. This fails closed but is noisy. Phase 20's lookup (by `ALGO_UPDATE.ai`) or the probe should settle it.
- **Anomaly journal ids.** They stay stable within a session through the router's memory, but `stream_anomaly_event`'s payload still carries the observation time. A second router built with the same session id, for example after a process restart that reuses the id, would hit `JournalConflict` on a duplicate anomaly. Phase 20/24 wiring should give every router instance a fresh session id, or plan 18-08's payload should be revisited.
- **ALGO_UPDATE lifecycle key.** The key follows the change-log summary of 2026-08-21 and is not verified live. The smoke (18-18) or the probe (18-20) may show that other fields differ between the two events of a pair; for example, `tt` or `ap` might be set on the second.
- **Untouched files.** STATE.md, ROADMAP.md, REQUIREMENTS.md and DECISIONS.md were not updated, as the orchestrator instructed. `.planning/config.json` (modified) and the 18-16 files `src/ops/operator_evidence.py` and `tests/test_operator_evidence.py` (untracked) were left alone.

## Self-Check: PASSED

- FOUND: src/adapters/binance_userdata_router.py, tests/support/stream_sinks.py, tests/test_userdata_rig.py, tests/test_userdata_router.py, tests/test_userdata_replay.py
- FOUND commits: 2d70117, 7a79c57, 70db815
