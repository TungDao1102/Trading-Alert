---
phase: 18-user-data-stream-error-taxonomy
plan: 06
subsystem: domain/algo-status, execution/attach, reconcile/sweeper
status: complete
tags: [binance, algo-order, ALGO_UPDATE, protection, EXEC-01, EXEC-02, D-07, G2-028, O-18-01]
requires: [18-01, 18-02, 18-03]
provides:
  - src/domain/algo_status.py (AlgoStatusClass, AlgoStatusEntry, ALGO_STATUS_TABLE, classify_algo_status, is_protection_confirmed; the 18-03 vocabulary stays)
  - src/execution/manager.py (_ACTIVE_ALGO_STATUSES removed; _is_leg_confirmed and the existing-leg adoption branch use is_protection_confirmed)
  - src/reconcile/sweeper.py (pre-cancel payload key algo_status_class)
  - docs/trading/EXECUTION_SPEC.md 6.1 (Status, Class, Meaning table and the fail-closed paragraph)
  - tests/test_algo_status.py
affects:
  - Phase 20 (reconcile and sweeper decisions driven by the class)
  - plan 18-20 (probe of the REST algoStatus vocabulary; a REST-only value classifies UNKNOWN)
tech-stack:
  added: []
  patterns:
    - read-only MappingProxyType status table with a per-entry documented meaning and source note; an import-time check that the keys equal the vocabulary
    - record-drift test that parses the owner's decision record, plus an independent literal pin of the same table
    - attach tests derive their expectation from is_protection_confirmed, not from a literal list
key-files:
  created:
    - tests/test_algo_status.py
  modified:
    - src/domain/algo_status.py
    - src/execution/manager.py
    - src/reconcile/sweeper.py
    - docs/trading/EXECUTION_SPEC.md
    - tests/test_execution_attach.py
    - tests/test_reconcile.py
decisions:
  - "Algo status classes as read from decisions/18-DEC-O-18-01.md (2026-10-16): TRIGGERING, TRIGGERED, FINISHED and CANCELED are UNKNOWN (record lines); NEW ACTIVE, REJECTED and EXPIRED TERMINAL_FAILED (documented defaults, no record line); no status is TERMINAL_OK; only NEW confirms protection"
  - "Stop rule of plan 18-06 did not trigger: none of the six watched statuses (TRIGGERING, TRIGGERED, FINISHED, CANCELED, REJECTED, EXPIRED) is ACTIVE in the record, and every recorded class is one of the four D-07 classes"
  - "classify_algo_status looks up only exact str values; None, empty, other case, surrounding whitespace, bytes, int and unseen strings are UNKNOWN"
metrics:
  duration: 7min
  completed: 2026-10-16
estimate:
  tokens: 58000
  tasks: 2
actuals:
  tokens: 8500
  tasks: 2
  commits: 2
plan_head_before: 4cb11476da042c8f65aa962e566ac2499bc0fd64
plan_head_after: 9dc2cef3e41250938d7cc69674c93cd0ca82475c
---

# Phase 18 Plan 06: Algo Status Classification Summary

A pure classification table of the seven ALGO_UPDATE statuses (NEW ACTIVE; TRIGGERING, TRIGGERED, FINISHED, CANCELED UNKNOWN per the owner's record; REJECTED, EXPIRED TERMINAL_FAILED; anything unseen UNKNOWN) now decides protective-leg confirmation and adoption in the attach path, is journaled by the orphan sweeper, and is shown and test-compared in EXECUTION_SPEC 6.1.

## Classes as read from the decision record

`decisions/18-DEC-O-18-01.md` (2026-10-16) holds four class lines: `class TRIGGERING: UNKNOWN`, `class TRIGGERED: UNKNOWN`, `class FINISHED: UNKNOWN`, `class CANCELED: UNKNOWN`. It has no NEW, REJECTED or EXPIRED line and states the defaults NEW ACTIVE, REJECTED and EXPIRED TERMINAL_FAILED. This equals the plan's expectation, so no difference is reported. The stop rule did not trigger: none of the six watched statuses is ACTIVE, and every class is one of ACTIVE, TERMINAL_OK, TERMINAL_FAILED, UNKNOWN.

## Performance

- Duration: about 7 minutes (2026-10-16T05:27:40Z to 05:34Z)
- Tasks: 2 of 2
- Files: 1 created, 6 modified

## Accomplishments

- `src/domain/algo_status.py` (stdlib only): `AlgoStatusClass` (str Enum), frozen `AlgoStatusEntry(status, klass, meaning, source_note)`, read-only `ALGO_STATUS_TABLE` with the documented meanings from SOURCES "Facts read for Phase 18" (WebFetch summaries, not verified live; EXPIRED is the tool's paraphrase), an import-time check that the keys equal `ALGO_STATUS_VOCABULARY`, `classify_algo_status`, `is_protection_confirmed`.
- `src/execution/manager.py`: `_ACTIVE_ALGO_STATUSES` and its comment block replaced by a pointer to the domain module; `_is_leg_confirmed` and the adoption branch of `_place_protective_leg` call `is_protection_confirmed`. No other behavior, signature or reason code changed. With the recorded table only NEW confirms and only a NEW existing leg is adopted, which is exactly the removed allow-list; `test_attach_behavior_unchanged_from_new_only_allow_list` proves it for the seven statuses, None, "", "new", " NEW", "NEW ", 7, b"NEW" and "SOMETHING_ELSE" across `_is_leg_confirmed`, placement and adoption.
- `tests/test_execution_attach.py`: two parametrized full-attach tests (existing SL adoption over the seven statuses; SL placement response over the seven statuses, "" and an unseen string) with expectations derived from `is_protection_confirmed`. No existing assertion was removed or weakened.
- `src/reconcile/sweeper.py`: the diff is one import and one payload key, `algo_status_class` = `classify_algo_status(status).value`; no control flow changed.
- `docs/trading/EXECUTION_SPEC.md` 6.1: Status, Class, Meaning table (first cell still a bare backticked status) and a paragraph: unseen values are UNKNOWN and fail closed, only ACTIVE counts as protection confirmed, the four flagged classes are the owner's record of 2026-10-16 (UNKNOWN until independently verified through Binance; D055 not decided by the table), no status is TERMINAL_OK, class-driven reconcile and sweeper decisions are Phase 20. Every EX-02 row and phrase kept; no URL added.

## Task Commits

1. Task 1 (tracer): `f42e180` feat(18-06): tracer - the algo status classification table drives protective-leg confirmation and adoption
2. Task 2: `9dc2cef` feat(18-06): journal the algo status class in the sweeper payload and show the class in EXECUTION_SPEC 6.1

## Verification

- Task 1 verify, `pytest -m "not docker" tests/test_algo_status.py tests/test_execution_attach.py tests/test_execution_manager.py -x`: 186 passed (red first: ImportError of `ALGO_STATUS_TABLE`). Tracer feedback gate: the verify was re-run after the commit and passed.
- Task 2 verify, `pytest -m "not docker" tests/test_algo_status.py tests/test_reconcile.py tests/test_decision_alignment_exchange.py -x`: 193 passed (red first: KeyError `algo_status_class` and the two doc tests failing).
- Plan verification, all five files with `-x`: 290 passed.
- `scripts/verify_decision_alignment.py docs`: no FAIL line, final line `ALL_PASS docs`.
- `mypy src`: no issues in 191 source files.
- `ruff check` and `ruff format --check` on the seven files of this plan: all checks passed, all formatted. On the whole tree both report findings only in the concurrent plan 18-07's uncommitted files (`src/adapters/binance_limits.py`, `tests/test_binance_limits.py`), which this plan did not touch.

All commands ran as `UV_OFFLINE=1 uv run --frozen --extra dev ...`; no network, no `.env`, no database URL.

## Deviations from Plan

### Auto-fixed Issues

None to the plan's behavior. Additions beyond the plan text:

**1. [Rule 2 - Hardening] Extra guards in the tests**
- The record-drift test also asserts that every record class is a D-07 class and that none of the six watched statuses is ACTIVE (the stop rule as a test), and that no status is classified twice.
- The removed-constant test also rejects an attribute access `manager._ACTIVE_ALGO_STATUSES` anywhere in `src`, `scripts` and `tests`, and the wiring test requires at least two calls of `is_protection_confirmed` in the manager.
- The sweeper tests cover every status, None, "", "new", an unseen string, an int, an absent `algo_status` attribute, and replay determinism of the event id.
- Commits: f42e180, 9dc2cef

## Open Issues

- The meanings in the table and the doc are WebFetch summaries of 2026-10-16 (not character-exact, not verified live); EXPIRED is the tool's paraphrase. The connected-machine smoke (plan 18-18) and the probe (plan 18-20) establish the live behavior.
- Whether the REST `algoStatus` vocabulary equals the WebSocket `X` vocabulary is still UNVERIFIED (research A3); a REST-only value classifies UNKNOWN, which fails closed.
- Tests outside the plan's verify list that build sweeper events (`tests/test_journal_ids.py`, `tests/test_drills.py`, `tests/test_persistence_journal_pg.py` (docker)) were not run, as instructed; a read of them shows they compare event ids relative to each other and pin no payload hash or full payload.
- STATE.md, ROADMAP.md and REQUIREMENTS.md were not updated, as instructed by the orchestrator.

## Known Stubs

None.

## Threat Flags

None: no new endpoint, auth path, file access or schema change. T-18-16 and T-18-17 mitigated as planned (unseen values UNKNOWN, only ACTIVE confirms, record-drift and doc-versus-code tests); T-18-SC: no package installed or changed.

## Self-Check: PASSED

- FOUND: src/domain/algo_status.py, src/execution/manager.py, src/reconcile/sweeper.py, docs/trading/EXECUTION_SPEC.md, tests/test_algo_status.py, tests/test_execution_attach.py, tests/test_reconcile.py
- FOUND commits: f42e180, 9dc2cef
