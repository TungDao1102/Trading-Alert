---
phase: 16-paper-runtime-composition
plan: 28
subsystem: research protocol / experiment identity (REV-16)
tags: [rev-16, d065, protocol-v2.2.0, experiment-identity, user-decision]
requires: [16-18]
provides:
  - "decisions/16-REV-16-brief.md: re-verified facts, both routes with consequences, manifest-identity mapping, the six consistency items"
  - "decisions/16-DEC-REV-16.md: user decision, route B (seventh identity field), recorded verbatim"
  - "evidence/16-28-amendment-check.txt: proof that the separate protocol v2.2.0 amendment landed (3bfcd32)"
affects: [16-37 checks the runner seam, 16-46 research run authorization]
actuals:
  tokens: 12000
  tasks: 3
  commits: 2
plan_head_before: c8332df4a08f7ea06d9531fa1b17bf3a760c5163
plan_head_after: 64f540145b0bee29daa1af0b6d33c3619f096d2d
commits: 2
requirements-completed: []
status: complete
---

# Phase 16 Plan 28: REV-16 protocol v2.2.0 gate Summary

**The user chose route B (a seventh identity field holding `manifest_hash(manifest)`, `data_snapshot_id` unchanged); the separate amendment task 261011-mi1 landed protocol v2.2.0 (landing commit 3bfcd32) and the closure chain can now reach plan 16-46.**

`commits: 2` counts the plan's two own commits made before `plan_head_after` (brief 7583dad, decision record 64f5401). The evidence-and-SUMMARY commit follows `plan_head_after`. The seven amendment commits (f2cceba to 9d2949c, quick task 261011-mi1) and de81ee8 (plan 16-29) sit between the base and HEAD but are not this plan's commits, so a raw `rev-list` count of this range would not equal 2.

## What was done

1. **Task 1 (tracer), 7583dad.** Re-verified the REV-16 compatibility facts against the current code and docs and wrote the brief with both routes, their code consequences, the manifest-identity mapping and the six planner consistency items. Nothing was pre-selected or recommended. Refinements found: `manifest_hash` is a module function (`src/research/manifest.py:235`), not a method; the per-split `dataset_id` differs from the manifest `dataset_id`; the `analytics-evidence/2` experiment object is a closed key set, so a seventh field touches the loader.
2. **Task 2 (blocking-human decision), 64f5401.** Option `route-b-seventh-field`, decided by the user on 2026-10-11, words recorded verbatim in `decisions/16-DEC-REV-16.md`. The decision leaves the `dataset_id` formula and the existing bindings unchanged and puts the protocol, schema and analytics-evidence updates into the separate amendment task.
3. **Task 3 (human action), evidence.** The amendment task landed outside the Phase 16 code plans (quick task 261011-mi1, landing commit 3bfcd325cf959e9402a94f4d326f4f785f1b59ef on develop; commits f2cceba, 652e7eb, 03049db, 03573db, 91c1468, 3bfcd32, docs 9d2949c). The executor re-ran the checks and recorded them in `evidence/16-28-amendment-check.txt`:
   - the protocol header reads `**Protocol version:** v2.2.0` (FROZEN, amended 2026-10-11, supersedes v2.1.0);
   - `tests/test_decision_alignment_protocol.py` and `tests/test_research_feasibility.py` pass (48 tests); all `tests/test_decision_alignment*.py` plus the feasibility tests pass (400 tests);
   - `scripts/verify_decision_alignment.py all` prints `ALL_PASS` (including PR-11 and DC-01 to DC-06);
   - no change under `params/` or to `uv.lock`; no G1 or G5 floor sentence line changed; `holdout_consumed.json` still has empty `entries`.

## Route B as landed

- The seventh field is `data_manifest_hash`, equal to `manifest_hash(manifest)`, the same value the run authorization binds as `manifest_sha256` (REV-16 mapping).
- `data_snapshot_id` keeps its meaning (the case `dataset_id`); the `dataset_id == data_snapshot_id` bindings in `assemble` and the reproducibility check are untouched.
- The `analytics-evidence/2` experiment key `data_manifest_hash` is optional with a default: no schema bump and no fixture change. (The decision file left this choice to the amendment task.)

## Note for plan 16-37

The runner-seam edit planned in 16-37 is now only a check: `experiment_identity_inputs` in `src/research/run.py` already returns `{"data_snapshot_id": dataset_id, "data_manifest_hash": manifest_hash(manifest)}` (done in amendment commit 652e7eb). 16-37 verifies that and re-runs the planner consistency check against v2.2.0.

## Deviations from Plan

None - plan executed as written. The amendment itself was done by the separate task, as the plan requires; no Phase 16 plan edited the protocol, code or docs.

## Requirements

`requirements-completed: []`. PAPER-01 and PAPER-02 close through the SC9 closure rule (Phase 16 criteria 1, 2, 3, 5, 7); this plan only gates the research chain and closes no requirement by itself.

## Known Stubs

None. This plan creates decision and evidence documents only.

## Threat Flags

None. T-16-64 (research run under the old identity) is mitigated: the header is v2.2.0 and the alignment tests pass before any authorization. T-16-65 (agent choosing the route) is mitigated: the user chose, the executor pre-selected nothing.

## Self-Check: PASSED

- FOUND: decisions/16-REV-16-brief.md, decisions/16-DEC-REV-16.md, evidence/16-28-amendment-check.txt
- FOUND commits: 7583dad, 64f5401, 3bfcd32
