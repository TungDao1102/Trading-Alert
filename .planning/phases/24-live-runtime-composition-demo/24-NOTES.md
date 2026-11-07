# Phase 24 notes (carried from Phase 18)

Input for `/gsd-discuss-phase 24` and the planner (items 2 and 3 also matter to Phase 25). Not a decision record. Written 2026-10-18 from `.planning/phases/18-user-data-stream-error-taxonomy/18-VERIFICATION.md` (warnings 1 to 3, none of which changed the Phase 18 verdict).

## 1. The clock-drift guard is opt-in at the adapter: the composition root must pass it

- `BinanceUsdmAdapter(drift_guard=None)` is valid, and then `place_entry` is not blocked on clock drift (`src/adapters/binance_usdm.py`, `_require_entries_allowed`). The guard itself fails closed (never measured, failed measurement, out of limit, stale or a pending -1021 all block new entries), but nothing in `src` or `scripts` constructs a `ClockDriftGuard` today.
- Phase 24 builds the live adapter. It must construct the `ClockDriftGuard` from the ratified `drift.*` limits and pass it together with a clock, and schedule the periodic re-measure (`drift.periodic_remeasure_interval_seconds`).
- Acceptance test to write in Phase 24: the composition root's adapter has a non-None drift guard, and a never-measured guard blocks `place_entry` before any SDK call. A composition that leaves it `None` must fail a test, not pass silently.

## 2. The exact `/private` user-data URL form is unsettled

- The SDK builds the `/private` stream URL and the form (`/private/ws/<key>` against the `?listenKey=&events=` form) was never captured; the Demo smoke only proved delivery through the SDK. The project code does not build the URL itself (plan 18-19, a direct transport, was skipped by design because the gate said `transport: sdk`).
- Low risk while the SDK stays the transport. Re-check in Phase 25 (Demo campaign): capture the connection URL form once, and re-read the current official user-data-streams page, before any direct transport is considered.

## 3. The shared REST rate-limit gate does not cover every REST holder

- Phase 18 gave the signed adapter, the public market-data class, the listenKey port, the probe adapter and the supervisor one shared `RestRateLimitGate` (a 418 or 429 blocks all of them). Known holders that still do their own handling: the data jobs, the Phase 16 paper runtime and two scripts (the written-down known gap in `tests/test_phase18_gate.py`).
- Phase 24 composes the live process. Decide there, with a test, that every REST holder in the live process takes the same gate (or record why a holder is outside it, for example a read-only job that runs in a different process). A 418 ban from one holder must not be ignored by another in the same process.

## From Phase 19 (2026-10-20)

Source: `19-execution-plan-binding-price-check/` (19-11, 19-14, 19-15 and 19-16 SUMMARY files) and the Q5 draft `19-DEC-Q5-DRAFT.md`. Input for `/gsd-discuss-phase 24`. Not a decision record.

## 4. Nothing drives the protection coordinator or feeds it fills

- `ProtectionCoordinator` (`src/execution/protection.py`) is stepped only by tests and `scripts/demo_rehearsal.py`. In `src` no scheduler calls its step, and no code turns user-data stream fills into the coordinator's input. `execute_approved_plan` only registers a `RestingEntry` with `live_context.protection_registry`.
- Phase 24 composes it: build the registry and the coordinator, step them on a bounded cadence, feed them from the Phase 18 user-data router, and test that an entry fill leads to a REST-confirmed stop without any manual call. Until then a filled entry has no stop in any real process.

## 5. The alert sink and the closers must be real

- Pass a real `CriticalAlertSink` (Phase 20 builds it, Phase 23 words the messages) and the real `EmergencyCloser` into the coordinator. A composition that leaves the rehearsal sink in place sends nothing to the operator.
- No placement is ever re-sent (owner decision Q5, 2026-10-20). The composition must not add a retry wrapper around `place_entry`, `place_algo_protective` or `place_market_close`; the AST guards in `tests/test_execution_manager.py` and `tests/test_binance_usdm_source_guard.py` must stay green.
- `resolve_unresolved_intents` at startup (G4-029) now also meets the Q5 rule: an entry left `UNKNOWN` must not be closed as `REJECTED` only because a probe says not found. The closing rule is a Phase 20 decision.

## 6. Live constraint inputs decide whether any TP is ever placed

- `attach_protectives_to_fill` places TP1 and TP2 only if `snapshot_is_valid_for_live` holds. With real data margin type, leverage and equity have no source before Phases 21 and 22, so every TP placement is refused into `TP_UNAVAILABLE` (stop kept, SAFE_MODE, alert). The Demo rehearsal records this as a known gap (COMPLETE_WITH_GAPS, attestation item 1 NOT_OBSERVED). The live risk-input producer of criterion 1 (constraints, equity, daily loss, open algo count) is what removes it.

## From the Demo rehearsal of 2026-11-06 (owner decision 2026-11-07: deferred)

Source: the Phase 24 Demo rehearsal (evidence `09-DEMO-REHEARSAL-EVIDENCE-smoke-20261106T160307Z.json`, 21 of 21 steps PASSED). Not a decision record; no DECISIONS row is written until the owner takes it up.

## 7. UNTRACKED_SYSTEM_ORDER and SAFE_MODE when the owner closes a position by hand while TP1 still rests

- When the owner closes a position by hand (OPERATOR_CLOSE), the plan becomes CLOSE_REQUIRED. A TP1 order of that plan may still rest on the exchange. Reconcile sees an exchange order with a system client id and no open local intent, reports UNTRACKED_SYSTEM_ORDER and enters SAFE_MODE. The system fails closed; no money is at risk. The cost is a false alert and an owner `/safemode_exit`.
- Candidate rule (not adopted): in CLOSE_REQUIRED and CLOSE_FAILED, TP legs of that same plan (matched by client id prefix) may rest and are not UNTRACKED. It changes Phase 20 semantics and the pinned cases in `tests/test_reconcile_classify.py`, so it needs a new DECISIONS row (next free id D098) and tests for both directions: that plan's TP allowed, another plan's TP still reported.
- Owner decision 2026-11-07: leave the current behavior, record it here, decide after Phase 24. The normal path (SL or TP fills by themselves) is not affected.
