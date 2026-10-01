# Phase 5: Risk Engine - Research

**Researched:** 2026-09-25
**Domain:** Deterministic position sizing / exchange quantization / portfolio gates (pure Python, Decimal-only)
**Confidence:** HIGH

## Summary

Phase 5 implements the `docs/trading/RISK_MANAGEMENT.md` risk contract verbatim as a new pure package `src/risk/` (stdlib + `Decimal` only): canonical sizing `quantity = (equity × risk_rate) / (SL_distance_per_unit + modeled_costs_per_unit)`, stepSize-floor quantization with a 60%-utilization reject gate and min-qty/notional rejects, and registry-parameterized portfolio gates (max 2 open, 1.0% aggregate, conservative V1 cluster, DAILY_STOP states) evaluated in a fixed enforcement order with first-failing-gate reason codes. All uncertain/stale state fails closed to NO_TRADE.

The phase is unusually well-specified: every decision (D-01–D-05) is locked in `05-CONTEXT.md`, the risk contract is 12 short sections, the planner input contract (`DEFERRED_TO_RISK` estimate fields) already exists in `src/core/planner.py`, the constraint-snapshot input shape already exists as `SymbolFilters` in `src/adapters/binance_usdm.py`, and the purity/test precedents (pinned-prec Decimal helpers, AST no-`float` guards, golden fixtures, tracer-first rollout) are established by Phases 3–4. The planner's main degrees of freedom are file layout inside `src/risk/`, fixture layout under `tests/fixtures/phase5/`, the exact registry key breakdown for costs/cluster/daily-state, and plan slicing (tracer sizing+quantization+parity first, then portfolio).

**Primary recommendation:** Tracer-first: plan 1 lands `size_position()` + `quantize()` + byte-identical parity fixture green; plan 2+ adds portfolio gates, DAILY_STOP state machine, registry extension, and reason-code vocabulary — all TDD, all Decimal, zero new dependencies.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Sizing follows `docs/trading/RISK_MANAGEMENT.md` §§1–3 verbatim: `allowed_risk = equity × risk_rate`, `risk_per_unit = SL_distance_per_unit + modeled_costs_per_unit`, `quantity = allowed_risk / risk_per_unit`. `risk_rate` default 0.5% of equity (research baseline, registry-owned per CONFIGURATION.md §3); SL distance derived from the Phase-4 plan (`entry_ref − stop_loss_price`, entry_ref = zone mid for LIMIT_ZONE). Modeled costs per unit include entry+exit fee + expected slippage (+ funding where applicable, Phase-6 cost-model compatible); exact cost keys are registry parameters, never hard-coded. All arithmetic in `Decimal`, tick/qty-step aware.
- **D-02:** Risk owns ALL exchange rounding: `rounded = floor(raw / step_size) × step_size` → realized-risk check (`realized_risk / allowed_risk >= minimum_risk_utilization_after_rounding`, baseline 60% per RISK_MANAGEMENT §11) → min-qty/notional reject → `QUANTIZATION_REJECT`/`NO_TRADE` preferred over round-up, never silent increase. Phase-4 planner `DEFERRED_TO_RISK` estimate fields are consumed as inputs, not re-derived; risk populates final `suggested_quantity`, `quantity_before/after_rounding`, `quantization_decision`, `realized_risk`. Identical function called in backtest/paper/live; parity golden fixture (same inputs → byte-identical outputs incl. reason codes) is CI-blocking. Raw/rounded/realized values logged per §11 rule 5.
- **D-03:** Portfolio gates from RISK_MANAGEMENT §§4–5/8 as registry parameters with research-placeholder defaults: `max_open_positions = 2`, `max_aggregate_open_risk = 1.0%`, correlated-cluster cap = conservative V1 cluster rule (directionally-aligned BTC/ETH/SOL/XRP counted as one cluster, cap = single-trade risk_rate until REFN-04 model exists), `daily_loss_stop` threshold TBD-by-researcher with states `NORMAL / WARNING / DAILY_STOP`. DAILY_STOP blocks new entries, leaves existing protectives active, raises alert. Enforcement order: per-trade sizing → cluster cap → aggregate cap → position count → daily state; first failing gate determines the reason code. Caps evaluated against live/reconciled position set, never against plan-local assumptions.
- **D-04:** Uncertain account/risk state fails closed to NO_TRADE with reason code, no new orders: unknown/stale equity, unreconciled positions/orders, missing stepSize/tick/min/notional metadata, or stale exchange-constraint snapshot (RISK_MANAGEMENT §12 fields + `metadata_observed_at_utc` with registry TTL) → reject and require revalidation before approval/execution. Never widen a protective stop silently (§6); any stop modification is explicit, logged, contract-permitted (else Phase 8/9 concern, out of scope here). No revenge/compensation logic (§7): risk never scales up after losses or missed targets.
- **D-05:** New pure package `src/risk/` under the Phase-4 D-10 purity contract: stdlib + `Decimal` only — no Polars/pandas/NumPy/SciPy, no Binance SDK types, no SQLAlchemy/Pydantic, no `float` (extend AST no-`float(` guards + mypy strict), UTC datetimes in, deterministic ordering. Exchange metadata arrives as frozen input structs via adapter edge (Phase-2 `src/data/metadata.py` shape), never fetched inside. Risk keys extend the Phase-3 `STRATEGY_KEYS` whitelist via reviewed registry change; new TOML values ship as new versioned sets, never ambient edits. Reason-code vocabulary: `QUANTIZATION_REJECT`, `MIN_QTY_REJECT`, `NOTIONAL_REJECT`, `UTILIZATION_REJECT`, `CLUSTER_CAP_REJECT`, `AGGREGATE_CAP_REJECT`, `MAX_POSITIONS_REJECT`, `DAILY_STOP_BLOCK`, `STALE_CONSTRAINTS`, `UNCERTAIN_ACCOUNT_STATE`.

### The agent's Discretion
- Exact file layout inside `src/risk/`, fixture layout under `tests/fixtures/phase5/`, per-key registry additions, cost-model key breakdown, cluster-membership rule details, daily-state transition thresholds, and plan slicing (tracer-first vs single slice) are at the planner/researcher discretion, provided D-01–D-05 semantics hold.
- Whether portfolio enforcement lands as one plan or sizing+portfolio slices is at the planner's discretion; sizing+quantization parity fixture must stay first.

### Deferred Ideas (OUT OF SCOPE)
- Backtest intrabar/SL-first/costs engine → Phase 6; WS/paper loop → Phase 7; Telegram approval + reconciliation/orphan-sweeper/SAFE_MODE rehearsal → Phase 8; live Algo exits + placement-time revalidation → Phase 9.
- Correlation model upgrade (REFN-04), OI/funding as features (REFN-02/REFN-03), 15M refinement (REFN-01), extra families (REFN-05) → v2 requirements, not Phase 5.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RISK-01 | System sizes positions from equity × risk-rate ÷ SL-distance including modeled costs, floors quantity to stepSize, rejects below the utilization threshold or minimums, and uses identical logic in backtest/paper/live | Canonical formula (§§1–3) + quantization algorithm (§11) + parity-fixture pattern below; `size_position`/`quantize` pure functions |
| RISK-02 | System enforces portfolio limits (max open positions, aggregate risk, correlated-cluster cap, DAILY_STOP states) and fails closed on uncertain account/risk state | Gate order + V1 cluster rule + daily-state machine + fail-closed input validation below; `check_portfolio` pure function |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Per-trade sizing + quantization math | In-process pure lib (`src/risk/`) | — | No I/O, no tier: identical function linked into backtest/paper/live processes |
| Portfolio cap evaluation | In-process pure lib (`src/risk/`) | — | Pure predicate over caller-supplied reconciled position snapshot; fetching state is the caller's (Phase 7/8/9) job |
| Constraint-snapshot freshness (TTL) | In-process pure lib | — | Pure comparison of `metadata_observed_at_utc` vs injected `now_utc`; clock injected, never read |
| Registry parameter loading/hashing | Domain layer (`src/domain/registry.py`) | — | Existing loader extended with new keys; risk receives a loaded `ParameterSet`, never reads TOML |
| Exchange metadata acquisition | Adapter edge (`src/adapters/`, `src/data/metadata.py`) | — | Risk receives frozen structs; never imports the SDK (D-05) |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`decimal`, `dataclasses`, `datetime`, `math.floor` via `//`) | 3.13 stdlib (pinned `==3.13.*` in `pyproject.toml`) [VERIFIED: pyproject.toml:5] | All risk arithmetic | D-05 mandates stdlib+Decimal only; zero new dependencies |
| `src/core/_decimal.py` pinned-prec helpers (`_q/_add/_sub/_mul/_div`, prec=28) [VERIFIED: src/core/_decimal.py:19-58] | Existing in-repo | Single precision source for risk ops | Established precedent (Phase-4 WR-16 fix); risk must reuse or relocate, never duplicate with drift |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `src/domain/registry.py` loader + `STRATEGY_KEYS` whitelist [VERIFIED: src/domain/registry.py:60-87] | Existing in-repo | Validate new risk keys; versioned TOML sets | Extend `STRATEGY_KEYS` + `INT_KEYS`/`DECIMAL_KEYS` via reviewed change; new values ship as new versioned sets |
| `src/domain/enums.py` `RejectionReason` + `QuantizationDecision` [VERIFIED: src/domain/enums.py:122-210] | Existing in-repo | Reason-code vocabulary | GLOSSARY §9 already carries `RISK_LIMIT`, `CORRELATED_RISK_LIMIT`, `DAILY_STOP`, `QUANTIZATION_REJECT`, `MIN_NOTIONAL_REJECT`, `EXCHANGE_CONSTRAINT`, `DATA_STALE`, `RECONCILIATION_REQUIRED`; D-05's finer codes (`MIN_QTY_REJECT`, `NOTIONAL_REJECT`, `UTILIZATION_REJECT`, `CLUSTER_CAP_REJECT`, `AGGREGATE_CAP_REJECT`, `MAX_POSITIONS_REJECT`, `DAILY_STOP_BLOCK`, `STALE_CONSTRAINTS`, `UNCERTAIN_ACCOUNT_STATE`) need a GLOSSARY + enum extension decision — either promote to `RejectionReason` or carry as module-level constants validated against `_SETUP_REASONS`-style allowlist |
| pytest + pytest-asyncio (auto) + Ruff + mypy strict [VERIFIED: pyproject.toml:33-82] | pytest>=9, mypy strict on `src/` | TDD + gates | `asyncio_mode="auto"`, AST no-`float` guard pattern in `tests/test_domain_no_float.py`, `test_metadata.py`, `test_core_planner.py` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib floor via `//` on Decimals | `math.floor(raw/step)` with floats | Floats banned for exchange-sensitive values (AGENTS.md constraint); Decimal `//` is exact |
| New `src/risk/_decimal.py` copy | Reuse `src/core/_decimal.py` | Reuse avoids the prec-50 drift bug class found in Phase-4 review (CR-04); if `src/risk/` must not import from `src/core/`, relocate helpers to a shared pure module — decide once, single source |
| `RejectionReason` enum growth | Plain-string reason codes | Strings risk synonym drift (the exact failure GLOSSARY §9 forbids); prefer enum promotion with GLOSSARY update |

**Installation:**
```bash
# No new packages. stdlib + in-repo code only (D-05).
```

**Version verification:** No external packages installed — verification N/A. Runtime pins already in `pyproject.toml` (`requires-python ==3.13.*`).

## Package Legitimacy Audit

No external packages installed in this phase (D-05: stdlib + `Decimal` only). Audit not applicable — nothing to check, remove, or flag. Planner must add a CI/purity gate instead: fail if `src/risk/` imports anything outside stdlib + `src/domain` + `src/core/_decimal.py` (or its relocated successor).

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```text
TradePlan (DEFERRED_TO_RISK estimates) ──┐
AccountState(equity, risk_rate)          ├──▶ size_position ──▶ raw_quantity
ParameterSet (risk + cost keys)          ──┘         │
                                                     ▼
ConstraintSnapshot (step/min/notional   ──▶ quantize ──▶ rounded qty ──▶ utilization/min/notional gates
  + metadata_observed_at_utc)                        │                    (QUANTIZATION_REJECT* / NO_TRADE)
                                                     ▼ sized plan fields
Reconciled positions + daily PnL        ──▶ check_portfolio ──▶ gate order:
snapshot + now_utc (all injected)                   cluster → aggregate → count → daily state
                                                     │         (first failure wins, reason code)
                                                     ▼ READY-sized plan or NO_TRADE + reason_code
```

Data-flow rules: every external fact (equity, positions, constraints, time) arrives as a frozen injected input; risk performs no I/O, reads no clock, no env, no DB, no SDK. Deterministic ordering wherever iteration occurs (sort positions by `(symbol, position_side)` before aggregation).

### Recommended Project Structure
```text
src/
├── risk/
│   ├── __init__.py        # barrel re-export, no logic (Phase-3/4 precedent)
│   ├── sizing.py          # size_position: allowed_risk / risk_per_unit (D-01)
│   ├── quantization.py    # quantize: floor + utilization + min/notional gates (D-02, §11)
│   ├── portfolio.py       # check_portfolio + daily-state machine (D-03)
│   ├── gating.py          # (optional) orchestration: sizing → quantize → portfolio, fixed gate order
│   └── types.py           # frozen input/output structs (ConstraintSnapshot, SizedResult, etc.)
├── domain/
│   ├── enums.py           # extend reason vocabulary (D-05)
│   └── registry.py        # extend STRATEGY_KEYS (D-05)
tests/
├── test_risk_sizing.py
├── test_risk_quantization.py
├── test_risk_portfolio.py
├── test_risk_parity.py       # byte-identical outputs incl. reason codes (CI-blocking)
├── test_risk_no_float.py     # extend AST guard to src/risk/
└── fixtures/
    └── phase5/               # plan + account + constraints + params → expected sized outputs
params/<family>/baseline-v2.toml  # new versioned sets carrying risk keys (never ambient edits)
```

Planner may merge `sizing.py`/`quantization.py`/`gating.py` differently; the non-negotiables are purity, gate order, and parity-fixture-first.

### Pattern 1: Canonical sizing with modeled costs (D-01)
**What:** `allowed_risk = equity × risk_rate`; `risk_per_unit = |entry_ref − stop_loss| + modeled_costs_per_unit`; `quantity = allowed_risk / risk_per_unit`, all in `Decimal` under pinned prec=28. SL distance is consumed from the Phase-4 plan (`entry_ref` = zone mid for LIMIT_ZONE, already computed by `planner.plan` [VERIFIED: src/core/planner.py:381-392]); risk never re-derives setup geometry.
**When to use:** Every new-entry sizing path; identical call in backtest/paper/live.
**Example:**
```python
# Source: docs/trading/RISK_MANAGEMENT.md §§1-3 + src/core/_decimal.py pattern
from decimal import Decimal
from src.core._decimal import _add, _div, _mul, _sub

allowed_risk = _mul(equity, risk_rate)  # equity × risk_rate
sl_distance = abs(_sub(entry_ref, stop_loss_price))  # per-unit SL distance
risk_per_unit = _add(sl_distance, modeled_costs_per_unit)  # + entry+exit fee + slippage (+funding)
if risk_per_unit <= Decimal("0"):
    return no_trade("EXCHANGE_CONSTRAINT")  # fail closed, never divide by zero
raw_quantity = _div(allowed_risk, risk_per_unit)
```

### Pattern 2: Floor-then-gate quantization (D-02, §11)
**What:** `rounded = floor(raw / step) × step` via Decimal `//` (exact, no float); then in order: min-quantity reject → notional reject (`rounded × reference_price < min_notional`) → utilization reject (`realized_risk / allowed_risk < 0.6`); never round up. Populate `quantity_before_rounding`, `quantity_after_rounding`, `quantization_decision` (`ACCEPTED`/`REJECTED` — enum values already exist [VERIFIED: src/domain/enums.py:202-210]), `realized_risk = rounded × risk_per_unit`.
**When to use:** Always after sizing; the same function in all three modes (parity fixture pins this).
**Example:**
```python
# Source: docs/trading/RISK_MANAGEMENT.md §11 algorithm + rules 1-4
steps = raw_quantity // step_size  # exact floor, Decimal
rounded = steps * step_size
if rounded < min_quantity:
    return no_trade("MIN_QTY_REJECT")  # D-05 code; map to GLOSSARY enum per planner decision
if rounded * reference_price < min_notional:
    return no_trade("NOTIONAL_REJECT")
realized_risk = rounded * risk_per_unit
if realized_risk / allowed_risk < minimum_risk_utilization_after_rounding:  # 0.6 baseline
    return no_trade("UTILIZATION_REJECT")  # == QUANTIZATION_REJECT family (§11 rule 3)
```

### Pattern 3: Ordered portfolio gates, first failure wins (D-03)
**What:** Evaluate per-trade sizing → cluster cap → aggregate cap → position count → daily state; first failing gate determines the reason code. Cluster rule V1: directionally-aligned BTC/ETH/SOL/XRP positions count as one cluster capped at single-trade `risk_rate`. Daily states `NORMAL / WARNING / DAILY_STOP` from registry thresholds; `DAILY_STOP` blocks new entries only (protectives stay active — enforced downstream, risk only emits the block + reason).
**When to use:** After a plan is sized; inputs are the reconciled position set + per-position open-risk values supplied by the caller (risk does not fetch or reconcile).
**Example:**
```python
# Source: 05-CONTEXT.md D-03 + docs/trading/RISK_MANAGEMENT.md §§4-5/8
for gate in (cluster_gate, aggregate_gate, count_gate, daily_state_gate):
    verdict = gate(sized_plan, open_positions, params, now_utc)
    if verdict.blocked:
        return no_trade(verdict.reason_code)  # first failure wins
```

### Anti-Patterns to Avoid
- **Planner pre-rounding or re-deriving SL distance:** risk consumes `DEFERRED_TO_RISK` fields as inputs [VERIFIED: src/core/planner.py:443-448, 481]; re-derivation forks the math and breaks parity.
- **Round-half-even / round-up "to meet minimums":** §11 rule 1 forbids exceeding the risk budget; below-minimum means reject, never silent increase.
- **Float anywhere on the path:** `float(quantity)`, float literals, `math.floor` on floats — 1-ulp flips NO_TRADE→order; AST guard must cover `src/risk/` (precedent: `tests/test_domain_no_float.py`, `test_core_planner.py:674-696`).
- **Ambient time/env reads:** `datetime.now()` inside `src/risk/` breaks byte-identity; `now_utc` and TTL are injected parameters.
- **Revenge/compensation scaling (§7) or silent stop-widening (§6):** explicitly out of scope; any stop change is explicit/logged/contract-permitted or it belongs to Phase 8/9.
- **Counting the candidate plan's own risk twice (or zero times) in aggregate/cluster sums:** define once whether the candidate is included in cap sums and pin with a boundary test.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Decimal precision context | Custom rounding/`getcontext()` juggling | `src/core/_decimal.py` helpers (prec=28) or single relocated copy | Ambient-context drift caused the Phase-4 CR-04 bug; one pinned source |
| Parameter loading/hashing/whitelisting | Custom TOML reader or env-var keys | `src/domain/registry.py` (`load_parameter_set`, `STRATEGY_KEYS`) | Content-hash identity + fail-closed unknown-key gates already tested; ambient strategy keys must raise `StrategyKeyOutsideRegistry` |
| Content hashing for parity fixtures | `hashlib` inline with ad-hoc separators | `src/domain/canonical.py:sha256_hex` (canonical JSON) | Byte-identity depends on canonical serialization; precedent: `make_signal_id`, `_plan_hash` |
| Exchange constraint parsing | Regex/scrape of exchangeInfo | `SymbolFilters` frozen struct via adapter edge [VERIFIED: src/adapters/binance_usdm.py:98-122] | Decimals + UTC already normalized at the boundary; risk takes the struct |
| Logging/audit trail | Custom logger | structlog (repo standard) or structured lineage log per §11 rule 5 (raw/rounded/realized) | Decision lineage must be explainable post-hoc |

**Key insight:** This phase's risk is math-forking: any second implementation of sizing/rounding (planner-side, backtest-side, live-side) silently breaks the byte-identical guarantee. One pure function, called everywhere, pinned by a CI-blocking parity fixture.

## Common Pitfalls

### Pitfall 1: Division by zero / non-positive risk_per_unit
**What goes wrong:** Zero SL distance (degenerate zone) or negative modeled costs → crash or absurd quantity.
**Why it happens:** Planner guarantees positive `risk` for its own estimate [VERIFIED: src/core/planner.py:386-392], but risk adds modeled costs and must not trust the input.
**How to avoid:** Fail closed (`EXCHANGE_CONSTRAINT` or dedicated code) when `risk_per_unit <= 0` before dividing; TDD boundary test with `sl_distance == 0` and `costs == 0`.
**Warning signs:** Any `_div` not preceded by a positivity guard.

### Pitfall 2: Utilization-gate inversion (comparing wrong ratio)
**What goes wrong:** Checking `rounded/raw >= 0.6` instead of `realized_risk/allowed_risk >= 0.6` — identical when costs are zero, divergent when costs exist, so tests pass until costs land.
**Why it happens:** §11's "60%" reads like a quantity ratio; D-02 defines it on realized risk.
**How to avoid:** Implement exactly `realized_risk / allowed_risk >= minimum_risk_utilization_after_rounding`; parity fixture MUST include a nonzero-cost case that distinguishes the two ratios.
**Warning signs:** Gate passes with costs present but no `risk_per_unit` in the expression.

### Pitfall 3: Stale-constraint comparison with naive datetimes or wrong polarity
**What goes wrong:** `metadata_observed_at_utc` naive, or TTL check backwards (rejecting fresh, accepting stale).
**Why it happens:** Timezone and subtraction-order slips; Windows dev machines lack OS zoneinfo (repo uses `tzdata` package).
**How to avoid:** UTC-aware guards on all datetime inputs (precedent: `_require_utc_aware` in `trade_plan.py`/`position.py`); `if now_utc - observed_at > ttl → STALE_CONSTRAINTS`; boundary tests at exactly TTL.
**Warning signs:** Tests only use far-fresh/far-stale timestamps, never the TTL edge.

### Pitfall 4: Non-deterministic iteration over positions
**What goes wrong:** Set/dict iteration order leaks into cluster sums or reason-code selection → parity breaks intermittently.
**Why it happens:** CPython set order depends on hashes; tests pass locally, fail in CI.
**How to avoid:** Sort positions by `(symbol, position_side)` before any aggregation; parity test runs the same input serialized in different key orders.
**Warning signs:** Any `for p in positions:` over an unordered collection without a preceding `sorted()`.

### Pitfall 5: Registry key type misclassification
**What goes wrong:** New risk key lands in neither `INT_KEYS` nor `DECIMAL_KEYS` correctly (e.g., `max_open_positions` as Decimal, `risk_rate` as int-only) → loader rejects valid sets or accepts lossy ones.
**Why it happens:** `DECIMAL_KEYS = STRATEGY_KEYS - INT_KEYS` is automatic [VERIFIED: src/domain/registry.py:240], but `INT_KEYS` membership is manual.
**How to avoid:** Count-like keys (`max_open_positions`, window/threshold counts) → `INT_KEYS`; rate/ratio/money keys → `DECIMAL_KEYS`; extend `tests/test_registry.py`-style type tests per key.
**Warning signs:** TOML `max_open_positions = 2.5` loads without error.

### Pitfall 6: Candidate-plan double-counting in caps
**What goes wrong:** Aggregate/cluster sums include or exclude the candidate inconsistently vs Phase-6/8/9 expectations.
**Why it happens:** D-03 says "caps evaluated against live/reconciled position set" — the candidate is not yet a position; the intended semantic (candidate + open ≤ cap) must be stated once.
**How to avoid:** Lock the semantic in the tracer plan (recommend: candidate risk ADDED to open-risk sums) and pin with a boundary test at exactly the cap.
**Warning signs:** No test with `open_risk + candidate_risk == cap` exact edge.

## Code Examples

### Sizing + quantize + gate orchestration skeleton
```python
# Source: composed from docs/trading/RISK_MANAGEMENT.md §§1-3,11 + 05-CONTEXT.md D-01..D-04
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class ConstraintSnapshot:  # adapter-edge shape; mirrors SymbolFilters fields
    symbol: str  # [VERIFIED: src/adapters/binance_usdm.py:108-122]
    price_tick_size: Decimal
    quantity_step_size: Decimal
    min_quantity: Decimal
    min_notional: Decimal
    metadata_observed_at_utc: datetime  # RISK_MANAGEMENT §12, UTC-aware


@dataclass(frozen=True)
class SizedResult:
    is_no_trade: bool
    quantity: Decimal | None  # final rounded qty when sized
    quantity_before_rounding: Decimal
    quantity_after_rounding: Decimal
    quantization_decision: str  # ACCEPTED / REJECTED (+ DEFERRED_TO_RISK upstream only)
    realized_risk: Decimal
    reason_code: str  # OK or D-05 vocabulary
```

### Fail-closed input validation (D-04)
```python
# Source: 05-CONTEXT.md D-04 + docs/trading/RISK_MANAGEMENT.md §§10,12
def _validate_inputs(*, equity, constraints, positions_reconciled, now_utc, ttl):
    if equity is None or equity <= Decimal("0"):
        return "UNCERTAIN_ACCOUNT_STATE"
    if not positions_reconciled:  # unreconciled → no new orders
        return "UNCERTAIN_ACCOUNT_STATE"
    if constraints is None or constraints.quantity_step_size <= 0:
        return "STALE_CONSTRAINTS"  # missing stepSize/tick/min/notional
    if now_utc - constraints.metadata_observed_at_utc > ttl:
        return "STALE_CONSTRAINTS"  # stale snapshot → revalidate
    return None
```

### Parity-fixture shape (CI-blocking, D-02)
```python
# Source: Phase-3/4 fixture precedent (tests/fixtures/phase4/expected_plans.json) + TESTING_STRATEGY golden-fixture rule
# tests/fixtures/phase5/<case>/_{input,expected}.json — input: plan fields + account + constraints + params;
# expected: quantity_before/after, quantization_decision, realized_risk, reason_code — byte-exact incl. Decimal-as-str.
# test_risk_parity.py: load → size → quantize → gate → assert canonical-JSON equality of the full output dict.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Planner-side quantity estimates as final | Planner emits `DEFERRED_TO_RISK` estimates; risk owns final math (D-02/D-09) | Phase 4 (04-03) | Phase 5 consumes estimate fields as inputs, populates final fields |
| `minimum_risk_utilization_after_rounding` reserved without reader | Wire the 60% utilization gate in `quantize()` | This phase (TOML comment marks it reserved [VERIFIED: params/trend-pullback/baseline-v1.toml:28-31]) | Rejects that were previously impossible now fire; backtest parity depends on it |
| GLOSSARY §9 coarse codes (`RISK_LIMIT`, `QUANTIZATION_REJECT`) | D-05 fine-grained codes (`UTILIZATION_REJECT`, `CLUSTER_CAP_REJECT`, …) | This phase | Planner must decide enum-promotion vs module constants + GLOSSARY update |

**Deprecated/outdated:**
- Legacy `binance-connector` / `binance-futures-connector` for constraint fetching — archived 2026-04-30; constraints arrive via the official SDK behind the adapter (STACK, HIGH confidence from prior research).
- `float` sizing math — banned repo-wide for exchange-sensitive values (AGENTS.md constraint).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Cost-model key breakdown (fee-rate entry/exit, slippage, funding keys) can be chosen by planner as new registry params [ASSUMED] | Standard Stack / Pattern 1 | Phase 6 cost-model mismatch; mitigate: name keys `fee_*`/`slippage_*`/`funding_*` and note Phase-6 compatibility as acceptance criterion |
| A2 | `daily_loss_stop` threshold + WARNING transition can be a researcher-chosen placeholder (e.g., WARNING at 50% of stop) since CONTEXT marks it TBD-by-researcher [ASSUMED] | Pattern 3 | Researcher may want different thresholds; mitigate: thresholds are registry params, changeable without code edits |
| A3 | V1 cluster membership = exact symbol set {BTC,ETH,SOL,XRP} directionally aligned; cross-symbol direction from injected position sides [ASSUMED] | Pattern 3 | Live universe is "live-5" (ROADMAP Phase 9); mitigate: cluster membership as a registry param (symbol list string), not hard-coded |
| A4 | Per-position open-risk values arrive precomputed from the caller (risk does not value positions from mark prices) [ASSUMED] | Pattern 3 | If Phase 8/9 expects risk to compute open risk from mark price, interface changes; mitigate: tracer plan locks the interface and documents it |
| A5 | New TOML sets ship as `baseline-v2.toml` per family (new versioned sets, never ambient edits) following the Phase-3/4 `params/<family>/baseline-v1.toml` layout [VERIFIED: params/trend-pullback/baseline-v1.toml:1-31 for layout; v2 naming ASSUMED] | Project Structure | Wrong version/file naming breaks fixture pins; mitigate: planner confirms naming in first plan |

## Open Questions

1. **Reason-code surfacing: enum promotion vs module constants?**
   - What we know: GLOSSARY §9 + `RejectionReason` carry coarse codes (`RISK_LIMIT`, `CORRELATED_RISK_LIMIT`, `DAILY_STOP`, `QUANTIZATION_REJECT`, `MIN_NOTIONAL_REJECT`) [VERIFIED: src/domain/enums.py:130-144]; D-05 names ten fine-grained codes.
   - What's unclear: Whether to extend `RejectionReason` + GLOSSARY (needs GLOSSARY edit, consistent with D-10 verbatim-value discipline) or keep D-05 codes as `src/risk/` constants mapped to coarse enums at the boundary.
   - Recommendation: Promote to `RejectionReason` + GLOSSARY update (one vocabulary everywhere downstream: alerts per SIGNAL_AND_ALERTS, journal rows, Telegram payloads); planner decides and records the decision.

2. **Where does the daily-PnL accumulator live?**
   - What we know: D-03 requires NORMAL/WARNING/DAILY_STOP states; risk is stateless pure math (no DB reads per D-05).
   - What's unclear: Whether the caller supplies cumulative daily loss as an injected Decimal (recommended — keeps risk pure) or risk reads journal rows (violates purity).
   - Recommendation: Inject `daily_loss_quote: Decimal | None` (None → fail closed `UNCERTAIN_ACCOUNT_STATE`); accumulation/rollover is a Phase 7/8 concern.

3. **Reference price for the notional check?**
   - What we know: `rounded × reference_price < min_notional → reject` (§11 rule 2 + §2 notional limits); plan carries `entry_min/entry_max`, zone mid is the deterministic ref (04-03 decision, STATE.md).
   - What's unclear: Whether to use zone-mid entry_ref, entry_max (conservative), or a mark price — none is named in RISK_MANAGEMENT.
   - Recommendation: Zone-mid `entry_ref` (consistent with SL-distance basis); pin in tracer with a boundary test.

## Environment Availability

Step 2.6: SKIPPED — pure in-process math phase with no external dependencies (no network, no DB, no services; stdlib + in-repo code only per D-05). Test runner (pytest>=9) and toolchain (Ruff, mypy strict) already pinned in `pyproject.toml` [VERIFIED: pyproject.toml:33-82].

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest>=9, `asyncio_mode = "auto"` [VERIFIED: pyproject.toml:46-51] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_risk_*.py -x` |
| Full suite command | `uv run pytest tests/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RISK-01 | Canonical sizing incl. modeled costs | unit (TDD) | `uv run pytest tests/test_risk_sizing.py -x` | ❌ Wave 0 |
| RISK-01 | Floor + utilization + min/notional gates, never round up | unit boundary (TDD) | `uv run pytest tests/test_risk_quantization.py -x` | ❌ Wave 0 |
| RISK-01 | Byte-identical outputs incl. reason codes (CI-blocking parity) | golden fixture | `uv run pytest tests/test_risk_parity.py -x` | ❌ Wave 0 |
| RISK-02 | Cluster → aggregate → count → daily gates, first-failure-wins | unit (TDD) | `uv run pytest tests/test_risk_portfolio.py -x` | ❌ Wave 0 |
| RISK-02 | Fail-closed on uncertain/stale (equity None, unreconciled, missing/stale constraints) | unit negative (TDD) | `uv run pytest tests/test_risk_portfolio.py -x -k fail_closed` | ❌ Wave 0 |
| RISK-01/02 | No `float(`/literal in `src/risk/`; mypy strict + Ruff clean | static gate | `uv run pytest tests/test_risk_no_float.py -x` + `mypy`/`ruff check` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_risk_*.py -x`
- **Per wave merge:** `uv run pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `src/risk/` package (sizing + quantization + portfolio + types + barrel)
- [ ] `tests/test_risk_sizing.py`, `test_risk_quantization.py`, `test_risk_portfolio.py`, `test_risk_parity.py`, `test_risk_no_float.py`
- [ ] `tests/fixtures/phase5/` golden files (at minimum: happy-path sizing, utilization-reject edge, min-qty reject, notional reject, each portfolio gate, stale-constraints, uncertain-account; nonzero-cost case per Pitfall 2)
- [ ] Registry extension: new risk keys in `STRATEGY_KEYS`/`INT_KEYS` + `params/<family>/baseline-v2.toml` sets (or planner-chosen equivalent)
- [ ] Enum/GLOSSARY extension for D-05 reason codes (or mapped-constants decision per Open Question 1)
- [ ] Framework install: none — pytest/Ruff/mypy already pinned

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth in pure math package |
| V3 Session Management | no | Stateless pure functions |
| V4 Access Control | no | No access decisions in this phase |
| V5 Input Validation | yes | Fail-closed validation of every input (None checks, Decimal typing, UTC-awareness, positivity guards); unknown registry keys raise via existing loader |
| V6 Cryptography | no | Hashing via existing `sha256_hex` only (identity, not secrecy) |

### Known Threat Patterns for pure-Decimal risk lib

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Oversized order from math error (financial integrity) | Tampering | Floor-never-round-up + utilization/min/notional gates + parity fixture; mypy strict + no-float guard |
| Stale constraints used for live sizing | Tampering / Repudiation | TTL check on `metadata_observed_at_utc` → `STALE_CONSTRAINTS`, revalidation required before approval/execution (D-04) |
| Unreconciled state sized as if certain | Tampering | `positions_reconciled` flag → `UNCERTAIN_ACCOUNT_STATE`, no new orders (RISK_MANAGEMENT §10) |
| Parameter smuggling outside registry | Tampering | `check_strategy_key_outside_registry` gate; new keys only via reviewed whitelist change |

## Project Constraints (from AGENTS.md)

- Determinism: same snapshot + account + strategy version + config = same decision; byte-equivalent outputs (parity fixture is the enforcement).
- No-AI core: LLM never decides direction/entry/SL/TP/size/risk/parameters — risk math is fixed formulas, no heuristics.
- Exchange authority: stepSize/tick/notional dynamic via exchangeInfo structs, never hard-coded; re-verify SDK surface before Phase 9, not here.
- Quantization: floor → 60% utilization → min/notional reject → NO_TRADE over round-up; identical backtest/paper/live.
- Fail closed: uncertain data/account/risk → NO_TRADE; SAFE_MODE interplay stays Phase 8.
- Tech stack: Python 3.13, Decimal/tick arithmetic for exchange-sensitive values, pytest + Ruff + mypy strict, TDD mode enabled.

## Sources

### Primary (HIGH confidence)
- `docs/trading/RISK_MANAGEMENT.md` §§1–12 — full risk contract read this session
- `src/core/planner.py:381-492` — DEFERRED_TO_RISK contract read this session
- `src/domain/registry.py:60-87,225-240` — STRATEGY_KEYS + INT/DECIMAL split read this session
- `src/domain/enums.py:122-210` — RejectionReason + QuantizationDecision values read this session
- `src/domain/trade_plan.py:46-105` — TradePlan fields read this session
- `src/core/types.py:309-327` — AccountState read this session
- `src/adapters/binance_usdm.py:98-122` — SymbolFilters fields read this session
- `src/core/_decimal.py:19-58` — pinned-prec helpers read this session
- `pyproject.toml:1-82` — interpreter pin + test/lint/type config read this session
- `05-CONTEXT.md` D-01–D-05 — locked decisions (project authority)
- `docs/configuration/CONFIGURATION.md` §3 — risk_rate + minimum_risk_utilization_after_rounding are strategy params

### Secondary (MEDIUM confidence)
- `docs/backtest/BACKTEST_SPEC.md` §§5,11,13 — cost-model + experiment-identity requirements risk must stay compatible with
- `docs/GLOSSARY.md` §9 — canonical reason codes (matches enums.py verbatim)
- Phase-4 `04-VERIFICATION.md` — DEFERRED_TO_RISK exit state assumed as input

### Tertiary (LOW confidence)
- None — no web sources needed; this phase is math + in-repo contracts, zero new libraries.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - stdlib-only, no new deps, all inputs read in-repo this session
- Architecture: HIGH - gate order, formulas, and contracts locked in CONTEXT + RISK_MANAGEMENT
- Pitfalls: HIGH - derived from reviewed Phase-3/4 failure modes (CR-04 precision drift, WR-10 reserved-key, float-guard precedents)

**Research date:** 2026-09-25
**Valid until:** 30 days (stable domain: frozen risk contract + locked decisions; only Binance SDK surface moves, and this phase does not touch it)
