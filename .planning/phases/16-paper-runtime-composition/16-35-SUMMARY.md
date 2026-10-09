---
phase: 16-paper-runtime-composition
plan: 35
subsystem: paper / record attribution
tags: [shadow, attribution, approval-delay, paper-record, d-15, sc3, digest-stable, loader]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plan 16-05: evidence loader with the REAL / fixture marker; plan 16-11: SHADOW confirm step and its journal event types and reasons"
provides:
  - "src/paper/journal.py: PaperRecord optional SHADOW fields (mode, approval_requested_at_utc, confirm_requested_at_utc, confirmed_at_utc, test_only), SHADOW_MODE, canonical_record_dict, assemble_paper_record(mode=, confirm=, test_only=, shadow_outcome=)"
  - "src/paper/attribution.py: ShadowOutcome, attribute_shadow_outcome, the confirm event and reason literals; APPROVAL_DELAY_LAG_SECONDS documented as the default for records with no human action only"
  - "src/adapters/analytics_files.py: _load_paper_record accepts the optional SHADOW keys (absent means None / False)"
  - "tests/test_paper_approval_delay_measured.py (37 tests), one added test in tests/test_paper_attribution.py"
affects: [16-31 runtime composition (SHADOW fill driver builds the ShadowOutcome and the approval / confirm dicts from the journal), 16-36 SHADOW journal report (reads the new keys through the evidence loader)]

requirements-completed: [PAPER-02]

actuals:
  tokens: 14000
  tasks: 2
  commits: 4
plan_head_before: 67c76b6375faa99f9bae99429933b4387f3fad29
plan_head_after: 8c6de16d1972bc98bfcaf255edeb96078cba575b
commits: 4

tech-stack:
  added: []
  patterns:
    - "Optional record fields omitted from the canonical dict when None / False, so every earlier digest hashes unchanged"
    - "Human action is read from the approval row's action (APPROVE, SKIP_USER, SKIP_BUSY, CANCEL); SIMULATE is the simulator leg and keeps the constant; a missing or unknown action fails closed"
    - "attribution.py stays stdlib-only; the journal vocabulary literals it repeats are pinned to their source modules by a test"

key-files:
  created:
    - tests/test_paper_approval_delay_measured.py
  modified:
    - src/paper/journal.py
    - src/paper/attribution.py
    - src/adapters/analytics_files.py
    - tests/test_paper_attribution.py

key-decisions:
  - "Q-K representation (planner choice kept): optional fields on PaperRecord, omitted from the canonical output when absent, not a new evidence kind. mode is limited to 'SHADOW', test_only is written only when True, the three new timestamps are UTC-aware and ordered (requested <= acted, confirm_requested <= confirmed)"
  - "A record has a human action iff its approval row's action is APPROVE, SKIP_USER, SKIP_BUSY or CANCEL and mode is SHADOW. Then acted_at_utc and requested_at_utc are mandatory and the measured value is recorded; the constant is used (and the WR-05a cross-check kept) only for the SIMULATE leg or when mode is absent, so Phase 7 to 10 behaviour is untouched"
  - "A filled SHADOW record must be APPROVE with both confirm timestamps and acted <= confirm_requested <= confirmed; a plan that was approved but not confirmed can only be an opportunity"
  - "Reason strings are existing vocabulary: approval actions, APPROVAL_EXPIRED, the confirm event types, and the journaled confirm reasons (CARD_DELIVERY_FAILED, RUNTIME_RESTART, USER_ID_UNAVAILABLE, a gate RejectionReason). CONFIRM_TTL_ELAPSED and a missing reason map to the event name SHADOW_CONFIRM_EXPIRED, as the plan states. An untouched plan is opportunity EXPIRED once it expired (the existing Case 3 rule, 07-CONTEXT D-03 line 24), else system alone"
  - "attribute_shadow_outcome raises for outcomes not decidable yet (APPROVE with no terminal confirm event, non-terminal events, unknown action, inconsistent combinations) instead of guessing"

patterns-established:
  - "assemble_paper_record(shadow_outcome=...) is the single place the SHADOW attribution is applied; a caller that only passes mode='SHADOW' with human filled legs gets APPROVE + SHADOW_CONFIRMED derived"

coverage:
  - id: D1
    description: "A SHADOW record with a real human action carries acted_at_utc - requested_at_utc (47 s in the test) and the confirm timestamps; a real timestamp is never replaced by signal + 30 s; a human action without its acted or requested timestamp, or acted before requested, is refused"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_approval_delay_measured.py#test_a_shadow_record_with_a_real_approval_carries_the_measured_delay"
        status: pass
      - kind: unit
        ref: "tests/test_paper_approval_delay_measured.py#test_the_measured_delay_is_not_overridden_by_signal_plus_the_constant"
        status: pass
      - kind: unit
        ref: "tests/test_paper_approval_delay_measured.py#test_a_human_action_without_its_acted_timestamp_cannot_fall_back_to_the_constant"
        status: pass
    human_judgment: false
  - id: D2
    description: "A record with no human action keeps acted_at = signal + APPROVAL_DELAY_LAG_SECONDS and the disagreement check, with and without the SHADOW mode"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_approval_delay_measured.py#test_a_record_with_no_human_action_keeps_the_documented_constant"
        status: pass
    human_judgment: false
  - id: D3
    description: "The new SHADOW fields are omitted from the canonical output when absent; every pinned Phase 7 digest and the other paper and analytics suites are unchanged (no expected literal edited)"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_approval_delay_measured.py#test_the_new_fields_are_omitted_from_the_canonical_output_when_absent"
        status: pass
      - kind: unit
        ref: "tests/test_paper_attribution.py#test_canonical_digest_equals_expected"
        status: pass
    human_judgment: false
  - id: D4
    description: "APPROVE then CONFIRM is user-executed-sim; SKIP, CANCEL, APPROVAL_EXPIRED, confirm cancel, confirm expiry (TTL, CARD_DELIVERY_FAILED, RUNTIME_RESTART, USER_ID_UNAVAILABLE) are opportunity with their reason and never user-executed-sim; untouched plans follow the existing rule; undecided outcomes are refused"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_approval_delay_measured.py#test_every_shadow_outcome_is_attributed"
        status: pass
      - kind: unit
        ref: "tests/test_paper_approval_delay_measured.py#test_an_approved_plan_that_was_not_confirmed_is_never_user_executed_sim"
        status: pass
      - kind: unit
        ref: "tests/test_paper_attribution.py#test_shadow_attribution_of_an_untouched_expired_plan_matches_the_existing_rule"
        status: pass
    human_judgment: false
  - id: D5
    description: "AttributionKind values are byte-exact; the evidence loader accepts the optional keys, refuses unknown keys, bad modes, non-bool test_only and non-UTC timestamps, and round-trips a SHADOW record; test_analytics_files and test_analytics_cli pass unchanged"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_paper_approval_delay_measured.py#test_the_evidence_loader_accepts_the_optional_shadow_keys"
        status: pass
      - kind: unit
        ref: "tests/test_paper_approval_delay_measured.py#test_attribution_kind_values_are_unchanged_byte_for_byte"
        status: pass
    human_judgment: false
  - id: D6
    description: "The assembler is fed real journal facts (approval row, confirm events) by the running SHADOW chain and the exporter writes these keys into the evidence file"
    requirement: PAPER-02
    verification: []
    human_judgment: true
    rationale: "Wiring the journal into ShadowOutcome and the approval / confirm dicts is plan 16-31; writing the keys into evidence files is plan 16-36. This plan provides the record shape, the assembler and the loader only"

duration: 12min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 35: Measured approval delay and SHADOW attribution Summary

**SHADOW paper records now carry the measured `acted_at_utc - requested_at_utc` approval delay and the confirm timestamps wherever a human acted, every SHADOW outcome is attributed system / user-executed-sim / opportunity with its journaled reason, and the 30 s constant survives only for records with no human action, with every existing paper digest unchanged.**

## Performance

- **Duration:** about 12 min (14:40Z to 14:52Z)
- **Tasks:** 2 (Task 1 tracer, Task 2 TDD)
- **Files:** 5 (1 created, 4 modified)
- **Plan base:** `67c76b6` (HEAD before Task 1)

## Accomplishments

- Tracer: `PaperRecord` gained `mode`, `approval_requested_at_utc`, `confirm_requested_at_utc`, `confirmed_at_utc`, `test_only`; `canonical_record_dict` writes them only when set, so `paper_records_digest` of any record without them is byte-identical to before. `assemble_paper_record(mode="SHADOW", confirm=...)` records the real approval timestamps for a human APPROVE and requires the confirm timestamps; the SIMULATE leg keeps signal + 30 s and its disagreement check.
- `attribute_shadow_outcome(ShadowOutcome) -> (AttributionKind, reason)` in `attribution.py` (stdlib only): the table of Test 1 of the plan, plus fail-closed errors for undecided or inconsistent outcomes.
- `assemble_paper_record(shadow_outcome=...)` applies it: filled pair for APPROVE + CONFIRM, `[system, opportunity]` for every other executed-never outcome (the opportunity row keeps the measured approval and card-issue timestamps when the journal has them), `[system]` alone for an untouched plan still open; order and fill legs for a non-executed outcome are refused.
- `_load_paper_record` reads the optional keys (absent or null means None / False), still refuses unknown keys, bad modes, non-bool `test_only` and non-UTC timestamps.

## RED Evidence

- **Task 1** (`0b2df57`): `tests/test_paper_approval_delay_measured.py` failed at collection with `ImportError: cannot import name 'canonical_record_dict' from 'src.paper.journal'`.
- **Task 2** (`fd71436`): the added tests failed at collection with `ImportError: cannot import name 'ShadowOutcome' from 'src.paper.attribution'`, shown by restoring the Task 1 versions of the three source files for one run (per-file `git checkout`, then the working copies were put back). The Task 2 implementation had been drafted before its tests were committed, so this RED was reproduced rather than observed first.

## Task Commits

1. **Task 1: measured delay and SHADOW fields** - `0b2df57` (test, RED), `497ab46` (feat, GREEN)
2. **Task 2: SHADOW attribution and loader** - `fd71436` (test, RED), `8c6de16` (feat, GREEN)

**Plan metadata:** committed separately (docs: complete plan).

## Verification

- `pytest tests/test_paper_approval_delay_measured.py tests/test_paper_attribution.py tests/test_paper_parity.py tests/test_paper_reviewfix_pins.py -q`: green (Task 1 command). Task 2 command set `tests/test_paper_approval_delay_measured.py tests/test_paper_attribution.py tests/test_analytics_files.py tests/test_analytics_cli.py`: green; also `test_domain_no_float`, `test_analytics_latency`, `test_analytics_no_trade`, `test_analytics_lifecycle`.
- `pytest -m "not docker" -k "paper or analytics or attribution or journal or killgate or evidence"` deselecting the known `tests/test_cost_parity.py` failure (deferred-items.md, plan 16-15): 1206 passed, 41 skipped. The whole suite was not run in one process.
- `git diff 67c76b6 -- tests`: only additions; no expected digest literal edited.
- `ruff check` and `ruff format --check` (src and tests): clean. `mypy src` (165 files): clean.
- No network, `.env` not read.

## Decisions Made

See `key-decisions` above. Q-K answer: optional `PaperRecord` fields omitted when absent.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The assembler needed the `confirm` and `shadow_outcome` inputs and a `canonical_record_dict` helper**
- **Found during:** Task 1 design
- **Issue:** the plan names the record fields and the assembler change but not how the confirm timestamps and the journaled outcome reach `assemble_paper_record`; "omit None fields from the canonical dict" needs one shared function for the digest and the tests.
- **Fix:** keyword-only `mode`, `confirm`, `test_only`, `shadow_outcome` on `assemble_paper_record` (all defaulted, so existing callers are unchanged) and the public `canonical_record_dict`, which `paper_records_digest` now calls.
- **Files modified:** src/paper/journal.py
- **Commit:** 497ab46, 8c6de16

**2. [Rule 2 - Missing critical] Fail-closed handling of a missing or unknown approval `action`**
- **Issue:** deciding "no human action" by guessing would put the 30 s constant where a measured delay belongs (T-16-81).
- **Fix:** `_is_human_action` raises for a missing or unknown `action`; only `SIMULATE` means no human.
- **Commit:** 497ab46

**Interpretation of Test 2** ("a SHADOW record whose real acted_at_utc is replaced by signal + 30 s is rejected"): the old assembler rejected every real timestamp that differed from signal + 30 s. The test asserts the new behaviour that fails on the old code: the real timestamp is recorded and differs from signal + 30 s; a human action without its `acted_at_utc` (the only way a caller could make the constant stand in for it) is refused.

### TDD ordering

Task 2's implementation was written before its tests were committed; the RED state was reproduced by restoring the committed sources for one run (see RED Evidence). Task 1 followed RED then GREEN.

**Total deviations:** 2 auto-fixed (1 Rule 3, 1 Rule 2) plus the Test 2 interpretation. **Impact:** within the plan's intent; the plan's interfaces are provided.

## Known Stubs

None.

## Threat Flags

None beyond the plan's register. T-16-81 (real delay never overwritten, the constant only for no human action) and T-16-82 (new fields omitted when absent, pinned digests asserted) are covered by tests. No package installs (T-16-SC).

## Notes for later plans

- Plan 16-31 builds `ShadowOutcome` and the approval / confirm dicts from the journal (`SHADOW_CONFIRM_*` events and their `reason`, the approval row's `action`, `requested_at_utc`, `acted_at_utc`); the PG approval store does not persist `actor_id` (plan 16-11 note), which this plan does not need.
- Plan 16-36's exporter should write `canonical_record_dict(record)` into the evidence `paper` list so the loader round-trips it (tested).
- `tests/test_cost_parity.py` still fails for the reason in `deferred-items.md`; not touched here.

## Self-Check: PASSED

- FOUND: tests/test_paper_approval_delay_measured.py, src/paper/journal.py, src/paper/attribution.py, src/adapters/analytics_files.py
- FOUND commits: 0b2df57, 497ab46, fd71436, 8c6de16
