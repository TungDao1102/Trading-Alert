---
phase: quick-261023-sj2
plan: 01
subsystem: demo-probe
tags: [demo-probe, evidence-capture, binance-demo, owner-run, reduce-only, min-notional, insufficient-margin, recv-window, income-history]
requires: [quick-261022-sj1]
provides:
  - "eight owner opt-in Demo probe cases (SJ2_CASES) in scripts/demo_probe.py"
  - "BinanceProbeAdapter.stale_timestamp_read (ProbePort, GuardedProbePort, both fakes)"
  - "owner-file keys reduce_only_flat, reduce_only_oversize, min_notional_entry, insufficient_margin, stop_reject_after_accept, trigger_cancel_race, recv_window_error, income_history and insufficient_margin_quantity"
  - ".planning/DEMO-EVIDENCE-PLAN.md sections 16 to 23, extended session list and TOML template, consumers rows, updated 'Not covered here'"
affects: [phase-19-owner-gaps, phase-20-deferred, phase-21, phase-25]
requirements-addressed: [O-05]
key-files:
  created:
    - tests/test_demo_probe_sj2_cases.py
  modified:
    - scripts/demo_probe.py
    - src/ops/operator_evidence.py
    - src/adapters/binance_probe.py
    - tests/probe_fakes.py
    - tests/test_operator_evidence.py
    - tests/test_binance_probe.py
    - tests/test_binance_probe_contract.py
    - tests/test_demo_probe_cases.py
    - tests/test_demo_probe_cli.py
    - tests/test_demo_probe_capture_cases.py
    - tests/test_demo_probe_sj1_cases.py
    - .planning/DEMO-EVIDENCE-PLAN.md
decisions:
  - "Key and case order: reduce_only_flat, reduce_only_oversize, min_notional_entry, insufficient_margin, stop_reject_after_accept, trigger_cancel_race, recv_window_error, income_history, then gtd_expiry. The rejection-answer cases come first, the stop cases next, the two reads last, so income_history sees the whole run window and the long GTD case still runs last."
  - "recvWindow of recv_window_error is the ratified signed_calls.recv_window_ms (5000 in the ratified file), not 'the smallest allowed': the project documents no minimum and the contract rule is 'missing contract is TBD, never invent'. The timestamp is 2 x that window behind the EXCHANGE time (the tool adds the local-minus-server offset it just measured)."
  - "insufficient_margin_order (owner request during the task) has its own bound margin_order_refusal; it is not held to max_notional_quote or the approved quantity, and nothing else is changed in order_bound_refusal."
  - "Accepted insufficient_margin_order ends NOT_OBSERVED (the -2019 answer was not seen), with accepted=true and the margin figures before and after recorded. A rejection code of any kind is OBSERVED."
  - "race_repeats and near_trigger_fraction now also serve trigger_cancel_race and stop_reject_after_accept (the loader accepts the key when either race case is on)."
status: complete
plan_head_before: 33ac7806666223dd6778d5cec1376197c8cddec8
plan_head_after: ae70c0b39a0b309df8daf6509a0a6c4230002380
commits: 3
actuals:
  tokens: 36000
  tasks: 4
  commits: 3
---

# Quick Task 261023-sj2: the remaining Demo probe cases Summary

Eight more owner opt-in Demo probe cases on the sj0/sj1 framework (A4, A8, -4164, -2019, the P5 remainder, the P7 trigger part, -1021 and the income history), one new read-only adapter operation, the loader keys and the owner runbook. Nothing was executed against Binance: no `--execute`, no network call, no Binance or Telegram contact. Evidence label: fakes only; nothing here is `[DEMO]`. `commits` counts the plan commit and the two work commits up to `plan_head_after`; the commit of this SUMMARY comes after it.

## What was built

All eight cases are `run_write_case` bodies in `scripts/demo_probe.py`: owner key default off, placed before `gtd_expiry`, hedge mode ends NOT_OBSERVED with nothing sent for the six that send orders, one-way only, nothing retried, the runner cleanup cancels and flattens after the case, every exchange answer recorded (HTTP class, code, category, message) in `observations` and in the `*_error_*` details, and the REST answers are written as fixtures in an executed run (`FIXTURE_CASES`).

1. `reduce_only_market_on_flat` (key `reduce_only_flat`, A4): reads open orders, open algo orders and the position; NOT_OBSERVED unless flat. ONE reduce-only MARKET SELL of the approved quantity. A rejection code is the answer. If it was accepted and a position appeared, `flipped=true` and the position is flattened at once with the opposite reduce-only order (`_WriteCase.flatten`).
2. `reduce_only_market_larger_than_position` (key `reduce_only_oversize`, A8): opens about half of the approved quantity (floored to the step; below the exchange minimum quantity is NOT_OBSERVED with the reason), then ONE reduce-only MARKET of the full approved quantity. Records the answer, the executed quantity (answer and a final order query), the position after and `outcome` = `rejected`, `clipped_to_position`, `partly_reduced`, `unchanged` or `flipped`; any remainder is flattened.
3. `non_reduce_only_below_min_notional` (key `min_notional_entry`, -4164): reads MIN_NOTIONAL, computes the largest step-grid quantity whose notional at the far price is strictly below it (never above the approved quantity; below the minimum quantity, or an unlisted filter, is NOT_OBSERVED), sends ONE far non-reduce-only LIMIT BUY, records the code and message, cancels it at once if accepted. Records `min_notional_used` and `computed_notional`.
4. `insufficient_margin_order` (key `insufficient_margin`, -2019; own `[order]` key `insufficient_margin_quantity`): see the section below.
5. `stop_rejected_after_acceptance` (key `stop_reject_after_accept`, needs `near_trigger_fraction`, P5 remainder and `ALGO_UPDATE.o.rm`): half-quantity position, then a reduce-only STOP_MARKET (not closePosition) for the full approved quantity just below the live mark. A rejected placement is the answer. If accepted: one wait (`case_timeout_seconds`) for the leg to end, every REST and frame status, the raw `rm` text and the full ALGO_UPDATE sequence; the leg is cancelled if still open. NOT_OBSERVED when nothing beyond NEW happened.
6. `trigger_cancel_race` (key `trigger_cancel_race`, needs `near_trigger_fraction` and `race_repeats`, P7 trigger part): per repeat, with a position open (one marketable entry of the approved quantity when none is), a closePosition stop near the live mark, an immediate cancel, then the algo query and the position. Records the cancel answer, the final algo status, `triggered` and `position_closed` per repeat, tallies, and the plain statement that it is not a deterministic race (`note`).
7. `timestamp_outside_recv_window` (key `recv_window_error`, -1021): reads the public server time, then ONE read-only signed GET (open orders) whose timestamp is 2 x the recvWindow behind the exchange time. Records both clocks, the offset, the timestamp actually sent, `clock_calls` and the exact answer. Implemented for real (not a stub), see "The stale clock".
8. `income_history_read` (key `income_history`): read-only. The income history from the run start converted to the exchange clock; row count, field names, row types, per-type counts, exact per-type and asset sums (arithmetic only), first and last row time. An empty window is NOT_OBSERVED.

### insufficient_margin_order (the one cap exception)

- Owner supplies `insufficient_margin_quantity` in `[order]` (a plain decimal string; no default, no proposed number). The loader requires it exactly when the case is on and refuses it otherwise; the runbook placeholder `"<OWNER: ...>"` is not a decimal, so the file is refused until replaced (tested).
- The case sends exactly that quantity as ONE GTC LIMIT BUY at the far price of the owner `far_price_fraction` band (always below the mark: it can only rest). It does NOT use `check_bounds` / `order_bound_refusal` / the `max_notional_quote` cap (code comment in `_insufficient_margin_order`, the docstring of `_WriteCase.margin_limit`, the module docstring and the runbook say so). Its own bound is `margin_order_refusal`: the key is enabled, the quantity is the owner's one, positive, on the step grid, the price is positive and not above the far price.
- Still required: the symbol, the flat account precheck (NOT_OBSERVED otherwise), the price band, quantity inside LOT_SIZE (below the minimum or above the maximum quantity is NOT_OBSERVED with nothing sent, because the answer would be a lot-size error, not -2019), and the runner cleanup (which flattens anything that filled; the case itself never closes a position above the cap).
- Records the available balance and margin totals before and after, the leverage, the implied notional and margin and whether it exceeds the available balance, then the exact answer. Accepted: cancelled at once, `order_accepted=true`, NOT_OBSERVED (`-2019 was not observed`).
- Tests prove the other cases still enforce the cap: with `cap="1"` the margin case still sends while the other five order cases end ERROR or NOT_OBSERVED with nothing sent; `order_bound_refusal` still refuses the margin quantity and any notional above the cap; an AST test pins that `margin_limit` is called only by `_insufficient_margin_order` and that handler calls none of `check_bounds`, `limit`, `order_bound_refusal`, `market_close`, `gtd_limit`, `conditional`.

### The stale clock (recv_window_error)

`BinanceProbeAdapter.stale_timestamp_read` makes the one SDK call `current_all_open_orders` (already a declared signed method). The installed SDK builds the timestamp inside `binance_common.utils.send_request` with `get_timestamp()`; the adapter replaces that module function only for the duration of the call (context manager, always restored) with a wrapper that subtracts a thread-local offset, set only in the worker thread of this one call, so no other thread is ever made stale. The answer carries `clock_calls`; when it is 0 (an SDK change would do that) the case ends NOT_OBSERVED instead of drawing a false conclusion. The contract test drives the real installed SDK `send_request` with a fake session (no network) and shows the stale timestamp in the query string; another test pins the SDK source line the replacement depends on. The change is contained in the probe adapter; no production module changed.

## Cases that can end NOT_OBSERVED (and which are best effort)

No case is a stub. Best effort, may stay NOT_OBSERVED on Demo: `stop_rejected_after_acceptance` (the price must reach the trigger), `trigger_cancel_race` (OBSERVED even when nothing triggered: it says the cancel won; NOT_OBSERVED only when no stop could be placed), `insufficient_margin_order` (NOT_OBSERVED if the quantity did not exceed the margin), `income_history_read` (NOT_OBSERVED when the window holds no row), `reduce_only_market_larger_than_position` (NOT_OBSERVED when the half entry is rejected, for example -4164, or too small). Always answerable: `reduce_only_market_on_flat`, `non_reduce_only_below_min_notional` (unless the filters make the order impossible), `timestamp_outside_recv_window` (unless the clock offset or the SDK clock cannot be honoured).

## Deviations from Plan

**1. [Interpretation] recvWindow.** The task said "the smallest allowed recvWindow". The project documents no minimum, so the ratified `signed_calls.recv_window_ms` is used and the timestamp is 2 x that behind. This is stated in `recv_window_note` and the runbook.

**2. [Scope change from the coordinator] Eighth case.** `insufficient_margin_order` was added during the task at the owner's request (the Demo wallet makes exceeding the normal cap harmless) with its own key and bound; -2019 was removed from "Not covered here". `income_history` stays right before `gtd_expiry` as asked; `insufficient_margin` sits fourth.

**3. [Rule 3 - pin updates]** `EVIDENCE_CASE_KEYS` tuple and the `DemoOrderLimits(...)` construction (new required field `insufficient_margin_quantity`, no default) in `tests/test_operator_evidence.py`; `EXPECTED_ORDER`, `ALL_OPTIONAL`, `SJ2_CASES` slice in `tests/test_demo_probe_cases.py`; the guarded reads count 19 to 20 in `tests/test_demo_probe_cli.py`; the coroutine-name set, the ban lists (`_READ_AND_MUTATING_CALLS`, `_READ_CALLS`) and the "one send site" pin (`to_thread` twice: `_call` and the one stale call) in `tests/test_binance_probe.py`; `_OPERATIONS` in `tests/test_binance_probe_contract.py`; `FIXTURE_CASES` and the session values in `tests/test_demo_probe_sj1_cases.py`; `make_config` and `run_cases` of `tests/test_demo_probe_capture_cases.py` got an optional `replace` argument (additive); `write_probe_limits` of `tests/probe_fakes.py` writes the new keys.

**4. [Plan detail] Commit gate.** Same as sj0 and sj1: the per-commit assertion allows only `agent-*` branches in a worktree; the assigned branch is `p20-sj2`. Before every commit I verified the toplevel `C:/Users/admin/Music/Trading/.claude/worktrees/p20-sj2`, an attached HEAD `refs/heads/p20-sj2`, not detached and not a protected branch.

**5. [Plan detail] No minimum-notional precheck of the half entry.** `reduce_only_oversize` and `stop_reject_after_accept` do not check that the half entry meets MIN_NOTIONAL; if the exchange rejects it the case ends NOT_OBSERVED with `entry rejected: <class> <code>` (the entry answer is recorded). A pre-check would hide a real answer.

**6. [Plan detail] `flatten` is bounded.** The new `_WriteCase.flatten` (signed, opposite side) is bound-checked like every capped order. Only the margin case could hold a position larger than the cap; it leaves that to the runner cleanup (unbounded by design).

### Auth gates

None.

## Verification actually run (offline, `TRADING_CI_STRICT=1`, `TEST_DATABASE_URL` from the environment, not echoed; `-n 4` for the non-gate files)

- `uv run pytest` on tests/test_demo_probe_sj2_cases.py (67 tests), test_demo_probe_sj1_cases.py, test_demo_probe_capture_cases.py, test_demo_probe_cases.py, test_demo_probe_cli.py, test_demo_probe_evidence.py, test_binance_probe.py, test_binance_probe_contract.py, test_binance_public.py, test_operator_evidence.py, test_user_data_smoke_cli.py, test_user_data_smoke_dry_run.py, test_user_data_smoke_evidence.py, test_agents_md.py, test_phase18_gate.py, test_phase19_gate.py, test_phase20_gate.py, test_persistence_exit_evidence_pg.py: 1196 passed, 1 skipped (the pre-existing Windows symlink test).
- `uv run mypy src`: no issues in 235 source files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 738 files already formatted. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- Offline dry run of the probe against fakes with every key on (`/tmp/p20/sj2/dry/limits.toml`: all 23 evidence keys true, quantity 0.002, cap 150, `insufficient_margin_quantity` 5): exit 0, `outcome: COMPLETE`, `acceptance: FAIL` (FAKE evidence never passes), 39 cases all NOT_REHEARSED, no ERROR, the eight new cases listed in order before `gtd_entry_expiry_status`, planned requests of the seven capped cases at most 0.002 and the margin case's one planned order at 5.
- The full suite was not run (orchestrator's job). `pyproject.toml`, `uv.lock`, `docs/DECISIONS.md`, `config/binance/`, `params/`, STATE, ROADMAP and REQUIREMENTS are untouched; no requirement was marked complete.

## RED evidence (honest)

- Adapter and contract: 29 tests failed (`AttributeError: no attribute 'stale_timestamp_read'`) in tests/test_binance_probe.py and tests/test_binance_probe_contract.py before `binance_probe.py` changed. After the code, one more existing test failed (the "one send site" pin) and was updated.
- Loader: 20 tests failed in tests/test_operator_evidence.py before the loader changed.
- Cases: I wrote tests/test_demo_probe_sj2_cases.py before the handlers but did not run it before writing them. RED was shown afterwards by swapping the commit-1 `scripts/demo_probe.py` and `src/ops/operator_evidence.py` (from `git show HEAD:`) over the new tests and restoring the files from saved copies: 62 of the 67 sj2 tests failed (the 5 that pass need no new code), 4 in tests/test_demo_probe_cases.py and 20 in tests/test_operator_evidence.py; with the new code all pass. The runbook tests failed (3 of the sj2 file, 5 of the sj1 file) before the runbook edit, as the first full run showed.
- A first attempt to patch test files through a Python script lost backslash escapes (the tool collapsed `\\`), producing broken files; those were discarded (`git checkout`) and redone, so no committed file carries that failure.

## Known Stubs

None. Every `<OWNER: ...>` in the runbook is an intentional owner placeholder.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: sdk-clock-replacement | src/adapters/binance_probe.py | For the duration of one read-only signed call the adapter swaps the SDK function `binance_common.utils.get_timestamp` for a wrapper that is stale only in the worker thread of that call and always restores the original. No credential is touched; a change of the SDK would make the case NOT_OBSERVED (`clock_calls` 0), not wrong. |
| threat_flag: cap-exception-order | scripts/demo_probe.py | `insufficient_margin_order` sends an order above the notional cap by design (owner key `insufficient_margin_quantity`). Bound: enabled key, exactly the owner quantity, step grid, price at or below the far price (below the mark, it can only rest), flat precheck, LOT_SIZE range, cleanup flattens any fill; opt-in, one-way, never retried. |
| threat_flag: more-probe-orders | scripts/demo_probe.py | Six new cases send orders on Demo (at most the approved quantity each, bound-checked first, never retried; `race_repeats` at most 5, one position open at a time), all opt-in by owner key. |

## Findings for later work

- `income_history_read` uses the exchange default limit (no `limit` parameter in the adapter); a run with more than that many rows shows the first rows only.
- The fake `stale_timestamp_read` answers -1021 with category `CLOCK_SKEW` (the project taxonomy name for -1021).
- `reduce_only_market_larger_than_position` and `stop_rejected_after_acceptance` open a half-size position; with an approved quantity of one lot step they are NOT_OBSERVED by design.

## Exact commands for the owner

1. Create your limits file `.planning/phases/19-execution-plan-binding-price-check/decisions/19-probe-limits.toml` from the template under "One session: all cases" of `.planning/DEMO-EVIDENCE-PLAN.md`. Replace every `<OWNER: ...>` (including `insufficient_margin_quantity`, a whole quantity on the step grid large enough to exceed your available margin at the account's leverage); every number is yours.
2. Dry run (offline): `uv run python -m scripts.demo_probe --environment DEMO --probe-limits-file .planning/phases/19-execution-plan-binding-price-check/decisions/19-probe-limits.toml --evidence-dir <a temporary directory>`
3. Smoke re-run (Step 2 of the runbook), then one session of all enabled cases, typed phrase `DEMO PROBE BTCUSDT`:
   `uv run python -m scripts.demo_probe --environment DEMO --probe-limits-file .planning/phases/19-execution-plan-binding-price-check/decisions/19-probe-limits.toml --evidence-dir .planning/phases/19-execution-plan-binding-price-check/evidence --fixtures-dir .planning/phases/19-execution-plan-binding-price-check/evidence/fixtures --execute`
4. Or one case at a time: add `--only reduce_only_market_on_flat` (or any other new case id) to the same command. Read the fixtures before any of them enters git (the account captures hold account values).

## Self-Check: PASSED

- Files: `scripts/demo_probe.py`, `src/ops/operator_evidence.py`, `src/adapters/binance_probe.py`, `tests/probe_fakes.py`, `tests/test_demo_probe_sj2_cases.py`, `.planning/DEMO-EVIDENCE-PLAN.md` and the PLAN of this task exist in the worktree.
- Commits 9025ea96 (plan), f115d313 (stale read) and ae70c0b3 (cases, loader, runbook) exist on branch p20-sj2.
