---
base: efc41c691622877e9300257e73d6a159a6cf0310
phase: 18-user-data-stream-error-taxonomy
plan: 10
subsystem: adapters/binance-usdm, adapters/binance-public, adapters/rate-limit-gate
status: complete
tags: [binance, error-taxonomy, rate-limit, 418, 429, cancel-retry, placement, EXEC-01, EXEC-02, D-10, D-11]
requires: [18-05, 18-07, 18-09]
provides:
  - src/adapters/binance_ratelimit_gate.py (RestRateLimitGate, RestGateRefusal, RateLimitBanActive, RateLimitPauseActive, GateRestriction)
  - BinancePublicMarketData(sdk_client=None, *, rest_gate=None) with a gate check before, and a 418/429 record after, each of its seven REST calls
  - BinanceUsdmAdapter(sdk_client=None, *, rest_gate=None, sleep=None); every REST call passes the gate; the inner public reader gets the same gate
  - taxonomy-routed absence (ORDER_ABSENT of QUERY or CANCEL) and cancel retry (STATUS_UNKNOWN only)
  - tests/test_binance_ratelimit_gate.py, tests/test_binance_usdm_error_routing.py, tests/test_binance_usdm_source_guard.py, tests/test_adapter_not_found_mapping.py (rewritten)
affects:
  - plan 18-12 (BinanceProbeAdapter takes the same gate instance)
  - plan 18-13 (composition creates the one gate; attach path turns a refused protective leg into an unprotected-position event; recvWindow)
  - plan 18-14 (SdkListenKeyPort takes the same gate instance)
  - plans 18-16, 18-17 (each composition creates exactly one gate)
tech-stack:
  added: []
  patterns:
    - one gated REST helper (`_gated_rest_call` in binance_public.py) used by both adapters, so no SDK REST call bypasses the gate (asserted: no `asyncio.to_thread(` left in binance_usdm.py)
    - SDK-shaped counting fakes with scripted exceptions, a virtual clock shared by gate and test, a recording sleep, and `asyncio.sleep` patched to fail
    - AST guards with one negative control per rule
key-files:
  created:
    - src/adapters/binance_ratelimit_gate.py
    - tests/test_binance_ratelimit_gate.py
    - tests/test_binance_usdm_error_routing.py
    - tests/test_binance_usdm_source_guard.py
  modified:
    - src/adapters/binance_usdm.py
    - src/adapters/binance_public.py
    - tests/test_adapter_not_found_mapping.py
    - tests/test_phase8_audit_reviewfix.py
decisions:
  - "The gate check runs inside the shared `_gated_rest_call`, immediately before each SDK send (every method, every cancel attempt), instead of as a separate first statement of each method; place_algo_protective's local argument validation (ValueError) therefore still runs first"
  - "`_gated_rest_call` and `_record_rate_limit` live in binance_public.py (an SDK-touching module) and binance_usdm.py imports them, because the gate module must stay free of SDK imports"
  - "A refusal's `retry_after_seconds` and `GateRestriction.until_utc`/`remaining_seconds` describe when REST opens again (the later of the active end times); the refusing class and `reason` follow the ban-first precedence"
  - "The cancel retry predicate keeps the name `_cancel_retry_predicate`; its body is `retry_eligible(classify(facts, CANCEL), CANCEL)` and a gate refusal is never retried"
metrics:
  duration: ~20min
  completed: 2026-10-16
  tasks: 3
  files: 8
actuals:
  tokens: 28400
  tasks: 3
  commits: 4
plan_head_before: efc41c691622877e9300257e73d6a159a6cf0310
plan_head_after: 538723781b6526317199b1f2be6211c151e78518
---

# Phase 18 Plan 10: Taxonomy-routed not-found and cancel, process-wide REST rate-limit gate Summary

An order is "absent" only when the taxonomy says ORDER_ABSENT for a QUERY or a CANCEL. A cancel is retried only for STATUS_UNKNOWN. Placement makes exactly one SDK call. One process-wide `RestRateLimitGate` turns a 418 into a REST ban and a 429 into a REST pause, and while either is active it refuses every REST call of every holder before the call is sent.

Plan revision: revised 2026-10-16 per `decisions/18-DEC-O-18-01.md` and its amendment of the same day. The revision added the process-wide gate (a 418 ban and a 429 pause for every REST call), dropped the bounded 429 cancel retry, limited the `_RECONCILER_CANCEL_*` constants to STATUS_UNKNOWN, and added the optional `rest_gate` of `BinancePublicMarketData`.

Known gap (restated): in Phase 18 the data jobs do not hold the gate. These are backfill, universe freeze and collector, which build `BinanceUsdmAdapter()` or `BinancePublicMarketData()` without one. The Phase 16 paper runtime and the scripts `paper_ws_smoke.py` and `shadow_rehearsal.py` are ungated too. All of them keep their existing rate-limit handling; universe freeze still retries rate-limit errors, including a ban (pre-existing). Gating them is left to the phases that compose those processes.

## What was built

- **Task 1 (tracer), commit 529fb48.** `_is_order_not_found_error` is now `_is_order_absent(exc, CallKind.QUERY)`, which calls `classify(error_facts_from_exception(exc), call_kind)`. The code set `_NOT_FOUND_CODES`, the regex `_NOT_FOUND_MESSAGE` and the `re` import are removed. `rate_limit_retry_after_seconds` now delegates to the shared SDK normalizer. The legacy test is reversed on purpose as `test_legacy_message_form_no_longer_maps_to_absent`. The re-raise matrix asserts that the exact same exception object comes back.
- **Task 2, commit 95392c9.**
  - **The gate.** The gate module is pure: stdlib, `src.domain.exchange_errors` and `RateLimitPolicy`, with an injected clock, a `threading.Lock`, end times that only move later, and no clearing method. Ban and pause lengths come only from the policy, through `rate_limit_decision`.
  - **Public reader.** `BinancePublicMarketData` takes an optional `rest_gate`.
  - **Order adapter constructor.** `BinanceUsdmAdapter` takes `rest_gate` and `sleep` as keyword-only arguments. Every SDK REST call goes through `_gated_rest_call`, with the call kind PLACEMENT, CANCEL, QUERY or TIME. The inner public reader shares the gate.
  - **Cancel.** The cancel retry uses tenacity with the four unchanged `_RECONCILER_CANCEL_*` ceilings and the injected `sleep`. ORDER_ABSENT is success and is logged with `error_class` and `code` only.
  - **Removed helpers.** `_is_already_canceled_message` and `_is_transient_reconcile` are gone.
  - **Docstrings.** One line was added to the SDK table for the constructor, and the constructor docstring was updated.
- **Task 3, commit 5387237.** An AST guard enforces four rules, each with a negative control:
  - the removed names stay removed;
  - there is no `re` import;
  - nothing reads `.error_message`, and nothing calls `str(exc|e|err|error|exception)` outside logger-call arguments; this covers both `binance_usdm.py` and `execution/manager.py`;
  - placement code has no loop, no await inside a loop and no tenacity.

  The guard found no violation in `src`, so `src` was not changed for Task 3.

## Verification

- Plan verification set, with `tests/test_phase8_audit_reviewfix.py` added: `uv run pytest -m "not docker"` on the gate, not-found, routing, source-guard, adapter-contract, reconcile, execution-manager, public, backfill and universe-freeze files gives **492 passed**.
- Per new or rewritten file:

  | File | Passed |
  |------|--------|
  | `test_binance_ratelimit_gate.py` | 65 |
  | `test_adapter_not_found_mapping.py` | 38 |
  | `test_binance_usdm_error_routing.py` | 177 |
  | `test_binance_usdm_source_guard.py` | 10 |
- Extra targeted regression (23 files that use the adapters, including demo rehearsal, drills, execution attach/emergency/gates, paper shadow runtime, no-unratified-defaults and SDK error mapping): **866 passed**.
- `uv run mypy src`: no issues, 195 source files.
- `ruff check` and `ruff format --check`: all checks pass on every file of this plan. Both commands also pass on the whole repository when the two files of the concurrent plan 18-11 are excluded (see Open issues).

## TDD gate compliance

- Task 1: the rewritten test failed first (6 failures, including the reversed legacy case). It passed after the taxonomy change.
- Task 2: the gate and routing tests failed first, with an ImportError and then constructor TypeErrors. They passed after the implementation.
- Task 3: the guard tests passed on first run on the real files; every negative control proves its rule matches a violation.

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 3 - Blocking] `tests/test_phase8_audit_reviewfix.py` WR-20 tests**
- **Found during:** Task 2.
- **Issue:** `test_wr20_transient_still_retries_programming_errors_do_not` asserted that `_cancel_retry_predicate(RuntimeError("timeout"))` is True. Under the taxonomy a non-SDK exception is UNKNOWN_EXCHANGE_ERROR and is never retried, which is exactly the plan's behavior.
- **Fix:** The test now asserts that `ServerError` and `NetworkError` are retried while `RuntimeError`, `ValueError` and `TypeError` are not. The already-canceled test also covers `BadRequestError(-2011)`. The intent of WR-20 is kept.
- **Files modified:** `tests/test_phase8_audit_reviewfix.py` (not in the plan's file list).
- **Commit:** 95392c9.

### Interpretation notes (no behavior beyond the plan)

- The gate check sits in the shared helper, immediately before each send (see the decisions above). The behavior asserted by the plan holds: no SDK call happens during a restriction, for every method and every cancel attempt.
- `rate_limit_retry_after_seconds` now returns None for a non-SDK exception that has a `retry_after` attribute, because the shared normalizer only reads the SDK 418 and 429 classes. The backfill, universe freeze and public suites pass unchanged.
- A 408 (`ClientError`) and the codes -1006 and -1007 are now retried on cancel, because they are STATUS_UNKNOWN. A non-SDK `RuntimeError` or `TimeoutError` on cancel is no longer retried.
- Tests added beyond the plan's list:
  - every one of the seven public calls checks and records the gate;
  - a naive clock is refused;
  - remaining seconds round up without float;
  - the cancel goes STATUS_UNKNOWN, then succeeds;
  - without a gate, every method raises after one call.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or schema. The plan's threat register covers the gate refusal messages (reason and seconds only) and the absent-cancel log fields (class name and int code only).

## Open issues

- Running `uv run ruff check` and `uv run ruff format --check` on the whole repository currently fails only on `tests/test_userdata_adapter.py`, which also fails formatting, and `tests/userdata_fakes.py`. Both are uncommitted in-progress edits of the concurrent plan 18-11 in the same worktree; they are not this plan's files and were not touched.
- `actuals.commits: 4` is the measured `git rev-list --count efc41c6..5387237`. It includes one interleaved commit of the concurrent plan 18-11 (47fcda7); this plan's own task commits are 529fb48, 95392c9 and 5387237.
- Not in this plan's scope, as the plan states:
  - injecting the gate into the listenKey port (18-14) and the probe adapter (18-12);
  - the composition that creates the single gate (18-13, 18-16, 18-17);
  - the unprotected-position event for a protective leg refused by the gate (18-13).

## Self-Check: PASSED

- FOUND: src/adapters/binance_ratelimit_gate.py, tests/test_binance_ratelimit_gate.py, tests/test_binance_usdm_error_routing.py, tests/test_binance_usdm_source_guard.py
- FOUND commits: 529fb48, 95392c9, 5387237
