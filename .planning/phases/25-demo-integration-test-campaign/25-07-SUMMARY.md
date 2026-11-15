---
phase: 25-demo-integration-test-campaign
plan: 07
subsystem: demo-soak-evaluator
tags: [criterion-3, D-09, D-10-deviation, EXEC-02, EXEC-03, OPS-01, tdd, journal]
requires: []
provides:
  - "scripts/evaluate_demo_soak.py: verify-registration, evaluate and export subcommands; registration (demo-soak-registration/1) and annotation formats; create-only sorted-LF report (demo-soak-evaluation/1) with an input manifest"
  - "tests/test_evaluate_demo_soak.py (81 tests) and tests/test_evaluate_demo_soak_pg.py (4 tests, disposable PostgreSQL): fixture journals built from JournalEvent objects with producer-imported event names"
affects: [25-19, 25-22, 25-24]
tech-stack:
  added: []
  patterns:
    - "every criterion is a pure function over the sorted event list returning a count, the offending journal ids and a note; overall PASS only when no criterion FAILS"
    - "event names imported from the producing module; payload keys named as constants; an AST test forbids re-typed producer names"
    - "injected clock in main; the only wall-clock default sits at the module edge"
key-files:
  created:
    - scripts/evaluate_demo_soak.py
    - tests/test_evaluate_demo_soak.py
    - tests/test_evaluate_demo_soak_pg.py
  modified: []
key-decisions:
  - "Deviation from D-10 stated in the script docstring: the Phase 16 paper tools are not reused (research Pitfall 2); only the manifest and SHA-256 pattern is. The owner can confirm this at plan 25-24."
  - "A defect annotation names the row that showed the defect: that row leaves the divergence, stop, duplicate, alert and health criteria and the window restarts at fixed_at_utc. An explained annotation never excuses a position without a stop or a duplicate entry (T-25-16). A row of another cause stays unexplained wherever it lies in time."
  - "The restart rule moves only the duration; every other criterion judges the whole exported journal, so a restart can never hide an unannotated row of a different cause."
requirements-completed: [EXEC-02, EXEC-03, OPS-01]
status: complete
actuals:
  tokens: 22300
  tasks: 3
  commits: 6
plan_head_before: c05307675eef8648ddcd6e1c1c04bf8f2e17bbe0
plan_head_after: b909d1c840f914d46c3c387afea122c5b2ab8aa3
---

# Phase 25 Plan 07: Demo soak evaluator Summary

Criterion 3 is now mechanical: a registration with a committed SHA-256, an owner annotation file, an owner-run `export` of the live journal and an `evaluate` that returns PASS only when every pre-registered criterion holds. No package was added; `pyproject.toml` and `uv.lock` are unchanged.

## Commands (the pair the owner runs on the soak host)

```text
uv run python scripts/evaluate_demo_soak.py verify-registration --registration R --hash-file H
uv run python scripts/evaluate_demo_soak.py export --database-url-env NAME --since T1 --until T2 --out J.jsonl
uv run python scripts/evaluate_demo_soak.py evaluate --registration R --hash-file H \
    --registration-committed-at T --journal J.jsonl [--annotations A.md] --out REPORT.json
```

Exit codes: 0 PASS; 1 a criterion FAILS (verify-registration: invalid file or hash mismatch); 2 unusable input (missing or malformed file, an output path that exists, an unset URL variable, an empty or reversed window). `--registration-committed-at` is `git log -1 --format=%cI -- <hash file>`. Export is owner-run; the database URL is read only from the variable named by `--database-url-env` and is never printed, logged or written (a failure names the exception type only).

## Registration format (`demo-soak-registration/1`)

A markdown file with exactly ONE fenced json block holding exactly these keys (an unknown or missing key is refused):

| Key | Rule |
|---|---|
| schema | `demo-soak-registration/1` |
| duration_days | integer, at least 21 (a bool or a float is refused) |
| symbols | non-empty list of non-empty strings |
| trade_generation | `{"owner_round_trips_per_week": integer >= 0 or null}` |
| healthy | `{"allowed_degraded_checks": [check names]}` |
| account, host, restart_policy, restart_rule | non-empty strings |
| pass_criteria | non-empty list of non-empty strings |
| image_commit | 40 lowercase hex |
| registered_at_utc | ISO 8601 with a timezone |

The hash file starts with the 64-hex SHA-256 of the registration file bytes (a `sha256sum` line is fine; upper case accepted).

## Annotation format

A markdown file with exactly ONE fenced json block holding a list of `{journal_event_id, kind, note, fixed_at_utc}`:

- `kind` is `explained` or `defect`; `note` is non-empty.
- `fixed_at_utc` is required for `defect` (timezone aware, not before the annotated row) and refused for `explained`.
- An unknown id, a repeated id, another kind or an extra key is refused (exit 2).

## Event-type table (plan 25-24 uses it)

| Criterion | Journal event (producer constant) | Payload keys read | Rule |
|---|---|---|---|
| registration_hash | none | none | SHA-256 of the registration equals the committed hash |
| order_after_registration | `LIVE_PLACEMENT_OUTCOME` (`src.live.execution_service.EVENT_PLACEMENT_OUTCOME`) | none | the first outcome row is strictly later than the registration commit; no outcome row passes with a note |
| duration | none | none | effective window (first row, moved to the latest defect `fixed_at_utc`, to the last row) at least `duration_days` |
| reconcile_divergence | `RECONCILE_TICK` (`src.reconcile.loop`); `SAFE_MODE_ENTER` (literal in `src.reconcile.safe_mode`, pinned by a test against the real controller) | `divergence_count` (an unreadable count counts as a divergence) | a row with a divergence, or any SAFE_MODE_ENTER, needs an annotation (explained or defect) |
| position_without_stop | `RECONCILE_TICK`: `counts[kind]` for POSITION_WITHOUT_STOP, ENTRY_WITHOUT_PROTECTIVE, TP_ONLY_POSITION; `PROTECTION_CLOSE_REQUIRED` (`src.execution.protection.EVENT_CLOSE_REQUIRED`): `branch`; `PROTECTION_TRANSITION` (`EVENT_PROTECTION_TRANSITION`): `to`, `reason` | as listed | FAIL unless the row carries a defect annotation; branches B2, B3, B4_FILL_AFTER_STOP, B5, NO_POSITION_ON_STOP_BUT_EXPOSED, B4_STOP_LOST_UNRESOLVED into CLOSE_REQUIRED, and reasons STOP_LOST / STOP_LOST_AFTER_PROTECTED into UNPROTECTED. B1 (a good stop kept), the operator close, B6 and the normal first-fill step into UNPROTECTED are not counted |
| duplicate_entry | `LIVE_PLACEMENT_OUTCOME`: `is_no_trade`, column `trade_plan_id`; `RECONCILE_TICK`: `counts[kind]` for DOUBLED_POSITION, DUPLICATE_EXCHANGE_ID | as listed | more than one placed outcome per plan, or a doubled position or duplicate exchange id, FAILS unless a defect annotation names a row of the group; explained never excuses it |
| alerts_explained | `OPERATIONAL_ALERT` (`src.ops.alerts.EVENT_OPERATIONAL_ALERT`) | none | every row needs an annotation |
| health_explained | `HEALTH_VERDICT` (`src.live.health.VERDICT_EVENT_TYPE`) | `failing`, `degraded` | a non-empty `failing`, a `degraded` name outside `healthy.allowed_degraded_checks`, or a missing list needs an annotation |
| round_trips | `PROTECTION_TRANSITION` | `reason` FIRST_FILL_STREAM or FIRST_FILL_REST (the fill), then a later `to` FLAT, per payload `trade_plan_id` | each FULL week of the effective window holds at least `owner_round_trips_per_week` completed round trips; null gives SKIPPED with a note |

Report: JSON, `sort_keys`, indent 2, LF, create-only; keys schema, verdict, evaluated_at_utc (injected clock), registration_committed_at_utc, criteria (name, status PASS/FAIL/SKIPPED, count, ids, note), window (first/last event, window start/end, effective_days to four places as a string, registered_duration_days, defect_count) and manifest (file name, byte count and SHA-256 of the registration, hash file, journal and annotations).

## TDD record

- RED 1 `d1bd731a`: the whole test module failed at collection (`cannot import name 'evaluate_demo_soak'`).
- GREEN 1 `b206a38e`: tracer, 36 tests passed; verification re-run end to end before expanding.
- RED 2 `30e3c74f`: 40 tests failed (every Task 2 behaviour).
- GREEN 2 `13918556`: 76 passed.
- RED 3 `e0f885b2`: 8 failed (`export` did not exist).
- GREEN 3 `b909d1c8`: 85 passed on a disposable PostgreSQL clone (`TEST_DATABASE_URL` is set in this environment; no skips).

## Verification run by this agent

- `uv run pytest -m "not docker" tests/test_evaluate_demo_soak.py tests/test_evaluate_demo_soak_pg.py` 85 passed, none skipped.
- `uv run python scripts/evaluate_demo_soak.py --help` exits 0 and names verify-registration, evaluate and export.
- Plan acceptance commands: the `from src.` / `EVENT_OPERATIONAL_ALERT` / `RECONCILE_TICK` check exits 0; scoped `ruff check` and `ruff format --check` on the three files pass.
- `uv run mypy src` success (291 files); `uv lock --check` ok; `git diff --exit-code -- pyproject.toml uv.lock` exits 0.
- Neighbour tests `tests/test_demo_same_code_path.py`, `tests/test_agents_md.py`, `tests/test_soak_runbook.py` pass. The full suite was not run (orchestrator, once per phase).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug in the plan's reading of the producers] The plan's event shapes differ from what the producers write**
- **Found during:** Task 2 (reading the producers, as the plan required).
- **Issue:** `RECONCILE_TICK` carries `divergence_count` and `counts` (kind to number), not a "divergence list". `PROTECTION_CLOSE_REQUIRED` is journaled only for branch B1 ("accepted knowingly"); the stop-related close branches reach the journal as a `PROTECTION_TRANSITION` into CLOSE_REQUIRED (payload `to`, `reason`) plus alerts.
- **Fix:** the divergence and kind criteria read `divergence_count` and `counts`; the stop criterion reads all three rows (tick counts, `PROTECTION_CLOSE_REQUIRED.branch`, and `PROTECTION_TRANSITION` `to`/`reason`), so it holds if a later change journals the branch on the close row too.
- **Files modified:** scripts/evaluate_demo_soak.py. **Commit:** 13918556.

**2. [Rule 2 - Missing critical coverage] TP_ONLY_POSITION added to the stop criterion**
- **Issue:** the plan named POSITION_WITHOUT_STOP and ENTRY_WITHOUT_PROTECTIVE; a position with a take-profit and no stop is also a position without a stop.
- **Fix:** TP_ONLY_POSITION is counted too (`STOP_DIVERGENCE_KINDS`). Conservative: it can only add a FAIL. **Commit:** 13918556.

**3. [Rule 3 - Blocking] SAFE_MODE_ENTER has no producer constant**
- **Issue:** `src/reconcile/safe_mode.py` journals the literal `"SAFE_MODE_ENTER"`, so "import, never re-type" is impossible without touching `src`.
- **Fix:** one named constant `EVENT_SAFE_MODE_ENTER` in the script, pinned by a test that runs the real `SafeModeController.enter_safe_mode` and compares the journaled event type. No `src` file was edited (plan `files_modified` lists none). A later `src` change that adds the constant can replace it.

### Design choices the plan left open

- Order events are all `LIVE_PLACEMENT_OUTCOME` rows (placed or refused by the gate), a stricter reading of "first soak order event" than only placed ones.
- A payload that cannot be read fails closed (unreadable tick count, health verdict without its lists, outcome without `is_no_trade` counts as placed).
- `export` with an empty window exits 2 and writes nothing, so an empty file cannot be mistaken for a soak.
- `evaluate` sets window_start from the first row of the exported journal: the owner exports with `--since` at the soak start so earlier rows are not in the file.

## Not covered by an agent-run test

- A run against a real soak journal or the owner's soak host database (agents never run `export` against a real database; only the disposable test clone was used).
- The payload keys of `PROTECTION_TRANSITION`, `PROTECTION_CLOSE_REQUIRED` and `OPERATIONAL_ALERT` are pinned by reading the producers (documented above), not by a drift test against the live coordinator; `RECONCILE_TICK` keys are pinned by the existing `tests/test_reconcile_loop.py`, `SAFE_MODE_ENTER` and the `HEALTH_VERDICT` keys by tests in this plan.
- The real registration values (duration, round trips per week, allowed degraded checks) and the commit time of the hash file: plans 25-19, 25-22 and 25-24 own them; the evaluator is generic over them.

## Known Stubs

None.

## Threat Flags

None. Mitigations: T-25-15 (hash compared by `evaluate`, first order must follow the commit; tests), T-25-16 (explained annotations ignored by the stop and duplicate criteria; tests), T-25-17 (URL from a named variable, sentinel tests on stdout, stderr and the file, also on the disposable database), T-25-SC (no dependency change; diff exits 0).

## Self-Check: PASSED

Files found: scripts/evaluate_demo_soak.py, tests/test_evaluate_demo_soak.py, tests/test_evaluate_demo_soak_pg.py. Commits found on the branch: d1bd731a, b206a38e, 30e3c74f, 13918556, e0f885b2, b909d1c8.
