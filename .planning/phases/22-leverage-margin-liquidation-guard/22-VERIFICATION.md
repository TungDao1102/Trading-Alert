---
phase: 22-leverage-margin-liquidation-guard
verified: 2026-10-24T00:00:00Z
status: human_needed
score: 4/4 roadmap success criteria verified at library level (fakes, recorded Demo payloads, local PostgreSQL); 0 Demo-proven end to end; 0 behavior-unverified; 0 blocking gaps; 2 warnings
covered_files:
  - .planning/phases/22-leverage-margin-liquidation-guard/22-01-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-01-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-02-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-02-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-03-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-03-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-04-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-04-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-05-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-05-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-06-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-06-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-07-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-07-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-08-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-08-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-09-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-09-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-10-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-10-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-11-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-11-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-12-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-12-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-13-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-13-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-14-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-14-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-15-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-15-SUMMARY.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-16-PLAN.md
  - .planning/phases/22-leverage-margin-liquidation-guard/22-16-SUMMARY.md
  - config/execution/execution-limits-v1.toml
  - src/adapters/binance_usdm.py
  - src/db/alembic/versions/0012_reservation_margin.py
  - src/execution/bracket_cache.py
  - src/execution/execution_limits.py
  - src/execution/liquidation_watch.py
  - src/execution/live_context.py
  - src/execution/manager.py
  - src/execution/margin_guard.py
  - src/execution/protection.py
  - src/execution/symbol_config_guard.py
  - src/persistence/risk_reservations.py
  - src/risk/liquidation.py
  - src/risk/margin_check.py
  - tests/test_phase22_gate.py
covered_digest: "v3:sha256:2d912bf275dd62c63a835e05fbf70f232556383fdf67706022367494d23e5b77"
behavior_unverified: 0
overrides_applied: 0
gaps: []
deferred:
  - truth: "MarginGuard, SymbolConfigGuard, BracketCache and LiquidationWatch run inside a live process; liquidation_watch is passed to ProtectionCoordinator (EXEC-02 / D-12 active)"
    addressed_in: "Phase 24"
    evidence: "22-DEFERRED.md rows 1 and 2; grep of src, scripts and deploy finds no constructor call of the four classes outside their own modules and no `liquidation_watch=` argument; tests/test_phase22_gate.py pins both"
  - truth: "Approved-but-unplaced plans' margin is written (register_request with required_margin) so the claims part of criterion 3 works on real rows"
    addressed_in: "Phase 24"
    evidence: "22-DEFERRED.md row 3; grep of src and scripts finds no writer of required_margin outside the persistence layer that stores a given value; the gate pins it"
  - truth: "Demo and mainnet proof of the guard end to end, a short, a higher bracket tier, codes -4048 / -4046 / lower-bracket leverage"
    addressed_in: "Phases 24 to 26"
    evidence: "22-DEFERRED.md 'Owner-run Demo cases' and deferred rows; ROADMAP Phases 24 to 26"
human_verification:
  - test: "O-1: decide the target leverage (default 5 = D035 cap) and whether the system may change margin type / leverage of a symbol the owner also trades by hand"
    expected: "A DECISIONS row, or the built default left in place. BTCUSDT on the Demo account is now ISOLATED x5 (was CROSSED x20) and the probe does not restore it"
    why_human: "Owner-only (22-OWNER-DECISIONS.md O-1, OPEN); the verifier does not decide it"
  - test: "O-2: set margin.liquidation_buffer_bps and decide its home (execution-limits key vs registry parameter; RISK_MANAGEMENT section 9 still says registry parameter)"
    expected: "A DECISIONS row first, then the number with provenance DECISION. Until then MarginGuard and LiquidationWatch refuse to construct (ExecutionLimitsNotConfigured) and gate 2b refuses every placement"
    why_human: "Owner-only number; key is NOT_CONFIGURED in value and provenance"
  - test: "O-3: set margin.max_bracket_age_ms and margin.headroom_bps, and decide whether to flip AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED after reading 22-DEMO-RESULTS.md R-4 / R-5"
    expected: "DECISIONS row; the constant stays False until then, which can only over-refuse"
    why_human: "Owner-only numbers and an evidence-gated constant (two Demo samples on one host)"
  - test: "O-4: decide whether a failed post-fill liquidation check closes the position (D-12 default) or only alerts"
    expected: "Decision recorded; Phase 24 passes the LiquidationFailurePolicy when it composes the watch"
    why_human: "Owner-only; both policy members are built behind a required argument"
  - test: "Phase 24 pre-canary: run the composed guard (MarginGuard over a real adapter) against the Demo for one symbol, one short and one position above bracket 1"
    expected: "Criteria 1 to 3 observed through the guard, not through single requests; claims of a second approved plan counted from a real required_margin"
    why_human: "Needs a running composed process and exchange time; Phase 22 composes nothing"
---

# Phase 22: Leverage, Margin + Liquidation Guard Verification Report

**Phase Goal:** Before any entry, the system explicitly sets ISOLATED margin and leverage (at most 5x) per symbol. The order is refused unless the liquidation price lies beyond the SL with a buffer, and unless the available margin covers the new order plus other resting entries (D035).
**Verified:** 2026-10-24
**Status:** human_needed
**Re-verification:** No, initial verification

## Verdict in one paragraph

Phase 22 delivers what its documents claim, at the level they claim, and no further. The four roadmap criteria are implemented and exercised at library level (stateful fake SDKs, scripted ports, the real adapter over recorded Demo payloads, a local PostgreSQL). Nothing is composed into a running process, live placement is still disabled, no owner number was invented, and the two known gaps (nothing writes `required_margin`; `liquidation_watch` is inactive until Phase 24) are stated honestly in `22-DEFERRED.md`, `22-DEMO-RESULTS.md`, `RISK_MANAGEMENT.md` and are pinned by `tests/test_phase22_gate.py`. No blocker was found. Status is `human_needed` because O-1 to O-4 are OPEN by design, nothing is Demo-proven through the guard, and two warnings (below) deserve a decision.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Criterion 1: margin type and leverage are set and verified from `/fapi/v1/symbolConfig`; account defaults are never inherited | VERIFIED at library level (not Demo-proven through the guard) | `src/execution/symbol_config_guard.py`: one read; no-op when ISOLATED + target + `isAutoAddMargin` False; otherwise (flat symbol only) at most one `change_margin_type` and one `change_initial_leverage`, a failed margin POST stops the leverage POST, a POST answer never decides, ONE final read decides (`_matches(last)`), anything else is `MARGIN_CONFIG_UNVERIFIED` + alert reason. Adapter `change_margin_type` / `change_initial_leverage` (`binance_usdm.py` 1858 to 1915) go through `_sdk_call(CallKind.PLACEMENT)`, which "never retries, never sleeps" (877 to 906). Demo (`22-DEMO-RESULTS.md` R-1 to R-3) saw the requests individually on BTCUSDT; the guard itself was built after that run and has not run against Demo, and 22-DEMO-RESULTS says so |
| 2 | Criterion 2: liquidation check uses exchange brackets and maintenance margin, never hard-coded values; liquidation price strictly beyond the SL by a configured buffer | VERIFIED at library level (one long sample on one tier on Demo) | `src/risk/liquidation.py`: brackets are inputs (`Bracket`), tier chosen by the bracket containing `Q x LP`, strict `LP < stop - buffer` (long) / `LP > stop + buffer` (short), buffer = entry x bps / 10000, fail closed on empty, non-contiguous, stale or over-cap tables, leverage above the entry bracket, wallet <= 0, inverted stop. `BracketCache` reads `leverage_brackets_snapshot` with a bounded age, drops on any failure, rejects `notionalCoef` != 1. The gate test pins that the two pure modules hold no numeric literal other than 0, 1, 10000. Demo R-7 matched the formula only with the entry fee netted; `entry_fee_rate` is a required argument. No short, no higher tier observed (documented) |
| 3 | Criterion 3: available margin uses `availableBalance`, the new order's initial margin plus fees, other resting entries and approved-but-unplaced plans | VERIFIED at library level for the margin math, the reading checks and the PostgreSQL claims reader; the "approved-but-unplaced" input is PRESENT BUT INACTIVE (known gap 1) | `src/risk/margin_check.py`: need = initial margin + (entry+exit) fees + open loss of a marketable limit + other claims; required = need x (1 + headroom_bps/10000); equality passes. Stale / future-dated / hedge / multi-asset / quote-row mismatch readings are refused before any figure is used. `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` is `False`, so PLACED claims are counted on top of `availableBalance` (over-refuse only). A claim with unknown `required_margin` makes the sum unknown and the verdict `UNCERTAIN_ACCOUNT_STATE`. Migration 0012 adds three nullable columns with two named CHECKs and a real downgrade; `PgRiskReservationStore.list_margin_claims` reads them. Nothing in `src/` writes `required_margin` |
| 4 | Criterion 4: position mode is one-way single-asset only, any other mode is NO_TRADE | VERIFIED at library level | `MarginGuard.evaluate` step 0 takes one fresh account reading and refuses hedge (`HEDGE_MODE_UNSUPPORTED`) and multi-asset (`MARGIN_MODE_UNSUPPORTED`) BEFORE the configuration guard can POST anything; the manager's existing gate 5f (`get_position_mode`, hedge refused) sits right before gate 5f2. G3-001 closed in `docs/SOURCES.md` "Facts read for Phase 22" with the explicit statement that the page itself was cited from research and not re-fetched |

**Score:** 4/4 truths verified at library level; 0 Demo-proven through the guard; 0 behavior-unverified.

### Adversarial checks requested by the caller

| Check | Result | Evidence |
|-------|--------|----------|
| Criteria 1 to 3 not overstated as Demo-proven | PASS | `22-DEMO-RESULTS.md` "Still not Demo-proven" and `22-DEFERRED.md` criteria section say NOT Demo-proven for 1, 2, 3 and restrict criterion 4 to fakes and recorded payloads; `docs/trading/RISK_MANAGEMENT.md` repeats the claims-writer limitation. Requirements EXEC-01 and EXEC-02 stay Pending in `.planning/REQUIREMENTS.md`; RISK-01/02 untouched |
| No owner number invented; O-1..O-4 OPEN; margin.* NOT_CONFIGURED | PASS | `config/execution/execution-limits-v1.toml` lines 56 to 59 and 89 to 92: all three `margin.*` keys and their provenance are `"NOT_CONFIGURED"`; `ExecutionLimits` lists them as required, so `unset_keys()` is non-empty and gate 2b returns `LIMITS_NOT_CONFIGURED`. `MarginGuard`, `BracketCache`, `LiquidationWatch` raise `ExecutionLimitsNotConfigured` while unset. `22-OWNER-DECISIONS.md`: all four OPEN, "decided none". `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED = False` |
| Live placement still disabled | PASS | `enablement.guard_placement` (gate 2) precedes gate 5f2 in `manager.py` (743 to 751 vs 995); the margin guard, which may POST an account configuration, is therefore unreachable while `LIVE_ORDERS_DISABLED`, a limit is unset or SAFE_MODE is on. No Phase 22 change to `enablement.py` |
| At most one config POST per kind, never retried | PASS | See truth 1. In addition `evaluate` of the guard is called once per approval attempt; a refused approval is not consumed, so a later retry of the approval is a fresh run (D-03: "one call per guard run"). That is by design, not a retry inside a run |
| Fail-closed paths | PASS | Every port exception in `MarginGuard.evaluate` returns `UNCERTAIN_ACCOUNT_STATE` with no message kept; `BaseException` propagates; the manager wraps request construction, the call and the verdict type check in `except Exception` -> `UNCERTAIN_ACCOUNT_STATE`; `LivePlacementContext.margin_guard` is required (no None default); the freshness of the account reading and the bracket reading is re-judged after the last await |
| `RejectionReason` still 21 members | PASS | `len(RejectionReason) == 21` run in the project env; the gate asserts it and that no Phase 22 plain code is a member |
| `entry_fee_rate` really passed from the request, not 0 or a constant | PASS | `manager.py` 1014 to 1015 builds the request from `cost_rates.fee_rate_entry` / `fee_rate_exit` (the account-verified `CostRates`, gate 4a); `margin_guard.py` 376 passes `request.fee_rate_entry` to `liquidation_verdict` and 408 to 409 to `margin_verdict`; `tests/test_margin_guard.py::test_the_guard_passes_request_fee_rate_entry_to_the_liquidation_function` and `tests/test_execution_manager.py` line 4233 assert it. The watch takes the rate from an `EntryFeeRateSource` port (None or error skips only the calibration comparison, never the decision) and `tests/test_liquidation_watch.py` runs it with 0.0004 against the recorded sample |
| Nothing composed into a running process | PASS | grep over `src`, `scripts`, `deploy` for `MarginGuard(`, `SymbolConfigGuard(`, `BracketCache(`, `LiquidationWatch(`, `liquidation_watch=` finds nothing outside the defining modules; `scripts/demo_rehearsal.py` refuses with `MARGIN_GUARD_NOT_COMPOSED` without an injected guard (per 22-DEFERRED, pinned) |
| Honesty of known gap 1 (`required_margin` never written) | PASS | Stated first in `22-DEFERRED.md`, in `RISK_MANAGEMENT.md` section 9 and pinned by the gate. Effect is fail-closed: any other RESERVED or PLACED row reads as unknown margin -> `UNCERTAIN_ACCOUNT_STATE`. It can only over-refuse |
| Honesty of known gap 2 (`liquidation_watch` inactive) | PASS | `ProtectionCoordinator(..., liquidation_watch=None)` default; `_check_liquidation_once` returns False when None; `22-DEFERRED.md`, `22-OWNER-DECISIONS.md` O-4 and the gate say EXEC-02 / D-12 are not active before Phase 24 |

### Targeted test run (not the full suite)

`uv run pytest tests/test_phase22_gate.py tests/test_symbol_config_guard.py tests/test_margin_guard.py tests/test_liquidation_watch.py tests/test_bracket_cache.py tests/test_liquidation_price.py tests/test_margin_check.py tests/test_protection_liquidation.py tests/test_leverage_margin_adapter.py tests/test_snapshot_margin_leverage.py tests/test_phase22_fixtures.py` : all passed (no failure, no error). The full suite was run green by the caller and was not repeated.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/execution/symbol_config_guard.py` | criterion 1 guard | VERIFIED | 300 lines, substantive, used by `MarginGuard` through `ConfigGuardPort` |
| `src/execution/bracket_cache.py` | bounded-age brackets | VERIFIED | 195 lines, used through `BracketPort` |
| `src/execution/margin_guard.py` | fixed-order orchestrator | VERIFIED | 516 lines, awaited at gate 5f2 |
| `src/execution/liquidation_watch.py` | post-fill check | VERIFIED as a library; INACTIVE by design | hook in `protection.py` 1653 to 1743, default None |
| `src/risk/liquidation.py`, `src/risk/margin_check.py` | pure predicates | VERIFIED | exact `Fraction`/`Decimal`, no clock, no float |
| `src/adapters/binance_usdm.py` | 2 mutating + 3 read calls | VERIFIED | PLACEMENT kind, signed policy, gate |
| `src/db/alembic/versions/0012_reservation_margin.py` | margin columns | VERIFIED | nullable, 2 CHECKs, downgrade; head asserted by the gate |
| `config/execution/execution-limits-v1.toml` | 3 required keys | VERIFIED | NOT_CONFIGURED |
| `tests/test_phase22_gate.py` | structural gate | VERIFIED | 815 lines, passes |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `manager.execute_approved_plan` | `MarginGuard.evaluate` | gate 5f2 via `live_context.margin_guard` | WIRED | after gates 2, 2b, 3 and 5f, before hand-off record and consume; verdict type checked |
| gate 5f2 pass | `RestingEntry.plan_constraint_snapshot` | `dataclasses.replace` with verified margin type, leverage, equity | WIRED | in-memory only; persisted write-once row untouched (A8) |
| `MarginGuard` | `SymbolConfigGuard`, `BracketCache`, account source, claims reader | ports | WIRED in tests; NOT composed in any process (Phase 24) |
| `ProtectionCoordinator` | `LiquidationWatch` | `liquidation_watch` kwarg | HOOK PRESENT, NOT PASSED anywhere (Phase 24) |
| `PgRiskReservationStore.list_margin_claims` | `MarginGuard` claims | `ClaimsPort` | PRESENT; rows have NULL margin until Phase 24 writes it |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|----------|------|--------|-----------|--------|
| `MarginGuardRequest.fee_rate_entry/exit` | fee rates | `risk_kwargs["cost_rates"]` (account-max verified `CostRates`) | yes | FLOWING |
| `MarginGuardVerdict.leverage/margin_type/equity_used` | verified values | final `symbolConfig` read and the same fresh account reading | yes (in fakes) | FLOWING |
| `claims` | other plans' margin | `risk_reservations.required_margin` | no writer in Phase 22 | DISCONNECTED by design (known gap 1, fail closed) |

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| RISK-01 (sizing unchanged) | SATISFIED, unchanged | the guard judges the already-sized quantity at the already-snapped price; no sizing code touched; REQUIREMENTS stays Complete (Phase 5) |
| RISK-02 (fail closed on uncertain account/risk state) | SATISFIED at library level for the new gates | all Phase 22 uncertainty -> `UNCERTAIN_ACCOUNT_STATE` or a plain code |
| EXEC-01 | NOT COMPLETE, correctly left Pending | guard built and tested with fakes; no Demo proof of the guard in a process (Phases 24 to 26) |
| EXEC-02 | NOT COMPLETE, correctly left Pending | see observation 3 below |

Orphaned requirements: none. No requirement is marked complete by this phase and `REQUIREMENTS.md` was not edited.

### Anti-Patterns Found

None blocking. No `TBD` / `FIXME` / `XXX` in the Phase 22 modules. No float constructor, wall-clock call, or quote-asset literal (the gate checks these). The `except Exception` blocks are deliberate fail-closed and carry `noqa` notes.

## Warnings (not blockers)

### W1. The "at most 5x" cap is not enforced as an invariant in code (hardening)

`SymbolConfigGuard.__init__` only requires `target_leverage` to be an int >= 1 (`symbol_config_guard.py` 137 to 143). `TARGET_LEVERAGE = 5` is a constant that the composition is expected to pass, and `tests/test_symbol_config_guard.py` even builds a guard with a target of 3 but none with a target above 5. `MarginGuard` accepts whatever leverage the exchange confirms. The adapter docstring for `change_initial_leverage` says "the guard compares with the D035 cap and the bracket (D-02)"; the bracket comparison exists (`LEVERAGE_ABOVE_BRACKET`), the cap comparison does not. CONTEXT D-02 says the plan is "also refused when the leverage it would need exceeds the cap". Today nothing is composed and the default is 5, so no wrong behavior is reachable, and no roadmap sentence requires the cap to be a code invariant, hence this is a warning. But the goal text says "at most 5x", and a Phase 24 composition that passes `target_leverage=20` would silently defeat it.

**Fix:** in `SymbolConfigGuard.__init__` add `if target_leverage > TARGET_LEVERAGE: raise ValueError("target_leverage must not exceed the D035 cap")`, add a test `test_the_constructor_refuses_a_target_above_the_d035_cap` (6 and 20 raise, 1 to 5 pass), and correct the adapter docstring wording or point it at the constructor check. Optionally also refuse in `MarginGuard` when `cfg.leverage > TARGET_LEVERAGE`.

### W2. Bookkeeping: ROADMAP Phase 22 plan checkboxes and status line are stale

`.planning/ROADMAP.md` Phase 22 still reads "16 plans (planned 2026-10-23, not executed)" and every `22-NN-PLAN.md` line is `[ ]` (line 59 also `[ ]`), although all 16 plans have SUMMARYs and commits. This is the orchestrator's close-out step (STATE/ROADMAP were out of scope for this verification). It does not affect the goal.

**Fix:** after accepting this verification, mark the 16 plan lines and the Phase 22 line done through the normal GSD phase-complete step, with the "library level, not Demo-proven, Pending EXEC-01/02" wording preserved.

## Observations (for the owner, no action required by Phase 22)

1. A configuration POST can be sent for a plan that is later refused by the liquidation or margin check (config is step 1, by A7). The manager journals `MARGIN_CONFIG_CHANGED` best-effort; if the journal write fails the row is lost (deferred row "A spill..." in `22-DEFERRED.md`). Documented, not a defect.
2. `22-DEMO-RESULTS.md` R-4 and R-5 show `availableBalance` already netting a resting order on Demo (two samples, one host). The constant stays `False`; the guard over-refuses, never under-refuses. Flipping it is the owner's DECISIONS row (O-3).
3. `.planning/REQUIREMENTS.md` defines EXEC-02 as the reconciliation loop (compare orders/positions, sweep orphans, SAFE_MODE), while the ROADMAP maps Phase 22's post-fill liquidation watch to EXEC-02 and `22-DEFERRED.md` ties the watch to it. Phase 22 does not touch reconciliation. This is a pre-existing mapping mismatch between ROADMAP and REQUIREMENTS wording; Phase 22 neither resolves nor worsens it, and EXEC-02 correctly stays Pending. Suggest the owner clarify it when Phase 24 closes EXEC-01/02.
4. Formula evidence is a single Demo sample (long, tier 1, taker 0.0004). The short branch and tiers above 1 are proven against the official worked examples and the research goldens only.

## Human Verification Required

See the `human_verification` list in the frontmatter (O-1 to O-4 owner decisions, and the Phase 24 composed-guard Demo run). None of them can be decided or performed by the verifier.

## Gaps Summary

No blocking gaps. Phase 22 achieved its goal as a tested library plus one wired gate (5f2) that is unreachable while live placement is disabled; the activation, the claims writer, the post-fill watch composition and all Demo/mainnet proof of the guard are explicitly Phase 24 to 26 work and are recorded as deferred, not as done.

---

_Verified: 2026-10-24_
_Verifier: Claude (gsd-verifier)_
