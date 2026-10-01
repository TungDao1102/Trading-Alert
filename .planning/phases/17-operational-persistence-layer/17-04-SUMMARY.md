---
phase: 17-operational-persistence-layer
plan: 04
subsystem: domain
tags: [journal, determinism, idempotency, telegram, tdd]

requires:
  - phase: 17-operational-persistence-layer
    provides: "plan 01: persistence foundations (journal store arrives in plan 08)"
provides:
  - "src/domain/journal.py: correlated_event_id (pure function of prefix, correlation id, event type, entity id, step)"
  - "SAFE_MODE, orphan-sweeper and drill-outcome journal ids built with content_hash_event_id (collision-free, replay-stable)"
  - "Telegram callback correlation id cbq:<callback_query.id> and deterministic receipt, chat-reject and outcome ids"
  - "tests/test_journal_ids.py: determinism and collision tests for every fixed builder"
affects: [17-08, 17-15]

actuals:
  tokens: 11000
  tasks: 2
  commits: 4
plan_head_before: 950316f47a8929f42c62402978cf50ad0ecf70e0
plan_head_after: 125d5c500bd1b63383d272fdba99f583ace74b02

tech-stack:
  added: []
  patterns:
    - "Journal ids are pure functions of event content or of a stable external correlation; no clock suffix, no randomness, no DB sequence"
    - "Callback payloads carry no wall-clock field; the occurred_at_utc column holds delivery time, so a redelivery is byte-identical in payload_json"
    - "Outcome step label encodes ok and reason_code so distinct outcomes of one correlation never share an id"

key-files:
  created:
    - tests/test_journal_ids.py
  modified:
    - src/domain/journal.py
    - src/reconcile/safe_mode.py
    - src/reconcile/sweeper.py
    - src/ops/drills.py
    - src/adapters/telegram_callbacks.py
    - tests/test_phase8_audit_reviewfix.py

key-decisions:
  - "A callback query without a non-empty string id raises ValueError before dispatch (fail closed); a missing attribute is treated the same as an empty id"
  - "correlated_event_id hashes a compact JSON array of the four non-prefix values (not a delimiter join), so field boundaries cannot be shifted to forge a collision, and it raises if the id would exceed the 128-char column"
  - "content_hash_event_id left byte-identical (enablement, health, kill-gate and manager cancel ids unchanged)"

patterns-established:
  - "Plan 08's journal store can use journal_event_id as the idempotency key: same event, same id; different event, different id"

requirements-completed: [DOMN-01, APRV-02]

coverage:
  - id: D1
    description: "correlated_event_id is deterministic across calls and fresh interpreters, sensitive to each argument, at most 128 chars, and rejects empty arguments"
    requirement: DOMN-01
    verification:
      - kind: unit
        ref: "tests/test_journal_ids.py#test_correlated_event_id_shape_and_determinism"
        status: pass
      - kind: unit
        ref: "tests/test_journal_ids.py#test_correlated_event_id_stable_across_fresh_interpreters"
        status: pass
      - kind: unit
        ref: "tests/test_journal_ids.py#test_correlated_event_id_changes_with_each_argument"
        status: pass
    human_judgment: false
  - id: D2
    description: "SAFE_MODE, orphan-sweeper and drill-outcome event ids hash event content: different events at one instant differ, the same event is stable"
    requirement: DOMN-01
    verification:
      - kind: unit
        ref: "tests/test_journal_ids.py#test_safe_mode_ids_differ_for_different_reasons_at_same_instant"
        status: pass
      - kind: unit
        ref: "tests/test_journal_ids.py#test_sweeper_pre_and_post_cancel_differ_for_one_algo_id"
        status: pass
      - kind: unit
        ref: "tests/test_journal_ids.py#test_drill_ids_differ_for_different_payloads_at_same_instant"
        status: pass
    human_judgment: false
  - id: D3
    description: "A redelivered Telegram callback produces identical journal ids and payloads; correlation comes from callback_query.id; ok and rejected outcomes and the chat-reject receipt get distinct ids"
    requirement: APRV-02
    verification:
      - kind: unit
        ref: "tests/test_journal_ids.py#test_redelivery_journals_identical_ids_and_payloads"
        status: pass
      - kind: unit
        ref: "tests/test_journal_ids.py#test_on_callback_correlation_comes_from_callback_query_id"
        status: pass
      - kind: unit
        ref: "tests/test_journal_ids.py#test_ok_and_rejected_outcomes_for_one_correlation_never_share_an_id"
        status: pass
      - kind: unit
        ref: "tests/test_journal_ids.py#test_on_callback_rejects_missing_query_id_before_dispatch"
        status: pass
    human_judgment: false

duration: 35min
completed: 2026-10-01
status: complete
---

# Phase 17 Plan 04: Deterministic Journal Ids Summary

**Every journal id builder flagged by F-412 is now a pure function of event content or of Telegram's stable callback_query.id, so a replay writes the same id and two different events never collide.**

## Performance

- **Duration:** ~35 min (about 12 of them the full suite)
- **Tasks:** 2 (both TDD, RED then GREEN)
- **Files:** 1 created, 6 modified

## Accomplishments

- `correlated_event_id` added beside `content_hash_event_id` in `src/domain/journal.py`; no clock, no randomness; stable across fresh interpreters.
- SAFE_MODE, orphan-sweeper (pre, failed, post) and drill-outcome ids replaced the `(name, millisecond)` form with `content_hash_event_id` over event type, entity, occurred_at and payload.
- `on_callback` derives `cbq:<callback_query.id>`; receipt, chat-reject and outcome events use `correlated_event_id` with steps `receipt`, `chat_reject` and `outcome:<ok>:<reason or NONE>`. The `received_at_utc` payload field and every `uuid` suffix are gone.

## Task Commits

1. Task 1 RED: `2410113` test(17-04): RED for deterministic collision-free journal ids
2. Task 1 GREEN: `43091b0` feat(17-04): content-hash ids for SAFE_MODE, sweeper and drill events, correlated_event_id
3. Task 2 RED: `6162510` test(17-04): RED for replay-stable callback correlation and ids
4. Task 2 GREEN: `125d5c5` feat(17-04): replay-stable callback correlation and deterministic callback ids

## Verification (real runs)

- Task 1 verify: `pytest tests/test_journal_ids.py tests/test_drills.py tests/test_reconcile.py tests/test_execution_enablement.py tests/test_kill_gate_event.py` exit 0 (plus `tests/test_phase8_audit_reviewfix.py`).
- Task 2 verify: `pytest tests/test_journal_ids.py tests/test_approval_message.py tests/test_phase8_audit_reviewfix.py tests/test_approval_replay.py tests/test_paper_notify.py` exit 0.
- `mypy src`: no issues in 125 files. `ruff check`: all checks passed. `ruff format --check src tests`: 279 files already formatted.
- Full suite `pytest -m "not docker" -q` with the dev PostgreSQL `trading_test` URL: exit 0, no F/E markers, 100%.
- Acceptance greps: no `_{int(now_utc.timestamp() * 1000)}` in the three modules; one `def correlated_event_id`; `content_hash_event_id(` appears 3 times in sweeper.py (plus the import); `uuid` count 0 and `received_at_utc` absent in telegram_callbacks.py; `correlated_event_id(` appears 3 times; `cbq:` present.
- Repo-root `ruff format --check` still reports one file (the planning document `17-RESEARCH.md`), already logged in `deferred-items.md` by plan 17-01; not touched here.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Existing test fakes lacked `callback_query.id`**
- **Found during:** Task 2 GREEN
- **Issue:** `_FakeQuery` in `tests/test_phase8_audit_reviewfix.py` had no `id`, so `on_callback` (now fail-closed on a missing id) failed three existing tests; `test_wr17` relied on random suffixes for distinct correlations.
- **Fix:** `_FakeQuery` takes a `query_id`; `test_wr17` now gives each press a distinct query id.
- **Files modified:** tests/test_phase8_audit_reviewfix.py
- **Commit:** 125d5c5

**2. [Plan scope note] `tests/test_approval_message.py` and `tests/test_approval_replay.py` needed no edits**
- They passed unchanged (their correlation ids are caller-supplied literals), so they are not in the diff although the plan listed them.

**Total deviations:** 1 auto-fixed (Rule 3), 1 scope note. **Impact:** none on behavior.

## Known Stubs

None.

## Threat Flags

None. T-17-11 and T-17-12 mitigated as planned; T-17-13 accepted per plan.

## Issues Encountered

None. The first RED for Task 1 initially failed at collection (missing import); the test module was changed to late-bind `correlated_event_id` so each test fails on its own merits before the GREEN commit.

## Self-Check: PASSED

- `tests/test_journal_ids.py` and this SUMMARY exist; commits 2410113, 43091b0, 6162510, 125d5c5 exist; measured commit count 4 from the recorded plan head.

## Next

Ready for the next Phase 17 plan; plan 08's journal store can rely on `journal_event_id` as an idempotency key (compare identity fields and payload on conflict, ignore occurred_at_utc/created_at_utc).
