# Phase 9: Live Execution Rollout - Pattern Map

**Mapped:** 2026-09-28
**Files analyzed:** 12 (6 new + 1 extended + 5 test files)
**Analogs found:** 12 / 12

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/execution/manager.py` (NEW) | service | request-response (orchestration) | `src/paper/loop.py:run_paper_tick` | role-match (pure orchestration pipeline) |
| `src/execution/placement.py` (NEW) | service | transform (Decimal math) | `src/risk/sizing.py:size_position` + `src/risk/quantization.py:quantize` | role-match (pure Decimal math, fail-closed) |
| `src/execution/fill_monitor.py` (NEW) | service | event-driven (fill folding) | `src/reconcile/compare.py:compare` | role-match (pure idempotent event folding) |
| `src/execution/enablement.py` (NEW) | service | state-machine (gate) | `src/reconcile/safe_mode.py:SafeModeController` | role-match (state machine + Protocol-typed deps) |
| `src/adapters/binance_usdm.py` (EXTEND) | adapter | request-response (REST) | `src/adapters/binance_usdm.py` (existing reconciler surface, lines 651-907) | exact (same file, extend in place) |
| `src/ops/health.py` (NEW) | service | request-response (probes) | `src/ops/drills.py:run_drill` | role-match (ops harness, journal-first) |
| `tests/test_execution_manager.py` (NEW) | test | test | `tests/test_paper_resync.py` (FakeAdapter pattern) | role-match |
| `tests/test_execution_modes.py` (NEW) | test | test | `tests/test_reconcile.py` (FakeReconcileAdapter) | role-match |
| `tests/test_execution_partials.py` (NEW) | test | test | `tests/test_paper_resync.py` (FakeAdapter) | role-match |
| `tests/test_execution_gates.py` (NEW) | test | test | `tests/test_drills.py` (FakeReconcileAdapter) | role-match |
| `tests/test_execution_enablement.py` (NEW) | test | test | `tests/test_drills.py` (FakeReconcileAdapter) | role-match |
| `tests/fixtures/phase9/` (NEW) | test fixture | test | `tests/fixtures/phase8/` (golden fixture pattern) | exact |

## Pattern Assignments

### `src/execution/manager.py` (service, request-response orchestration)

**Analog:** `src/paper/loop.py:run_paper_tick` (lines 306-553)

**Imports pattern** (lines 19-35):
```python
from __future__ import annotations
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.backtest.costs import build_cost_model, modeled_costs_per_unit
from src.core.planner import plan
from src.core.strategy import evaluate
from src.core.types import AccountState, Candle, MarketSnapshot
from src.domain.registry import load_parameter_set
from src.domain.trade_plan import TradePlan
from src.risk.gating import evaluate_risk
from src.risk.portfolio import resolve_absolute_thresholds
from src.risk.types import ConstraintSnapshot, OpenPosition
```

**Core orchestration pattern** (lines 306-553): `run_paper_tick(case_input: dict[str, Any]) -> dict[str, Any]` is a pure function of inputs + injected `now_utc`. No clock reads, no I/O, no randomness. The manager follows the same shape: `execute_approved_plan(approved_plan: dict[str, Any]) -> dict[str, Any]` — pure function of inputs + injected `now_utc`, no I/O.

**Validation helpers pattern** (lines 42-78): Local copies of `_require_decimal`, `_require_utc_aware`, `_require_non_empty`, `_coerce_money`, `_parse_utc_aware` — D-12 fail-closed boundary discipline. The manager reuses these for parsing approved-plan dicts.

**Gate pattern** (lines 261-298): `check_feature_validity` and `check_feed_freshness` return `str | None` rejection reason codes. The manager's placement-time gates (exchangeInfo revalidation, headroom check, DAILY_STOP) follow the same shape: each gate returns a reason code or None, first failure wins.

**Risk pipeline call** (lines 503-522): `evaluate_risk` is called identically with the same kwargs. The manager calls `evaluate_risk` identically (D-05 parity guarantee) — no live-local sizing.

**Error handling pattern**: No try/except in the pure function — invalid inputs raise ValueError/TypeError loudly (D-12). The adapter call sites catch SDK exceptions and convert to typed outcomes.

---

### `src/execution/placement.py` (service, transform Decimal math)

**Analog:** `src/risk/sizing.py:size_position` (lines 30-87) + `src/risk/quantization.py:quantize` (lines 32-155)

**Imports pattern** (sizing.py lines 14-23):
```python
from __future__ import annotations
from decimal import Decimal

from src.core._decimal import _add, _div, _mul, _sub
from src.core.types import AccountState
from src.domain.enums import QuantizationDecision, RejectionReason
from src.domain.trade_plan import TradePlan

from .types import SizedResult
```

**Core sizing pattern** (sizing.py lines 30-87): `size_position` is a pure function of `(trade_plan, account_state, entry_ref, modeled_costs_per_unit)` returning a `SizedResult`. The placement module's `size_protectives_to_filled_qty` follows the same shape: pure function of `(filled_qty, protective_template, constraint_snapshot)` returning a `ProtectiveSizing` frozen dataclass.

**Quantization pattern** (quantization.py lines 32-155): `quantize` floors raw quantity via exact Decimal floor-division, then applies gates in fixed order (first failure wins). The placement module's `quantize_protective_qty` follows the same shape: floor to stepSize, check min_qty, check min_notional, return quantized Decimal.

**Fail-closed validation pattern** (sizing.py lines 90-94, quantization.py lines 158-162):
```python
def _require_decimal(value: object, field_name: str) -> Decimal:
    """Reject non-Decimal values for money/qty/price inputs (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
    return value
```

**Reason code pattern** (sizing.py lines 26-27): `_OK = "OK"` and `_DEFERRED = QuantizationDecision.DEFERRED_TO_RISK.value` — use enum values for byte-identity with GLOSSARY §9. The placement module uses the same pattern for protective sizing outcomes.

**No-float purity contract**: The module imports NOTHING from Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic — stdlib + Decimal + `src/core/_decimal.py` only. AST no-`float(` guard scope extended to placement.py.

---

### `src/execution/fill_monitor.py` (service, event-driven fill folding)

**Analog:** `src/reconcile/compare.py:compare` (lines 194-496)

**Imports pattern** (compare.py lines 34-40):
```python
from __future__ import annotations
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from src.domain.enums import OrderRole, OrderStatus
```

**Core folding pattern** (compare.py lines 194-496): `compare` is a pure function that takes local intent + exchange truth and produces a typed `CompareDiff`. The fill monitor's `fold_fills` follows the same shape: pure function of `(fill_events, current_position_view)` producing a `FoldedPositionView` frozen dataclass.

**Idempotent keying pattern** (compare.py lines 228-258): Index truth rows by canonical identifier for O(1) lookup. The fill monitor keys by `(order_id, exchange_trade_id)` — mirrors `FillRow` unique key precedent (STATE.md 03-04 decision).

**Deterministic ordering pattern** (compare.py lines 472-480):
```python
divergences.sort(
    key=lambda d: (
        d.symbol,
        d.client_algo_id or "",
        d.client_order_id or "",
        d.kind,
    )
)
```
The fill monitor sorts folded fills by `(symbol, order_id, exchange_trade_id)` for deterministic downstream consumption.

**Duck-typed lookup pattern** (compare.py lines 556-560):
```python
def _get_field(entry: Any, field_name: str) -> Any:
    """Read a field from either an object (attribute) or a dict (key)."""
    if isinstance(entry, dict):
        return entry.get(field_name)
    return getattr(entry, field_name, None)
```
The fill monitor accepts both attribute-style objects and dict-style payloads (test fixture format).

**No-float purity contract**: stdlib + `src/domain/enums.py` only. No Binance SDK, no SQLAlchemy, no Pydantic, no Polars.

---

### `src/execution/enablement.py` (service, state-machine gate)

**Analog:** `src/reconcile/safe_mode.py:SafeModeController` (lines 125-340)

**Imports pattern** (safe_mode.py lines 21-26):
```python
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from src.domain.enums import RejectionReason, SystemMode
```

**Protocol-typed deps pattern** (safe_mode.py lines 49-79):
```python
class AdapterLike(Protocol):
    """Anything that quacks like the project adapter for SAFE_MODE."""

    async def snapshot_open_normal_orders(self, *, symbol: str | None = None) -> list[Any]: ...
    async def snapshot_open_algo_orders(self, *, symbol: str | None = None) -> list[Any]: ...
    async def snapshot_positions(self, *, symbol: str | None = None) -> list[Any]: ...


class JournalLike(Protocol):
    """Anything that quacks like the project journal for SAFE_MODE."""

    def record(self, event: Any) -> None: ...
```
The enablement module defines `AdapterLike` (with `place_entry`, `place_algo_protective`, `query_order_by_client`, `get_position_mode`) and `JournalLike` — same Protocol-typed surface pattern.

**State machine pattern** (safe_mode.py lines 125-340): `SafeModeController` owns a boolean flag + entered_at_utc + entered_reason. The enablement module's `LiveEnablementController` owns `LIVE_ORDERS_DISABLED` flag + enabled_at_utc + operator_id — same shape.

**Guard pattern** (safe_mode.py lines 214-239): `guard_new_entries(trade_plan)` returns a `SafeModeVerdict(is_no_trade, reason_code)`. The enablement module's `guard_placement(plan)` returns an `EnablementVerdict(can_place, reason_code)` — same discriminated envelope shape.

**Journal-first pattern** (safe_mode.py lines 316-340): `_journal_safe_mode_event` records the transition BEFORE mutating state. The enablement module journals enable/disable transitions before flipping the flag.

**Tick cadence constant** (safe_mode.py line 41): `SAFE_MODE_TICK_SECONDS: int = 60` — module-level named constant, not env var. The enablement module follows the same pattern for any cadence constants.

---

### `src/adapters/binance_usdm.py` (EXTEND — adapter, request-response REST)

**Analog:** `src/adapters/binance_usdm.py` existing reconciler surface (lines 651-907)

**Existing pattern to extend** (lines 651-907): The adapter already has `snapshot_open_normal_orders`, `snapshot_open_algo_orders`, `snapshot_positions`, `query_algo_order_by_client`, `cancel_normal_order`, `cancel_algo_order`. The Phase-9 extension adds `place_entry`, `place_algo_protective`, `query_order_by_client`, `get_position_mode` — same shape.

**SDK call pattern** (lines 422-432):
```python
response = await asyncio.to_thread(
    self._sdk.rest_api.kline_candlestick_data,
    symbol=symbol,
    interval=interval,
    start_time=start_ms,
    end_time=end_ms,
    limit=limit,
)
raw = response.data()
return [_row_to_kline(symbol, interval, row) for row in raw]
```
The new `place_entry` follows the same shape: `await asyncio.to_thread(self._sdk.rest_api.new_order, ...)` then project response to frozen dataclass.

**Bounded retry pattern** (lines 804-845):
```python
retry = tenacity.retry_if_exception(_cancel_retry_predicate)
stop = tenacity.stop_after_attempt(_RECONCILER_CANCEL_MAX_ATTEMPTS) | tenacity.stop_after_delay(
    _RECONCILER_CANCEL_MAX_DELAY_SECONDS
)
wait = tenacity.wait_random_exponential(
    multiplier=_RECONCILER_CANCEL_WAIT_MULTIPLIER_SECONDS,
    max=_RECONCILER_CANCEL_WAIT_MAX_SECONDS,
)
decorator = tenacity.AsyncRetrying(retry=retry, stop=stop, wait=wait, reraise=True)
```
The new placement methods use the same bounded-retry pattern with placement-specific ceilings (e.g., `_PLACEMENT_MAX_ATTEMPTS: int = 3`).

**Already-canceled handling pattern** (lines 835-845):
```python
try:
    await _do_cancel_with_retry()
except Exception as exc:
    if _is_already_canceled_message(str(exc)):
        log.info(
            "adapter.cancel_normal_order.already_canceled",
            symbol=symbol,
            orig_client_order_id=orig_client_order_id,
        )
        return
    raise
```
The new placement methods treat ambiguous responses (timeout, 5xx) as "query-by-ID first" — never blind-retry (EXECUTION_SPEC §10).

**Flag-never-fabricate pattern** (lines 576-585):
```python
if (
    f_price.tick_size is None
    or f_lot.step_size is None
    or f_lot.min_qty is None
    or f_min_notional.notional is None
):
    raise ValueError(
        f"exchangeInfo filter missing numeric field for {sym.symbol!r}: {sym.filters!r}"
    )
```
The new placement methods raise loudly on missing SDK response fields — never default to zero or epoch-0.

**Decimal projection pattern** (lines 375-382):
```python
return Kline(
    symbol=symbol,
    interval=interval,
    open_time_utc=_ms_to_utc(int(row[0])),
    close_time_utc=_ms_to_utc(int(row[6])),
    open=Decimal(str(row[1])),
    ...
)
```
The new placement response dataclasses (`EntryPlacementResult`, `AlgoPlacementResult`) project SDK response fields to `Decimal`/`UTC` frozen dataclasses.

**Float-at-boundary pattern** (RESEARCH §Pattern 1): Execution core computes everything in `Decimal`; the adapter converts to the SDK's `float` params via `float(str(d))` on already-quantized values. The new placement methods follow this pattern.

---

### `src/ops/health.py` (service, request-response probes)

**Analog:** `src/ops/drills.py:run_drill` (lines 268-324)

**Imports pattern** (drills.py lines 44-52):
```python
from __future__ import annotations
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from src.domain.journal import JournalEvent
```

**Probe result pattern** (drills.py lines 122-152): `DrillOutcome` is a frozen dataclass with `drill`, `fault`, `outcome`, `occurred_at_utc`. The health module's `HealthCheckResult` follows the same shape: frozen dataclass with `check_name`, `status` (PASS/FAIL/DEGRADED), `detail`, `observed_at_utc`.

**Journal-first pattern** (drills.py lines 312-318):
```python
event = _build_drill_outcome_event(
    declaration=declaration,
    fault=fault,
    outcome=outcome,
    now_utc=now_utc,
)
journal.record(event)
```
The health module journals each probe result as a `JournalEvent` with `event_type="HEALTH_CHECK"`.

**Caller-supplied timestamp pattern** (drills.py lines 303-306):
```python
if now_utc.tzinfo is None:
    raise ValueError("run_drill: now_utc must be UTC-aware")
if now_utc.utcoffset() != _ZERO_TIMEDELTA:
    raise ValueError("run_drill: now_utc must be UTC")
```
The health module accepts `now_utc` as a parameter (never `datetime.now()`) for testability.

**Checklist pattern** (SECURITY_AND_OPERATIONS §4): The health module checks market-feed freshness, last closed-candle time, WS connection state, user-data stream state, REST error rate, reconciliation drift, DB writes, Telegram delivery, unprotected positions, orphaned orders. Each check is a separate function returning `HealthCheckResult`.

---

### `tests/test_execution_manager.py` (test)

**Analog:** `tests/test_paper_resync.py` (lines 1-526)

**Imports pattern** (test_paper_resync.py lines 24-38):
```python
from __future__ import annotations
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import tenacity

PHASE7_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase7"
```

**No-retry-sleep fixture pattern** (test_paper_resync.py lines 39-53):
```python
@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: Any) -> None:
    """Bypass production retry sleeps (Group A option 1)."""
    monkeypatch.setattr(
        tenacity,
        "wait_random_exponential",
        lambda *args, **kwargs: tenacity.wait_none(),
        raising=True,
    )
```
The execution manager tests use the same fixture to bypass placement retry sleeps.

**FakeAdapter pattern** (test_paper_resync.py lines 80+): The tests inject a `FakeExecutionAdapter` that records `place_entry`, `place_algo_protective`, `query_order_by_client`, `get_position_mode` calls and returns pre-configured responses. Mirrors the `FakeAdapter` pattern from `test_paper_resync.py`.

**Golden fixture pattern** (test_paper_resync.py lines 56-69):
```python
def _load_input(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
```
The execution manager tests load `tests/fixtures/phase9/placement_sequences/{input,expected}.json` and assert byte-exact outcomes.

---

### `tests/test_execution_modes.py` (test)

**Analog:** `tests/test_reconcile.py` (lines 1-906)

**FakeReconcileAdapter pattern** (test_reconcile.py lines 68+): The tests inject a `FakeExecutionAdapter` that records placement calls and returns pre-configured responses for both one-way and hedge mode branches. Mirrors the `FakeReconcileAdapter` pattern.

**Mode branch coverage**: The tests cover both position-mode branches:
- One-way: SL `closePosition=true`, TP1 `reduceOnly` + explicit quantity, TP2 `closePosition=true`
- Hedge: explicit `positionSide` (LONG/SHORT), `reduceOnly` omitted, `closePosition` forbidden on BUY-in-LONG / SELL-in-SHORT

**Golden fixture pattern**: `tests/fixtures/phase9/mode_branches/{one_way,hedge}/{input,expected}.json` — byte-exact mode-correct parameter matrices.

---

### `tests/test_execution_partials.py` (test)

**Analog:** `tests/test_paper_resync.py` (lines 1-526)

**Partial-fill sizing pattern**: The tests inject fill events arriving out-of-order and replayed, and assert the fill monitor folds them idempotently to a single position view. Mirrors the `backfill_missed_closes` test pattern.

**Idempotent keying test**: The tests assert that replayed fills (same `(order_id, exchange_trade_id)`) are counted once — mirrors `FillRow` unique key precedent.

**Golden fixture pattern**: `tests/fixtures/phase9/partial_fills/{input,expected}.json` — byte-exact folded position views.

---

### `tests/test_execution_gates.py` (test)

**Analog:** `tests/test_drills.py` (lines 1-1183)

**FakeReconcileAdapter pattern** (test_drills.py lines 68+): The tests inject a `FakeExecutionAdapter` that records placement calls and returns pre-configured responses for gate-rejection scenarios.

**Gate coverage**: The tests cover:
- Headroom reject: open algo count + planned legs > 200 → `EXCHANGE_CONSTRAINT` NO_TRADE
- DAILY_STOP block: live reconciled state in DAILY_STOP → `DAILY_STOP_BLOCK` NO_TRADE
- Stale constraints: `metadata_observed_at_utc` past TTL → `STALE_CONSTRAINTS` NO_TRADE
- Uncertain account state: None daily loss → `UNCERTAIN_ACCOUNT_STATE` NO_TRADE

**Golden fixture pattern**: `tests/fixtures/phase9/gates/{headroom_reject,daily_stop_block,stale_constraints}/{input,expected}.json` — byte-exact gate outcomes.

---

### `tests/test_execution_enablement.py` (test)

**Analog:** `tests/test_drills.py` (lines 1-1183)

**FakeReconcileAdapter pattern** (test_drills.py lines 68+): The tests inject a `FakeExecutionAdapter` and assert the enablement controller blocks placement when `LIVE_ORDERS_DISABLED` is true.

**Enablement coverage**: The tests cover:
- Default-disabled: `LIVE_ORDERS_DISABLED=true` → all placements blocked
- Explicit enable: operator sets `LIVE_ORDERS_DISABLED=false` → placements allowed
- Emergency controls: manual-close + SAFE_MODE → all placements blocked
- Secret-free logs: assert no API keys/signatures in log output

**Golden fixture pattern**: `tests/fixtures/phase9/enablement/{disabled,enabled,emergency}/{input,expected}.json` — byte-exact enablement outcomes.

---

### `tests/fixtures/phase9/` (test fixture)

**Analog:** `tests/fixtures/phase8/` (golden fixture pattern)

**Directory structure**:
```
tests/fixtures/phase9/
├── placement_sequences/
│   ├── input.json
│   └── expected.json
├── mode_branches/
│   ├── one_way/
│   │   ├── input.json
│   │   └── expected.json
│   └── hedge/
│       ├── input.json
│       └── expected.json
├── partial_fills/
│   ├── input.json
│   └── expected.json
├── gates/
│   ├── headroom_reject/
│   │   ├── input.json
│   │   └── expected.json
│   ├── daily_stop_block/
│   │   ├── input.json
│   │   └── expected.json
│   └── stale_constraints/
│       ├── input.json
│       └── expected.json
└── enablement/
    ├── disabled/
    │   ├── input.json
    │   └── expected.json
    ├── enabled/
    │   ├── input.json
    │   └── expected.json
    └── emergency/
        ├── input.json
        └── expected.json
```

**Fixture format** (mirrors `tests/fixtures/phase8/orphan_divergence/input.json`):
- `input.json`: approved plan + constraint snapshot + reconciled positions + adapter responses
- `expected.json`: expected placement calls + expected journal events + expected gate outcomes

**Byte-exact determinism**: All Decimal values serialized as strings (D-12), all datetimes as ISO-8601 UTC strings, all enums as their `.value` strings.

---

## Shared Patterns

### Authentication / Authorization Gate

**Source:** `src/approval/binding.py:check_binding_full` (lines 149-216)

**Apply to:** `src/execution/manager.py` — every placement call gates on the Phase-8 approval binding (SignalId + strategyVersion + parameterSetId/Hash + plan hash + expiry + authorized chat + one-time token).

```python
def check_binding_full(
    *,
    callback: Callback,
    approval: Approval,
    authorized_chat_id: int,
    now_utc: datetime,
    expiry_utc: datetime,
    approval_strategy_version: str,
    approval_parameter_set_id: str,
    approval_parameter_set_hash: str,
) -> BindingCheck:
    """Run the fixed-order gate with full identity tuple (D-01).

    Gate order is fixed and never reordered:
      1. chat-id — wrong chat rejected before any state lookup.
      2. expiry — now_utc >= expiry_utc is expired (boundary inclusive).
      3. plan-hash — mismatch is STALE_SETUP.
      4. version/parameter-set — mismatch is INVALIDATED.
      5. token-hash — mismatch is INVALIDATED (wrong token).
    """
```

The manager calls `check_binding_full` before any placement — stale/mismatched/superseded plans are unapprovable.

---

### Error Handling — Fail-Closed Reason Codes

**Source:** `src/risk/gating.py:evaluate_risk` (lines 27-122) + `src/risk/portfolio.py:check_portfolio` (lines 152-353)

**Apply to:** All execution files — every gate returns a typed reason code from `RejectionReason` enum, first failure wins.

```python
# Gate order (first failure wins):
#   1. exchangeInfo revalidation (tick/step/notional + headroom)
#   2. DAILY_STOP on live reconciled state
#   3. Stale constraints (metadata_observed_at_utc past TTL)
#   4. Uncertain account state (None daily loss, unreconciled positions)
```

The manager's placement-time gates follow the same shape: each gate returns a `RejectionReason` value or `OK`, first failure wins.

---

### Validation — D-12 Boundary Discipline

**Source:** `src/domain/order.py` (lines 23-41) + `src/domain/trade_plan.py` (lines 22-41)

**Apply to:** All execution files — Decimal-only for money/qty/price, UTC-aware datetimes, non-empty strings.

```python
def _require_decimal(value: object, field_name: str) -> None:
    """Reject non-Decimal values for money/qty/price fields (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")


def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive and non-UTC datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def _require_non_empty(value: str, field_name: str) -> None:
    """Reject empty strings for validated non-empty fields."""
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} must be a non-empty string")
```

The execution files use these helpers at every boundary — adapter edge, placement math, fill monitor, enablement controller.

---

### Deterministic ID Derivation

**Source:** `src/execution/order_ids.py` (lines 86-151)

**Apply to:** `src/execution/manager.py` + `src/adapters/binance_usdm.py` (place_entry, place_algo_protective) — every placement reuses the deterministic `x-`/`xa-` 36-char IDs.

```python
def derive_client_order_id(*, plan_hash: str, role: str) -> str:
    """Return the deterministic Binance client_order_id for a plan leg.

    Per D-04: the same `(plan_hash, role)` always yields the same
    client_order_id across processes, restarts, and replays.
    """
    validated_hash = _require_plan_hash(plan_hash)
    validated_role = _require_role(role)
    role_code = ROLE_CODES[validated_role]
    return _CLIENT_PREFIX + validated_hash[:_CLIENT_PLAN_SLICE_LEN] + role_code


def derive_algo_client_id(*, plan_hash: str, role: str) -> str:
    """Return the deterministic Binance algo_client_id for a plan leg."""
    validated_hash = _require_plan_hash(plan_hash)
    validated_role = _require_role(role)
    role_code = ROLE_CODES[validated_role]
    return _ALGO_PREFIX + validated_hash[:_ALGO_PLAN_SLICE_LEN] + role_code
```

The manager calls `derive_client_order_id(plan_hash, "ENTRY")` for entry placement and `derive_algo_client_id(plan_hash, role)` for each protective leg. Retry/restart/replay-safe by construction.

---

### Bounded Retry (tenacity)

**Source:** `src/adapters/binance_usdm.py` (lines 103-123, 804-845) + `src/paper/resync.py` (lines 45-48, 177-202)

**Apply to:** `src/adapters/binance_usdm.py` (place_entry, place_algo_protective) — bounded retry on transient faults only, fail closed on programming errors.

```python
_RECONCILER_CANCEL_MAX_ATTEMPTS: int = 3
_RECONCILER_CANCEL_MAX_DELAY_SECONDS: int = 30
_RECONCILER_CANCEL_WAIT_MULTIPLIER_SECONDS: int = 1
_RECONCILER_CANCEL_WAIT_MAX_SECONDS: int = 10


def _is_transient_reconcile(exc: BaseException) -> bool:
    """Retry transient faults only; fail closed on programming errors."""
    return not isinstance(exc, (ValueError, KeyError, TypeError))
```

The placement methods use the same pattern with placement-specific ceilings (e.g., `_PLACEMENT_MAX_ATTEMPTS: int = 3`, `_PLACEMENT_MAX_DELAY_SECONDS: int = 30`).

---

### Journal-First Ordering

**Source:** `src/reconcile/sweeper.py:_build_pre_image_event` (lines 303-330) + `src/reconcile/safe_mode.py:_journal_safe_mode_event` (lines 316-340)

**Apply to:** All execution files — every placement, fill, cancel, divergence, and SAFE_MODE transition lands as a `JournalEvent` with full identity.

```python
def _build_pre_image_event(
    self,
    *,
    symbol: str,
    client_algo_id: str,
    probe: Any,
    now_utc: datetime,
) -> JournalEvent:
    """Build the pre-cancel JournalEvent carrying the orphan state."""
    payload = {
        "symbol": symbol,
        "client_algo_id": client_algo_id,
        "algo_status": getattr(probe, "algo_status", None),
        "update_time_utc": _iso(getattr(probe, "update_time_utc", None)),
        "phase": "pre_cancel",
    }
    return JournalEvent(
        journal_event_id=(f"orphan_sweep_pre_{client_algo_id}_{int(now_utc.timestamp() * 1000)}"),
        occurred_at_utc=now_utc,
        event_type="ORPHAN_SWEEP",
        entity_type="OpenAlgoOrder",
        entity_id=client_algo_id,
        correlation_id="reconcile_orphan_sweep",
        payload_json=_build_payload_json(payload),
    )
```

The execution files journal every transition with `event_type` (PLACEMENT, FILL, CANCEL, DIVERGENCE, SAFE_MODE), `entity_type` (Order, Fill, Position, SystemMode), `entity_id` (client_order_id, client_algo_id, symbol), and `correlation_id` (plan_hash or signal_id).

---

### Protocol-Typed Dependencies

**Source:** `src/reconcile/sweeper.py:AdapterLike` (lines 35-49) + `src/reconcile/safe_mode.py:AdapterLike` (lines 49-79)

**Apply to:** `src/execution/manager.py`, `src/execution/fill_monitor.py`, `src/execution/enablement.py` — Protocol-typed adapter + journal surfaces.

```python
class AdapterLike(Protocol):
    """Anything that quacks like the project adapter for cancel paths."""

    async def query_algo_order_by_client(self, *, client_algo_id: str) -> Any: ...

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> None: ...


class JournalLike(Protocol):
    """Anything that quacks like the project journal for the sweeper."""

    def record(self, event: Any) -> None: ...
```

The execution files define their own `AdapterLike` (with placement methods) and `JournalLike` — tests inject fakes that record calls.

---

### Structured Logging (structlog)

**Source:** `src/adapters/binance_usdm.py` (lines 68-76, 839-844) + `src/paper/supervisor.py` (lines 28-37)

**Apply to:** All execution files — structured JSON logs with correlation ID, SignalId, client/algo order IDs, symbol, strategy version, UTC timestamp, event type, result.

```python
import structlog

log = structlog.get_logger()

# Usage:
log.info(
    "adapter.cancel_normal_order.already_canceled",
    symbol=symbol,
    orig_client_order_id=orig_client_order_id,
)
```

The execution files use the same pattern: `log.info("execution.placement.entry_placed", symbol=..., client_order_id=..., plan_hash=..., strategy_version=..., now_utc=...)`.

---

### Purity Contract (stdlib + Decimal only)

**Source:** `src/execution/order_ids.py` (lines 21-23) + `src/risk/sizing.py` (lines 9-12) + `src/reconcile/compare.py` (lines 30-32)

**Apply to:** `src/execution/manager.py`, `src/execution/placement.py`, `src/execution/fill_monitor.py`, `src/execution/enablement.py` — stdlib + Decimal + `src/core/_decimal.py` only. No Binance SDK, no SQLAlchemy, no Pydantic, no Polars.

```python
"""The module is dependency-free: stdlib + `src/domain/enums.py` only.
No Telegram, no Binance SDK, no SQLAlchemy, no Pydantic, no Polars.
"""
```

The execution files follow the same purity contract. AST no-`float(` guard scope extended to all execution files.

---

## No Analog Found

None — all 12 files have strong analogs in the existing codebase. The Phase-9 work is composition + adapter extension, not invention.

## Metadata

**Analog search scope:** `src/execution/`, `src/adapters/`, `src/approval/`, `src/reconcile/`, `src/risk/`, `src/paper/`, `src/ops/`, `src/data/`, `src/domain/`, `tests/`

**Files scanned:** 60+ Python files across `src/` and `tests/`

**Pattern extraction date:** 2026-09-28

**Key analog files read:**
- `src/execution/order_ids.py` (158 lines) — deterministic ID derivation
- `src/execution/__init__.py` (30 lines) — package surface
- `src/adapters/binance_usdm.py` (1161 lines) — sole SDK importer, reconciler surface
- `src/approval/binding.py` (225 lines) — fixed-order gate
- `src/approval/replay.py` (244 lines) — replay-to-existing resolution
- `src/approval/tokens.py` (62 lines) — one-time token primitives
- `src/approval/mapping.py` (135 lines) — short-id to full-id mapping
- `src/reconcile/compare.py` (582 lines) — three-source compare
- `src/reconcile/sweeper.py` (443 lines) — cancel-only orphan sweeper
- `src/reconcile/safe_mode.py` (363 lines) — SAFE_MODE controller
- `src/risk/gating.py` (125 lines) — risk pipeline orchestration
- `src/risk/sizing.py` (97 lines) — pure position-sizing
- `src/risk/quantization.py` (223 lines) — pure quantization
- `src/risk/portfolio.py` (353 lines) — portfolio gates
- `src/risk/types.py` (236 lines) — pure-risk frozen dataclasses
- `src/paper/loop.py` (556 lines) — pure paper-loop dispatch
- `src/paper/supervisor.py` (349 lines) — WS supervisor
- `src/paper/resync.py` (287 lines) — REST resync
- `src/paper/journal.py` (496 lines) — paper record assembly
- `src/paper/notify.py` (347 lines) — SIMULATE notify
- `src/ops/drills.py` (935 lines) — RUNBOOK drill harness
- `src/ops/backup.py` (612 lines) — backup + restore drill
- `src/data/metadata.py` (90 lines) — versioned symbol metadata
- `src/domain/enums.py` (236 lines) — GLOSSARY-canonical enums
- `src/domain/order.py` (110 lines) — Order frozen dataclass
- `src/domain/position.py` (87 lines) — Position frozen dataclass
- `src/domain/fill.py` (88 lines) — Fill frozen dataclass
- `src/domain/journal.py` (77 lines) — JournalEvent frozen dataclass
- `src/domain/approval.py` (70 lines) — Approval frozen dataclass
- `src/domain/trade_plan.py` (105 lines) — TradePlan frozen dataclass
- `tests/test_order_ids.py` (552 lines) — deterministic ID tests
- `tests/test_reconcile.py` (906 lines) — reconciler tests
- `tests/test_approval_replay.py` (702 lines) — approval replay tests
- `tests/test_drills.py` (1183 lines) — RUNBOOK drill tests
- `tests/test_paper_resync.py` (526 lines) — paper resync tests
- `tests/test_paper_supervisor_backfill.py` (317 lines) — supervisor backfill tests
- `tests/test_paper_notify.py` (279 lines) — paper notify tests
