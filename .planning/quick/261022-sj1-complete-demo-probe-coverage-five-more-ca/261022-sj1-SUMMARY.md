---
phase: quick-261022-sj1
plan: 01
subsystem: demo-probe
tags: [demo-probe, evidence-capture, binance-demo, owner-run, partial-fill, gtd, stream-loss]
requires: [quick-261021-sj0]
provides:
  - "five owner opt-in Demo probe cases (SJ1_CASES) in scripts/demo_probe.py"
  - "ProbePort.server_time and ProbePort.order_book (adapter, guarded port, both fakes)"
  - "owner-file keys exchange_info_read, gtd_min_lifetime, partial_fill_attempt, cancel_fill_race, stream_loss and race_repeats"
  - ".planning/DEMO-EVIDENCE-PLAN.md sections 11 to 15, 'One session: all cases', updated 'Not covered here'"
affects: [phase-19-owner-gaps, phase-20-deferred, phase-25]
requirements-addressed: [O-05]
key-files:
  created:
    - tests/test_demo_probe_sj1_cases.py
  modified:
    - scripts/demo_probe.py
    - src/ops/operator_evidence.py
    - src/adapters/binance_probe.py
    - src/adapters/binance_public.py
    - tests/probe_fakes.py
    - tests/test_operator_evidence.py
    - tests/test_binance_public.py
    - tests/test_binance_probe.py
    - tests/test_binance_probe_contract.py
    - tests/test_demo_probe_cases.py
    - tests/test_demo_probe_cli.py
    - .planning/DEMO-EVIDENCE-PLAN.md
decisions:
  - "Key names: exchange_info_read, gtd_min_lifetime, partial_fill_attempt, cancel_fill_race, stream_loss (race_repeats is in [order]). The five keys sit before gtd_expiry in EVIDENCE_CASE_KEYS and CASE_ORDER, so the only case that waits more than ten minutes still runs last."
  - "RACE_REPEATS_MAX = 5 (my number: a cap on probe orders, the prompt only asked for a small bound)."
  - "The 'touch price' of entry_cancel_fill_race is the best ask (the price a BUY executes against); it must lie within the owner far_price_fraction band, else the case stops."
  - "stream_loss_during_case is implemented (not a stub): the existing drop_stream_transport mechanism is safe to reuse, so no NOT_OBSERVED stub was needed."
status: complete
plan_head_before: 4b8b71dbe912b115eab515b1611eef348ab2fe82
plan_head_after: b91d0651028108ba665dba992bc09f97f5565e28
commits: 4
actuals:
  tokens: 36000
  tasks: 3
  commits: 4
---

# Quick Task 261022-sj1: five more Demo probe cases Summary

Five more owner opt-in Demo probe cases on the sj0 framework (P3, P5, P7, A1 boundary, A10), two new unsigned port reads (server time, order book depth), the loader key `race_repeats`, and the owner session template. Nothing was executed against Binance: no `--execute`, no network call, no Binance or Telegram contact. Evidence label: fakes only; nothing here is `[DEMO]`. `commits` counts the plan commit and the three work commits up to `plan_head_after`; the commit of this SUMMARY comes after it.

## What was built

- **Cases** (`scripts/demo_probe.py`, each only when its own key is true, each NOT_REHEARSED in a dry run, hedge mode NOT_OBSERVED with nothing sent for the four that send orders, every order bound-checked by `order_bound_refusal` through `_WriteCase` before the first send, nothing retried, the runner cleanup cancels and flattens after the case):
  - `exchange_info_read_for_close` (key `exchange_info_read`): no order. One `symbol_filters` read timed on the rig clock; LOT_SIZE, MARKET_LOT_SIZE, PRICE_FILTER (tick only) and MIN_NOTIONAL values; comparison with the filters the run read at its start (`matches_run_start_snapshot`, `snapshot_differences`).
  - `gtd_min_lifetime_boundary` (key `gtd_min_lifetime`): two far BUY GTD entries at the approved quantity, `goodTillDate` = public server time + 599 s and + 601 s (`GTD_BOUNDARY_MARGINS_SECONDS`), the server time read right before each send. Records server time, local clock before and after the read, `local_minus_server_ms`, the margin, the value sent minus server and minus local clock, accept or reject and the exact error code, class, category and message; an accepted order is cancelled at once; never waits.
  - `partial_fill_attempt` (key `partial_fill_attempt`): depth read, then ONE BUY LIMIT of the approved quantity at `min(marketable price, floor(cap / quantity))`; nothing is sent when that price does not reach the best ask. Records the raw status and quantities, cancels the remainder, queries again, flattens. OBSERVED only when a partial fill was seen (status, executed strictly between 0 and original, or a PARTIALLY_FILLED frame); else NOT_OBSERVED with the reason `no partial fill produced`.
  - `entry_cancel_fill_race` (key `cancel_fill_race`, `race_repeats`): per repeat a depth read, one BUY LIMIT at the best ask, an immediate cancel, one final status query, an immediate reduce-only MARKET close of any fill. Records the cancel code, the final status, the fill and an outcome string per repeat plus tallies. The evidence says plainly that it does not reproduce a deterministic race.
  - `stream_loss_during_case` (key `stream_loss`): drops the stream first with the existing `drop_stream_transport` (nothing is sent if the drop is not possible), then a marketable entry and a closePosition stop while the stream is down, REST reads, one wait for LIVE, then compares REST with what the stream delivered after the drop (`entry_fill_frame_delivered`, `stop_frame_delivered`, `comparison_entry`, `comparison_stop`). NOT_OBSERVED when the stream does not return.
- **Reads**: `BinancePublicMarketData.order_book` (unsigned `GET /fapi/v1/depth`, Decimal levels, malformed answer raises), `BinanceProbeAdapter.server_time` and `.order_book` (observations, refused during a ban); `check_server_time` and `order_book` bound to the installed SDK by the contract test. `ProbePort`, `GuardedProbePort`, `FakeProbePort` and `RecordingProbePort` carry both.
- **Loader**: five new `EVIDENCE_CASE_KEYS`, `race_repeats` (positive int, required exactly with `cancel_fill_race`, at most `RACE_REPEATS_MAX`, refused otherwise, messages never carry the value), `DemoOrderLimits.race_repeats` (a required field, no default: an existing test pins "no default"). The real 18-probe-limits file loads to the same values (pinned).
- **Evidence**: `settings.race_repeats` added (schema id `demo-probe-evidence/schema-1` unchanged); the REST answers of the five cases are written as `<case_id>-rest-<NNN>-<operation>.json` in an executed run (`FIXTURE_CASES`).
- **Runbook**: sections 11 to 15, "One session: all cases" (ordered ids with keys, a complete limits TOML where every key is on and every number is `<OWNER: ...>`, the single command without `--only`), consumers table rows, "Not covered here" updated (P3, P5, P7 best effort, P3 and P7 may stay NOT_OBSERVED; no case for the 418 duration or the 429 queue order, by the owner decision not to provoke a ban). Nothing true was removed.

## Cases that can only ever answer NOT_OBSERVED (or an answer that is not the full question)

- **`partial_fill_attempt`**: NOT_OBSERVED whenever Demo fills the approved quantity completely, fills nothing, rejects, or the cap keeps the price below the best ask. The tool never raises the quantity, so on a deep Demo book it may never produce a partial fill (P3, A5 stay unproven there).
- **`entry_cancel_fill_race`**: the case is OBSERVED when cancels were answered, but what it observes is a sample of cancel answers at the touch (-2011, FILLED, CANCELED). It cannot reproduce or prove the order of a cancel crossing a fill in flight, nor a stop triggering during a cancel (P7 stays open).
- **`stream_loss_during_case`**: NOT_OBSERVED when no stream runs, the drop is not possible, the entry does not fill, or the stream does not come back within one `case_timeout_seconds`. It cannot cover a stream lost for longer than that, nor a stop rejected or timed out under a lost stream. Also not rehearsable in a dry run (no stream): NOT_REHEARSED with no planned requests.
- Always answerable: `gtd_min_lifetime_boundary` (accept or reject is the answer; which clock the rule uses is only inferable when the clocks differ by more than about the 2 s gap) and `exchange_info_read_for_close` (PRICE_FILTER minPrice and maxPrice are not exposed by the project port and are recorded as NOT_OBSERVED).

## Deviations from Plan

**1. [Plan structure] Task 1 split across two commits.** The loader keys changed `EVIDENCE_CASE_KEYS`, which `tests/test_demo_probe_cases.py` pins against `OPTIONAL_CASES`; committed alone they would have left a red commit. Commit 42b6f39c holds the two port reads (public reader, adapter, contract); the loader went into the Task 2 commit 487ebb9f with the cases. Three work commits instead of the plan's three tasks as drawn, all green.

**2. [Rule 3 - Blocking] A public read had to be added to `src/adapters/binance_public.py`.** The prompt asked for the book depth; no depth read existed. I added `order_book` and the dataclass `OrderBookReading` there (the gated public reader, like `mark_price`) and the name `order_book` to `ALLOWED_REST_CALLS` of the public-surface AST test (a pin, public market data only). No other module of the paper path changed.

**3. [Rule 1 - pin updates]** `tests/test_demo_probe_cases.py` (`EXPECTED_ORDER`, `ALL_OPTIONAL`, and `CAPTURE_CASES == EXPECTED_ORDER[19:]` became "the sj0 ten in relative order" plus `SJ1_CASES == EXPECTED_ORDER[28:33]` and GTD last); `tests/test_demo_probe_cli.py` (guarded reads 17 to 19); `tests/test_operator_evidence.py` (the key tuple, `race_repeats=None` in the direct `DemoOrderLimits(...)` construction because the "no default value" test forbids a default); `tests/test_binance_probe.py` (coroutine set, ban list); `tests/test_binance_probe_contract.py` (`PUBLIC_SDK_METHODS`, operations, payloads); `tests/test_binance_public.py` (`ALLOWED_REST_CALLS`). The sj0 capture tests and `test_demo_probe_evidence.py` needed no change.

**4. [Plan detail] Fake default summaries extended additively**: `FakeProbePort.new_limit_order` now answers `orig_qty` and `executed_qty`, and `query_order` adds them when known. No existing assertion needed a change.

**5. [Plan detail] Commit-gate branch allow-list**, same as sj0: the per-commit assertion allows only `agent-*` style branches in a worktree; the assigned branch is `q-sj1`. Before every commit I verified the toplevel `C:/Users/admin/Music/Trading/.claude/worktrees/q-sj1`, an attached HEAD `refs/heads/q-sj1`, not detached, not a protected branch. Commits: 294fb0c0, 42b6f39c, 487ebb9f, b91d0651.

**6. [Interpretation] `touch price` = best ask**, and `far_price_fraction` still applies as a band check around the mark (`far_below` to `far_above`); a touch outside it stops the case with nothing sent. The alternative (best bid) would mostly yield CANCELED and never -2011 or FILLED.

**7. [Interpretation] `stream_loss_during_case` does a real fill during the gap** (marketable entry, closePosition stop), not a far resting order, because the production cycle is fill-driven; it opens at most the approved quantity and the runner cleanup flattens it.

**8. [Plan detail] `GTD_BOUNDARY_MARGINS_SECONDS = (599, 601)`** are the two numbers of the task statement, kept as a named tool constant (a test pins it); the 600 s floor itself is not a constant in the code.

### Auth gates

None.

## Verification actually run (offline, `TRADING_CI_STRICT=1`, `TEST_DATABASE_URL` from the environment, not echoed)

- `uv run pytest` on tests/test_demo_probe_sj1_cases.py (55 tests), test_demo_probe_capture_cases.py, test_demo_probe_cases.py, test_demo_probe_cli.py, test_demo_probe_evidence.py, test_binance_probe.py, test_binance_probe_contract.py, test_binance_public.py, test_operator_evidence.py, test_phase18_gate.py, test_phase19_gate.py, test_persistence_exit_evidence_pg.py, test_user_data_smoke_cli.py, test_user_data_smoke_dry_run.py, test_user_data_smoke_evidence.py, test_agents_md.py: all passed; the one skip is the pre-existing Windows symlink test of test_user_data_smoke_dry_run.py.
- `uv run mypy src`: no issues in 235 source files. `uv run ruff check`: all checks passed. `uv run ruff format --check`: 728 files already formatted. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `git diff 4b8b71db -- .planning/phases/18-user-data-stream-error-taxonomy/decisions/` is empty (Phase 18 owner TOML files unchanged); `19-probe-limits.toml` and its `decisions/` directory do not exist.
- The full suite was not run (orchestrator's job).

## RED evidence (honest)

- Loader: 17 new or changed tests in `tests/test_operator_evidence.py` failed before the loader code (key tuple, `race_repeats`, smoke refusals). A first attempt to apply that test edit by a `python3` script silently did nothing on this machine (no `python3`), so the first pytest run showed passing dots from the old tests; the real RED run came after the edit was redone with the Edit tool.
- Public `order_book`: 3 failed (`AttributeError`) before `binance_public.py` changed.
- Adapter reads and contract: 17 failed or errored before `binance_probe.py` changed.
- Script: `tests/test_demo_probe_sj1_cases.py` had 49 failed (all but one) before the script code. As a second check after the work, the old `scripts/demo_probe.py` and `src/ops/operator_evidence.py` (from HEAD of the plan commit) were swapped in over the new tests and restored byte-identical: 49 failed in the sj1 file, 4 in test_demo_probe_cases.py, 1 in test_demo_probe_cli.py, 18 in test_operator_evidence.py.
- Runbook: the 5 runbook and session tests failed before the runbook edit.
- Not independently RED: the guarded-port lines (17 to 19 reads) in test_demo_probe_cli.py were added after the delegation existed; their only RED is the old-script swap above (1 failed). Test-side bugs fixed along the way, not code bugs: a hook of my `GapPort` fixture that ran at the entry wait and raised `StopIteration`, a missing `mkdir` for sub-directories, and Decimal text formats (`55000` against `55000.00`).

## Known Stubs

None. Every `<OWNER: ...>` in the runbook is an intentional owner placeholder.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: new-public-read | src/adapters/binance_public.py, src/adapters/binance_probe.py | Two unsigned public reads were added to the probe: `GET /fapi/v1/depth` (through the gated public reader, so a ban or pause refuses it) and the already existing `GET /fapi/v1/time`. They carry no credential. |
| threat_flag: more-probe-orders | scripts/demo_probe.py | Four new cases send orders on Demo (at most the approved quantity each, bound-checked first, never retried; `race_repeats` is at most 5). All are opt-in by owner key, one-way mode only, dry-run unreachable, and the runner cleanup cancels and flattens after each. |

## Findings for later work

- `PRICE_FILTER` minPrice and maxPrice are not in `SymbolFilters`; if the A10 comparison needs them, the public reader would have to expose them.
- The dry run cannot rehearse `stream_loss_during_case` (no stream): its serialized status is NOT_REHEARSED with an empty planned-request list.
- The order cases pass `reduce_only=True` to `run_write_case` only to get the hedge-mode refusal (as sj0's GTD case does), although none of them sends a reduce-only order except the flatten.
- `partial_fill_attempt` prices with the same halfway-to-the-PERCENT_PRICE-edge rule the entry cases use (the first live probe met -4016 at the edge); a different crossing price is the owner's call.

## Exact next steps for the owner

1. Add the keys you want (and `race_repeats` if `cancel_fill_race` is on) to your `19-probe-limits.toml` from the layout in Step 0 or the example in "One session: all cases" of `.planning/DEMO-EVIDENCE-PLAN.md`; every number is yours.
2. Dry run (Step 1), then the smoke re-run (Step 2).
3. Run the cases one by one with `--only` or the whole session with the single command of "One session: all cases"; phrase `DEMO PROBE BTCUSDT`.
4. Read the fixtures before any of them enters git (the account captures hold account values).

## Self-Check: PASSED

- Files: `scripts/demo_probe.py`, `src/ops/operator_evidence.py`, `src/adapters/binance_probe.py`, `src/adapters/binance_public.py`, `tests/probe_fakes.py`, `tests/test_demo_probe_sj1_cases.py`, `.planning/DEMO-EVIDENCE-PLAN.md` and the PLAN of this task exist in the worktree.
- Commits 294fb0c0, 42b6f39c, 487ebb9f and b91d0651 exist on branch q-sj1.
