---
phase: 09-live-execution-rollout
plan: "04"
subsystem: execution
tags: [tdd, health-checks, enablement, protective-confirmation, expiry, cancel-wiring, live-5-scope, checkpoint-blocked]
dependency_graph:
  requires:
    - phase: 09-01
      provides: execution-manager, placement-surface, sdk-17.4.0-verified
    - phase: 09-02
      provides: size-protectives-to-filled-qty, fold-fills
    - phase: 09-03
      provides: decide-placement-gate, live-enablement-controller, manager-enablement-wiring
  provides:
    - health-check-probes
    - health-verdict-aggregate
    - protective-confirmation-verdict
    - entry-fill-multi-leg-attach
    - pending-entry-expiry-wiring
    - protective-cancel-wiring
    - emergency-manual-close
    - live-5-scope-guard
  affects:
    - phase-9-live-readiness-checkpoint (blocked — see below)
tech-stack:
  added: []
  patterns: [fail-closed-health-aggregate, journal-first-health-probe, protocol-typed-notify-surface, journal-first-cancel-wiring, live-5-scope-guard, fixed-order-multi-leg-attach]
key-files:
  created:
    - src/ops/health.py
    - tests/test_execution_health.py
    - tests/test_execution_enablement.py
    - tests/test_execution_attach.py
    - tests/fixtures/phase9/enablement/enabled/input.json
    - tests/fixtures/phase9/enablement/enabled/expected.json
    - tests/fixtures/phase9/enablement/emergency/input.json
    - tests/fixtures/phase9/enablement/emergency/expected.json
    - tests/fixtures/phase9/attach/input.json
    - tests/fixtures/phase9/attach/expected.json
    - .planning/phases/09-live-execution-rollout/deferred-items.md
  modified:
    - src/execution/manager.py
decisions:
  - "Ten health probes (SECURITY_AND_OPERATIONS section 4) are pure functions of caller-supplied inputs plus injected now_utc; each journals exactly one HEALTH_CHECK JournalEvent; run_health_checks aggregates with any-FAIL-blocks-enablement fail-closed posture"
  - "Telegram delivery probe consumes a narrow Protocol-typed NotifierLike surface (structural send_message) so health.py never imports python-telegram-bot; exceptions/None responses never leak chat_id or probe text into the journal payload (T-9-15)"
  - "require_protective_confirmation is the single source of truth for the all-three-legs-confirmed check; both the mid-attach failure path and the end-of-attach defensive check route through it, composing with SafeModeController.enter_safe_mode on any gap"
  - "attach_protectives_to_fill places SL then TP1 then TP2 in fixed order; an unconfirmed leg halts immediately with zero rescue placement (D-02) — no retry, no attempt at remaining legs"
  - "expire_pending_entry and cancel_untriggered_protectives journal the pre-image BEFORE and the post-image AFTER each cancel call, mirroring the 08-04 sweeper's journal-first pattern"
  - "emergency_manual_close runs a fixed four-step EXECUTION_SPEC section 11 sequence: expire pending entry, cancel untriggered protectives, disable live orders, freeze to SAFE_MODE"
  - "LIVE5_SYMBOLS (BTCUSDT/ETHUSDT/BNBUSDT/SOLUSDT/XRPUSDT) scope guard raises ValueError before any adapter call in execute_approved_plan, attach_protectives_to_fill, expire_pending_entry, cancel_untriggered_protectives, and emergency_manual_close"
key-decisions:
  - "HealthCheckResult and HealthVerdict are frozen dataclasses; HealthVerdict.is_no_trade=True iff any probe reports STATUS_FAIL"
  - "ProtectiveConfirmationVerdict and AttachOutcome are frozen dataclasses mirroring the PASS-or-NO_TRADE discriminated-envelope pattern used throughout src/execution and src/risk"
  - "Task 3 (testnet rehearsal plus credential provisioning plus LIVE-TAP clearance) is a gate=\"blocking-human\" checkpoint that cannot be executed or fabricated by the executor — it requires real operator-supplied evidence and stays BLOCKED pending that attestation"
patterns-established:
  - "Pattern: fail-closed health aggregate — any single FAIL probe blocks the whole verdict, never averaged or weighted"
  - "Pattern: journal-first cancel wiring — pre-image before, post-image after every cancel_order/cancel_algo_order call"
  - "Pattern: live-5 scope guard — a hard ValueError boundary (not a NO_TRADE envelope) for symbols outside the smallest-capital live universe"
requirements-completed: []
coverage:
  - id: D1
    description: "Ten health probes cover market-feed freshness, last closed-candle time, WS state, user-data stream state, REST error rate, reconciliation drift, DB writes, Telegram delivery, unprotected positions, and orphaned orders, each journaled as a HEALTH_CHECK JournalEvent"
    requirement: OPS-02
    verification:
      - kind: unit
        ref: tests/test_execution_health.py#test_all_probes_pass_yields_aggregate_pass_verdict
        status: pass
      - kind: unit
        ref: tests/test_execution_health.py#test_any_fail_probe_blocks_enablement_with_health_check_failed
        status: pass
      - kind: unit
        ref: tests/test_execution_health.py#test_each_probe_journals_exactly_one_health_check_event
        status: pass
    human_judgment: false
  - id: D2
    description: "Protective confirmation holds ENTRY_WITHOUT_PROTECTIVE and routes to SAFE_MODE; entry fills attach all three protective legs sized to folded filled quantity via fold_fills then size_protectives_to_filled_qty then per-leg place_algo_protective with confirmation, per D-02"
    requirement: EXEC-01
    verification:
      - kind: unit
        ref: tests/test_execution_attach.py#test_partial_fill_replayed_fills_fold_and_attach_once
        status: pass
      - kind: unit
        ref: tests/test_execution_attach.py#test_unconfirmed_sl_leg_yields_entry_without_protective_with_zero_rescue
        status: pass
    human_judgment: false
  - id: D3
    description: "Non-live-5 symbols raise ValueError before any adapter call across every placement/cancel path"
    requirement: EXEC-01
    verification:
      - kind: unit
        ref: tests/test_execution_attach.py#test_non_live5_symbol_raises_before_any_adapter_call
        status: pass
    human_judgment: false
  - id: D4
    description: "Testnet rehearsal plus credential provisioning plus LIVE-TAP clearance — operator attestation with real evidence lines"
    requirement: OPS-02
    verification:
      - kind: human
        ref: "09-04 task 3 (checkpoint:human-verify, gate=blocking-human)"
        status: blocked
    human_judgment: true
metrics:
  duration: ~50min
  completed_date: 2026-09-29
  tasks: 2
  commits: 4
status: blocked
actuals:
  tokens: 21972
  tasks: 2
  commits: 4
  plan_head_before: fbf6d26847de4f30a5032bc4f606d355d0cf9400
  plan_head_after: 07f90d63888357e59ca4d2feaa47d792baa92cf5
---

# Phase 9 Plan 4: Health Probes, Protective Confirmation, Expiry/Cancel Wiring, Live-Readiness Checkpoint Summary

## One-liner

Ten SECURITY_AND_OPERATIONS health probes plus protective-confirmation/expiry/cancel wiring and the LIVE-TAP live-readiness gate — tasks 1-2 complete and green, task 3 (testnet/credential/LIVE-TAP human attestation) is a `gate="blocking-human"` checkpoint that stays BLOCKED pending real operator evidence.

## Status: BLOCKED on human checkpoint (task 3 of 3)

**Tasks 1 and 2 are complete, tested, and committed.** Task 3 — the
testnet rehearsal plus credential provisioning plus LIVE-TAP clearance
gate — cannot be executed or fabricated by an autonomous executor. Per
the plan's own prohibitions ("MUST NOT fabricate testnet rehearsal,
credential provisioning, or Telegram tap evidence in fixtures") and the
`gate="blocking-human"` semantics (never auto-approved, in any mode,
per `checkpoints.md` golden rule 6), this plan halts here. No live
order exists and none can exist until the operator clears this gate.

## Task Results

| Task | Name | Commits | Files |
|------|------|---------|-------|
| 1 | Health probes plus enablement and health suites | `d98b292` (test), `be66f32` (feat) | src/ops/health.py, tests/test_execution_health.py, tests/test_execution_enablement.py, tests/fixtures/phase9/enablement/{enabled,emergency}/{input,expected}.json |
| 2 | Protective confirmation plus entry expiry and cancel wiring plus filled-qty multi-leg attach | `fc4691d` (test), `07f90d6` (feat) | src/execution/manager.py, tests/test_execution_attach.py, tests/fixtures/phase9/attach/{input,expected}.json |
| 3 | Testnet rehearsal plus credential provisioning plus LIVE-TAP clearance GATE | — NOT EXECUTED — | blocking-human checkpoint, awaiting operator attestation |

## Task 1: Health Probes Plus Enablement and Health Suites

**Commits:** `d98b292` (test, RED), `be66f32` (feat, GREEN)

Created `src/ops/health.py` with one probe function per
SECURITY_AND_OPERATIONS section 4 item:

- `check_market_feed_freshness`, `check_last_closed_candle_time`,
  `check_ws_connection_state`, `check_user_data_stream_state`,
  `check_rest_error_rate`, `check_reconciliation_drift`,
  `check_db_writes`, `check_telegram_delivery` (async),
  `check_unprotected_positions`, `check_orphaned_orders`

Each returns a frozen `HealthCheckResult` (check name, PASS/FAIL/
DEGRADED status, detail, `observed_at_utc` from caller-supplied
`now_utc`) and journals exactly one `HEALTH_CHECK` JournalEvent.
`run_health_checks` aggregates to a `HealthVerdict`: any FAIL yields
`is_no_trade=True, reason_code="HEALTH_CHECK_FAILED"` — RED blocks
enablement, fail-closed.

The Telegram delivery probe consumes a narrow Protocol-typed
`NotifierLike` surface (structural `send_message`) so `health.py`
never imports python-telegram-bot; exceptions and `None` responses
never leak `chat_id` or probe text into the journal payload (verified
by a dedicated secret-free test).

`tests/test_execution_enablement.py` proves default-disabled blocks,
explicit `enable()` allows, and the emergency manual-close
(`LiveEnablementController.disable()`) composes with
`SafeModeController.enter_safe_mode()`/`guard_new_entries()` to block
new entries on both surfaces simultaneously — using only pre-existing
09-03 modules, so this suite is self-contained within task 1.

**Verification:**
```
uv run --python 3.13 pytest tests/test_execution_enablement.py tests/test_execution_health.py -q
→ 14 passed
uv run --python 3.13 ruff check src/ops/health.py tests/test_execution_health.py tests/test_execution_enablement.py
→ All checks passed
```

## Task 2: Protective Confirmation Plus Expiry/Cancel Wiring Plus Filled-Qty Multi-Leg Attach

**Commits:** `fc4691d` (test, RED), `07f90d6` (feat, GREEN)

Added to `src/execution/manager.py`:

- `require_protective_confirmation` — the single source of truth for
  the all-three-legs-confirmed check; holds `ENTRY_WITHOUT_PROTECTIVE`
  and routes to `SafeModeController.enter_safe_mode(...)` when SL/TP1/
  TP2 are not all confirmed. Never places rescue protection (D-02).
- `attach_protectives_to_fill` — folds entry fills via `fold_fills`,
  sizes SL/TP1/TP2 to the FOLDED filled quantity via
  `size_protectives_to_filled_qty`, then places + confirms each leg in
  fixed order (SL, TP1, TP2) via the Protocol-typed
  `place_algo_protective`, with deterministic `xa-` algo client ids.
  An unconfirmed leg halts immediately — zero rescue placement, zero
  attempt at remaining legs.
- `expire_pending_entry` — cancels a stale pending LIMIT entry via
  `cancel_order` by deterministic `x-` EN id, on any of the five
  EXECUTION_SPEC section 4 triggers (expiry_time, invalidation,
  superseded_plan, mode_change, operator_close), with journal
  pre-image before and post-image after.
- `cancel_untriggered_protectives` — cancels the SL/TP1/TP2 algo legs
  via `cancel_algo_order` by `xa-` ids, same journal-first pattern.
- `emergency_manual_close` plus `safe_mode_freeze` — implement
  EXECUTION_SPEC section 11 manual controls: cancel pending entry,
  cancel untriggered protectives, disable live orders
  (`LiveEnablementController.disable`), freeze to SAFE_MODE.
- `LIVE5_SYMBOLS` scope guard (`BTCUSDT`, `ETHUSDT`, `BNBUSDT`,
  `SOLUSDT`, `XRPUSDT`) — non-live-5 symbols raise `ValueError` before
  any adapter call, wired into `execute_approved_plan` and every new
  placement/cancel path.

`tests/test_execution_attach.py` proves:
1. Partial-fill sizing to filled qty plus replayed-fill single attach
   — a fill-event list with a replayed duplicate folds to the
   deduplicated filled quantity (0.300 from raw events summing 0.500
   with a replay), and the three protective legs are placed exactly
   once each, sized to that folded quantity (TP1 qty 0.150).
2. Unconfirmed-leg divergence with zero rescue placement — an adapter
   that rejects the SL leg yields `ENTRY_WITHOUT_PROTECTIVE` with
   exactly one `place_algo_protective` call; SAFE_MODE composition
   fires with reason `ENTRY_WITHOUT_PROTECTIVE`.
3. Non-live-5 symbol (`DOGEUSDT`) raises `ValueError` before any
   adapter call.

**Verification:**
```
uv run --python 3.13 pytest tests/test_execution_attach.py tests/test_execution_manager.py tests/test_execution_gates.py tests/test_execution_modes.py tests/test_execution_partials.py -q
→ 29 passed
uv run --python 3.13 ruff check src/execution/manager.py tests/test_execution_attach.py
→ All checks passed
uv run --python 3.13 mypy src/execution/manager.py src/ops/health.py
→ Success: no issues found in 2 source files
uv run --python 3.13 pytest tests/ -q
→ full suite green (5 pre-existing skips unrelated to this plan)
```

## Task 3: Testnet Rehearsal Plus Credential Provisioning Plus LIVE-TAP Clearance GATE — NOT EXECUTED

**Status: BLOCKED — `gate="blocking-human"`, awaiting operator attestation.**

This task requires the operator to, on testnet:

1. Perform the smallest-quantity LIMIT entry plus all three CONDITIONAL
   protective legs round-trip.
2. Confirm TP1-partial then TP2 close-all remainder semantics
   (RESEARCH A1) — or record corrected semantics as a follow-up.
3. Confirm `ALGO_UPDATE.o.rm` rejection parsing (RESEARCH A4).
4. Provision live no-withdrawal keys with IP allowlisting, encrypted
   off-source, with paper/live separation.
5. Clear the 08-02 LIVE-TAP GATE with a real APPROVE + SKIP tap + an
   unknown-chat rejection.
6. Attest health-green on all ten probes built in task 1.

**No evidence has been fabricated.** No test fixture in this plan
claims any testnet order id, credential provisioning confirmation, or
Telegram tap outcome. The executor cannot obtain any of this — it
requires real credentials, a real Telegram bot/chat, and a real
Binance testnet account.

**Nothing in this plan enables live orders.** `LiveEnablementController`
still defaults `LIVE_ORDERS_DISABLED=true`; no code path in this
plan or any prior 09-01/02/03 plan flips it. The block is both a
process gate (this checkpoint) and a code-level fail-closed default.

## Deviations from Plan

**1. [Rule 1 - Bug] Fixed `FillEvent` construction in the attach test**

- **Found during:** Task 2 (RED→GREEN transition)
- **Issue:** The attach test initially passed raw JSON dicts (with
  string `fill_quantity` values) directly to `attach_protectives_to_fill`.
  `fold_fills` only sums `fill_quantity` when it is a `Decimal`
  instance (D-12 boundary discipline) — passing raw fixture dicts
  silently summed to `Decimal("0")`, producing a spurious `NO_FILL`
  result instead of the intended `0.300` folded quantity.
- **Fix:** Added `_build_fill_events` to convert the fixture's
  `fill_events` list into `FillEvent` dataclass instances (mirrors
  `tests/test_execution_partials.py:_build_fill_events`), then used it
  at all three call sites in `tests/test_execution_attach.py`.
- **Files modified:** `tests/test_execution_attach.py`
- **Commit:** folded into `07f90d6` (part of the GREEN commit, since
  it was discovered during the same verification cycle).

**2. [Out-of-scope, logged not fixed] Pre-existing `src/ops/drills.py` ruff findings**

- **Found during:** Running the plan's overall verification step
  (`ruff check src/execution src/ops`).
- **Issue:** Three F401 unused-import findings in `src/ops/drills.py`
  (a Phase-8 file this plan did not modify): unused `datetime.UTC` at
  module scope, and two local `import asyncio` statements that shadow
  the module's own helper import.
- **Action:** Logged to
  `.planning/phases/09-live-execution-rollout/deferred-items.md` per
  the executor's scope-boundary rule — NOT fixed, since it is outside
  this plan's file list. `src/ops/health.py` and
  `src/execution/manager.py` (this plan's actual files) are ruff-clean.

**3. [Process note, not a deviation] Local Python 3.13 provisioning**

- The execution sandbox had no `uv` and no Python 3.13 interpreter
  pre-installed (only a stray Python 3.14). Per the user's explicit
  mid-turn instruction to use `uv` for verification, `uv` was
  installed via `pip install uv` on the available interpreter, then
  `uv python install 3.13 --system-certs` (native TLS — the sandbox's
  outbound HTTPS terminates through a corporate proxy the bundled
  webpki roots don't trust) provisioned the pinned Python 3.13.15, and
  `uv sync --extra dev` installed the full project + dev dependency
  set. All verification commands in this plan ran through
  `uv run --python 3.13 ...` exactly as specified — no test framework
  substitution, no relaxed Python-version pin.

## Threat Mitigations Applied

| Threat ID | Mitigation | Test |
|-----------|------------|------|
| T-9-13 | Live credentials (no-withdrawal keys, IP allowlisting, encrypted off-source storage, paper/live separation) — code cannot prove exchange-side settings; operator attests at task 3 checkpoint (still BLOCKED) | N/A — human attestation pending |
| T-9-14 | `require_protective_confirmation` holds `ENTRY_WITHOUT_PROTECTIVE` and forces SAFE_MODE with never-auto-attach; sweeper stays cancel-only | `test_unconfirmed_sl_leg_yields_entry_without_protective_with_zero_rescue` |
| T-9-15 | Health-check payloads and Telegram-probe failures never carry `chat_id`, probe text, keys, secrets, tokens, or signatures — verified by a dedicated log-scan test | `test_telegram_delivery_probe_fails_on_exception`, `test_secret_free_log_scan_across_enablement_and_health_events` |
| T-9-16 | `expire_pending_entry` wires all five EXECUTION_SPEC section 4 cancel triggers with deterministic, idempotent cancel-by-ID | manual review of `_EXPIRY_TRIGGERS` vocabulary against EXECUTION_SPEC section 4 |

## Verification

```
uv run --python 3.13 pytest tests/test_execution_enablement.py tests/test_execution_health.py -q          → 14 passed
uv run --python 3.13 pytest tests/test_execution_attach.py tests/test_execution_manager.py \
  tests/test_execution_gates.py tests/test_execution_modes.py tests/test_execution_partials.py -q         → 29 passed
uv run --python 3.13 pytest tests/ -q                                                                     → full suite green
uv run --python 3.13 ruff check src/execution src/ops                                                     → 3 pre-existing findings in drills.py (deferred, out of scope); health.py/manager.py clean
uv run --python 3.13 mypy src/execution/manager.py src/ops/health.py                                      → Success: no issues found in 2 source files
```

Task 3 verification (testnet order ids, health-green attestation,
LIVE-TAP tap evidence) is `MISSING` by design per the plan's own
`<verify>` block for that task — it requires operator attestation, not
an automated command.

## Self-Check

- [x] Task 1 executed, tested, committed (RED + GREEN)
- [x] Task 2 executed, tested, committed (RED + GREEN)
- [x] Task 3 correctly recognized as `gate="blocking-human"` and NOT executed, NOT fabricated
- [x] 43 total new/updated tests pass (14 health/enablement + 29 attach/manager/gates/modes/partials)
- [x] Ruff clean on `src/ops/health.py` and `src/execution/manager.py`
- [x] mypy strict clean on both touched source modules
- [x] Full `tests/` suite green
- [x] No `float()` in execution-core placement math
- [x] No Binance SDK / python-telegram-bot / SQLAlchemy / Pydantic / Polars imports in `src/ops/health.py`
- [x] No Binance SDK imports in `src/execution/manager.py`
- [x] SUMMARY.md created documenting BLOCKED status

## Next Steps

**This plan cannot advance past task 3 without operator action.** The
operator must:

1. Perform the testnet round-trip (entry + SL + TP1 + TP2) and record
   the order ids + UTC timestamps.
2. State the RESEARCH A1 verdict (confirm or correct TP1-partial/TP2
   close-all semantics).
3. Provision live credentials (no-withdrawal, IP-allowlisted,
   encrypted off-source, paper/live separated) and confirm.
4. Perform a real APPROVE tap, a real SKIP tap, and an unknown-chat
   rejection against the 08-02 LIVE-TAP GATE.
5. Attest health-green across all ten probes.

Once the operator supplies this evidence, a fresh executor run
resumes at task 3, records the evidence lines in an updated SUMMARY,
and only then may `status` be marked `complete`.

## Self-Check: PASSED

All claimed files and commits verified present on disk / in git history.
