---
phase: 08-approval-reconciliation-hardening
plan: "02"
subsystem: approval-intake
tags: [tdd, telegram, approval, callback, short-id-mapping, atomic-write, journal-first, adapter-boundary]
dependency_graph:
  requires:
    - phase: 08-01
      provides: src/approval/tokens.py, src/approval/binding.py, src/approval/replay.py (resolve_callback core)
  provides:
    - src/adapters/telegram_notify.py (format_approve, build_approve_keyboard, build_skip_keyboard)
    - src/approval/mapping.py (ShortIdMapping + derive_short_id)
    - src/db/models.py (ShortIdMappingRow on single Base)
    - src/db/alembic/versions/0003_callback_mapping.py
    - src/db/mappers.py (short_id_mapping_to_row / short_id_mapping_from_row)
    - src/adapters/telegram_callbacks.py (PTB Application receiver — unit-tested, live-tap gate awaits operator)
    - tests/test_approval_message.py (28 tests)
  affects:
    - APRV-01 (12-field alert + 64-byte callback_data + chat gate + journal-first + restart-safe mapping)
    - 08-04 (LIVE live-tap evidence gate)
    - 08-05 (RUNBOOK drills referencing the live APPROVE/SKIP path)
tech-stack:
  added: []
  patterns:
    - strict parse_callback_data (APR/SKP/SIM/SKIP prefixes + 32-hex short_id + 64-byte ceiling)
    - chat-gate-before-state-lookup (D-01 security invariant) at the receiver boundary
    - journal-first receipt ordering (T-8-12) — JournalEvent before resolve_callback
    - atomic write contract: save_atomic(approval, mapping) owns the same transaction
    - replay-to-existing semantics (08-01 D-01) carried into the receiver
    - adapter-boundary isolation: only the two telegram adapters import python-telegram-bot
    - PTB-free text renderer (format_approve) reusable by paper-core without adapter violation
key-files:
  created:
    - src/approval/mapping.py
    - src/db/alembic/versions/0003_callback_mapping.py
    - src/adapters/telegram_callbacks.py
  modified:
    - src/adapters/telegram_notify.py
    - src/db/models.py
    - src/db/mappers.py
    - tests/test_approval_message.py
    - tests/test_paper_notify.py
key-decisions:
  - "D-08-02-01 format_approve is a PTB-free text renderer mirroring format_simulate posture (same 12 APRV-01 fields, same fail-closed validation); the renderer lives in telegram_notify.py so paper-core can reuse it without violating adapter isolation"
  - "D-08-02-02 callback_data prefixes are APR:/SKP: for live Phase-8 buttons and SIM:/SKIP: for inert Phase-7 labels; SIM/SKIP resolve to SIMULATE_RECORDED so the receiver never advances approval state in response to a SIMULATE-only button"
  - "D-08-02-03 short_id is sha256(signal_id)[:32] — deterministic across processes and Python versions; same value flows from keyboard builder to receiver parser to mapping row PK"
  - "D-08-02-04 ShortIdMappingRow lives on the single existing Base (D-02); String(32) PK on short_id; non-nullable signal_id/trade_plan_id/created_at_utc; no auto-increment"
  - "D-08-02-05 migration 0003 mirrors the 0002 op.create_table convention with two indexes (signal_id, trade_plan_id) and downgrades cleanly (verified via alembic --sql)"
  - "D-08-02-06 receiver persists ShortIdMappingRow in the SAME transaction as the Approval row transition via the injected save_atomic(approval, mapping) callable; replay paths pass mapping=None because the row already exists from the first transition"
  - "D-08-02-07 receiver is the ONLY importer of telegram.ext.Application; telegram.ext imports are forbidden in every other src/ module (verified by tests/test_approval_message.py::test_telegram_callbacks_adapter_is_the_only_ptb_application_importer)"
  - "D-08-02-08 unknown-chat callbacks are journaled as CALLBACK_RECEIVED events with chat_gate_rejected=True in payload_json so the audit trail still captures the attempt (T-8-12 repudiation mitigation)"
  - "D-08-02-09 SIMULATE_RECORDED callbacks journal the receipt but return early without calling resolve_callback (D-02 + 08-01 D-11 — SIMULATE does not advance approval state)"
  - "D-08-02-10 LIVE-TAP GATE PENDING: TELEGRAM_BOT_TOKEN and TELEGRAM_AUTHORIZED_CHAT_ID are not provisioned in this environment; operator must run a real APPROVE + SKIP tap and an unknown-chat rejection before plan 08-02 can be marked complete"
patterns-established:
  - "Pattern: callback_data prefix taxonomy — APR/SKP (live) vs SIM/SKIP (inert); receiver resolves SIM/SKIP to SIMULATE_RECORDED so phase-7 wire format stays byte-identical"
  - "Pattern: adapter-boundary isolation extended to two adapters (send-side + callback-side); both must import telegram; no other src/ module may"
  - "Pattern: atomic write contract via injected save_atomic(approval, mapping) callable — receiver owns the boundary, caller owns the transaction"
requirements-completed:
  - APRV-01
coverage:
  - id: D1
    description: "12-field APPROVE/SKIP alert (symbol, direction, setup, entry, SL, TP(s), RR, risk %, expiry, invalidation, exposure, reason codes) with byte-stable formatting and Decimal str precision"
    requirement: APRV-01
    verification:
      - kind: unit
        ref: "tests/test_approval_message.py#test_format_approve_renders_all_12_aprv01_fields"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_format_approve_rejects_empty_symbol"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_format_approve_rejects_inverted_entry_bounds"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_format_approve_rejects_empty_take_profits"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_format_approve_rejects_naive_datetime"
        status: pass
    human_judgment: false
  - id: D2
    description: "build_approve_keyboard and build_skip_keyboard emit APR:/SKP: callback_data within Telegram's 64-byte ceiling; both keyboards share the same deterministic short id"
    requirement: APRV-01
    verification:
      - kind: unit
        ref: "tests/test_approval_message.py#test_build_approve_keyboard_emits_apr_short_id_within_64_bytes"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_build_skip_keyboard_emits_skp_short_id_within_64_bytes"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_build_approve_and_skip_keyboards_share_short_id"
        status: pass
    human_judgment: false
  - id: D3
    description: "Existing SIMULATE wire format (SIM:/SKIP: labels) is byte-identical — no Phase-7 test breaks"
    requirement: APRV-01
    verification:
      - kind: unit
        ref: "tests/test_approval_message.py#test_simulate_keyboard_callback_data_byte_identical"
        status: pass
      - kind: unit
        ref: "tests/test_paper_notify.py (6 tests still green)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Short-to-full mapping: ShortIdMappingRow on the single existing Base with String(32) PK on short_id, non-nullable signal_id/trade_plan_id/created_at_utc; migration 0003 creates the table with the 0002 op.create_table convention; mapper round-trips"
    requirement: APRV-01
    verification:
      - kind: unit
        ref: "tests/test_approval_message.py#test_short_id_mapping_orm_row_uses_single_base"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_short_id_mapping_round_trip_via_orm_row"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_migration_0003_creates_short_id_mapping_table"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_approval_mapping_module_is_dependency_free"
        status: pass
      - kind: automated_sql
        ref: "alembic upgrade head --sql (clean CREATE TABLE + 2 indexes)"
        status: pass
      - kind: automated_sql
        ref: "alembic downgrade 0003_callback_mapping:0002_domain_registry --sql (clean DROP)"
        status: pass
    human_judgment: false
  - id: D5
    description: "PTB callback receiver: parse_callback_data strict, authorized_chat_gate runs BEFORE state lookup, journal-first receipt before resolve_callback, atomic save_atomic(approval, mapping), delegate to 08-01 resolve_callback"
    requirement: APRV-01
    verification:
      - kind: unit
        ref: "tests/test_approval_message.py#test_parse_callback_data_accepts_apr_skp_sim_skip_prefixes"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_parse_callback_data_rejects_malformed_payloads"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_authorized_chat_gate_runs_before_state_lookup"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_dispatch_callback_chat_gate_runs_before_state_lookup"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_dispatch_callback_journal_first_receipt_before_resolve"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_dispatch_callback_simulate_recorded_does_not_advance_state"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_dispatch_callback_atomic_write_passes_mapping_to_save"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_dispatch_callback_replay_returns_existing_approval"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_dispatch_callback_binding_gate_failure_returns_reason_code"
        status: pass
      - kind: unit
        ref: "tests/test_approval_message.py#test_telegram_callbacks_adapter_is_the_only_ptb_application_importer"
        status: pass
    human_judgment: false
  - id: D6
    description: "LIVE-TAP GATE — operator must confirm a real APPROVE tap and a real SKIP tap each produce exactly one Approval transition and clear the client spinner, AND an unknown-chat callback is rejected with no state change"
    requirement: APRV-01
    verification: []
    human_judgment: true
    rationale: "Live-tap evidence requires TELEGRAM_BOT_TOKEN + TELEGRAM_AUTHORIZED_CHAT_ID provisioned in this environment, plus a real Telegram bot + chat. Both are operator-controlled; this executor cannot fabricate taps. Auto-mode does NOT auto-approve this gate per operator instructions — live verification MUST be operator-confirmed."
metrics:
  duration: "~25 min"
  completed_date: "2026-09-27"
  tasks: 3
  commits: 3
  tests_added: 28
  tests_passing: 28
  full_suite_regressions: 0
status: halted
plan_head_before: e682ba1
commits: 3
actuals:
  tokens: 23852
  tasks: 3
  commits: 3
---

# Phase 8 Plan 02: APPROVE/SKIP Telegram Intake + Short-Id Mapping Summary

**12-field APPROVE/SKIP alerts + 64-byte callback_data + chat-gate-first + journal-first receipt + restart-safe short→full mapping; live-tap gate awaits operator with TELEGRAM_BOT_TOKEN + TELEGRAM_AUTHORIZED_CHAT_ID**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-09-27T13:35:00Z (approx)
- **Completed:** 2026-09-27T14:00:00Z (approx)
- **Tasks:** 3 (2 complete + 1 awaiting live-tap verification)
- **Files modified:** 8
- **Tokens:** 23852 (chars/4 over realized diff)

## Accomplishments

- **12-field APPROVE/SKIP alert text** rendered via PTB-free `format_approve(...)` in `src/adapters/telegram_notify.py`, mirroring `format_simulate` posture exactly (same 12 APRV-01 fields, same Decimal str precision, same UTC-aware datetime validation, same fail-closed ValueError posture on malformed payloads).
- **64-byte callback_data keyboards** `build_approve_keyboard` and `build_skip_keyboard` emit `APR:<32-hex>` and `SKP:<32-hex>` (36 bytes total) — well under Telegram's hard limit. Both keyboards share the same deterministic short id so the receiver resolves either callback to the same approval.
- **Existing SIMULATE wire format preserved** — `build_simulate_keyboard` still emits `SIM:<short>` and `SKIP:<short>` (the inert Phase-7 labels); receiver resolves SIM/SKIP to `SIMULATE_RECORDED` so the phase-7 byte format is untouched. All 6 Phase-7 paper_notify tests still green.
- **Short→full mapping** in `src/approval/mapping.py` (pure record type, dependency-free) + `ShortIdMappingRow` on the single existing Base (String(32) PK, non-nullable signal_id/trade_plan_id/created_at_utc) + migration `0003_callback_mapping.py` (mirrors 0002 convention, downgrades cleanly via `alembic --sql`).
- **PTB callback receiver** in `src/adapters/telegram_callbacks.py` — the ONLY `telegram.ext.Application` importer. Strict `parse_callback_data` (APR/SKP/SIM/SKIP + 32-hex + 64-byte ceiling), `authorized_chat_gate` (runs BEFORE any state lookup), `dispatch_callback` (journal-first receipt → short-id mapping lookup → delegate to `resolve_callback` → atomic `save_atomic(approval, mapping)` write), `on_callback` (PTB handler with `query.answer()` spinner clear first).
- **Atomic write contract** — the receiver's injected `save_atomic(approval, mapping)` callable owns the same transaction for the ShortIdMappingRow insert and the Approval row transition. Replay paths pass `mapping=None` because the mapping row already exists from the first transition; the receiver never opens its own session.
- **Adapter-boundary isolation** — `python-telegram-bot` imports are confined to two adapters (send-side `telegram_notify.py` + callback-side `telegram_callbacks.py`). No other src/ module may import `telegram.ext` (verified by `test_telegram_callbacks_adapter_is_the_only_ptb_application_importer`).
- **28 new unit tests** covering: 12-field rendering, 64-byte ceiling, shared short-id, SIMULATE wire-format stability, mapping determinism + validators + round-trip + single-Base invariant + migration chain + purity grep, parse (APR/SKP/SIM/SKIP + malformed), chat gate, journal-first ordering, SIMULATE_RECORDED inert path, atomic write contract, replay-to-existing, binding-gate failure translation, and PTB Application importer isolation.

## Task Commits

Each task was committed atomically:

1. **Task 1: APPROVE/SKIP 12-field message + keyboards (TDD)** — `d649dc1` (`feat(08-02): APPROVE/SKIP 12-field message + APR/SKP keyboards (TDD)`)
2. **Task 2: Short-to-full mapping + migration 0003 + mapper** — `3749e08` (`feat(08-02): short-to-full mapping row + migration 0003 + mapper`)
3. **Task 3: PTB callback receiver + dispatch + journal-first ordering** — `166276f` (`feat(08-02): PTB callback receiver + dispatch + journal-first ordering`)

**Plan metadata:** not yet committed (this SUMMARY) — pending.

_Note: TDD task followed RED → GREEN → REFACTOR with one commit (test + impl together), per the project precedent in 08-01._

## Files Created/Modified

- `src/adapters/telegram_notify.py` — added `format_approve`, `build_approve_keyboard`, `build_skip_keyboard`, `_short_signal_id_with_prefix`, `APR_PREFIX`/`SKP_PREFIX`/`SIM_PREFIX`/`SKIP_PREFIX`/`TELEGRAM_CALLBACK_DATA_MAX_BYTES` constants. Existing `build_simulate_keyboard` byte-identical.
- `src/approval/mapping.py` — **NEW** — `ShortIdMapping` frozen dataclass, `derive_short_id(signal_id)`, `make_short_id_mapping(...)`, `SHORT_ID_LENGTH` constant. Dependency-free (stdlib + src/domain/* only).
- `src/db/models.py` — added `ShortIdMappingRow` on the single existing Base. String(32) PK on short_id, non-nullable signal_id/trade_plan_id/created_at_utc. No auto-increment. No second declarative base.
- `src/db/alembic/versions/0003_callback_mapping.py` — **NEW** — `down_revision = "0002_domain_registry"`, mirrors 0002 `op.create_table` convention, two indexes (signal_id, trade_plan_id), clean downgrade (verified via `alembic --sql`).
- `src/db/mappers.py` — added `short_id_mapping_to_row` and `short_id_mapping_from_row`. Round-trippable. No Enum translation needed (plain strings + UTC-aware datetime).
- `src/adapters/telegram_callbacks.py` — **NEW** — the ONLY `telegram.ext.Application` importer. `CallbackKind` enum, `ParsedCallback` frozen dataclass, `parse_callback_data`, `authorized_chat_gate`, `dispatch_callback`, `on_callback` (PTB handler), `build_application` (ApplicationBuilder + CallbackQueryHandler). Pure surfaces (`parse_callback_data`, `authorized_chat_gate`, `dispatch_callback`) take injected dependencies so unit tests never touch the network.
- `tests/test_approval_message.py` — **NEW** — 28 tests across 8 behaviors (12-field rendering, 64-byte ceiling, SIMULATE stability, mapping module + model + migration, parse, chat gate, journal-first, atomic write, replay-to-existing, binding-gate failure, PTB Application isolation).
- `tests/test_paper_notify.py` — updated `test_telegram_adapter_is_the_only_telegram_importer` to allow both adapters (send-side + callback-side).

## Decisions Made

- **format_approve is PTB-free** — mirrors `format_simulate` posture exactly. Lives in `telegram_notify.py` so paper-core can reuse it without violating adapter isolation. (Decision `D-08-02-01`.)
- **Callback-data prefix taxonomy** — APR:/SKP: are the live Phase-8 prefixes; SIM:/SKIP: remain the inert Phase-7 labels and resolve to `SIMULATE_RECORDED`. Phase-7 wire format is byte-identical. (Decision `D-08-02-02`.)
- **Short-id derivation** — `sha256(signal_id)[:32]`, deterministic across processes and Python versions. The same value flows from keyboard builder to receiver parser to mapping row PK. (Decision `D-08-02-03`.)
- **ShortIdMappingRow on the single Base** — String(32) PK on short_id, non-nullable fields, no auto-increment. Mirrors the D-02/D-03 purity precedent from 03-04. (Decision `D-08-02-04`.)
- **Migration 0003 mirrors 0002 convention** — same `op.create_table` shape, two lookup indexes (`ix_short_id_mapping_signal_id`, `ix_short_id_mapping_trade_plan_id`), downgrades cleanly via `alembic downgrade --sql`. (Decision `D-08-02-05`.)
- **Atomic write contract via injected `save_atomic(approval, mapping)`** — the receiver owns the boundary; the caller owns the transaction. Replay paths pass `mapping=None` because the row already exists. (Decision `D-08-02-06`.)
- **Receiver is the ONLY `telegram.ext.Application` importer** — adapter-boundary isolation extended to two adapters. No other src/ module may import `telegram.ext` (verified by test). (Decision `D-08-02-07`.)
- **Unknown-chat callbacks journaled as CALLBACK_RECEIVED with `chat_gate_rejected=True`** — the audit trail still captures the attempt (T-8-12 repudiation mitigation). (Decision `D-08-02-08`.)
- **SIMULATE_RECORDED callbacks journal but do not advance state** — receiver returns early without calling `resolve_callback` for SIM/SKIP prefixes. (Decision `D-08-02-09`.)
- **LIVE-TAP GATE PENDING** — `TELEGRAM_BOT_TOKEN` and `TELEGRAM_AUTHORIZED_CHAT_ID` are not provisioned in this environment. Operator must run a real APPROVE + SKIP tap and confirm an unknown-chat rejection before plan 08-02 can be marked complete. (Decision `D-08-02-10`.)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed stale telegram-importer assertion in test_paper_notify.py**
- **Found during:** Task 3 (after adding `telegram_callbacks.py`)
- **Issue:** The Phase-7 test `test_telegram_adapter_is_the_only_telegram_importer` asserted that ONLY `telegram_notify.py` imports `telegram`. With the Phase-8 callback receiver adding a second importer, the assertion fired.
- **Fix:** Updated both `tests/test_approval_message.py::test_telegram_adapter_is_the_only_telegram_importer` and `tests/test_paper_notify.py::test_telegram_adapter_is_the_only_telegram_importer` to allow both adapters (sorted for determinism) and added `test_telegram_callbacks_adapter_is_the_only_ptb_application_importer` to enforce the stricter `telegram.ext` boundary.
- **Files modified:** tests/test_approval_message.py, tests/test_paper_notify.py
- **Committed in:** 166276f (Task 3 commit)

**2. [Rule 3 - Blocking] Fixed pytest import-order issue in test_approval_message.py**
- **Found during:** Task 1 (ruff check post-GREEN)
- **Issue:** Ruff flagged un-sorted imports in the new test file.
- **Fix:** Ran `ruff check --fix` to organize the imports.
- **Files modified:** tests/test_approval_message.py
- **Committed in:** d649dc1 (Task 1 commit)

**3. [Rule 1 - Bug] Fixed ruff format findings across new files**
- **Found during:** Task 1 + Task 2 + Task 3
- **Issue:** Multiple ruff format findings (collapsed multi-line strings, InlineKeyboardMarkup constructor formatting, etc.).
- **Fix:** Ran `ruff format` on all new/modified files.
- **Files modified:** src/adapters/telegram_notify.py, src/adapters/telegram_callbacks.py, tests/test_approval_message.py, tests/test_paper_notify.py
- **Committed in:** d649dc1, 3749e08, 166276f (per-task commits)

**4. [Rule 1 - Bug] Fixed mypy errors in src/adapters/telegram_callbacks.py**
- **Found during:** Task 3 (static gates check)
- **Issue:** mypy flagged three issues: `MaybeInaccessibleMessage.chat_id` attr-defined error (query.message can be inaccessible in newer PTB), `Application` missing type arguments, and an unused `type: ignore` comment.
- **Fix:** Added `getattr(query.message, "chat_id", None)` guard with a documenting comment explaining the PTB type-narrowing workaround; typed `Application` as `Application[Any, Any, Any, Any, Any, Any]`; removed the unused `type: ignore` comment.
- **Files modified:** src/adapters/telegram_callbacks.py
- **Committed in:** 166276f (Task 3 commit)

**5. [Rule 1 - Bug] Fixed test assertion using wrong short-id value**
- **Found during:** Task 3 (atomic-write test)
- **Issue:** Test asserted `saved_mapping.short_id == "a" * 32` (literal callback_data short id), but the mapping's short_id is `derive_short_id(signal_id)` (sha256 prefix of signal_id), not the callback_data literal.
- **Fix:** Updated the assertion to compare against `derive_short_id(signal_id)` with a documenting comment explaining the D-02 derivation rule.
- **Files modified:** tests/test_approval_message.py
- **Committed in:** 166276f (Task 3 commit)

---

**Total deviations:** 5 auto-fixed (4 bug fixes, 1 import-ordering)
**Impact on plan:** All auto-fixes necessary for static-gate compliance and correctness. No scope creep. The plan's structural shape (3 tasks, 8 files, 28 tests, 3 commits) is preserved.

## Issues Encountered

- **mypy + PTB Application generic typing** — the `Application` class is generic over 6 type parameters; defaulting to `Any` for all six was the cleanest path forward since the receiver never inspects the context types.
- **`query.message.chat_id` is a MaybeInaccessibleMessage union** — newer PTB versions (22.x) widened `query.message` to include `MaybeInaccessibleMessage` which lacks `chat_id`. The handler uses `getattr(query.message, "chat_id", None)` and only replies if the chat_id is available; the operator still sees the spinner clear via `query.answer()` which always runs first.

## User Setup Required

**External services require manual configuration.** This plan's `user_setup` block (TELEGRAM_BOT_TOKEN + TELEGRAM_AUTHORIZED_CHAT_ID) is the live-tap gate. Without these, the operator cannot confirm the live APPROVE/SKIP flow end-to-end.

To provision and verify:

1. **Create the Telegram bot** via @BotFather; copy the token.
2. **Find your chat id** via @userinfobot.
3. **Set environment variables:**
   ```bash
   export TELEGRAM_BOT_TOKEN="<token from BotFather>"
   export TELEGRAM_AUTHORIZED_CHAT_ID="<chat id from userinfobot>"
   ```
4. **Run the operator verification drill** — start the paper loop, wait for a Phase-8 APPROVE/SKIP alert, tap APPROVE then SKIP, and send a callback from an unknown chat. Confirm:
   - Each tap produces exactly one Approval transition (DB row count delta = 1).
   - The client spinner clears on every tap.
   - The unknown-chat callback is rejected with no Approval row mutation.
5. **Resume-signal** — operator replies with the tap evidence (transition counts + unknown-chat rejection observation), then execution continues to 08-04/08-05 waves.

## Next Phase Readiness

- **For 08-04 (reconciler) and 08-05 (RUNBOOK drills)**: nothing blocks — the approval core + intake + mapping are unit-test-green and the live-tap gate is operator-side only.
- **For 08-04 reconciliation sweep**: the receiver's atomic-write contract means the reconciler can assume every PENDING approval has a corresponding ShortIdMappingRow on disk; the sweeper's "delete the orphan protective" path does not need to consult the mapping table.
- **For 08-05 drills**: the journal-first receipt (D-02 + T-8-12) means every callback attempt — including chat-gate rejections — leaves an audit trail in `journal_events`, so the drill harness can replay the event sequence for verification.
- **Live-tap gate**: blocked on operator provisioning of TELEGRAM_BOT_TOKEN + TELEGRAM_AUTHORIZED_CHAT_ID and a real APPROVE + SKIP tap + unknown-chat rejection. Until that gate passes, plan 08-02 cannot be marked `status: complete` — it stays at `status: halted` per the schema rule.

## Self-Check

- [x] `src/adapters/telegram_notify.py` exists with `format_approve`, `build_approve_keyboard`, `build_skip_keyboard`
- [x] `src/approval/mapping.py` exists with `ShortIdMapping`, `derive_short_id`, `make_short_id_mapping`
- [x] `src/db/models.py` has `ShortIdMappingRow` on the single Base (verified by `test_short_id_mapping_orm_row_uses_single_base`)
- [x] `src/db/alembic/versions/0003_callback_mapping.py` exists with `down_revision = "0002_domain_registry"`
- [x] `src/db/mappers.py` has `short_id_mapping_to_row` + `short_id_mapping_from_row` (round-trip tested)
- [x] `src/adapters/telegram_callbacks.py` exists; ONLY `telegram.ext.Application` importer
- [x] `tests/test_approval_message.py` has 28 tests, all green
- [x] Migration upgrade SQL clean (verified via `alembic upgrade head --sql`)
- [x] Migration downgrade SQL clean (verified via `alembic downgrade --sql`)
- [x] 68 tests pass (28 approval_message + 13 approval_replay + 6 paper_notify + 21 order_ids)
- [x] ruff check clean
- [x] ruff format clean
- [x] mypy strict clean (src/adapters/telegram_callbacks.py)
- [x] adapter-boundary isolation enforced (verified by `test_telegram_callbacks_adapter_is_the_only_ptb_application_importer`)
- [ ] **LIVE-TAP GATE PENDING** — operator must run a real APPROVE + SKIP tap + unknown-chat rejection before plan can be marked complete

## Self-Check: PASSED (with live-tap gate outstanding)

All unit-testable work is complete and committed. The live-tap gate is the only outstanding item and is operator-side (requires TELEGRAM_BOT_TOKEN + TELEGRAM_AUTHORIZED_CHAT_ID provisioning).

---
*Phase: 08-approval-reconciliation-hardening*
*Completed: 2026-09-27 (unit-testable work); live-tap gate outstanding*
