---
phase: 24-live-runtime-composition-demo
plan: 01
subsystem: planning
tags: [owner-decisions, execution-limits, one-way-doors, phase-24]

requires:
  - phase: 23-telegram-approval-hardening-money
    provides: confirm core, user-id gate, SHADOW money-block carry-over (P23-R1)
  - phase: 20-reconcile-safe-mode-hardening
    provides: the NOT_CONFIGURED limit keys and their recorded constraints
provides:
  - "24-OWNER-DECISIONS.md: Q1..Q16 with the recommendation first, answered 2026-10-31"
  - "24-LIMITS-CHECKPOINT.md: every NOT_CONFIGURED execution-limits key with an assistant recommendation, answered 2026-10-31 except one key"
  - "the Owner answers tables below, which the preconditions of plans 24-05 to 24-35 read"
affects: [24-05, 24-06, 24-07, 24-08, 24-09, 24-14, 24-16, 24-17, 24-22, 24-23, 24-24, 24-25, 24-26, 24-29, 24-30, 24-35]

actuals:
  tokens: 19000
  tasks: 3
  commits: 3  # own commits (git log --grep "(24-01)"); the raw range count is larger, see Deviations
plan_head_before: 32c3be83334648802fb26aed7b4f86900ea44204
plan_head_after: 3a3919cc5077ceaa6d6ca2c120c8b4bf39f4532d  # last own commit; plans 24-02 and 24-03 committed in between

key-files:
  created:
    - .planning/phases/24-live-runtime-composition-demo/24-OWNER-DECISIONS.md
    - .planning/phases/24-live-runtime-composition-demo/24-LIMITS-CHECKPOINT.md
  modified: []

key-decisions:
  - "Q1: one live process, python -m src.live.runtime, one asyncio loop (D-01)"
  - "Q2: sync stores kept, every on-loop store call through src/ops/store_executor.py (one writer thread); no async pool (D-25)"
  - "Q3: hand-written migration 0015_order_event_time with a monotonic event-time guard (D-10)"
  - "Q9: CLOSE_POSITION after a failed post-fill liquidation check (D085 O-4 wins over CONTEXT D-24)"
  - "Q14: Demo fill recorded as evidence only; LIVE_NET_PNL_SEMANTICS_VERIFIED stays False until the Phase 26 canary (D086)"
  - "Q10: the Phase 16 soak is running, so the SHADOW money block ships as a NEW text version with the old pins kept"

requirements-completed: []  # APRV-01, EXEC-01, EXEC-02, EXEC-03, OPS-02, OPS-03, OPS-04 stay Pending: this plan decides, it builds nothing

duration: 1 session
completed: 2026-10-31
status: complete
---

# Phase 24 Plan 01: Owner decision packet and limits checkpoint Summary

**Sixteen architecture questions (three one-way doors first) and every NOT_CONFIGURED execution limit were put to the owner with a recommendation first; the owner followed all recommendations, and one limit key (the user-data silence bound) remains unanswered because no recommendation exists for it.**

## Performance

- **Duration:** one session plus the owner's reply
- **Tasks:** 3 of 3 (Tasks 1 and 2 automated, Task 3 owner decision)
- **Files created:** 2 planning files; no source, test, config, docs/ or dependency file was touched

## Accomplishments

- `24-OWNER-DECISIONS.md`: Q1 to Q16, each with Recommendation, Why, Alternatives, Undo cost, Plans that depend on it and the recorded Answer. No limit number appears in it.
- The two research conflicts were surfaced, not silently resolved: Q9 (CONTEXT D-24 versus D085 O-4) and Q14 (CONTEXT D-23 versus D086 O-4).
- Q10 found that a Phase 16 soak is running (epoch pinned 2026-10-25, hourly freeze ticks clean, a ws-silence incident on 2026-10-27, soak image from commit 6f73e5b), so the SHADOW text change goes behind a new text version.
- `24-LIMITS-CHECKPOINT.md`: fourteen required keys, the alert-only stale-entry grace and the optional D083 clock margin, each with meaning, reader, constraint, evidence, a labelled ASSISTANT RECOMMENDATION and reason; the derived-cadence table; the five relationships plan 24-06 will test (all hold with the recommended values); the live heartbeat row.
- The official user-data-streams page and the websocket-market-streams page were re-read once on 2026-10-31. Neither states a server ping interval, so `stale_feed.max_user_data_silence_ms` was given no number.

## Owner answers

Recorded on 2026-10-31. The reply reached the executor through the orchestrator; the owner's words are the quoted text. The reading below the quote is the orchestrator's and the assistant's, not the owner's.

Owner reply, verbatim (2026-10-31):

> theo recommend của bạn hết đi, nếu có chỗ nào khó quyết, hãy thông báo với tôi

Reading: "follow your recommendation for all of it" applies to Q1 to Q16 and to the numeric limit keys that carry a recommended number. "If anything is hard to decide, tell me" is answered by the one open item, key 14 below, which the orchestrator reports to the owner. The six questions the owner saw in full with their options earlier (Q1, Q2, Q3, Q9, Q10, Q14) take option A, the recommendation.

### Q1 to Q16

| Q | Topic | Chosen option |
|---|-------|---------------|
| Q1 | Process boundary | recommended: one live process `python -m src.live.runtime`, one asyncio loop |
| Q2 | StoreExecutor seam | recommended: sync stores behind `src/ops/store_executor.py`, one writer thread, no async pool |
| Q3 | Migration 0015 | recommended: `0015_order_event_time`, nullable event-time columns on orders and positions, `update_position_snapshot`, guarded downgrade |
| Q4 | Signal source | recommended: `SignalSource` Protocol with only the Demo-smoke injector; later owner phase for strategy-driven signals to be named |
| Q5 | DEMO enablement and the three feed probes | recommended: manager unchanged, in-process DEMO-only `enable()`, starts DISABLED, probe meanings and D056 rows as written |
| Q6 | Telegram identity | recommended: second bot for the live process, live-only variable names, refuse start if the SHADOW bot variable is present |
| Q7 | Operator commands | recommended: `/status`, `/disable_entries`, `/safemode_exit` (two-step), `/close SYMBOL` (two-step); gate clear stays on ssh |
| Q8 | One database per mode | recommended: mode-scoped approved-approvals reader, shared compose database |
| Q9 | Post-fill liquidation policy | recommended: D085 `CLOSE_POSITION` (not the CONTEXT D-24 default) |
| Q10 | SHADOW money text | recommended: soak is running, so a NEW text version with the old pins kept |
| Q11 | Heartbeat shape | recommended: `deploy/heartbeat.sh --target live`, one check per process |
| Q12 | Limits files in the image | recommended: bake `config/execution` and `config/binance` into the image |
| Q13 | Revision stamp | recommended: build argument stamped into the image environment |
| Q14 | Verification flags | recommended: Demo fill as evidence only; `LIVE_NET_PNL_SEMANTICS_VERIFIED` stays False until the Phase 26 canary |
| Q15 | Live restart policy | recommended: `restart: "no"` until the first clean Demo run |
| Q16 | Exact signed-quantity compare | recommended: keep the D-01a bound check, revisit in Phase 25 |

No override was given for any question. Plans whose precondition reads this table (24-05 for Q2, 24-07 for Q3, 24-08 for Q8, 24-09 for Q10, 24-14 and 24-29 for Q4, 24-16 for Q9, 24-17 and 24-30 for Q6, 24-22 and 24-26 for Q5, 24-23 for Q7, 24-24 for Q11, 24-25 for Q12 and Q13, 24-30 and 24-35 for Q15) therefore run as written.

### Limit keys (values are those of `24-LIMITS-CHECKPOINT.md`; nothing is written to config by this plan)

| # | Key | Owner value |
|---|-----|-------------|
| 1 | `protection.max_unprotected_ms` | 180000 |
| 2 | `protection.entry_terminal_timeout_ms` | 900000 |
| 3 | `protection.entry_unknown_grace_ms` | 1800000 |
| 4 | `protection.emergency_close_poll_timeout_ms` | 30000 |
| 5 | `pre_placement.min_remaining_validity_seconds` | 900 |
| 6 | `pre_placement.max_mark_price_age_ms` | 5000 |
| 7 | `pre_placement.max_last_price_age_ms` | 5000 |
| 8 | `reconcile.tick_interval_ms` | 15000 |
| 9 | `reconcile.entry_unknown_probe_count` | 3 |
| 10 | `reconcile.entry_unknown_probe_interval_ms` | 5000 |
| 11 | `reconcile.lot_filter_refresh_interval_ms` | 3600000 |
| 12 | `reconcile.entry_stale_grace_ms` (alert only) | 900000 |
| 13 | `stale_feed.max_mark_price_age_ms` | 60000 |
| 14 | `stale_feed.max_user_data_silence_ms` | NOT ANSWERED: no recommendation exists; owner to choose from the Demo run's observed ping/pong times |
| 15 | `alerts.dedupe_window_ms` | 300000 |
| 16 | D083 clock margin (optional) | left NOT_CONFIGURED |
| - | live heartbeat period and grace (install argument) | period 60 s, grace 120 s |

Consequence for plan 24-06: thirteen required keys plus the alert-only key have values. Key 14 is required, so the live path still refuses to start until the owner answers it, and plan 24-06 must not write a number for it. The owner is to be told this is the one item that is hard to decide.

## Task Commits

1. **Task 1: owner decision packet** - `cd45d83e` (docs)
2. **Task 2: limits checkpoint** - `f48f6d6e` (docs)
3. **Task 3: owner answers recorded in both packets** - `3a3919cc` (docs)

The final metadata commit (this SUMMARY, STATE.md, ROADMAP.md) follows.

## Deviations from Plan

None in the work itself: Tasks 1 and 2 were executed as written and Task 3 was recorded verbatim.

- **Measured commit count.** The plan's ledger method (`git rev-list --count` from the stored base 32c3be83) counts 10 commits at the time of writing, because plans 24-02 and 24-03 committed on the same branch in parallel. The `commits:` value above is 3, the commits whose subject carries `(24-01)`. The ledger base is `.git/gsd-plan-head-before-24-01`. Verifiers should use the subject filter for this plan.
- **Per-tick REST weights** in the limits row of `reconcile.tick_interval_ms` are read from the installed SDK docstrings, not from the current Binance REST pages (the fetch tool does not render them). The row says so and tells plan 24-20 to compare against the live `exchangeInfo` rate limits.
- **Plan 24-03 added the D083 key** (`rest_gate.ban_end_clock_margin_ms`, optional, NOT_CONFIGURED) after the limits packet was written; the packet describes it generically as "the optional D083 clock margin", which is the same key.

## Issues Encountered

- `python3` is not on the PATH of this machine; a first scripted edit was skipped and redone with the Edit tool and `uv run python`. No file was left half-edited.

## Known Stubs

None. The packets are documents; the blank answer fields were all filled.

## Threat Flags

None. No network endpoint, auth path, file access or schema was added. T-24-01 (repudiation of the owner answer) is mitigated: the answer is recorded verbatim with its date and key 14 is left "NOT ANSWERED" instead of defaulted. T-24-02 (DEMO enablement): Q5 states the in-process enable is DEMO-only and unreachable in LIVE, and plan 24-22 tests it. T-24-SC: `git diff --exit-code -- pyproject.toml uv.lock` exits 0 for this plan's commits.

## Next Phase Readiness

- Plans that need only Q answers can run as written.
- Plan 24-06 and the first Demo run wait for key 14. The owner's decision is expected after the Demo run records the observed ping and pong times; plan 24-06 writes the other values and halts on key 14.

## Self-Check: PASSED

- FOUND: 24-OWNER-DECISIONS.md, 24-LIMITS-CHECKPOINT.md
- FOUND commits cd45d83e, f48f6d6e, 3a3919cc (ancestors of HEAD)
