---
quick_id: 261015-o9l
status: complete
date: 2026-10-15
commit: f0f5366
---

# 261015-o9l summary: manifest build command (plan 16-37 Task 3, tests 1 to 3)

## What changed
- `src/research/manifest_build.py` (new) and a 5-line `__main__` hook in `src/research/manifest.py`: `python -m src.research.manifest --build --decision <16-DEC-O-03b.md> --raw-root <root> --out <file>`.
- `tests/test_research_manifest_build.py` (57 tests): synthetic record and store, the real record through `build_manifest` (day files stubbed) with the REEF entry equal to the pinned fixture, refusals (missing, empty, unregistered, inconsistent values; bad price text; unknown symbol; non-REEF settlement; unclean constraint path; duplicate constraint rows; unreadable record), atomic write leaves no file on a failed reload, Holdout day files do not move the hash, authorization hash equals the identity's manifest value (route B).

## Verification
- Full suite `pytest -m "not docker"`: 6,694 passed, 471 skipped, exit 0. ruff check, ruff format --check (547 files) and mypy src clean. `SIMULATOR_SEMANTICS_VERSION` 2.1.0.
- Draft S0 manifest built from the real record and the real data (4m31s), kept in the session scratchpad, NOT in the repo: manifest_hash `ec161733076f99e626da6900b7cc354ed68aa3104f5ac60de486b3b39f7ac569`, dataset_id `34a1efa2622b04eca14af58365d5d9d539525e8982c1271e1a9d5b006d18d7d2` (equal to the independent derivations in the probe evidence). A rebuild with the final code is byte-identical.
- Two independent Opus 5.5 reviews. Draft vs record: MATCHES (own hash recomputation, own recomputation of the REEF bounds from the evidence, universe content hash, constraint file). Code: APPROVE WITH CHANGES; the four should-fix items (atomic write, error paths, REEF-only settlement, test gaps) and the constraint-path guard were applied.

## Notes for the freeze and the run
- The runner reads `constraint_source` relative to the current directory: run from the repository root.
- The manifest has no field for the open-interest limitation (record correction 4); it lives in the O-03b record.
- Nits left: canonical-text requirement for equity and risk_rate, refusals printed to stdout.

## Not done
No manifest committed or frozen, no authorization, no run, no Holdout read, no push.
