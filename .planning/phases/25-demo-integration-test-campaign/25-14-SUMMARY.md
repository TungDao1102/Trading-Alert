---
phase: 25-demo-integration-test-campaign
plan: 14
subsystem: demo-scenarios
tags: [D-06, D-07, S10, S19, S11, rate-limit, rest-gate, rest-gate-cli, db-outage, spill, tdd, OPS-01]
requires: [25-02, 25-08, 25-09, 25-10, 25-11, 25-12, 25-13]
provides:
  - "tests/support/demo_scenarios/s10_rate_limit.py: S10 run(env, recorder, *, variant='429'|'418'), policy_of, retry_after_for, reconcile_gate_skips, ban_alerts, read_journal, persisted_record, sdk_calls, await_refusal"
  - "tests/support/demo_scenarios/s19_rest_gate_cli.py: S19 run(env, recorder), run_cli (in-process rest_gate_cli.main, env clock on the twin), parse_status, audit_lines"
  - "tests/support/demo_scenarios/s11_db_outage.py: S11 run(env, recorder), spill_events, the one-override trigger (stop rejection plus journal outage)"
  - "three CI twins (tests/test_demo_twin_s10_rate_limit.py, _s19_rest_gate_cli.py, _s11_db_outage.py) and three owner-run demo tests (tests/demo/test_demo_s10_..., _s19_..., _s11_...)"
affects: [25-17, 25-19]
tech-stack:
  added: []
  patterns:
    - "one scenario is one async run(env, recorder) shared by the CI twin and the owner's Demo test"
    - "a 429 or 418 answer is raised under the real adapter (SdkFaults) before the SDK sends; the real gate records and persists it; a real ban is never provoked"
    - "the operator commands run in process through rest_gate_cli.main; the twin hands the CLI the env clock for its one clock read"
    - "an outage is armed in the same override that rejects the stop, so it starts exactly when the risk-reducing action does (fake and Demo alike)"
key-files:
  created:
    - tests/support/demo_scenarios/s10_rate_limit.py
    - tests/support/demo_scenarios/s19_rest_gate_cli.py
    - tests/support/demo_scenarios/s11_db_outage.py
    - tests/test_demo_twin_s10_rate_limit.py
    - tests/test_demo_twin_s19_rest_gate_cli.py
    - tests/test_demo_twin_s11_db_outage.py
    - tests/demo/test_demo_s10_rate_limit.py
    - tests/demo/test_demo_s19_rest_gate_cli.py
    - tests/demo/test_demo_s11_db_outage.py
  modified: []
key-decisions:
  - "S10/S19 trigger: the signed read the gate sees on the composed rig is the equity refresh the CONFIRM makes through the real adapter and the SDK stand-in (account_information_v3). The reconcile tick reads the account through the fake-served snapshots, so it makes no SDK call. The 429/418 is armed after APPROVE and consumed by the CONFIRM; the refusal is UNCERTAIN_ACCOUNT_STATE with no place_entry at the edge."
  - "S10 429 Retry-After is 10 s, refused (ValueError) unless below both the cap and the 429 fallback, so the persisted wait equals the header and the test shows the header wins (twin limits: cap 999, fallback 33)."
  - "S10/S19 evidence of 'persisted' is the state record read read-only (FileGateStateStore.inspect), compared to the injection time and to the policy wait; the restriction itself is asserted on the twin and best effort on Demo (a short pause may have ended)."
  - "S19: the CLI reads the wall clock once; the twin's gate deadline is virtual (2026-10-09 + wait), so run_cli patches rest_gate_cli.datetime.now to the env clock on a synthetic env only. Without it an unforced clear would succeed on the twin and be refused on Demo."
  - "S19 uses clear --force: the persisted ban is in the future, so an unforced clear is refused (exit 3, no audit line); the scenario shows both."
  - "S11 arms StoreFaults.fail_store('journal','record',times=None) inside the same FaultEdge.override that raises the -2021 rejection (times=1), because a Demo entry fills at once and arming after the entry would race the first protection pass."
  - "S11 replays the spill the way production does: at the next start (RUNBOOK 21.2), by stopping the process in order and starting a second one over the same stores; replay_spill is not called by hand."
  - "S11 leaves SAFE_MODE with the operator exit in the FIRST process before the restart, and again in the second process if the start entered SAFE_MODE, so the durable state ends clean."
requirements-completed: [OPS-01]
status: complete
duration: about 4h (estimate; start time was not recorded)
completed: 2026-11-07
commits: 6
plan_head_before: d7af8c219f534a49f49b99455ada5b430cf420fc
plan_head_after: 8f7097b2f4d5abf7d218cb0c34041a8b387dd736
actuals:
  tokens: 24600
  tasks: 3
  commits: 6
---

# Phase 25 Plan 14: S10 rate limit, S19 REST gate operator commands, S11 DB outage Summary

The API-down and DB-failure scenarios of the Demo campaign, each as a shared `run(env, recorder)`, a CI twin on the fake composed process and an owner-run demo test. S10 shows that an injected 429 or 418 is recorded and persisted by the real REST gate, refuses the CONFIRM with nothing sent, re-sends nothing and lifts after the Retry-After; S19 shows the operator procedure after a false 418 (stop, `rest_gate_cli status`, `clear` refused then `clear --force` with its audit lines, restart on a clear gate); S11 shows a risk-reducing close survives a journal outage (close sent, flat, rows in the local spill, SAFE_MODE with a DB_FAILURE row, spill replayed at the next start). The twin of S11 exposed a real gap in `src` (finding F1) that is recorded and pinned with a strict xfail. Nothing under `src`, `scripts`, `pyproject.toml`, `uv.lock`, `harness.py`, `catalog.py` or `fault_edge.py` changed.

## Commits

| Task | RED | GREEN |
|------|-----|-------|
| 1 (tracer): S10 injected 429 / 418 | 913346ad | e2963732 |
| 2: S19 rest_gate_cli status and clear | 3942dca6 | 8692e81b |
| 3: S11 DB outage during a risk-reducing close | 535ea5ef | 8f7097b2 |

RED means the twin and demo test were committed while the scenario module was absent (collection error confirmed for each). The S19 RED commit carried one ruff E501 docstring line, fixed in its GREEN commit. The tracer gate (re-run `<verify>` end to end after the tracer commit) passed: S10 twin plus the marker guard plus `tests/demo` green.

## What each scenario asserts

**S10** (`s10_rate_limit.run(env, recorder, *, variant="429")`): clean start, start, baseline gate open. A `far` request is approved; `account_information_v3` is armed once with a 429 and Retry-After 10 s (DEMO_FAULT_INJECTED on Demo); CONFIRM. The gate holds `RATE_LIMIT_PAUSE_429`, the state file holds a `pause_until` equal to the record time plus the Retry-After and no ban deadline; the placement decision is a refusal (twin: `UNCERTAIN_ACCOUNT_STATE`) with zero `place_entry` at the edge; a replayed CONFIRM during the restriction places nothing and exactly one SDK call (the injected one) happened since arming; one reconcile tick journals `RECONCILE_SKIPPED_GATE` with reason `RATE_LIMIT_PAUSE_429`; a 429 raises no ban alert. After the pause the gate opens, a new `far` request is placed, cancelled, `account_clean`. The 418 variant (twin only, `ValueError` naming S19 on a non-synthetic env) takes the fallback wait from the loaded limits (777 s on the twin), persists the ban, journals exactly one `REST_GATE_BAN_ENTERED` alert with the gate's deadline, stops the process, starts a second one: admitted, the same ban deadline restored, entries not enabled, nothing sent. Negative control: with no armed answer the run halts at the restriction step.

**S19** (`s19_rest_gate_cli.run`): a false 418 with no Retry-After is injected after APPROVE; the CONFIRM is refused, the ban is persisted for the ratified fallback and its alert journaled. While the process still runs, `status` exits 0 and shows the ban, and an unforced `clear` exits 3 and changes nothing (research assumption A6, recorded as observed). The process is stopped in order (RUNBOOK 22.5); `status` shows the future deadline; an unforced `clear` exits 3 and writes no audit line; `clear --force --operator-id phase25-owner --reason "Phase 25 S19 false restriction"` exits 0 and the audit file `<state file>.clear-audit.jsonl` holds two lines (`requested`, `cleared`) with the operator, the reason, `forced: true` and the overridden `ban_until_utc`; `status` then shows no deadline. The restarted process restores a clear gate (`RESTORED_DURABLE`), is admitted and enabled, a `far` request is placed and cancelled, `account_clean`. The scenario never edits the state file (a source test forbids `write_text`, `open(` and the like). Negative control: a failing forced clear stops the run at the clear step.

**S11** (`s11_db_outage.run`): clean start, start, spill baseline. One override of the first stop placement arms `journal.record` unavailable (until cleared) and raises the -2021 rejection. Entry and fill; the stop is placed once (injected) and never resent; exactly one reduce-only MARKET close under the derived `xc-` id; the position is flat; the local spill holds the rows the journal refused (twin: 12 rows: `EMERGENCY_CLOSE` pre-send, `PROTECTIVE_CANCEL`, `OPERATIONAL_ALERT`, `SAFE_MODE_ENTER`/`REENTER`), among them a `SAFE_MODE_ENTER` with reason `DB_FAILURE` (the standing reason is `CLOSE_REQUIRED`, which replaced it); SAFE_MODE is on. The database is back (fault cleared): a new request is refused (twin: `RECONCILIATION_REQUIRED`) with `place_entry` unchanged; the operator leaves SAFE_MODE through `/safemode_exit` and `/confirm`; a new request after the exit is refused `CLUSTER_CAP_REJECT` (finding F1 a, recorded as NOT_REHEARSED). The process is stopped; the second process's start replays all 12 spilled rows (`failed`, `conflicts`, `corrupt` empty, spill empty, each id in the journal once); the start itself is in SAFE_MODE with entries not enabled (finding F1 b, recorded as NOT_REHEARSED); the scenario leaves SAFE_MODE again, ticks, `account_clean`. Outcome COMPLETE_WITH_GAPS. Negative control: with a healthy journal nothing is spilled and the run halts at the spill step.

## REUSES per twin

| Twin | REUSES |
|---|---|
| `tests/test_demo_twin_s10_rate_limit.py` | `tests/test_binance_ratelimit_gate.py::test_valid_retry_after_is_capped_for_ban_and_pause`, `tests/test_gate_restart.py::test_restart_with_active_418_ban_still_refuses`, `tests/test_fault_edge.py::test_an_injected_418_under_the_real_adapter_records_a_ban_and_nothing_is_resent`, `::test_an_injected_429_pauses_the_shared_gate` |
| `tests/test_demo_twin_s19_rest_gate_cli.py` | `tests/test_rest_gate_cli.py::test_clear_refuses_a_future_deadline_without_force`, `::test_clear_with_force_clears_and_says_forced`, `::test_clear_takes_effect_only_after_restart_restore`, `tests/test_rest_gate_clear_audit.py::test_a_forced_clear_over_a_real_ban_records_who_why_and_what_was_overridden`, `tests/test_fault_edge.py::test_an_injected_418_under_the_real_adapter_records_a_ban_and_nothing_is_resent` |
| `tests/test_demo_twin_s11_db_outage.py` | `tests/test_protection_sweep_spill.py::test_the_flat_sweep_spills_its_audit_rows_and_finishes_while_the_journal_is_down`, `tests/test_risk_first_spill.py::test_act_then_record_keeps_the_spill_when_the_journal_is_down`, `::test_replay_spill_records_the_event_once_and_a_second_replay_is_a_noop`, `tests/test_risk_first_write_ahead.py::test_with_the_journal_down_the_record_waits_for_the_spill_and_is_kept`, `tests/test_demo_twin_s04_stop_rejected.py::test_one_reduce_only_market_close_under_an_xc_id_flattens_the_position` |

Each twin has a test that checks every referenced test name exists in its file; the plan's REUSES AST one-liner exits 0 (checked for S19). The plan's `tests/test_execution_emergency.py` and `tests/test_risk_first_spill.py` read-first names that did not fit are replaced by the closer tests above.

## Verification

- `uv run pytest -m "not docker" tests/test_demo_twin_s10_rate_limit.py tests/test_demo_twin_s19_rest_gate_cli.py tests/test_demo_twin_s11_db_outage.py tests/test_demo_marker_guard.py tests/demo -q`: passed, 1 xfailed (finding F1 a, strict), 17 demo tests skipped (none passed). Per file: S10 twin 13 tests, S19 twin 12, S11 twin 12 (11 pass, 1 xfail).
- Also green: `tests/test_rest_gate_cli.py`, `test_demo_same_code_path.py`, `test_demo_harness.py`, `test_demo_env_factory.py`, `test_no_unratified_defaults.py`, `test_fault_edge.py`, `test_demo_evidence_index.py`, `test_agents_md.py`. `TRADING_CI_STRICT=1` collection of `tests/demo` exits 0.
- Scoped `ruff check` and `ruff format --check` on the nine files: clean. `uv run mypy src`: no issues (291 files). `uv lock --check`: ok.
- `git diff --exit-code -- src scripts pyproject.toml uv.lock tests/support/demo_scenarios/harness.py tests/support/demo_scenarios/catalog.py tests/support/fault_edge.py` exits 0.
- No `pytest -m demo`, no `--execute`, no signed or network call, no `.env` read, no soak. The nine new files are LF.

## Deviations from Plan

**1. [Plan wording] The trigger is the CONFIRM's equity refresh, not "one signed read of the reconcile tick".** On the composed rig the reconcile tick reads the account through the fake-served snapshots and makes no SDK call, so a fault armed on `account_information_v3` is consumed by the equity refresh the CONFIRM runs through the real adapter. The reconcile tick is used for what the plan also asks of it: its gate skip is journaled.

**2. [Plan wording] "the gate alert is journaled" holds for the 418 only.** The gate raises `REST_GATE_BAN_ENTERED` when a 418 starts or extends a ban; a 429 pause raises none. S10's 429 asserts the absence, its twin 418 variant and S19 assert the alert.

**3. [Plan wording] `clear` needs `--force` and writes two audit lines.** A persisted deadline in the future makes an unforced `clear` exit 3 (no audit line). The scenario shows that refusal, then `clear --force` exits 0 and appends a `requested` and a `cleared` line (the plan says "one audit line").

**4. [Plan wording] The spill is replayed at the next start, not in the running process.** `replay_spill` is called only by the start recovery (RUNBOOK 21.2), so S11 stops the process and starts a second one.

**5. [Mechanism, inside latitude] S11 arms both faults in one override.** See key-decisions; labelled DEMO_FAULT_INJECTED on Demo, the override is recorded in the edge ledger as an injected stop placement.

**6. [Scope] Entries "restored by the documented exit" are NOT shown in S11.** They cannot be: see finding F1 a. The step is recorded NOT_REHEARSED with the observed refusal, and a strict xfail test pins the plan's truth.

**7. [Shared helpers] The scenarios import helpers from `s04_stop_rejected.py`, `s06_replay.py`, `s07_restart_cuts.py`, `s08_stream_loss.py` and `s10_rate_limit.py`.** The catalog names only the nine files of the plan.

## Findings

**F1 (behaviour gap in `src`, not fixed; no src change allowed here): the coordinator's `PROTECTION_TRANSITION` rows are not spilled while the journal is down, and nothing journals them again.** RUNBOOK 21.2 and `20-DEFERRED.md` record the limit ("The coordinator does not spill its own PROTECTION_TRANSITION rows when the journal is down"); S11 shows its consequences on the real composed process, which the runbook does not state:
- (a) The risk reservation sweep (`src/live/reservation_release.py`) takes the plan's end from the journal (a `PROTECTION_TRANSITION` into FLAT). With that row lost, the closed position's reservation stays RESERVED in the running process (`counted_reservations_after_the_exit == ['RESERVED']`), so after the database is back and the operator has left SAFE_MODE the next request on the cluster is refused `CLUSTER_CAP_REJECT`. Without the outage the same sequence places the next entry (checked on the twin). Held by the strict xfail `test_after_the_database_returns_and_the_exit_a_new_request_is_placed` (desired behaviour: the documented exit restores entries) and by the observation test `test_finding_f1_a_the_closed_plans_reservation_stays_counted_after_the_exit`.
- (b) The restart rebuilds the plan from the intent rows as live (`plans_restored == 1`), the reconcile enters SAFE_MODE (observed reasons in the journal: `RESTORE_INCONSISTENT`, `UNSYNCED_NORMAL`, `ENTRY_WITHOUT_PROTECTIVE`), and the process is admitted but not enabled. The reconcile then settles the plan as FLAT (the end row goes to a healthy journal), the reservation is released and `/safemode_exit` succeeds, but entries stay disabled in that process (ENABLE runs only at start). Pinned as observed by `test_finding_f1_a_restart_after_an_outage_close_starts_in_safe_mode` (a src change that spills or re-journals the rows changes it on purpose).
The risk-reducing action itself is unaffected (close sent once, flat, spill, DB_FAILURE row). The fix belongs to the owner (spill the coordinator's rows, or let the sweep read the coordinator state), with its own DECISIONS row.

**F2 (observation, assumption A6): `rest_gate_cli` has no running-process check.** While the process runs, `status` exits 0 and an unforced `clear` is refused only for the future deadline (exit 3, nothing written). Whether a forced `clear` is refused or warns while a process runs was NOT attempted (the procedure stops the process first; a forced clear would write a file the running gate may overwrite). The CLI's own text warns "stop the trading process before clearing".

**F3 (observation): a 418 does not put the running process in SAFE_MODE.** The reconcile only journals `RECONCILE_SKIPPED_GATE`; entries are refused because the equity refresh fails (`UNCERTAIN_ACCOUNT_STATE`), not because of a gate check on the placement. A restart under a persisted ban IS admitted but enters SAFE_MODE (`STARTUP_RECONCILE_FAILED`, not enabled) and restores the same deadline.

**F4 (twin fidelity, stated in the S10 module): the twin does not exercise the real adapter's gate check on a placement.** `place_entry` and the other order calls are served by the Binance-semantics fake on the composed rig, so the gate guard inside the real `_sdk_call` is not on their path (it is covered by `tests/test_binance_ratelimit_gate.py` and `tests/test_fault_edge.py`). The signed read that carries the gate on the twin is the equity refresh.

## Not covered by an agent-run test

Everything below first runs in the owner's session (`pytest -m demo`, `TRADING_DEMO_RUN=1`); agents never connect to Demo:

- The three demo tests only collect and skip. That `SdkFaults` through the owner's `_FaultableClient` shim over the real `DerivativesTradingUsdsFutures` raises the injected 429/418 at the right call, that the real adapter classifies it and that the real gate persists to the owner's state directory are unobserved. On Demo the scheduler runs concurrently: a background task may consume the injected answer before the CONFIRM (the scenario asserts the gate, the injection count and the refusal, not who consumed it); the "nothing in between" SDK window and the reconcile skip are asserted only while the restriction is still active (otherwise recorded NOT_OBSERVED).
- S10 Demo runs the 429 only (Retry-After 10 s, real wait). The 418 beyond 259200 s and the 429/418 queue order are not scenarios: they stay permanent NOT_OBSERVED rows of `DEMO_VS_MAINNET.md` (owner decision 2026-10-22).
- S19 Demo: the CLI reads the real wall clock against a real ban deadline (days); the first run-time `clear --force` over a real Demo state file, the second process on Demo after the clear, and the gate state file under the owner's state directory are unobserved. If a Demo run stops between the injection and the clear, the owner must clear the ban by hand (instruction in the evidence under `recovery_instruction` and in the demo test docstring).
- S11 Demo: the override that arms the outage at the first stop placement on the real adapter, a real reduce-only Demo close with the journal proxy down, the local spill on the owner's disk, the replay into the real PostgreSQL journal (`PgJournalStore.get` idempotency) and the durable SAFE_MODE exit on PostgreSQL are unobserved. The real `docker compose stop postgres` variant is not part of the test. Risk caps on a real account (cluster cap, daily loss after a closed trade) may refuse the post-exit request for reasons of their own; the scenario records the reason it sees.
- Entries restored after a DB outage and the documented exit are not demonstrated anywhere (finding F1): the twin's second process is not restartable, and the first process refuses with `CLUSTER_CAP_REJECT`.

## Known Stubs

None.

## Threat Flags

None. T-25-34 (the 429/418 is raised before the SDK sends and labelled DEMO_FAULT_INJECTED; Demo S10 runs the 429 only; S19's 418 is cleared in the same run, with a recorded recovery instruction), T-25-35 (S19 asserts the audit lines and uses the CLI, never a hand edit; a source test forbids file writes), T-25-36 (S11 asserts the close goes out once reduce-only, the spill rows and the DB_FAILURE row) and T-25-SC (no package added; `pyproject.toml` and `uv.lock` unchanged) hold.

## Self-Check: PASSED

The nine created files exist; commits 913346ad, e2963732, 3942dca6, 8692e81b, 535ea5ef and 8f7097b2 are ancestors of HEAD; `git rev-list --count d7af8c21..8f7097b2` is 6.
