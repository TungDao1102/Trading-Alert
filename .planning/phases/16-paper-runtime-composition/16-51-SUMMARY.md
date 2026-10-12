---
phase: 16-paper-runtime-composition
plan: 51
subsystem: soak evidence / parity replay inputs (16-DEC-PARITY option 1)
tags: [parity, replay, evidence-bundle, paper-01]
requires:
  - phase: 16-paper-runtime-composition
    provides: "plans 16-25, 16-26, 16-29"
provides:
  - "PAPER_REPLAY_INPUTS and PAPER_HISTORY_BARS record types (acceptance log) next to the unchanged heartbeat"
  - "build_parity_replay from a bundle alone, run by run in acceptance order; ParityUnavailable reported as 'NOT EVALUATED' FAIL"
  - "runtime_record_line writer; evaluate_trial_soak.py replays without a seam"
status: complete
commits: [8f597bc, 191e25b, 05a4471, 64e7257, d44e6e0, 5494cb5]
---

# Plan 16-51 summary

Tasks 1 and 2 implemented 16-DEC-PARITY option 1. Task 3 (blocking-human pin review) was approved
by the user on 2026-10-12; see evidence/16-51-pin-review.md section E. No sha256 digest moved, no
fixture changed, no forbidden path touched. Three pinned expectations moved (vocabulary set,
backfill record set, arrival-order record count 2 to 5) and are re-pinned.

Deviation: the three re-pins landed in commit 5494cb5 (CI fix) before the approval; contents match
the review file.

Not run on this machine: the PostgreSQL strict run of Task 2 (no TEST_DATABASE_URL); needs CI or a
host with the database.
