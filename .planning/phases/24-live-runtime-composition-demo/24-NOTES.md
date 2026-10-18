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
