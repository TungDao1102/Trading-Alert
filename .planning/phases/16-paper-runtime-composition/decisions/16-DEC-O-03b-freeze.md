# 16-DEC-O-03b-freeze: freeze of the research run 1 dataset manifest, scenario S0 (plan 16-37, Task 3)

decided by: user
date: 2026-10-15
words:
freeze

context (recorded for audit): the word above is the user's whole reply. It answers the assistant's question "Freeze manifest S0?" asked after the draft manifest was built from `16-DEC-O-03b.md` and checked by two independent reviews (draft vs the user's words: MATCHES; builder code: approved after changes; commit f0f5366).

## What is frozen
- File: `docs/research/preregistration/research-run-1-manifest.json` (3,196 bytes, LF, `.gitattributes -text`), file sha256 `fdf2259ec3e2ec052e4cb2b11b165ce6213870ce893ab6a812852787cdff8490`.
- `manifest_hash` (the value a run authorization binds as `manifest_sha256`): `ec161733076f99e626da6900b7cc354ed68aa3104f5ac60de486b3b39f7ac569`.
- `dataset_id`: `34a1efa2622b04eca14af58365d5d9d539525e8982c1271e1a9d5b006d18d7d2` (research window files only, 49,549 files before 2026-05-10).
- Values: those of `16-DEC-O-03b.md` (Final values), including the REEFUSDT terminal declaration and the bounded settlement entry (0.000845 / 0.000887). Scenario: S0 (constraint file sha256 `4307eec7...e11d3f`).
- The file is byte-identical to the draft that was reviewed; it reloads with `load_manifest` to the hash above.

## Consequence
Changing any value, or this file, is a new registration and a new experiment (REV-05); a manifest hash that no longer equals the one above is not this experiment. The Holdout boundary 2026-05-10 .. 2026-10-03 is fixed by this freeze and remains single-use (G5).

## Not authorized by this record
The S1 manifest (own values, own file and hash, own words), the grid hashes and any run authorization (plan 16-46, the user writes it), any run, any Holdout read, `docs/research/holdout_consumed.json`, ExperimentRecord, push.

## Authorization files (2026-10-15)

The user typed: "Tôi, Tung Dao, ủy quyền chạy research run 1 kịch bản S0 cho cả ba grid (trend-pullback, breakout-retest, range-mr) với manifest đã freeze, và cho phép Claude tạo ba file ủy quyền". This amends O-03a option (a) (user writes the files): Claude wrote the three files on that instruction. Files: `docs/research/preregistration/research-run-1-authorization-<family>.json`, authorized_at_utc 2026-10-15T11:30:22+00:00. `load_authorization` accepts all three and manifest and grid hashes equal the runner's own hashes. No simulation was run by this step.
