# Phase 4: Pure Core (Feature + Strategy + Planner) - Pattern Map

**Mapped:** 2026-09-23
**Files analyzed:** 19 new/modified files
**Analogs found:** 14 / 14 (all matched)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/core/__init__.py` | package barrel | re-export | `src/domain/__init__.py` | exact |
| `src/core/types.py` | model (frozen dataclasses) | value object | `src/domain/signal.py` + `src/domain/trade_plan.py` | exact |
| `src/core/features.py` | service (pure math) | transform | `src/data/quality.py` (pure-function surface) | role-match |
| `src/core/strategy.py` | service (pure function) | transform | `src/domain/registry.py` (pure loader) | role-match |
| `src/core/planner.py` | service (pure function) | transform | `src/domain/registry.py` (pure loader) | role-match |
| `src/core/enums.py` | model (enums) | value object | `src/domain/enums.py` | exact |
| `src/domain/enums.py` (MODIFY) | model (enums) | value object | `src/domain/enums.py` (existing) | exact |
| `src/domain/registry.py` (MODIFY) | service (loader) | transform | `src/domain/registry.py` (existing) | exact |
| `src/domain/__init__.py` (MODIFY) | package barrel | re-export | `src/domain/__init__.py` (existing) | exact |
| `params/breakout-retest/baseline-v1.toml` | config | static | `params/trend-pullback/baseline-v1.toml` | exact |
| `params/range-mr/baseline-v1.toml` | config | static | `params/trend-pullback/baseline-v1.toml` | exact |
| `tests/fixtures/phase4/candles.csv` | test fixture | static | `tests/fixtures/phase3/candles.csv` | exact |
| `tests/fixtures/phase4/parameters.json` | test fixture | static | `tests/fixtures/phase3/parameters.json` | exact |
| `tests/fixtures/phase4/expected_features.json` | test fixture | static | `tests/fixtures/phase3/expected_signals.json` | exact |
| `tests/fixtures/phase4/expected_signals.json` | test fixture | static | `tests/fixtures/phase3/expected_signals.json` | exact |
| `tests/fixtures/phase4/expected_plans.json` | test fixture | static | `tests/fixtures/phase3/expected_plans.json` | exact |
| `tests/conftest.py` (MODIFY) | test fixture loader | static | `tests/conftest.py` (existing) | exact |
| `tests/test_domain_no_float.py` (MODIFY) | test (static guard) | static | `tests/test_domain_no_float.py` (existing) | exact |
| `tests/test_no_lookahead.py` (MODIFY) | test (determinism) | static | `tests/test_no_lookahead.py` (existing) | exact |
| `tests/test_prefix_invariance.py` (MODIFY) | test (determinism) | static | `tests/test_prefix_invariance.py` (existing) | exact |
| `tests/test_candle_close_timing.py` (MODIFY) | test (determinism) | static | `tests/test_candle_close_timing.py` (existing) | exact |
| `tests/test_domain_boundary.py` (MODIFY) | test (boundary) | static | `tests/test_domain_boundary.py` (existing) | exact |
| `tests/test_core_features.py` | test (unit) | static | `tests/test_tracer_slice.py` | role-match |
| `tests/test_core_strategy_trend_pullback.py` | test (unit) | static | `tests/test_tracer_slice.py` | role-match |
| `tests/test_core_strategy_breakout_retest.py` | test (unit) | static | `tests/test_tracer_slice.py` | role-match |
| `tests/test_core_strategy_range_mr.py` | test (unit) | static | `tests/test_tracer_slice.py` | role-match |
| `tests/test_core_planner.py` | test (unit) | static | `tests/test_tracer_slice.py` | role-match |

## Pattern Assignments

### `src/core/__init__.py` (package barrel, re-export)

**Analog:** `src/domain/__init__.py`

**Imports pattern** (lines 1-39):
```python
"""Domain package — pure, dependency-free value objects (Phase 3, plan 03-02).

Per D-01: the strategy core imports NOTHING from SQLAlchemy, Pydantic,
Polars, or the Binance SDK. Dependency-free domain keeps Phase 4 pure
functions testable without a DB.

This barrel re-exports the public symbols. No logic lives here.
"""

from __future__ import annotations

from .approval import Approval
from .enums import (
    ApprovalAction,
    ApprovalResult,
    OrderStatus,
    PositionStatus,
    RejectionReason,
    SignalStatus,
    SystemMode,
    TradePlanStatus,
    TradeStatus,
)
from .fill import Fill
from .ids import derive_child_id, make_signal_id
from .journal import JournalEvent
from .order import Order
from .position import Position
from .registry import (
    ParameterSet,
    RegistrySchemaMismatch,
    StrategyKeyOutsideRegistry,
    UnregisteredParameterSet,
    load_parameter_set,
    verify_parameter_set,
)
from .signal import Signal
from .trade_plan import TradePlan

__all__ = [
    # Enums
    "SignalStatus",
    ...,
]
```

**Core pattern:** Module docstring + `from __future__ import annotations` + alphabetical imports + `__all__` list. No logic in barrel.

---

### `src/core/types.py` (model, frozen dataclasses)

**Analog:** `src/domain/signal.py` + `src/domain/trade_plan.py`

**Imports pattern** (signal.py lines 13-18):
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .enums import SignalStatus
```

**Validation helpers pattern** (signal.py lines 21-34):
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
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")
```

**Frozen dataclass + `__post_init__` pattern** (signal.py lines 37-78):
```python
@dataclass(frozen=True)
class Signal:
    """A deterministic statement that the strategy detected a setup.

    `signal_id` is the content hash from `ids.make_signal_id` — never
    passed in by callers. `status` is explicit (D-11); NULL timestamps
    mean "transition never happened".
    """

    signal_id: str
    strategy_id: str
    strategy_version: str
    parameter_set_id: str
    parameter_set_hash: str
    symbol: str
    direction: str  # LONG/SHORT — Phase 4 may promote to Enum
    setup_type: str
    source_timeframe: str
    source_candle_close_utc: datetime  # aware UTC
    detected_at_utc: datetime
    status: SignalStatus  # explicit — never inferred (D-11)
    expires_at_utc: datetime
    invalidated_at_utc: datetime | None = None  # None = "never happened"

    def __post_init__(self) -> None:
        for fname in (
            "signal_id",
            "strategy_id",
            "strategy_version",
            "parameter_set_id",
            "parameter_set_hash",
            "symbol",
            "direction",
            "setup_type",
            "source_timeframe",
        ):
            _require_non_empty(getattr(self, fname), fname)
        _require_utc_aware(self.source_candle_close_utc, "source_candle_close_utc")
        _require_utc_aware(self.detected_at_utc, "detected_at_utc")
        _require_utc_aware(self.expires_at_utc, "expires_at_utc")
        if self.invalidated_at_utc is not None:
            _require_utc_aware(self.invalidated_at_utc, "invalidated_at_utc")
```

**Decimal guard pattern** (trade_plan.py lines 22-27):
```python
def _require_decimal(value: object, field_name: str) -> None:
    """Reject non-Decimal values for money/qty/price fields (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
```

**Apply to:** `Candle`, `FeatureOutput`, `FeatureFrame`, `SetupResult` (or `NO_TRADE`/`SETUP` discriminated union) — all frozen dataclasses with `__post_init__` validation.

---

### `src/core/features.py` (service, pure math transform)

**Analog:** `src/data/quality.py` (pure-function surface, fail-closed posture)

**Imports pattern** (quality.py lines 14-20):
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import polars as pl
from src.adapters.binance_usdm import Kline
```

**Note:** `src/core/features.py` MUST NOT import polars/pandas/NumPy (D-10). Replace with stdlib only:
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext

from .types import Candle, FeatureOutput
```

**Fail-closed verdict pattern** (quality.py lines 36-52):
```python
@dataclass(frozen=True)
class QualityVerdict:
    """Result of one batch quality check.

    `structural_ok` is the gate: False ⇒ caller MUST NOT publish the batch
    (D-10 fail-closed). The other counters are telemetry for the
    coverage layer to report.
    """

    structural_ok: bool
    duplicates: int
    ohlc_violations: int
    timestamp_regressions: int
    gap_count: int
    negative_values: int = 0
    bad_durations: int = 0
    mixed_keys: int = 0
```

**Apply to:** `FeatureOutput(value: Decimal | None, valid: bool, reason_code: str)` and `FeatureFrame(features_valid: bool, ...)` — fail-closed gate pattern.

**Decimal EMA recurrence** (from RESEARCH.md §Code Examples, lines 273-279):
```python
from decimal import Decimal, localcontext


def ema_update(prior: Decimal, price: Decimal, alpha: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 28  # pinned; never inherit ambient getcontext().prec
        return alpha * price + (Decimal(1) - alpha) * prior
```

**Decimal ATR recurrence** (from RESEARCH.md §Code Examples, lines 289-292):
```python
def true_range(high: Decimal, low: Decimal, prev_close: Decimal | None) -> Decimal:
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))
```

---

### `src/core/strategy.py` (service, pure function)

**Analog:** `src/domain/registry.py` (pure loader, fail-closed)

**Imports pattern** (registry.py lines 30-39):
```python
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .canonical import sha256_hex
```

**Apply to:** `src/core/strategy.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.domain.ids import make_signal_id
from src.domain.registry import ParameterSet

from .types import Candle, FeatureFrame, SetupResult
```

**Pure function signature** (per D-07):
```python
def evaluate(
    snapshot: MarketSnapshot,
    account_state: AccountState,
    strategy_version: str,
    parameter_set: ParameterSet,
) -> SetupResult:
    """Pure: (snapshot, account_state, strategy_version, parameter_set) -> NO_TRADE | SETUP."""
```

**SignalId construction** (ids.py lines 19-46):
```python
def make_signal_id(
    *,
    strategy_id: str,
    strategy_version: str,
    parameter_set_id: str,
    symbol: str,
    source_timeframe: str,
    source_candle_close_utc: datetime,
    setup_fingerprint: str,
) -> str:
    """Return the content-hash SignalId for the given identity tuple."""
    return sha256_hex(
        {
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "parameter_set_id": parameter_set_id,
            "symbol": symbol,
            "source_timeframe": source_timeframe,
            "source_candle_close_utc": source_candle_close_utc,
            "setup_fingerprint": setup_fingerprint,
        }
    )
```

**Apply to:** Strategy emits `Signal` via `make_signal_id` with `detected_at_utc = source_candle_close_utc` (D-07 candle-close timing).

---

### `src/core/planner.py` (service, pure function)

**Analog:** `src/domain/registry.py` (pure loader, fail-closed)

**Imports pattern** (same as strategy.py):
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from src.domain.canonical import sha256_hex
from src.domain.ids import derive_child_id
from src.domain.registry import ParameterSet
from src.domain.signal import Signal
from src.domain.trade_plan import TradePlan

from .types import SetupResult
```

**Plan hash construction** (per D-08, mirrors canonical.py lines 71-84):
```python
def _plan_hash(
    signal_id: str,
    entry_min: Decimal,
    entry_max: Decimal,
    stop_loss: Decimal,
    take_profit_json: str,
    invalidation_rule_json: str,
    expiry_utc: datetime,
) -> str:
    return sha256_hex(
        {
            "signal_id": signal_id,
            "entry_min_price": entry_min,
            "entry_max_price": entry_max,
            "stop_loss_price": stop_loss,
            "take_profit_json": take_profit_json,
            "invalidation_rule_json": invalidation_rule_json,
            "expiry_utc": expiry_utc,
        }
    )
```

**TradePlan construction** (trade_plan.py lines 46-105 — full field list):
```python
@dataclass(frozen=True)
class TradePlan:
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

**TradePlan ID derivation** (per D-08, uses `derive_child_id`):
```python
trade_plan_id = derive_child_id(signal_id, "trade_plan:v1")
```

**Apply to:** Planner emits `TradePlan` with `quantization_decision = "DEFERRED_TO_RISK"` (D-09), `plan_hash` via `sha256_hex`, `trade_plan_id` via `derive_child_id`.

---

### `src/core/enums.py` (model, enums)

**Analog:** `src/domain/enums.py`

**Enum pattern** (enums.py lines 16-29):
```python
class SignalStatus(str, Enum):
    """GLOSSARY §2 — Signal lifecycle states.

    Execution lifecycle states do NOT belong in SignalStatus.
    """

    DETECTED = "DETECTED"
    NOTIFIED = "NOTIFIED"
    VIEWED = "VIEWED"
    APPROVED = "APPROVED"
    SKIPPED_USER = "SKIPPED_USER"
    SKIPPED_BUSY = "SKIPPED_BUSY"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
```

**Apply to:** Family-local reason codes (`WARMUP_INSUFFICIENT`, `GAP_IN_SOURCE`) as `str, Enum` mixin. Values copy GLOSSARY verbatim.

---

### `src/domain/enums.py` (MODIFY — add D-06 enum promotions)

**Analog:** `src/domain/enums.py` (existing)

**Add new enums** (after line 143, before `__all__`):
```python
class Direction(str, Enum):
    """GLOSSARY — Signal direction (D-06 promotion)."""

    LONG = "LONG"
    SHORT = "SHORT"


class SourceTimeframe(str, Enum):
    """GLOSSARY — Source candle timeframe (D-06 promotion)."""

    M1 = "1m"
    H1 = "1h"
    H4 = "4h"


class EntryModel(str, Enum):
    """GLOSSARY — Trade plan entry model (D-06 promotion)."""

    LIMIT_ZONE = "LIMIT_ZONE"
    MARKET = "MARKET"


class OrderRole(str, Enum):
    """GLOSSARY — Order role in plan (D-06 promotion)."""

    ENTRY = "ENTRY"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT_1 = "TAKE_PROFIT_1"
    TAKE_PROFIT_2 = "TAKE_PROFIT_2"


class QuantizationDecision(str, Enum):
    """GLOSSARY — Quantization decision (D-06 promotion, D-09 deferral)."""

    DEFERRED_TO_RISK = "DEFERRED_TO_RISK"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
```

**Apply to:** Add `Direction`, `SourceTimeframe`, `EntryModel`, `OrderRole`, `QuantizationDecision` enums. `SetupType` is per-family (planner discretion — one enum per family or a single enum with all family setup names).

---

### `src/domain/registry.py` (MODIFY — extend STRATEGY_KEYS)

**Analog:** `src/domain/registry.py` (existing)

**Extend STRATEGY_KEYS** (lines 60-72):
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
        # Phase 4 additions (D-05, family B/C keys):
        "retest_window_bars",
        "retest_depth_atr",
        "breakout_volume_threshold",
        "zone_min_touches",
        "zone_aging_bars",
        "range_break_buffer_atr",
        "regime_filter_lookback",
    }
)
```

**Extend INT_KEYS** (lines 210-216):
```python
INT_KEYS = frozenset(
    {
        "swing_lookback",
        "breakout_confirmation_bars",
        "signal_expiry_hours",
        # Phase 4 additions:
        "retest_window_bars",
        "zone_min_touches",
        "zone_aging_bars",
        "regime_filter_lookback",
    }
)
```

**Apply to:** Add new family B/C keys to `STRATEGY_KEYS` and `INT_KEYS` (planner discretion on exact key names per A5 in RESEARCH.md).

---

### `src/domain/__init__.py` (MODIFY — re-export new enums)

**Analog:** `src/domain/__init__.py` (existing)

**Extend imports** (lines 13-23):
```python
from .enums import (
    ApprovalAction,
    ApprovalResult,
    Direction,  # Phase 4 D-06
    EntryModel,  # Phase 4 D-06
    OrderRole,  # Phase 4 D-06
    OrderStatus,
    PositionStatus,
    QuantizationDecision,  # Phase 4 D-06
    RejectionReason,
    SignalStatus,
    SourceTimeframe,  # Phase 4 D-06
    SystemMode,
    TradePlanStatus,
    TradeStatus,
)
```

**Extend `__all__`** (lines 40-69):
```python
__all__ = [
    # Enums
    "SignalStatus",
    "TradePlanStatus",
    "ApprovalAction",
    "ApprovalResult",
    "OrderStatus",
    "TradeStatus",
    "PositionStatus",
    "SystemMode",
    "RejectionReason",
    "Direction",  # Phase 4
    "SourceTimeframe",  # Phase 4
    "EntryModel",  # Phase 4
    "OrderRole",  # Phase 4
    "QuantizationDecision",  # Phase 4
    ...,
]
```

---

### `params/breakout-retest/baseline-v1.toml` (config, static)

**Analog:** `params/trend-pullback/baseline-v1.toml`

**Full file pattern** (lines 1-28):
```toml
# params/breakout-retest/baseline-v1.toml
#
# Seed parameter set for the breakout-retest strategy (Phase 4, plan 04-XX).
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
strategy_id = "breakout-retest"
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
minimum_risk_utilization_after_rounding = 0.6
# Family B additions:
retest_window_bars = 5
retest_depth_atr = 0.3
breakout_volume_threshold = 1.5
```

**Apply to:** Same structure for `range-mr/baseline-v1.toml` with family C keys.

---

### `tests/fixtures/phase4/candles.csv` (test fixture, static)

**Analog:** `tests/fixtures/phase3/candles.csv`

**Full file pattern** (lines 1-6):
```csv
symbol,timeframe,open_time_utc,open,high,low,close,volume
BTCUSDT,1h,2026-09-19T00:00:00Z,50000.00,50100.00,49900.00,50050.00,123.456
BTCUSDT,1h,2026-09-19T01:00:00Z,50050.00,50200.00,50000.00,50150.00,98.765
BTCUSDT,1h,2026-09-19T02:00:00Z,50150.00,50300.00,50100.00,50250.00,110.234
BTCUSDT,1h,2026-09-19T03:00:00Z,50250.00,50400.00,50200.00,50350.00,105.678
BTCUSDT,1h,2026-09-19T04:00:00Z,50350.00,50500.00,50300.00,50450.00,115.432
```

**Apply to:** Phase 4 candles.csv with 1H + 4H rows, gap injection rows, warm-up-short prefixes. Columns per TESTING_STRATEGY §2.

---

### `tests/fixtures/phase4/parameters.json` (test fixture, static)

**Analog:** `tests/fixtures/phase3/parameters.json`

**Full file pattern** (lines 1-6):
```json
{
  "strategy_id": "trend-pullback",
  "strategy_version": "v1.0.0",
  "parameter_set_id": "baseline-v1",
  "parameter_set_hash": "e1579900b1be20b8a6db76c554255cbec8125d5d317f6df7dadd5de78d2afae5"
}
```

**Apply to:** Phase 4 parameters.json with real `parameter_set_hash` from `load_parameter_set("trend-pullback", "baseline-v1").parameter_set_hash`.

---

### `tests/fixtures/phase4/expected_features.json` (test fixture, static)

**Analog:** `tests/fixtures/phase3/expected_signals.json`

**Placeholder pattern** (lines 1-3):
```json
{
  "signals": []
}
```

**Apply to:** Phase 4 expected_features.json with byte-exact expected feature values per candle (EMA/ATR/swing/zone), hand-computed from the candles.csv.

---

### `tests/fixtures/phase4/expected_signals.json` (test fixture, static)

**Analog:** `tests/fixtures/phase3/expected_signals.json`

**Placeholder pattern** (lines 1-3):
```json
{
  "signals": []
}
```

**Apply to:** Phase 4 expected_signals.json with byte-exact expected Signal objects (signal_id, strategy_id, direction, setup_type, source_timeframe, source_candle_close_utc, etc.).

---

### `tests/fixtures/phase4/expected_plans.json` (test fixture, static)

**Analog:** `tests/fixtures/phase3/expected_plans.json`

**Placeholder pattern** (lines 1-3):
```json
{
  "plans": []
}
```

**Apply to:** Phase 4 expected_plans.json with byte-exact expected TradePlan objects (trade_plan_id, entry_min/max, stop_loss, take_profit_json, plan_hash, etc.).

---

### `tests/conftest.py` (MODIFY — add phase4_* fixtures)

**Analog:** `tests/conftest.py` (existing)

**Phase 3 fixture pattern** (lines 70-102):
```python
@pytest.fixture(scope="session")
def phase3_candles() -> list[dict]:
    """Load the hand-built boundary-covering candle CSV.

    Columns per TESTING_STRATEGY §2:
    symbol,timeframe,open_time_utc,open,high,low,close,volume
    """
    with (PHASE3_FIXTURES_DIR / "candles.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="session")
def phase3_parameters() -> dict:
    """Load the pinned registry set."""
    return json.loads((PHASE3_FIXTURES_DIR / "parameters.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def phase3_expected_signals() -> dict:
    """Load the byte-exact expected signals (placeholder per D-09)."""
    return json.loads((PHASE3_FIXTURES_DIR / "expected_signals.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def phase3_expected_plans() -> dict:
    """Load the byte-exact expected plans (placeholder per D-09)."""
    return json.loads((PHASE3_FIXTURES_DIR / "expected_plans.json").read_text(encoding="utf-8"))
```

**Apply to:** Add `PHASE4_FIXTURES_DIR = FIXTURES_DIR / "phase4"` and `phase4_candles`, `phase4_parameters`, `phase4_expected_features`, `phase4_expected_signals`, `phase4_expected_plans` fixtures mirroring the phase3 pattern.

---

### `tests/test_domain_no_float.py` (MODIFY — extend SCANNED_FILES)

**Analog:** `tests/test_domain_no_float.py` (existing)

**SCANNED_FILES pattern** (lines 17-31):
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
)
```

**Apply to:** Append `src/core/*` modules:
```python
SCANNED_FILES = (
    ...existing entries...,
    "src/core/__init__.py",
    "src/core/types.py",
    "src/core/features.py",
    "src/core/strategy.py",
    "src/core/planner.py",
    "src/core/enums.py",
)
```

---

### `tests/test_no_lookahead.py` (MODIFY — replace placeholder with real family logic)

**Analog:** `tests/test_no_lookahead.py` (existing)

**Placeholder pipeline pattern** (lines 33-52):
```python
def _signal_entries(candles: list[dict]) -> list[tuple[str, str]]:
    """Placeholder pipeline output: one (close_iso, signal_id) per candle.

    Each output references ONLY its own source candle (closed-candle
    input by construction) — the property the no-lookahead tests pin.
    """
    entries = []
    for candle in candles:
        close = _close_time(candle)
        sid = make_signal_id(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_set_id=PARAMETER_SET_ID,
            symbol=candle["symbol"],
            source_timeframe=candle["timeframe"],
            source_candle_close_utc=close,
            setup_fingerprint=sha256_hex(dict(candle)),
        )
        entries.append((close.isoformat(), sid))
    return entries
```

**Apply to:** Replace `_signal_entries` with real `src.core.strategy.evaluate()` call. Tests stay structurally identical — only the mapping changes.

---

### `tests/test_prefix_invariance.py` (MODIFY — replace placeholder)

**Analog:** `tests/test_prefix_invariance.py` (existing)

**Same pattern as test_no_lookahead.py** — replace `_signal_entries` with real `evaluate()` call.

---

### `tests/test_candle_close_timing.py` (MODIFY — replace placeholder)

**Analog:** `tests/test_candle_close_timing.py` (existing)

**Same pattern** — replace `_signal_entries` with real `evaluate()` call. The `frozen_clock` fixture (conftest.py lines 48-55) stays as-is.

---

### `tests/test_domain_boundary.py` (MODIFY — replace placeholder)

**Analog:** `tests/test_domain_boundary.py` (existing)

**Placeholder pattern** (lines 21-29):
```python
def _placeholder_decide(candles: list[dict]) -> dict:
    """Placeholder harness entry point: invalid reasons, never raises."""
    if len(candles) == 0:
        return {"status": "INVALID", "reason": "EMPTY_INPUT"}
    if len(candles) == 1:
        return {"status": "INVALID", "reason": "SINGLE_BAR"}
    if len(candles) < MIN_BARS_TBD:
        return {"status": "INVALID", "reason": "WARMUP_INSUFFICIENT"}
    return {"status": "NO_TRADE", "reason": "MECHANISM_PLACEHOLDER_TBD"}
```

**Apply to:** Replace `_placeholder_decide` with real `src.core.features.compute_features()` + `src.core.strategy.evaluate()` calls. Tests stay structurally identical.

---

### `tests/test_core_features.py` (test, unit)

**Analog:** `tests/test_tracer_slice.py`

**Test scaffold pattern** (lines 80-101):
```python
def _mk_kline(
    *,
    open_ms: int,
    close_ms: int,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    price: str = "100.00",
) -> Kline:
    """Build a minimal valid Kline for unit tests."""
    return Kline(
        symbol=symbol,
        interval=interval,
        open_time_utc=datetime.fromtimestamp(open_ms / 1000, tz=UTC),
        close_time_utc=datetime.fromtimestamp(close_ms / 1000, tz=UTC),
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("1.0"),
        quote_volume=Decimal(price),
        trade_count=10,
    )
```

**Apply to:** Build `_mk_candle()` helper for `src.core.types.Candle` (frozen dataclass with Decimal OHLC). Test EMA/ATR/swing/zone computation against hand-computed expected values.

---

### `tests/test_core_strategy_trend_pullback.py` (test, unit)

**Analog:** `tests/test_tracer_slice.py`

**Apply to:** Test `src.core.strategy.evaluate()` for trend-pullback family. Use `phase4_candles` fixture, assert NO_TRADE for warm-up-insufficient, assert SETUP for valid setup, assert SignalId matches `make_signal_id` with expected fingerprint.

---

### `tests/test_core_strategy_breakout_retest.py` (test, unit)

**Analog:** `tests/test_tracer_slice.py`

**Apply to:** Same pattern as trend-pullback test, but for breakout-retest family. Load `params/breakout-retest/baseline-v1.toml` via `load_parameter_set`.

---

### `tests/test_core_strategy_range_mr.py` (test, unit)

**Analog:** `tests/test_tracer_slice.py`

**Apply to:** Same pattern, but for range-mr family. Load `params/range-mr/baseline-v1.toml`.

---

### `tests/test_core_planner.py` (test, unit)

**Analog:** `tests/test_tracer_slice.py`

**Apply to:** Test `src.core.planner.plan()` for SETUP → TradePlan. Assert entry zone, SL, TP1/TP2, RR gate (RR < minimum_rr → NO_TRADE), plan_hash byte-exact match, `quantization_decision = "DEFERRED_TO_RISK"`.

---

## Shared Patterns

### Frozen Dataclass + Validation (D-01/D-02/D-12)

**Source:** `src/domain/signal.py` lines 21-78, `src/domain/trade_plan.py` lines 22-105
**Apply to:** All new dataclasses in `src/core/types.py` (`Candle`, `FeatureOutput`, `FeatureFrame`, `SetupResult`)

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")


def _require_decimal(value: object, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")


@dataclass(frozen=True)
class Candle:
    symbol: str
    interval: str
    open_time_utc: datetime
    close_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, "symbol")
        _require_non_empty(self.interval, "interval")
        _require_utc_aware(self.open_time_utc, "open_time_utc")
        _require_utc_aware(self.close_time_utc, "close_time_utc")
        for fname in ("open", "high", "low", "close", "volume"):
            _require_decimal(getattr(self, fname), fname)
```

---

### Canonical Hash Identity (D-04/D-08)

**Source:** `src/domain/canonical.py` lines 39-89
**Apply to:** All new IDs/hashes in `src/core/` (SignalId via `make_signal_id`, plan_hash via `sha256_hex`, trade_plan_id via `derive_child_id`)

```python
from src.domain.canonical import sha256_hex
from src.domain.ids import make_signal_id, derive_child_id

# SignalId
signal_id = make_signal_id(
    strategy_id="trend-pullback",
    strategy_version="v1.0.0",
    parameter_set_id="baseline-v1",
    symbol="BTCUSDT",
    source_timeframe="1h",
    source_candle_close_utc=close_time,
    setup_fingerprint=sha256_hex({"regime": "BULLISH", "trigger": "pullback"}),
)

# TradePlan ID
trade_plan_id = derive_child_id(signal_id, "trade_plan:v1")

# Plan hash
plan_hash = sha256_hex(
    {
        "signal_id": signal_id,
        "entry_min_price": entry_min,
        "entry_max_price": entry_max,
        "stop_loss_price": stop_loss,
        "take_profit_json": take_profit_json,
        "invalidation_rule_json": invalidation_rule_json,
        "expiry_utc": expiry_utc,
    }
)
```

---

### Fail-Closed Quality Gate (D-04/D-10)

**Source:** `src/data/quality.py` lines 36-52, 98-210
**Apply to:** `FeatureOutput(valid: bool, reason_code: str)` and `FeatureFrame(features_valid: bool, ...)`

```python
@dataclass(frozen=True)
class FeatureOutput:
    """One feature value with validity gate (D-03)."""

    value: Decimal | None
    valid: bool
    reason_code: str  # "OK", "WARMUP_INSUFFICIENT", "GAP_IN_SOURCE"


@dataclass(frozen=True)
class FeatureFrame:
    """Whole-bar feature summary (D-03)."""

    features_valid: bool  # AND of all required-feature validity
    ema_20: FeatureOutput
    ema_50: FeatureOutput
    ema_200: FeatureOutput
    atr_14: FeatureOutput
    swing_high: FeatureOutput
    swing_low: FeatureOutput
    zone_upper: FeatureOutput
    zone_lower: FeatureOutput
```

---

### Parameter Registry Loading (D-04/D-05/D-06)

**Source:** `src/domain/registry.py` lines 305-342
**Apply to:** All strategy/planner code that needs parameters

```python
from src.domain.registry import load_parameter_set

ps = load_parameter_set("trend-pullback", "baseline-v1")
# ps.strategy_id, ps.strategy_version, ps.parameter_set_id, ps.parameter_set_hash, ps.params
```

---

### Decimal-Only Arithmetic (D-12)

**Source:** `src/domain/canonical.py` lines 48-49, `tests/test_domain_no_float.py` lines 34-65
**Apply to:** All price/qty/RR arithmetic in `src/core/`

```python
from decimal import Decimal, localcontext

# String construction only — never Decimal(0.5)
alpha = Decimal("2") / (Decimal("20") + Decimal("1"))  # EMA α for period=20

# Pinned local context — never inherit ambient getcontext().prec
with localcontext() as ctx:
    ctx.prec = 28
    result = alpha * price + (Decimal(1) - alpha) * prior
```

---

### Golden Fixture Harness (D-07/D-09)

**Source:** `tests/conftest.py` lines 70-102, `tests/test_fixture_harness.py` lines 1-209
**Apply to:** All Phase 4 test files

```python
# conftest.py
@pytest.fixture(scope="session")
def phase4_candles() -> list[dict]:
    with (PHASE4_FIXTURES_DIR / "candles.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="session")
def phase4_parameters() -> dict:
    return json.loads((PHASE4_FIXTURES_DIR / "parameters.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def phase4_expected_signals() -> dict:
    return json.loads((PHASE4_FIXTURES_DIR / "expected_signals.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def phase4_expected_plans() -> dict:
    return json.loads((PHASE4_FIXTURES_DIR / "expected_plans.json").read_text(encoding="utf-8"))
```

---

### Determinism Test Pattern (D-08)

**Source:** `tests/test_no_lookahead.py` lines 33-52, `tests/test_prefix_invariance.py` lines 33-48, `tests/test_candle_close_timing.py` lines 34-49
**Apply to:** All Phase 4 determinism suites

```python
from src.domain.canonical import sha256_hex
from src.domain.ids import make_signal_id


def _signal_entries(candles: list[dict]) -> list[tuple[str, str]]:
    """Pipeline output: one (close_iso, signal_id) per candle."""
    entries = []
    for candle in candles:
        close = _close_time(candle)
        sid = make_signal_id(
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            parameter_set_id=PARAMETER_SET_ID,
            symbol=candle["symbol"],
            source_timeframe=candle["timeframe"],
            source_candle_close_utc=close,
            setup_fingerprint=sha256_hex(dict(candle)),
        )
        entries.append((close.isoformat(), sid))
    return entries
```

**Apply to:** Replace placeholder `_signal_entries` with real `src.core.strategy.evaluate()` calls. Test structure stays identical.

---

### AST No-Float Guard (D-12)

**Source:** `tests/test_domain_no_float.py` lines 17-31, 34-65
**Apply to:** Extend `SCANNED_FILES` to include `src/core/*`

```python
SCANNED_FILES = (
    ...existing entries...,
    "src/core/__init__.py",
    "src/core/types.py",
    "src/core/features.py",
    "src/core/strategy.py",
    "src/core/planner.py",
    "src/core/enums.py",
)
```

---

### Enum Promotion Pattern (D-06)

**Source:** `src/domain/enums.py` lines 16-29
**Apply to:** All new enums in `src/domain/enums.py` and `src/core/enums.py`

```python
from enum import Enum


class Direction(str, Enum):
    """GLOSSARY — Signal direction (D-06 promotion)."""

    LONG = "LONG"
    SHORT = "SHORT"
```

**Apply to:** `Direction`, `SourceTimeframe`, `EntryModel`, `OrderRole`, `QuantizationDecision` in `src/domain/enums.py`. Family-local reason codes in `src/core/enums.py`.

---

## No Analog Found

None — all Phase 4 files have clear analogs in the existing codebase. The pure-core pattern is a direct extension of the Phase-3 domain/registry/fixture patterns.

## Metadata

**Analog search scope:** `src/domain/`, `src/data/`, `src/adapters/`, `tests/`, `params/`
**Files scanned:** 54 Python files + 2 TOML files
**Pattern extraction date:** 2026-09-23
**Tracked-source verification:** All analog paths verified via `git ls-files` (non-empty output = tracked). No gitignored mirrors used.
