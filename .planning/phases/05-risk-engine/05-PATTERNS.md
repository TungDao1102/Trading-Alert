# Phase 5: Risk Engine — Pattern Map

**Mapped:** 2026-09-25
**Files analyzed:** 17 (12 new + 5 modified)
**Analogs found:** 13 / 13 tracked (all verified via `git ls-files`)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/risk/__init__.py` | barrel | re-export | `src/core/__init__.py:25-41` | exact (pure-package barrel pattern) |
| `src/risk/types.py` | model | frozen input/output structs | `src/core/types.py:308-327` (AccountState) + `src/adapters/binance_usdm.py:99-122` (SymbolFilters) + `src/core/types.py:341-368` (PlanResult envelope) | exact (purity + UTC + Decimal guards + discriminator envelope) |
| `src/risk/sizing.py` | service | pure math (D-01) | `src/core/planner.py:443-448` (risk_budget + suggested_quantity) + `src/core/_decimal.py:33-58` (pinned-prec helpers) | exact (same formula, same helper set, same purity) |
| `src/risk/quantization.py` | service | pure math (D-02, §11) | `src/core/_decimal.py` floor discipline + `src/data/metadata.py` SymbolFilters shape + `src/domain/enums.py:202-210` QuantizationDecision | exact (floor-via-Decimal, no round-up, reason-code vocabulary extension) |
| `src/risk/portfolio.py` | service | pure gating (D-03/D-04) | `src/core/planner.py:402-409` (first-failure-wins gate loop) + `src/data/quality.py` fail-closed posture + `src/domain/canonical.py` deterministic ordering rule | exact (gate order + fail-closed + sorted-iteration) |
| `src/risk/gating.py` (optional) | service | orchestration | `src/core/planner.py:200-491` (`plan()` orchestrates features→strategy→geometry→RR) | role-match (sizing→quantize→portfolio ordered pipeline) |
| `src/domain/enums.py` *(modify)* | enum | additive vocabulary | `src/domain/enums.py:122-144` (RejectionReason) + `:202-210` (QuantizationDecision) | exact (GLOSSARY §9 verbatim-value discipline, `str, Enum` mixin) |
| `src/domain/registry.py` *(modify)* | config | whitelist extension | `src/domain/registry.py:60-87` (STRATEGY_KEYS) + `:225-240` (INT_KEYS/DECIMAL_KEYS split) | exact (D-05 key set addition, fail-closed unknown-key gate) |
| `src/domain/trade_plan.py` *(modify)* | model | field population | `src/domain/trade_plan.py:46-105` (frozen dataclass + post_init guards) | exact (risk populates final quantity/risk fields on existing shape) |
| `src/core/_decimal.py` *(reuse, not modify)* | utility | pinned prec | self — Phase-4 WR-16 single-source-of-truth | exact (reuse, do NOT duplicate; risk MUST import from `src/core/_decimal.py` per RESEARCH §Don't Hand-Roll) |
| `params/<family>/baseline-v2.toml` (×3 families) | config | versioned TOML set | `params/trend-pullback/baseline-v1.toml:1-31` | exact (new versioned set per family, never ambient edits) |
| `tests/test_risk_sizing.py` | test | TDD unit | `tests/test_core_planner.py:1-230` (full planner contract test file structure) | exact (RED→GREEN TDD, expected-vs-actual Decimal equality) |
| `tests/test_risk_quantization.py` | test | TDD unit boundary | `tests/test_metadata.py:1-324` (boundary + Decimal-exact arithmetic tests) | exact (TDD boundary tests at floor/notional/utilization edges) |
| `tests/test_risk_portfolio.py` | test | TDD unit + negative | `tests/test_core_planner.py:283-409` (RR gate first-failure-wins) + `tests/test_core_planner.py:601-670` (envelope validation) | exact (gate-order tests + fail-closed negative tests) |
| `tests/test_risk_parity.py` | test | CI-blocking golden fixture | `tests/fixtures/phase4/expected_plans.json:1-70` + `tests/conftest.py:131-160` (phase fixture loaders) | exact (byte-exact canonical-JSON equality, identical inputs → identical outputs across backtest/paper/live) |
| `tests/test_risk_no_float.py` | test | AST static guard | `tests/test_domain_no_float.py:1-95` (SCANNED_FILES list + `_find_float_calls` walker) + `tests/test_metadata.py:256-292` (`_find_float_calls` simpler walker) + `tests/test_core_planner.py:678-705` (single-file AST check) | exact (extend SCANNED_FILES list with `src/risk/*.py`, identical walker) |
| `tests/conftest.py` *(modify)* | test | shared fixture loader | `tests/conftest.py:115-160` (PHASE4_FIXTURES_DIR + phase4_* fixtures) | exact (PHASE5_FIXTURES_DIR + phase5_* loaders for parity + tombstones) |
| `tests/fixtures/phase5/` *(new directory)* | fixture | golden input/output JSON | `tests/fixtures/phase4/expected_plans.json` + `parameters.json` | exact (per-case `{input,expected}.json` triple with Decimal-as-str, `+00:00` UTC ISO timestamps) |
| `docs/GLOSSARY.md` *(modify)* | docs | canonical enum source-of-truth | `docs/GLOSSARY.md` §9 (current reason-code vocabulary) | exact (additive extension per `src/domain/enums.py` enum-promotion decision in RESEARCH §Open Questions) |

## Pattern Assignments

### `src/risk/__init__.py` (barrel — re-export only)

**Analog:** `src/core/__init__.py:1-41`

**Imports pattern** (`src/core/__init__.py:13-23`):
```python
"""Pure-core package — feature engine, strategy function, planner (Phase 4, plan 04-01).

Per D-01/D-10: the pure core imports NOTHING from Polars/pandas/NumPy/Binance
SDK/SQLAlchemy/Pydantic — stdlib + Decimal only, mirroring the Phase-3 D-01
domain purity precedent. This barrel re-exports the public symbols.

The package is dependency-free by construction. Any future plan that wants
to add a third-party dependency here must first lift D-10.
"""
from __future__ import annotations

from .features import compute_features, ema_update, true_range
from .planner import plan
from .strategy import evaluate
from .types import (
    AccountState,
    Candle,
    FeatureFrame,
    FeatureOutput,
    MarketSnapshot,
    SetupResult,
)

__all__ = [
    # Types
    "Candle",
    "FeatureOutput",
    "FeatureFrame",
    "SetupResult",
    "MarketSnapshot",
    "AccountState",
    # Features
    "compute_features",
    "ema_update",
    "true_range",
    # Strategy
    "evaluate",
    # Planner
    "plan",
]
```

**Apply to risk barrel:** module docstring stating D-05 purity contract (stdlib + Decimal + `src/core/_decimal.py` only), re-export `size_position`, `quantize`, `check_portfolio`, `RiskInputs`/`SizedResult`/`PortfolioVerdict` types, empty logic body. D-05's purity rule must be stated in the docstring so the AST no-float guard has a discoverable contract.

---

### `src/risk/types.py` (model — frozen dataclasses + UTC + Decimal guards)

**Analog:** `src/core/types.py:308-368` (AccountState + PlanResult envelope) + `src/adapters/binance_usdm.py:99-122` (SymbolFilters frozen struct mirroring exchangeInfo fields)

**Validation helpers** (`src/core/types.py:32-59`):
```python
def _require_non_empty(value: str, field_name: str) -> None:
    """Reject empty strings for validated non-empty fields."""
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive and non-UTC datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(
            f"{field_name} must be UTC, got offset {value.utcoffset()}"
        )


def _require_decimal(value: object, field_name: str) -> None:
    """Reject non-Decimal values for money/qty/price fields (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(
            f"{field_name} must be Decimal, got {type(value).__name__}"
        )


def _require_positive(value: Decimal, field_name: str) -> None:
    """Reject non-positive Decimals (D-04 fail-closed)."""
    if value <= Decimal("0"):
        raise ValueError(f"{field_name} must be > 0, got {value}")
```

**AccountState pattern** (`src/core/types.py:308-328`):
```python
@dataclass(frozen=True)
class AccountState:
    """Minimal account view the pure core needs (D-07/Phase 5 expands).

    `equity` is the current account equity in quote currency. `risk_rate`
    is the per-trade equity fraction. Both are Decimal; all strategy
    arithmetic stays in Decimal.
    """

    equity: Decimal
    risk_rate: Decimal

    def __post_init__(self) -> None:
        _require_decimal(self.equity, "equity")
        _require_decimal(self.risk_rate, "risk_rate")
        _require_positive(self.equity, "equity")
        if not (Decimal("0") < self.risk_rate <= Decimal("1")):
            raise ValueError(
                f"risk_rate {self.risk_rate} must be in (0, 1]"
            )
```

**PlanResult discriminator envelope** (`src/core/types.py:341-368`):
```python
@dataclass(frozen=True)
class PlanResult:
    """Discriminated NO_TRADE-or-TradePlan envelope emitted by `planner.plan`.

    `is_no_trade=True` carries a canonical `RejectionReason` value in
    `reason_code`; `is_no_trade=False` carries a fully populated TradePlan.
    """

    is_no_trade: bool
    trade_plan: TradePlan | None = None
    reason_code: str = "OK"

    def __post_init__(self) -> None:
        _require_non_empty(self.reason_code, "reason_code")
        if self.is_no_trade:
            if self.trade_plan is not None:
                raise ValueError(
                    "PlanResult: is_no_trade=True requires trade_plan=None"
                )
        else:
            if self.trade_plan is None:
                raise ValueError(
                    "PlanResult: is_no_trade=False requires a TradePlan"
                )
```

**SymbolFilters mirror** (`src/adapters/binance_usdm.py:99-122`):
```python
@dataclass(frozen=True)
class SymbolFilters:
    """Snapshot of the exchangeInfo filters for one symbol.

    Decimals for all numeric filter fields (Pitfall 4 — no float). The
    raw filter list and full symbol record are retained as JSON blobs so
    later plans (position-mode, leverage brackets) can pull additional
    fields without re-querying.
    """

    symbol: str
    contract_type: str
    status: str
    onboard_time_utc: datetime | None
    price_tick_size: Decimal
    quantity_step_size: Decimal
    min_quantity: Decimal
    max_quantity: Decimal | None
    min_notional: Decimal
    base_asset: str
    quote_asset: str
    margin_asset: str
    notional_constraints_json: str
    order_capabilities_json: str
    position_mode_snapshot_json: str
```

**Apply to `src/risk/types.py`:** Copy the validation helper quartet verbatim into `src/risk/types.py` (each Phase layer keeps its own guards per `src/core/types.py:26-29` docstring rationale; never share). Define three frozen dataclasses:
- `ConstraintSnapshot` — mirrors SymbolFilters fields actually consumed (`symbol`, `price_tick_size`, `quantity_step_size`, `min_quantity`, `min_notional`, `metadata_observed_at_utc` UTC-aware); rejects `step_size <= 0` and `min_quantity <= 0` via `_require_positive`.
- `RiskInputs` — frozen bundle of `trade_plan: TradePlan` + `account_state: AccountState` + `constraint_snapshot: ConstraintSnapshot` + `parameter_set: ParameterSet` + `now_utc: datetime` + optional `positions_reconciled: bool` + `daily_loss_quote: Decimal | None`; rejects naive `now_utc`.
- `SizedResult` — `is_no_trade: bool` + `quantity: Decimal | None` + `quantity_before_rounding: Decimal` + `quantity_after_rounding: Decimal` + `quantization_decision: QuantizationDecision` + `realized_risk: Decimal` + `reason_code: str` (canonical RejectionReason value or D-05 fine-grained code); envelope validates `is_no_trade=True → quantity is None` per `PlanResult` discipline.

---

### `src/risk/sizing.py` (service — D-01 canonical formula)

**Analog:** `src/core/planner.py:443-448` (current pre-quantization sizing estimate) + `src/core/_decimal.py:33-58` (pinned-prec helpers)

**Pre-quantization risk_budget math** (`src/core/planner.py:443-448`):
```python
# Quantization estimates (D-09: DEFERRED_TO_RISK; Phase 5 owns stepSize math).
risk_budget = _mul(account_state.equity, risk_rate)
# suggested_quantity = risk_budget / risk (pre-rounding; Phase 5 floors).
suggested_quantity = _div(risk_budget, risk)
quantity_before_rounding = suggested_quantity
quantity_after_rounding = suggested_quantity  # Phase 5 floors; planner passes through
```

**Pinned-prec helpers to reuse** (`src/core/_decimal.py:22-58`):
```python
_PREC = 28

def _q(x: Decimal | int | str) -> Decimal:
    """Build a Decimal from a string/int (never from a float)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, str):
        return Decimal(x)
    raise TypeError(f"_q: unsupported type {type(x).__name__}")


def _div(a: Decimal, b: Decimal) -> Decimal:
    """Divide two Decimals under a pinned local context (D-10)."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        return a / b


def _mul(a: Decimal, b: Decimal) -> Decimal:
    """Multiply two Decimals under a pinned local context."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        return a * b


def _add(a: Decimal, b: Decimal) -> Decimal:
    """Add two Decimals under a pinned local context."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        return a + b


def _sub(a: Decimal, b: Decimal) -> Decimal:
    """Subtract two Decimals under a pinned local context."""
    with localcontext() as ctx:
        ctx.prec = _PREC
        return a - b
```

**Apply to `size_position()`:** Signature `(*, equity: Decimal, risk_rate: Decimal, entry_ref: Decimal, stop_loss: Decimal, modeled_costs_per_unit: Decimal) -> SizedResult` (pure — no clock, no I/O). Internals:
1. Validate inputs: `equity > 0`, `risk_rate ∈ (0, 1]`, `entry_ref != 0`, `stop_loss != 0`, `modeled_costs_per_unit >= 0`; negative `risk_per_unit` or zero → return `SizedResult(is_no_trade=True, reason_code=EXCHANGE_CONSTRAINT, …)` (Pitfall 1 mitigation).
2. Compute `allowed_risk = _mul(equity, risk_rate)`, `sl_distance = abs(_sub(entry_ref, stop_loss))`, `risk_per_unit = _add(sl_distance, modeled_costs_per_unit)`, `raw_quantity = _div(allowed_risk, risk_per_unit)`.
3. Return `SizedResult` with `quantity_before_rounding = raw_quantity`, `quantity_after_rounding = raw_quantity` (passthrough — quantization owns the floor in `quantization.py`), `quantization_decision = DEFERRED_TO_RISK` from `QuantizationDecision` enum, `realized_risk = raw_quantity * risk_per_unit` (or `allowed_risk` exactly), `reason_code = "OK"`. NEVER import the SDK, NEVER read a clock.

**Decision reference:** D-01 + RESEARCH §Pattern 1 (lines 135-150) + Pitfall 1 (zero SL distance → EXCHANGE_CONSTRAINT fail closed).

---

### `src/risk/quantization.py` (service — D-02, §11 floor + utilization + min/notional)

**Analog:** `src/domain/enums.py:202-210` (QuantizationDecision enum values) + `src/core/_decimal.py` floor discipline + `src/data/metadata.py:60-89` (Decimal-from-string handling)

**QuantizationDecision enum** (`src/domain/enums.py:202-210`):
```python
class QuantizationDecision(str, Enum):
    """GLOSSARY — Quantization decision (D-06 promotion, D-09 deferral).

    `DEFERRED_TO_RISK` is the V1 default — Phase 5 owns stepSize math.
    """

    DEFERRED_TO_RISK = "DEFERRED_TO_RISK"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
```

**SymbolFilters fields consumed** (`src/adapters/binance_usdm.py:108-119`):
```python
symbol: str
price_tick_size: Decimal
quantity_step_size: Decimal
min_quantity: Decimal
max_quantity: Decimal | None
min_notional: Decimal
```

**Apply to `quantize()`:** Signature `(*, sized: SizedResult, constraint_snapshot: ConstraintSnapshot, allowed_risk: Decimal, risk_per_unit: Decimal, minimum_risk_utilization_after_rounding: Decimal, reference_price: Decimal) -> SizedResult` (pure). Internals — exact §11 algorithm:
1. `steps = raw_quantity // quantity_step_size` (Decimal `//` is exact floor, never round-up — Pitfall 2 mitigation).
2. `rounded = steps * quantity_step_size`.
3. Gate order (first failure wins per D-02):
   - `rounded < min_quantity` → `reason_code = "MIN_QTY_REJECT"` (D-05 fine-grained; per planner decision may promote to `RejectionReason` + GLOSSARY update).
   - `rounded * reference_price < min_notional` → `reason_code = "NOTIONAL_REJECT"`.
   - `realized_risk = rounded * risk_per_unit`; if `realized_risk / allowed_risk < minimum_risk_utilization_after_rounding` (0.6 baseline) → `reason_code = "UTILIZATION_REJECT"` (Pitfall 2: the ratio uses `realized_risk/allowed_risk`, NOT `rounded/raw_quantity` — parity fixture MUST include a nonzero-cost case).
4. On any reject: return `SizedResult(is_no_trade=True, quantity=None, quantity_before_rounding=sized.quantity_before_rounding, quantity_after_rounding=rounded, quantization_decision=REJECTED, realized_risk=realized_risk, reason_code=...)`.
5. On accept: return `SizedResult(is_no_trade=False, quantity=rounded, quantity_before_rounding=sized.quantity_before_rounding, quantity_after_rounding=rounded, quantization_decision=ACCEPTED, realized_risk=realized_risk, reason_code="OK")`.

**Strict rules:**
- Floor via `Decimal // step_size` only (never `math.floor(raw/step)` — floats banned).
- Never round up to meet minimums (§11 rule 1 + RISK_MANAGEMENT §11).
- Log raw/rounded/realized per §11 rule 5 via `structlog.get_logger().info("risk.quantize", raw=..., rounded=..., realized_risk=...)` (RECOMMENDED but not gating — see RES-04 standard logger precedent).
- Reason-code vocabulary: prefer `RejectionReason` enum-promotion (RESEARCH §Open Question 1 — recommendation) — if promoted, add `MIN_QTY_REJECT = "MIN_QTY_REJECT"`, `NOTIONAL_REJECT = "NOTIONAL_REJECT"`, `UTILIZATION_REJECT = "UTILIZATION_REJECT"` to `src/domain/enums.py:122-144`. Otherwise carry as module-level constants in `src/risk/quantization.py` mapped to coarse `RejectionReason` values at the planner-decision boundary.

---

### `src/risk/portfolio.py` (service — D-03 portfolio gates + DAILY_STOP + D-04 fail-closed)

**Analog:** `src/core/planner.py:402-409` (first-failure-wins gate loop) + `src/data/quality.py` fail-closed posture + `src/domain/canonical.py` deterministic ordering

**First-failure-wins gate loop pattern** (`src/core/planner.py:402-409`):
```python
# RR gate — TP1 is structure-derived, so this gate can fire (CR-03).
realized_rr = _div(abs(_sub(tp1, entry_ref)), risk)
if realized_rr < minimum_rr:
    return PlanResult(
        is_no_trade=True,
        trade_plan=None,
        reason_code=RejectionReason.RR_TOO_LOW.value,
    )
```

**UTC-aware datetime guards** (`src/domain/position.py:35-42`):
```python
def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive and non-UTC datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(
            f"{field_name} must be UTC, got offset {value.utcoffset()}"
        )
```

**Apply to `check_portfolio()`:** Signature `(*, sized: SizedResult, candidate_risk: Decimal, open_positions: Sequence[OpenPosition], daily_loss_quote: Decimal | None, parameter_set: ParameterSet, now_utc: datetime, ttl: timedelta) -> PortfolioVerdict` (pure — sorts positions deterministically per Pitfall 4).

1. **Input validation (D-04 fail-closed):**
   - `equity` not passed (consumed upstream) — but `daily_loss_quote is None` → `reason_code = "UNCERTAIN_ACCOUNT_STATE"`.
   - `sized.realized_risk > 0` else fail closed (defensive).
   - `_require_utc_aware(now_utc, "now_utc")`; `_require_utc_aware(constraint_snapshot.metadata_observed_at_utc, ...)`; `now_utc - observed_at > ttl` → `reason_code = "STALE_CONSTRAINTS"` (Pitfall 3 — UTC-aware subtraction only).
   - `open_positions` sorted by `(symbol, position_side)` before any aggregation (Pitfall 4 — non-deterministic iteration).

2. **Gate order (D-03 — first failure wins, fixed order):**
   - **Cluster gate:** directionally-aligned BTCUSDT/ETHUSDT/SOLUSDT/XRPUSDT counted as one cluster (V1 conservative rule from RESEARCH A3); if `cluster_open_risk + candidate_risk > cluster_cap` (single-trade `risk_rate` until REFN-04) → `reason_code = "CLUSTER_CAP_REJECT"`.
   - **Aggregate gate:** `aggregate_open_risk + candidate_risk > max_aggregate_open_risk` (default 1.0%) → `reason_code = "AGGREGATE_CAP_REJECT"`. Boundary: `== cap` is PASS per `>= cap` semantics; pin with boundary test at exact cap.
   - **Position count gate:** `len(open_positions) >= max_open_positions` (default 2) → `reason_code = "MAX_POSITIONS_REJECT"`. Decision: count OPEN positions only (candidate is not yet a position); `candidate_risk` is NOT in the count, only its realized risk in aggregates (Pitfall 6 — document this once in the tracer plan + boundary test).
   - **Daily state gate:** derive `state` from `daily_loss_quote` vs `daily_loss_stop_threshold` (and WARNING midpoint e.g. 50% of stop per RESEARCH A2); if `state == DAILY_STOP` → `reason_code = "DAILY_STOP_BLOCK"`.

3. **On pass:** `PortfolioVerdict(is_no_trade=False, sized=sized, reason_code="OK", daily_state=state)`.
4. **On fail:** `PortfolioVerdict(is_no_trade=True, sized=None, reason_code=<gate code>, daily_state=state)`.

**DailyState enum** (NEW in `src/domain/enums.py`): `class DailyState(str, Enum): NORMAL = "NORMAL"; WARNING = "WARNING"; DAILY_STOP = "DAILY_STOP"` — copy verbatim from RISK_MANAGEMENT §8 + docs/GLOSSARY.md §8 (SystemMode precedent: `src/domain/enums.py:107-119`).

**OpenPosition frozen struct** (in `src/risk/types.py` or shared): `(symbol: str, position_side: str, open_risk: Decimal, daily_pnl_contribution: Decimal)` — Decimal money fields, UTC datetimes, sorted by `(symbol, position_side)`.

---

### `src/risk/gating.py` (optional service — orchestration)

**Analog:** `src/core/planner.py:200-491` (the `plan()` function orchestrates features→strategy→geometry→RR→TradePlan in fixed order)

**Apply to `evaluate_risk()`:** Signature `(*, trade_plan: TradePlan, account_state: AccountState, constraint_snapshot: ConstraintSnapshot, parameter_set: ParameterSet, open_positions: Sequence[OpenPosition], daily_loss_quote: Decimal | None, now_utc: datetime, ttl: timedelta, modeled_costs_per_unit: Decimal) -> PortfolioVerdict`. Pipeline in fixed order:
1. `size_position()` → `SizedResult`.
2. `quantize()` → `SizedResult` (possibly `is_no_trade=True` with quantization reject).
3. If still `is_no_trade=False`: `check_portfolio()` → `PortfolioVerdict`.
4. Return `PortfolioVerdict` (single envelope; caller unwraps `sized.trade_plan` for downstream consumers).

**Decision (planner-discretion):** may be merged into a single `evaluate_risk()` function in `src/risk/sizing.py` if the layering feels heavy — non-negotiables are purity, gate order, and the parity fixture (RESEARCH §Recommended Project Structure).

---

### `src/domain/enums.py` *(modify)* — extend RejectionReason + new DailyState enum

**Analog:** `src/domain/enums.py:122-144` (existing RejectionReason enum) + `:202-210` (QuantizationDecision additive extension)

**Current RejectionReason enum** (`src/domain/enums.py:122-144`):
```python
class RejectionReason(str, Enum):
    """GLOSSARY §9 — Canonical rejection reasons.

    Do not create synonyms such as `Skipped-User`, `USER_SKIPPED`, and
    `SKIPPED_USER` in different modules. Use the canonical enum names
    above.
    """

    NO_TRADE_REGIME = "NO_TRADE_REGIME"
    RR_TOO_LOW = "RR_TOO_LOW"
    STALE_SETUP = "STALE_SETUP"
    INVALIDATED = "INVALIDATED"
    RISK_LIMIT = "RISK_LIMIT"
    CORRELATED_RISK_LIMIT = "CORRELATED_RISK_LIMIT"
    DAILY_STOP = "DAILY_STOP"
    QUANTIZATION_REJECT = "QUANTIZATION_REJECT"
    MIN_NOTIONAL_REJECT = "MIN_NOTIONAL_REJECT"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    EXCHANGE_CONSTRAINT = "EXCHANGE_CONSTRAINT"
    DATA_STALE = "DATA_STALE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
```

**Apply:** Add the D-05 fine-grained codes (verbatim values — D-10 discipline):
```python
# Phase 5 D-05 additions — extend GLOSSARY §9 to match.
QUANTIZATION_REJECT = ...   # already present, retained
MIN_QTY_REJECT = "MIN_QTY_REJECT"
NOTIONAL_REJECT = "NOTIONAL_REJECT"
UTILIZATION_REJECT = "UTILIZATION_REJECT"
CLUSTER_CAP_REJECT = "CLUSTER_CAP_REJECT"
AGGREGATE_CAP_REJECT = "AGGREGATE_CAP_REJECT"
MAX_POSITIONS_REJECT = "MAX_POSITIONS_REJECT"
DAILY_STOP_BLOCK = "DAILY_STOP_BLOCK"  # distinct from existing DAILY_STOP per D-03
STALE_CONSTRAINTS = "STALE_CONSTRAINTS"
UNCERTAIN_ACCOUNT_STATE = "UNCERTAIN_ACCOUNT_STATE"
```

**Plus new `DailyState` enum** (mirrors `SystemMode` style at `src/domain/enums.py:107-119`):
```python
class DailyState(str, Enum):
    """GLOSSARY §8 — Daily PnL state machine (D-03)."""
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    DAILY_STOP = "DAILY_STOP"
```

**Decision (per RESEARCH §Open Question 1):** recommended path is enum promotion + GLOSSARY.md §9 update so SIGNAL_AND_ALERTS.md + journal rows + Telegram payloads all read from one vocabulary. Planner may instead carry as module constants mapped to coarse enums at the boundary — either is acceptable, but the decision must be recorded once in the first plan and applied consistently.

---

### `src/domain/registry.py` *(modify)* — extend STRATEGY_KEYS + INT_KEYS

**Analog:** `src/domain/registry.py:60-87` (STRATEGY_KEYS frozenset) + `:225-240` (INT_KEYS frozenset)

**STRATEGY_KEYS addition** (extend existing set at `src/domain/registry.py:60-87`):
```python
STRATEGY_KEYS = frozenset(
    {
        "swing_lookback",
        "zone_tolerance_atr",
        "breakout_confirmation_bars",
        "entry_buffer_atr",
        "sl_buffer_atr",
        "minimum_rr",
        "signal_expiry_hours",
        "risk_rate",
        "minimum_risk_utilization_after_rounding",
        # Family B (breakout-retest) — added in plan 04-03 (D-05).
        "retest_window_bars",
        "retest_depth_atr",
        "breakout_volume_threshold",
        # Family C (range-mr) — added in plan 04-03 (D-05).
        "zone_min_touches",
        "zone_aging_bars",
        "range_break_buffer_atr",
        "regime_filter_lookback",
        # Detector volatility knobs — promoted to the registry in the
        # Phase 04 review fix (CR-01). Previously silent `.get()`
        # code defaults in the Family B/C detectors; now versioned
        # parameters that fail closed (KeyError) when absent.
        "atr_period",
        "touch_tolerance_atr",
        # ----- Phase 5 D-05 additions (D-03 portfolio + cost model) -----
        # Portfolio gates (research baselines per RISK_MANAGEMENT §§4-5).
        "max_open_positions",
        "max_aggregate_open_risk",
        "cluster_cap",
        # Daily PnL state machine (RISK_MANAGEMENT §8).
        "daily_loss_warning_threshold",
        "daily_loss_stop_threshold",
        # Cost model keys (RISK_MANAGEMENT §3) — Phase-6-compatible.
        "fee_rate_entry",
        "fee_rate_exit",
        "expected_slippage",
        # Constraint-snapshot freshness (RISK_MANAGEMENT §12).
        "constraint_snapshot_ttl_seconds",
    }
)
```

**INT_KEYS addition** (extend existing set at `src/domain/registry.py:225-240`):
```python
INT_KEYS = frozenset(
    {
        "swing_lookback",
        "breakout_confirmation_bars",
        "signal_expiry_hours",
        # Family B (breakout-retest) — added in plan 04-03 (D-05).
        "retest_window_bars",
        # Family C (range-mr) — added in plan 04-03 (D-05).
        "zone_min_touches",
        "zone_aging_bars",
        "regime_filter_lookback",
        # Detector volatility knob — Phase 04 review fix (CR-01).
        "atr_period",
        # ----- Phase 5 D-05 additions -----
        "max_open_positions",                      # count, not a rate
        "constraint_snapshot_ttl_seconds",         # duration in seconds
    }
)
```

**Pitfall 5 mitigation:** count-like keys (`max_open_positions`, `constraint_snapshot_ttl_seconds`) → `INT_KEYS`; rate/ratio/money/cost keys → `DECIMAL_KEYS` (automatic via `DECIMAL_KEYS = STRATEGY_KEYS - INT_KEYS` at `src/domain/registry.py:240`). Pin with `tests/test_registry.py`-style type tests per key — TOML `max_open_positions = 2.5` must NOT load.

---

### `src/domain/trade_plan.py` *(modify)* — no shape changes, populate existing fields

**Analog:** `src/domain/trade_plan.py:46-105` (existing TradePlan shape)

**Existing TradePlan shape** (`src/domain/trade_plan.py:46-78`):
```python
@dataclass(frozen=True)
class TradePlan:
    """The executable interpretation of one signal (DATA_MODEL §2.4).
    ...
    """

    trade_plan_id: str
    signal_id: str  # FK to Signal
    trade_plan_version: str
    entry_model: str  # validated non-empty string (Phase 4 may promote to Enum)
    entry_min_price: Decimal
    entry_max_price: Decimal
    stop_loss_price: Decimal
    take_profit_json: str  # JSON-as-TEXT
    invalidation_rule_json: str  # JSON-as-TEXT
    expiry_utc: datetime  # aware UTC
    expected_rr_json: str  # JSON-as-TEXT
    risk_rate: Decimal
    risk_budget: Decimal
    suggested_quantity: Decimal
    quantity_before_rounding: Decimal
    quantity_after_rounding: Decimal
    quantization_decision: str  # validated non-empty string
    plan_hash: str
    status: TradePlanStatus  # explicit — never inferred (D-11)
    created_at_utc: datetime  # aware UTC
```

**Apply:** NO structural change to `TradePlan` (per D-02 — risk populates existing fields, never adds new ones). The Phase-5 risk pipeline produces a NEW TradePlan via `dataclasses.replace(plan, suggested_quantity=..., quantity_before_rounding=..., quantity_after_rounding=..., quantization_decision=ACCEPTED/REJECTED.value, risk_rate=...)` (frozen, so `replace` is required — `dataclasses.replace` precedent at `src/domain/trade_plan.py` post_init guards).

**Decision:** Optional enum-typed `quantization_decision: QuantizationDecision` promotion is planner-discretion (RESEARCH §Open Question 1 secondary). Keep as `str` (current shape) with validated value in `[DEFERRED_TO_RISK, ACCEPTED, REJECTED]` is acceptable; enum promotion is preferred for downstream type safety.

---

### `params/<family>/baseline-v2.toml` (×3 families — config)

**Analog:** `params/trend-pullback/baseline-v1.toml:1-31`

**Seed TOML layout** (`params/trend-pullback/baseline-v1.toml`):
```toml
# params/trend-pullback/baseline-v1.toml
#
# Seed parameter set for the trend-pullback strategy (Phase 3, plan 03-01).
#
# Per D-04: this file is the source of truth for the parameter set.
# Once referenced by a backtest/alert/order plan, its hash is permanent.
# Do not mutate — create a new parameter set + bump strategy version.
#
# Per D-06: strategy-semantic parameters live ONLY in the registry.
# Runtime config (endpoints, tokens, DB refs, log levels, poll intervals)
# lives in env/secret stores and must never silently alter strategy semantics.

schema_version = 1

[strategy]
strategy_id = "trend-pullback"
strategy_version = "v1.0.0"

[parameters]
swing_lookback = 20
zone_tolerance_atr = 0.5
breakout_confirmation_bars = 3
entry_buffer_atr = 0.1
sl_buffer_atr = 0.2
minimum_rr = 2.0
signal_expiry_hours = 4
risk_rate = 0.005
# RESERVED (review WR-10): minimum_risk_utilization_after_rounding has no
# reader in src/ — no utilization gate exists yet. Wiring belongs to the
# Phase 5 risk/quantization work. Do not assume an active gate.
minimum_risk_utilization_after_rounding = 0.6
```

**Apply:** Create `params/<family>/baseline-v2.toml` for each of `trend-pullback`, `breakout-retest`, `range-mr`. Strategy version bumps to `v2.0.0` (RESEARCH A5). Inherit v1 keys + add D-05 keys:
```toml
schema_version = 1

[strategy]
strategy_id = "trend-pullback"
strategy_version = "v2.0.0"

[parameters]
# Inherited from baseline-v1.
swing_lookback = 20
zone_tolerance_atr = 0.5
breakout_confirmation_bars = 3
entry_buffer_atr = 0.1
sl_buffer_atr = 0.2
minimum_rr = 2.0
signal_expiry_hours = 4
risk_rate = 0.005
minimum_risk_utilization_after_rounding = 0.6

# Family-specific knobs (inherited from v1, kept intact).
retest_window_bars = 8
retest_depth_atr = 0.3
breakout_volume_threshold = 1.5
zone_min_touches = 3
zone_aging_bars = 24
range_break_buffer_atr = 0.3
regime_filter_lookback = 100
atr_period = 14
touch_tolerance_atr = 0.2

# ----- Phase 5 additions -----
# Portfolio gates (RISK_MANAGEMENT §§4-5 research baselines).
max_open_positions = 2
max_aggregate_open_risk = 0.01          # 1.0%
cluster_cap = 0.005                     # single-trade risk_rate
# Daily PnL state machine (RISK_MANAGEMENT §8).
daily_loss_warning_threshold = 0.005    # WARNING at 50% of stop
daily_loss_stop_threshold = 0.01        # DAILY_STOP at 1.0% of equity
# Cost model keys (RISK_MANAGEMENT §3) — Phase-6-compatible.
fee_rate_entry = 0.0002                 # 2 bps maker
fee_rate_exit = 0.0005                  # 5 bps taker
expected_slippage = 0.0001              # 1 bps
# Constraint-snapshot freshness (RISK_MANAGEMENT §12).
constraint_snapshot_ttl_seconds = 3600  # 1 hour
```

**Naming decision (RESEARCH A5):** new versioned sets (`baseline-v2.toml`) per family; never ambient edits to `baseline-v1.toml`. `parameter_set_hash` changes on every edit — old hashes remain in journal rows for historical replay.

---

### `tests/test_risk_sizing.py` (TDD unit)

**Analog:** `tests/test_core_planner.py:1-230` (full planner contract test file structure)

**Test scaffold pattern** (`tests/test_core_planner.py:26-67`):
```python
import csv
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from src.core.features import compute_features
from src.core.planner import plan
from src.core.types import AccountState, Candle, PlanResult
from src.domain.canonical import sha256_hex
from src.domain.enums import RejectionReason, TradePlanStatus
from src.domain.ids import derive_child_id
from src.domain.registry import ParameterSet, load_parameter_set


def _build_candles_from_csv(rows: list[dict]) -> list[Candle]:
    """Convert CSV dict rows to Candle objects."""
    candles: list[Candle] = []
    for row in rows:
        open_time = datetime.fromisoformat(row["open_time_utc"].replace("Z", "+00:00"))
        ...
```

**Apply:** Test file structure:
- **Header docstring:** state D-01 contract (formula + D-12 Decimal-only + TDD RED→GREEN).
- **Helpers:** `_mk_account_state(equity, risk_rate)`, `_mk_trade_plan(side, entry_ref, stop_loss)` (returns a frozen `TradePlan` with `quantization_decision="DEFERRED_TO_RISK"`), `_mk_risk_inputs(...)`.
- **Tests:** (1) happy-path LONG sizing matches `allowed_risk / risk_per_unit` byte-exactly; (2) zero SL distance → `EXCHANGE_CONSTRAINT` fail closed (Pitfall 1); (3) zero `risk_rate` → invalid `AccountState` post_init; (4) negative costs → handled per RISK_MANAGEMENT §3 sign convention (test must pin); (5) Decimal arithmetic byte-identical across two runs (parity subset).

---

### `tests/test_risk_quantization.py` (TDD boundary)

**Analog:** `tests/test_metadata.py:1-324` (boundary + Decimal-exact arithmetic tests)

**SymbolFilters helper** (`tests/test_metadata.py:38-67`):
```python
def _mk_filters(
    symbol: str,
    *,
    tick: str = "0.10",
    step: str = "0.001",
    min_notional: str = "50",
) -> SymbolFilters:
    """Build a SymbolFilters instance for tests.

    Defaults match the live-5 Binance USDⓈ-M perpetual contract shape:
    tick=0.10, step=0.001, min_notional=50 USDT.
    """
    base_asset = symbol[:-4] if symbol.endswith("USDT") else symbol
    return SymbolFilters(
        symbol=symbol,
        contract_type="PERPETUAL",
        status="TRADING",
        onboard_time_utc=datetime(2020, 1, 1, tzinfo=UTC),
        price_tick_size=Decimal(tick),
        quantity_step_size=Decimal(step),
        min_quantity=Decimal(step),
        max_quantity=Decimal("1000"),
        min_notional=Decimal(min_notional),
        base_asset=base_asset,
        quote_asset="USDT",
        margin_asset="USDT",
        notional_constraints_json='{"filterType":"MIN_NOTIONAL","notional":"50"}',
        order_capabilities_json='{"order_types":["LIMIT","MARKET"]}',
        position_mode_snapshot_json='{"pricePrecision":2,"quantityPrecision":3}',
    )
```

**Apply:** Boundary tests at:
1. **Floor exact step** — `raw == steps × step_size` → `rounded == raw` → ACCEPTED.
2. **Floor one ULP below** — `raw = steps × step_size + 1 ulp` → rounds DOWN to next step → ACCEPTED (verify the one-ULP doesn't flip).
3. **Below min_qty** — `rounded < min_quantity` → `MIN_QTY_REJECT`.
4. **Below min_notional** — `rounded × reference_price < min_notional` → `NOTIONAL_REJECT`.
5. **Below utilization threshold** (60%) with NONZERO costs — `rounded × risk_per_unit / allowed_risk < 0.6` → `UTILIZATION_REJECT` (Pitfall 2 — MUST distinguish from `rounded/raw_quantity` ratio; parity fixture pins this).
6. **Utilization exact equality** — `rounded × risk_per_unit / allowed_risk == 0.6` → ACCEPTED (boundary pin).
7. **Reference price zero / negative** → fail closed.
8. **`quantity_step_size == 0`** → fail closed (defensive — adapter edge should never produce this).

---

### `tests/test_risk_portfolio.py` (TDD unit + negative)

**Analog:** `tests/test_core_planner.py:283-409` (RR gate first-failure-wins) + `:601-670` (envelope validation)

**Apply:** Tests:
1. **Gate order** — at exact cap on cluster (PASS), at cap + 1 ulp on cluster (FAIL → `CLUSTER_CAP_REJECT`); same for aggregate, count, daily state.
2. **First failure wins** — cluster OK, aggregate FAIL → reason = `AGGREGATE_CAP_REJECT` (not cluster).
3. **DAILY_STOP blocks new entries** — `daily_loss_quote == daily_loss_stop_threshold` → `DAILY_STOP_BLOCK` (boundary).
4. **WARNING does not block** — `daily_loss_quote == daily_loss_warning_threshold` → `PortfolioVerdict` with `daily_state = WARNING`, `is_no_trade = False`.
5. **Stale constraints** — `now_utc - metadata_observed_at_utc > ttl` → `STALE_CONSTRAINTS` (boundary at exactly TTL — PASS).
6. **`daily_loss_quote is None`** → `UNCERTAIN_ACCOUNT_STATE` (D-04).
7. **`open_positions` order independence** — feed two position lists with different insertion orders; both produce identical `PortfolioVerdict` (Pitfall 4 — non-deterministic iteration).
8. **Candidate-plan double-counting** — `open_risk + candidate_risk == cap` exact edge (PASS per `>= cap`) → ACCEPTED; one ULP over → `AGGREGATE_CAP_REJECT` (Pitfall 6).

---

### `tests/test_risk_parity.py` (CI-blocking golden fixture)

**Analog:** `tests/fixtures/phase4/expected_plans.json:1-70` + `tests/conftest.py:131-160` (phase fixture loaders)

**Phase fixture loader pattern** (`tests/conftest.py:131-160`):
```python
@pytest.fixture(scope="session")
def phase4_parameters() -> dict:
    """Load the pinned registry set (trend-pullback/baseline-v1)."""
    return json.loads(
        (PHASE4_FIXTURES_DIR / "parameters.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="session")
def phase4_expected_features() -> dict:
    """Load the byte-exact expected feature values for the tracer slice."""
    return json.loads(
        (PHASE4_FIXTURES_DIR / "expected_features.json").read_text(encoding="utf-8")
    )
```

**Expected fixture shape** (`tests/fixtures/phase4/expected_plans.json:1-25`):
```json
{
  "plans": [
    {
      "created_at_utc": "2026-09-18T10:59:59+00:00",
      "entry_max_price": "50976.11812218609640044949190",
      ...
      "plan_hash": "a8e41ec86094d8e3dc4f99bcf44c77425aecfe6b9a6f9cdddd09ae1450d64091",
      "quantity_after_rounding": "1.101984053195538022097961153",
      "quantity_before_rounding": "1.101984053195538022097961153",
      "quantization_decision": "DEFERRED_TO_RISK",
      "risk_budget": "50.00000",
      "risk_rate": "0.005",
      ...
      "trade_plan_id": "232ad4c62fa194e5f7a4b08fc4aba59eeafcb8c35c4d53ff5bd9484657bb074d",
      "trade_plan_version": "v1"
    },
    ...
  ]
}
```

**Apply:** Parity fixture per case:
- `tests/fixtures/phase5/<case>/input.json` — `{trade_plan_fields, account_state, constraint_snapshot, parameter_set_id, open_positions, daily_loss_quote, now_utc, ttl, modeled_costs_per_unit}`.
- `tests/fixtures/phase5/<case>/expected.json` — `{quantity_before_rounding, quantity_after_rounding, quantization_decision, realized_risk, reason_code, daily_state, is_no_trade}` — Decimal-as-str, `+00:00` UTC ISO timestamps.
- `test_risk_parity.py::test_risk_pipeline_byte_identical` — load input → run pipeline → assert canonical-JSON equality of the full output dict (use `src/domain/canonical.py:sha256_hex` for fast equality).

**Required case coverage** (minimum per RESEARCH §Wave 0 Gaps):
- `happy_path_long` — sized, accepted, all gates PASS.
- `happy_path_short` — symmetric.
- `utilization_reject_edge` — nonzero costs (Pitfall 2 — pin the ratio variant).
- `min_qty_reject` — rounded < min_quantity.
- `notional_reject` — rounded × reference_price < min_notional.
- `cluster_cap_reject` — at cap + 1 ulp on cluster.
- `aggregate_cap_reject` — at cap + 1 ulp on aggregate.
- `max_positions_reject` — at exact max.
- `daily_stop_block` — `daily_loss_quote == stop_threshold`.
- `stale_constraints` — `now_utc - observed_at > ttl`.
- `uncertain_account_state` — `daily_loss_quote is None`.

---

### `tests/test_risk_no_float.py` (AST static guard — extend existing)

**Analog:** `tests/test_domain_no_float.py:1-95` (SCANNED_FILES list + `_find_float_calls` walker)

**Current SCANNED_FILES list** (`tests/test_domain_no_float.py:17-37`):
```python
SCANNED_FILES = (
    "src/domain/__init__.py",
    "src/domain/approval.py",
    "src/domain/canonical.py",
    "src/domain/enums.py",
    "src/domain/fill.py",
    "src/domain/ids.py",
    "src/domain/journal.py",
    "src/domain/order.py",
    "src/domain/position.py",
    "src/domain/registry.py",
    "src/domain/signal.py",
    "src/domain/trade_plan.py",
    "src/db/mappers.py",
    # Phase 4 plan 04-01 — pure core (D-10).
    "src/core/__init__.py",
    "src/core/types.py",
    "src/core/features.py",
    "src/core/strategy.py",
    "src/core/planner.py",
)
```

**Walker** (`tests/test_domain_no_float.py:40-71`):
```python
def _find_float_calls(src: str) -> list[tuple[int, str]]:
    """AST-walk source and return `(line_no, line_text)` for float shapes.

    Flags `float(...)` calls, float literals (`0.5`), `Decimal(<float
    literal>)` shapes (silent binary-noise constructors), and numpy
    floating-type uses (`np.float64`). TOML-sourced floats are the
    known exception: they never appear as literals on this path —
    `_normalize_params` converts them at the registry boundary.
    """
    found: dict[tuple[int, str], None] = {}
    lines = src.splitlines()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "float":
                found[(node.lineno, lines[node.lineno - 1].strip())] = None
            elif (
                isinstance(func, ast.Name)
                and func.id == "Decimal"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, float)
            ):
                found[(node.lineno, lines[node.lineno - 1].strip())] = None
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, float):
                found[(node.lineno, lines[node.lineno - 1].strip())] = None
        elif isinstance(node, ast.Attribute):
            if node.attr in {"float16", "float32", "float64", "floating"}:
                found[(node.lineno, lines[node.lineno - 1].strip())] = None
    return sorted(found)
```

**Apply:** Two acceptable paths — planner's choice:
1. **Extend `tests/test_domain_no_float.py:SCANNED_FILES`** with `"src/risk/__init__.py"`, `"src/risk/types.py"`, `"src/risk/sizing.py"`, `"src/risk/quantization.py"`, `"src/risk/portfolio.py"`, `"src/risk/gating.py"` (if exists). Single guard, simpler.
2. **New `tests/test_risk_no_float.py`** with identical walker, scoped to `src/risk/*.py` — mirrors `tests/test_core_planner.py:test_planner_has_no_float_literals` precedent at `:678-705`.

Recommend option 1 (extend SCANNED_FILES) — single guard, one place to extend for future phases.

---

### `tests/conftest.py` *(modify)* — add phase5 fixture loaders

**Analog:** `tests/conftest.py:115-160`

**Existing phase4 fixture loaders** (`tests/conftest.py:115-160`):
```python
# Phase 4 fixtures directory (plan 04-01).
PHASE4_FIXTURES_DIR = FIXTURES_DIR / "phase4"
...
@pytest.fixture(scope="session")
def phase4_candles() -> list[dict]:
    """Load the hand-built 1H + 4H closed candle CSV for the tracer slice."""
    with (PHASE4_FIXTURES_DIR / "candles.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="session")
def phase4_parameters() -> dict:
    """Load the pinned registry set (trend-pullback/baseline-v1)."""
    return json.loads(
        (PHASE4_FIXTURES_DIR / "parameters.json").read_text(encoding="utf-8")
    )
```

**Apply:** Append to `tests/conftest.py`:
```python
# Phase 5 fixtures directory (D-02 parity-fixture rule).
PHASE5_FIXTURES_DIR = FIXTURES_DIR / "phase5"


@pytest.fixture(scope="session")
def phase5_parity_cases() -> list[dict]:
    """Load every parity case under tests/fixtures/phase5/.

    Each case directory contains `input.json` + `expected.json`. The
    list order is sorted by case name for deterministic iteration.
    """
    cases: list[dict] = []
    for case_dir in sorted(PHASE5_FIXTURES_DIR.iterdir()):
        if not case_dir.is_dir():
            continue
        cases.append({
            "name": case_dir.name,
            "input": json.loads((case_dir / "input.json").read_text(encoding="utf-8")),
            "expected": json.loads((case_dir / "expected.json").read_text(encoding="utf-8")),
        })
    return cases


@pytest.fixture
def phase5_frozen_clock() -> datetime:
    """Frozen UTC clock for parity fixtures — 2026-09-19T00:00:00Z."""
    return datetime(2026, 9, 19, tzinfo=UTC)
```

---

### `tests/fixtures/phase5/` *(new directory)*

**Analog:** `tests/fixtures/phase4/` (5 files: `candles.csv`, `expected_features.json`, `expected_plans.json`, `expected_signals.json`, `parameters.json`)

**Apply:** Per-case directory layout:
```
tests/fixtures/phase5/
├── happy_path_long/
│   ├── input.json
│   └── expected.json
├── happy_path_short/
│   ├── input.json
│   └── expected.json
├── utilization_reject_edge/    # nonzero-cost case (Pitfall 2)
│   ├── input.json
│   └── expected.json
├── min_qty_reject/
├── notional_reject/
├── cluster_cap_reject/
├── aggregate_cap_reject/
├── max_positions_reject/
├── daily_stop_block/
├── stale_constraints/
└── uncertain_account_state/
```

**input.json shape:**
```json
{
  "trade_plan": {
    "trade_plan_id": "<sha256>",
    "signal_id": "<sha256>",
    "trade_plan_version": "v1",
    "entry_model": "LIMIT_ZONE",
    "entry_min_price": "<Decimal-as-str>",
    "entry_max_price": "<Decimal-as-str>",
    "stop_loss_price": "<Decimal-as-str>",
    "take_profit_json": "{\"tp1\":\"...\",...}",
    "invalidation_rule_json": "{\"basis\":\"CANDLE_CLOSE\",...}",
    "expiry_utc": "<ISO8601 +00:00>",
    "expected_rr_json": "{\"tp1_rr\":\"...\",...}",
    "risk_rate": "0.005",
    "risk_budget": "50.00000",
    "suggested_quantity": "<Decimal-as-str>",
    "quantity_before_rounding": "<Decimal-as-str>",
    "quantity_after_rounding": "<Decimal-as-str>",
    "quantization_decision": "DEFERRED_TO_RISK",
    "plan_hash": "<sha256>",
    "status": "READY",
    "created_at_utc": "<ISO8601 +00:00>"
  },
  "account_state": {"equity": "10000.00", "risk_rate": "0.005"},
  "constraint_snapshot": {
    "symbol": "BTCUSDT",
    "price_tick_size": "0.10",
    "quantity_step_size": "0.001",
    "min_quantity": "0.001",
    "min_notional": "50",
    "metadata_observed_at_utc": "<ISO8601 +00:00>"
  },
  "parameter_set_id": "baseline-v2",
  "open_positions": [
    {"symbol": "ETHUSDT", "position_side": "LONG", "open_risk": "30.00", "daily_pnl_contribution": "0"}
  ],
  "daily_loss_quote": "0",
  "now_utc": "<ISO8601 +00:00>",
  "ttl_seconds": "3600",
  "modeled_costs_per_unit": "<Decimal-as-str>"
}
```

**expected.json shape:**
```json
{
  "is_no_trade": false,
  "quantity": "<Decimal-as-str or null>",
  "quantity_before_rounding": "<Decimal-as-str>",
  "quantity_after_rounding": "<Decimal-as-str>",
  "quantization_decision": "ACCEPTED|REJECTED|DEFERRED_TO_RISK",
  "realized_risk": "<Decimal-as-str>",
  "reason_code": "OK|MIN_QTY_REJECT|...",
  "daily_state": "NORMAL|WARNING|DAILY_STOP"
}
```

---

### `docs/GLOSSARY.md` *(modify)* — extend §9 reason vocabulary

**Analog:** existing `docs/GLOSSARY.md` §9 (canonical reason-code vocabulary — matches `src/domain/enums.py:122-144` verbatim)

**Apply:** Add the D-05 fine-grained codes to §9 (verbatim — D-10 discipline):
```
QUANTIZATION_REJECT          # existing — coarse
MIN_NOTIONAL_REJECT          # existing — coarse (kept for back-compat)
MIN_QTY_REJECT               # D-05 — finer
NOTIONAL_REJECT              # D-05 — finer
UTILIZATION_REJECT           # D-05 — finer (60% gate)
CLUSTER_CAP_REJECT           # D-05 — finer (BTC/ETH/SOL/XRP cluster)
AGGREGATE_CAP_REJECT         # D-05 — finer
MAX_POSITIONS_REJECT         # D-05 — finer
DAILY_STOP_BLOCK             # D-05 — distinct from DAILY_STOP (existing)
STALE_CONSTRAINTS            # D-05 — TTL fail closed
UNCERTAIN_ACCOUNT_STATE      # D-05 — fail closed
```

Add §8 daily-state machine if not already present:
```
NORMAL   # daily loss < warning threshold
WARNING  # warning threshold ≤ daily loss < stop threshold
DAILY_STOP  # daily loss ≥ stop threshold — no new entries
```

---

## Shared Patterns

### Decimal-only + pinned prec (D-05 / D-10 / D-12)

**Source:** `src/core/_decimal.py:1-61` (whole module is the precedent) + `src/core/_decimal.py` re-exported from `src/core/planner.py:42` and `src/core/strategy.py:41`

**Apply to all `src/risk/*.py`:** import the pinned-prec helpers via `from src.core._decimal import _q, _add, _sub, _mul, _div`. NEVER call `Decimal(float)` (the AST no-float guard catches this), NEVER call `float()`, NEVER use `math.floor` on floats. Local `Decimal // step_size` is the exact-floor primitive for quantization.

**Validation helpers** (`src/core/types.py:32-59`): copy `_require_decimal`, `_require_non_empty`, `_require_utc_aware`, `_require_positive` into `src/risk/types.py` — each Phase layer keeps its own guards (`src/core/types.py:26-29` docstring: "no shared module; each Phase layer keeps its own guards").

### UTC-aware datetime handling (D-12)

**Source:** `src/core/types.py:38-46` + `src/domain/position.py:35-42` + `src/domain/canonical.py:50-56`

**Apply to:** `now_utc` and `metadata_observed_at_utc` in every risk input. Pitfall 3 mitigation: the TTL subtraction `now_utc - observed_at_utc` MUST be between two UTC-aware datetimes; reject naive datetimes in `__post_init__`; pin boundary tests at exactly TTL (PASS) and TTL + 1 second (FAIL → `STALE_CONSTRAINTS`).

### Fail-closed input validation (D-04)

**Source:** `src/core/planner.py:226-261` (signal-vs-candles correspondence gates) + `src/adapters/binance_usdm.py:386-413` (flag-never-fabricate: missing fields raise, never default to zero)

**Apply to:** `_validate_inputs(...)` at the top of every public risk function (`size_position`, `quantize`, `check_portfolio`, `evaluate_risk`). Reject:
- `equity is None` or `equity <= 0` → `UNCERTAIN_ACCOUNT_STATE`.
- `daily_loss_quote is None` → `UNCERTAIN_ACCOUNT_STATE`.
- `positions_reconciled == False` → `UNCERTAIN_ACCOUNT_STATE` (caller-supplied flag).
- `constraint_snapshot is None` or `quantity_step_size <= 0` or `min_quantity <= 0` or `min_notional <= 0` → `STALE_CONSTRAINTS`.
- `metadata_observed_at_utc is None` or naive → `STALE_CONSTRAINTS`.
- `now_utc` naive or non-UTC → `ValueError` at post_init.

NEVER raise at runtime inside pure functions — return `SizedResult(is_no_trade=True, reason_code=..., ...)` / `PortfolioVerdict(is_no_trade=True, reason_code=..., ...)` envelopes. The pattern matches `src/core/planner.py:294-306` (try/except ValueError → NO_TRADE wrapper).

### Registry extension (D-04/D-06)

**Source:** `src/domain/registry.py:60-87` (STRATEGY_KEYS) + `:225-240` (INT_KEYS) + `:316-320` (fail-closed unknown-key gate)

**Apply:** Add D-05 keys to both frozensets (see `src/domain/registry.py` *(modify)* above). New keys fail closed at load time — a missing `max_open_positions` in any v2 TOML raises `StrategyKeyOutsideRegistry`. Extend `tests/test_registry.py` per-key type tests (Pitfall 5): `max_open_positions` is INT, `risk_rate`/`max_aggregate_open_risk`/`cluster_cap`/`fee_rate_entry`/etc. are DECIMAL.

### Deterministic ID + canonical hashing (D-03/D-08/D-12)

**Source:** `src/domain/canonical.py:1-89` + `src/domain/ids.py:1-60` + `src/core/planner.py:52-77` (`_plan_hash`)

**Apply to:** parity-fixture canonical-JSON equality check (use `sha256_hex(canonical_bytes(...))` from `src/domain/canonical.py`). The plan_hash of a sized TradePlan does NOT change between planner and risk (risk uses `dataclasses.replace` to populate `quantity_*` and `quantization_decision`; the identity-bearing fields stay identical, so plan_hash stays identical). Tracer decision: lock the semantic that plan_hash binds BEFORE risk quantization (D-08 unchanged) — if Phase 6 wants plan_hash to include final quantity, that's a Phase 6 scope decision.

### Purity contract (D-05)

**Source:** `src/core/__init__.py:1-9` (docstring contract) + `tests/test_domain_no_float.py:1-95` (AST guard) + `tests/test_metadata.py:274-292` (per-module guard precedent)

**Apply to:** Every `src/risk/*.py` module docstring MUST state D-05 purity ("stdlib + Decimal + `src/core/_decimal.py` only"). NEVER import `polars`, `pandas`, `numpy`, `scipy`, `binance-sdk-*`, `sqlalchemy`, `pydantic`, `httpx`. Imports from `src/domain` (canonical, enums, ids, registry, trade_plan, signal) and `src/core/_decimal.py` only.

### Adapter-boundary isolation (D-05)

**Source:** `src/adapters/binance_usdm.py:1-15` (module docstring: SDK import isolated) + `src/data/metadata.py:30` (`from src.adapters.binance_usdm import SymbolFilters`)

**Apply to:** Risk never imports `binance-sdk-*` or any adapter. `ConstraintSnapshot` arrives as a frozen struct from `src/data/metadata.py` or directly constructed from `SymbolFilters` (same fields — risk builds its own frozen struct to keep the package dependency-free; planner decides the exact field subset).

### Test pattern: TDD RED→GREEN + boundary tests

**Source:** `tests/test_core_planner.py:1-230` + `tests/test_metadata.py:1-324` + `tests/test_registry.py:1-100`

**Apply to:** every `tests/test_risk_*.py` file. Header docstring states the contract + D-numbers + "RED phase — must fail until implemented" (until GREEN). Each test uses a frozen UTC clock (`tests/conftest.py:frozen_clock` at `:58-66`), fixed parameter set (`load_parameter_set("trend-pullback", "baseline-v2")` after Phase 5 ships v2 TOML), and asserts Decimal-exact equality (not approximate).

---

## No Analog Found

All 13 tracked analogs are found — no file in the new/modified list lacks an existing analog. The only file with no precedent is the optional `src/risk/gating.py` orchestration (which has a role-match in `src/core/planner.py:plan()` but no exact fit); it may be inlined into `src/risk/sizing.py` per planner discretion.

## Metadata

**Analog search scope:** `src/core/`, `src/domain/`, `src/adapters/`, `src/data/`, `tests/`, `tests/fixtures/phase4/`, `params/`
**Files scanned:** 21 analog files (all verified tracked via `git ls-files`)
**Pattern extraction date:** 2026-09-25
**Tracked-source gate:** all analog paths verified via `git ls-files -- <path>` — no gitignored capability mirrors referenced.
