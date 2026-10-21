---
phase: 20-reconcile-safe-mode-hardening
plan: 14
subsystem: execution-pending-actions
tags: [pending-actions, rest-gate, 429-418, q4, d-19, d-16, migration-0008, fail-closed, tdd]
requires: [20-03, 20-07, 20-08, 20-09]
provides:
  - "migration 0008_pending_protective_actions: table pending_protective_actions (intent only, no price, quantity or side), CHECKs, partial unique index on (plan_hash, pending_kind) WHERE state = 'PENDING'"
  - "src.execution.pending_actions: PendingKind, PendingState, PendingAction, PendingActionStore, IntentSpill, BlockedRecorder, intent_event, pending_id_for, gate_reason_text, retry_after_until and the NOTE_* resolution texts"
  - "src.persistence.pending_actions.PgPendingActionStore (record_blocked, resolve, supersede, list_open)"
  - "ProtectionCoordinator(pending_actions=, spill=) and MarketEmergencyCloser(pending_actions=, spill=) keywords (default None: behavior unchanged)"
  - "blocks_new_entries() is also True while any pending row is PENDING and when the store cannot be read"
affects: [20-15, 20-17, 20-18, 20-19, 20-21, 20-24]
tech-stack:
  added: []
  patterns:
    - "spill first, then the durable store; a store failure enters SAFE_MODE DB_FAILURE once and the step carries on"
    - "the pending row is a record of intent, never the input of a send: the ordinary step re-reads the exchange and decides"
    - "a Protocol (IntentSpill) declared next to the consumer so src.execution does not import src.ops"
key-files:
  created:
    - src/db/alembic/versions/0008_pending_protective_actions.py
    - src/execution/pending_actions.py
    - src/persistence/pending_actions.py
    - tests/support/pending_action_fakes.py
    - tests/test_pending_actions.py
    - tests/test_pending_actions_pg.py
  modified:
    - src/db/models.py
    - src/execution/protection.py
    - src/execution/emergency_close.py
    - src/persistence/__init__.py
    - tests/support/protection_doubles.py
    - tests/test_persistence_migration_pg.py
    - docs/data/DATA_MODEL.md
key-decisions:
  - "The spill record is written when the gate REFUSES the action (the Task 1 action text), once per open episode of (plan_hash, kind); it is not written before every send. A new sent request every step would otherwise create a file per step during a long ban."
  - "pending_id is a content hash of plan_hash, kind AND opening time, so a block after a resolution opens a new row; the plan signature pending_id_for(plan_hash, kind) could not do that without a primary-key collision."
  - "Any PENDING row blocks new entries (fail closed), including a PROTECTION_ENTRY_CANCEL_NOT_SENT row while the plan is PROTECTED_ENTRY_OPEN; an unreadable store also blocks."
  - "FLAT closes every open row of the plan (stop superseded, entry-cancel and close resolved with note PLAN_FLAT)."
requirements-addressed: [RISK-03, EXEC-02]
status: complete
duration: about 2h
completed: 2026-10-21
estimate:
  tokens: 115000
  tasks: 3
actuals:
  tokens: 26500   # chars/4 over `git diff 7cce83c5 HEAD -- src tests` (106065 chars)
  tasks: 3
  commits: 6      # MEASURED: git rev-list --count 7cce83c5..HEAD at SUMMARY write, before the SUMMARY commit
plan_head_before: 7cce83c532fe8e3b23938ec1dfb60215afb195ae
plan_head_after: b4dcf893b78fb5e62257854610de347258bf0347
---

# Phase 20 Plan 14: Durable pending protective actions behind the REST gate Summary

**A stop, an entry-remainder cancel or an emergency close that the REST gate refuses (418 ban, 429 pause, gate not restored) is now a durable, payload-free PENDING row that survives a restart; it is resolved by current exchange state and a queued stop is superseded, never sent, once policy requires a close.**

Base commit `7cce83c5` (develop), branch `p20-14`. `commits: 6` is the measured `git rev-list --count 7cce83c5..HEAD` taken at SUMMARY write, before the SUMMARY commit itself. All three tasks were finished; the named split point (after Task 1) was not used. No requirement is marked complete (`requirements-addressed` lists the areas the plan contributes to; REQUIREMENTS.md is not edited).

## What was built

- **Migration 0008** (`down_revision` = `0007_intent_resolution_reason`, hand-written, imports no project module). Table `pending_protective_actions`: `pending_id` PK, `plan_hash`, `trade_plan_id`, `approval_id`, `symbol`, `pending_kind`, `state`, `gate_reason`, `first_blocked_at_utc`, `last_blocked_at_utc`, `block_count`, `retry_after_until_utc` NULL, `resolved_at_utc` NULL, `resolution_note` NULL. Named CHECKs `ck_..._kind`, `_state`, `_block_count`, `_time_order`, `_resolution` (open = no resolution time and no note, closed = both); partial unique index `uq_pending_protective_actions_open`. No column for price, quantity or side. No foreign keys (an intent log keyed by plan hash). Real downgrade. Migrations 0001-0007 are byte-unchanged (`git diff --stat -- src/db/alembic/versions/000[1-7]*.py` prints nothing).
- **`src/execution/pending_actions.py`** (stdlib + `src.domain` only): the enums, the frozen `PendingAction` (validated: UTC times, fixed-text reason and note, open/closed consistency), the `PendingActionStore` Protocol, `BlockedRecorder` (spill first once per episode, then the store; returns False when the STORE failed), `intent_event` (the journal-shaped spill record: kind, gate reason, symbol, plan id; no price, quantity or side).
- **`PgPendingActionStore`**: `record_blocked` reads the open row `FOR UPDATE` and inserts or bumps in one transaction (a lost race is `RowConflict`); `resolve` and `supersede` touch only the open row and answer None when nothing is open; `list_open` is ordered by `(first_blocked_at_utc, pending_id)`.
- **`ProtectionCoordinator`**: a refused stop (`_place_stop`) and a refused entry cancel (`_cancel_entry_remainder`) call `_record_blocked` after the existing journal row. Resolution by current state: stop read ACTIVE (`STOP_CONFIRMED_ACTIVE`), cancel accepted (`ENTRY_CANCEL_ACCEPTED`) or entry read terminal (`ENTRY_TERMINAL`). The one place a state changes (`_transition`) supersedes the STOP row on CLOSE_REQUIRED (`CLOSE_REQUIRED_BY_POLICY`) and CLOSE_FAILED, and closes every open row on FLAT. `_place_stop` returns `SKIPPED` without sending in CLOSE_REQUIRED, CLOSE_FAILED and FLAT. `blocks_new_entries()` is True while any row is PENDING and when `list_open()` raises.
- **`MarketEmergencyCloser`**: `_not_sent` records `CLOSE_NOT_SENT` (reason and retry-after from the refusal); the row is resolved when a request passes the gate (`CLOSE_SENT_AFTER_GATE`) or REST shows the position flat (`CLOSE_CONFIRMED_FLAT`). The close still re-reads the position and sizes the part itself on the next call.
- **Tests**: `tests/test_pending_actions.py` (20), `tests/test_pending_actions_pg.py` (16, PostgreSQL), 0008 additions in `tests/test_persistence_migration_pg.py` (head pinned to 0008, revision chain, no price/quantity/side column, downgrade to 0007 and back, partial-index predicate, kind and state CHECK literals), `tests/support/pending_action_fakes.py` (`InMemoryPendingActionStore`, `FailingPendingActionStore`).
- **Docs**: `docs/data/DATA_MODEL.md` section 2.17.

## Decisions on the plan's open points

- **Owner decision O-C (plan 20-07) = option a1 with commands.** Under a1 the restore reasons exist: `GateNotRestored` is a `RestGateRefusal` with reasons `GATE_NOT_RESTORED` and `GATE_STATE_UNKNOWN`, `retry_after_seconds` 1 (no end known). The tests use `RateLimitPauseActive` (429) throughout and one test, `test_a_gate_that_is_not_restored_is_recorded_like_a_pause`, covers `GateNotRestored("GATE_STATE_UNKNOWN")`. `IP_BAN_418` goes through the same code path (reason text only) and has no dedicated test. A refused safety action stays a PENDING row and never bypasses the gate; the coordinator and closer ask the gate for no exemption.
- **Nothing here claims a position always has a stop under every rate-limit condition.** While the exchange forbids sending, the plan stays in its blocking state; the pending row only records the intent (Q4). The 429/418 semantics are `[DOC]`; no `[DEMO]` claim.

## Deviations from Plan

**1. [Design] `LocalSpill` is typed through a Protocol, not imported.** The plan names `spill: LocalSpill | None`. `tests/test_protection_router_rig.py::test_protection_module_is_pure` lists the only imports `protection.py` may have (`src.domain`, `src.execution.*`, `src.persistence.errors`), so importing `src.ops.spill` (even under `TYPE_CHECKING`) would fail it. `IntentSpill` (a one-method Protocol, `write(event)`) lives in `src/execution/pending_actions.py`; `LocalSpill` satisfies it structurally (mypy clean). Behavior is as planned.

**2. [Design] `pending_id_for(plan_hash, kind, *, opened_at_utc)`.** The plan lists `pending_id_for(plan_hash, kind)`. With only those two inputs a re-block after a RESOLVED row would insert the same primary key. The opening time is a third input, so each episode has its own deterministic id.

**3. [Scope] The spill write is in the refusal branch, once per open episode.** Truth 1 of the plan says "Before ... is sent, its INTENT is written ahead to the local spill"; the Task 1 action says "In the coordinator's stop PreSendRefusal branch: write the intent ahead to the spill ..., then record_blocked". I followed the action text. Writing before every send would put a file on disk for every stop, cancel and close attempt, and the entry cancel is re-issued every step. The spill record is kept (never discarded) so a later `replay_spill` can put it into the journal; it is the fallback when the store is down.

**4. [Rule 3 - test support] `tests/support/protection_doubles.py::make_rig` gained optional `pending_actions` and `spill` keywords** (default None, handed to the coordinator and to the real closer). The file is not in `files_modified`; without it no coordinator test could attach a store.

**5. [Order] The closer's constructor keywords were added in the Task 1 GREEN commit.** `make_rig` passes them to the real closer, and the existing protection tests use `real_closer=True`; the keywords are stored in Task 1 and used in Task 2.

**6. [Scope] `_sweep` is not touched** (see "For dependents").

No pinned existing assertion had to be changed. `tests/test_persistence_migration_pg.py` got additions plus the head assertion the plan names.

## TDD Gate Compliance

Commits in order: `98e76f95` test + `19fa17cf` feat (Task 1, tracer); `8394e0aa` test + `cbbcb0a5` feat (Task 2); `3b799224` docs (Task 3); `b4dcf893` test (one extra regression guard). No REFACTOR commit. Task 3 is documentation only.

RED evidence (pytest failures seen before the GREEN commit; `gsd_run check tdd-red-evidence` does not parse pytest output and was not run):
- Task 1 RED: collection `ModuleNotFoundError: No module named 'src.execution.pending_actions'` for `tests/test_pending_actions.py` (honest: the failure is a missing module, not an assertion on the behavior; the PG tests were not run RED).
- Task 2 RED: 9 of 13 new tests failed on behavior (no entry-cancel or close row, no resolution, no supersede, `blocks_new_entries` ignored the store); 4 already passed (failing-store flow, the spill record, no bypass, behavior unchanged without a store). These four are regression guards for behavior Task 1 already delivered.
- `b4dcf893` passed on first run against the Task 2 code (guard, not a RED/GREEN pair).

Tracer feedback gate: the Task 1 verify (`tests/test_pending_actions.py`, `tests/test_pending_actions_pg.py`, `tests/test_persistence_migration_pg.py`, with `TRADING_CI_STRICT=1`) passed end to end after the GREEN code; the task has no `gate="blocking-human"`. Tracer verified, expansion followed.

## Verification actually run (only this plan's tests, the tests of touched files and the three gate files)

- Final run at `3b799224` (code unchanged since `cbbcb0a5`), sequential, `TRADING_CI_STRICT=1`, `TEST_DATABASE_URL` set: `tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_persistence_exit_evidence_pg.py tests/test_pending_actions.py tests/test_pending_actions_pg.py tests/test_persistence_migration_pg.py tests/test_metadata.py tests/test_domain_mappers.py tests/test_cutover.py tests/test_emergency_market_close.py tests/test_protection_branches.py tests/test_system_throttle_protection.py`: exit 0, no failure, no skip (strict mode turns a skip into a failure).
- Before the commit of Task 2, with `-n 4`: `tests/test_emergency_market_close.py tests/test_protection_branches.py tests/test_protection_coordinator.py tests/test_protection_router_rig.py tests/test_protection_stop_lost.py tests/test_protection_supervision.py tests/test_protection_take_profits.py tests/test_protection_transitions.py tests/test_protection_unknown_entry.py tests/test_system_throttle_protection.py tests/test_execution_emergency.py tests/test_pending_actions.py`: 251 passed.
- After the last extra test: `tests/test_pending_actions.py` 20 passed.
- `uv run mypy src`: no issues in 226 source files. `uv run ruff check` and `uv run ruff format --check`: clean. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- `git diff --exit-code -- docs/DECISIONS.md pyproject.toml uv.lock config/binance` exits 0 (T-20-SC: no package added).
- Acceptance: `grep -niE "price|quantity|side"` on the migration matches only two docstring lines (no column definition); `test_migration_0008_has_no_price_quantity_or_side_column` checks the declared column names. `git diff --stat -- src/db/alembic/versions/000[1-7]*.py` prints nothing.
- Not run: the full suite (orchestrator). Line endings: `models.py`, `protection.py`, `emergency_close.py`, `persistence/__init__.py`, `protection_doubles.py`, `test_persistence_migration_pg.py` and `DATA_MODEL.md` were converted to LF for editing and restored to CRLF (checked with `file`); new files are LF.

## Known limits

- `[NOT_TESTED]` Behaviour against a real Binance 418/429: every test uses the Binance-semantics fake and `RateLimitPauseActive` / `GateNotRestored` raised by the fake. Nothing is `[DEMO]`.
- A pending row whose supersede or resolve write failed (store down) stays PENDING in the database. The coordinator still never sends from a SUPERSEDED-state plan (`_place_stop` guards by state), and SAFE_MODE DB_FAILURE was entered; a restart must treat such a row by reading the plan, which is plan 20-19.
- Per-step cost: with a store attached, each step of a plan whose entry is not terminal issues one `resolve` after a successful cancel, which is a locked read that finds nothing in the common case. Acceptable at the expected cadence; a cheaper "known open" flag needs the restart load of plan 20-19.
- `blocks_new_entries()` reads the store on every call and counts every open row of the table, not only the rows of plans this coordinator tracks (stricter than before, as the plan states).
- The queue ORDER once the gate opens (D-20) and the restart load are not here.

## For dependents

- **20-17:** `src/execution/protection.py::_sweep` still ignores the `CancelVerdict` map that `cancel_untriggered_protectives` returns (20-11 summary) and still sets `sweep_done = True` after a non-raising call, even when a leg verified `UNKNOWN` or `STILL_OPEN`. This plan touched neither `_sweep` nor that call, so the item is untouched and remains for plan 20-17.
- **20-19:** load `PgPendingActionStore.list_open()` at start; the coordinator has no way to learn a row was left open by an earlier process except `blocks_new_entries()`. Decide per plan from the current exchange state. `BlockedRecorder` keeps its "spilled once" set in memory only, so the first refusal after a restart writes one more spill record (harmless, replay is idempotent).
- **20-21:** serve order is not set here. `list_open()` is ordered by `(first_blocked_at_utc, pending_id)`.
- **20-24:** no composition passes `pending_actions` or `spill` yet; every real coordinator and closer is still without a store until Phase 24 wires them. `GATE_NOT_RESTORED` / `GATE_STATE_UNKNOWN` reasons only appear once a real gate has a `state_store`.

## Known Stubs

None. `pending_actions` and `spill` default to None; that is intended wiring left to plans 20-19 and 24, not a stub that blocks this plan's goal.

## Threat Flags

None beyond the plan's register. T-20-34 mitigated (no payload columns, supersede guard in `_place_stop`, tests `test_superseded_stop_is_never_sent` and the schema-column tests); T-20-35 mitigated (store failure enters SAFE_MODE DB_FAILURE once, the spill record stays: `test_a_failing_pending_store_never_blocks_the_protective_flow`, `..._leaves_the_spill_record`); T-20-36 mitigated (the refusal is recorded only, `test_a_gate_refusal_is_recorded_and_never_worked_around`); T-20-SC mitigated (no package added). New file surface: the spill directory the operator already chooses for plan 20-08; no network, no endpoint.

## Self-Check: PASSED

- Files present: src/db/alembic/versions/0008_pending_protective_actions.py, src/execution/pending_actions.py, src/persistence/pending_actions.py, tests/support/pending_action_fakes.py, tests/test_pending_actions.py, tests/test_pending_actions_pg.py, and the modified src/db/models.py, src/execution/protection.py, src/execution/emergency_close.py, src/persistence/__init__.py, tests/support/protection_doubles.py, tests/test_persistence_migration_pg.py, docs/data/DATA_MODEL.md.
- Commits present on p20-14: 98e76f95, 19fa17cf, 8394e0aa, cbbcb0a5, 3b799224, b4dcf893.
- Not touched: STATE.md, ROADMAP.md, REQUIREMENTS.md, docs/DECISIONS.md, config/binance/, params/, pyproject.toml, uv.lock, `.gsd/`, `.planning/config.json`, `.planning/state.json`, `.planning/milestone.lock`.
