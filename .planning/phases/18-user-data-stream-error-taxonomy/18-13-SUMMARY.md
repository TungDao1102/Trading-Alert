---
base: cc8d030b9af2fc3902b9e0adb820f12e5e3f704f
phase: 18-user-data-stream-error-taxonomy
plan: 13
subsystem: adapters/binance-usdm, scripts/demo-rehearsal
status: complete
tags: [binance, recvWindow, clock-drift, rate-limit, 418, 429, signed-calls, OPS-02, EXEC-01, D-14, F-505]
requires: [18-07, 18-09, 18-10]
provides:
  - BinanceUsdmAdapter(sdk_client=None, *, rest_gate=None, sleep=None, signed_call_policy=None, drift_guard=None, clock=None, on_clock_skew=None)
  - SignedCallPolicyMissing, EntriesBlocked (src/adapters/binance_usdm.py)
  - private BinanceUsdmAdapter._sdk_call(call_kind, method, **kwargs) - the one path of all eleven signed SDK calls
  - scripts/demo_rehearsal.py --limits-file, load_signed_call_policy, LimitsFileRefused, default_adapter_factory(credentials, *, signed_call_policy, clock)
  - tests/test_binance_usdm_signed_calls.py
affects:
  - Phases 19 and 24 (compose ClockDriftGuard refresh with the gated server_time of the same rest_gate; react to EntriesBlocked)
  - Phases 19 and 20 (ENTRY_WITHOUT_PROTECTIVE from a refused or rate-limited protective leg is the unprotected-position event)
  - plans 18-16, 18-17 (compositions must pass signed_call_policy together with the one rest_gate)
tech-stack:
  added: []
  patterns:
    - one signed-call helper (policy check, gate check, explicit recv_window, worker thread, 418/429 record, -1021 hook, re-raise the original)
    - AST send guard with a negative control (no signed SDK attribute outside the helper's method argument)
    - SDK keyword-argument binding against inspect.signature of the installed SDK
key-files:
  created:
    - tests/test_binance_usdm_signed_calls.py
  modified:
    - src/adapters/binance_usdm.py
    - scripts/demo_rehearsal.py
    - tests/test_binance_usdm_error_routing.py
    - tests/test_binance_ratelimit_gate.py
    - tests/test_adapter_not_found_mapping.py
    - tests/test_adapter_strictness.py
    - tests/test_execution_adapter_contract.py
    - tests/test_execution_manager.py
    - tests/test_demo_rehearsal_safety.py
decisions:
  - "_sdk_call calls asyncio.to_thread itself (it no longer goes through _gated_rest_call); the public delegations keep _gated_rest_call in binance_public.py"
  - "place_entry runs the policy check, then the drift-guard check, before building SDK enums; the gate check stays inside _sdk_call (EntriesBlocked wins over a gate refusal when both apply)"
  - "A gate without a policy is allowed (public reader use); a policy without a gate, or with a gate whose policy differs, is a ValueError"
  - "The rehearsal loads the limits file after the credentials, inside the existing refusal block; the refusal message names the path only"
  - "In the 18-10 routing tests an adapter built without a gate gets a private gate of its own; the ungated-test case is restricted to the public delegations, because a signed call can no longer run ungated"
metrics:
  duration: ~3h wall clock (includes an API session-limit interruption and two 10-20 minute full-suite runs)
  completed: 2026-10-16
  tasks: 3
  files: 10
actuals:
  tokens: 16500
  tasks: 3
  commits: 3
plan_head_before: cc8d030b9af2fc3902b9e0adb820f12e5e3f704f
plan_head_after: bc645963f325c22f8b774dc22860e3b72b38d502
---

# Phase 18 Plan 13: Explicit recvWindow on every signed call, drift guard on new entries Summary

All eleven signed methods of `BinanceUsdmAdapter` now go through one private helper, `_sdk_call`. The helper fails closed when no policy is configured, runs the shared `RestRateLimitGate` check, and passes `recv_window=SignedCallPolicy.recv_window_ms` to the SDK. On a 418 or 429 it records the answer in the gate. On a -1021 it calls the hook once. In every case it re-raises the original exception and never retries. When a `ClockDriftGuard` is configured, `place_entry` raises `EntriesBlocked` before any SDK call while the guard blocks entries. The Phase 9 rehearsal loads the ratified policy from `--limits-file`.

Plan revision: revised 2026-10-16 per `decisions/18-DEC-O-18-01.md` and its amendment of the same day: a signed call requires the shared gate, nothing is retried on a 418 or 429, and the plan adds the never-retry matrix, the restriction-expiry test and the unprotected-position test.

## Commits

`commits: 3` is the number of 18-13 commits. `git rev-list --count base..HEAD` gives 11, because the 18-12 and 18-14 executors committed on the same `phase-18` branch at the same time.

- e93041a feat(18-13): signed-call helper with explicit recv_window, fail-closed policy, -1021 hook (tracer)
- 7babb50 feat(18-13): every signed method through the recv_window helper, drift guard blocks new entries only
- bc64596 feat(18-13): rehearsal loads the ratified signed-call policy; existing tests use TEST_ONLY policies

## What was built

- **Task 1 (tracer):** constructor arguments and checks, `SignedCallPolicyMissing`, `EntriesBlocked` and `_sdk_call`. `query_order_by_client` and `place_entry` were migrated first. The tracer gate re-ran its verify command end to end and it passed.
- **Task 2:** the other nine methods now use the helper. The call kinds are QUERY for the queries, snapshots, position mode and commission rate, CANCEL for the two cancels (the STATUS_UNKNOWN tenacity loop wraps the helper) and PLACEMENT for `new_algo_order`. `user_commission_rate` now passes `symbol` by keyword. The module docstring table was updated.
- **Task 3:** the rehearsal has a `--limits-file` option. `default_adapter_factory` builds exactly one `RestRateLimitGate` per run (checked by a source test), and a missing or invalid file refuses with exit code 2 before any adapter is built. The constructions in existing tests now pass the TEST_ONLY policy and a gate.

The installed SDK 17.4.0 was checked: `inspect.signature` shows a `recv_window` parameter on all eleven methods (`current_all_open_orders`, `current_all_algo_open_orders`, `position_information_v3`, `query_algo_order`, `query_order`, `cancel_order`, `cancel_algo_order`, `new_order`, `new_algo_order`, `get_current_position_mode`, `user_commission_rate`). A contract test pins this.

## Unprotected-position proof (decision item 5)

`test_protective_blocked_by_pause_or_ban_surfaces_unprotected_position` runs the real `attach_protectives_to_fill` of the unchanged `src/execution/manager.py`. It uses the real adapter over SDK fakes and a recording SAFE_MODE controller. There are five cases:

- gate paused before the attach
- gate banned before the attach
- `new_algo_order` answers 429
- `new_algo_order` answers 418
- the next leg's query-by-ID is refused by a pause that another holder set after the stop was placed

Every case ends in ENTRY_WITHOUT_PROTECTIVE, enters SAFE_MODE once and carries `failure_detail` `"<ROLE>: [probe ]<TypeName>"`. `new_algo_order` is sent zero times for a refused leg and once when the exchange answered. Nothing is retried, no sleep is recorded and the failing role is never in `placed_legs`. `git diff cc8d030..HEAD -- src/execution/manager.py` is empty.

## Existing test files that needed the policy and gate

- `tests/test_binance_usdm_error_routing.py` (Task 1)
- `tests/test_binance_ratelimit_gate.py` (Task 2; an extra file not in the frontmatter, `test_public_rate_limit_answer_restricts_shared_gate`)
- `tests/test_adapter_not_found_mapping.py`
- `tests/test_adapter_strictness.py` (the commission adapter only)
- `tests/test_execution_adapter_contract.py`
- `tests/test_execution_manager.py` (`test_real_adapter_place_entry_makes_a_single_attempt`)
- `tests/test_demo_rehearsal_safety.py` (new tests only; the existing constructions call public methods and needed no change)

`tests/test_constraint_snapshot.py` and `tests/test_demo_rehearsal_flow.py` are listed in the frontmatter but needed no edit. Their constructions only reach public methods, or go through the injected factory.

## Verification

- Task 1 verify: 200 passed. Task 2 verify set: 491 passed. `mypy src`: no issues (197 files). `uv lock --check`: ok.
- `ruff check` and `ruff format --check` are clean on every file of this plan. The whole-tree run showed findings only in `tests/test_userdata_supervisor.py` (plan 18-14, in progress at the time).
- Full non-docker suite `pytest -m "not docker" -x`: 8538 passed, 501 skipped and 1 failed. It stopped on `tests/test_userdata_supervisor.py::test_hard_keepalive_failure_reports_category_and_never_loops`, plan 18-14's file, which was mid-edit and uncommitted when the run started. Neither that test nor that file uses `BinanceUsdmAdapter`. After 18-14 committed, the file passed on its own, and the two test files after the stop point (`test_wave0_sanity.py`, `test_wr_registry_scopes.py`) passed (14). An earlier full run without `-x`, made before the Task 3 fixes, failed only on `SignedCallPolicyMissing` in the four files fixed in Task 3 (53 failures).
- `git diff BASE..HEAD -U0 -- tests`: one removed line in this plan's files contains `assert`, so the count is 1, not the 0 the plan expects (see the deviations). The other removed assert line in the whole-tree diff, in `tests/test_userdata_adapter.py`, belongs to plan 18-14.

## Deviations from Plan

1. **[Rule 1 - expected behavior change] One assertion replaced.** `tests/test_adapter_strictness.py::test_user_commission_rate_projects_frozen_dataclass` asserted `commission_calls == [("BTCUSDT", None)]`, which pins the old "recv_window left to the SDK default" behavior that this plan removes. It now asserts `[("BTCUSDT", TEST_ONLY_RECV_WINDOW_MS)]`. That is stronger, but the removed-assert count is 1, not 0.
2. **[Rule 3 - blocking] 18-10 ungated test narrowed.** `test_without_a_gate_a_rate_limit_raises_after_one_call_and_nothing_is_refused` was parametrized over every method. A signed method can no longer run without the policy and the gate, so the test now covers the seven public delegations through a new `_ungated_adapter()` helper. Its assertions are unchanged. The signed methods are covered by the fail-closed tests in the new file. The routing `_adapter()` helper gives an adapter built without a gate a private gate, so the `no_gate` parametrizations still run with identical assertions.
3. **[Rule 3] Extra file.** `tests/test_binance_ratelimit_gate.py` needed the policy argument for one construction, because it is in the Task 2 verify set.
4. **Interpretation of "confirmation query refused by a pause".** The manager probes with `query_algo_order` before each placement. The case where the gate was paused before the attach already refuses the stop-loss probe, so the fifth case was made distinct: the stop is placed and confirmed, another holder then records a pause, and the TAKE_PROFIT_1 query is refused (zero sends for that leg).

## Known Stubs

None.

## Threat Flags

None. The plan adds no endpoint or auth path. The new `--limits-file` option reads a local TOML file, and its refusal message names only the path.

## Open issues

- Composing the drift guard into the runtime (refresh loop, `on_clock_skew=guard.note_clock_skew_error`, reacting to `EntriesBlocked`) is left to Phases 19 and 24, as planned.
- The data jobs (`BinanceUsdmAdapter()` in the backfill, collector and universe freeze) keep calling only public methods without a policy or a gate, which is the known Phase 18 gap recorded by plan 18-10.

## Self-Check: PASSED

Files: tests/test_binance_usdm_signed_calls.py, src/adapters/binance_usdm.py and scripts/demo_rehearsal.py exist. Commits e93041a, 7babb50 and bc64596 exist on phase-18.
