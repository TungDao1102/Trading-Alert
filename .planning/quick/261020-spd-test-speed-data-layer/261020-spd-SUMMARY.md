---
quick_id: 261020-spd
status: complete (B2 and the DuckDB gap-check idea dropped by the owner)
date: 2026-10-20
commits: 622e65f, c410247, 5000686, 8b01a61
---

# 261020-spd summary: faster research and data tests

## What changed
- A1 `622e65f` (tests only): `build_store(..., oi=False)`; the modules that only build engine series stop writing thousands of open-interest files nobody reads (warmup, checkpoint, terminal-settlement, known-gap and the other provable ones). Default stays "write OI".
- A2 `c410247` (tests only): one session-shared terminal world and lower-base run for the terminal-settlement, known-gap and warm-up tests.
- A3 `5000686` (tests only): the warm-up manifest `dataset_id` is computed once per `val_end`.
- B1 `8b01a61` (production, `src/data/case_input.py`): each case-input file is related to `raw_root` once and the root is resolved once, instead of two resolves per file twice. `dataset_id`, `files`, their order and every error are unchanged.

## Evidence for B1
`tests/test_case_input_relative_paths_equivalence.py` keeps the old code as a reference: 14 tests (builder output ==/repr on 9 store/series cases and with minute rows; 72 helper comparisons over 6 root spellings x 6 file lists x 2 stores; a symlink/junction root; 9 outside/missing-file lists x 2 spellings; an unresolvable root). Byte goldens of 6 research runs (75 records, 50 checkpoints, 6 logs, 1.12 MB) were identical before and after (agent report in the commit message). Re-run by the orchestrator after the agent was stopped: equivalence tests plus `tests/test_case_input_builder.py`, 37 passed, no skips, 2 min 19 s.

## Not done
- B2 (build the case data once per window in `run_research`) and the DuckDB gap-check replacement: dropped by the owner on 2026-10-20; registered as [P16S-01] and [P16S-02] in `.planning/phases/16-paper-runtime-composition/deferred-items.md`. The unfinished B2 attempt was discarded from the working tree before any commit.
- Before/after wall times of the five modules were not re-measured at the end (the agent was stopped); the baseline from the profile was warmup 136 s, checkpoint 93 s, terminal 50 s, case-input 113 s, known-gap 86 s. The sequential gate of plan 16-65 records the whole suite.

## Scope guards kept
No change to `SIMULATOR_SEMANTICS_VERSION`, protocol, manifest, grids, authorization files, params, `fsync` or `src/data/coverage.py`. No push.
