---
phase: quick-261020-q2d
subsystem: execution-binding
tags: [phase-19, review-fix, WR-01, D078, approval, consume, persistence]
requires:
  - "quick task 261020-q1o (approvals.approved_quantity, D078); owner: \"làm cả 2\""
status: complete
committed: false
plan_head_before: 996f91f
commits:
  - "4d63ca0 test(19): WR-01 follow-up failing tests for the consume-time stored quantity check"
  - "ce0a261 fix(19): WR-01 follow-up the consume transaction re-checks the stored approved quantity"
  - "c96f94d docs(19): D078 item (6) records the consume-time stored-quantity check (WR-01 follow-up)"
  - "d1ad5f9 test(19): WR-01 follow-up failing tests for SAFE_MODE on an inconsistent stored quantity"
  - "d32deb3 fix(19): WR-01 follow-up SAFE_MODE on an inconsistent stored approved quantity"
  - "6ac738b docs(19): D078 item (6) states the SAFE_MODE policy of the stored-quantity refusal"
decisions_id: "none new; D078 amended in place (item (6))"
---

# Quick 261020-q2d: consume-time check of the stored approved quantity (WR-01 follow-up 2 of 2)

**The consume transaction now re-reads `approvals.approved_quantity` itself. If the stored value
is NULL, differs from the quantity the manager bound, or is below the quantity about to be placed,
the transaction rolls back and the manager answers `APPROVED_QUANTITY_NOT_CONFIRMED` with no
exchange call.**

## What changed

- `src/persistence/errors.py`: `ApprovedQuantityRefused(IntentStateConflict)`.
- `src/persistence/execution_state.py`: `consume_and_record_entry_intent(..., approved_quantity)`
  (required keyword). After the INSERT, `_require_stored_quantity` reads the approval row
  `FOR UPDATE`. For an APPROVED, unconsumed row it requires stored NOT NULL, stored == bound and
  stored >= intended. The consuming UPDATE also carries those conditions. A missing,
  not-APPROVED or consumed row keeps the plain `IntentStateConflict`. A replay returns False
  before any quantity is read. A non-Decimal or non-finite argument raises `TypeError`.
- `src/execution/intent_store.py`: the Protocol takes the new keyword.
- `src/execution/manager.py`: passes `bound.approved_quantity`; maps `ApprovedQuantityRefused`
  to the new plain code `APPROVED_QUANTITY_NOT_CONFIRMED` (exported).
- `tests/support/intent_store_fakes.py`: all five fakes take the keyword. Wrappers pass it on.
  The in-memory fake ignores it because it has no approvals table.
- Docs: D078 is amended in place (status note; item (5) no longer says "not built"; new item
  (6)). Also a DOC_STATUS line, a GLOSSARY 9.3 row, a DATA_MODEL 2.5 sentence, a 19-REVIEW-FIX
  follow-up section (not given a batch number) and the 19-OWNER-GAPS WR-01 row.

## Test-first evidence

- At base `996f91f`, a scratch PG test (deleted) set the DB row to NULL and then to 2.000 while
  the caller's Approval carried 2.415. Both runs gave `OK` and one `place_entry`.
- RED commit `4d63ca0`: the new files fail at collection (`ImportError`
  `APPROVED_QUANTITY_NOT_CONFIRMED`).

## Verification (real results, TRADING_CI_STRICT=1, process-env TEST_DATABASE_URL, -n 4)

| Run | Result |
|---|---|
| New PG file + manager unit file + all direct/indirect consume callers (10 files incl. exactly_once, write_ahead, intent_recovery(+pg), realized_risk, approvals_pg, approval_replay_pg, callback_redelivery_pg) | 303 passed, 0 skipped |
| Other files using intent-store fakes / persistence errors / execute_approved_plan, plus binding, migration_pg, phase19 gate (25 files) | 915 passed, 0 skipped |
| Doc/gate group (18 files incl. phase18/19 gates, decision_alignment*, agents_md) after the doc edits | 540 passed |
| ruff check / format --check / mypy src / uv lock --check / verify_decision_alignment all | pass / 668 formatted / 214 files OK / 62 packages unchanged / ALL_PASS |

The runs overlap, so the counts should not be added. Not run: the full suite, `-m docker`, any
Demo, `--execute` or network call.

## Notes for the merger

- No new DECISIONS id. D079/D080 are reserved for the provisional D-10/Q5 drafts, so D081 would
  break contiguity. If the other agent's merge adds a row, D078 keeps its id.
- Conflict risk: the 19-OWNER-GAPS WR-01 row (one clause removed, one sentence appended) and the
  end of 19-REVIEW-FIX.md.
- SAFE_MODE was an open choice; the owner decided it on 2026-10-20 ("ok tôi đồng ý"). See below.

## SAFE_MODE policy (owner decision 2026-10-20)

- The store raises one of two subclasses of `ApprovedQuantityRefused`:
  - `ApprovedQuantityMissing` for a NULL (a legacy row from before revision 0006).
  - `ApprovedQuantityInconsistent` when the stored value differs from the bound quantity or is
    below the quantity to place.
- For the inconsistent cases the manager enters SAFE_MODE `APPROVED_QUANTITY_INCONSISTENT`. The
  reason is defined like `_DB_FAILURE`. Entry goes through the existing non-raising
  `_enter_safe_mode` helper, which moved above the consume with its body unchanged.
- A NULL gives NO_TRADE only. The NO_TRADE code is `APPROVED_QUANTITY_NOT_CONFIRMED` in all
  three cases. A replay enters no SAFE_MODE.
- RED commit `d1ad5f9`: the three new unit tests failed and the PG file failed at import (the
  subclasses did not exist).
- New tests:
  - unit: NULL gives no SAFE_MODE; inconsistent enters SAFE_MODE; a SAFE_MODE controller that
    raises still gives NO_TRADE.
  - PG: NULL gives no SAFE_MODE, 2.000 (below) and 2.416 (differs) enter SAFE_MODE with that
    reason and no `place_entry`; replay with NULL or 2.000 stored enters no SAFE_MODE.
- Docs: D078 item (6) and its status note, the GLOSSARY 9.3 row (amended) and a 9.4 row (new),
  the DOC_STATUS line, the 19-REVIEW-FIX section, the 19-OWNER-GAPS WR-01 row. The gate's
  SAFE_MODE reason inventory lists the new reason.
- Verification after the policy change:
  - new PG file, manager tests and all consume callers (10 files): 307 passed, 0 failed.
  - 24 related files: 884 passed.
  - doc/gate group (18 files): 540 passed.
  - ruff check clean, 668 files formatted, mypy src clean (214 files), `uv lock --check` shows 62
    packages unchanged, alignment ALL_PASS.
