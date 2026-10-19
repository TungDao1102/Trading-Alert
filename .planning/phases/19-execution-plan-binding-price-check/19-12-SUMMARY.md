---
phase: 19-execution-plan-binding-price-check
plan: 12
subsystem: execution
tags: [emergency-close, reduce-only, MARKET, lot-split, deterministic-ids, query-before-resend, tdd, binance]
requires: ["19-04", "19-08", "19-10", "19-11"]
provides:
  - "src/execution/order_ids.py: derive_close_order_id (xc- + plan_hash[:29] + 4-digit attempt, 36 chars)"
  - "src/execution/emergency_close.py: CloseAdapter, EmergencyCloseStatus, EmergencyCloseResult, MarketEmergencyCloser (close_position, last_result), discover_next_attempt_no"
  - "journal event type EMERGENCY_CLOSE; SAFE_MODE reason EMERGENCY_CLOSE_FAILED; alert events EMERGENCY_CLOSE_FAILED and EMERGENCY_CLOSE_NOT_SENT"
affects: [19-14, 19-17]
tech-stack:
  added: []
  patterns: [journal-first send, query-before-resend with a fresh id per attempt, REST position as the only truth after each part, AST purity guards]
key-files:
  created:
    - src/execution/emergency_close.py
    - tests/test_emergency_market_close.py
  modified:
    - src/execution/order_ids.py
decisions:
  - "Attempt ids use a new derivation (xc-) so ROLE_CODES and OrderRole stay untouched (research F6)"
  - "Every outcome the closer cannot prove (probe failure, found but non-terminal attempt, indeterminate probe, unreadable position, no valid part, filter read failure) enters SAFE_MODE(EMERGENCY_CLOSE_FAILED) with a critical alert; PENDING_UNKNOWN is the status for the ones where an attempt may exist"
  - "A pre-send refusal is NOT_SENT with alert EMERGENCY_CLOSE_NOT_SENT and no SAFE_MODE from the closer; the coordinator deadline decides (Q4 open)"
  - "-2022 and -2024 are both REJECTED_DEFINITIVE in the taxonomy and are handled identically: re-read the position, flat is True, otherwise CLOSE_FAILED, never a resend"
status: complete
commits: 6
plan_head_before: 2a31cdb
plan_head_after: 64c1543
actuals:
  tokens: 14900
  tasks: 3
  commits: 6
---

# Phase 19 Plan 12: Automatic reduce-only MARKET emergency close Summary

`MarketEmergencyCloser.close_position` re-reads the position over REST, sizes one valid MARKET part from live exchangeInfo filters (`next_close_part`), sends it reduce-only under a deterministic per-attempt id, re-reads the position after every part and returns True only when REST shows the position flat; everything it cannot prove ends in SAFE_MODE, a critical alert and a journal row, never in a false "safe".

## What was built

1. **Tracer (Task 1, tracer-type).** `derive_close_order_id(plan_hash=, attempt_no=)` returns `"xc-" + plan_hash[:29] + "%04d"` (36 characters, same charset as the other derived ids). Attempt 0, 10000, a bool or a non-int raises; `ROLE_CODES` is unchanged (a test pins it). `MarketEmergencyCloser(adapter, journal, safe_mode_controller, alert_sink, clock)` subclasses the `EmergencyCloser` Protocol of plan 19-11. With a +0.004 BTCUSDT position it sends exactly one SELL, position_side BOTH, quantity 0.004, id attempt 0001, journals `EMERGENCY_CLOSE` `pre_send` before the adapter call and `post_send` after (scalar payload fields only, entity_id the attempt id), re-reads the position and reports `last_result.status == "FLAT"`. A Hedge entry raises `ValueError` before any call (D-14). The tracer feedback gate (re-running the task's automated verify end to end) passed before Task 2 started.
2. **Parts and escalation (Task 2).** Position 12 with market max 5 and step 1 sends 5, 5, 2 under attempts 0001 to 0003 with a REST position read after every send; each part is sized from the REST value, so a stop that fired in between shrinks the next part (test: 5 then 4, not 5 then 5). The loop is bounded by `len(plan_close_parts(first REST position).parts)` (at least 1): a position that never moves stops after that many sends with `PARTS_EXHAUSTED`. No valid part (`next_close_part` None), a failing live `symbol_lot_filters` read (Q3 default) and an unreadable position (first read or re-read) all send nothing further, enter SAFE_MODE `EMERGENCY_CLOSE_FAILED`, raise one critical alert `EMERGENCY_CLOSE_FAILED` (the reason is the code, for example `NO_VALID_PART`), journal a `failed` record and return False with `CLOSE_FAILED`. A position already flat returns True with zero sends.
3. **Ambiguity and discovery (Task 3).** An exception from `place_market_close` is classified with `error_facts` + `classify(..., PLACEMENT)` (no message text is read; an AST test enforces it). `REJECTED_DEFINITIVE` and `PRECONDITION_NO_POSITION` (which include -2022 and -2024) re-read the position: flat is True, otherwise `REJECTED_NOT_FLAT`; the two codes end in identical results (test). Everything else, and a `None` result, is ambiguous: the attempt id is queried first. Found FILLED continues with a fresh position read; absent, or found ended unfilled (CANCELED, EXPIRED, EXPIRED_IN_MATCH, REJECTED), spends the id and the next part uses the next number (never the same id twice; an autouse test fixture asserts this over every scenario in the file); found NEW or any unknown status, a probe that raises, or a probe whose `found` is not a plain bool returns False with `PENDING_UNKNOWN`, SAFE_MODE and the alert, with no resend. Attempts proven to have had no effect are bounded by the planned part count. A `PreSendRefusal` is journaled `not_sent`, raises alert `EMERGENCY_CLOSE_NOT_SENT`, returns False with `NOT_SENT`, and triggers no probe and no resend. `discover_next_attempt_no(adapter=, symbol=, plan_hash=)` probes 0001, 0002, ... and returns the first definitively absent number (a failing or indeterminate probe raises); `close_position` starts from it, so a second call after a crash never reuses an id, and a failing discovery sends nothing and stops as `PENDING_UNKNOWN`. A purity test pins imports (no SDK, no `src.adapters`, no frame or HTTP libraries, no asyncio), no float, no wall clock, no sleep.

## Open items (recorded, not decided)

- **Q3**: a failed live exchangeInfo read during the close is treated as "no valid part can be built" (the D-16 SAFE_MODE branch). The plan-time snapshot is not used as a fallback until the owner decides. `lot_filters_from_plan_snapshot` is therefore not called by this module.
- **Q4 / Phase 18 src/WR-12**: a 418/429 pause refuses the close (`PreSendRefusal`, nothing sent); no exemption was added. The closer reports NOT_SENT and a critical alert and makes no claim of safety; the coordinator's deadline keeps running.
- **A4 / A8**: that a reduce-only MARKET on a flat or smaller position answers -2022 or -2024 comes from the repo taxonomy and the fake's labelled TEST CONVENTION, not from the live page. The closer never branches on the difference.
- The fake fills a MARKET close at once and in full. The real response is normally an acknowledgment, so a position read immediately after a part could in principle still show the old size; the reduce-only flag keeps a resulting extra part from flipping the position, and a -2022/-2024 rejection is handled by the same re-read. Not exercised against the real exchange.

## Notes for plan 19-14 (the caller)

- Call `await closer.close_position(entry=RestingEntry, reason="CLOSE_REQUIRED")` from the failure branches and read `closer.last_result` (`status`, `parts_sent`, `reason`) for the coordinator state: True maps to FLAT; False with `CLOSE_FAILED` or `PENDING_UNKNOWN` maps to CLOSE_FAILED (the closer already entered SAFE_MODE and alerted); False with `NOT_SENT` maps to a close that did not leave the process (the coordinator's deadline and its own SAFE_MODE decision apply).
- `discover_next_attempt_no` costs one REST query per used attempt; a fresh plan costs one.
- A previous attempt found by discovery is treated as spent without checking its status; a still-open earlier MARKET close is practically impossible and the position re-read bounds the exposure.

## Deviations from Plan

None. Only `src/execution/order_ids.py`, `src/execution/emergency_close.py` and `tests/test_emergency_market_close.py` changed (plus this SUMMARY.md). `emergency_manual_close`, `protection.py`, `lot_split.py` and the adapter are untouched. Judgement calls inside the plan are listed in `decisions`.

## Verification

- `uv run pytest -m "not docker" tests/test_emergency_market_close.py tests/test_execution_emergency.py tests/test_binance_usdm_source_guard.py -x`: 80 passed, exit 0.
- Also run (one pytest at a time): `tests/test_order_ids.py tests/test_no_unratified_defaults.py tests/test_domain_boundary.py tests/test_protection_coordinator.py tests/test_protection_router_rig.py tests/test_market_lot_split.py`: all passed, exit 0.
- `uv run mypy src`: Success, no issues found in 211 source files.
- `uv run ruff check`: All checks passed.
- `uv run ruff format --check`: 656 files already formatted.

The whole `pytest -m "not docker"` suite was not run (memory limit on this machine). A green test proves agreement with the fake's labelled rules, not with mainnet.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint, auth path or schema; the new module only calls adapter methods that already exist (T-19-29 duplicate close, T-19-30 false safety and T-19-31 audit after restart are mitigated as the plan states; T-19-SC: no package changed).

## Self-Check: PASSED

- src/execution/emergency_close.py, tests/test_emergency_market_close.py and the `derive_close_order_id` addition in src/execution/order_ids.py exist.
- Commits b5f243d, 8a9d97a, 0e81ec9, 4f9c411, aad0ad8, 64c1543 are on branch p19-12 (RED test commit before each GREEN implementation commit).
