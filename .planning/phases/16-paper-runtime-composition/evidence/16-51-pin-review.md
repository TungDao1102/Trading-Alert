# Plan 16-51 pin review (digests and pinned expectations)

Status: AWAITING USER APPROVAL. No pre-existing test expectation has been edited. Nothing is
re-pinned until the user replies "approved" (16-51 Task 3, blocking-human checkpoint).

Decision this implements: `decisions/16-DEC-PARITY.md` (option 1, the runtime records the replay
inputs). Code constants are unchanged (16-DEC-O-07); no `strategy_version` or parameter set change.

## A. sha256 digests: none moved

No sha256 digest moved, and no file under `tests/fixtures/` changed. These guard suites pass
UNEDITED with the Task 1 and Task 2 code in place:

| Guard suite | What it pins |
|-------------|--------------|
| `tests/test_paper_start_gate.py` | `_clean_run_digest` |
| `tests/test_paper_parity.py` | verdict digest of `fixtures/phase7/parity_overlapping_history` (d06c739a...) |
| `tests/test_paper_reviewfix_pins.py` | run_paper_tick outcome digests |
| `tests/test_paper_feed_gates.py`, `tests/test_paper_closed_candle.py` | run_paper_tick outcome digests |
| `tests/test_paper_decision_surface.py` | surface_digest equalities (and the new test pins `74ad1cc1...792a` measured BEFORE the plan: `decision_surface` over the Phase 7 fixture still gives that digest, 500 records) |
| `tests/test_fixture_harness.py` | EXPECTED_SIGNALS_DIGEST, EXPECTED_PLANS_DIGEST |
| `tests/test_backtest_report.py` | EXPECTED_REPORT_DIGEST (27 passed) |

Why none moves: `run_paper_tick`, the simulator, `src/core`, `src/risk` and analytics are not
edited; `decision_surface` keeps its signature and output (its per-bar body moved into
`observe_closed_bar`, which adds one behaviour only: the context callable is resolved after the
warm-up gate, so a gated bar no longer calls it; records and digest are identical); the
PAPER_BAR_PROCESSED and PAPER_GAP payloads are byte-identical (the new data is in two NEW event
types).

Task 1 verify run (the plan's command, three tests of section B deselected):

```
282 passed, 3 deselected        (15 test files incl. tests/test_paper_replay_inputs.py)
mypy src: Success: no issues found in 179 source files
ruff check: All checks passed!
ruff format --check: 512 files already formatted
tests/test_paper_market_inputs.py::test_src_has_no_default_implementation_of_the_risk_inputs_port: passed
```

## B. Pinned expectations that moved (3, exactly the three the plan expected)

These three tests fail with the Task 1/2 code, each on exactly the assertion named; they are the
only pre-existing failures. They are listed here and NOT edited.

### B1. `tests/test_paper_vocabulary.py::test_runtime_event_type_carries_the_tick_stats_record` (line 63)

- Failing assertion: the exact set of `RuntimeEventType` names equals the nine names pinned today.
- Old value: `{RUNTIME_START, RUNTIME_STOP, EPOCH_PINNED, PAPER_BAR_PROCESSED, PAPER_GAP,
  PAPER_TICK_STATS, WS_DISCONNECT, WS_RECONNECT, HEALTH_STATE_CHANGED}`.
- New value: the same set plus `PAPER_REPLAY_INPUTS` and `PAPER_HISTORY_BARS`.
- Cause: the two new record types of 16-DEC-PARITY option 1 are new members of the closed
  vocabulary (`src/paper/vocabulary.py`). Observed failure: "Extra items in the right set:
  'PAPER_HISTORY_BARS', 'PAPER_REPLAY_INPUTS'".

### B2. `tests/test_paper_runtime_pipeline.py::test_backfill_only_batch_extends_history_and_records_one_gap_per_close` (line 458)

- Failing assertion: `{r.event_type for r in fx.state.records(EPOCH_ID)} == {RuntimeEventType.PAPER_GAP}`
  after a warm-up and a backfill batch.
- Old value: `{PAPER_GAP}`.
- New value: `{PAPER_GAP, PAPER_HISTORY_BARS}`, and, to keep the intent of the line (nothing says
  the feed was healthy because the backfill worked), the re-pinned test also asserts that no
  `PAPER_BAR_PROCESSED` and no `HEALTH_STATE_CHANGED` record exists.
- Cause: the pipeline now logs every accepted bar, REST_WARMUP and REST_BACKFILL included, in a
  `PAPER_HISTORY_BARS` record so the parity replay can rebuild the windows in acceptance order.
  The gaps themselves are unchanged (`sorted(result.recorded) == fx.gap_records()` still passes).
  Observed failure: "Extra items in the left set: PAPER_HISTORY_BARS".

### B3. `tests/test_paper_runtime_pipeline.py::test_every_arrival_order_of_one_group_gives_byte_identical_records` (line 761)

- Failing assertion: `len(baseline[0]) == 2  # the 4h context record and the 1h heartbeat`.
- Old value: 2 state records.
- New value: 5 state records: the 4h context heartbeat, the 1h heartbeat, the 1h bar's
  `PAPER_REPLAY_INPUTS` record, the `PAPER_HISTORY_BARS` record of the warm-up batch and the
  `PAPER_HISTORY_BARS` record of the group batch (flushed before the evaluation).
- The property the test guards is NOT affected: I ran the same body with the count taken as 5 and
  the equality over all 24 arrival orders of the group holds (records, evaluated candles and
  duplicate count byte-identical in every order).
- Observed failure: "assert 5 == 2".

## C. Any other pre-existing failure

None so far. (Task 2 may add entries here with cause; each would be accepted or refused one by one.)

## D. Hard-limit check

`git log --grep="(16-51)" --name-only --format=` lists no path under `src/paper/{loop,bars,
supervisor,resync,notify,market_inputs,runtime,runtime_config,freeze,restart}.py`,
`src/{persistence,backtest,core,risk,adapters}/`, `params/`, `config/` or `tests/fixtures/`
(the Task 3 verify command checks this mechanically; the output is appended at the checkpoint).

## E. Approval (Task 3 checkpoint)

- Approval words (verbatim): "aprrove"
- Date (UTC): 2026-10-12
- Approved by: user
- Order note: the three re-pinned assertions of section B were already applied by commit 5494cb5
  (`fix(ci): align tests with 16-51 records and NO_CHECK_BUCKET`), before this approval was given.
  Their content matches section B exactly. The extra no-heartbeat/no-health assertion proposed in
  B2 is already implied by the exact event-type set equality, so it was not added separately.
- Task 3 verify run after approval: 17 paper test files passed (1 skipped, the PostgreSQL line, no
  TEST_DATABASE_URL on this machine: NOT RUN), forbidden paths: [] (no commit of this plan touches
  a forbidden path).
