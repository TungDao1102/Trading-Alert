---
phase: 16-paper-runtime-composition
plan: 24
subsystem: paper-runtime / per-closed-bar pipeline
tags: [paper-runtime, bar-pipeline, source-tag-rule, q-d, history-only, heartbeat, sibling-hold]

requires:
  - phase: 16-paper-runtime-composition
    provides: "16-08 vocabulary (SourceTag, TaggedBar, GapReason, DropReason); 16-10 evaluate_closed_bar, BarBuffers, group_by_close, decision surface; 16-16 RuntimeRecord and RuntimeStatePort"
provides:
  - "src/paper/pipeline.py: BarPipeline, PipelineResult, DroppedBar, HeldBar; one PAPER_BAR_PROCESSED heartbeat per processed closed bar and PAPER_GAP records for skipped closes"
  - "Q-D rule implemented exactly as decided: REST_BACKFILL bars are history-only (decisions/16-DEC-Q-D.md, option history-only)"
  - "src/paper/surface.py: gate_record, context_record, outcome_record, feature_digest (one outcome-to-record mapping shared by replay and live)"
affects: [16-26 runtime loop, 16-27 O-07 table, 16-29 restart, 16-15 coverage, 16-25 trial evaluator]

actuals:
  tokens: 15500
  tasks: 3
  commits: 5
plan_head_before: 577767b5b88a19ff7d7c4de06bc3fc6020ea766a
plan_head_after: f0ff6a3923e97ab0623cb35d9eda51bb673feb4d
commits: 5

tech-stack:
  added: []
  patterns:
    - "Pure stateful pipeline: tick time injected, no clock, no sleep; a hold is returned as data (HeldBar with deadline) and re-submitted by the caller"
    - "Strongest-source copy of a bar wins inside a batch (LIVE_WS over REST_BACKFILL over REST_WARMUP), so records never depend on arrival order"
    - "Fail closed on history holes: a live bar is recorded as a feed-gate reject, never evaluated on guessed state"

key-files:
  created:
    - src/paper/pipeline.py
    - tests/test_paper_runtime_pipeline.py
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-D.md
  modified:
    - src/paper/surface.py

key-decisions:
  - "Q-D (user): option history-only. REST_BACKFILL bars only extend history in time order, are never evaluated, and each skipped close is one PAPER_GAP with the existing GapReason.WS_RECONNECT_WINDOW. No backfill_eval_max_age_seconds key and no age or freshness exception exists."
  - "A backfill gap is written with a deterministic payload (expected close, reason, source; no tick time) so a replayed gap is the same record; no HEALTH_STATE_CHANGED or LIVE_WS heartbeat is written because a backfill succeeded"
  - "Continuity gate: the last WARMUP_MIN_BARS 1h bars before a live bar and the last WARMUP_MIN_BARS 4h bars must be contiguous, and the latest 4h bar must not be a whole 4h cycle behind; otherwise the live bar is a recorded feed-gate reject HISTORY_DISCONTINUITY"
  - "The 4h sibling is 'due' when the latest known 4h close plus 4h equals the live 1h close (cadence read from history, no calendar), because the Phase 7 fixture 4h bars are not on the UTC 00/04/08 grid"
  - "A fetched 4h sibling is context only and is handled like a backfilled bar (history plus one PAPER_GAP WS_RECONNECT_WINDOW); a missing sibling at the deadline is one PAPER_GAP EXCHANGE_NO_CANDLE on the 4h close plus a SIBLING_4H_MISSING feed-gate heartbeat for the 1h bar"
  - "fetch_4h_bar is a required constructor keyword next to sibling_4h_wait_seconds (neither has a default)"

requirements-completed: [PAPER-01]

coverage:
  - id: D1
    description: "A closed LIVE_WS 1h bar after REST warm-up is evaluated once and recorded as one replayable PAPER_BAR_PROCESSED heartbeat whose surface equals the offline replay; warm-up and forming bars never evaluate; duplicates write nothing"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_pipeline.py#test_live_bar_after_warmup_is_evaluated_once_and_recorded"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_pipeline.py#test_warmup_bars_only_extend_history_and_a_forming_bar_never_evaluates"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_pipeline.py#test_a_duplicate_live_bar_is_reported_and_writes_nothing"
        status: pass
    human_judgment: false
  - id: D2
    description: "A bar closing after the tick time is reported as FUTURE_CLOSE with its delta in milliseconds, neither evaluated nor recorded"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_pipeline.py#test_a_bar_closing_after_the_tick_time_is_reported_as_future_close"
        status: pass
    human_judgment: false
  - id: D3
    description: "Q-D history-only: backfill bars extend history, never reach evaluate_closed_bar, each close is one PAPER_GAP WS_RECONNECT_WINDOW, duplicates are idempotent, mixed batches decide per bar, live bars after reconnect are processed normally, and an unreconciled hole fails closed"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_pipeline.py#test_backfill_only_batch_extends_history_and_records_one_gap_per_close"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_pipeline.py#test_mixed_batch_decides_per_bar"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_pipeline.py#test_duplicate_backfill_bars_create_no_record_and_no_state_change"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_pipeline.py#test_live_bars_after_a_successful_reconnect_are_processed_normally"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_pipeline.py#test_an_unreconciled_hole_fails_closed_until_history_is_filled"
        status: pass
    human_judgment: false
  - id: D4
    description: "4h sibling hold with a required wait and fetch, EXCHANGE_NO_CANDLE gap, and byte-identical records for every arrival order"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_pipeline.py#test_a_1h_bar_waits_for_its_4h_sibling_and_is_evaluated_after_it"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_pipeline.py#test_at_the_deadline_the_sibling_is_fetched_once_and_a_missing_one_is_a_gap"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_pipeline.py#test_every_arrival_order_of_one_group_gives_byte_identical_records"
        status: pass
    human_judgment: false
  - id: D5
    description: "Real feed behaviour (a live WS drop, reconnect and REST backfill against Binance) is not exercised; fake-level green never closes PAPER-01 (SC9). Evidence comes from the trial soak (plans 16-43, 16-44)."
    requirement: PAPER-01
    human_judgment: true
    rationale: "Needs the soak; no unit test can assert live exchange behaviour"

duration: 3h wall clock including the wait for the Q-D decision (about 45 min of work)
completed: 2026-10-10
status: complete
---

# Phase 16 Plan 24: Per-closed-bar pipeline Summary

**`BarPipeline` turns the supervisor's tagged bars into one replayable heartbeat per processed closed bar: only closed LIVE_WS 1h bars are evaluated, REST warm-up and (by the user's Q-D decision "history-only") REST backfill bars only extend history, every skipped close is one `PAPER_GAP`, and a history hole or a missing 4h sibling fails closed.**

## Q-D record

- Decision file: `.planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-D.md`
- **Recorded option: `history-only`**, decided by the user on 2026-10-10 ("Chọn Option 1: history-only." and "Đồng ý. Quyết định này nhất quán với CONTEXT D-06.").
- **Configuration key: none.** Option `fresh-within-bound` was not chosen, so `backfill_eval_max_age_seconds` does not exist anywhere (a test greps `src/` for it). Plans 16-26 and 16-27 add no key for this rule.
- The rule applies to SHADOW and paper evidence and must not change during the soak without a separate user decision.

## Accomplishments

- **Tracer (Task 1):** `src/paper/pipeline.py` with `BarPipeline.handle(bars, *, now_utc)`. A closed `LIVE_WS` 1h bar passes `check_feed_freshness`, `check_feature_validity` (both called from `src/paper/loop.py`) and `evaluate_closed_bar`, then writes one `PAPER_BAR_PROCESSED` keyed through `runtime_event_id` with `occurred_at_utc` equal to the bar close. The payload carries `source`, `tick_time_utc`, the bar fields, stage, reason code, plan hash and the full decision-surface dict; a test proves the surface equals the offline `decision_surface` replay of the same bar. `LIVE_WS` 4h bars write a context record. A bar closing after the tick time lands in `PipelineResult.dropped` as `DroppedBar(reason=FUTURE_CLOSE, delta_ms)` and is neither recorded nor added to history.
- **Q-D rule (Task 3):** `REST_BACKFILL` bars are added to history in time order and never evaluated (spy proves they never reach `evaluate_closed_bar`: no signal, plan, approval or reservation). Each such close is exactly one `PAPER_GAP` with `GapReason.WS_RECONNECT_WINDOW` and a deterministic payload; nothing is written that could read as HEALTHY. A duplicate REST bar (already accepted from any source) creates no record and no state change. The interim `UndecidedSourceRule` refusal from the tracer commit is gone.
- **Mixed batches:** decided per bar. When a batch holds several copies of one bar the strongest source wins (LIVE_WS over REST_BACKFILL over REST_WARMUP); a conflicting copy raises `ValueError`. A live bar after a backfill in the same batch is evaluated because the backfilled bars already sit in the history in time order.
- **Fail closed:** the live gate chain is freshness, warm-up minimum, then a continuity gate. A hole in the last 200 1h or 4h bars, or a latest 4h bar a whole cycle behind, gives a recorded feed-gate heartbeat `HISTORY_DISCONTINUITY` and no evaluation; filling the hole (for example by a REST warm-up of the missing closes) resumes evaluation.
- **4h sibling:** at a shared close a live 1h bar without its 4h sibling is returned as `HeldBar` with deadline close + `sibling_4h_wait_seconds` and changes no state. The caller re-submits it. At the deadline `fetch_4h_bar(symbol, close)` is tried once; a fetched bar is context only (history plus one gap); if it is still missing, one `PAPER_GAP EXCHANGE_NO_CANDLE` for the 4h close is written and the 1h bar is recorded as a `SIBLING_4H_MISSING` feed-gate reject. `sibling_4h_wait_seconds` and `fetch_4h_bar` are required constructor inputs without defaults (TypeError test plus an AST check).
- **Arrival-order independence:** all 24 permutations of a group (4h, live 1h, duplicate 1h, warm-up bar) give byte-identical records and the same evaluated set.
- `src/paper/surface.py` gained `gate_record`, `context_record`, `outcome_record` and a public `feature_digest`; `decision_surface` now uses them, so replay and live share one outcome-to-record mapping. Behaviour is unchanged (existing decision-surface, bars, parity and float-guard tests pass).

## RED Evidence

- **Task 1** (`2db1b4c`): collection failed with `ImportError: cannot import name 'pipeline' from 'src.paper'`. GREEN `5c83bba`: 9 tests pass.
- **Task 3** (`af43f40`): the whole file failed with `TypeError: BarPipeline.__init__() got an unexpected keyword argument 'fetch_4h_bar'`. GREEN `f0ff6a3`: 29 tests pass.

## Task Commits

1. **Task 1 (tracer):** `2db1b4c` (test, RED), `5c83bba` (feat, GREEN)
2. **Task 2 (decision):** `a81e1bb` (docs, Q-D record)
3. **Task 3:** `af43f40` (test, RED), `f0ff6a3` (feat, GREEN)

## Verification

- `tests/test_paper_runtime_pipeline.py`: 29 passed. Related suites (decision surface, bars, float guard, start gate, parity) pass.
- `ruff check`, `ruff format --check` (485 files) and `mypy src` (170 files) are clean.
- Full `pytest -m "not docker"`: everything passes except `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments`, a failure already logged in `deferred-items.md` by plan 16-15 (`[]` versus `()` for `open_positions`). This plan touches neither `src/paper/loop.py` nor the simulator (`git diff 577767b -- src/backtest src/paper/loop.py` is empty).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree created at a stale base**
- **Found during:** start
- **Issue:** the worktree was at 9186194, without this plan or the code of plans 16-08, 16-10 and 16-16.
- **Fix:** `git merge --ff-only 577767b` (tip of `develop`) inside the worktree; no commit was lost. `uv sync --frozen --extra dev` created `.venv`.

**2. [Rule 3 - Blocking] `src/paper/surface.py` edited although not in `files_modified`**
- **Issue:** the pipeline needs a per-bar mapping from `BarOutcome` to the surface record; only the whole-series `decision_surface` existed.
- **Fix:** extracted `gate_record`, `context_record`, `outcome_record`, `feature_digest` (behaviour unchanged).
- **Commit:** 5c83bba

**3. [Rule 2 - Missing critical] New feed-gate reason codes and the continuity gate**
- **Issue:** the ratified rule requires "reconciliation, continuity and warm-up/state validation" before live evaluation resumes and "fail closed rather than guess"; no existing gate detected a hole in history.
- **Fix:** the `HISTORY_DISCONTINUITY` and `SIBLING_4H_MISSING` feed-gate reason codes (surface strings like `DUPLICATE_BAR`, not a new `GapReason`). The continuity span reuses `WARMUP_MIN_BARS`, so no new number was introduced.
- **Commit:** f0ff6a3

**4. [Rule 2 - Design] Stale 4h bars are not turned into DATA_STALE rejects**
- The freshness gate runs only for 1h bars that could be evaluated; 4h bars never produce signals. `run_paper_tick` applies it to every event.

**Total deviations:** 4 (2 Rule 3, 2 Rule 2). **Impact:** no change to `src/paper/loop.py` or the backtest; no ratified decision altered.

## Points for the next plans

- Plan 16-26 (runtime loop) must re-submit `PipelineResult.held` at each deadline, journal `PipelineResult.dropped` counts and pass the supervisor's own `GapRecord`s to the state port. A PAPER_GAP the supervisor writes for a close this module also gaps (same epoch, symbol, interval, close) must carry the same payload, otherwise `RuntimeRecordConflict` is raised (fail loudly). The gap payload written here is `expected_close_utc`, `reason`, `source`.
- Plan 16-29 (restart) must seed the dedup from the state port: `_seen` is in memory, so a restart relies on re-warm-up and the idempotent record ids, and a live bar re-delivered after a restart whose heartbeat already exists would be re-evaluated and hit `RuntimeRecordConflict` if its content differs.
- Plan 16-27 (O-07 table) needs no new row for Q-D; the 4h wait value and the continuity span (`WARMUP_MIN_BARS`) are implementation values, not ratified numbers. `STALENESS_THRESHOLD_SECONDS` (60 s) still applies to a held bar re-submitted at its deadline, so the wait must stay well below it.
- A hole stalls live evaluation until it leaves the 200-bar continuity span or REST warm-up refills it; the runtime should trigger that refill after a gap it could not recover.
- `src/analytics/no_trade.py` maps unknown reason codes to UNMAPPED; map `HISTORY_DISCONTINUITY` and `SIBLING_4H_MISSING` to DATA_UNAVAILABILITY when the paper rows are wired to analytics.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path or schema; the module is pure and takes the `fetch_4h_bar` callable by injection.

## Self-Check: PASSED

- Created files exist: `src/paper/pipeline.py`, `tests/test_paper_runtime_pipeline.py`, `decisions/16-DEC-Q-D.md`.
- Commits found: 2db1b4c, 5c83bba, a81e1bb, af43f40, f0ff6a3.
- `grep -E "^option: history-only$" decisions/16-DEC-Q-D.md` matches.
