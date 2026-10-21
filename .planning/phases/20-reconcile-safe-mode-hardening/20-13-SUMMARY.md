---
phase: 20-reconcile-safe-mode-hardening
plan: 13
subsystem: ops-alerts
tags: [alerts, telegram, journal-first, dedupe, spill, restart-requeue, T-G, D-22, D-23, tdd]
requires: [20-01, 20-08]
provides:
  - "src.ops.alerts: AlertSeverity, OperationalAlert (create + strict constructor), ALERT_EVENTS (closed map of the 18 OPS-05 events), render_alert_text, JournalFirstAlertSink (alert, critical, requeue_undelivered), TelegramAlertSender (async drain -> SendReport), AlertTextBot, RequeueReport, emit_daily_state_alert (TEST TRIGGER)"
  - "journal event types OPERATIONAL_ALERT, ALERT_SUPPRESSED, ALERT_DELIVERED, ALERT_SEND_FAILED (correlation operational_alerts, entity OperationalAlert)"
affects: [20-12, 20-22, 20-26]
tech-stack:
  added: []
  patterns: ["journal first, spill fallback (record_after), then queue", "episode dedupe measured from the first alert", "bounded MESSAGE retry copied from src.paper.shadow", "fixed text template, free fields restricted to code or class-name patterns"]
key-files:
  created:
    - src/ops/alerts.py
    - tests/test_alerts.py
    - .planning/phases/20-reconcile-safe-mode-hardening/20-13-SUMMARY.md
  modified: []
key-decisions:
  - "The sender takes the sink's queue as a required keyword (`queue=`); the plan's constructor list had no queue parameter on the sender, but a shared deque is the only link between the two."
  - "ALERT_SUPPRESSED is one row per suppressed repeat carrying the running count (1, 2, ...), not one row rewritten at the end of the episode: the journal is append-only and a content-hash id cannot be updated."
  - "The dedupe episode lasts alerts.dedupe_window_ms from the FIRST alert (not sliding); the edge is exclusive (a repeat exactly one window later is a new alert)."
  - "OperationalAlert.create sanitises (INVALID_REASON / INVALID_SUBJECT / INVALID_SYMBOL / INVALID_PLAN_HASH); the dataclass constructor validates strictly and also checks alert_id against the content."
  - "If the journal and the spill both fail, the alert is still queued before AuditRecordLost is raised, so the operator is told even when the audit record is lost."
  - "A send that fails after the budget is journaled ALERT_SEND_FAILED and not re-queued in the same process; restart re-queue (no ALERT_DELIVERED row) is the second chance."
requirements-addressed: []
status: complete
duration: about 1h
completed: 2026-10-21
estimate:
  tokens: 85000
  tasks: 3
actuals:
  tokens: 13436   # chars/4 over `git diff 22df05e4 HEAD` (53744 chars)
  tasks: 3
  commits: 6      # MEASURED: git rev-list --count 22df05e4..HEAD (3 test + 3 feat), taken before the SUMMARY commit
plan_head_before: 22df05e4c02b2adfdfdda1811ed8928dddd6f128
plan_head_after: 1a45ad92c33fc662a38e096322994a1569c73bc2
---

# Phase 20 Plan 13: Operational alerts Summary

Journal-first alert sink with spill fallback, episode dedupe with counted suppression, a Telegram sender with a bounded message retry, restart re-queue of undelivered alerts, and a test-only trigger for the two Phase 21 daily states. Two new files; no existing file changed; no dependency added.

Base `22df05e4` (develop), branch `p20-13`. `commits: 6` is measured before the SUMMARY commit itself. All three tasks finished; no split point and no owner checkpoint existed in this plan. `requirements-addressed` is empty on purpose: OPS-05 is NOT complete (producers are wired by plan 20-22, the daily states by Phase 21).

## What was built

- `src/ops/alerts.py`
  - `ALERT_EVENTS`: the 18 events of the OPS-05 matrix mapped to `AlertSeverity`. Severity is my judgement (the plan lists events only): CRITICAL for UNPROTECTED_POSITION, CLOSE_REQUIRED, EMERGENCY_CLOSE_FAILED/NOT_SENT, PROTECTIVE_REJECTED, ENTRY_STATE_UNKNOWN, PROTECTION_HANDOFF_FAILED, DAILY_STOP; HIGH for TP_UNAVAILABLE, DIVERGENCE, FOREIGN/UNKNOWN_ORDER, STALE_DATA, AUTH_FAILURE, DUPLICATE_EXECUTION_ATTEMPT, DB_FAILURE, MANUAL_CLOSE_ORPHAN_UNVERIFIED; WARNING for DAILY_LOSS_WARNING. An unknown event raises `ValueError` and journals nothing.
  - `OperationalAlert`: frozen; `alert_id` is `content_hash_event_id` of (event, subject, reason, occurred_at_utc), so plan hash and symbol are not part of the id. The journal row id equals the alert id.
  - `render_alert_text`: severity, event, subject, reason, UTC time; the plan hash stays in the journal and out of the message.
  - `JournalFirstAlertSink(journal, spill, limits, queue=None)`: `alert(...)` (the reconcile-loop shape), `critical(...)` (the `CriticalAlertSink` shape; the symbol is the subject), `requeue_undelivered(rows)`. The dedupe window comes from `limits.alerts_dedupe_window_ms`; an unset value raises `ExecutionLimitsNotConfigured(("alerts.dedupe_window_ms",))` at construction.
  - `TelegramAlertSender(bot, chat_id, journal, spill, sleep, queue)`: `async drain() -> SendReport(delivered, failed, audit_lost)`. The bot type is `AlertTextBot`, a Protocol with `send_message` only (it is cast to `TelegramTextBot` for `send_text`), so no edit or other method is reachable.
  - `emit_daily_state_alert(sink, *, state, subject, now_utc)`: DAILY_STOP -> `DAILY_STOP` (CRITICAL), WARNING -> `DAILY_LOSS_WARNING` (WARNING), anything else `ValueError`. Docstring says TEST TRIGGER.
- Reuse note (plan asked for it): `_is_retryable`, `_stop`, `_wait`, `_send_bounded` are small copies of the private helpers in `src/paper/shadow.py` (not imported). They use the shared `NOTIFY_MAX_ATTEMPTS`, `NOTIFY_MAX_DELAY_SECONDS`, `NOTIFY_WAIT_*` constants from `src.paper.notify`, `send_text` and `TelegramSendError` from `telegram_notify`. The copy takes no keyboard.
- `tests/test_alerts.py`: 33 tests (fake bot with a single `send_message`, a trace-recording journal, real `telegram.error` exceptions, an injected recording sleep).

## Task commits

1. Task 1 (tracer): RED `b0b1298c` (test), GREEN `fff54cf7` (feat)
2. Task 2: RED `e005946c` (test), GREEN `9eb9d16b` (feat)
3. Task 3: RED `a27f14d8` (test), GREEN `1a45ad92` (feat)

Plan metadata: the `docs(20-13)` commit that adds this file.

## Deviations from Plan

**1. [Rule 3 - Blocking/interface] `TelegramAlertSender` has a required `queue` keyword.** The plan's constructor list is `(bot, chat_id, journal, spill, sleep)` and `drain()` takes no argument, so the sender had no way to see the sink's queue. The sink exposes `.queue` and accepts `queue=`; the composition passes the same deque to both. Plan 20-22 must do so.

**2. [Interface addition] Extra public names** beyond the plan's list: `SendReport.audit_lost`, `RequeueReport(requeued, invalid)`, `AlertTextBot`, event-type constants, `INVALID_*` constants. `requeue_undelivered` returns a report (the plan did not state a return value).

**3. [Behaviour choice] Subject, symbol and plan hash are sanitised like the reason** (replaced by `INVALID_SUBJECT`, `INVALID_SYMBOL`, `INVALID_PLAN_HASH`). The plan only named the reason, but a free subject would be a leak path of the same kind (a poisoned subject test exists).

**4. [Not a deviation, worth stating] The `TP_UNAVAILABLE` call site in `src/execution/protection.py` passes `detail` (a failure detail) as the reason.** If that value is not an upper-case code or a class name the alert shows `INVALID_REASON`. Neither call site was changed (the plan forbids it); plan 20-22 should check what `detail` carries.

No existing test had to be changed.

## TDD Gate Compliance

Tracer first, then two pairs; every task has a `test(20-13)` commit before its `feat(20-13)` commit. No REFACTOR commit.

RED evidence is the pytest output seen before each GREEN commit (`gsd_run check tdd-red-evidence` does not parse pytest output and was not run, as in plans 20-01 and 20-08):
- Task 1 RED: collection error, `ModuleNotFoundError: No module named 'src.ops.alerts'` (the module did not exist). Not an assertion failure on the behaviour.
- Task 2 RED: 3 failed, 19 passed. The failures were assertion failures for the planned behaviour (`assert 2 == 1` for dedupe and for the window edge, `DID NOT RAISE ExecutionLimitsNotConfigured`). The other 16 tests (bounded retry, rejected send, attempt budget, no-secret text, journal outage) already passed because the tracer GREEN had implemented the sender; they are regression guards, not RED.
- Task 3 RED: 10 failed, 23 passed; the failures are `AttributeError` (`requeue_undelivered` and `emit_daily_state_alert` missing), not assertions. The AST scan test passed at once because no caller exists.

Tracer feedback gate: the Task 1 verify command was re-run after the GREEN commit and passed (10 passed); the task has no `gate="blocking-human"`.

## Verification (only this plan's tests and tests of files that scan `src` were run)

- `uv run pytest -m "not docker" tests/test_alerts.py`: 33 passed (4 PTB deprecation warnings about `RetryAfter.retry_after`, raised inside `telegram.error`, not by this module).
- Also run, with `-n 4`: `tests/test_no_unratified_defaults.py tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_paper_notify.py tests/test_paper_shadow_isolation.py tests/test_modeled_costs_none_guard.py tests/test_domain_no_float.py tests/test_risk_first_spill.py tests/test_alerts.py`: 262 passed, 1 failed (below).
- `uv run mypy src`: no issues in 220 files. `uv run ruff check`: passed. `uv run ruff format --check`: 686 files already formatted.
- `git diff --exit-code -- pyproject.toml uv.lock`: exit 0 (T-20-SC).
- The full suite was not run (orchestrator). `scripts/verify_decision_alignment.py` was not run: no AGENTS.md, docs or rule file was edited.

### Pre-existing failure, out of scope (not caused by this plan)

`tests/test_phase18_gate.py::test_invariant_6_placement_is_single_attempt_and_decides_on_no_message_text` fails: `message_text_reads(manager_source)` finds `str(failed_lost)` at `src/execution/manager.py:2018` ("outside a logger call"). That line comes from plan 20-08 (`exc.add_note(str(failed_lost))`, already in the base commit `22df05e4`); this plan changed neither `manager.py` nor the test (`git diff 22df05e4 --stat` for both is empty). The `AuditRecordLost` message carries event id and exception class names only, so the intent holds, but the AST guard flags it. Whoever owns 20-08 follow-up or the phase gate should decide between allow-listing that call and changing it. I did not touch it.

## Acceptance map

| Criterion | Evidence |
|---|---|
| `test_close_required_is_journaled_before_it_is_sent` | passes; asserts trace `journal:OPERATIONAL_ALERT, send, journal:ALERT_DELIVERED` |
| wall clock / forbidden imports | `test_the_alerts_module_reads_no_wall_clock_and_imports_no_placement_path`: `wall_clock_calls` empty; the only `src.execution` import is `execution_limits`, the only `src.adapters` import is `telegram_notify` |
| one named test per Task 2 behaviour bullet | rate-limited x2 then success, rejected once, TRANSIENT budget, dedupe (+ exclusive edge), `test_alert_text_never_contains_secret_material`, sender only calls `send_message` |
| `test_daily_state_trigger_has_no_production_caller` | passes (AST scan of every other file under `src`) |
| Protocol conformance | `test_sink_satisfies_the_critical_alert_sink_and_the_reconcile_alert_sink_shapes` (mypy-checked assignment; `uv run mypy src tests/test_alerts.py` was clean when run on the tracer) |

## Evidence labels

- `[EXECUTED]` everything in the Verification section, with a fake bot. No Telegram call, no network, no Binance, nothing `[DEMO]`.
- `[ASSUMED]` Telegram rate-limit behaviour (research A3): the tests use real `telegram.error` classes but the live Bot API behaviour was not observed.
- `[NOT_TESTED]` delivery through a real `telegram.Bot`; the spill with a real PostgreSQL outage (fakes only).
- OPS-05 is NOT complete. DAILY_STOP and the daily-loss WARNING are contract plus a test trigger only: a passing test of `emit_daily_state_alert` is not end-to-end coverage. LIVE stays blocked.

## Notes for dependents

- 20-22: construct one `deque`, pass it to the sink (`queue=`) and the sender (`queue=`); wire the producers; check the conformance of `JournalFirstAlertSink.alert` with plan 20-12's `ReconcileAlertSink`; decide what `TP_UNAVAILABLE`'s `detail` should be. The OPS-05 matrix may state "test trigger only" for the two daily alerts, and the AST test proves it.
- 20-19 / Phase 24 (composition): read the `operational_alerts` rows at start and call `requeue_undelivered(rows)`, then drain periodically; `drain()` is not scheduled by this module.
- Authentication-failure and duplicate-attempt events exist in the contract but have no producer yet (T-G).

## Known Stubs

None. `emit_daily_state_alert` having no production caller is deliberate, documented and test-enforced.

## Threat Flags

None beyond the plan's register. T-20-31 mitigated (fixed template, restricted free fields, poisoned reason/subject/plan-hash test); T-20-32 mitigated (episode dedupe with counted suppression, bounded retry); T-20-33 mitigated (journal first with spill fallback, restart re-queue); T-20-SC mitigated (dependency files unchanged). The only outbound surface is the injected bot's `send_message`.

## Self-Check: PASSED

- FOUND: `src/ops/alerts.py`, `tests/test_alerts.py`, this SUMMARY
- FOUND commits: b0b1298c, fff54cf7, e005946c, 9eb9d16b, a27f14d8, 1a45ad92
- Not touched: STATE.md, ROADMAP.md, REQUIREMENTS.md, docs/DECISIONS.md, params/, pyproject.toml, uv.lock, `.gsd/`, `.planning/config.json`, `.planning/state.json`, `.planning/milestone.lock`
