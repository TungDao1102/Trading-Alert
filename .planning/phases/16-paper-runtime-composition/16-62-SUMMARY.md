---
phase: 16-paper-runtime-composition
plan: 62
subsystem: paper-rest-backfill-depth
status: complete
tags: [rest-backfill, resync, supervisor, configuration, gate, image-commit, B1-WR-09]
requires: [16-56, 16-57, 16-59]
requirements: [PAPER-01]
requirements-completed: []
provides:
  - "backfill_missed_closes(depth_bars, beyond_depth_reason) as required keywords: the request is bounded by the configured depth, newest closes first; each request asks min(REST_BACKFILL_PAGE_SIZE, remaining depth) rows"
  - "closes older than the newest depth_bars are recorded gaps with the reason of the window being verified (never EXCHANGE_NO_CANDLE, never dropped, no bar fabricated); one paper.resync.beyond_depth log line names the count"
  - "PaperSupervisor(backfill_depth_bars) required, >= 1, ValueError otherwise; build_supervisor passes config.timing.rest_backfill_depth_bars; scripts/paper_ws_smoke.py loads the ratified value with load_runtime_config (PAPER_RUNTIME_CONFIG or the committed v2 file)"
  - "module constants REST_BACKFILL_PAGE_SIZE = 1500 and REST_BACKFILL_PAGE_CAP = 200 (O-07 ratify current, unchanged values)"
  - "config/paper/README.md line and RUNBOOK 20.2 bullet: what the key controls and what happens beyond it"
  - "evidence/16-62-gate.txt with IMAGE_COMMIT=efae1f3efe3211f75f94e165e5d1c9956b20a6f1"
affects: [16-60, 16-43, 16-61, 16-44]
tech-stack:
  added: []
  patterns:
    - "an operator-facing key is a required keyword through the composition root; an AST test pins that no default exists"
    - "a bounded REST walk records what it does not request as gaps instead of truncating silently"
key-files:
  created:
    - tests/test_paper_backfill_depth.py
    - .planning/phases/16-paper-runtime-composition/evidence/16-62-gate.txt
  modified:
    - src/paper/resync.py
    - src/paper/supervisor.py
    - src/paper/runtime.py
    - scripts/paper_ws_smoke.py
    - config/paper/README.md
    - docs/operations/RUNBOOK.md
    - tests/test_paper_resync.py
    - tests/test_paper_reviewfix_pins.py
    - tests/test_paper_supervisor_backfill.py
key-decisions:
  - "The beyond-depth reason is passed into backfill_missed_closes as a required keyword (the plan allowed this or returning the older closes apart): the supervisor already holds the reason of the window, so no relabelling step is needed and the resync can never emit EXCHANGE_NO_CANDLE for them."
  - "The smoke script reads the depth through ratified_backfill_depth(environ), threaded through run_smoke and SmokeRun as an optional environ keyword that defaults to os.environ; main passes its own env."
  - "Nothing in the v2 file, the page size, the page cap or the RESYNC_* bounds changed; no number was typed anywhere (the README line names the warm-up and the value by reference, because the README guard forbids standalone numbers)."
duration: "not measured; two full-suite runs of about 15 minutes each dominated"
completed: 2026-10-17
commits: 4
plan_head_before: fbe7ee1e8654ff772b943506c68579df7799ef39
plan_head_after: 77749c4a66fc37f2ca8c5d2d9a4507570dcb7647
actuals:
  tokens: 8300
  tasks: 3
  commits: 4
---

# Phase 16 Plan 62: REST backfill depth Summary

The ratified `timing.rest_backfill_depth_bars` (1500) now controls how many closes one supervisor REST backfill requests, and a different value demonstrably requests a different depth. IMAGE_COMMIT, the commit the soak image is built from, is `efae1f3efe3211f75f94e165e5d1c9956b20a6f1`.

## Re-check outcome (B1-WR-09)

The finding held. Before the change an AST scan of `src/` found the key only in `src/paper/runtime_config.py` (the field and the required-key list), and the resync paged with its own `limit=1500` and a 200-page cap. The test `test_the_composition_root_consumes_the_configured_depth` failed on that, and after the change finds the read in `src/paper/runtime.py`.

## The depth rule as implemented

- `backfill_missed_closes` computes the expected closes from the last close to now. When there are more than `depth_bars`, it keeps the newest `depth_bars`, starts the page walk at the open time of the oldest kept close and returns every older expected close as a `GapRecord` with `beyond_depth_reason`. When there are not, the walk starts at the last close as before.
- Every request asks `min(REST_BACKFILL_PAGE_SIZE, remaining depth)` rows; the remaining depth falls by the rows each page returns, and the walk ends on a short page, on an exhausted depth, on a cursor past now, or after `REST_BACKFILL_PAGE_CAP` pages (the unchanged truncation warning).
- The supervisor passes the depth and the reason of the window being verified (`WS_RECONNECT_WINDOW`, or `WS_DISCONNECTED` when the rebuild was exhausted) from `_backfill_pairs`, which serves reconnect, drop recovery, the watchdog recovery and the post-start verification backfill alike. Backfilled bars stay `REST_BACKFILL` history and are never evaluated (Q-D).
- With 1500 and a 14-day trial (336 one-hour closes at most) the trial behaves as before; the key now controls it.
- The restart warm-up (1000 x 1h, 300 x 4h, `WARMUP_BARS`) is untouched and a test pins that `restart.py` does not mention the key.

## Tests (tests/test_paper_backfill_depth.py, 19 cases)

RED first: the file failed on 17 of its cases before any source change (the re-check, the end-to-end depth wiring, beyond depth, within depth and pagination, the page cap, the required keyword and ValueError, the smoke helper and script, and the constants). Test 5's constants guard also failed first, only because the names `REST_BACKFILL_PAGE_SIZE` and `REST_BACKFILL_PAGE_CAP` did not exist yet; their values are the unchanged ratified ones, and the RESYNC_* values and WARMUP_BARS passed from the start.

- End to end through `run_admitted` with fake WS client and fake REST adapter: an outage of 30 one-hour closes with D = 21 and D = 3 requests exactly the newest D closes per pair (sum of requested rows = D, first start = open of the oldest kept close) and journals D `REST_BACKFILL` history entries.
- Beyond depth, after a reconnect and after a drop and rebuild: the 30 - D older closes are `SUPERVISOR` gaps with reason `WS_RECONNECT_WINDOW`, the kept closes are history (each with the pipeline's own `REST_BACKFILL` gap, as in the seam test of plan 16-57), no bar exists for an older close, and nothing was evaluated.
- Within depth: an outage of 5 closes with D = 21 is one request of 21 rows starting at the next grid open; D = 3000 with 1502 closes pages as 1500 + 1500 rows (the CR-01 property); requests never exceed the depth or the page size; a misbehaving adapter is stopped at 200 pages.

Existing expectations that moved only because the depth now binds were updated with a B1-WR-09 comment: `tests/test_paper_resync.py` (depth 1500, limit 1500 still asserted), the CR-01 pagination and ValueError pins of `tests/test_paper_reviewfix_pins.py` (depth 3000 and 1500), and the supervisor rig of `tests/test_paper_supervisor_backfill.py`.

## Gate (evidence/16-62-gate.txt)

On a clean tracked tree at `efae1f3`: full suite `-m "not docker"` exit 0, 10118 tests ran, 10112 passed, 6 skipped (symlinks unavailable, NTFS POSIX modes, file modes on Windows; none is a PostgreSQL test, `TEST_DATABASE_URL` was set), 0 failed; `ruff check` exit 0; `ruff format --check` exit 0 (618 files); `mypy src` exit 0 (202 files); `uv lock --check` exit 0. The diff of `params/`, the frozen manifest, grid and authorization files and `paper-runtime-v1.toml` since `c654524` is empty, and `git log -- config/paper/paper-runtime-v2.toml` lists exactly one commit, the one of plan 16-56 (`63ffa58`). The no-float guard `tests/test_domain_no_float.py` passes; no `float` was added to `src/paper/`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] README line broke the admission README guard**
- **Found during:** Task 3 (first full-suite run, commit e7e3f4f)
- **Issue:** My Task 2 README line named 1000, 300 and 1500. `tests/test_paper_runtime_admission.py::test_readme_lists_every_key_one_per_line_without_values` allows no standalone number in the README, and that test is not among Task 2's verify commands, so it only surfaced in the full suite.
- **Fix:** The line now names the warm-up counts and the ratified value by reference (the restart module, 16-DEC-O-07). The README still states the consumer, the newest-first rule, the gap rule, the history-only rule and the structural warm-up.
- **Files modified:** `config/paper/README.md`
- **Commit:** efae1f3
- **Consequence:** the full suite was run again from the start; IMAGE_COMMIT is the commit after the fix.

None other: the plan was executed as written. The only choice inside the plan was the form of the beyond-depth reason (passed in, listed under key-decisions).

## Tracer note

The tracer slice (Task 1) was verified end to end in the same run by the tests above, which exercise the real `run_admitted` composition root before Tasks 2 and 3 expanded; no auto-mode checkpoint applied (the plan is autonomous).

## Pending, not done here

- The targeted re-review of `c654524..efae1f3efe3211f75f94e165e5d1c9956b20a6f1` that the outline requires before anything is pushed or merged is not part of this plan and has not been run.
- Plan 16-43 (checks out IMAGE_COMMIT on the soak host and builds the image, owner/host actions) and the epoch pin were not touched. Plans 16-60 and 16-61 start after this gate.
- PAPER-01 is not marked complete: this plan is one input to it; `requirements.mark-complete` was not called.

## Known Stubs

None.

## Threat Flags

None. The change adds no endpoint, credential path or schema; the REST requests are the same public klines call with a smaller or equal `limit`.

## Self-Check: PASSED

- Files exist: `tests/test_paper_backfill_depth.py`, `evidence/16-62-gate.txt`, this summary.
- Commits exist: `3f4a858`, `e7e3f4f`, `efae1f3`, `77749c4`.
- The Task 3 verify commands pass: IMAGE_COMMIT is HEAD~1 of the evidence commit, five `exit=0` lines and no non-zero exit line, and `git diff --quiet c654524 HEAD -- params/ ...manifest.json ...paper-runtime-v1.toml` is quiet.
