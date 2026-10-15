---
phase: quick-261014-nnl
plan: 09
subsystem: research protocol v2.4.0 landing
tags: [s-b-interval, protocol, d070, d071, holdout-marker]
requires: ["07", "08"]
status: complete
commits: 1
plan_head_before: b67a100
completed: 2026-10-15
---

# Plan 09 Summary: protocol v2.4.0 landed (D070, D071)

Landed the user-adopted text (16-DEC-V240.md, draft sha256 eecb323a...72885a) byte for byte, with D070 (amendment and the only "protocol v2.4.0 frozen" row) and D071 (regeneration inventory), after the user's own words authorized the one-field marker edit ("authorized", 2026-10-15, recorded in 16-DEC-V240-marker.md; marker_sha256_before 8360af41...14de).

- Commit: 006c480. docs/research/holdout_consumed.json changed by exactly one line (protocol_version v2.3.0 -> v2.4.0); schema and empty entries unchanged.
- Witnesses moved: header v2.4.0, EXPECTED_SUPERSEDES v2.3.0, DC-03 binds D070, DOC_STATUS index, BACKTEST_SPEC, research-gate.yml comment; new tests/test_research_protocol_v240.py (10 tests) pins the Validation-only statement.
- D071 (user saw the full MOVED list before commit, 2026-10-15) had one stray period fixed before commit. The D070 wording "stops trading" was kept on the user's instruction.
- Verify: five targeted pytest files pass, verify_decision_alignment.py ALL_PASS, ruff check clean. Full suite is plan 10.
- Deviations: plan verify grep for the old phrase replaced by the adopted sentence; D071 digests copied from the ffda8c4 diff.
- Not done: no manifest freeze, O-03, Holdout read, ExperimentRecord, push.
