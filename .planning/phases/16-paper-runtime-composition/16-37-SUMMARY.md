---
phase: 16-paper-runtime-composition
plan: 37
subsystem: research preregistration (closure-chain step O-03b, data manifest)
tags: [consistency-check, dataset-coverage, protocol-v2.2.0, o-03b, tracer]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-28 (protocol v2.2.0 landed, route B) and plan 16-45 (three registered grid files)"
provides:
  - "evidence/16-37-consistency.md: protocol version read, grid check on the three grid files, six consistency items with owners, local dataset coverage facts, open facts not verifiable here"
affects: [16-37 Task 2 (O-03b user decision), 16-37 Task 3, 16-46]

requirements-completed: []

status: Task 1 tracer done, Task 2 (O-03b) pending user, Task 3 not started
actuals:
  tokens: 9000
  tasks: 1
  commits: 1
plan_head_before: e92ca7dde798ef49f46550dd101b52190ba786f1
plan_head_after: 261f900229382e948953e83ec81625113a23e9bd
commits: 1

key-files:
  created:
    - .planning/phases/16-paper-runtime-composition/evidence/16-37-consistency.md
    - .planning/phases/16-paper-runtime-composition/16-37-SUMMARY.md
  modified: []

key-decisions: []
---

# Phase 16 Plan 37: Tracer, preflight and post-amendment consistency check

**Task 1 only: the protocol header reads v2.2.0, the three registered grids list STRUCTURALLY_VALID (16 points each), the six consistency items of plan 16-28 have one row each with one gap found, and the local dataset coverage is recorded as facts for the user's O-03b decision. No date, symbol or value is proposed.**

`commits: 1` counts the evidence commit measured when this file was written; the commit that adds this SUMMARY follows and is not part of `plan_head_after`.

## Status

Task 1 tracer done. Task 2 (O-03b, `checkpoint:decision`, `gate="blocking-human"`) is pending the user and was not started. Task 3 (manifest build and runner identity wiring) was not started. Requirements completed: none.

## What was done

- Read the protocol header: `Protocol version: v2.2.0`, FROZEN, amended 2026-10-11.
- Ran `python -m src.research.register --list-grid` on the three grid files (the plan names one file, `research-run-1-grid.json`, which does not exist; plan 16-45 registered three, a deviation already recorded in its SUMMARY). All 48 points are STRUCTURALLY_VALID.
- Re-checked the six consistency items of plan 16-28 against the landed v2.2.0 text. Items 1, 2, 3, 5 and 6: no conflict. Item 4: one gap (see below).
- Recorded the local dataset coverage per symbol and dataset kind, which kinds the runner needs, and the facts that cannot be verified here.
- Task 1 automated check passed (exit 0, empty list).

## Findings for their owners (nothing edited)

1. Item 4 gap, owner USER (scope) and ROADMAP-BATCH if it becomes a plan: `src/analytics/provenance.py:56-98` (`ExperimentIdentity`) does not carry `data_manifest_hash`, while `RESEARCH_PROTOCOL.md:338-343` says every record carries seven fields. The adapter accepts the field as optional (`src/adapters/analytics_files.py:137-141`, `:610-629`); the digest still differs because `experiment_id` includes it.
2. Note for the Task 3 executor: the route B body of `experiment_identity_inputs` (`src/research/run.py:68-81`) already landed in commit 652e7eb with the amendment.
3. Observation for ROADMAP-BATCH: this plan lists `requirements: [PAPER-01]`, while `ROADMAP.md:711` closes PAPER-01 on criteria 1, 2 and 7; not assessed.
4. Per plan 16-45's SUMMARY, a cross-family multiplicity blocker is recorded against plan 16-46; it is not an input of this plan and was not re-examined.

## Facts the user needs for O-03b (from the evidence file)

- The runner needs trade klines (1m, plus the strategy and context intervals, default 1h and 4h), mark-price klines 1m, and funding. It does not request open interest (`src/research/run.py:136`, `:166`; `src/data/case_input.py:73-74`).
- Locally: trade klines 1m/1h/4h, mark klines 1m/1h/4h, funding for 19 symbols; no open-interest data. All 12 symbols of research-universe-v1 have data; 11 over 2024-10-03..2026-10-02, REEFUSDT through 2025-01-22. Seven data symbols are not in the universe (ENAUSDT, HYPEUSDT, MOVRUSDT, NEARUSDT, PUMPUSDT, QNTUSDT, ZECUSDT).
- Anomalies: SOLUSDT trade 1h has two stray partitions (2023-11-14, 2023-11-15); PUMPUSDT funding has a missing range 2025-06-20..2025-07-09.
- The runner refuses non-empty `excluded_periods` (`run.py:122-127`); the Validation block must divide into four equal whole-day folds (`manifest.py:148-160`); a constraint source JSON with a row per symbol must exist and be hashed (`run.py:90-103`), and no such file was found in the repository.
- The OI gap window 2026-10-09T19:34:49Z..19:55:00Z is outside the local data range (last local partition 2026-10-02) and is not a series the runner reads.
- Not verifiable here: whether the local copy is current against the EC2 host.

## What the user must decide (Task 2, O-03b)

The executor pre-selects nothing. The checkpoint asks the user for, in the user's own words: data window start and end (UTC); universe and symbols; candle intervals; data source and version; the exact Development, four Validation fold and holdout start and end (UTC, the holdout is single-use once a candidate runs on it, protocol G5); excluded periods and known gaps; the research account inputs (equity, risk rate) and the constraint source. Options: `values` (with every manifest value) or `postpone`. Reply `values` or `postpone` to resume; the answer goes to `decisions/16-DEC-O-03b.md`. Approving the grid did not authorize a run and this record does not either (L-10).

## Deviations from Plan

- [Scope] The plan names one grid file; the three registered files were checked instead (instruction of the orchestrator, plan 16-45 deviation).
- [Scope] The coverage and open-facts sections were added to the evidence file on the orchestrator's instruction; they are read-only facts.
- Commits were made on `master` (the branch of the working tree and of the preceding plan 16-40 commits; no worktree, `branching_strategy: none`).

## Known Stubs

None.

## Threat Flags

None.

## Self-Check: PASSED

- `.planning/phases/16-paper-runtime-composition/evidence/16-37-consistency.md` exists; commit 261f900 exists on `master`.

## Second tracer (data snapshot, REEF, constraint source)

Read-only, 2026-10-13, evidence in `evidence/16-37-data-snapshot.md` (commit 35df0ba). Status unchanged: Task 1 tracer done, Task 2 (O-03b) pending user, Task 3 not started. The user's reviewer tentatively chose `[2024-10-03T00:00Z, 2026-10-03T00:00Z)`, 12 symbols; the executor proposes nothing. No data, manifest, decision, param, grid or code file was edited; no network, no simulator run; the Holdout days were read for sha256 and timestamps only.

- Local snapshot: `C:\Users\daotu\local-data-snapshot-16-37.sha256` (outside the repo), 61,665 lines (trade 1m/1h/4h and mark 1m, 8,142 each; funding 29,097), sha256 of the listing `b9b8426a31a2821d27d07fc49457cabcdc7cd887910b8185269de3bfa5982b34`; 49,549 lines are runner-read files, 12,116 are Holdout days (integrity only). `dataset_identity()` over the runner-read part: `34a1efa2622b04eca14af58365d5d9d539525e8982c1271e1a9d5b006d18d7d2`. The evidence file holds the read-only EC2 command (volume `trading_rawdata`, `docker run --network none -v ...:ro`); its script body reproduces the listing byte-for-byte locally, the `docker run` wrapper was not run.
- Coverage (timestamps only): the 11 long-history symbols have zero gaps and present = expected in the runner range and the Holdout range for every series, except a tolerated single missing 4 h funding instant (2026-06-24T04:00Z, in the Holdout range) for DOGSUSDT and WIFUSDT. REEFUSDT ends at 2025-01-22T08:59Z (last partition partial: 540 one-minute rows), with one trailing hole per series in every range.
- REEFUSDT and the engine: an unacknowledged hole raises `CaseInputGapError`; an acknowledged trailing `GapRange` lets the run continue and the symbol produces no signals after its data ends. 30 `GapRange` entries are needed for the tentative window (six builder calls x five series; funding label `4h` in the whole range and Development, `8h` in the empty folds). A `GapRange` has no reason field and the manifest rejects extra keys. Code-derived risk, occurrence unverified: a REEFUSDT position open after 2025-01-22T08:00Z would raise `FundingCoverageError`, and no acknowledged `GapRange` can cover that hole (`funding.py:229-262`, `coverage.py:397`). Four options (a) to (d) with consequences are in the evidence file.
- Constraint source: no stored file is a constraint source with a row per symbol or a history for the window. BNBUSDT, BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT have one exchange-origin observation (2026-09-19) in `tests/fixtures/exchange_info_sample.json`, in a layout that needs conversion. 1000PEPEUSDT, DOGEUSDT, DOGSUSDT, REEFUSDT, SUIUSDT, WIFUSDT, WLDUSDT have no verified constraint row in any checked source. The PostgreSQL `symbol_metadata` table, the designed producer, was not examined.
- Not verified: local copy vs EC2 host, the `docker run` wrapper, whether a REEFUSDT position is ever open past its last funding instant, the PostgreSQL table, the provenance of the 2026-09-19 fixture.
