---
phase: 23-telegram-approval-hardening-money
plan: 06
subsystem: approval
status: complete
tags: [confirm, d041, two-step, shadow-profile, demo-live-profiles, p16r-02, fail-closed]
requirements-addressed: [APRV-02]
requires: [23-01]
provides:
  - "src/approval/confirm_core.py: ConfirmProfile, SHADOW/DEMO/LIVE_CONFIRM_PROFILE, core ConfirmBook(profile, card_renderer), ConfirmOutcome, ConfirmRecord, ConfirmState, ConfirmEntry, ConfirmResult, stores/ports, REASON_* codes, assert_no_stranded_approvals(profile=...)"
  - "src/paper/shadow_confirm.py: SHADOW ConfirmBook subclass over the core, every former public name re-exported"
  - "P16R-02 resolved: _deferred_confirmed is a list; one on_confirmed call per adopted CONFIRM, in order, outside the locks"
affects: [23-08, 23-09, 23-10, 23-13, 24]
tech-stack:
  added: []
  patterns:
    - "profile object carries every mode-specific string (event names, entity type, id prefixes, payload mode label, log namespace)"
    - "card text injected as a CardRenderer: the core owns no message text"
    - "structural DeliveryFailure Protocol instead of importing the Telegram failure type"
key-files:
  created:
    - src/approval/confirm_core.py
    - tests/test_confirm_core.py
  modified:
    - src/paper/shadow_confirm.py
    - src/paper/shadow.py
    - tests/test_approval_replay.py
key-decisions:
  - "DEMO/LIVE event names are mode-prefixed like SHADOW's (DEMO_CONFIRM_ISSUED ... LIVE_CONFIRM_NOTICE_FAILED), entity types DemoConfirm / LiveConfirm, correlation demo-confirm: / live-confirm:, journal id prefixes demo-cnf / live-cnf, log namespaces execution.demo_confirm / execution.live_confirm (D-09, Claude's discretion). src/paper/attribution.py still reads only the SHADOW names; DEMO/LIVE attribution is a later consumer (for plan 23-13's register)."
  - "The deferred hook items are drained even when the body of a section raised after finishing some CONFIRMs; the body error wins, hook errors are then only logged. Without this an adoption made before a later entry of the same sweep raised would be lost for good (state is already CONFIRMED, so no later sweep adopts it again)."
  - "The SHADOW subclass overrides the entry factory (_new_entry) so that the construction site of card_text stays in src/paper/shadow_confirm.py, where tests/test_paper_shadow_runtime.py (composer-only guard) reads it; the core's default factory uses the injected CardRenderer."
metrics:
  completed: 2026-10-25
commits: 5
plan_head_before: 766bc2332153f6bdde7d8ab4d0d22027daab61a7
plan_head_after: 0a418ca771e2d878f4ea74aa70c00fea1ebad338
actuals:
  tokens: 24000
  tasks: 3
  commits: 5
---

# Phase 23 Plan 06: Mode-independent confirm core Summary

The SHADOW two-step CONFIRM state machine (D041) now lives in `src/approval/confirm_core.py`, parametrized by a `ConfirmProfile`; SHADOW is a thin profile over it with unchanged journal rows and texts, DEMO and LIVE have profiles and pass the D-10 refusal matrix at core level, and P16R-02 is resolved as a list.

## What was done

**Task 1 (tracer) - move the core.** Code was moved, not rewritten: the state machine, the stores/ports protocols, `StrandedApprovals`, the REASON_* codes, `ConfirmOutcome` and `ConfirmRecord` (from `shadow.py`) and `assert_no_stranded_approvals` went to the core; every SHADOW literal (six event names, entity type `ShadowConfirm`, correlation `shadow-confirm:`, id prefix `shadow-cnf`, payload mode `SHADOW`, log events `paper.shadow_confirm.*`) is read from `SHADOW_CONFIRM_PROFILE`. The card is a `CardRenderer`; `require_shadow` stays in `src/paper`. `src/paper/shadow_confirm.py` keeps the delivery (`deliver_confirm_card`, `CardDelivery`), the callbacks, `render_confirm_card`, the `EVENT_SHADOW_*` aliases, `TERMINAL_CONFIRM_EVENTS`, `_correlation`, and an `assert_no_stranded_approvals` wrapper with the old signature; `__all__` only gained names. `shadow.py` changed by 1 added and 21 removed lines (the two definitions and one import). The core's AST import scan finds nothing from `src.execution`, `src.paper`, `src.adapters` or `telegram`.

**Task 2 - P16R-02 (D-16).** `_deferred_confirmed` is `list[tuple[Approval, TradePlan, datetime]]`; `_in_section` clears it at entry, `_finish_confirm` appends, and after both locks are released `_run_confirmed_hooks` calls the hook for each item in order, attempts every item even after one raised, and re-raises the first hook error after all ran. Tests: two adoptions in one sweep reach the hook once each in order with the book lock free (probed from another thread); a raising hook does not skip the later one; the first error is the one re-raised; a single press still calls the hook once; an adoption made before a later entry of the same sweep raised still reaches the hook.

**Task 3 - D-10 matrix.** Core-level tests with the DEMO profile (LIVE for the last cases): valid CONFIRM (one call, `approving_user_id` of the CONFIRM actor journaled), double tap, replayed correlation (no new row), TTL at the inclusive boundary and the last second inside, other user (rejected, not terminal, owner can still confirm), no user id, other chat, plan expiry (inclusive, re-check not reached), re-check refusal `MARK_PRICE_CROSSED_STOP` and re-check error, stale plan hash, CANCEL (and CONFIRM after it), cancel by another user, restart expiry `RUNTIME_RESTART`, stranded sweep, missing user id at issue, LIVE names, hook is the only seam. No core change was needed: the moved machine had no SHADOW-only assumption.

## Commits

| Hash | Message |
|------|---------|
| dbadbed0 | test(23-06): RED - confirm core import ban, profile literals and DEMO/LIVE journal names |
| 623defde | feat(23-06): extract the mode-independent confirm core; SHADOW is its profile |
| 3c4569b0 | test(23-06): RED - two adoptions in one sweep must both reach on_confirmed (P16R-02) |
| 85f0c666 | fix(23-06): every CONFIRM adopted in one sweep reaches on_confirmed once, in order (P16R-02) |
| 0a418ca7 | test(23-06): DEMO/LIVE profile refusal matrix at core level (D-10) |

## Deviations from Plan

**1. [Rule 1 - Bug] `test_no_synonym_reason_strings_in_src_approval` scans every `src/approval/*.py`**
- **Found during:** Task 1 (running the wider test set).
- **Issue:** the guard rejects any upper-case string literal in `src/approval/` that is not a `RejectionReason` value; the moved confirm machine has the SHADOW confirm reason codes and journal names (`CONFIRM_TTL_ELAPSED`, `RUNTIME_RESTART`, ...), which are not synonyms. Same situation as plan 23-01 with `reason_codes.py`.
- **Fix:** the scan also skips `confirm_core.py`, with a comment (5 lines in `tests/test_approval_replay.py`, the same precedent as 23-01).
- **Impact on the plan's acceptance wording:** the `git log -- tests/` check lists `tests/test_approval_replay.py` besides `tests/test_confirm_core.py`. It is not a SHADOW test file and no SHADOW test file was touched (`git diff --name-only 766bc233..HEAD -- tests/` = those two files). Plan 23-07 does not edit it (read-only there).
- **Commit:** 623defde

**2. [Rule 2 - Correctness] hooks of already-finished CONFIRMs run when the section body raises**
- **Found during:** Task 2 design. With the list, a sweep that adopts A and then raises on B would drop A's hook for good (A's state is CONFIRMED, so no later sweep adopts it again). `_in_section` now drains the list in that case, the body error wins and hook errors are logged only. Test: `test_an_adoption_is_not_lost_when_a_later_entry_of_the_same_sweep_raises`.
- **Commit:** 85f0c666

**3. [Structure] SHADOW overrides the entry factory.** `tests/test_paper_shadow_runtime.py::test_the_confirm_entry_card_text_is_assigned_only_from_the_card_composer` (unedited) requires a `card_text=render_confirm_card(...)` keyword call inside `src/paper/shadow_confirm.py`. The core builds entries through an overridable `_new_entry`; the SHADOW subclass overrides it with that call and also passes an equivalent `CardRenderer` for the core contract.

**4. [Environment] Line endings.** In this worktree the checkout is CRLF (core.autocrlf=true, index LF) for `shadow.py`, `shadow_confirm.py` and `test_approval_replay.py`, contrary to the plan's "shadow_confirm.py is LF". `shadow.py` and `test_approval_replay.py` were edited bytes-aware (CRLF kept; numstat 1/21 and 4/1); `shadow_confirm.py` was rewritten as a whole and is CRLF like its neighbours; `confirm_core.py` and `test_confirm_core.py` are new LF files. Git stores LF in all cases.

## Authentication gates

None.

## Verification (executed)

- `uv run pytest -m "not docker"` on tests/test_confirm_core.py, test_paper_shadow_{confirm,buttons,messages,telegram_failures,lock_order,isolation,reservations,runtime,fill,ledger,evidence_export}.py, test_paper_approval_delay_measured.py, test_paper_test_signal_rehearsal.py, test_rehearsal_compose.py, test_approval_replay.py, test_domain_no_float.py: 495 passed (`-n 4`).
- `TRADING_CI_STRICT=1` (TEST_DATABASE_URL set in the process environment) on test_paper_shadow_pg.py, test_paper_shadow_reservations_pg.py, test_paper_shadow_runtime_pg.py: 10 passed, none skipped.
- Scoped `ruff check`, `ruff format --check` and `mypy` on confirm_core.py, shadow_confirm.py, shadow.py, tests/test_confirm_core.py: clean. `scripts/verify_decision_alignment.py all`: ALL_PASS.
- `git diff --exit-code -- pyproject.toml uv.lock src/execution`: exit 0. No SHADOW test file edited.
- Evidence label: executed tests with fakes and local PostgreSQL [DESIGN]. DEMO and LIVE are not composed into any process (Phase 24); the profiles are proven at core level only.

## Notes for later plans

- Plan 23-13 register: DEMO/LIVE journal event names, entity types and prefixes above; `src/paper/attribution.py` does not read them yet; the `confirm_core.py` skip in the synonym guard; `REASON_*` codes are plain strings defined in the core (`USER_ID_UNAVAILABLE` has one definition in `reason_codes.py`).
- Phase 24 connects `execute_approved_plan` to the core's single `on_confirmed` seam; the hook now receives every adopted CONFIRM, each with its own approval, plan and confirm instant.
- `ConfirmEntry` fields are unchanged; the core adds no payload key (SHADOW payloads stay byte-identical).

## Known Stubs

None.

## Threat Flags

None. The core adds no network endpoint, auth path or file access; it imports nothing order-capable (AST-tested).

## Self-Check: PASSED

- FOUND: src/approval/confirm_core.py, tests/test_confirm_core.py, src/paper/shadow_confirm.py, src/paper/shadow.py
- FOUND commits: dbadbed0, 623defde, 3c4569b0, 85f0c666, 0a418ca7 (all ancestors of HEAD)
