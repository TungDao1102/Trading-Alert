---
phase: 25-demo-integration-test-campaign
plan: 02
subsystem: testing
tags: [fault-injection, test-only, composed-rig, rest-gate, EXEC-01, OPS-01]
requires: []
provides:
  - "FaultEdge / FaultPublic: adapter and public-reader faults through the exchange_edge seam"
  - "SdkFaults: 418/429 and other SDK errors seen by the real adapter and the real REST gate"
  - "StoreFaults: StoreUnavailable on chosen store methods through the stores seam"
  - "faults= / sdk_faults= / store_faults= pass-through on make_composed_rig and build_fake_smoke_env"
affects: [25-03, 25-04, 25-05, 25-06, 25-07, 25-08, 25-09, 25-10]
tech-stack:
  added: []
  patterns:
    - "inject the trigger at an existing production seam, keep the reaction real (D-08)"
    - "every injection recorded (method, mode, sequence); the scenario labels it DEMO_FAULT_INJECTED"
key-files:
  created:
    - tests/support/fault_edge.py
    - tests/test_fault_edge.py
  modified:
    - tests/support/live_composed_rig.py
    - tests/support/live_smoke_env.py
key-decisions:
  - "Faults are armed by method name on proxies that forward every other name, so check_wiring (gate, drift guard, snapshot recorder identity) stays empty."
  - "StoreFaults hands out one cached wrapper per store method: wiring compares `producer._snapshot_recorder == stores.snapshots.record`, which a fresh closure per access would break."
  - "StoreFaults.wrap is idempotent, so a restart that reuses previous.stores keeps one set of pending faults."
requirements-completed: [EXEC-01, OPS-01]
status: complete
duration: 40min
completed: 2026-11-07
commits: 6
plan_head_before: 56cca1fc216e3ac6e23d7208a8cd6b20ad1d8442
plan_head_after: 19b20aaf1ef2958525a371220a0e618f989b9752
actuals:
  tokens: 11800
  tasks: 3
  commits: 6
---

# Phase 25 Plan 02: Test-only fault injection Summary

Three test-only fault objects (adapter/public, SDK, store) installed through the three seams `build_wiring` already has, so a scenario can inject a stop rejection, a lost ACK, a 418/429, a DB outage or a stale mark into the REAL composed process and observe the real reaction. Nothing under `src` changed (D-08).

## What was built

- **Tracer (Task 1):** an injected `BadRequestError(-2021)` on `place_algo_protective` through `FaultEdge` after an approved, confirmed and filled plan: the real coordinator takes the B5 branch to CLOSE_REQUIRED, the fake records exactly one market close and ends flat, the rejection never reached the fake (`rig.fake.calls_to("place_algo_protective") == []`), the FaultEdge ledger holds one injected record, and `check_wiring(rig.wiring) == []`.
- **Adapter and public modes (Task 2):** payload mutation, lost response after send, hold/release, override, stale and moved mark.
- **SDK and store faults (Task 3):** 418/429 under the real adapter and gate (`account_information_v3` over CompositeRest), `StoreUnavailable` on store methods, restart reuse.

## API for the scenario plans

`methods` below are the names the real adapter / reader / SDK / store has. A fault applies to the next `times` calls (default 1) in registration order per method; `times=None` means until cleared.

### `FaultEdge()` (tests/support/fault_edge.py)

| Member | Signature | Effect |
|---|---|---|
| `bind` | `bind(inner) -> FaultEdge` | bind the wrapped adapter (a restart rebinds) |
| `install` | `install(bundle) -> ExchangeBundle` | `dataclasses.replace` of `adapter` and `public`; gate untouched |
| `inner` | property | the wrapped adapter |
| `public` | `FaultPublic` | the installed public reader |
| `injections` | `list[Injection(method, mode, sequence)]` | every applied fault, 1-based order |
| `calls_to` | `calls_to(method) -> list[dict]` | records `{method, args, kwargs, injected, mode, sequence[, mutated_kwargs]}` of every coroutine call through the edge |
| `raise_before_send` | `(method, exc, *, times=1)` | raise `exc`, inner not reached |
| `mutate_payload` | `(method, fn, times=1)` | inner receives `fn(kwargs)`; record keeps `kwargs` and `mutated_kwargs` |
| `drop_response_after_send` | `(method, exc, times=1)` | inner runs, then `exc` (lost ACK) |
| `override` | `(method, coro_fn, times=None)` | `await coro_fn(**kwargs)`, inner not called |
| `hold` / `release` / `held` | `hold(method)`, `release(method)`, `held(method) -> bool` | block the next call until released (no sleep); `release` before the call pre-releases, with nothing held it raises `ValueError` |
| `clear` | `clear(method)` | drop armed faults and unconsumed holds of the method |
| `stale_mark` / `moved_mark` | `(symbol, age: timedelta, *, times=None)` / `(symbol, price: Decimal, *, times=None)` | delegate to `FaultPublic` |

Synchronous methods and plain attributes (`_rest_gate`, `_drift_guard`, `error_facts`) pass through unrecorded.

### `FaultPublic`

`stale_mark(symbol, age, *, times=None)` (reading's `exchange_time_utc` moved back by `age`; negative age raises `ValueError`), `moved_mark(symbol, price, *, times=None)` (positive finite `Decimal` only, a float raises `TypeError`), `clear_marks(symbol=None)`, `mark_price(symbol)`; other symbols and methods pass through. Marks are recorded in the same ledger (`faults.calls_to("mark_price")`).

### `SdkFaults()`

`fail_sdk(sdk_method, exc, times=1)`, `clear(sdk_method=None)`, `wrap_factory(factory)`, `calls_to(sdk_method)` (calls that reached the proxy, i.e. past the REST gate), `injections`. Builders: `rate_limit_ban_error(*, retry_after=None, ban_until_epoch_ms=None)` (HTTP 418, code -1003; the 13-digit ban-until goes in the message exactly as D083 reads it) and `too_many_requests_error(*, retry_after=None)` (429). The SDK method name for the account read is `account_information_v3`. Note `prepare()` already reads it once: compare call counts against a count taken before arming.

### `StoreFaults()`

`wrap(store_set)` (idempotent; returns a real `LiveStoreSet` of proxies), `fail_store(attr, method, times=1, exc=None)` (`attr` is a `LiveStoreSet` field name, an unknown one raises `ValueError`; default error `StoreUnavailable`), `clear(attr=None, method=None)`, `calls_to("<attr>.<method>")`, `injections`.

### Rig and env

`make_composed_rig(..., faults=None, sdk_faults=None, store_faults=None)`; `ComposedRig` gains `faults`, `sdk_faults`, `store_faults`; `rig.edge` stays the `ComposedExchangeEdge`, `rig.assembly.exchange.adapter` is the FaultEdge when installed. `build_fake_smoke_env(..., faults=None, sdk_faults=None, store_faults=None)`: same objects go to the first rig and the restart rig (the restart reuses the wrapped stores); `FakeSmokeEnv` has `faults`, `sdk_faults`, `store_faults` fields.

## Deviations from Plan

None - plan executed as written. Small choices inside the plan's latitude: `held(method)` returns a bool; `raise_before_send` etc. use dict call records (like the fake's `calls_to`); `FaultEdge.stale_mark/moved_mark` delegate to `FaultPublic` so a scenario needs one handle.

## Verification

- `uv run pytest -m "not docker" tests/test_fault_edge.py tests/test_live_stream_to_protection.py tests/test_live_demo_smoke.py tests/test_binance_ratelimit_gate.py -x -q` passed; also tests/test_live_composed_tracer.py, test_live_reservation_release.py, test_live_smoke_injection.py and test_no_unratified_defaults.py passed.
- Scoped `ruff check` and `ruff format --check` on the four files: clean. `uv run mypy src`: no issues. `uv lock --check`: ok.
- `git diff --exit-code -- src pyproject.toml uv.lock` exits 0; `git grep -n fault_edge -- src` prints nothing.
- Line endings kept: `live_composed_rig.py` and `live_smoke_env.py` stay all-CRLF (checked byte counts).

## Not covered by an agent-run test

- Nothing here was run against Binance Demo; every test uses the Binance-semantics fake and in-memory stores (D-02). A real 418/429 is never provoked.
- `SdkFaults.wrap_factory` sets `client.rest_api` on the rig's SimpleNamespace stand-in; it is not meant for the real SDK client built by `build_sdk_client` (no Demo run uses it).
- No scenario consumes the DEMO_FAULT_INJECTED label yet (plan 25-08).
- The src import-guard extension (LIVE_FORBIDDEN_IMPORTS for src/execution and src/risk) belongs to plan 25-05; here only `git grep fault_edge -- src` was checked.

## Known Stubs

None.

## Threat Flags

None (test-only; no new network endpoint, auth path or schema). T-25-04, T-25-05, T-25-06 and T-25-SC mitigations hold as listed in the plan.

## Self-Check: PASSED

Files tests/support/fault_edge.py, tests/test_fault_edge.py, tests/support/live_composed_rig.py, tests/support/live_smoke_env.py found; commits e2777a29, 3165d23e, 8de55730, 152404b3, 61feaf88, 19b20aaf are ancestors of HEAD.
