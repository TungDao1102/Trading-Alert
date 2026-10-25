---
phase: 23-telegram-approval-hardening-money
plan: 05
subsystem: execution
tags: [confirm, pre-placement, recheck, prior-outcome, fail-closed]
requires:
  - src/execution/pre_placement.py (Phase 19 checks, unchanged)
  - src/execution/intent_store.py (IntentRecord)
provides:
  - "src/execution/confirm_recheck.py: ConfirmInputs, PrefetchedConfirmInputs, make_confirm_recheck, prefetched_provider, CONFIRM_INPUTS_UNAVAILABLE, CONFIRM_INPUTS_MISMATCH"
  - "src/execution/prior_outcome.py: PriorOutcome, describe_prior_outcome, prior_outcome_for_expired_redelivery, PRIOR_OUTCOME_LABEL"
affects: [23-11 reply layer, Phase 24 composition]
key-files:
  created:
    - src/execution/confirm_recheck.py
    - src/execution/prior_outcome.py
    - tests/test_confirm_recheck.py
    - tests/test_prior_outcome_reply.py
  modified: []
decisions:
  - "The prefetched snapshot's clock is rebound to the press instant: now_utc is replaced, and the mark/last checked-at instants are moved forward to now_utc (max), never backwards, so price age and remaining validity are judged at CONFIRM."
  - "Identity of a snapshot is checked against the Signal (symbol, direction) and the TradePlan (plan_hash), because TradePlan carries no symbol or side."
  - "A snapshot is consumed by take() even when it is then refused as a mismatch (single use, fail closed)."
metrics:
  tasks: 2
  commits: 4
status: complete
commits: 4
plan_head_before: 6c759ef6bb6cce99b9343538d293c7881ab0d280
plan_head_after: 0a98c8e8369c4d359c1cc8b51b1acf23724e40a5
---

# Phase 23 Plan 05: Confirm-time recheck and prior-outcome description Summary

Two pure helpers: a single synchronous CONFIRM recheck that re-runs the Phase 19 pre-placement checks (plus the position-mode check) from a pre-fetched, single-use snapshot, and a mapping of a stored entry intent to "already executed" / "needs reconciliation" / "rejected".

## What was built

- `make_confirm_recheck(provider)` returns `(signal, plan, now_utc) -> str | None`. It calls `evaluate_pre_placement` and then `check_position_mode` from `pre_placement.py` (not changed). No snapshot gives `CONFIRM_INPUTS_UNAVAILABLE`; a different plan hash, symbol or side gives `CONFIRM_INPUTS_MISMATCH`; hedge mode gives `HEDGE_MODE_UNSUPPORTED`; an unknown mode raises `ValueError`.
- `PrefetchedConfirmInputs` is a lock-guarded dict, `put` / `take` (single use). `prefetched_provider` rebinds the clock to the press instant.
- `describe_prior_outcome` maps ACKED to ALREADY_EXECUTED; UNKNOWN, SENT, INTENDED to NEEDS_RECONCILIATION; REJECTED to REJECTED; None to None. A parametrized test covers every `ExecutionIntentStatus` member.
- `prior_outcome_for_expired_redelivery` reads the intent only for APPROVAL_EXPIRED on an APPROVED approval (G4-032); other reasons, missing, SKIPPED, EXPIRED or PENDING never call the reader.

## Tracer

Task 1 verified end to end: a snapshot is put, the recheck refuses a mark that crossed the stop (MARK_PRICE_CROSSED_STOP), and a second CONFIRM finds no snapshot (CONFIRM_INPUTS_UNAVAILABLE).

## Verification

- `uv run pytest -m "not docker" tests/test_prior_outcome_reply.py tests/test_confirm_recheck.py tests/test_pre_placement.py tests/test_phase19_gate.py`: all passed (211 tests).
- mypy on both modules: no issues. ruff check and format check on the four files: clean.
- `git diff` of `pyproject.toml`, `uv.lock`, `src/execution/pre_placement.py`, `src/execution/manager.py` against the base: empty.
- Evidence label: executed unit tests [DESIGN]; the composition that pre-fetches and binds the reader is Phase 24.

## Deviations from Plan

None in behavior. One refinement within the plan's intent (Rule 2, fail closed): beyond rebinding `now_utc`, the prices' checked-at instants are moved forward to the press instant (never backwards) so a snapshot that was fresh when fetched is judged stale if the press comes later. Covered by `test_price_age_is_measured_at_the_press_instant` and `test_press_instant_before_fetch_does_not_make_readings_fresher`.

Environment notes: the worktree base did not contain the wave plan files (they live untracked in the main tree), so the plan was read from the main tree read-only; this SUMMARY is written in the worktree's phase directory. No `.codegraph/` exists in the worktree. Per orchestrator instruction STATE.md, ROADMAP.md and requirements were not touched.

## Known Stubs

None.

## Threat Flags

None. T-23-14 and T-23-15 are mitigated as planned; no new network, auth or file surface.

## Self-Check: PASSED

Files exist: src/execution/confirm_recheck.py, src/execution/prior_outcome.py, tests/test_confirm_recheck.py, tests/test_prior_outcome_reply.py. Commits exist on branch worktree-agent-aec036710a087a51f.
