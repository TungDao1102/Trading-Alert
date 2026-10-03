---
phase: 12-fee-cost-model-correctness
verified: 2026-10-03T12:00:00Z
status: passed
score: 4/4 must-haves verified
covered_files:
  - .planning/phases/12-fee-cost-model-correctness/12-01-PLAN.md
  - .planning/phases/12-fee-cost-model-correctness/12-01-SUMMARY.md
  - .planning/phases/12-fee-cost-model-correctness/12-02-PLAN.md
  - .planning/phases/12-fee-cost-model-correctness/12-02-SUMMARY.md
  - .planning/phases/12-fee-cost-model-correctness/12-03-PLAN.md
  - .planning/phases/12-fee-cost-model-correctness/12-03-SUMMARY.md
  - .planning/phases/12-fee-cost-model-correctness/12-04-PLAN.md
  - .planning/phases/12-fee-cost-model-correctness/12-04-SUMMARY.md
  - .planning/phases/12-fee-cost-model-correctness/12-05-PLAN.md
  - .planning/phases/12-fee-cost-model-correctness/12-05-SUMMARY.md
  - .planning/phases/12-fee-cost-model-correctness/12-06-PLAN.md
  - .planning/phases/12-fee-cost-model-correctness/12-06-SUMMARY.md
  - .planning/phases/12-fee-cost-model-correctness/12-07-PLAN.md
  - .planning/phases/12-fee-cost-model-correctness/12-07-SUMMARY.md
  - .planning/phases/12-fee-cost-model-correctness/12-08-PLAN.md
  - .planning/phases/12-fee-cost-model-correctness/12-08-SUMMARY.md
  - .planning/phases/12-fee-cost-model-correctness/12-09-PLAN.md
  - .planning/phases/12-fee-cost-model-correctness/12-09-SUMMARY.md
  - .planning/phases/12-fee-cost-model-correctness/12-10-PLAN.md
  - .planning/phases/12-fee-cost-model-correctness/12-10-SUMMARY.md
  - .planning/phases/12-fee-cost-model-correctness/12-11-PLAN.md
  - .planning/phases/12-fee-cost-model-correctness/12-11-SUMMARY.md
  - src/adapters/binance_usdm.py
  - src/backtest/costs.py
  - src/backtest/simulator.py
  - src/domain/enums.py
  - src/domain/registry.py
  - src/execution/manager.py
  - src/paper/loop.py
  - src/risk/cost_guards.py
  - src/risk/cost_rates.py
  - src/risk/gating.py
  - src/risk/live_commission.py
  - src/risk/sizing.py
  - tests/test_commission_rates.py
  - tests/test_cost_parity.py
  - tests/test_risk_cost_guards.py
  - tests/test_sl_loss_property.py
covered_digest: "v2:sha256:6181dbd24d51a31f09a59f8a7b83bb38664488cff8b89fb92bc8c09335c5866c"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: passed
  previous_score: 4/4
  gaps_closed: []
  gaps_remaining: []
  regressions: []
---

# Phase 12: Fee + Cost Model Correctness Verification Report

**Phase Goal:** Every mode (backtest, paper, live) sizes and books trades with costs in quote currency, so a stop-loss exit never loses more than `risk_rate` plus bounded slippage. Live uses the account's real commission rate.
**Verified:** 2026-10-03
**Status:** passed (with warnings, none of which defeats a success criterion)
**Re-verification:** Yes, after Phase 13, 13.1 and 17 changed related code (costs.py hash helper moved, manager.py gained SL write-ahead and approval consumption, repo-wide ruff reflow)

## Goal Achievement

### Observable Truths (ROADMAP success criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Cost per unit = entry x fee_entry + SL x (fee_exit + exit_slippage), quote per unit; a property test asserts loss at SL <= risk budget across price and stop-width grid, including low-price XRP | VERIFIED | `src/risk/cost_rates.py:88-117` `per_unit_round_trip_cost` is linear in price, Decimal-only, prices validated > 0. It also includes the entry slippage term (stricter than the roadmap sketch, per D-01). `src/risk/gating.py:96-108` calls it from the adverse zone edge (LONG entry_max, SHORT entry_min) and passes the result into `size_position`. `tests/test_sl_loss_property.py` has 60 grid points (BTC 60000, ETH 3000, XRP 0.5 x 5 widths x 2 sides x 2 equities) and 5 fill fractions across the zone. Loss is computed with literal Decimal rates that never call project code, with tolerance 0. A mutation check feeds the OLD formula and confirms violations on BTC and XRP, and a vacuity guard confirms the harness fails when it is fed correct quantities. All pass. |
| 2 | Backtest slippage is multiplied by price; a minimum stop distance and a cost-to-risk ceiling produce NO_TRADE | VERIFIED | `src/backtest/simulator.py:684-689` books `price x quantity x rate` per leg. The exit leg uses `exit_slippage_rate` for SL and EOD, and `expected_slippage` for TP1. A missing `exit_slippage_rate` raises. `src/risk/gating.py:127-154` runs the STOP_TOO_TIGHT and COST_TO_RISK_EXCEEDED guards before `quantize`, and returns NO_TRADE. `tests/test_sl_loss_property.py` covers the guard regions: widths 0.1-0.29% give STOP_TOO_TIGHT, 0.4-0.7% give COST_TO_RISK_EXCEEDED, 0.8% passes. Both codes are in the 20-code `RejectionReason` (12-01). |
| 3 | Live reads GET /fapi/v1/commissionRate per symbol, uses max(parameter, account), never falls back to zero; backtest stays on versioned fees | VERIFIED (read and resolver layers; runtime wiring is Phase 24 by design) | Adapter `user_commission_rate(symbol)` at `src/adapters/binance_usdm.py:1268-1304` with strict parse: missing, non-decimal, non-finite, negative, above 0.01 or wrong-symbol raises, never returns zero. `resolve_live_cost_rates` (`src/risk/live_commission.py:118-162`) returns per-side `max(parameter, account taker)`, `fee_source=ACCOUNT_MAX`, and returns NO_TRADE `UNCERTAIN_ACCOUNT_STATE` with no rates for a missing, wrong-symbol, stale or future-dated commission. `src/execution/manager.py:426-447` refuses PARAMETER-sourced rates for a real order. `cost_rates_from_model` (`src/backtest/costs.py:290-309`) keeps backtest and paper on versioned parameter fees (PARAMETER) and refuses legacy 7-key models. `tests/test_commission_rates.py` covers max rule, TTL boundary, zero account rate, and fail-closed cases. |
| 4 | Golden fixtures and experiment hashes are regenerated deliberately and recorded in a DECISIONS entry; Phase-5 fixtures no longer use hand-typed costs | VERIFIED | `docs/DECISIONS.md` has D046 (design), D047 (canonical cost-hash text), and D048 (inventory of every moved fixture, pin and hash, and what deliberately did not move). All eleven `tests/fixtures/phase5/*/input.json` now carry `cost_rates`, not `modeled_costs_per_unit`. Expected values are hand-derived in `tests/fixtures/phase5/DERIVATIONS.md`. I re-derived happy_path_long: 50100x0.0006 + 49000x0.0008 = 69.26; risk_per_unit 1169.26; qty 0.042; realized_risk 49.10892 (matches `expected.json`). Phase 6 fixtures are regenerated by `scripts/gen_phase6_fixtures.py`, with geometry guarded by `tests/test_phase6_fixture_geometry.py`. |

**Score:** 4/4 truths verified, 0 behavior-unverified. The behavior-dependent invariants (SL loss within budget, fail-closed commission, guards before quantization) each have an exercising test that passes.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/risk/cost_rates.py` | `CostRates`, `per_unit_round_trip_cost` | VERIFIED | Substantive, wired into `gating.py` and `backtest/costs.py` |
| `src/risk/cost_guards.py` | Guard checks and validation | VERIFIED | Wired into `size_and_quantize` |
| `src/risk/gating.py` | Shared pipeline with adverse-edge sizing, guards, cost trail | VERIFIED | Used by simulator, paper loop and manager |
| `src/risk/live_commission.py` | Live resolver, fail-closed | VERIFIED | Tested. No production caller yet (Phase 24 wiring by design) |
| `src/adapters/binance_usdm.py` `user_commission_rate` | Strict adapter read | VERIFIED | Matches installed SDK signature (per review) |
| `src/backtest/simulator.py` `_apply_costs` | Per-leg price x qty x rate | VERIFIED | Line 684-689 |
| `src/backtest/costs.py` | 8-key cost identity, canonical hash, price-aware helper delegating to shared producer | VERIFIED | `modeled_costs_per_unit` delegates to `per_unit_round_trip_cost` |
| `params/*/baseline-v5.toml` and no-trade-v3 / simple-trend-v3 | New versioned sets with `exit_slippage_rate`, guards, TTL | VERIFIED | The three families' v5 sets carry `exit_slippage_rate` 0.0003, `min_stop_distance_rate` 0.003, `max_cost_to_risk` 0.15, `commission_rate_ttl_seconds` 3600 |
| `docs/DECISIONS.md` D046-D048, `docs/SOURCES.md` commissionRate row | Records | VERIFIED | Present. SOURCES notes the official page was not read directly (MEDIUM confidence), Demo behavior unverified until Phase 24 |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| `simulator.run` | `evaluate_risk` | `cost_rates_from_model` + `guard_rates_from_params` (lines 838-858) | WIRED |
| `paper/loop.py` | `evaluate_risk` | same helpers | WIRED (shared-path parity tested in `tests/test_cost_parity.py`) |
| `evaluate_risk` | producer and guards | `size_and_quantize` (gating.py:96-154) | WIRED |
| `execution.manager` | `evaluate_risk` | Gate 4a then 4b | WIRED (label check only, see WR-01) |
| `resolve_live_cost_rates` | production runtime | none yet | Intentionally unwired (Phase 24) |

### Data-Flow Trace (Level 4)

Cost values flow from registry params (or fixture cost dict) through `cost_rates_from_model` into `per_unit_round_trip_cost`, then `SizedResult.modeled_costs_per_unit`, then `TradeRecord` and `_apply_costs`. There are no static returns or hardcoded literals in the chain. FLOWING.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Key phase tests (re-run 2026-10-03) | `.venv/Scripts/python -m pytest tests/test_sl_loss_property.py tests/test_cost_parity.py tests/test_risk_cost_guards.py tests/test_commission_rates.py` | 153 passed | PASS |
| Full suite, run once (`-m "not pg"`, `tests/test_deploy_docs.py` deselected) | `.venv/Scripts/python -m pytest -q -m "not pg"` | Only failure is `tests/test_docker_cutover.py::test_the_reported_oi_gap_is_the_engineered_forty_five_minutes` (Phase 13.1 Docker cutover proof, environment-dependent, exit_code 3). `tests/test_deploy_docs.py::test_refresh_pins_lookup_is_read_only_and_reports_moves` also fails (Phase 13.1 pin refresh, needs network/Docker). No Phase 12 test fails | PASS for Phase 12 (2 unrelated 13.1 environment failures) |
| mypy on `src/risk`, `src/backtest/costs.py`, `simulator.py`, `execution/manager.py`, `adapters/binance_usdm.py` | `python -m mypy ...` | no issues in 13 files | PASS |
| ruff on `src` and `tests` | `ruff check src tests` | All checks passed (the earlier F841 in `portfolio.py` is gone) | PASS |

### Probe Execution

No probe scripts are declared for this phase. Skipped.

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| RISK-01 | 12-01, 02, 03, 05, 06, 07, 08, 09, 10, 11 | Sizes from equity x risk-rate / SL distance including modeled costs; identical logic backtest/paper/live | SATISFIED | One shared pipeline (`size_and_quantize`), parity test, SL-loss property |
| BKTS-01 | 12-04, 09, 10, 11 | Backtest applies fees/funding/slippage before selection | SATISFIED for fee and slippage (funding is Phase 14 by design) | `_apply_costs` per-leg booking, regenerated Phase 6 fixtures |
| DOMN-02 | 12-02, 03, 11 | Traceable to immutable versioned parameter set | SATISFIED | v5 sets are new files, old sets byte-identical, pins added, hashes recorded (D047/D048), binding gate |

All three IDs in PLAN frontmatter appear in REQUIREMENTS.md (lines 26, 38, 45). I found no ORPHANED phase-12 requirements.

### Anti-Patterns Found

No TBD, FIXME or XXX markers in the phase-touched risk and backtest cost modules. The two ruff F841 findings in `src/risk/portfolio.py` are not a phase-12 change.

### Re-verification Note (Phase 13 / 13.1 / 17 drift)

Commits since 2026-09-30 touching phase-12 files: `costs.py` (canonical decimal helper moved to `src/domain/canonical.py`, `_canonical_decimal_text` alias kept, hash pins unchanged), `simulator.py`/`registry.py`/`paper/loop.py` (ruff reflow only), `execution/manager.py` (Phase 17 write-ahead intent and approval consumption), `domain/enums.py` (Phase 17). `gating.py`, `cost_rates.py`, `cost_guards.py`, `live_commission.py`, `sizing.py` and the adapter are unchanged. Re-checked: simulator `_apply_costs` still books price x quantity x rate per leg with `exit_slippage_rate` for SL/EOD and raises when it is missing (lines 640-690); `manager._live_cost_rates_are_verified` now checks `fee_source == ACCOUNT_MAX`, `account_symbol == candidate_symbol`, and `observed_at <= now <= expires_at` and `execute_approved_plan` requires a `CostRates` (lines 317-335, 556-570). That closes WR-01 (label-only trust) in code. All four success criteria still hold; the Phase 12 goal is intact.

### Review Findings Weighed (12-REVIEW.md: 0 critical, 5 warning, 6 info)

None of the findings defeats a success criterion. They are WARNINGS, recommended for closing before Phase 24 wires live.

- **WR-01 (manager trusts the `fee_source` label):** originally confirmed; now MITIGATED by Phase 17 (`manager.py:317-335` verifies symbol and freshness window, see re-verification note). Original finding text follows. `CostRates` is a public dataclass, so a mistaken or hostile caller could label parameter fees `ACCOUNT_MAX`. It also does not re-check freshness or symbol at placement time. SC3 asks that live "reads commissionRate per symbol, uses max, never falls back to zero". Those properties hold in the adapter and resolver, both tested, and no production caller exists until Phase 24, which is named in the roadmap as the wiring phase. WARNING: harden in Phase 24 (Option A or B from the review).
- **WR-02 (no plan-geometry validation, `abs()` masks inverted plans):** CONFIRMED as defense-in-depth. The planner builds the plans. It does not affect the property proven for well-formed plans. WARNING.
- **WR-03 (`run()` and `run_paper_tick` do not assert cost-model to registry binding):** CONFIRMED. Binding is enforced at `experiment.assemble` and `paper.freeze.pin_stream_epoch`, so the recorded experiment and stream identity are guarded. Direct `run()` use with a mismatched fixture is not. "Backtest stays on versioned fees" holds at the experiment boundary. WARNING.
- **WR-04 and WR-05 (NaN/Infinity and exception type in registry and guard validators):** not reachable from the TOML registry for the tested paths. Hardening. WARNING.
- **IN-01 to IN-06:** informational. IN-06 notes `min_stop_distance_rate` 0.003 is never the binding guard because the 0.15 ceiling implies a minimum stop of about 0.79% (this is documented in D046 item 6).

### Non-blocking Decision Pending (not a verification gap)

- **D046 item 6, ratification of `max_cost_to_risk` 0.15:** the ceiling is the binding gate (about 0.79% minimum stop) and biases toward NO_TRADE on tighter stops. It was implemented as locked and frozen by the v5 pins. Changing it means new v6 sets and a user decision, never a tune after results. It is non-blocking by design and is listed here so it is not lost.
- **Binance Demo/testnet behavior of `commissionRate`:** unverified, deferred to Phase 24 by design. The official docs page was not read directly (SOURCES.md, MEDIUM confidence). Re-confirm before Phase 24.

### Human Verification Required

None required for the phase goal.

### Gaps Summary

No gaps. All four ROADMAP success criteria are backed by code and by passing tests that exercise the behavior, not just its presence. The full suite passes. The main residual risk is the live-path hardening in WR-01, which is safe to defer only because live runtime wiring does not exist yet (Phase 24).

---

_Verified: 2026-10-03_
_Verifier: Claude (gsd-verifier)_
