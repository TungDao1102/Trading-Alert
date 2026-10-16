---
phase: 18-user-data-stream-error-taxonomy
plan: 02
subsystem: planning/decisions (O-18-01, O-18-04)
status: complete
tags: [binance, safety-thresholds, rate-limit, clock-drift, user-data-stream, algo-status, D061, O-18-01, O-18-04, OPS-02, EXEC-05, EXEC-01]
requires: []
provides:
  - decisions/18-O-18-01-table.md (27 canonical key rows in section A, section B environment and credential questions, section C the four flagged ALGO_UPDATE status rows; every user value cell empty)
  - decisions/18-DEC-O-18-01.md (the user's decision record, option values; 27 limit lines, environment, credential and class lines; written by the user's words in ec8a94b and amended by the user in d4b8c4f; not touched by this executor)
affects:
  - plan 18-05 (rate_limit_decision reads the 418 and 429 fallbacks and the cap)
  - plan 18-06 (status classes from the class lines)
  - plan 18-07 (ClientLimits, SignedCallPolicy, RateLimitPolicy, DriftLimits, StreamLimits field names)
  - plan 18-09 (writes the limit, env and credential lines into config/binance/binance-limits-v1.toml and the environment rows)
  - plans 18-10, 18-12, 18-13, 18-14 (the process-wide REST rate-limit gate and its holders)
tech-stack:
  added: []
  patterns:
    - ratification table with an empty user value column; values live only in the user's decision record
    - shape-only completeness check of the record (never judges, adjusts or fills a value)
key-files:
  created:
    - .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-O-18-01-table.md (Task 1, 45c986c)
    - .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-01.md (Task 2, the user's record, ec8a94b; user amendment d4b8c4f)
  modified:
    - .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-O-18-01-table.md (Task 3 amendment, 1056b19)
decisions:
  - "O-18-01 / O-18-04: option values, decided by the user (record decisions/18-DEC-O-18-01.md, commit ec8a94b; 429 semantics amended by the user in commit d4b8c4f). The executor proposed, chose and wrote no value."
  - "Key split 26 to 27 (rate_limit_no_retry_after_wait_seconds replaced by rate_limit_418_no_retry_after_wait_seconds and rate_limit_429_no_retry_after_wait_seconds, cap kept): a user-authorized plan revision of 2026-10-16, not a CODE CHANGE REQUESTED"
  - "Class lines as read in the user's record: TRIGGERING, TRIGGERED, FINISHED and CANCELED are all UNKNOWN; no NEW, REJECTED or EXPIRED line, so NEW stays ACTIVE and REJECTED and EXPIRED stay TERMINAL_FAILED (D-07 defaults); the plan 18-06 stop rule does not trigger"
metrics:
  duration: "Task 1 committed 2026-10-16T03:09Z; Task 2 decided by the user the same day (ec8a94b 04:30Z, amendment d4b8c4f); Task 3 about 05:00Z to 05:15Z"
  completed: 2026-10-16
  tasks: 3
  files: 2
actuals:
  tokens: 14000
  tasks: 3
  commits: 1
plan_head_before: 154ecdf590ff559b1c256dd455a47a8e082ce623
plan_head_after: 1056b19
---

# Phase 18 Plan 02: O-18-01 safety numbers, environment data and status classes Summary

The O-18-01 ratification table now lists exactly the 27 canonical safety keys the user's record authorizes (the former single rate-limit wait is split into a 418 row and a 429 row beside the cap), every user value cell is still empty, and the user's decision record `decisions/18-DEC-O-18-01.md` passes the shape check unchanged: 27 `limit` lines, the environment and credential lines, and the four flagged status classes.

## Who decided what

- **Chosen option id:** `values`.
- **Decided by:** the user. The record was written from the user's words in commit `ec8a94b` (Task 2, blocking-human checkpoint) and amended by the user's words in commit `d4b8c4f` (section "Amendment 2026-10-16 (user): 429 semantics": no 429 retry of any kind, a 429 pauses all REST through the shared gate, protective failures surfaced as an unprotected position). Commit `ddda6e6` (orchestrator) only marked the superseded 429 retry sentence of the record.
- **Plan revision:** the key split from 26 to 27 keys is a user-authorized plan revision of 2026-10-16 (the user's line allows splitting the rate-limit wait into three keys and revising the plans that had not executed). It is not a CODE CHANGE REQUESTED and did not stop this plan.
- **Values:** every value is the user's and lives only in the record. This SUMMARY copies no number; the executor wrote, changed or completed no value.

## Tasks

| Task | Name | Commit | Files |
|---|---|---|---|
| 1 | Tracer: O-18-01 table, user column empty (26 rows at the time) | 45c986c | decisions/18-O-18-01-table.md |
| 2 | Checkpoint O-18-01 / O-18-04 (blocking-human, the user's decision) | ec8a94b (record), d4b8c4f (user amendment) | decisions/18-DEC-O-18-01.md |
| 3 | Amend the table to 27 keys; shape check of the record | 1056b19 | decisions/18-O-18-01-table.md |

Tasks 1 and 2 were done in earlier sessions; this session ran Task 3 only.

## Task 3, Step 1: table amendment

In `decisions/18-O-18-01-table.md`:

- The section A row `signed_calls.rate_limit_no_retry_after_wait_seconds` was replaced in place by `signed_calls.rate_limit_418_no_retry_after_wait_seconds` and `signed_calls.rate_limit_429_no_retry_after_wait_seconds`, in that order. Both keep the old unit, documented-limit, precedent and observation cells. Their meaning and "where it lives" cells are the texts the plan prescribes (`RateLimitPolicy.no_retry_after_wait_418_seconds` / `no_retry_after_wait_429_seconds`, plan 18-07, consumed by `rate_limit_decision` 18-05, the process-wide REST rate-limit gate 18-10 and its holders 18-12, 18-13, 18-14). The options cell is split per status. The old sentence "One value covers both 418 and 429 ...; D-11: ... 429 honors `retry_after` and backs off" was dropped, because the user's amendment removes any 429 retry. Both rows add the sentence that waiting proves nothing about an order and that a blocked protective order is reported as an unprotected position. Both user value cells are empty.
- The cap row meaning is now "The upper cap applied to a valid Retry-After value and to either fallback, against an absurd or corrupt header."; "The cap applies to both 418 and 429" is kept.
- In the `client.sdk_retries` and `client.sdk_backoff_ms` rows, the stale shape-check sentence now reads "The shape check of plan 18-02 Task 3 accepts zero for this key (plan revision of 2026-10-16)."
- "26 keys" was changed to "27 keys" in the "How to read the columns" block and in the section A heading. The dated line "Amended 2026-10-16 by plan 18-02 Task 3 per `18-DEC-O-18-01.md` ..." was added under the heading.
- The closing block "What the user is asked for" was left as asked on 2026-10-16. It still says "26 keys" because it records the question as it was put to the user.

## Task 3, Step 2: shape check (verification outputs)

| Check | Output | Exit |
|---|---|---|
| Table completeness (Task 1 command, re-run after the amendment) | `27 27 [] [] 0` (27 canonical keys, 27 found, none missing, none extra, 0 filled user value cells) | 0 |
| Table content (Task 1 second command) | `[]` | 0 |
| Record shape check | `27 [] [] True [('TRIGGERING', 'UNKNOWN'), ('TRIGGERED', 'UNKNOWN'), ('FINISHED', 'UNKNOWN'), ('CANCELED', 'UNKNOWN')] [] False` | 0 |
| Record unchanged (`git diff --exit-code HEAD -- decisions/18-DEC-O-18-01.md`) | no diff | 0 |

What the record shape check confirmed:

- Every one of the 27 canonical keys has exactly one `limit` line, and no other `limit` key exists. The former single key is absent.
- Every value has the required shape:
  - a plain positive integer, with zero accepted for `client.sdk_retries` and `client.sdk_backoff_ms`;
  - `true` or `false` for `drift.include_measurement_uncertainty`;
  - a positive integer or `none` for the three nullable keys.
- The `probe environment`, `env DEMO ws_streams_url`, `env DEMO ws_api_url`, `env TESTNET`, `credential DEMO` (key and secret) and `credential LIVE` (key and secret) lines exist.
- Each of TRIGGERING, TRIGGERED, FINISHED and CANCELED has exactly one valid `class` line.
- No line says CODE CHANGE REQUESTED.

The check validated shape only and judged no value.

**Class lines as read (the user's record):** TRIGGERING UNKNOWN, TRIGGERED UNKNOWN, FINISHED UNKNOWN, CANCELED UNKNOWN. There is no NEW, REJECTED or EXPIRED line, so the documented defaults stand: NEW is ACTIVE, and REJECTED and EXPIRED are TERMINAL_FAILED. None of the six statuses watched by plan 18-06 (TRIGGERING, TRIGGERED, FINISHED, CANCELED, REJECTED, EXPIRED) is ACTIVE, so the 18-06 stop rule (a non-resting status recorded ACTIVE) does not trigger.

## Deviations from Plan

None in substance. Two notes:

- The 418 row's options cell needed a "long" side once the old shared text was split. The old shared "Long: reads and cancels stay blocked long after a brief throttle" describes a 429 throttle, so the 418 row instead says "every REST call stays blocked after the ban has already ended". This is a neutral trade-off with no value proposed.
- The plan commit ledger was started at `154ecdf` (a plan 18-24 commit by the parallel executor, which landed just before Task 3). `commits: 1` therefore counts Task 3 only. The full plan history is listed in the Tasks table above.

## Known Stubs

None.

## Corrections the user must make

None. The record is complete in shape.

## Self-Check: PASSED

- FOUND: .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-O-18-01-table.md
- FOUND: .planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DEC-O-18-01.md
- FOUND: commits 45c986c, ec8a94b, d4b8c4f, 1056b19
