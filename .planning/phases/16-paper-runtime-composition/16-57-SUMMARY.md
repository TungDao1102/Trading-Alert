---
phase: 16-paper-runtime-composition
plan: 57
subsystem: paper-runtime-crash-consistency
status: complete
tags: [paper-runtime, acceptance-log, parity, gap-records, startup-seam, configuration-identity, shadow, B1-CR-02, B1-WR-05, B1-WR-01, B1-WR-08, B1-WR-03]
requires: [16-55, 16-56]
provides:
  - the acceptance log is flushed before every heartbeat and every pipeline PAPER_GAP
  - GapLedger, a shared written-gap set; the first writer of a close wins
  - PaperSupervisor.verify_start_seam, one backfill awaited right after supervisor.start()
  - config_identity (SHA-256 of the canonical, validated configuration values) in EPOCH_PINNED and every RUNTIME_START, with the raw file hash as provenance
  - check_epoch_consistency refuses a different or absent identity (exit 6, held)
  - SHADOW_SIGNAL_LOST, journaled at start for a risk-passed bar whose alert never persisted
  - decision record 16-DEC-CONFIG-PIN
affects: [16-43, 16-59, 16-62]
tech-stack:
  added: []
  patterns:
    - "flush-before-reference: a record naming a bar is written only after the log entry holding it"
    - "first-writer-wins key set shared by a worker thread and the event loop (lock-guarded claim)"
    - "semantic configuration identity: hash of validated values, raw-file hash kept as provenance"
    - "restart detection with an explicit journal row instead of a late re-drive (L-11)"
key-files:
  created:
    - tests/test_paper_runtime_gap_writers.py
    - tests/test_paper_runtime_config_pin.py
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-CONFIG-PIN.md
  modified:
    - src/paper/pipeline.py
    - src/paper/runtime.py
    - src/paper/runtime_state.py
    - src/paper/supervisor.py
    - src/paper/restart.py
    - src/paper/runtime_config.py
    - src/paper/shadow_runtime.py
    - src/paper/shadow.py
    - src/paper/evidence_export.py
    - config/paper/README.md
    - docs/operations/RUNBOOK.md
    - tests/test_paper_replay_inputs.py
    - tests/test_paper_runtime_pipeline.py
    - tests/test_paper_runtime_restart.py
    - tests/test_paper_supervisor_backfill.py
    - tests/test_paper_runtime_held_state.py
    - tests/test_paper_shadow_runtime.py
    - tests/test_paper_shadow_evidence_export.py
    - tests/test_soak_runbook.py
key-decisions:
  - "Configuration identity = sha256_hex of {schema, health, timing, account, scope} built from the validated RuntimeConfig; decimals use canonical_decimal_text (spelling-invariant), symbols keep their configured order, keys are sorted by the canonical serializer"
  - "A lost SHADOW signal is a risk-passed heartbeat with no SHADOW_ALERT_PENDING journal row naming a stored plan of the same plan_hash; it is journaled as SHADOW_SIGNAL_LOST (id on epoch and plan_hash, no parent ids) and never re-alerted"
  - "The pipeline and the supervisor share one GapLedger seeded from the restored gaps and the restart gaps; BarPipeline takes it as a required claim_gap callable"
  - "The loader now also refuses an unknown section or top-level key, so nothing outside the schema is silently ignored before hashing"
duration: about 30 minutes
completed: 2026-10-16
commits: 4
plan_head_before: 1c87ac368c560414d2b385e34edb0eb5f03b2897
plan_head_after: c92401d94d277f74e0334f41ba1f42fe23375aff
actuals:
  tokens: 20400
  tasks: 3
  commits: 4
---

# Phase 16 Plan 57: Crash consistency and configuration identity Summary

Plan 16-57 makes the paper runtime crash-consistent and binds its configuration to the pin.

- A crash inside a batch can no longer fail the parity check. The acceptance log is written before every heartbeat and every gap.
- Each close gets one PAPER_GAP, whichever writer reports it first.
- The start-up seam is backfilled once after the start.
- A risk-passed bar whose SHADOW alert never persisted is journaled at the next start. It is never alerted late.
- A changed configuration value is refused with exit 6 and holds the container. A comment-only edit runs.

## Tasks

| Task | Name | Commit |
| --- | --- | --- |
| 1 | Tracer: a crash after a 4h heartbeat inside one batch still passes parity (B1-CR-02) | 0a9fc12 |
| 2 | B1-WR-05 gap writers and B1-WR-01 start-up seam | adc9cfc |
| 3 | Step 0: the owner's decision record 16-DEC-CONFIG-PIN | c56156b |
| 3 | Configuration identity (B1-WR-08) and lost SHADOW signals (B1-WR-03) | c92401d |

Commit count, measured: `git rev-list --count 1c87ac3..HEAD` is 4 before this metadata commit.

## Re-check outcomes

All five findings held. Each re-check failed on the parent before its fix.

- **B1-CR-02.** One batch held a 4h LIVE_WS bar and the 1h bar at the same close, and the 1h context factory raised. The committed 4h heartbeat then failed parity with "the bar is not a LIVE_WS entry of its run's acceptance log". The gated heartbeats and the pipeline gaps were also written before their history record:
  - a WARMUP_INSUFFICIENT heartbeat;
  - a DATA_STALE heartbeat;
  - a REST_BACKFILL gap;
  - a missing-sibling gap.
- **B1-WR-05 (a).** One supervisor backfill raised for BTCUSDT 1h and wrote two SUPERVISOR gaps. The cursor was not advanced, so the next `reconnect` fetched the same closes. The pipeline then wrote REST_BACKFILL gaps with the same ids and other payloads, and the loop exited 7 with `RuntimeRecordConflict`.
- **B1-WR-05 (b).** The pipeline recorded a missing 4h sibling (NO_4H_SIBLING). A later reconnect backfilled the 4h bar, and the pipeline's REST_BACKFILL gap for the same close exited 7 with `RuntimeRecordConflict`.
- **B1-WR-01.** The test used a fake SDK client that fires `open` when a callback is registered on an open connection, as binance_common does. A bar that closed between the warm-up snapshot and the subscription never reached history and had no gap. The next live 1h bar was `HISTORY_DISCONTINUITY`.
- **B1-WR-08.** After the pin, `account.risk_rate` was changed from "0.01" to "0.02". The start exited 0 and the loop ran with 0.02. EPOCH_PINNED and RUNTIME_START held only the strategy id, the parameter set id and the hash. Recorded in 16-DEC-CONFIG-PIN.md.
- **B1-WR-03.** A fault was injected after the risk-passed heartbeat and before the SHADOW write: `insert_signal` raised, and run 1 exited 7. The restart journaled nothing about the missing plan.

## Recorded option

`decisions/16-DEC-CONFIG-PIN.md` holds:
- `option: refuse-on-value-change`, `decided by: user` and `date: 2026-10-16`;
- the source, 16-DEC-FIXPLANS.md at commit bdbdc11;
- the user's line verbatim;
- the 16-57 summary line of 16-DEC-FIXPLANS.md, labelled as a summary of the reviewer text;
- the reviewer section "Q1 — Bind effective runtime configuration to the pinned epoch", copied by a script from the committed file and asserted equal;
- the B1-WR-08 re-check result.

## The configuration identity

- **How it is computed.** `config_identity(config) = sha256_hex(config_identity_payload(config))`, in `src/paper/runtime_config.py`. The payload is `{"schema": "paper-runtime-config-identity/1", "health": {...}, "timing": {...}, "account": {...}, "scope": {"symbols": [...]}}`. It is built from the validated `RuntimeConfig` and never from the file bytes.
- **What goes into it.**
  - Every key of every section, in schema order.
  - Integers stay integers.
  - Decimals use `canonical_decimal_text`, so "0.01" and "0.010" are one value.
  - The symbols keep their configured order, and reordering them changes the identity.
  - `canonical_bytes` sorts the keys.
- **What changes it.** A comment, a blank line, whitespace, or a different key or section order leaves it unchanged. Any changed value changes it; each key of each section is tested one at a time.
- **What reaches it.** A missing or unknown key is refused by the loader (exit 4) before any hash. So is an unknown section or top-level key, which is new; see the deviations.
- **What the records carry.** EPOCH_PINNED, written by `--pin-epoch`, and every RUNTIME_START carry two fields:
  - `config_identity_sha256`, the identity;
  - `config_file_provenance`, holding `file_sha256` (the raw bytes) and `path` (the value of `PAPER_RUNTIME_CONFIG`). This is provenance only and is never compared.
- **The check.** `check_epoch_consistency(epoch, state, *, config_identity)` compares the identity with the latest pin of the epoch.
  - A different identity is an `EpochMismatch`, and so is a pin with no identity. That means exit 6 before RUNTIME_START, with no record written, and a hold with the held marker under `--hold-on-refusal` (`--healthcheck` reports unhealthy).
  - The refusal message names the first 12 hex characters of both identities, never a configuration value.
  - A comment-only edit starts normally, and its RUNTIME_START records the new file hash.

## The lost-signal SHADOW event

- **Name.** `EVENT_SHADOW_SIGNAL_LOST = "SHADOW_SIGNAL_LOST"`, in `src/paper/shadow_runtime.py` next to `EVENT_SHADOW_POSITION_CLOSED` and `EVENT_SHADOW_PLAN_CONTEXT`. tests/test_paper_shadow_evidence_export.py asserts the exact name.
- **Detection.** `_LiveLoop.run` reads the epoch's PAPER_BAR_PROCESSED records of stage `risk_passed` (`_risk_passed_bars`) and passes them as `RiskPassedBar` values to `ShadowCoordinator.start(risk_passed=...)`, which hands them to `restore`. shadow_runtime never imports the runtime. A heartbeat with no plan hash or signal id fails the start closed.
- **What counts as persisted.** A bar's alert persisted when the `shadow-alert:<signal_id>` correlation holds a SHADOW_ALERT_PENDING row that names a stored plan with the same plan_hash. That row is written after the signal, the plan, both approvals and the mapping.
- **The journal row.** Every other bar gets one row:
  - correlation `shadow-lost:<plan_hash>`;
  - id `correlated_event_id(prefix="shadow-lost", entity_id=plan_hash, step=epoch_id)`;
  - no signal or plan id, because those parent rows do not exist and the foreign keys would refuse them;
  - a payload of epoch, plan hash, signal id, symbol, interval, bar close, reason `NOT_PERSISTED_BEFORE_RESTART` and mode, with no wall-clock instant.
- **What else happens.** The bar is logged with `paper.shadow.signal_lost`. There is no alert, no approval and no plan row.
- **On a second start.** The row is found by its correlation and nothing new is written.
- **Counted apart.** `ShadowCoordinator.lost_signals()` returns the lost plan hashes. `paper_records()` and the evidence export never include them, and `attribute_shadow_outcome` refuses the event as an outcome.

## Gap writers and the seam

- `GapLedger` (in runtime_state) is built once per run in `run_admitted`, or comes from `LoopWiring.gap_ledger` for an injected pipeline. `_restore_before_subscribing` seeds it with `restored.recorded_gaps` and with the restart gaps it just wrote.
- `_LiveLoop._sink_gap` and `BarPipeline._write_gap` claim a key before writing. A refused claim skips only the PAPER_GAP record. The bar still enters history. The first writer's `source` and `reason` stay.
- `claim_gap` is a required keyword of `BarPipeline`, with no default, like its other inputs. The five test constructions were updated.
- `PaperSupervisor.verify_start_seam()` marks one pending event and runs `_run_event("open")`. That is the path a connection event takes: `_backfill_and_emit(GapReason.WS_RECONNECT_WINDOW)` under `_recovery_lock`, with live bars held and delivered after the backfilled bars.
  - `_LiveLoop.run` awaits it right after `supervisor.start()` and before the consumer starts. If it fails, the supervisor and the SHADOW chain are stopped and the start fails with RuntimeFailClosed (exit 7).
  - Its depth is the existing REST backfill path; plan 16-62 wires `rest_backfill_depth_bars`.
- The `restart.py` docstring now names the post-start verification backfill. Q-D, the fence and the ratified retry constants are unchanged.
- The supervisor cursor is unchanged. A pair whose backfill raises does not advance its cursor, so a later backfill heals history (tested). A hole the exchange reports between returned bars still lets the cursor pass it, as before; this plan does not change that.

## Deviations from Plan

1. **[Rule 2] Unknown sections refused.** The loader now also refuses an unknown section or top-level key. Before, `_refuse_unknown_keys` checked keys only inside the four sections, so `[extras]` or `version = 3` was silently ignored. The owner's rule says to reject unknown keys rather than ignore them. `paper-runtime-v2.toml` is unaffected, and so are the test configurations.
2. **Decimal canonical form.** The identity uses `canonical_decimal_text` (D047, spelling-invariant), not `str(Decimal)`, because the decision compares effective values. A spelling such as "0.010" is not a value change.
3. **Lost-signal criterion.** The check reads the alert's SHADOW_ALERT_PENDING row and the stored plan row with the same plan_hash, not the plan row alone. A plan row without its approvals and journal row was never alerted either.
   - `ALERT_CORRELATION_PREFIX` was added to `src/paper/shadow.py`, a file outside the plan's list, and `_alert_event` uses it.
   - The `start` and `restore` parameter `risk_passed` defaults to an empty tuple, so the rehearsal and the existing callers are unchanged. The composition root always passes it.
4. **evidence_export.py.** Only its docstring changed. The analytics-evidence/2 document gains no key (D-18, existing fields only). "Counted apart" is `ShadowCoordinator.lost_signals()` plus the attribution reader's refusal, both tested.
5. **Tests outside the list.** tests/test_soak_runbook.py has a new 20.2 test for the identity rule. tests/test_paper_runtime_restart.py now expects 8 REST calls in the planned-restart test instead of 4: 4 warm-up calls and 4 seam-verification calls from the seeded cursors.
6. **TDD order in Task 3.** For Tests 1 and 2, the RED evidence is the B1-WR-08 re-check: on the parent the start exited 0 with no record. The test module imports names that do not exist on the parent. Those tests were not run separately against the parent before the implementation. The WR-03 tests did fail first: the restart wrote 0 lost rows and the new name did not exist.
7. **Re-check tooling.** For Task 2, a temporary copy of the new test file without the ledger arguments ran against the parent code and was deleted. It was never committed.

## Verification

All commands used `uv run --frozen --extra dev`. Only targeted tests were run, because the machine is memory-limited.

- **Task 1.** The verify set (replay_inputs, runtime_pipeline, parity, decision_surface, exit_evaluator) gave 127 passed and 1 skipped (PostgreSQL). Neighbours (runtime_loop, restart, coverage) gave 88 passed.
- **Task 2.**
  - The verify set (gap_writers, restart, supervisor_backfill, runtime_loop, runtime_pipeline, coverage) gave 158 passed. supervisor_backfill alone, with the two new seam tests, gave 36 passed.
  - Neighbours (watchdog, replay_inputs, market_inputs, held_state, instance_guard, admission, liveness) gave 168 passed and 1 skipped.
  - Neighbours (shadow_runtime, compose, shadow_isolation, restart_pg, runtime_state) gave 129 passed and 3 skipped.
- **Task 3.**
  - `grep -E "^option: refuse-on-value-change$"` on the record passes.
  - The verify set (config_pin, held_state, shadow_runtime, shadow_evidence_export, exit_evaluator, compose, restart) gave 221 passed.
  - Neighbours gave 271 passed and 5 skipped (PostgreSQL). They were gap_writers, instance_guard, watchdog, liveness, admission, runtime_loop, market_inputs, shadow_isolation, test_signal_rehearsal, soak_evidence_export, restart_pg and runtime_state.
  - The docs tests (soak_runbook, deploy_docs, runtime_env) gave 114 passed. config_file and no_unratified_defaults passed.
- **Checks.** `ruff check src scripts tests` passed. `ruff format --check src scripts tests` reports 571 files already formatted. `mypy src` found no issues in 202 source files.
- **Skipped here, recorded in `.planning/WINDOWS.md` (entries 8 to 11).**
  - The PostgreSQL replay-inputs round trip (test_paper_replay_inputs.py:1185).
  - The three PostgreSQL restart tests (test_paper_runtime_restart_pg.py).
  - The PostgreSQL soak evidence export test (test_soak_evidence_export.py:818).
  - The SHADOW_SIGNAL_LOST row on the PostgreSQL SHADOW and journal stores.
  - Entry 4 of 16-56 (the rehearsal PostgreSQL test) is still open.

## Owner actions

None new from this plan. Two owner actions from earlier plans are still open before plan 16-43:
- the separate soak backup bucket (16-55);
- the second healthchecks.io check and its URL for the paper heartbeat (16-56).

Note for the pin in plan 16-43:
- Any change of a `paper-runtime-v2.toml` value after the pin is refused and needs a new pin.
- Plan 16-62 wires `rest_backfill_depth_bars` without changing its value, so it does not change the identity. It still lands before the pin (correction 5).

## Requirement status

PAPER-01 stays Pending. REQUIREMENTS.md closes it only after the trial soak of plan 16-43 (D061 item J).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat register:
- T-16-144 to T-16-148 are mitigated as planned.
- The new provenance field records the configuration path, which is not a secret, and no configuration value.
- The lost-signal row holds identifiers and a reason only.

## Self-Check: PASSED

- FOUND: tests/test_paper_runtime_gap_writers.py, tests/test_paper_runtime_config_pin.py, decisions/16-DEC-CONFIG-PIN.md
- FOUND commits: 0a9fc12, adc9cfc, c56156b, c92401d
