---
phase: 20-reconcile-safe-mode-hardening
plan: 20
subsystem: reconcile
tags: [reconcile, safe-mode, symbol-ownership, EXEC-02]
requires: [20-04, 20-05, 20-12, 20-16]
provides:
  - "compare(local_active_plans=...) emits AMBIGUOUS_POSITION_OWNER for more than one active plan per symbol"
  - "LocalIntent.active_plans and its entry in compare_kwargs()"
  - "SAFE_MODE reason SYMBOL_OWNERSHIP_CONFLICT (classify), GLOSSARY 9.4 row"
affects: [20-24]
key-files:
  created: [tests/test_symbol_ownership.py]
  modified:
    - src/reconcile/compare.py
    - src/reconcile/local_intent.py
    - src/reconcile/classify.py
    - docs/GLOSSARY.md
    - tests/test_reconcile_classify.py
key-decisions:
  - "Owner decision O-D: accept-narrow (reconcile-time detection only; a new owner policy, not D-13)"
status: complete
commits: 3
plan_head_before: 9632d69ed6f009a119110ba8aa03ffbcd38e5add
plan_head_after: 4367ecb80dfae29d5a771e0d13709e77a6799997
actuals:
  tokens: 40000
  tasks: 3
  commits: 3
---

# Phase 20 Plan 20: Symbol ownership invariant Summary

More than one active plan for one symbol, or exposure whose owning plan cannot be determined, is detected at reconcile time and enters SAFE_MODE with its own reason `SYMBOL_OWNERSHIP_CONFLICT`; no owner is guessed and nothing is closed.

## Owner decision O-D

Answer given by the owner in the orchestrating session on 2026-10-21, recorded verbatim:

> O-D: accept-narrow

Meaning (plan option `accept-narrow`): accept the narrow symbol-ownership scope as proposed, with no extra condition. This is a NEW owner policy decision (O-D, reconcile-time detection only). It is not a D-13 decision and is never attributed to D-13. Task 1 was a blocking-human checkpoint already answered by the owner before this run, so it was not re-asked.

## What was built

- `src/reconcile/compare.py`: new frozen carrier `LocalActivePlan(plan_hash, symbol)` and new optional keyword `local_active_plans: Sequence[Any] = ()` (default empty, existing callers unchanged; `None` raises `TypeError` like the other sources). A new Pass 3b emits one `AMBIGUOUS_POSITION_OWNER` per symbol with more than one distinct `plan_hash`, merged with the exposure-based emission of Pass 3 (a symbol never yields two). An active plan item with no usable plan hash or symbol also yields one (symbol `UNKNOWN` when the symbol is unusable): fail closed, never dropped.
- `src/reconcile/local_intent.py`: `LocalIntent.active_plans` (default `()`), filled with every tracked plan whose state is not FLAT / ENTRY_ENDED_NO_FILL plus every plan that is NOT tracked but is named by an unresolved ENTRY intent (SENT / UNKNOWN). The tracked state wins: an unresolved ENTRY row of a FLAT plan does not reactivate it. `compare_kwargs()` passes it as `local_active_plans`; the loop was not edited (it already passes `**local.compare_kwargs()`).
- `src/reconcile/classify.py`: `SAFE_MODE_SYMBOL_OWNERSHIP_CONFLICT`; `AMBIGUOUS_POSITION_OWNER` now maps to safe_mode_reason `SYMBOL_OWNERSHIP_CONFLICT`, alert `DIVERGENCE`, action `ALERT_ONLY` (never DELEGATE, never a close). Because the kind is the same, the existing exposure-based ambiguity (missing plan_hash / side / bound, two owners) uses the new reason too, as the plan states.
- `docs/GLOSSARY.md` 9.4: one row `SYMBOL_OWNERSHIP_CONFLICT` naming `src/reconcile/classify.py` and `src/reconcile/loop.py` and the O-D (not D-13) policy (bytes-aware, CRLF kept).
- `tests/test_symbol_ownership.py` (new, 30 tests): tracer through one tick, compare unit cases, `derive_local_intent` active-plan rules, classify, ambiguous exposure, unreadable local data, restore pending, the D077 deadline on top using the real coordinator and emergency closer, GLOSSARY row.
- `tests/test_reconcile_classify.py` (not in `files_modified`, see Deviations): the two assertions this change makes stale were updated.

## Ownership source evaluation

Question (T-F): do `protections()` plus `list_unresolved_intents()` identify active plans reliably?

- What they give: the coordinator's `protections()` views carry `plan_hash`, `symbol`, `state` for every tracked plan; since 20-19 the views are rebuilt from the durable intents and the journal after a restart. `list_unresolved_intents()` adds SENT / UNKNOWN rows, i.e. legs that may exist on the exchange although no coordinator state names the plan (a placement whose answer was lost). Together they cover: a tracked plan in any non-final state, and an untracked plan with an ENTRY that may be resting.
- What they do not give, stated as gaps:
  1. Before the restart rebuild completes the loop skips the tick (`RECONCILE_SKIPPED_RESTORE_PENDING`; tested), so a conflict is simply not evaluated in that window; no ownership decision is made on a partial view.
  2. A plan known only to the journal and not rebuilt into `protections()`, and with no unresolved ENTRY row, is not seen. Its exposure (if any) still appears on Binance and surfaces as `UNSYNCED_POSITION` or an unowned order, but the second-plan conflict is not detected from local data alone.
  3. Only ENTRY intent rows count for untracked plans. A plan known only by an unresolved stop or take-profit row is not counted as active.
  4. An unresolved intent row of a tracked plan in FLAT / ENTRY_ENDED_NO_FILL does not reactivate it (tracked state wins). If that state were wrong, the conflict would be missed; the coordinator is the authority for plan state.
  5. No `positions` table and no `Order` rows exist (D-13 deferral to Phase 24) and neither is assumed. Phase 24 adds Order rows, which would give exact per-plan attribution by client order id.
  6. The check is a bound, not exact position reconciliation: it cannot see an over-fill below the intended quantity (A6, D-01a).
- Failed reads: a raising `protections()` or `list_unresolved_intents()` enters SAFE_MODE `DB_FAILURE` and makes no ownership decision in that tick (tested for both); the compare is not invoked.
- Verdict: reliable for the tracked-plan case, which is the case Phase 19 produces (the coordinator registers every placed entry); weaker for a plan lost from the journal. Binance stays authoritative; local rows are evidence of ownership only.

## Task commits

| Task | Name | Commit |
|------|------|--------|
| 1 | Owner decision O-D (checkpoint, answered: accept-narrow) | none (recorded in this file) |
| 2 (RED) | Failing tests for the symbol ownership invariant | 03e76c41 |
| 2 (GREEN) | compare / local_intent / classify implementation | 37fa792d |
| 3 | GLOSSARY 9.4 row SYMBOL_OWNERSHIP_CONFLICT | 4367ecb8 |

## Verification

- `uv run pytest -m "not docker" tests/test_symbol_ownership.py tests/test_reconcile_compare_v2.py tests/test_reconcile_classify.py tests/test_reconcile_loop.py tests/test_phase19_gate.py`: 300 passed.
- Also run and green: `tests/test_reconcile.py`, `tests/test_reconcile_stream_divergences.py`, `tests/test_safe_mode_exit_operator.py`, `tests/test_drills.py`, `tests/test_decision_alignment_bookkeeping.py`, `tests/test_domain_enums.py`, `tests/test_agents_md.py`, `tests/test_protection_supervision.py`.
- `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS. `uv run mypy src`: no issues (233 files). `uv run ruff check` and `uv run ruff format --check`: clean.
- `git diff --exit-code -- src/execution/pre_placement.py src/execution/manager.py pyproject.toml uv.lock`: exit 0. `grep -c SYMBOL_OWNERSHIP_CONFLICT docs/GLOSSARY.md`: 1.
- Evidence label: executed tests with fakes; the policy is the owner's O-D decision, not D-13; no [DEMO] claim. The full suite was not run (orchestrator's job).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree was based on master, not on the Phase 20 branch**
- **Found during:** startup (the plan file was absent).
- **Issue:** the isolated worktree branch started at `master` (9d8a9b0e) while Phase 20 work lives on `develop`.
- **Fix:** `git merge --ff-only develop` (a fast-forward to 9632d69e, no commits of mine existed). Also `uv sync --frozen --extra dev` to create the worktree venv (no dependency change; `pyproject.toml` and `uv.lock` untouched).

**2. [Rule 1 - Bug] Two existing assertions made stale by the plan's own change**
- **Issue:** `tests/test_reconcile_classify.py` pinned "every reason equals the kind name except STREAM_TASK_DIED" and "compare_kwargs has exactly three keys". The plan changes both facts.
- **Fix:** updated those two assertions (a small `own_reason` map; the key set now includes `local_active_plans`). The file is outside `files_modified` but no other way keeps the suite green.
- **Commit:** 37fa792d

**3. Task 2 commit has a transiently red GLOSSARY test**
- The RED commit already contained the GLOSSARY 9.4 test; the row belongs to Task 3 per the plan, so `test_glossary_94_has_exactly_one_symbol_ownership_conflict_row` fails at 37fa792d and passes at 4367ecb8.

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path, file access or schema; `src/execution/pre_placement.py` and the manager ingress are untouched (no plan-ingress rejection).

## Self-Check: PASSED

- tests/test_symbol_ownership.py, src/reconcile/compare.py, src/reconcile/local_intent.py, src/reconcile/classify.py, docs/GLOSSARY.md present; commits 03e76c41, 37fa792d, 4367ecb8 are ancestors of HEAD.
