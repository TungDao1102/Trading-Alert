---
phase: 18-user-data-stream-error-taxonomy
plan: 23
subsystem: scripts/operator-tools
status: complete
tags: [demo-probe, D055, D-15, D-16, D-17, G2-029, EXEC-01, EXEC-02, order-bound, T-18-55, T-18-72, offline]
requires: [18-17]
provides:
  - scripts/demo_probe.py (order_bound_refusal, OrderBoundRefused, run_write_case, the 15 write-case handlers registered in CASE_HANDLERS, case_partial_fill, GuardedProbePort.banned, DOCUMENTED_ALGO_TIME_IN_FORCE, the REASON_* texts of the write cases)
  - tests/probe_fakes.py (FakeProbePort scenario helpers - marketable and partial fills, per-id order and algo statuses, scripted duplicate answers, on_wait hooks, system_cancel_algo, trigger_algo with a child order, the banned flag)
  - tests/test_demo_probe_cases.py (per-case branching tests, order-bound tests, ban tests, registry completeness, dry-run rehearsal and handler-purity tests)
affects:
  - plan 18-20 (blocking-human live Demo run starts from a complete registry; see the limits-file constraints under Findings)
  - plan 18-21 (corrects BinanceSemanticsFakeAdapter from the recorded answers)
  - plan 18-25 (documents)
tech-stack:
  added: []
  patterns:
    - one write-case wrapper (run_write_case) applies the common rules; each handler checks every order it will send before the first send, so a refused case sends nothing
    - dependent cases read the premise outcome from recorder.results, never from an assumption
    - every case wait is one wait_up_to(rig, predicate, case_timeout_seconds); no handler sleeps
key-files:
  created: []
  modified:
    - scripts/demo_probe.py
    - tests/probe_fakes.py
    - tests/test_demo_probe_cases.py
    - tests/test_demo_probe_evidence.py
decisions:
  - "The probe port has no order-book read, so a marketable BUY LIMIT is priced at the PERCENT_PRICE upper bound (mark x multiplierUp, floored to the tick). It fills at the book's best ask; the notional bound is checked at the limit price, which bounds the fill from above."
  - "The after-ban cleanup attempt lives in the write-case wrapper, not in the 18-17 runner: when the port reports no ban (GuardedProbePort.banned, fail closed) cleanup_symbol runs once; its result and the case's known open ids go into the evidence `ban` record. The runner's 18-17 ban behaviour is unchanged."
  - "Reconciliation after the pre-placed, orphan and full-fill cases (and the stream gap) is taken inside the handler, recorded as details reconciliation_expected / _observed / _matches; the runner is unchanged."
metrics:
  duration: "about 20 minutes (2026-10-16T08:37Z to 08:57Z)"
  completed: 2026-10-16
  tasks: 3
  files: 4
estimate:
  tokens: 60000
  tasks: 3
actuals:
  tokens: 31500
  tasks: 3
  commits: 6
plan_head_before: 091f38fa95f8fd014a844f5d41a8ca66401d92cc
plan_head_after: dfadd5186d1c3de36cb7d79fbf88f42e4c6a9cee
---

# Phase 18 Plan 23: Demo probe - the cases that send orders Summary

Every case of `CASE_ORDER` now has a handler. The 15 cases that send orders run through one wrapper that applies the common rules. Every order passes one shared bound before it is sent: never above the owner's approved quantity or notional cap. Each case records the exact exchange answers as data, or ends NOT_OBSERVED with the reason. Dependent cases read their premise from the run recorder and never act on a rejected leg.

Nothing in this plan contacted Binance. Every run was a test on fakes or an offline dry run, and `--execute` was never passed. D055 stays OPEN.

## Commits

`commits: 6`, measured as `git rev-list --count 091f38f..dfadd51`.

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer, red) | 0eb780c | FakeProbePort scenario helpers; carrier-case, order-bound and common-rule tests; the 18-17 dry-run evidence test widened |
| 1 (tracer) | 724c412 | `order_bound_refusal`, `run_write_case`, `_WriteCase`, the four carrier handlers |
| 2 (red) | 96e00d7 | D055 case tests |
| 2 | 9e566c8 | the five D055 handlers and `case_partial_fill` |
| 3 (red) | d205c32 | G2-029, optional, ban, completeness, dry-run and purity tests |
| 3 | dfadd51 | the G2-029 and optional handlers, `GuardedProbePort.banned`, docstring |

## What was built

- **Order bound (`order_bound_refusal`, T-18-55).** Every write handler calls it for every order it will send, before the first send. It refuses:
  - a quantity that is not positive, off the step grid, or above the approved `quantity`;
  - a `quantity * price` above `max_notional_quote` (the price is the order's highest limit or trigger price).

  A close-position order has no quantity and passes the quantity rules. The single exception is `market_lot_size_out_of_range`: its quantity must equal `market_lot_probe_quantity` exactly, and the notional cap is not applied. A refusal makes the case ERROR "order bound: ... (nothing more was sent)". The send helpers check the bound again just before sending.
- **Common rules (`run_write_case`).**
  - Unknown position mode: NOT_OBSERVED. Hedge mode: the reduce-only based cases are NOT_OBSERVED "hedge mode: reduceOnly cannot be sent". Those cases are `preplaced_stop_reduce_only_flat`, `entry_never_fills_protective_orphan`, `full_fill_protective_quantity`, `below_min_notional_reduce_only_leg`, `triggered_market_exit_lifecycle`, `explicit_time_in_force_variant` and `market_lot_size_out_of_range`.
  - A script error is ERROR "script error: <Type>". The handler returns it without raising, and the runner's per-case cleanup still runs.
  - A 418 or 429 answer stops the case NOT_OBSERVED and keeps its answers. The runner then aborts the run.
  - A `ProbeBanned` records the case's answers and its known open ids under `ban`. If the port reports no ban, `cleanup_symbol` is attempted once. The exception is then re-raised, the run ends ABORTED_BAN, and the remaining cases are NOT_OBSERVED "run aborted: ban".
  - Client ids are unique per case, except the intended reuse.
  - Prices are Decimals on the tick grid and quantities are on the step grid (no float).
- **Carrier cases (Task 1).**
  - `duplicate_client_algo_id`: a far STOP BUY carrier (up-trigger and price at mark x (2 - fraction)), then the same `clientAlgoId` again, then a cancel. A rejected carrier gives NOT_OBSERVED "carrier rejected: <class> <code>".
  - Two id-reuse cases after CANCELED: a far LIMIT or the carrier, cancel, the same id again, cancel. A failed cancel gives NOT_OBSERVED and the reuse is not sent.
  - `id_reuse_after_filled`: a marketable entry, then one wait for FILLED, then the same id placed as a far LIMIT.
- **D055 cases (Task 2).**
  - Pre-placed leg: STOP_MARKET SELL with explicit quantity and reduceOnly while flat. Records the algo status, the frames (one wait, only with a running stream) and a reconciliation.
  - Close-position STOP_MARKET while flat.
  - Orphan: far entry, then leg, then the entry is cancelled. One wait for the leg to end. Records `orphaned` (true, false or unknown), a clean `cancel_algo_order` and a reconciliation.
  - Full fill: leg first, then a marketable entry. Records position amount, listed leg quantity and status, `protective_quantity_equals_position` and a reconciliation.
  - `partial_fill`: derived from the REST statuses and the stream frames of the entry cases. It sends no order.
  - Three rejected variants, each answered once. In hedge mode the reduce-only variant is recorded as skipped.
  - Each dependent case covers the premise-not-run branch, the leg-not-accepted branch and the leg-rejected-in-this-case branch.
- **G2-029 and optional cases (Task 3).**
  - Below-minimum-notional leg: NOT_OBSERVED when impossible; otherwise a reduce-only leg of the smallest valid quantity on a position.
  - Triggered exit: a reduce-only STOP_MARKET one tick below a fresh mark, then one `wait_up_to` of `case_timeout_seconds` on REST and frames. Records:
    - the statuses seen;
    - `ai`, `aq`, `rm`, and the child `c` and `i`;
    - the REST `actual_order_id`;
    - the LOT_SIZE and MARKET_LOT_SIZE values;
    - the MARKET_LOT_SIZE statement.
  - Optional cases:
    - one leg per documented time-in-force;
    - a stream gap during an open far order, with the recovery states and a reconciliation;
    - the triggered exit at `market_lot_probe_quantity`. For this case a rejected placement is itself the finding.
- **Registry.** `set(CASE_HANDLERS) == set(CASE_ORDER)`. The dry run with every optional case enabled invokes each handler once in `CASE_ORDER`, with no ERROR. Every case is NOT_REHEARSED and none is flagged `handler_registered` false.

## Verification

All commands ran as `UV_OFFLINE=1 uv run --frozen --extra dev …`. The full suite was not run (memory limit). PostgreSQL and Docker were off.

**Tests**

| Test set | Result |
|----------|--------|
| Task 1 verify (three probe files) | 241 passed |
| Task 2 verify (three probe files) | 267 passed |
| Task 3 verify (three probe files) | 298 passed: cases 127, evidence 78, CLI 93 |
| Plan verification set: three probe files, three `test_user_data_smoke_*` files, `test_binance_probe.py` | 581 passed |
| Scans over `scripts/` | 723 passed |

The scans over `scripts/` were `test_analytics_edge_guards`, `test_decision_alignment*`, `test_paper_exit_evaluator`, `test_universe_freeze`, `test_env_example`, `test_kill_gate_clock`, `test_paper_shadow_isolation`, `test_code_version`, `test_demo_rehearsal_safety`, `test_no_unratified_defaults`, `test_binance_probe_contract` and `test_operator_evidence`.

**Lint and types**

| Check | Result |
|-------|--------|
| `ruff check` | all checks passed |
| `ruff format --check` | 603 files already formatted |
| `mypy src` | no issues in 199 source files |
| `mypy scripts/demo_probe.py` (outside the gate) | no error in the script; the 2 existing errors in `tests/support/limits.py:191` are unchanged |
| `uv lock --check` | 60 packages, unchanged |

**Dry run.** An offline dry run of the CLI used TEST_ONLY limits with every optional case enabled and wrote to the scratchpad. It exited 0 with outcome COMPLETE: 19 cases, all NOT_REHEARSED, none unregistered, 52 planned requests, 0 live port calls. Acceptance was FAIL, as expected, because FAKE evidence never passes.

**Plan 18-17 tests.** They pass, with one exception: the dry-run evidence test was widened (deviation 1).

## TDD Gate Compliance

Each task has a `test(18-23)` commit before its `feat(18-23)` commit.

- **Task 1.** 23 new tests failed with AttributeError (the missing `order_bound_refusal`, `run_write_case` and handlers). The 218 tests from plan 18-17 still passed. The Task 1 implementation was written before its test commit was made, but the red run happened before any implementation existed. The tracer gate (interactive, end-of-phase, automated-only verify) re-ran the Task 1 verify: 241 passed.
- **Task 2.** 26 tests were red (unregistered handlers), then green.
- **Task 3.** 18 tests were red, then green. Two groups of tests passed on their first run: the ban tests (5) and the handler-purity test. They test the wrapper and helpers written in Task 1, so they are new coverage of existing code, not new behaviour. The `GuardedProbePort.banned` test was added with its implementation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The 18-17 dry-run evidence test pinned the planned operations to the four read-only ones**
- **Found during:** Task 1.
- **Issue:** `tests/test_demo_probe_evidence.py::test_the_dry_run_records_planned_requests_only` asserted that the planned-operation set equals {query_order, query_algo_order, cancel_order, cancel_algo_order}. That held only while the write cases were unregistered.
- **Fix:** the test now requires those four, and only order placements and per-id queries and cancels (`MUTATING_OPERATIONS | CASE_QUERY_OPERATIONS`). This file is not in the plan's file list.
- **Commit:** 0eb780c.

**2. [Rule 2 - Correctness] `GuardedProbePort.banned` (read-only, fails closed)**
- **Issue:** the plan's rule "cleanup is attempted once only if the adapter reports no ban" needs the adapter's ban flag. The 18-17 guarded port did not expose it.
- **Fix:** an explicit property that returns the inner adapter's `banned` bool. It returns True when the flag is missing or not a bool. This is not attribute passthrough, and the 18-17 test for that still passes.
- **Commit:** dfadd51.

### Interpretation notes (no behaviour beyond the plan)

- **Marketable entry price.** The plan says "a marketable LIMIT at the best ask", but `ProbePort` has no order-book read, and the adapter was not to be edited. The entry is priced at the PERCENT_PRICE upper bound instead (see decisions). If that filter is unreadable, the case is NOT_OBSERVED.
- **Triggered exit trigger.** The plan says "just beyond the mark so that it triggers". The trigger is the highest tick-grid price strictly below a fresh mark: a SELL stop that triggers on a one-tick fall.
- **Rejected variants.**
  - (a) is a TAKE_PROFIT_MARKET close-position while flat, so it differs from `closeposition_stop_flat`.
  - (b) is reduceOnly together with closePosition.
  - (c) is a non-reduce-only SELL STOP_MARKET with its trigger far above the mark, so the wrong-side trigger is not confounded with a reduce-only rejection.
  - In hedge mode only (b) is skipped, recorded as a detail. The case is not in the reduce-only list.
- **Reconciliation.** It is taken by the handler, not the runner, because the runner is unchanged by design.
- **Optional time-in-force case.** It sends GTC, IOC, FOK, GTX, GTD and RPI, the values the New Algo Order page listed (research B9). GTD is sent without `goodTillDate` because the port has no such parameter, so its answer is expected to be a rejection. That answer is still recorded as data.
- **Partial fill.** The handler sends nothing and does not use `run_write_case`, because it needs no position mode. It still turns any exception into ERROR.

## Findings (not changed: outside the plan's scope)

- **Constraints on the owner's probe limits file (plan 18-20).** These are sizing facts, not a recommended parameter (D-17). With quantity q, mark M and fraction f:
  - Far orders are accepted only if q x M x f is at least the symbol's minimum notional. Otherwise the carrier cases will record "carrier rejected" (-4164 is likely).
  - The bound refuses, as ERROR, any case whose highest order exceeds the cap: q x M x (2 - f) for the carriers and up-triggers, and q x M x multiplierUp for the marketable entries.

  The TEST_ONLY values (q 0.002, f 0.80, mark 60000, min notional 100) would make a real far BUY 96 USDT, which is below 100.
- **Wrong-side variant (c).** If the exchange accepts it, it triggers and opens a short of the approved quantity. The bound covers it and the per-case cleanup flattens it.
- **No drift check before the first order.** The finding from plan 18-17 stands. The probe preflight still does not measure server-time drift, because `BinanceProbeAdapter` exposes no gated `server_time`. A -1021 would be recorded as data. Plan 18-20 should decide whether to add it.
- **Flat-account precondition.** The precondition from plan 18-17 is unchanged, and the write cases rely on it: the per-case cleanup cancels everything on the symbol.
- **Real ban in a live run.** With the real adapter, a `ProbeBanned` comes with `adapter.banned` true or the gate restricted. The after-ban cleanup is therefore skipped, or refused by the gate before sending. The fake branch with no ban exists for completeness.
- **Dry-run coverage.** `RecordingProbePort` answers carry no order status, so in a dry run every entry takes the "did not fill" path. The planned requests do not show the post-fill steps: the reuse after a fill, the full-fill comparison, the below-notional leg and the triggered exit leg. The handlers never branch on mode; the scripted fake tests cover those paths.
- **Worktree branch name.** The branch is `phase-18`, outside the `agent-*` namespace that the executor's commit assertion expects. The commits were made there as the orchestrator instructed, consistent with plans 18-16 and 18-17.

## Known Stubs

None. Every case id has a handler. `.planning/WINDOWS.md` does not exist, so no ledger entry was appended.

## Threat Flags

None beyond the plan's register:

- **T-18-55:** one bound, checked for every order before the first send and again just before each send, with tests per case family.
- **T-18-72:** dependent cases read the premise from `recorder.results`, and both branches of each are tested. No retry exists.
- **T-18-SC:** no package was installed.

## Self-Check: PASSED

- FOUND: scripts/demo_probe.py, tests/probe_fakes.py, tests/test_demo_probe_cases.py, tests/test_demo_probe_evidence.py
- FOUND commits: 0eb780c, 724c412, 96e00d7, 9e566c8, d205c32, dfadd51
