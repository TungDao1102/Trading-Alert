# Phase 12: Fee + Cost Model Correctness - Research

**Researched:** 2026-09-30
**Domain:** Deterministic position sizing / cost model in quote-per-unit, Decimal arithmetic, registry versioning, Binance `commissionRate` read
**Confidence:** HIGH for in-repo mapping and formula feasibility; MEDIUM for the `commissionRate` endpoint (official page reached only through search summary plus change log plus installed SDK); LOW for Binance Demo behavior (not documented in any page retrieved)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### Cost-per-unit formula and sizing (F-001, F-801, F-962)
- **D-01:** `modeled_costs_per_unit` becomes price-aware. It takes the entry reference price, the stop price, the side and the cost model, and returns **quote per unit of base**:
  `entry_ref × (fee_rate_entry + entry_slippage_rate) + stop_price × (fee_rate_exit + exit_slippage_rate)`.
  Entry is a taker fill (D036), so the entry slippage term is included; this is stricter than the roadmap sketch and is the conservative reading of F-962. Fix the docstring, which currently claims quote currency while returning a rate sum. Its unit must scale linearly with price (contract test, F-801). — **Reversibility:** costly — sizing, gating, backtest, paper and execution all consume the producer.
- **D-02:** `size_position` keeps `risk_per_unit = sl_distance + modeled_costs_per_unit`; the fix is in the producer and its callers (`src/backtest/simulator.py:803`, `src/paper/loop.py:504`, `src/risk/gating.py`), not in a second formula. The same function is called in backtest, paper and live (Phase 5 D-02 parity).
- **D-03:** Use the **adverse edge of the entry zone** (LONG: `entry_max`; SHORT: `entry_min`) for the entry price and the SL distance, replacing the zone-mid `entry_ref` of Phase 5 D-02. Reason: the roadmap invariant "loss at SL ≤ risk budget" must hold for a fill anywhere in the zone, and zone-mid under-sizes when the fill lands on the adverse edge. The planner must confirm this against `src/risk/gating.py` and the quantizer's `reference_price`, and record the supersession of the zone-mid rule in DECISIONS. — **Reversibility:** one-way — changes every sized quantity and every golden fixture; the DECISIONS entry pins it.
- **D-04:** All fee and slippage rates are decimal fractions. The loader rejects any fee or slippage rate above `0.01` as a unit error (F-028). The protocol wording that says "basis points" cannot be edited in place (v1.1.0 is frozen); if it needs a bump, record it as a follow-up.

### Slippage model (F-306)
- **D-05:** Simulated PnL books slippage per leg as `fill_price × quantity × rate` (currently `quantity × rate`, which is 60,000× too small on BTC). Entry uses `expected_slippage`; the stop exit uses a **separate `exit_slippage_rate`** because a stop-market fills worse than a limit. Take-profit exits use `expected_slippage`. — **Reversibility:** costly — changes realized PnL in every trade record and the experiment hash inputs.
- **D-06:** New parameter `exit_slippage_rate`, baseline **0.0003 (3 bps)**, within the audit's 2–5 bps range for stop exits. The planner checks that value against the protocol's stress convention before freezing it, and never tunes it after seeing results.

### Guards: minimum stop distance and cost-to-risk ceiling (F-002)
- **D-07:** Two registry parameters, both risk gates that produce NO_TRADE before quantization:
  - `min_stop_distance_rate` (SL distance ÷ entry ref), baseline **0.003 (0.3%)**;
  - `max_cost_to_risk` (round-trip modeled cost ÷ `risk_per_unit`), baseline **0.15** (audit F-002 research baseline).
  The computed ratio is recorded on the sizing result.
- **D-08:** Two new canonical rejection codes, `STOP_TOO_TIGHT` and `COST_TO_RISK_EXCEEDED`, added to GLOSSARY §9 first (D016: GLOSSARY is the enum source), then to `RejectionReason` and the rejection-code tests. No synonym of an existing code. Phase 11 already reserved `INSUFFICIENT_MARGIN`; do not touch it.
- **D-09:** D044 follow-up 1 lands here: remove the five deprecated `RejectionReason` aliases and update `tests/test_domain_enums.py` in the same change as D-08, so the enum has one edit window.

### Live commission rate (F-962, F-031)
- **D-10:** Live reads `GET /fapi/v1/commissionRate` per symbol through the adapter layer (SDK models never leak). Sizing uses `max(parameter_rate, account_rate)` **per side** (entry uses taker per D036, stop exit uses taker). The BNB discount is ignored in sizing (F-031).
- **D-11:** If the account rate is unavailable, stale beyond a TTL, or malformed, live entries **fail closed** (NO_TRADE with the existing account-state-uncertain reason). It never falls back to zero, and it does not silently fall back to the parameter rate either: the parameter rate is a floor, not a substitute for an unknown account state. The TTL is a registry parameter; the planner picks a baseline (suggest 1 hour) and documents it.
- **D-12:** Backtest and paper keep the **versioned parameter fees** so runs are reproducible from the parameter-set hash. Only live substitutes the account rate. The rates actually used, and their source (`PARAMETER` vs `ACCOUNT_MAX`), are recorded on the sizing result and journal input (not on the frozen Phase-4 `TradePlan`, to avoid changing plan identity).
- **D-13:** Exact endpoint path, weight, response fields and demo/testnet behavior are re-verified against current official Binance docs before implementation (AGENTS.md exchange-authority rule); the researcher records the source URL and fetch date in `docs/SOURCES.md`. This phase adds the adapter method plus fixture-driven tests only. Runtime wiring (scheduler, cache refresh loop) belongs to Phase 24.

### Parameter sets, hashes, fixtures (F-608, D044 follow-up 2)
- **D-14:** Never edit an existing `params/**/*.toml` (F-810). Create the next versioned sets (`baseline-v5` for the three families, plus matching no-trade and simple-trend successors) carrying `exit_slippage_rate`, `min_stop_distance_rate`, `max_cost_to_risk` and the commission TTL, with headers naming what they supersede. Old sets stay byte-identical and hash-locked. If extending `COST_KEYS` would change old sets' hashes or make old sets unloadable, the loader treats the new keys as required only for the new strategy_version, and the planner records the decision.
- **D-15:** Fix the hash-spelling trap (`partial_fill_fraction` `1` vs `1.0` hashing differently, D044 follow-up 2): canonicalize numeric cost values to a single Decimal string form before hashing. This changes cost hashes, so it gets its own DECISIONS entry and is done in the same window as the deliberate regeneration below, never silently.
- **D-16:** Golden fixtures and experiment hashes are regenerated **deliberately**: one DECISIONS entry lists every fixture and hash that moved and why (F-608). Phase-5 fixtures stop using hand-typed cost values (`"1.0"`/`"0.0"`) and instead feed values produced by the corrected producer, with expected outputs hand-derived in a comment or sidecar file rather than emitted by the code under test.

### Verification (F-601)
- **D-17:** Property test (explicit Decimal grid; the planner checks whether `hypothesis` is already a dev dependency and does not add one without cause): across prices (BTC ~60,000, ETH ~3,000, XRP ~0.5), stop widths (0.3%–3%), both sides and fill positions across the entry zone, the simulated SL-exit loss including fees and slippage is `<= allowed_risk` plus a stated Decimal tolerance. Includes the low-price XRP case.
- **D-18:** Hand-computed oracle tests for the producer and for `_apply_costs` at a fixed BTC and a fixed XRP case, so the property test is not the only guard. A contract test asserts linear price scaling. The test that recomputes the same buggy formula (`tests/test_backtest_simulator.py` Test 11) is replaced, not kept.
- **D-19:** Parity: backtest, paper and the risk pipeline call one shared producer; a test asserts identical output for identical inputs across the three call sites.

### Claude's Discretion
- File and function names for the new guard module, provided guards run inside the existing `evaluate_risk` pipeline before quantization.
- Exact baseline value for the commission TTL, subject to D-11.
- Whether the property test is one module or split by unit/integration.
- Test fixture folder layout for the regenerated goldens.

### Deferred Ideas (OUT OF SCOPE)
- Funding cost in sizing and PnL: Phase 14 (F-905, F-021).
- Mark-price trigger evaluation and causal fills: Phases 13–14.
- Commission cache refresh loop and scheduler wiring: Phase 24.
- Generalizing the quote asset and USDC fee tiers: Phase 27.
- Protocol wording change from "basis points" to "decimal fraction" if it needs a v1.2.0 bump: follow-up, not an in-place edit of v1.1.0.

None of the pending todos matched this phase.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RISK-01 | Size from equity × risk-rate ÷ SL-distance including modeled costs, floor to stepSize, reject below utilization/minimums, identical logic in backtest/paper/live | One shared quote-per-unit producer (section "Pattern 1"), adverse-edge entry proven worst-case (section "D-03 feasibility"), guards before quantization, SL-loss property test (Validation Architecture) |
| BKTS-01 | Simulator applies fees/funding/slippage before any selection decision | `_apply_costs` slippage fix (price × qty × rate per leg), separate `exit_slippage_rate` for SL exits, fixtures regenerated (section "Fixture and hash inventory") |
| DOMN-02 | Every backtest/paper/alert/order plan traceable to an immutable versioned parameter set | New `baseline-v5` sets, old sets byte-locked (PA-02/PA-03), pin file + PA gates extended, hash canonicalization D-15 confined to `cost_model_hash` (does not touch `parameter_set_hash`) |
</phase_requirements>

## Summary

The bug is confirmed in the current code: `modeled_costs_per_unit` returns `fee_rate_entry + fee_rate_exit + expected_slippage` (a dimensionless rate), `size_position` adds it to a quote-currency distance, and `_apply_costs` books slippage as `quantity × rate` with no price factor. Every consumer is small and enumerable: two src call sites of the producer (`src/backtest/simulator.py:803`, `src/paper/loop.py:504`), one shared pipeline (`src/risk/gating.py:evaluate_risk`), and the live manager (`src/execution/manager.py:418`) which passes caller-built `risk_kwargs` straight into `evaluate_risk`. The fix is a producer with signature `(entry_price, stop_price, rates)` computed **inside** `evaluate_risk` so the entry/stop used for the cost and for `sl_distance` cannot diverge across the three modes.

The adverse-edge decision (D-03) is feasible and provably worst-case: for LONG the loss at SL for a fill at `p` is `p(1+c_e) − S(1−c_x)`, increasing in `p`, maximal at `entry_max`; for SHORT it is `S(1+c_x) − p(1−c_e)`, decreasing in `p`, maximal at `entry_min`. With the D-05 booking rule (fees and slippage as `fill × qty × rate`, SL exit priced exactly at `stop_loss_price` by `resolve_intrabar`), the simulated SL loss equals `qty × risk_per_unit` exactly, so the property test tolerance can be effectively zero and `qty` floored to `quantity_step_size` guarantees `loss <= allowed_risk`. Two things D-03 leaves open and this research resolves by recommendation: (1) live places its LIMIT at the zone **mid** (`derive_limit_price`) and the simulator fills at the zone **mid**, so adverse-edge sizing is a deliberately conservative bound, not the actual fill; (2) the quantizer's `reference_price` (min-notional gate) should stay at zone-mid because that is the price the order is actually placed at.

Three consequences of the locked numbers the planner must not miss. First, with 5 bps taker in + 5 bps taker out + 1 bps entry slippage + 3 bps exit slippage (14 bps round trip), `max_cost_to_risk = 0.15` is equivalent to a minimum stop distance of about **0.79%** of price, so the 0.3% `min_stop_distance_rate` is dominated and the cost ceiling is the binding gate (computed below). Second, every existing simulator/paper fixture has a stop only **~0.064%** from entry (entry 121.5, SL 121.422), so all of them become `STOP_TOO_TIGHT`; the fixture generator's candle geometry must be rescaled, not just re-blessed. Third, `hypothesis` is not installed (dev extras are pytest, pytest-asyncio, respx, ruff, mypy); use an explicit Decimal grid as D-17 already says.

**Primary recommendation:** Put one pure `per_unit_round_trip_cost(entry_price, stop_price, rates)` in `src/risk/` (no backtest import), have `src/backtest/costs.py::modeled_costs_per_unit` delegate to it, change `evaluate_risk` to take `cost_rates` plus the two guard rates as explicit required kwargs (replacing the pre-computed `modeled_costs_per_unit`), size at the adverse edge, keep the notional gate on zone-mid, add `exit_slippage_rate` as an optional-until-v5 cost key selected by presence, and enforce the new registry keys via the v5 sets, consumers and a new PA gate.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Per-unit cost producer, sizing, guards, quantization | Pure core (`src/risk/`) | — | Stdlib + Decimal only; identical function in backtest/paper/live (Phase 5 D-02 parity); no SDK, clock, or env |
| Cost model value object + hash | Pure core (`src/backtest/costs.py`) | Registry (`src/domain/registry.py`) | Registry owns parameter identity; `CostModel` owns cost identity (`cost_model_hash`) |
| Simulated PnL booking (`_apply_costs`) | Backtest simulator (`src/backtest/simulator.py`) | — | Keep edits localized to cost math; Phase 14 rewrites the simulator |
| Live `commissionRate` read | Adapter edge (`src/adapters/binance_usdm.py`) | Pure core (rate resolution) | SDK models must not leak; adapter returns a frozen project dataclass with no clock; caller stamps `observed_at_utc` |
| Account-rate resolution `max(param, account)`, staleness, fail-closed | Pure core (`src/risk/`) | Execution manager (caller) | Pure and unit-testable; manager supplies snapshot + `now_utc` (one clock) |
| Commission cache refresh loop / scheduler | Execution runtime (Phase 24) | — | Explicitly out of scope (D-13) |
| Parameter sets, hash locks, pin file | Registry files (`params/`) + `tests/fixtures/phase4/parameters.json` | Gate scripts (`scripts/decision_alignment/`) | Versioned, never edited in place (F-810) |
| Rejection-code vocabulary | Docs (`docs/GLOSSARY.md` §9) → `src/domain/enums.py` | GL gates (`scripts/decision_alignment/bookkeeping.py`) | D016: GLOSSARY is the enum source |

## Standard Stack

No new runtime dependency. Everything is stdlib `decimal` via the existing pinned helpers plus the already-installed SDK.

### Core (existing, verified in this session)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `src/core/_decimal.py` (`_add/_sub/_mul/_div`) | in-repo, prec 28 | All new money math | `_PREC = 28`, pinned `localcontext`; determinism rule [VERIFIED: src/core/_decimal.py:19-59] |
| `binance-sdk-derivatives-trading-usds-futures` | 17.4.0 installed (pin `>=17.3,<18`) | `rest_api.user_commission_rate(symbol, recv_window)` | Official connector behind the adapter [VERIFIED: `importlib.metadata.version` printed `17.4.0`; method read at `.venv/Lib/site-packages/binance_sdk_derivatives_trading_usds_futures/rest_api/api/account_api.py:1035-1080`] |
| pytest 9 / pytest-asyncio (auto) / respx | per `pyproject.toml` `[project.optional-dependencies].dev` | Tests | Existing; fake-REST pattern in `tests/test_adapter_strictness.py` [VERIFIED: pyproject.toml lines 34-42] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Explicit Decimal grid | `hypothesis` | Not installed (`importlib.util.find_spec("hypothesis")` returned `None`; absent from `pyproject.toml` and `uv.lock`). D-17 says do not add without cause; a deterministic grid is also byte-reproducible (project determinism rule). Do not add. |

**Installation:** none.

**Version verification:** No package added, so no registry check needed. SDK method and response model were read from the installed 17.4.0 files, not from memory.

## Package Legitimacy Audit

No external packages are installed by this phase. `slopcheck`/registry checks not applicable.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                     params/<family>/baseline-v5.toml  (registry, hash-locked)
                                   |
                       load_parameter_set()  -> ParameterSet.params
                                   |
         +-------------------------+---------------------------+
         |                         |                           |
   build_cost_model(slice)   min_stop_distance_rate     commission_rate_ttl_seconds
   -> CostModel(8 keys,      max_cost_to_risk           (live only)
      cost_model_hash)             |                           |
         |                         |                 GET /fapi/v1/commissionRate
   CostRates (PARAMETER)           |                 (adapter, per symbol, no clock)
         |                         |                           |
         |                         |             AccountCommission(observed_at stamped by caller)
         |                         |                           |
         +-----------+-------------+------------- resolve_cost_rates(mode) ------+
                     |                                    LIVE: max(param, account) per side,
                     |                                    stale/None/malformed -> UNCERTAIN_ACCOUNT_STATE
                     v
   TradePlan (frozen; entry_min/entry_max/stop) --> evaluate_risk(cost_rates, guards, ...)
                     |
        sizing_entry = LONG: entry_max | SHORT: entry_min          (adverse edge, D-03)
        costs = per_unit_round_trip_cost(sizing_entry, stop, rates) (ONE producer, D-19)
                     |
        size_position(entry_ref=sizing_entry, modeled_costs_per_unit=costs)
                     |  (sl_distance <= 0 -> EXCHANGE_CONSTRAINT, unchanged)
        guard 1: sl_distance / sizing_entry < min_stop_distance_rate -> STOP_TOO_TIGHT
        guard 2: costs / risk_per_unit      > max_cost_to_risk       -> COST_TO_RISK_EXCEEDED
                     |
        quantize(reference_price = zone-mid, risk_per_unit)  -> MIN_QTY / NOTIONAL / UTILIZATION
                     |
        check_portfolio -> PortfolioVerdict
                     |
   +-----------------+------------------+
   |                 |                  |
 simulator.run   paper loop         execution manager (live)
   |
 _resolve_entry (fill = zone mid, unchanged) -> resolve_intrabar (SL exits at stop_loss_price)
   |
 _apply_costs: fee = price*qty*fee_rate ; slippage = price*qty*rate per leg
               (SL exit uses exit_slippage_rate ; TP/entry use expected_slippage)
```

### Recommended Project Structure
```
src/risk/
├── cost_rates.py     # NEW: CostRates, AccountCommission, resolve_cost_rates, per_unit_round_trip_cost, check_cost_guards
├── sizing.py         # size_position: formula unchanged (D-02); entry_ref is now the adverse edge
├── gating.py         # evaluate_risk: computes sizing_entry + costs + guards internally
├── types.py          # SizedResult gains optional rate/ratio fields (default None)
src/backtest/costs.py # CostModel gains exit_slippage_rate; modeled_costs_per_unit delegates to src/risk
src/adapters/binance_usdm.py  # + async user_commission_rate(symbol) -> CommissionRates
params/<family>/baseline-v5.toml, baseline-no-trade-v3.toml, baseline-simple-trend-v3.toml
tests/fixtures/phase4/parameters.json  # + pins for the new sets (PA-01)
```
`src/risk/` currently imports nothing from `src/backtest/` [VERIFIED: import scan of `src/risk/*.py` this session]; keep it that way, and let `src/backtest/costs.py` import from `src/risk/`.

### Pattern 1: One shared producer, computed inside `evaluate_risk`
**What:** The producer takes explicit prices and rates; `evaluate_risk` is the only place that decides the sizing entry price.
**When to use:** All three modes. The manager passes `risk_kwargs` directly to `evaluate_risk` [VERIFIED: src/execution/manager.py:418 `verdict = evaluate_risk(**risk_kwargs)`], so any pre-computed `modeled_costs_per_unit` supplied by a caller could be built from a different entry price than the one `evaluate_risk` uses for `sl_distance`.
**Example (target shape, not existing code):**
```python
# src/risk/cost_rates.py  (stdlib + Decimal + src.core._decimal only)
def per_unit_round_trip_cost(
    *, entry_price: Decimal, stop_price: Decimal, rates: CostRates
) -> Decimal:
    entry_leg = _mul(entry_price, _add(rates.fee_rate_entry, rates.entry_slippage_rate))
    exit_leg = _mul(stop_price, _add(rates.fee_rate_exit, rates.exit_slippage_rate))
    return _add(entry_leg, exit_leg)
```
`src/backtest/costs.py::modeled_costs_per_unit(cost_model, side, entry_price, stop_price)` builds `CostRates` from the model (source `PARAMETER`) and calls the same function. Keep the public name so `src/backtest/__init__.py` exports and existing imports keep working.

### Pattern 2: Explicit required kwargs, not a `parameter_set` dict lookup, for the guards
**What:** Pass `min_stop_distance_rate` and `max_cost_to_risk` as keyword-only required arguments, exactly like `minimum_risk_utilization_after_rounding`.
**Why:** The `parameter_set` argument of `evaluate_risk` is the portfolio-threshold dict; tests build it by hand with only the five portfolio keys (`tests/test_execution_manager.py:_build_risk_kwargs`, `tests/test_risk_portfolio.py` `PARAMETERS`), and `resolve_absolute_thresholds` just copies the whole dict through [VERIFIED: src/risk/portfolio.py:80-110]. Reading guard rates from it would silently make them optional in tests and force every hand-built dict to change anyway. Explicit kwargs fail loudly (TypeError) at every call site, which is the fail-closed behavior wanted.
**Call sites that must change (complete list, from grep this session):** `src/backtest/simulator.py:803-821`, `src/paper/loop.py:504-522`, `src/execution/manager.py:418` (kwargs come from the caller, docstring at 320-323 lists the keys), `tests/test_risk_portfolio.py:941-970`, `tests/test_execution_manager.py:385-415`, `tests/test_risk_sizing.py`, `tests/test_risk_quantization.py`, `tests/test_risk_parity.py`, `tests/phase10_helpers.py`, plus fixtures `tests/fixtures/phase5/*/input.json` and `tests/fixtures/phase9/placement_sequences/input.json`.

### Pattern 3: Guard order inside `evaluate_risk`
Order: compute `costs` -> `size_position` (keeps its own `sl_distance <= 0 -> EXCHANGE_CONSTRAINT`) -> `STOP_TOO_TIGHT` -> `COST_TO_RISK_EXCEEDED` -> `quantize` -> `check_portfolio`. Running the guards after `size_position` preserves the current reason for degenerate geometry (existing tests assert `EXCHANGE_CONSTRAINT` for zero SL distance through the sizing helpers, e.g. `tests/test_risk_portfolio.py:768`). Boundaries: reject when `stop_rate < min_stop_distance_rate` and when `ratio > max_cost_to_risk` (equality passes); pin both with boundary tests.
`check_portfolio` returns `sized=None` for any upstream reject [VERIFIED: src/risk/portfolio.py `if sized.is_no_trade: return PortfolioVerdict(... sized=None ...)`], so the D-07 "ratio recorded on the sizing result" survives only on accepted results. For rejected plans emit the ratio in a structlog lineage event (same pattern as `quantize._emit_lineage`, local `import structlog`).

### Pattern 4: Live rate resolution as a pure function
```python
@dataclass(frozen=True)
class AccountCommission:            # built by the caller from the adapter result + its own clock
    symbol: str
    maker_rate: Decimal
    taker_rate: Decimal
    observed_at_utc: datetime       # UTC-aware, validated like ConstraintSnapshot

def resolve_cost_rates(*, cost_model, mode, account_commission, now_utc, ttl) -> CostRates | RejectionReason:
    # PARAMETER: rates straight from the model, fee_source="PARAMETER"
    # LIVE: account_commission None / wrong symbol / age > ttl / age < 0 / rate not in [0, 0.01]
    #       -> UNCERTAIN_ACCOUNT_STATE (never zero, never silent parameter fallback)
    #       else fee_rate_entry = max(param_entry, taker_rate), fee_rate_exit = max(param_exit, taker_rate),
    #            fee_source="ACCOUNT_MAX"
```
Mirror the `constraint_snapshot_ttl_seconds` freshness check in `check_portfolio` (age > ttl or age < 0 fails closed) [VERIFIED: src/risk/portfolio.py freshness block]. Baseline TTL: `commission_rate_ttl_seconds = 3600`, an INT key next to `constraint_snapshot_ttl_seconds = 3600` [VERIFIED: params/trend-pullback/baseline-v4.toml:50 and src/domain/registry.py:109,277]. Rationale: fee tier changes on a 30-day volume basis, so hourly is far tighter than needed; `commissionRate` weight is 20 per symbol, negligible.

### Anti-Patterns to Avoid
- **Pre-computed cost passed into `evaluate_risk`:** lets the caller and pipeline disagree on the entry price. Remove the `modeled_costs_per_unit` kwarg.
- **Recomputing the formula in tests:** replace `tests/test_backtest_simulator.py` Test 11 with hand-derived oracles (F-601). An oracle must not call `per_unit_round_trip_cost`.
- **Defaulting a missing `exit_slippage_rate` to `expected_slippage`:** silent default, forbidden by the fail-closed rule. A model without it is legacy: constructible and hashable, refused by sizing/simulation.
- **Using `float` anywhere** (canonicalizer already rejects it; keep `_coerce_decimal` behavior).

## D-03 feasibility (adverse-edge entry)

**Worst-case proof (derived this session, verified numerically below).** Let `c_e = fee_entry + slip_entry`, `c_x = fee_exit + slip_exit`, fill price `p`, stop `S`, quantity `q`. With D-05 booking (`fee = price·q·rate`, `slippage = price·q·rate`, SL exit at exactly `S`):
- LONG: `loss(p) = q[(p − S) + p·c_e + S·c_x] = q[p(1 + c_e) − S(1 − c_x)]`, increasing in `p`, maximal at `p = entry_max`.
- SHORT: `loss(p) = q[(S − p) + p·c_e + S·c_x] = q[S(1 + c_x) − p(1 − c_e)]`, decreasing in `p`, maximal at `p = entry_min`.
At the adverse edge `loss = q × risk_per_unit`, where `risk_per_unit = sl_distance + entry·c_e + S·c_x` is exactly D-01 + D-02. So `loss(p) <= q × risk_per_unit <= allowed_risk` for every `p` in the zone once `q` is floored.

**Code facts confirmed by reading:**
- `evaluate_risk` currently builds `entry_ref` as zone-mid and passes it both to `size_position(entry_ref=...)` and to `quantize(reference_price=entry_ref)` [VERIFIED: src/risk/gating.py:69-73 `# Zone-mid entry_ref = (entry_min + entry_max) / 2 (D-02 locked` and lines 76-109]. The change is local to this function.
- `size_position` derives `sl_distance = abs(_sub(entry_ref_d, trade_plan.stop_loss_price))` from its `entry_ref` argument [VERIFIED: src/risk/sizing.py:59], so passing the adverse edge as `entry_ref` needs no formula change (keep the parameter name to avoid churn; document it as the sizing entry).
- `quantize` uses `reference_price` only for `rounded × reference_price < min_notional` and the `<= 0` guard [VERIFIED: src/risk/quantization.py:79,105-106].
- Live places its LIMIT at zone-mid: `limit_price = quantize_price(price=derive_limit_price(entry_min_price=..., entry_max_price=...), ...)` [VERIFIED: src/execution/manager.py:471-478], and `derive_limit_price` returns `_div(_add(entry_min_price, entry_max_price), Decimal("2"))` [VERIFIED: src/execution/placement.py:143]. The simulator fills at zone-mid (`entry_ref = _div(_add(trade_plan.entry_min_price, trade_plan.entry_max_price), Decimal("2"))`, src/backtest/simulator.py:479-482).

**Recommendations (planner should adopt; record in the DECISIONS entry):**
1. Size at the adverse edge, but keep `quantize(reference_price=zone_mid)`: that is the price the order is placed at in live and filled at in the simulator, so the min-notional gate judges the order that will exist. Using `entry_max` for LONG would make the notional gate optimistic (higher price), and the asymmetry between sides would be a new bug.
2. Leave the simulator fill price at zone-mid (Phase 14 owns fill causality). Consequence to state in the DECISIONS entry: actual SL loss for a mid fill is below the budget by about `(edge − mid) × q`, and `realized_risk` recorded on the trade is the worst-case figure, so R-multiples in `src/backtest/report.py` are measured against the worst-case risk. This is conservative, not a defect.
3. The planner geometry gate (`minimum_rr`, planner.py:383-409) still measures RR from zone-mid; do not change it (plan identity and Phase-4 digests are frozen). The TradePlan is untouched.
4. Supersession note for DECISIONS: Phase 5 D-02 zone-mid `entry_ref` remains the notional/limit/fill reference; it is superseded only as the risk-sizing entry.

## Fixture and hash inventory (what moves, what does not)

**Unchanged by design (verify still green):**
- All ten pre-Phase-11 parameter files and hashes: `PRE_PHASE_FILE_SHA256` / `PRE_PHASE_HASHES` [VERIFIED: scripts/decision_alignment/params.py:26-96]. The registry hashes `{strategy_id, strategy_version, parameter_set_id, parameters}` only [VERIFIED: src/domain/registry.py:414-420], so extending `STRATEGY_KEYS` cannot move any existing `parameter_set_hash`.
- Phase-4 fixtures and digests (`tests/test_fixture_harness.py` `EXPECTED_SIGNALS_DIGEST`/`EXPECTED_PLANS_DIGEST`): they sit before the risk stage and the planner does not use costs. `TradePlan` stays frozen.
- `tests/test_registry.py` pinned set hashes (lines ~773-809): registry-only.

**Will move / must be regenerated (mechanism-derived; confirm by running the suite after the code change):**
| Item | Why it moves | Action |
|------|--------------|--------|
| `tests/fixtures/phase5/*/input.json` (11 dirs) + `expected.json` | hand-typed `modeled_costs_per_unit` (`"1.0"` at BTC 50,000); sizing entry now adverse edge | Replace with producer-fed inputs; hand-derive expected in a sidecar (D-16). `happy_path_long` currently expects `quantity 0.049`, `realized_risk 49.04900` |
| `tests/fixtures/phase6/{intrabar_*,limit_*,invalidation_cancels_entry}/input.json` (8 dirs) | 5-line cost dict lacks `exit_slippage_rate`; stops ~0.064% from entry so all hit `STOP_TOO_TIGHT` | Rescale candle geometry in `scripts/gen_phase6_fixtures.py` so ATR-derived stop is >= the guards; add cost key; repoint `parameter_set_id`/`strategy_version` to a v5 set |
| `tests/fixtures/phase7/*/input.json` + `expected.json` (parity, clean_run, attribution_split, epoch_rollover, etc.) | pinned digests/verdict tuples change when reasons or trades change; `parity_overlapping_history/expected.json` pins `cost_model_hash 770c9591...` and `parameter_set_hash e3176f73...` (baseline-v2) | Regenerate and record |
| `tests/fixtures/phase7.1/*` (binding: match, wrong_fee, wrong_funding, precision_drift) | cost-hash canonicalization (D-15) | `precision_drift` asserts `0.00020` vs `0.0002` must NOT bind; under D-15 they bind. Repurpose to a real value change |
| `tests/fixtures/phase8/replay_5x`, `tests/fixtures/phase9/placement_sequences/input.json` | carry `modeled_costs_per_unit` / parameter dicts into `evaluate_risk` kwargs | Update to new kwargs |
| `tests/fixtures/phase6/baselines/*/expected.json` | audit F-608: stale, apparently unused (`trades []`, `trade_count 1`) | Confirm unused, delete or fix (audit recommendation) |
| `tests/fixtures/phase6/registry_identity/expected.json` | all `PLACEHOLDER_FILLED_AT_GREEN` | leave; fixture is grandfathered (baseline-v2 has 3 of 7 cost keys) |
| `tests/fixtures/phase10/*` (`cost_model_hash`, `modeled_costs_per_unit` literals) | opaque analytics inputs, not computed from `CostModel` | expected to stay; confirm by suite run |

**Tests asserting the old trailing-precision cost-hash semantics (conflict with D-15; rewrite, do not delete):** `tests/test_backtest_experiment.py` `test_cost_model_hash_precision_discipline` (line ~314) and the assertions at lines ~731-744 (`trailing` vs `trimmed` hash inequality), and `tests/test_backtest_binding.py` `test_binding_gate_rejects_precision_drift`. D-15 deliberately supersedes Phase 7.1 D-04/D-12 **for `cost_model_hash` only**; `tests/test_registry.py` Test 13 (`Decimal("1.50")` vs `Decimal("1.5")` give different `parameter_set_hash`) is registry behavior and must keep passing.

**Current real cost hashes** (computed this session by `build_cost_model` over each set's registry slice): v3 sets `12c05d5f4061...`; all v4/no-trade-v2/simple-trend-v2 sets share `e18ce0093131...` (PA-05 relies on this equality); no-trade-v1 / simple-trend-v1 `98d177271d96...`; v1/v2 sets raise `KeyError` (only 3 of 7 cost keys). Under D-15 these do not move because their spellings are already minimal (`partial_fill_fraction` is `Decimal('0.5')` or int `1`). Only fixture dicts spelled `"1.0"` move.

## Parameter-set and hash design (D-14, D-15)

**Recommendation (Option B, per D-14's own fallback wording):** presence-driven cost-key tuple.
- Keep `COST_KEYS` (7 keys) unchanged for legacy sets. Add `exit_slippage_rate` as an 8th key that participates in `cost_model_hash` **only when present** in the slice; a model built without it has `exit_slippage_rate = None` and `cost_model_hash` computed over the 7 legacy keys (still D-15 canonical).
- Sizing (`resolve_cost_rates`) and the simulator/paper entry refuse a model whose `exit_slippage_rate is None` (fail closed).
- Why not simply extending `COST_KEYS`: `assert_cost_model_binds_registry` and `paper/freeze` do `{k: parameter_set.params[k] for k in COST_KEYS}` [VERIFIED: src/backtest/binding.py `registry_slice = {k: parameter_set.params[k] for k in COST_KEYS}`; src/paper/freeze.py:386], so every v3/v4 set would raise `KeyError` and about 60 existing test references (test_backtest_experiment 29, test_backtest_binding 26, test_paper_freeze 5) would need migrating to v5. PA-05 (`check_cost_hash_parity`) also builds models for the five v4 sets over `COST_KEYS` [VERIFIED: scripts/decision_alignment/params.py:216-229]. Option B leaves those untouched.
- The safeguard against a v5 set that forgets the key being silently treated as legacy: new gate **PA-07** (v5 sets each carry all four Phase-12 keys, `strategy_version` bumped, header contains `Supersedes`) plus the consumer-side refusal above.

**Registry changes (`src/domain/registry.py`):**
- Add to `STRATEGY_KEYS`: `exit_slippage_rate`, `min_stop_distance_rate`, `max_cost_to_risk`, `commission_rate_ttl_seconds`. `DECIMAL_KEYS = STRATEGY_KEYS - INT_KEYS - STRING_KEYS` picks up the three Decimal ones automatically [VERIFIED: registry.py:292]; add `commission_rate_ttl_seconds` to `INT_KEYS`.
- D-04 unit guard in `_check_param_types`: for `fee_rate_entry`, `fee_rate_exit`, `expected_slippage`, `exit_slippage_rate` reject `> 0.01` (raise `StrategyKeyOutsideRegistry`, message names the key and "unit error"). Also `CostModel.__post_init__` must range-check `[0, 0.01]` (defense in depth, since simulator fixtures bypass the registry). Range for the guards: `min_stop_distance_rate` in `(0, 1)`, `max_cost_to_risk` in `(0, 1]`, TTL `> 0`. All existing sets have fee/slippage values <= 0.0005, so no old set changes behavior.
- `working_type` precedent: keys added later were made optional in old sets and only whitelisted [VERIFIED: registry.py:110-115 comment "Optional; absent in sets that predate it"]. Follow it; `check_strategy_key_outside_registry` will now also reject ambient config named after the four new keys (same as every other whitelisted key), so runtime config must not use those names.

**New sets (D-14):** `params/trend-pullback/baseline-v5.toml`, `params/breakout-retest/baseline-v5.toml`, `params/range-mr/baseline-v5.toml`, plus successors of `baseline-no-trade-v2` and `baseline-simple-trend-v2`, which by the existing naming are `baseline-no-trade-v3` and `baseline-simple-trend-v3` (their own series; CONTEXT says "matching successors"). Note `range-mr` has no `baseline-v3` [VERIFIED: `ls params/range-mr` -> v1, v2, v4], and `trend-pullback` no-trade/simple-trend are v1, v2. Copy the v4 body byte-for-byte for non-cost keys (v4 states "every other key, value and order is unchanged" vs v3; `baseline-no-trade-v2`/`simple-trend-v2` differ from v4 only in `minimum_rr`, `zone_tolerance_atr`, and `atr_period` [VERIFIED: diff run this session]), add:
```toml
exit_slippage_rate = 0.0003            # 3 bps stop-market exit (D-06)
min_stop_distance_rate = 0.003         # 0.3% (D-07)
max_cost_to_risk = 0.15                # (D-07)
commission_rate_ttl_seconds = 3600     # 1 hour (D-11)
```
`strategy_version`: bump to `v4.0.0` (v4 sets are `v3.0.0`, v3 sets `v2.0.0`); headers say "Supersedes baseline-v4". Registry accepts any non-empty `strategy_version`. Pin each new set's hash in `tests/fixtures/phase4/parameters.json` (PA-01 fails on an unpinned TOML: "no pinned hash" [VERIFIED: scripts/decision_alignment/params.py `check_pins`] and `tests/test_decision_alignment_params.py:54-56` asserts that behavior). PA-04 (`check_new_set_facts`) hard-codes `EXPECTED_NEW_VERSION = "v3.0.0"` and `NEW_SET_IDS` = the five v4-era sets; add the v5 sets under a new tuple and a new expected version rather than editing PA-04's constants, and keep PA-05 on the v4 sets (they still build a 7-key model).

**Hash canonicalization (D-15):** in `CostModel` (not in `src/domain/canonical.py`, which also hashes IDs/plans and must not change), hash a normalized rendering of the numeric cost fields. Recommended normalization: `format(value.normalize(), "f")` for Decimals (yields `1` for `1`/`1.0`, `0.0002` for `0.00020`, `100` for `100`; avoids `1E+2`), zero normalized to `0`. Test cases: `"1.0"`, `"1"`, int `1`, `Decimal("1.00")`, `"0.00020"`, `"0"`, `"0.0"`, and a large value. Apply the same normalization in `build_cost_model` path and the `CostModel.__post_init__` recomputation (CR-09 verification) so a supplied hash is checked against the same rule. Does not change registry `parameter_set_hash`. Own DECISIONS entry (next free ID is D046; last existing row is D045 [VERIFIED: grep of docs/DECISIONS.md]).

## Rejection-code work (D-08, D-09)

**Current enum (verbatim, src/domain/enums.py:130-156):** `NO_TRADE_REGIME, RR_TOO_LOW, STALE_SETUP, INVALIDATED, RISK_LIMIT, CORRELATED_RISK_LIMIT, DAILY_STOP, QUANTIZATION_REJECT, MIN_NOTIONAL_REJECT, INSUFFICIENT_MARGIN, EXCHANGE_CONSTRAINT, DATA_STALE, RECONCILIATION_REQUIRED, APPROVAL_EXPIRED, MIN_QTY_REJECT, NOTIONAL_REJECT, UTILIZATION_REJECT, CLUSTER_CAP_REJECT, AGGREGATE_CAP_REJECT, MAX_POSITIONS_REJECT, DAILY_STOP_BLOCK, STALE_CONSTRAINTS, UNCERTAIN_ACCOUNT_STATE` (23 members). Aliases to delete: `RISK_LIMIT`, `CORRELATED_RISK_LIMIT`, `DAILY_STOP`, `QUANTIZATION_REJECT`, `MIN_NOTIONAL_REJECT`. Result: 18 + 2 = 20 members.

**Everything that hard-codes the alias set (one edit window, all in the same change):**
1. `docs/GLOSSARY.md` §9: add the two codes to the §9.1 text block (source of truth first), delete §9.2 alias table, fix the §9 lead-in counts ("17 codes ... plus reserved ... Five synonyms").
2. `src/domain/enums.py`: remove 5 members, add `STOP_TOO_TIGHT = "STOP_TOO_TIGHT"`, `COST_TO_RISK_EXCEEDED = "COST_TO_RISK_EXCEEDED"`. `src/risk/types.py` builds `_REASON_CODES` from the enum automatically [VERIFIED: types.py:27].
3. `tests/test_domain_enums.py` `test_rejection_reason_values_match_glossary_section_9` (expected set lines ~200-224 and docstring).
4. `scripts/decision_alignment/bookkeeping.py`: `ALIASES` tuple (lines 26-32), GL-01 ("none of the five aliases"), GL-03 (`union == enum` and `sorted(aliases) == sorted(ALIASES)`), `parse_glossary_sections` (`sec92`). Rework GL-01/GL-03 for an empty alias section; the matching `tests/test_decision_alignment_bookkeeping.py` cases.
5. `scripts/decision_alignment/ops_risk.py:210` `QUANTIZATION_SYNONYM = "QUANTIZATION_REJECT"` (gate that forbids the synonym in RISK_MANAGEMENT text) and `tests/test_decision_alignment_ops_risk.py:181-184` – these test that the synonym is *forbidden in docs*; likely still valid, verify.
6. `tests/test_backtest_simulator.py:207` accepts `"QUANTIZATION_REJECT"` as a string in an allowed-reasons set; drop it.
7. GL-02 counts codes referenced as `RejectionReason.X` in `src/`; the two new codes become referenced and must be in §9.1 (they will be, per step 1). D044/`docs/DECISIONS.md` text mentioning "five deprecated aliases" is history; append a new entry, do not edit D044.

## Live `commissionRate` (D-10..D-13)

**Endpoint facts and provenance:**
| Fact | Value | Source / tag |
|------|-------|--------------|
| Method + path | `GET /fapi/v1/commissionRate` | [VERIFIED: installed SDK 17.4.0 `account_api.py:1035-1080`, `path="/fapi/v1/commissionRate"`, `method="GET"`] and [CITED: https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/User-Commission-Rate via WebSearch summary, 2026-09-30] |
| Weight | 20 (IP) | [VERIFIED: SDK docstring "Weight(IP): 20"] [CITED: same official page, search summary] |
| Security type | USER_DATA (signed; `is_signed=True`) | [VERIFIED: SDK `account_api.py`] |
| Parameters | `symbol` mandatory, `recvWindow` optional, `timestamp` mandatory (SDK adds) | [VERIFIED: SDK signature `user_commission_rate(self, symbol, recv_window=None)`; `RequiredError` if symbol None] [CITED: official page search summary] |
| Response fields | `symbol`, `makerCommissionRate`, `takerCommissionRate`, `rpiCommissionRate`, all strings; example `"0.0002"`, `"0.0004"`, `"0.00005"` | [VERIFIED: `rest_api/models/user_commission_rate_response.py` fields `symbol`, `maker_commission_rate`, `taker_commission_rate`, `rpi_commission_rate`, all `Optional[StrictStr]`] [CITED: official page search summary with the example JSON] |
| RPI field added | effective 2025-11-26 | [CITED: https://developers.binance.com/docs/derivatives/change-log, WebFetch 2026-09-30: "Effective on 2025-11-26, RPI commisson fee is available in the response of User Commission Rate endpoint"] |
| Demo / testnet behavior | Not documented in any page retrieved | [ASSUMED] unknown; the change log fetch found no `demo-fapi.binance.com` reference. Verify during the D040 DEMO stage (Phase 24) |

**Retrieval honesty (for `docs/SOURCES.md`):** a direct WebFetch of the official page returned a different endpoint's content (Account Information V2) and then a truncated shell; a `curl` with a browser user-agent returned HTTP 202 with an empty body. The official page was reached only through WebSearch result text. The SDK (generated from Binance's OpenAPI) was read directly and agrees on path, weight and fields. Treat as MEDIUM; the row must say so, and the adapter must not depend on any field beyond `symbol`, `takerCommissionRate`, `makerCommissionRate`.

**Draft `docs/SOURCES.md` row (table at "Facts verified for Phase 11" style; add a "Facts verified for Phase 12" table):**
`| https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/User-Commission-Rate | GET /fapi/v1/commissionRate, weight 20 (IP), USER_DATA, params symbol (required) and recvWindow, response fields symbol / makerCommissionRate / takerCommissionRate / rpiCommissionRate (strings) | 2026-09-30 | WebSearch result text for the official page (direct WebFetch returned another endpoint's content, curl returned an empty HTTP 202); cross-checked against installed SDK 17.4.0 account_api.py and the change-log entry of 2025-11-25 (RPI field effective 2025-11-26). MEDIUM confidence. Demo/testnet behavior not documented in retrieved material; verify in the DEMO stage |`
Also add a short subsection to `docs/integration/BINANCE.md` (§6 Orders or a new §12 "Account commission") stating the endpoint, that sizing uses `max(parameter, account taker)` per side, BNB discount ignored, fail-closed rule, and the verify marker style the file already uses ("verify against current Binance docs before implementation").

**Adapter design (project pattern):**
```python
@dataclass(frozen=True)
class CommissionRates:  # in src/adapters/binance_usdm.py next to PositionModeResult
    symbol: str
    maker_rate: Decimal
    taker_rate: Decimal


async def user_commission_rate(self, symbol: str) -> CommissionRates:
    response = await asyncio.to_thread(self._sdk.rest_api.user_commission_rate, symbol)
    raw = response.data()
    # flag-never-fabricate (D-09 pattern): None maker/taker, non-decimal string, negative, > 0.01,
    # or raw.symbol != symbol -> raise ValueError. Never return 0.
```
Follow `get_position_mode` (asyncio.to_thread, model imported locally) [VERIFIED: src/adapters/binance_usdm.py:1231-1254]. The adapter takes no clock (same as `exchange_info`, whose filters carry no observed time); the caller stamps `observed_at_utc` when building the pure `AccountCommission`. Call the SDK method positionally/with `symbol=` only; do not pass `recv_window` unless the module's existing convention requires it. Tests: `tests/test_adapter_strictness.py` fake-REST pattern with `UserCommissionRateResponse` instances (`_FakeRest`/`_FakeResponse`) covering ok, missing taker, `"abc"`, negative, `"0.5"`, symbol mismatch. Whether the manager's Protocol-typed adapter surface (`tests/test_execution_adapter_contract.py`) needs the method is a Phase 24 wiring question; do not add it to the execution Protocol in this phase.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Decimal arithmetic under fixed precision | raw `Decimal` operators | `_add/_sub/_mul/_div` from `src/core/_decimal.py` | Pinned prec-28 context; ambient context cannot change results |
| Canonical hashing | new serializer | `sha256_hex` in `src/domain/canonical.py` | Single canonicalizer; only normalize the cost values *before* passing them in (D-15) |
| Param-set identity and unit checks | ad hoc file parsing | `load_parameter_set` / `_parse_and_validate` / `_check_param_types` | Fail-closed whitelist, ASCII keys, raw-string Decimal preservation |
| Freshness/TTL check | new clock logic | mirror the `check_portfolio` constraint-snapshot block (age > ttl or age < 0 fails closed) | Same semantics, one clock (`now_utc` injected) |
| Exchange SDK access | `httpx` call to `/fapi/v1/commissionRate` | `rest_api.user_commission_rate` behind the adapter | Official SDK owns the wire and signing; AGENTS.md exchange rule |
| Property testing | `hypothesis` | explicit Decimal grid | Not installed; deterministic and byte-reproducible |

**Key insight:** the bug class here is unit drift between modules that each "work" in isolation. The defense is one producer, computed at one place, verified by oracles that do not call it.

## Common Pitfalls

### Pitfall 1: Every existing simulator fixture becomes STOP_TOO_TIGHT
**What goes wrong:** Phase 6/7 fixtures trade at price ~121.5 with SL 121.422 (stop 0.064% away; observed by running `run()` on `tests/fixtures/phase6/intrabar_both_touched/input.json`, `exit 121.4221...` `qty 635.67`, `realized_pnl -103.594` versus allowed 50). `min_stop_distance_rate = 0.003` rejects all of them, so the sim tests lose their trades.
**Why:** `scripts/gen_phase6_fixtures.py` builds a smooth +0.10/bar uptrend from 100 (ATR ~0.1, ~0.1% of price).
**How to avoid:** rescale the candle step (for example 1.0-2.0/bar on a 100-250 price) so the family-A stop (`swing_low − sl_buffer_atr × ATR`, zone `±zone_tolerance_atr × ATR`) is >= 0.79% (the cost ceiling binds first, see Pitfall 2). Validate by running `run()` and asserting a trade exists before blessing.
**Warning signs:** `outcome_kind == "REJECT"` with `reason_code == "STOP_TOO_TIGHT"` in every `intrabar_*` and `limit_*` fixture.

### Pitfall 2: The 0.15 cost ceiling, not the 0.3% stop floor, is the binding gate
**What goes wrong:** With baseline v5 rates (fee 0.0005 in, 0.0005 out, entry slip 0.0001, exit slip 0.0003) the round trip is about 14 bps of price. `cost / (d + cost) <= 0.15` requires `d >= ~0.79%` of price (`0.0014 / (0.15/0.85 + 0.0008) ≈ 0.0079`, computed this session). A 0.5% BTC stop gives ratio 0.2185 (rejected); a 2.2% stop gives 0.0592 (accepted).
**Why it happens:** the audit's 0.15 baseline (F-002) was derived under a *maker*-in model; D-01/D-06 use taker-in plus slippage.
**How to avoid:** do NOT retune after seeing results (D-06/D-07 forbid it). Do surface the number to the user in the DECISIONS entry and the SUMMARY, and check that the real strategy stop distances in the regenerated fixtures clear it. Whether 0.15 should be kept is a user call (Open Question 1), not a planner call.

### Pitfall 3: Reading guard parameters from the portfolio `parameter_set` dict
See Pattern 2. Hand-built dicts in tests would silently lack the keys.

### Pitfall 4: `PortfolioVerdict` drops the sizing result on reject
**What goes wrong:** the guards' ratio (D-07) and the fee source (D-12) vanish on NO_TRADE.
**How to avoid:** add optional fields to `SizedResult` (default `None`, so existing constructors, `_to_parity_dict` helpers and fixtures need no change) and emit a structlog lineage event on every guard reject.

### Pitfall 5: `1` vs `1.0` and trailing zeros in cost hashes
Registry TOML `1.0` becomes int `1` (`_normalize_value` converts integer-valued floats to `int`) [VERIFIED: registry.py:214-221], and `_coerce_decimal` then renders `"1"`, whereas fixture dicts spelled `"1.0"` render `"1.0"` (two of the phase-7.1 grandfathered baselines failed exactly this way, per `tests/test_backtest_binding.py` header). Fix once in `CostModel` (D-15) and cover with the spelling matrix above.

### Pitfall 6: D-15 versus the Phase 7.1 precision tests
See the inventory. Rewrite the three precision-drift tests to use a genuine value change; keep `parameter_set_hash` precision behavior untouched.

### Pitfall 7: Deleting the aliases breaks Phase 11 gates, not just tests
See "Rejection-code work". `scripts/verify_decision_alignment.py` must be green after the change; run it (it has its own test module `tests/test_decision_alignment*.py`).

### Pitfall 8: Doc edits must keep Phase 11 gate tokens
`scripts/decision_alignment/ops_risk.py` and `bookkeeping.py` assert literal phrases in RISK_MANAGEMENT.md, CONFIGURATION.md (for example `baseline-v4`, `taker`, `D036`, `Canonical order (D031):`) and the D044/D045 rows [VERIFIED: bookkeeping.py D044_TOKENS, ops_risk.py CONFIGURATION_PHRASES / QUANTIZATION_* constants]. Amend by adding text; never remove those tokens. Append DECISIONS rows (D046, D047), do not edit D044/D045.

### Pitfall 9: `EOD` exits and slippage rate
`resolve_intrabar` returns `exit_kind` `SL` | `TP1` | `EOD`; `EOD` is a close at the last 1m candle (a market-style exit). D-05 specifies only SL and TP. Recommend `EOD` uses `exit_slippage_rate` (market exit, conservative) — record as a planner decision [ASSUMED, not in CONTEXT].

### Pitfall 10: Live account rate of `0` is legitimate, unknown is not
`max(param, account)` already floors a real zero at the parameter rate. Fail closed only on absent/None/stale/malformed/out-of-range values, and on symbol mismatch. Do not treat `0` as malformed.

## Code Examples

### Hand-derived oracle cases (computed this session with Python `Decimal`; independent of the code under test)
Rates: `fee_in = 0.0005`, `slip_in = 0.0001`, `fee_out = 0.0005`, `slip_out = 0.0003`. Equity 10,000, risk 0.005, `allowed_risk = 50`.

| Case | Zone | Sizing entry | Stop | Round-trip cost per unit | risk_per_unit | cost/rpu | raw qty | floored qty | Loss at SL |
|------|------|--------------|------|--------------------------|---------------|----------|---------|-------------|------------|
| BTC LONG 2.2% | 59,900-60,100 | 60,100 (entry_max) | 58,780 | 83.0840 | 1,403.0840 | 0.0592 | 0.0356357851... | 0.035 (step 0.001) | 49.1079400 |
| BTC SHORT 2.3% | 59,900-60,100 | 59,900 (entry_min) | 61,300 | 84.9800 | 1,484.9800 | 0.0572 | 0.0336704871... | 0.033 | 49.0043400 |
| XRP LONG 1.6% | 0.4990-0.5010 | 0.5010 | 0.4930 | 0.00069500 | 0.00869500 | 0.0799 | 5750.43128... | 5750.4 (step 0.1) | 49.999728 |
| BTC LONG 0.5% (guard) | 59,900-60,100 | 60,100 | 59,800 | 83.9000 | 383.9000 | 0.2185 | 0.13024... | rejected `COST_TO_RISK_EXCEEDED` (0.2185 > 0.15) | — |
Old-formula check: rate-sum `0.0009` added to a 1,320 distance makes the BTC LONG case size at ~0.0378 and lose ~53.1 at SL, above the 50 budget. Also verify `producer(2·P, ...) == 2 · producer(P, ...)` (linear scaling contract) and that XRP slippage is `price × qty × rate` (old code gave `qty × rate`, 2× too large at 0.5, F-306).

### `_apply_costs` target booking (edit localized to the cost math)
```python
# src/backtest/simulator.py  _apply_costs  (sketch)
exit_rate = (
    cost_model.exit_slippage_rate
    if trade_record.exit_kind in ("SL", "EOD")
    else cost_model.expected_slippage
)  # TP1 uses expected_slippage (D-05)
slip_entry = _mul(_mul(entry_price, quantity), cost_model.expected_slippage)
slip_exit = _mul(_mul(exit_price, quantity), exit_rate)
slippage = _add(slip_entry, slip_exit)  # TradeRecord.slippage_amount = total
```
Fees are already `price × qty × rate` [VERIFIED: src/backtest/simulator.py:651-652]. `TradeRecord` field names stay; `modeled_costs_per_unit` keeps its name and changes meaning to quote per unit (persisted analytics fields `_TRADE_DECIMAL_FIELDS` in `src/adapters/analytics_files.py:79` and `src/backtest/experiment.py:263` just parse it as a Decimal).

### Property-test skeleton (explicit grid, no hypothesis)
```python
PRICES = [Decimal("60000"), Decimal("3000"), Decimal("0.5")]
STOP_WIDTHS = [
    Decimal(x) for x in ("0.008", "0.01", "0.015", "0.02", "0.03")
]  # >= guard-clearing widths
FILL_FRACTIONS = [Decimal(x) for x in ("0", "0.25", "0.5", "0.75", "1")]  # position inside the zone
# for side in LONG/SHORT: build zone +-0.1% around price, stop at width below/above adverse edge,
# run evaluate_risk -> quantized qty; for each fill p = emin + f*(emax-emin):
#   loss = (p-S)*q + p*q*fee_in + S*q*fee_out + p*q*slip_in + S*q*slip_out   (LONG; mirror for SHORT)
#   assert loss <= allowed_risk          # tolerance 0: q is floored, arithmetic is exact in prec 28
# and: the same test run against a copy of the OLD formula (rate-sum) must FAIL (proves the test bites).
```
Include widths below 0.79% in a second test asserting `COST_TO_RISK_EXCEEDED`, and below 0.3% asserting `STOP_TOO_TIGHT`. Because `q` is floored to the step, use `<=` with zero tolerance for post-`quantize` quantities; allow `Decimal("1e-20")` relative tolerance only for raw (unfloored) `size_position` output.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `binance-connector` / `binance-futures-connector` | `binance-sdk-derivatives-trading-usds-futures` | legacy archived 2026-04-30 (per AGENTS.md stack table) | Use `rest_api.user_commission_rate` on the official SDK |
| `commissionRate` maker/taker only | + `rpiCommissionRate` field | effective 2025-11-26 | Ignore RPI; do not require it |
| Rate-sum added to a price distance | quote-per-unit producer | this phase | Closes F-001 / F-801 |

**Deprecated/outdated:** the five `RejectionReason` aliases (removed here); hand-typed `"1.0"`/`"0.0"` cost values in Phase 5 fixtures (F-608).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Binance Demo (`demo-fapi.binance.com`) serves `GET /fapi/v1/commissionRate` with the same shape | Live `commissionRate` | Phase 24 DEMO stage may need a fixture-only path; adapter tests here are fixture-driven so no impact on this phase |
| A2 | `EOD` exits use `exit_slippage_rate` (market-style exit) | Pitfall 9 | Backtest PnL slightly optimistic if `expected_slippage` was intended; user/planner to confirm |
| A3 | Keeping `quantize(reference_price=zone_mid)` while sizing at the adverse edge is the intended reading of "confirm against the quantizer's reference_price" | D-03 feasibility | If the user wants the notional gate on the adverse edge, LONG becomes optimistic on min-notional; low risk (exchange would reject, not a safety failure) |
| A4 | `strategy_version` `v4.0.0` for the new sets and `commission_rate_ttl_seconds = 3600` | Parameter-set design | Cosmetic/version numbering; hash-locked once pinned so decide before pinning |
| A5 | The official Binance page fields, read through search-result text rather than a direct page fetch, are complete (no additional mandatory params) | Live `commissionRate` | Adapter tests are fixture-driven and the SDK agrees; low |
| A6 | Existing phase-10 analytics fixtures with `cost_model_hash` / `modeled_costs_per_unit` literals are opaque and will not move | Fixture inventory | Suite run after the change will show; extra regeneration effort only |

## Open Questions

1. **Is `max_cost_to_risk = 0.15` still right under taker-in + 3 bps exit slippage?**
   - What we know: at 14 bps round trip it forces stops >= ~0.79% and dominates the 0.3% floor; the baseline came from the audit's maker-in arithmetic. D-06/D-07 forbid tuning after results.
   - What's unclear: whether the user intended a ceiling this strict for the trend-pullback family whose real stop distances are not yet measured on real data (Phase 13 supplies data).
   - Recommendation: implement 0.15 as locked, surface the 0.79% implication in the DECISIONS entry and phase summary for the user to ratify or change *before* the v5 hashes are pinned (pinning freezes the value).
2. **Simulator fill price (mid vs adverse edge).** Recommendation is to keep mid (Phase 14 owns it) and state the conservatism. If the user prefers end-to-end equality of loss and budget, the simulator would fill at the adverse edge in this phase.
3. **`EOD` slippage rate** (A2).
4. **Demo behavior of `commissionRate`** (A1): verify in Phase 24.
5. **Protocol wording (F-028):** `docs/research/RESEARCH_PROTOCOL.md` line 96 says "basis points per side" for `entry_fee` [VERIFIED: grep this session]. It is frozen at v1.1.0; record the follow-up in the DECISIONS entry, do not edit.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv `.venv/Scripts/python` | all tests | ✓ | 3.13 | — |
| pytest 9 / pytest-asyncio / respx | tests | ✓ | per pyproject dev extra | — |
| `binance-sdk-derivatives-trading-usds-futures` | adapter method + fake models | ✓ | 17.4.0 | — |
| `hypothesis` | (property test) | ✗ | — | explicit Decimal grid (chosen) |
| Live Binance endpoint / API key | not needed (fixture-driven, D-13) | n/a | — | — |
| Network for doc verification | SOURCES.md row | ✓ (WebSearch/WebFetch); official page direct fetch partial | — | recorded honestly in SOURCES.md |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** `hypothesis` -> Decimal grid.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9, pytest-asyncio `asyncio_mode = "auto"`, `addopts = "-q"`, `testpaths = ["tests"]` [VERIFIED: pyproject.toml `[tool.pytest.ini_options]`] |
| Config file | `pyproject.toml` |
| Quick run command | `.venv/Scripts/python -m pytest tests/test_risk_sizing.py tests/test_risk_quantization.py tests/test_risk_parity.py tests/test_risk_portfolio.py tests/test_backtest_simulator.py tests/test_registry.py tests/test_domain_enums.py -q` |
| Full suite command | `.venv/Scripts/python -m pytest -q` (baseline before any change: passed, `real 3m10s`, measured this session with `-x`) |
| Gates | `.venv/Scripts/python scripts/verify_decision_alignment.py` (PA/GL/… gates), `ruff check`, `mypy src` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RISK-01 | Producer returns hand-derived quote/unit for BTC and XRP; scales linearly with price | unit | `pytest tests/test_cost_per_unit.py -x` | ❌ Wave 0 |
| RISK-01 | SL loss <= allowed_risk over price x width x side x fill-position grid (fails on old formula) | property (grid) | `pytest tests/test_sl_loss_property.py -x` | ❌ Wave 0 |
| RISK-01 | `STOP_TOO_TIGHT` / `COST_TO_RISK_EXCEEDED` at, below and above boundaries; reason order; degenerate geometry still `EXCHANGE_CONSTRAINT` | unit | `pytest tests/test_risk_cost_guards.py -x` | ❌ Wave 0 |
| RISK-01 | Same rates + prices give identical cost in producer, `evaluate_risk`, simulator, paper (D-19) | parity | `pytest tests/test_cost_parity.py -x` | ❌ Wave 0 |
| RISK-01 | Live: `max(param, account)` per side; None/stale/future/malformed/symbol mismatch -> `UNCERTAIN_ACCOUNT_STATE`; never zero | unit | `pytest tests/test_commission_rates.py -x` | ❌ Wave 0 |
| RISK-01 | Adapter parses `UserCommissionRateResponse` strictly (missing taker, non-decimal, negative, >0.01, wrong symbol raise) | adapter (fake REST) | `pytest tests/test_adapter_strictness.py -x` (extend) | ✅ extend |
| BKTS-01 | `_apply_costs` slippage = price x qty x rate per leg; SL uses `exit_slippage_rate`; hand-derived BTC/XRP oracle | unit | `pytest tests/test_backtest_simulator.py -x` (replace Test 11) | ✅ modify |
| BKTS-01 | Regenerated phase-6/7 fixtures yield real trades and pinned digests | golden | `pytest tests/test_backtest_simulator.py tests/test_paper_parity.py tests/test_paper_closed_candle.py -x` | ✅ regenerate |
| DOMN-02 | Old ten sets byte/hash-locked (PA-02, PA-03); v5 sets pinned (PA-01), carry four keys + `Supersedes` + bumped version (new PA-07) | gate | `pytest tests/test_decision_alignment_params.py -x` and `python scripts/verify_decision_alignment.py` | ✅ extend |
| DOMN-02 | Loader rejects fee/slippage rate > 0.01; new keys typed/ranged; old sets still load | unit | `pytest tests/test_registry.py -x` | ✅ extend |
| DOMN-02 | `cost_model_hash` canonicalization matrix (`1`, `1.0`, `1.00`, `0.00020`, `0`, `0.0`); forged hash still rejected (CR-09); registry `parameter_set_hash` precision test (Test 13) still passes | unit | `pytest tests/test_backtest_experiment.py tests/test_backtest_binding.py tests/test_registry.py -x` | ✅ rewrite 3 tests |
| D-09 | Enum equals GLOSSARY §9.1 (20 members); GL-01..GL-06 green without alias table | unit/gate | `pytest tests/test_domain_enums.py tests/test_decision_alignment_bookkeeping.py -x` | ✅ modify |

### Sampling Rate
- **Per task commit:** the Quick run command (about tens of seconds; subset of the 3m10s suite).
- **Per wave merge:** full suite plus `scripts/verify_decision_alignment.py`.
- **Phase gate:** full suite green, gates green, `ruff check src tests scripts`, `mypy src`, before `/gsd-verify-work`.

### Nyquist notes (oracle independence)
- Oracle values above were computed by a standalone Decimal script, not by importing project code; the test files must hard-code those literals (or derive them by explicit arithmetic in the test body), never call `per_unit_round_trip_cost` or `_apply_costs` to compute the expectation.
- The property test must include a mutation check: a local copy of the old rate-sum formula fed through the same harness must violate the invariant (guards against a vacuous test).
- Sample the zone at least at both edges and the mid (fills at `f = 0, 0.5, 1`) so the monotone worst-case proof is exercised on both sides; include a step-size case where flooring is material (BTC 0.001, XRP 0.1) and a case where `min_qty` triggers.

### Wave 0 Gaps
- [ ] `tests/test_cost_per_unit.py` — oracle, linear scaling, side symmetry, invalid side
- [ ] `tests/test_sl_loss_property.py` — Decimal grid incl. XRP; old-formula mutation check
- [ ] `tests/test_risk_cost_guards.py` — boundaries, order, ratio on `SizedResult`, lineage on reject
- [ ] `tests/test_commission_rates.py` — `resolve_cost_rates` and `AccountCommission` validation
- [ ] `tests/test_cost_parity.py` — D-19 across producer, `evaluate_risk`, simulator, paper
- [ ] Extend `tests/test_adapter_strictness.py`, `tests/test_registry.py`, `tests/test_decision_alignment_params.py`, `tests/test_decision_alignment_bookkeeping.py`, `tests/test_domain_enums.py`
- [ ] Framework install: none

## Security Domain

`security_enforcement` is enabled (absent = enabled; `.planning/config.json` has `"security_enforcement": true`, `"security_asvs_level": 1`).

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (no new auth) | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — (signed USER_DATA call reuses the existing SDK client and key handling; no new secret paths) |
| V5 Input Validation | yes | Strict Decimal parsing of exchange strings, range `[0, 0.01]`, symbol match, registry type/range checks (`_check_param_types`), `CostModel.__post_init__` |
| V6 Cryptography | no new use | existing SHA256 canonical hashing only; do not hand-roll |
| V7 Error handling / logging | yes | Adapter errors carry no key material; log symbol and field names only (project convention in `tests/test_execution_secret_posture.py`) |
| V8 Data protection | yes (light) | Commission rates are account-specific but not secret; do not log API keys or raw signed URLs |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed / partial exchange response yields a zero or negative fee, inflating size | Tampering / Elevation | Adapter raises on None/non-decimal/negative/out-of-range; `resolve_cost_rates` fails closed to `UNCERTAIN_ACCOUNT_STATE`; `max()` with the parameter floor |
| Stale account rate (tier worsened) under-sizes costs | Repudiation / Tampering | TTL from registry; `age > ttl` or negative age fails closed |
| Unit error in a parameter file (`2` instead of `0.0002`) | Tampering | Loader rejects fee/slippage > 0.01 (D-04) and `CostModel` range-checks |
| Silent parameter mutation / hash drift | Tampering | Never edit old `params/*.toml`; PA-01..PA-03 gates; pins in `tests/fixtures/phase4/parameters.json` |
| Fee source spoofing between modes | Spoofing | `fee_source` recorded on the sizing result; backtest/paper hard-wired to `PARAMETER` |

## Sources

### Primary (HIGH confidence)
- In-repo files read this session (cited with paths and lines above): `src/backtest/costs.py`, `src/backtest/simulator.py`, `src/risk/{sizing,gating,quantization,types,portfolio}.py`, `src/domain/{registry,canonical,enums}.py`, `src/core/{_decimal,planner}.py`, `src/paper/loop.py`, `src/execution/{manager,placement}.py`, `src/adapters/binance_usdm.py`, `scripts/decision_alignment/{params,bookkeeping,ops_risk}.py`, `params/trend-pullback/*.toml`, `tests/*` and `tests/fixtures/*` as listed, `docs/{GLOSSARY,DECISIONS,SOURCES}.md`, `docs/trading/RISK_MANAGEMENT.md`, `.planning/audits/2026-09-29-deep-audit/findings.json` (F-001, F-002, F-005, F-028, F-031, F-306, F-601, F-608, F-801, F-962).
- Installed SDK 17.4.0 source: `rest_api/api/account_api.py:1035-1080`, `rest_api/models/user_commission_rate_response.py`.

### Secondary (MEDIUM confidence)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/User-Commission-Rate — endpoint, weight 20, parameters, response example, via WebSearch result text (direct fetch returned another page), 2026-09-30.
- https://developers.binance.com/docs/derivatives/change-log — RPI commission field, effective 2025-11-26; no demo/testnet reference for this endpoint, WebFetch 2026-09-30.

### Tertiary (LOW confidence)
- Binance Demo behavior of `commissionRate`: none found; marked `[ASSUMED]` (A1).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependency; SDK method read from installed source.
- Architecture: HIGH — all call sites enumerated by grep and reading; worst-case proof checked numerically.
- Pitfalls: HIGH for fixture/gate fallout (observed by running the simulator and reading the gates); MEDIUM for exact counts of tests that will need edits (confirm by running the suite after the code change).
- `commissionRate` endpoint: MEDIUM (see retrieval note); Demo behavior LOW.

**Research date:** 2026-09-30
**Valid until:** 2026-10-30 for in-repo findings (until other phases touch these files); re-verify Binance endpoint facts at Phase 24 wiring.
