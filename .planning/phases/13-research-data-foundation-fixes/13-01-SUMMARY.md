---
phase: 13-research-data-foundation-fixes
plan: 01
subsystem: data-collection
tags: [collector, open-interest, funding, collect-list, tomllib, docker, cadence]

requires:
  - phase: 02-data-layer
    provides: OI/funding collector (async_oi_tick, async_funding_sweep, watermarks, gap journal)
provides:
  - "Config-driven collector universe: docs/research/universe/collect-list-v1.toml (live-5 union top 15 TRADING USDT perpetuals by 24h quote volume, chosen 2026-09-30)"
  - "src/data/collect_list.py: loader (fail closed), deterministic proposer, TOML renderer, propose CLI"
  - "Collector refuses to start (exit 2, healthcheck 1) on a bad collect list with zero adapter calls; no live-5 fallback"
  - "Docker image ships docs/research/universe"
  - "Loop sleeps to the next cadence boundary (period no longer stretches with tick duration)"
affects: [13-02, 13-06, 13-07, 13.1-ops, research-universe-freeze]

actuals:
  tokens: 12170
  tasks: 3
  commits: 6
plan_head_before: 0df71a9ef8c56cd4ed385a2e1174b9decd5ed756
plan_head_after: 357c420d1558a2674c4d61238bfc6e1713e88261

tech-stack:
  added: []
  patterns:
    - "Operational config file under docs/research/universe validated by a stdlib tomllib loader that raises a project ValueError subclass (fail closed, no fallback)"
    - "Deterministic proposer over raw public JSON: Decimal volume, (-volume, symbol) sort key, sorted output"
    - "Wall-clock seam (_utc_now) plus integer-ms boundary helper for grid-aligned loops"

key-files:
  created:
    - src/data/collect_list.py
    - docs/research/universe/collect-list-v1.toml
    - tests/test_collect_list.py
    - tests/fixtures/phase13/collect_list/ticker_24hr.json
    - tests/fixtures/phase13/collect_list/exchange_info.json
    - .planning/phases/13-research-data-foundation-fixes/deferred-items.md
  modified:
    - src/data/collector.py
    - Dockerfile
    - tests/test_collector.py

key-decisions:
  - "Collect list is an operational input: no FROZEN semantics, no content hash, lives under docs/research/universe not params/ (D-02)"
  - "No fallback to LIVE_5 on any collect-list defect; collector exits 2 (healthcheck 1) before any engine/adapter is built (T-13-02)"
  - "Proposer only considers PERPETUAL + USDT + TRADING symbols matching ^[A-Z0-9]+USDT$; ties break by symbol ascending; live-5 always unioned in (T-13-03)"
  - "collector.py keeps its own integer-ms epoch helper rather than importing src.paper.resync, to avoid a data-to-paper layer dependency"

requirements-completed: [DATA-02]

coverage:
  - id: D1
    description: "Collector universe is read from the versioned collect list (live-5 union top 15 by volume) for the loop, --once and --healthcheck; explicit --universe overrides and is validated"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "tests/test_collector.py#test_main_once_polls_exactly_the_collect_list"
        status: pass
      - kind: unit
        ref: "tests/test_collector.py#test_explicit_universe_override_is_validated"
        status: pass
    human_judgment: false
  - id: D2
    description: "A missing, unreadable, empty or malformed collect list stops the collector with exit 2 (healthcheck 1) and no adapter calls; never falls back to live-5"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "tests/test_collector.py#test_missing_collect_list_refuses_start_without_live5_fallback"
        status: pass
      - kind: unit
        ref: "tests/test_collector.py#test_healthcheck_with_missing_collect_list_is_unhealthy"
        status: pass
      - kind: unit
        ref: "tests/test_collect_list.py#test_empty_collect_list_is_rejected"
        status: pass
    human_judgment: false
  - id: D3
    description: "Deterministic proposer and the committed collect-list-v1.toml generated from live exchange data (TRADING PERPETUAL USDT only, live-5 superset, provenance recorded)"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "tests/test_collect_list.py#test_proposer_union_of_top15_and_live5_with_symbol_tiebreak"
        status: pass
      - kind: unit
        ref: "tests/test_collect_list.py#test_committed_collect_list_is_valid_live5_superset"
        status: pass
    human_judgment: false
  - id: D4
    description: "Docker image contains docs/research/universe"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "tests/test_collect_list.py#test_dockerfile_copies_universe_directory"
        status: pass
    human_judgment: true
    rationale: "Test asserts the COPY line and its position in the Dockerfile text; an actual image build was not run in this sandbox"
  - id: D5
    description: "Loop sleeps to the next cadence boundary measured after the tick"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "tests/test_collector.py#test_loop_sleeps_to_next_cadence_boundary_after_tick"
        status: pass
      - kind: unit
        ref: "tests/test_collector.py#test_ms_until_next_tick_mid_period"
        status: pass
    human_judgment: false
  - id: D6
    description: "24 hour live run: every collect-list symbol keeps a fresh OI and funding watermark"
    requirement: DATA-02
    verification: []
    human_judgment: true
    rationale: "Needs live Binance, PostgreSQL and a day of wall-clock time (13-VALIDATION manual-only row)"

duration: 21min
completed: 2026-09-30
status: complete
---

# Phase 13 Plan 01: Collector Widening Summary

**The OI/funding collector now polls a versioned collect list (live-5 union the top 15 TRADING USDT perpetuals by 24h volume, generated from live Binance data on 2026-09-30), refuses to start on a bad list, ships the list in the Docker image, and sleeps to the next 5-minute grid boundary.**

## Performance

- **Duration:** 21 min
- **Started:** 2026-09-30T13:02:56Z
- **Completed:** 2026-09-30T13:24Z
- **Tasks:** 3 (1 tracer, 2 auto; all TDD)
- **Files modified:** 9 (6 created, 3 modified) plus deferred-items.md

## Accomplishments

- `src/data/collect_list.py`: fail-closed loader (`CollectListError`), deterministic `propose_collect_list`, `render_collect_list_toml`, and a `propose` CLI that refuses to overwrite its `--out`.
- `collector.py` takes `--collect-list` (default `docs/research/universe/collect-list-v1.toml`); `--universe` now defaults to None and is regex-validated; the live-5 fallback and import are gone. Loop, `--once` and `--healthcheck` share `_resolve_universe`.
- `docs/research/universe/collect-list-v1.toml` committed: 15 symbols (BNB, BTC, DOGE, ENA, ETH, HYPE, MOVR, NEAR, PUMP, QNT, SOL, SUI, WLD, XRP, ZEC). All live-5 symbols were already inside the top 15 at fetch time (BNB ranked 15th), so the union equals the top 15. Provenance (both endpoint paths, fetch time 2026-09-30T13:05:22Z) is in the file header.
- Dockerfile: `COPY docs/research/universe ./docs/research/universe` before `RUN useradd`; HEALTHCHECK and CMD untouched.
- `_ms_until_next_tick` plus a `_utc_now` clock seam: the loop measures the clock after the tick and sleeps to the next boundary, so a slower tick over 15+ symbols cannot stretch the period (Pitfall 5).

## Task Commits

1. **Task 1 (tracer): collect-list file to loader to collector polling exactly the listed symbols**
   - RED `d482687` (test), GREEN `8a9842e` (feat)
2. **Task 2: proposer, committed list, image packaging**
   - RED `9aec911` (test), GREEN `6294268` (feat)
3. **Task 3: cadence-boundary sleep**
   - RED `2e69718` (test), GREEN `357c420` (feat)

**Plan metadata:** committed separately (docs: complete plan).

Tracer gate: the tracer `<verify>` (pytest, mypy, ruff) was re-run end-to-end after Task 1 and passed, so expansion proceeded.

## Files Created/Modified

- `src/data/collect_list.py` - loader, proposer, renderer, propose CLI.
- `src/data/collector.py` - `--collect-list`, `_resolve_universe`, `_utc_now`, `_ms_until_next_tick`, boundary sleep.
- `docs/research/universe/collect-list-v1.toml` - the operational list.
- `Dockerfile` - COPY line for the universe directory.
- `tests/test_collect_list.py`, `tests/test_collector.py` - loader/proposer/CLI/packaging and collector wiring/timing tests.
- `tests/fixtures/phase13/collect_list/{ticker_24hr,exchange_info}.json` - trimmed live public data with documented deliberate edits.

## Decisions Made

- Collect list stays an operational input (no FROZEN semantics, no hash, not under `params/`), per D-02.
- Any list defect exits before an engine or adapter is built; there is no live-5 fallback (T-13-02).
- The proposer parses only symbols whose exchangeInfo record is TRADING PERPETUAL USDT, so a junk `quoteVolume` on an excluded symbol cannot break selection, while a bad value on an eligible symbol raises.
- `collector.py` carries its own 5-line integer-ms epoch helper instead of importing `src.paper.resync` (keeps the data layer independent of the paper layer).

## Deviations from Plan

None - plan executed exactly as written. Two small notes, neither a deviation:

- The real exchangeInfo contained a live PENDING_TRADING record (GAIBUSDT), so only its ticker row had to be synthesised; the fixture's `_fixture_note` says so.
- The repository's existing files are not `ruff format`-clean under the current config, so only `ruff check` (the plan's gate) was applied, not `ruff format`.

## Issues Encountered

- Pre-existing failures outside this plan: 7 tests in `tests/test_decision_alignment.py` and `tests/test_decision_alignment_bookkeeping.py` fail with `OPS-06 row is Phase 13.1, expected Phase 13` (planning docs vs the decision-alignment gate). Logged in `deferred-items.md`; not touched. Every other test in `tests/` passes.
- A shell heredoc mangled backslash escapes while appending a test helper; fixed by using the Edit tool (test avoids literal newline escapes via `os.linesep`).

## Known Stubs

None.

## Threat Flags

None. The only new input surfaces are the operator-editable collect list (validated, T-13-01/02) and the local-file `propose` CLI (no network).

## User Setup Required

None. Manual follow-up from the plan: on a host with PostgreSQL, run the collector for 24 hours and confirm every collect-list symbol has a fresh `oi` and `funding` watermark (13-VALIDATION manual-only row).

## Next Phase Readiness

- The collector can be started on a personal machine now (`python -m src.data.collector`); each day it runs preserves OI that the 30-day API window would otherwise destroy (F-107).
- Residual note for Phase 13.1 (untested): `time.sleep` could in principle wake a hair before a boundary if the wall clock is adjusted mid-sleep, which would floor the next tick to the previous grid slot. Not observed; a guard (for example a 1 ms pad) can be added if it ever shows up in the gap journal.
- Next plans in the phase have no dependency on this one.

## TDD Gate Compliance

Each task has a `test(13-01)` RED commit followed by a `feat(13-01)` GREEN commit (d482687 to 8a9842e, 9aec911 to 6294268, 2e69718 to 357c420). RED runs failed on the intended cause (missing module/symbols or unrecognised `--collect-list`). No REFACTOR commits were needed.

## Self-Check: PASSED

- Files exist: collect_list.py, collect-list-v1.toml, test_collect_list.py, both fixtures (verified below).
- Commits found: d482687, 8a9842e, 9aec911, 6294268, 2e69718, 357c420.
- Task acceptance criteria and plan-level verification (pytest 79 passed across the two files, mypy clean, ruff clean, `--help` lists `--collect-list`, single Dockerfile COPY line, `git ls-files` lists the TOML) re-run and passing.
