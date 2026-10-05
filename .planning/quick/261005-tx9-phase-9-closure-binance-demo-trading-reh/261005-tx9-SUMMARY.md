---
phase: quick-261005-tx9
plan: 01
subsystem: execution-rehearsal
tags: [binance-demo, rehearsal, telegram-approval, exchange-facts, phase-9-closure]
requires:
  - src/execution/manager.py execute_approved_plan and attach_protectives_to_fill
  - src/adapters/telegram_callbacks.py dispatch_callback and on_callback
  - src/ops/health.py ten probes
provides:
  - scripts/demo_rehearsal.py (Binance Demo Trading rehearsal runner, dry run by default)
  - 09-EXCHANGE-FACTS.md (eight verdicts against official Binance docs)
affects:
  - plan 09-04 task 3 evidence gap (closable only after the operator runs the tool)
tech-stack:
  added: []
  patterns:
    - host guard re-checked on every adapter call, no passthrough wrapper
    - dry-run mutation block at the adapter boundary
    - evidence recorder that accepts only exchange-returned dataclasses
key-files:
  created:
    - scripts/demo_rehearsal.py
    - tests/test_demo_rehearsal_safety.py
    - tests/test_demo_rehearsal_flow.py
    - .planning/phases/09-live-execution-rollout/09-EXCHANGE-FACTS.md
  modified: []
decisions:
  - Plan stop and target levels are anchored at or beyond the mark price (min and max of entry and mark), not at the entry price, so the fill scenario stop cannot trigger on placement.
  - The plan hash includes a run id so the deterministic client ids are unique per run (the manager probes an existing algo id first and treats a cancelled one as unconfirmed).
  - Exchange facts sourced from Wayback snapshots of the official pages because the live pages answer HTTP 202 with an empty body to non-browser clients.
status: complete
duration: not measured
completed: 2026-10-05
plan_head_before: 6ca26319c85ae75ba068eea640c16eb41fb8b123
plan_head_after: 37380d2ffcc34be49da90edabf217cc696557adb
commits: 5
actuals:
  tokens: 45600
  tasks: 3
  commits: 5
---

# Phase quick-261005-tx9 Plan 01: Binance Demo rehearsal runner and exchange-fact verdicts Summary

A Demo-Trading-only rehearsal runner (dry run by default, `--execute` gated by a TTY and a typed phrase) that drives the real Phase 9 execution path against Binance Demo and writes scrubbed evidence, plus eight documented verdicts on the exchange facts left open in 09-REVIEW-FIX.md. No order was placed and no credential was used: everything was verified with fakes and a patched transport.

## Outcome

All three tasks are done and verified. The runner has NOT been run against Demo; the human check in the plan (dry run first, then permission for `--execute`) is still open and belongs to the orchestrator and the user.

## What was built

| Task | Name | Commits |
| ---- | ---- | ------- |
| 1 | Tracer: credentials, Demo-only client with per-call host guard, guarded adapter, evidence, CLI gate | 970f5b9 (RED), f8bda17 (GREEN) |
| 2 | Verdicts for the six exchange facts plus two addenda | 5d930a9 |
| 3 | Health preflight, plan derivation, Telegram taps, far and fill scenarios, attestation map | 7b03278 (RED), 37380d2 (GREEN) |

Tracer gate: auto mode was active and Task 1 carries no `blocking-human` gate. The task verify command (57 tests across both files, ruff, format, scoped mypy) was re-run end to end before expansion and again after it: "Tracer verified end-to-end, expanding".

### Runner (scripts/demo_rehearsal.py)

- SR-1: credentials only from the four named environment variables; secrets masked in repr; evidence scrubbed with `Redactor.from_environ` and re-checked after the write; only a sha256 prefix of any chat id is stored.
- SR-2: the only reachable host is the SDK Demo constant. `build_demo_sdk_client` has no host parameter, and every adapter call re-reads the live `ConfigurationRestAPI.base_path`. A transport-level test (`requests.Session.request` patched) proves every URL starts with `https://demo-fapi.binance.com/` and that a mutated base path is refused before any request.
- SR-9: in dry run the four mutating adapter methods never reach the inner adapter (a recording inner proves it). `--execute` needs a TTY and the exact phrase `DEMO {SCENARIO} BTCUSDT`, else exit 2 before any adapter is built.
- SR-6: ten probes first. Probes 3, 4 and 7 are reported DEGRADED with honest details (no WebSocket, no user-data stream, no PostgreSQL); the other seven are evaluated against live Demo REST state. Any FAIL aborts before any order.
- SR-4: Decimal-only plan derived from exchangeInfo, the mark price and `baseline-v5` (read only). The quantity is the smallest step multiple that passes entry min-notional, TP1 min-quantity and TP1 min-notional (0.004 BTC in the hand-computed test case). The rehearsal equity is back-solved and the unmodified `evaluate_risk` is required to return exactly that quantity.
- SR-7 and SR-11: approvals are created only as PENDING; APPROVED comes only from `dispatch_callback` after a real tap. Timeout, send failure, a SKIP tap and an unauthorized-chat tap place nothing. The unknown-chat step learns a second chat id from a `/start` message at run time and verifies the chat gate rejection, the `CALLBACK_RECEIVED(chat_gate_rejected)` plus `CALLBACK_REJECTED` journal events and an untouched approval row; with no second chat it is recorded NOT_REHEARSED.
- SR-3 and SR-5: placement goes through `execute_approved_plan` and `attach_protectives_to_fill` with `TP1_QUANTITY_FRACTION` imported from `src.backtest.semantics` (0.5, unchanged). `LiveEnablementController` is created and enabled inside the run and disabled in a `finally`.
- SR-8: dry-run evidence goes to a `DRYRUN` file with zero exchange order records; executed runs write `EVIDENCE` files whose order ids and timestamps come only from adapter result dataclasses. The attestation map covers the six 09-04 task 3 items (item 3 always NOT_OBSERVED, item 4 always HUMAN_ONLY).

### Exchange facts (09-EXCHANGE-FACTS.md)

| Entry | Verdict |
| ----- | ------- |
| Fact 1 query-order not-found code | UNCONFIRMED |
| Fact 2 active algo statuses | UNCONFIRMED |
| Fact 3 reduceOnly on algo orders | CONFIRMED |
| Fact 4 MIN_NOTIONAL on reduce-only legs | CONTRADICTED |
| Fact 5 MAX_NUM_ALGO_ORDERS and the literal 200 | CONFIRMED |
| Fact 6 closePosition STOP_MARKET with no position | UNCONFIRMED |
| Addendum A Demo REST URL and algo support | UNCONFIRMED |
| Addendum B PERCENT_PRICE semantics | CONFIRMED |

Findings the orchestrator should act on:
- Fact 5: the change log (2025-12-29) says the conditional order limit is 200 across all symbols and the exchangeInfo `MAX_NUM_ALGO_ORDERS` filter was removed. The "KNOWN GAP" comment in `src/execution/gates.py` (per symbol, make it dynamic from exchangeInfo) is therefore out of date. The Common Definition page still describes the removed per-symbol filter, so the two official pages conflict.
- Fact 4: the Error Code page states `-4164 MIN_NOTIONAL ... (unless you choose reduce only)`. The TP1 notional gate is stricter than the docs require; that is the safe direction, so nothing was changed. Do not relax it before the Demo cross-check.
- Fact 1: the docs name `-2011` CANCEL_REJECTED ("Unknown order sent") and `-2013` NO_SUCH_ORDER, but no page ties either to Query Order or Query Algo Order.
- Every "Demo cross-check" line reads NOT YET OBSERVED and is for the orchestrator to fill from the operator's evidence file.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fill-scenario levels would trigger on placement**
- **Found during:** Task 3 plan derivation design
- **Issue:** The plan says SL, TP1 and TP2 are tick-aligned "from" the entry price. In the fill scenario the entry LIMIT sits above the mark, so an SL 1.5 percent below the entry is still above the mark and a SELL STOP_MARKET would be rejected as "would immediately trigger" (the manager would then cancel the entry and enter SAFE_MODE).
- **Fix:** the stop is anchored at `min(entry, mark)` and the targets at `max(entry, mark)`. `derive_plan` also aborts if the stop is not below the mark or TP1 not above it.
- **Files modified:** scripts/demo_rehearsal.py, tests/test_demo_rehearsal_flow.py
- **Commit:** 37380d2

**2. [Rule 3 - Blocking] Official docs could not be fetched live**
- **Found during:** Task 2
- **Issue:** `developers.binance.com` answers every non-browser request with HTTP 202 and an empty body (a bot challenge); no WebFetch tool was available to the executor, and the legacy GitHub Pages site only redirects to the same host.
- **Fix:** every verdict quotes the Wayback Machine snapshot of the official page at the same path (snapshots dated 2026-01-13 to 2026-06-17, fetched 2026-10-05) and says so in the file header and each Source line. Nothing came from third-party mirrors, SDK models or memory. The orchestrator should re-check any verdict that matters against the live page.
- **Files modified:** .planning/phases/09-live-execution-rollout/09-EXCHANGE-FACTS.md
- **Commit:** 5d930a9

**3. [Rule 2 - Missing critical functionality] Unique plan hash per run**
- **Issue:** the manager probes an existing algo client id before placing the SL; a cancelled SL from an earlier Demo run (visible for 3 days) would be found and treated as unconfirmed, cancelling the entry.
- **Fix:** the canonical plan JSON hashed into `plan_hash` includes a run id derived from the scenario and start time.
- **Commit:** 37380d2

**4. [Rule 2 - Missing critical functionality] Honest exchange-failure evidence**
- **Issue:** the manager swallows `place_entry` exceptions (it probes and retries), so the runner would never see the exception type.
- **Fix:** `GuardedAdapter` keeps a per-method error log (type names only) and a mutating-attempt counter; the runner copies them into evidence failures and uses the counter to tell FAILED (an attempt happened) from ABORTED_NO_ORDER.
- **Commit:** 37380d2

**5. [Plan adjustment] Tracer seam kept for the Task 1 tests**
- The full far scenario now needs a Telegram channel, so the Task 1 safety-test helper passes `scenario_runner=dr.run_tracer` (a main() keyword, not a CLI option) to keep exercising the spine without Telegram. The full scenarios are covered in the flow tests.

### Other notes
- In the far scenario `cancel_untriggered_protectives` is called as planned; TP1 and TP2 were never placed, so their cancel errors are tolerated and recorded by type name only.
- An unfilled fill-scenario entry cancels the entry and then the leftover stop; a partial fill keeps its stop and gets targets attached.
- Dry-run simulated results carry a `DRYRUN-` prefixed id and are never written to `exchange_orders`.

## Verification

- `uv run --python 3.13 pytest tests/test_demo_rehearsal_safety.py tests/test_demo_rehearsal_flow.py -q`: 57 passed.
- `ruff check` and `ruff format --check` on the three Python files: clean.
- `mypy scripts/demo_rehearsal.py`: no error reported for the script (the 5 older errors in other src files are untouched).
- Regression: `tests/test_execution_manager.py`, `test_execution_attach.py`, `test_execution_health.py`, `test_execution_enablement.py`, `test_execution_secret_posture.py` pass (113 tests).
- `git status` over `src/execution`, `src/adapters`, `src/ops`, `params`, `pyproject.toml` and `uv.lock` is empty. No Phase 14 file was touched.
- The structural grep gate on 09-EXCHANGE-FACTS.md passes (6 fact sections, 8 verdicts, 8 sources, 8 cross-check lines).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model. Notable residual risk: the intent store is the in-memory test double and is labelled as such in the evidence `synthetic_inputs`; the real Telegram channel (`PtbApprovalChannel`) is not exercised offline.

## Open items for the orchestrator

1. Human check: the user runs the dry run first with the four environment variables set in the shell session (`--scenario taps`, then `--scenario far`) and reads the DRYRUN evidence (expect 7 PASS plus 3 DEGRADED probes and zero exchange orders). Only then ask for explicit permission to run `--execute` with the typed phrase. The executor never ran the script.
2. Fill the "Demo cross-check" lines in 09-EXCHANGE-FACTS.md from the operator's evidence file.
3. EXEC-01 and OPS-02 stay Pending; this plan updates no requirement status, STATE.md or ROADMAP.md.

## Self-Check: PASSED

- FOUND: scripts/demo_rehearsal.py, tests/test_demo_rehearsal_safety.py, tests/test_demo_rehearsal_flow.py, .planning/phases/09-live-execution-rollout/09-EXCHANGE-FACTS.md
- FOUND commits: 970f5b9, f8bda17, 5d930a9, 7b03278, 37380d2
