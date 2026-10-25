---
phase: 23-telegram-approval-hardening-money
plan: 03
subsystem: ops-alerts
tags: [telegram, operator-alerts, wording, golden-fixtures, tdd]
requires:
  - phase: 20-reconcile-safe-mode-hardening
    provides: "OperationalAlert, render_alert_text, TelegramAlertSender.drain, the alert sink and its bounded retry"
provides:
  - "src/ops/alert_wording.py: AlertWording, EVENT_WORDING, CLOSE_REQUIRED_WORDING, CLOSE_REQUIRED_GENERIC, worded_alert_text, reconciliation_required_text, RECONCILIATION_REQUIRED"
  - "scripts/gen_phase23_fixtures.py: render_all() and main(--check) with the alerts section (plans 23-09 and 23-12 add sections)"
  - "tests/fixtures/phase23/alerts/*.txt (16 generated golden texts) and DERIVATIONS.md"
affects: [23-11, 23-12, 23-09]
tech-stack:
  added: []
  patterns:
    - "static wording table keyed by event and CLOSE_REQUIRED branch code; Phase 20 header unchanged"
    - "generator with render_all() and --check, one section function per plan"
key-files:
  created:
    - src/ops/alert_wording.py
    - scripts/gen_phase23_fixtures.py
    - tests/test_alert_wording.py
    - tests/test_phase23_fixtures.py
    - tests/fixtures/phase23/DERIVATIONS.md
    - tests/fixtures/phase23/alerts/
  modified:
    - src/ops/alerts.py
    - tests/test_alerts.py
key-decisions:
  - "No import cycle: src/ops/alerts.py imports worded_alert_text at the top; worded_alert_text imports render_alert_text inside the function (type-only import of OperationalAlert under TYPE_CHECKING)."
  - "CLOSE_REQUIRED is always worded: an unlisted reason (a branch added later, INVALID_REASON) gets CLOSE_REQUIRED_GENERIC, never the bare template."
  - "DB_FAILURE has one sentence set that is true for all emitters, including src/execution/daily_stop.py (DAY_STATE_MISSING, DAY_STATE_UNREADABLE), which enters no SAFE_MODE and cancels nothing."
  - "The golden comparison reads files with CRLF turned into LF, because core.autocrlf=true on this machine gives the checkout CRLF; the generator itself writes LF."
requirements-completed: [APRV-01]
status: complete
duration: ~1h
completed: 2026-10-25
plan_head_before: 760d89cb
plan_head_after: 96076ce89968ea539bb4f0c8c761c333ac02bf7e
commits: 4
actuals:
  tokens: 16000
  tasks: 2
  commits: 4
---

# Phase 23 Plan 03: Plain-word operator alerts Summary

**Every critical alert Phase 20 raises now reaches the operator as the unchanged Phase 20 header plus four plain lines (what happened, position, what the system did, what you must do), with the event and reason codes verbatim, from a static table traced to the emitting code.**

## What was built

- `src/ops/alert_wording.py`: nine CLOSE_REQUIRED branch wordings (literals equal to the `BRANCH_*` constants, pinned by a test that collects them by name prefix), the generic CLOSE_REQUIRED wording, and wordings for TP_UNAVAILABLE, EMERGENCY_CLOSE_FAILED, EMERGENCY_CLOSE_NOT_SENT, ENTRY_STATE_UNKNOWN, PROTECTION_HANDOFF_FAILED and DB_FAILURE. `reconciliation_required_text()` and the `RECONCILIATION_REQUIRED` literal are wording only (not in `ALERT_EVENTS`).
- `src/ops/alerts.py` (CRLF kept): `TelegramAlertSender.drain` sends `worded_alert_text(alert) or render_alert_text(alert)`. Nothing else changed; `ALERT_EVENTS`, `OperationalAlert`, `render_alert_text` and the sanitising regexes are untouched. Working-tree numstat 3 added / 3 deleted (import, the text line, and the `_send_bounded` call collapsed to one line because `ruff format --check` requires it), `git ls-files --eol` still `w/crlf`.
- `scripts/gen_phase23_fixtures.py`: `render_all()`, `main(argv)` with `--out` and `--check` (exit 1 on a changed, missing or extra generated file), alerts section.
- 16 golden files `tests/fixtures/phase23/alerts/<EVENT>[__<REASON>].txt` (nine branch codes, the generic one, six events) and `DERIVATIONS.md`, one row per entry with the emitting file and line, read 2026-10-25.

## Tasks and commits

| Task | Commit | What |
|---|---|---|
| 1 RED | 85ca5ce1 | tests: B2 worded text, header unchanged, STALE_DATA unworded, drain sends worded text |
| 1 GREEN | 608a177c | alert_wording (B2), drain call site, generator and first golden |
| 2 RED | 73e90faf | tests: full table, branch-code equality, T-23-09/T-23-10 checks, one golden per entry |
| 2 GREEN | 96076ce8 | the full table, reconciliation wording, 16 goldens, DERIVATIONS.md |

Tracer gate: `<verify>` re-run after Task 1 (alert, wording, fixtures tests, mypy, `--check`) passed before Task 2 started.

## Verification

- `uv run pytest -m "not docker" tests/test_alert_wording.py tests/test_alerts.py tests/test_alerts_ops05_matrix.py tests/test_alerts_cancellation.py tests/test_phase23_fixtures.py tests/test_phase20_gate.py tests/test_agents_md.py tests/test_domain_no_float.py`: all pass.
- `uv run python -m scripts.gen_phase23_fixtures --check` exits 0 (and exits 1 on an altered or deleted file, tested on a temporary copy).
- `uv run ruff check` and `ruff format --check` on this plan's files, `uv run mypy src/ops/alert_wording.py src/ops/alerts.py`: clean.
- `src/execution`, `pyproject.toml`, `uv.lock` unchanged by this plan.
- Evidence label: executed tests with the fake bot [DESIGN]; no producer is composed into a running process until Phase 24.

## Deviations from Plan

**1. [Rule 3 - Blocking] Worktree base was stale.** The worktree branch `worktree-agent-a09ca2769a3faccea` was created at `master` (6c759ef6), which has no Phase 20 code (`src/ops/alerts.py` missing) and no Phase 23 plan files. The branch had no commits of its own, so at startup I ran `git reset --hard develop` (760d89cb, the tip that holds Phases 20 to 22 and plans 23-01/23-02). The orchestrator should merge this branch into `develop`, not `master`.

**2. [Rule 1 - Format] drain call collapsed to one line.** `ruff format --check` requires `_send_bounded(self._bot, self._chat_id, text, self._sleep)` on one line, so the working-tree diff of `src/ops/alerts.py` is 3 added / 3 deleted instead of "at most 3 changed lines" read as 3 added / 1 deleted. Still the single call site, still CRLF.

**3. Golden comparison tolerates CRLF.** `core.autocrlf=true` makes a Windows checkout CRLF; the test and `--check` read generated files with CRLF as LF. The plan's `.gitattributes` was not touched (not in `files_modified`).

**4. Subjects in goldens.** The plan fixed subject `plan-0001`; the real `critical()` producers use the symbol as subject. Wording does not depend on the subject, so the plan's fixed input was kept for plan-scoped events and `SYSTEM` (what `SafeModeAlertObserver` uses) for ENTRY_STATE_UNKNOWN, PROTECTION_HANDOFF_FAILED and DB_FAILURE.

No auth gates. No new dependency. The 16 file count equals nine `BRANCH_*` constants today; the test follows the constants if one is added.

## Known Stubs

None. (RECONCILIATION_REQUIRED wording has no consumer until plans 23-11 and 23-12.)

## Threat Flags

None. No new endpoint, auth path or file access; the wording table is static, and a test refuses `=`, `@` and `://` in wording lines (T-23-10). ENTRY_STATE_UNKNOWN and RECONCILIATION_REQUIRED say "needs reconciliation" and never "reject" (T-23-09).

## Self-Check: PASSED

- Files exist: src/ops/alert_wording.py, scripts/gen_phase23_fixtures.py, tests/test_alert_wording.py, tests/test_phase23_fixtures.py, tests/fixtures/phase23/DERIVATIONS.md, 16 golden files.
- Commits 85ca5ce1, 608a177c, 73e90faf, 96076ce8 are ancestors of HEAD.
