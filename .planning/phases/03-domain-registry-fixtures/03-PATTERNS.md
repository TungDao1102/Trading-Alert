# Phase 3: Domain + Registry + Fixtures — Pattern Map

**Mapped:** 2026-09-22
**Files analyzed:** 27 (22 new + 5 modified/extended)
**Analogs found:** 24 with in-repo analogs / 27 (3 greenfield files — `params/` TOML seeds, `tests/fixtures/phase3/` golden triple — have no in-repo analog; format reference is RESEARCH.md §Code Examples + TESTING_STRATEGY.md §2)

## Phase Context (greenfield domain layer, rich in-repo precedent)

This is a **code-creation** phase (CONTEXT D-01..D-12). The working material is:

- The `docs/` corpus (DATA_MODEL §2.1–2.7, GLOSSARY §§2–9, CONFIGURATION §§2–7, RESEARCH_PROTOCOL §5, TESTING_STRATEGY §§2–5) — canonical contracts the code must conform to.
- `03-RESEARCH.md` §Architecture Patterns (lines 142–252) and §Code Examples (lines 313–571) — explicit Python patterns from the Phase-3 researcher, cited with line numbers below.
- In-repo precedent: `src/adapters/binance_usdm.py:49-67` (frozen dataclass + Decimal + UTC), `src/db/models.py:33-228` (single-Base + TIMESTAMPTZ + NUMERIC(38,18)), `src/db/alembic/versions/0001_baseline.py:1-111` (reviewed migration + parity-gate convention), `tests/test_metadata.py:89-145` (CapturingSession pattern), `tests/conftest.py:30-49` (golden-fixture loaders + frozen_clock), `scripts/check_migration_parity.py:1-226` (offline DDL diff), `tests/test_metadata.py:256-292` + `tests/test_coverage.py:650-662` + `tests/test_backup.py:431-441` (AST no-`float(` guard).

Code / module vocabulary used in the table:

| Module role | Module data flow |
|-------------|------------------|
| `domain-entity` | frozen pure-Python dataclass; zero heavy imports (D-01) |
| `domain-enum` | GLOSSARY-canonical `Enum` classes (D-10) |
| `domain-canonical` | scalar normalizer + canonical JSON + SHA256 (shared by ids + registry) |
| `domain-registry` | TOML loader + fail-closed hash verification (D-04/D-05/D-06) |
| `domain-ids` | content-hash ID constructors (D-03) |
| `orm-model` | SQLAlchemy 2.0 declarative; PG mirror of domain (D-02) |
| `mapper` | thin total `to_row`/`from_row` per entity (D-02) |
| `migration` | Alembic reviewed migration; `down_revision = "0001_baseline"` |
| `test-fixture` | golden recorded samples (candles.csv + parameters.json + expected_*.json) |
| `test-suite` | TDD RED→GREEN; CapturingSession + frozen_clock + AST no-`float(` guard |
| `ci-gate` | registry-rejection workflow (extends Phase-1 research-gate.yml) |

## File Classification

| # | New/Modified File | Module Role | Module Data Flow | Closest Format/Structure Analog | Match Quality |
|---|-------------------|-------------|------------------|---------------------------------|---------------|
| 1 | `src/domain/__init__.py` *(new)* | domain-entity (re-exports) | barrel re-export only | `src/adapters/__init__.py` pattern (no logic, re-exports only) | exact (barrel convention) |
| 2 | `src/domain/enums.py` *(new)* | domain-enum | GLOSSARY-canonical lifecycle enums | `src/adapters/binance_usdm.py:49-67` (frozen dataclass + `str, Enum` mixin precedent); `docs/GLOSSARY.md:39-143` (canonical values) | exact (verbatim values from GLOSSARY) |
| 3 | `src/domain/canonical.py` *(new)* | domain-canonical | scalar normalizer + canonical JSON + SHA256 | `src/adapters/binance_usdm.py:130-132` (`_ms_to_utc` — UTC discipline); `src/data/quality.py:25-33` (single-source-of-truth table pattern); `03-RESEARCH.md:425-463` §Code Examples canonicalizer | exact (verbatim from RESEARCH §Code Examples) |
| 4 | `src/domain/ids.py` *(new)* | domain-ids | content-hash ID constructors | `src/adapters/binance_usdm.py:49-67` (frozen dataclass precedent); `03-RESEARCH.md:379-423` §Code Examples `make_signal_id` + `derive_child_id` | exact (verbatim from RESEARCH §Code Examples) |
| 5 | `src/domain/signal.py` *(new)* | domain-entity | frozen dataclass (Signal) | `src/adapters/binance_usdm.py:49-67` (`Kline` frozen dataclass with Decimal + UTC); `03-RESEARCH.md:379-407` §Code Examples Signal shape | exact (verbatim from RESEARCH §Code Examples) |
| 6 | `src/domain/trade_plan.py` *(new)* | domain-entity | frozen dataclass (TradePlan) | `src/adapters/binance_usdm.py:49-67` (frozen dataclass precedent); `docs/data/DATA_MODEL.md` §2.4 (canonical field list) | exact (frozen dataclass + Decimal + UTC + Enum status) |
| 7 | `src/domain/approval.py` *(new)* | domain-entity | frozen dataclass (Approval) | `src/adapters/binance_usdm.py:49-67` (frozen dataclass precedent); `docs/data/DATA_MODEL.md` §2.5 (canonical field list) | exact (frozen dataclass + Decimal + UTC + Enum action/result) |
| 8 | `src/domain/order.py` *(new)* | domain-entity | frozen dataclass (Order) | `src/adapters/binance_usdm.py:49-67` (frozen dataclass precedent); `docs/data/DATA_MODEL.md` §2.7 (canonical field list, Algo-Order-shaped IDs) | exact (frozen dataclass + Decimal + UTC + Enum status) |
| 9 | `src/domain/fill.py` *(new)* | domain-entity | frozen dataclass (Fill) | `src/adapters/binance_usdm.py:49-67` (frozen dataclass precedent); `docs/data/DATA_MODEL.md` §2.8 (canonical field list) | exact (frozen dataclass + Decimal + UTC) |
| 10 | `src/domain/position.py` *(new)* | domain-entity | frozen dataclass (Position) | `src/adapters/binance_usdm.py:49-67` (frozen dataclass precedent); `docs/data/DATA_MODEL.md` §2.9 (canonical field list) | exact (frozen dataclass + Decimal + UTC + Enum status) |
| 11 | `src/domain/journal.py` *(new)* | domain-entity | frozen dataclass (JournalEvent) | `src/adapters/binance_usdm.py:49-67` (frozen dataclass precedent); `docs/data/DATA_MODEL.md` §2.10 (canonical field list, append-only) | exact (frozen dataclass + UTC + Enum event_type) |
| 12 | `src/domain/registry.py` *(new)* | domain-registry | TOML loader + canonical hash + fail-closed | `src/data/store.py:43-91` (`publish_batch` — fail-closed immutability); `src/data/quality.py:98-210` (`check_batch` — fail-closed structural gate); `03-RESEARCH.md:465-509` §Code Examples registry loader | exact (fail-closed loader + custom exception types) |
| 13 | `src/db/models.py` *(modified — extend)* | orm-model | 7 new ORM tables on existing `Base` | `src/db/models.py:33-228` (single-Base + TIMESTAMPTZ + NUMERIC(38,18) + JSON-as-TEXT convention) | exact (same conventions, new tables) |
| 14 | `src/db/mappers.py` *(new)* | mapper | thin total `to_row`/`from_row` per entity | `src/data/metadata.py:37-90` (`refresh_symbol_metadata` — versioned INSERT pattern); `src/adapters/binance_usdm.py:161-192` (`_row_to_kline` — adapter row→dataclass mapping) | exact (total + round-trip tested) |
| 15 | `src/db/alembic/versions/0002_domain_registry.py` *(new)* | migration | 7 `op.create_table` blocks + indexes | `src/db/alembic/versions/0001_baseline.py:1-111` (same convention: TIMESTAMPTZ + NUMERIC(38,18) + JSON-as-TEXT + reviewed migration) | exact (same convention, `down_revision = "0001_baseline"`) |
| 16 | `params/<strategy_id>/<parameter_set_id>.toml` *(new, seed)* | domain-registry (data) | versioned TOML parameter set | `tests/fixtures/exchange_info_sample.json` (recorded golden fixture precedent); `docs/configuration/CONFIGURATION.md` §§2-7 (parameter-set identity contract) | exact (format reference) |
| 17 | `tests/fixtures/phase3/candles.csv` *(new, golden)* | test-fixture | hand-built boundary-covering bars | `tests/fixtures/exchange_info_sample.json` (recorded golden fixture precedent); `docs/testing/TESTING_STRATEGY.md:25-29` (candle CSV column order) | exact (format reference) |
| 18 | `tests/fixtures/phase3/parameters.json` *(new, golden)* | test-fixture | pinned registry set | `tests/fixtures/exchange_info_sample.json` (recorded golden fixture precedent) | exact (format reference) |
| 19 | `tests/fixtures/phase3/expected_signals.json` *(new, golden)* | test-fixture | byte-exact expected outputs | `tests/fixtures/exchange_info_sample.json` (recorded golden fixture precedent); `docs/testing/TESTING_STRATEGY.md:13-22` §2 golden-fixture model | exact (format reference) |
| 20 | `tests/fixtures/phase3/expected_plans.json` *(new, golden)* | test-fixture | byte-exact expected outputs | `tests/fixtures/exchange_info_sample.json` (recorded golden fixture precedent); `docs/testing/TESTING_STRATEGY.md:13-22` §2 golden-fixture model | exact (format reference) |
| 21 | `tests/conftest.py` *(modified — extend)* | test-fixture (shared) | phase-3 loaders (candles, params, expected) | `tests/conftest.py:30-49` (golden_exchange_info + frozen_clock + fixture_path pattern) | exact (extend existing fixture pattern) |
| 22 | `tests/test_domain_enums.py` *(new)* | test-suite | enum membership + no-invented-names | `tests/test_metadata.py:152-187` (golden fixture inserts one row per live-5); `tests/test_collector.py:435-458` (PG-vs-SQLite boundary assertion) | exact (enum membership + boundary) |
| 23 | `tests/test_domain_ids.py` *(new)* | test-suite | content-hash ID stability + collision | `tests/test_metadata.py:223-253` (Decimal exactness — byte-equality test pattern) | exact (byte-equality test pattern) |
| 24 | `tests/test_domain_mappers.py` *(new)* | test-suite | mapper round-trip ×7 | `tests/test_metadata.py:89-145` (CapturingSession pattern for SQLite NUMERIC lossiness); `tests/test_collector.py:123-160` (in-memory SQLite session fixture) | exact (CapturingSession + round-trip) |
| 25 | `tests/test_registry.py` *(new)* | test-suite | loader + hash stability + byte-equality | `tests/test_metadata.py:223-253` (Decimal exactness — byte-equality test pattern) | exact (byte-equality test pattern) |
| 26 | `tests/test_registry_gate.py` *(new)* | test-suite | negative tests (unregistered/mutated/strategy-key-outside) | `tests/test_collector.py:216-260` (per-symbol failure isolation — negative test pattern) | exact (negative test pattern) |
| 27 | `tests/test_fixture_harness.py` *(new)* | test-suite | golden triple loads + placeholder expectations byte-exact | `tests/test_metadata.py:152-187` (golden fixture loads + asserts); `tests/conftest.py:30-49` (golden_exchange_info fixture) | exact (golden fixture load + assert) |
| 28 | `tests/test_no_lookahead.py` *(new)* | test-suite | no-lookahead determinism | `tests/test_collector.py:268-304` (skipped tick — expected vs observed, no interpolation); `src/data/backfill.py:337-342` (drop forming candle — Pitfall 1 precedent) | exact (forming-candle invariant) |
| 29 | `tests/test_prefix_invariance.py` *(new)* | test-suite | prefix-invariance determinism | `tests/test_collector.py:622-694` (per-symbol resume — idempotent re-run pattern) | exact (idempotent re-run pattern) |
| 30 | `tests/test_candle_close_timing.py` *(new)* | test-suite | candle-close-timing determinism | `src/adapters/binance_usdm.py:49-55` (`Kline.close_time_utc <= now_utc` invariant); `src/data/backfill.py:337-342` (drop forming candle) | exact (close-time invariant) |
| 31 | `tests/test_domain_boundary.py` *(new)* | test-suite | boundary determinism (empty/single/warm-up-insufficient) | `tests/test_collector.py:505-543` (healthcheck with/without watermarks — boundary pattern) | exact (boundary test pattern) |
| 32 | `tests/test_domain_no_float.py` *(new)* | test-suite | AST no-`float(` guard extended to domain | `tests/test_metadata.py:256-292` (`_find_float_calls` + `test_no_float_call_in_metadata_or_adapter`); `tests/test_coverage.py:650-662` (same pattern for coverage); `tests/test_backup.py:431-441` (same pattern for backup) | exact (verbatim AST guard pattern, extended file list) |
| 33 | `.github/workflows/registry-gate.yml` *(new, or extend research-gate.yml)* | ci-gate | registry-rejection workflow | `.github/workflows/research-gate.yml:1-135` (Phase-1 D-07 gate — freeze check + identity-tuple check + registry-path tripwire) | exact (extend Phase-1 gate story) |

## Pattern Assignments

### 1. `src/domain/__init__.py` *(new)* — domain-entity / barrel re-export

**Analog:** `src/adapters/__init__.py` (barrel re-export convention — no logic, only `from .module import Symbol` lines).

**Shape** (verbatim from `src/adapters/__init__.py` pattern):
```python
# Source: src/adapters/__init__.py — barrel re-export convention
from .enums import (
    SignalStatus, TradePlanStatus, ApprovalAction, OrderStatus,
    PositionStatus, SystemMode,
)
from .signal import Signal
from .trade_plan import TradePlan
from .approval import Approval
from .order import Order
from .fill import Fill
from .position import Position
from .journal import JournalEvent
from .registry import (
    ParameterSet, load_parameter_set, verify_parameter_set,
    UnregisteredParameterSet, ParameterSetMutated,
    RegistrySchemaMismatch, StrategyKeyOutsideRegistry,
)

__all__ = [
    "Signal", "TradePlan", "Approval", "Order", "Fill", "Position", "JournalEvent",
    "SignalStatus", "TradePlanStatus", "ApprovalAction", "OrderStatus",
    "PositionStatus", "SystemMode",
    "ParameterSet", "load_parameter_set", "verify_parameter_set",
    "UnregisteredParameterSet", "ParameterSetMutated",
    "RegistrySchemaMismatch", "StrategyKeyOutsideRegistry",
]
```

**Why barrel-only:** D-01 — the domain package must be importable without side effects; no logic in `__init__.py` keeps the import graph clean for Phase 4 pure functions.

---

### 2. `src/domain/enums.py` *(new)* — domain-enum / GLOSSARY-canonical

**Analog:** `src/adapters/binance_usdm.py:49-67` (frozen dataclass + `str, Enum` mixin precedent) + `docs/GLOSSARY.md:39-143` (canonical values).

**Shape** (verbatim from `03-RESEARCH.md:317-377` §Code Examples):
```python
# Source: docs/GLOSSARY.md §§2-8 (verbatim values — copy exactly, invent nothing)
from enum import Enum

class SignalStatus(str, Enum):
    DETECTED = "DETECTED"
    NOTIFIED = "NOTIFIED"
    VIEWED = "VIEWED"
    APPROVED = "APPROVED"
    SKIPPED_USER = "SKIPPED_USER"
    SKIPPED_BUSY = "SKIPPED_BUSY"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"

class TradePlanStatus(str, Enum):
    READY = "READY"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"

class ApprovalAction(str, Enum):   # NOTE: GLOSSARY defines ApprovalAction, not ApprovalStatus
    SIMULATE = "SIMULATE"
    APPROVE = "APPROVE"
    SKIP_USER = "SKIP_USER"
    SKIP_BUSY = "SKIP_BUSY"
    CANCEL = "CANCEL"

class OrderStatus(str, Enum):
    PLANNED = "PLANNED"            # entry state — no approval state on orders (D024)
    SUBMITTING = "SUBMITTING"
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"

class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    LIQUIDATION_REPORTED = "LIQUIDATION_REPORTED"
    UNKNOWN = "UNKNOWN"

class SystemMode(str, Enum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE_APPROVAL = "LIVE_APPROVAL"
    SAFE_MODE = "SAFE_MODE"
    LIVE_AUTONOMOUS_DISABLED = "LIVE_AUTONOMOUS_DISABLED"
```

**Why `str, Enum` mixin:** keeps ORM `.value` storage trivial while preserving Enum identity for mypy checks. Same idiom as `src/adapters/binance_usdm.py:49-67` (frozen dataclass with `Decimal` + UTC).

**D-10 mapping:** unknown status at any boundary raises `ValueError` via `Enum(value)` coercion. No stringly-typed statuses anywhere.

---

### 3. `src/domain/canonical.py` *(new)* — domain-canonical / scalar normalizer + SHA256

**Analog:** `src/adapters/binance_usdm.py:130-132` (`_ms_to_utc` — UTC discipline) + `src/data/quality.py:25-33` (single-source-of-truth table pattern) + `03-RESEARCH.md:425-463` §Code Examples canonicalizer.

**Shape** (verbatim from `03-RESEARCH.md:425-463` §Code Examples):
```python
# Source: 03-RESEARCH.md:425-463 — Canonicalizer core (kailash-py _canonical.py whitelist + RFC 8785 JCS profile)
import hashlib
import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

def canonical_scalars(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: canonical_scalars(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [canonical_scalars(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)          # full precision: "1.50" ≠ "1.5" by design
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime in canonical hash input")
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        raise TypeError("unordered set in canonical hash input — use a sorted list")
    if isinstance(value, float):
        raise TypeError("float in canonical hash input — use Decimal/str/int")
    return value                   # str/int/bool/None pass through; anything else → json TypeError

def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(canonical_scalars(payload), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")

def sha256_hex(payload: dict) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()
```

**Why no `default=str`:** silently implementation-defined; breaks byte parity across versions. Let `TypeError` fire.

**Why `allow_nan=False`:** `float('nan')`/`inf` have no canonical JSON form; reject loudly.

**Why `Decimal → str()`:** full precision preserved (`Decimal("1.50")` stays `"1.50"`, never `"1.5"`).

---

### 4. `src/domain/ids.py` *(new)* — domain-ids / content-hash ID constructors

**Analog:** `src/adapters/binance_usdm.py:49-67` (frozen dataclass precedent) + `03-RESEARCH.md:379-423` §Code Examples `make_signal_id` + `derive_child_id`.

**Shape** (verbatim from `03-RESEARCH.md:407-423` §Code Examples):
```python
# Source: 03-RESEARCH.md:407-423 — D-03 binding superset (parameterSetId included)
from datetime import datetime
from .canonical import sha256_hex

def make_signal_id(*, strategy_version: str, parameter_set_id: str, symbol: str,
                   source_timeframe: str, source_candle_close_utc: datetime,
                   setup_fingerprint: str) -> str:
    return sha256_hex({
        "strategy_version": strategy_version,
        "parameter_set_id": parameter_set_id,
        "symbol": symbol,
        "source_timeframe": source_timeframe,
        "source_candle_close_utc": source_candle_close_utc,  # canonical.py → isoformat
        "setup_fingerprint": setup_fingerprint,
    })

def derive_child_id(parent_signal_id: str, discriminator: str) -> str:
    # plan/order IDs: parent hash + fixed discriminator ("trade_plan:v1", "order:entry", …)
    return sha256_hex({"parent_signal_id": parent_signal_id, "discriminator": discriminator})
```

**D-03 binding superset:** `strategyVersion + parameterSetId + symbol + source_timeframe + source_candle_close_utc + setup_fingerprint`. The fingerprint is an opaque canonical-JSON string so Phase 4 can widen it without changing the ID scheme.

---

### 5-11. `src/domain/{signal,trade_plan,approval,order,fill,position,journal}.py` *(new)* — domain-entity / frozen dataclasses

**Analog:** `src/adapters/binance_usdm.py:49-67` (`Kline` frozen dataclass with `Decimal` + UTC) + `03-RESEARCH.md:379-407` §Code Examples Signal shape.

**Shape** (verbatim from `03-RESEARCH.md:379-407` §Code Examples, applied to all 7 entities):
```python
# Source: src/adapters/binance_usdm.py:49-67 (Kline frozen dataclass) + 03-RESEARCH.md:379-407
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .enums import SignalStatus

@dataclass(frozen=True)
class Signal:
    signal_id: str                 # content hash from ids.make_signal_id — never passed in by callers
    strategy_id: str
    strategy_version: str
    parameter_set_id: str
    parameter_set_hash: str
    symbol: str
    direction: str                 # LONG/SHORT — Phase 4 may promote to Enum; D-09 keeps Phase 3 minimal
    setup_type: str
    source_timeframe: str
    source_candle_close_utc: datetime   # aware UTC; loader/mapper assert tzinfo
    detected_at_utc: datetime
    status: SignalStatus           # explicit — never inferred (D-11)
    expires_at_utc: datetime
    invalidated_at_utc: datetime | None = None  # None = "never happened" (D-11)
```

**Conventions applied to all 7 entities:**
- `@dataclass(frozen=True)` — immutable value flows through the pipeline (same as `Kline`).
- Money/qty/price fields are `Decimal` (no float for exchange-sensitive values per ENGINEERING_PRINCIPLES).
- Timestamps are `datetime` with `tzinfo=UTC` (D-06).
- Status fields are `Enum` (D-10) — explicit, never inferred from nullable columns (D-11).
- `Optional` is reserved for "transition never happened" timestamps only (D-11).

**D-11 mapping:** `status` alone answers "what state"; NULL timestamp = "transition never happened". No `approved_at IS NOT NULL ⇒ approved` inference.

---

### 12. `src/domain/registry.py` *(new)* — domain-registry / TOML loader + fail-closed

**Analog:** `src/data/store.py:43-91` (`publish_batch` — fail-closed immutability) + `src/data/quality.py:98-210` (`check_batch` — fail-closed structural gate) + `03-RESEARCH.md:465-509` §Code Examples registry loader.

**Shape** (verbatim from `03-RESEARCH.md:465-509` §Code Examples):
```python
# Source: 03-RESEARCH.md:465-509 — Fail-closed registry loader (D-04/D-05/D-06)
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .canonical import canonical_bytes, sha256_hex

REGISTRY_ROOT = Path("params")
SCHEMA_VERSION = 1
# Closed whitelist of strategy-semantic keys (D-06). Anything strategy-semantic
# found OUTSIDE the registry raises; anything unknown INSIDE raises.
STRATEGY_KEYS = frozenset({
    "swing_lookback", "zone_tolerance_atr", "breakout_confirmation_bars",
    "entry_buffer_atr", "sl_buffer_atr", "minimum_rr", "signal_expiry_hours",
    "risk_rate", "minimum_risk_utilization_after_rounding",
})  # seed list from CONFIGURATION.md §3 strategy examples — planner extends deliberately, never silently

class UnregisteredParameterSet(Exception): ...
class ParameterSetMutated(Exception): ...
class RegistrySchemaMismatch(Exception): ...
class StrategyKeyOutsideRegistry(Exception): ...

@dataclass(frozen=True)
class ParameterSet:
    strategy_id: str
    strategy_version: str
    parameter_set_id: str
    parameter_set_hash: str   # sha256 over canonical JSON of the normalized params doc
    params: dict              # normalized values (Decimals preserved, not floats)

def load_parameter_set(strategy_id: str, parameter_set_id: str) -> ParameterSet:
    path = REGISTRY_ROOT / strategy_id / f"{parameter_set_id}.toml"
    if not path.is_file():
        raise UnregisteredParameterSet(f"{strategy_id}/{parameter_set_id}")
    doc = tomllib.loads(path.read_bytes().decode("utf-8"))
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise RegistrySchemaMismatch(f"{path}: {doc.get('schema_version')!r}")
    # …validate identity fields, normalize numerics (whole floats→int iff integral
    # else Decimal(str(v))), reject unknown keys, sha256 over canonical body…

def verify_parameter_set(path: Path, expected_hash: str) -> None:
    """Re-hash a TOML file and raise ParameterSetMutated on mismatch (D-04/D-05)."""
    doc = tomllib.loads(path.read_bytes().decode("utf-8"))
    actual_hash = sha256_hex(doc)
    if actual_hash != expected_hash:
        raise ParameterSetMutated(f"{path}: expected {expected_hash}, got {actual_hash}")
```

**Why fail-closed:** D-04/D-05 — never a silent fallback. Unknown strategy-semantic key outside the registry raises (D-06). Mutated set raises `ParameterSetMutated`.

**Why custom exception types:** mypy-checkable; tests assert on specific exception types (not string matching).

---

### 13. `src/db/models.py` *(modified — extend)* — orm-model / 7 new tables on existing `Base`

**Analog:** `src/db/models.py:33-228` (single-Base + TIMESTAMPTZ + NUMERIC(38,18) + JSON-as-TEXT convention).

**Conventions to replicate** (verbatim from `src/db/models.py:10-13`):
```python
# Source: src/db/models.py:10-13 — All timestamps TIMESTAMPTZ, all money/qty NUMERIC(38,18)
from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

class SignalRow(Base):
    __tablename__ = "signals"
    signal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    parameter_set_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # SignalStatus.value — explicit (D-11)
    source_candle_close_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invalidated_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # …remaining DATA_MODEL §2.3 fields; prices/qty NUMERIC(38,18); payloads String…
```

**Conventions applied to all 7 tables:**
- Single `Base` (already defined at `src/db/models.py:33-39`).
- PK on the deterministic content-hash ID (D-03).
- `TIMESTAMPTZ` for all timestamps (UTC enforced at ORM boundary).
- `NUMERIC(38, 18)` for money/qty/price fields.
- `String` (unbounded) for JSON-as-TEXT blobs (portable across PG versions).
- `String(16)` for status columns (stores `Enum.value`).
- `nullable=True` ONLY for "transition never happened" timestamps (D-11).

**No ORM class IS the domain model** (D-02): `src/domain/` never imports from `src/db/`.

---

### 14. `src/db/mappers.py` *(new)* — mapper / thin total `to_row`/`from_row`

**Analog:** `src/data/metadata.py:37-90` (`refresh_symbol_metadata` — versioned INSERT pattern) + `src/adapters/binance_usdm.py:161-192` (`_row_to_kline` — adapter row→dataclass mapping).

**Shape** (per-entity round-trip tested):
```python
# Source: src/data/metadata.py:37-90 (versioned INSERT) + src/adapters/binance_usdm.py:161-192 (row→dataclass)
from src.domain.signal import Signal
from src.db.models import SignalRow

def signal_to_row(s: Signal) -> SignalRow:
    return SignalRow(
        signal_id=s.signal_id,
        strategy_version=s.strategy_version,
        parameter_set_id=s.parameter_set_id,
        parameter_set_hash=s.parameter_set_hash,
        symbol=s.symbol,
        status=s.status.value,  # Enum → .value for ORM storage
        source_candle_close_utc=s.source_candle_close_utc,
        invalidated_at_utc=s.invalidated_at_utc,
        # …remaining fields
    )

def signal_from_row(r: SignalRow) -> Signal:
    return Signal(
        signal_id=r.signal_id,
        strategy_version=r.strategy_version,
        parameter_set_id=r.parameter_set_id,
        parameter_set_hash=r.parameter_set_hash,
        symbol=r.symbol,
        status=SignalStatus(r.status),  # .value → Enum (raises on unknown — D-10)
        source_candle_close_utc=r.source_candle_close_utc,
        invalidated_at_utc=r.invalidated_at_utc,
        # …remaining fields
    )

# assert signal_from_row(signal_to_row(s)) == s  (per-entity round-trip test)
```

**Why total + round-trip tested:** every field mapped; `from_row(to_row(x)) == x` round-trip test per entity catches drift.

**Why `Enum(value)` coercion at boundary:** D-10 — unknown status raises `ValueError` loudly.

---

### 15. `src/db/alembic/versions/0002_domain_registry.py` *(new)* — migration / 7 tables

**Analog:** `src/db/alembic/versions/0001_baseline.py:1-111` (same convention: TIMESTAMPTZ + NUMERIC(38,18) + JSON-as-TEXT + reviewed migration).

**Shape** (verbatim from `src/db/alembic/versions/0001_baseline.py:1-17` docstring convention):
```python
# Source: src/db/alembic/versions/0001_baseline.py:1-17 — Same convention as baseline
"""Domain + registry mirror — Phase 3 (DOMN-01/DOMN-02 storage half).

op.create_table(...) calls match src/db/models.py Mapped[...] columns 1:1
(same convention as 0001_baseline.py). Verified offline by
scripts/check_migration_parity.py — no script changes needed.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002_domain_registry"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("signal_id", sa.String(length=128), nullable=False),
        sa.Column("strategy_version", sa.String(length=32), nullable=False),
        sa.Column("parameter_set_id", sa.String(length=64), nullable=False),
        sa.Column("parameter_set_hash", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_candle_close_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at_utc", sa.DateTime(timezone=True), nullable=True),
        # …remaining DATA_MODEL §2.3 fields
        sa.PrimaryKeyConstraint("signal_id"),
    )
    op.create_index("ix_signals_symbol_close", "signals", ["symbol", "source_candle_close_utc"], unique=False)
    # …6 more tables (trade_plans, approvals, orders, fills, positions, journal_events)
    # …indexes on (parameter_set_id, parameter_set_hash) for registry join queries

def downgrade() -> None:
    op.drop_table("journal_events")
    op.drop_table("positions")
    op.drop_table("fills")
    op.drop_table("orders")
    op.drop_table("approvals")
    op.drop_table("trade_plans")
    op.drop_table("signals")
```

**Parity-gate coverage:** `scripts/check_migration_parity.py:137-154, 178-210` renders `head` DDL and diffs the full `Base.metadata` — new tables flow through automatically with zero script changes.

---

### 16. `params/<strategy_id>/<parameter_set_id>.toml` *(new, seed)* — domain-registry / versioned TOML

**Analog:** `tests/fixtures/exchange_info_sample.json` (recorded golden fixture precedent) + `docs/configuration/CONFIGURATION.md` §§2-7 (parameter-set identity contract).

**Shape** (hand-authored, immutable once used):
```toml
# Source: docs/configuration/CONFIGURATION.md §§2-7 — parameter-set identity contract
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
minimum_risk_utilization_after_rounding = 0.6
```

**Why hand-authored (not `tomli-w`):** stdlib `tomllib` is read-only; the small number of seed TOML files can be hand-authored once and treated as immutable artifacts. Zero new dependencies.

**D-04 immutability:** once a parameter set is referenced by a backtest/alert/order plan, its hash is stored permanently. Mutation raises `ParameterSetMutated` on next load.

---

### 17-20. `tests/fixtures/phase3/{candles.csv,parameters.json,expected_signals.json,expected_plans.json}` *(new, golden)* — test-fixture / golden triple

**Analog:** `tests/fixtures/exchange_info_sample.json` (recorded golden fixture precedent) + `docs/testing/TESTING_STRATEGY.md:13-22` §2 golden-fixture model.

**`candles.csv` shape** (verbatim from `docs/testing/TESTING_STRATEGY.md:25-29`):
```csv
# Source: docs/testing/TESTING_STRATEGY.md:25-29 — canonical candle CSV column order
symbol,timeframe,open_time_utc,open,high,low,close,volume
BTCUSDT,1h,2026-09-19T00:00:00Z,50000.00,50100.00,49900.00,50050.00,123.456
BTCUSDT,1h,2026-09-19T01:00:00Z,50050.00,50200.00,50000.00,50150.00,98.765
# …boundary-covering bars (empty input, single bar, warm-up-insufficient)
```

**`parameters.json` shape** (pinned registry set):
```json
{
  "strategy_id": "trend-pullback",
  "strategy_version": "v1.0.0",
  "parameter_set_id": "baseline-v1",
  "parameter_set_hash": "<sha256-hex-of-canonical-toml-body>"
}
```

**`expected_signals.json` / `expected_plans.json` shape** (byte-exact, minimal placeholders per D-09):
```json
{
  "signals": [],
  "plans": []
}
```

**Why minimal placeholders:** D-09 — Phase 3 proves the MECHANISM with empty/minimal expectations; Phase 4 populates real family expectations without changing the harness.

---

### 21. `tests/conftest.py` *(modified — extend)* — test-fixture / shared

**Analog:** `tests/conftest.py:30-49` (golden_exchange_info + frozen_clock + fixture_path pattern).

**Shape** (extend existing fixture pattern):
```python
# Source: tests/conftest.py:30-49 — extend existing fixture pattern
from pathlib import Path

PHASE3_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase3"

@pytest.fixture(scope="session")
def phase3_candles() -> list[dict]:
    """Load the hand-built boundary-covering candle CSV."""
    import csv
    with (PHASE3_FIXTURES_DIR / "candles.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))

@pytest.fixture(scope="session")
def phase3_parameters() -> dict:
    """Load the pinned registry set."""
    import json
    return json.loads((PHASE3_FIXTURES_DIR / "parameters.json").read_text(encoding="utf-8"))

@pytest.fixture(scope="session")
def phase3_expected_signals() -> dict:
    """Load the byte-exact expected signals."""
    import json
    return json.loads((PHASE3_FIXTURES_DIR / "expected_signals.json").read_text(encoding="utf-8"))

@pytest.fixture(scope="session")
def phase3_expected_plans() -> dict:
    """Load the byte-exact expected plans."""
    import json
    return json.loads((PHASE3_FIXTURES_DIR / "expected_plans.json").read_text(encoding="utf-8"))
```

**Why session-scoped:** fixtures are immutable golden data; loaded once per test session.

---

### 22. `tests/test_domain_enums.py` *(new)* — test-suite / enum membership + no-invented-names

**Analog:** `tests/test_metadata.py:152-187` (golden fixture inserts one row per live-5) + `tests/test_collector.py:435-458` (PG-vs-SQLite boundary assertion).

**Test cases:**
1. **Enum membership** — every value in `SignalStatus` is a member of the GLOSSARY-canonical set.
2. **No invented names** — a string literal matching an enum value anywhere outside `enums.py` and its test fails.
3. **Unknown status raises** — `SignalStatus("UNKNOWN_VALUE")` raises `ValueError`.
4. **`.value` storage** — `SignalStatus.DETECTED.value == "DETECTED"` (ORM storage contract).

---

### 23. `tests/test_domain_ids.py` *(new)* — test-suite / content-hash ID stability

**Analog:** `tests/test_metadata.py:223-253` (Decimal exactness — byte-equality test pattern).

**Test cases:**
1. **Byte-equality across key orderings** — same logical payload built in different key insertion orders → identical digest.
2. **Decimal precision preserved** — `Decimal("1.50")` vs `Decimal("1.5")` → *different* digests (documented, not a bug).
3. **Naive datetime rejected** — `make_signal_id(..., source_candle_close_utc=datetime(2026, 9, 19), ...)` raises `ValueError`.
4. **Float rejected** — `make_signal_id(..., setup_fingerprint=1.5)` raises `TypeError`.
5. **Set rejected** — `make_signal_id(..., setup_fingerprint={"a", "b"})` raises `TypeError`.

---

### 24. `tests/test_domain_mappers.py` *(new)* — test-suite / mapper round-trip ×7

**Analog:** `tests/test_metadata.py:89-145` (CapturingSession pattern for SQLite NUMERIC lossiness) + `tests/test_collector.py:123-160` (in-memory SQLite session fixture).

**Test cases (per entity ×7):**
1. **Round-trip** — `signal_from_row(signal_to_row(s)) == s` for all 7 entities.
2. **CapturingSession snapshot** — assert on captured ORM instance BEFORE SQLite roundtrip (NUMERIC → REAL lossiness).
3. **Enum coercion** — `signal_from_row(row_with_unknown_status)` raises `ValueError`.
4. **Nullable timestamp** — `invalidated_at_utc=None` round-trips correctly.

**CapturingSession pattern** (verbatim from `tests/test_metadata.py:89-145`):
```python
# Source: tests/test_metadata.py:89-145 — CapturingSession for SQLite NUMERIC lossiness
class CapturingSession:
    """Wraps a SQLAlchemy session and records every `add()` call.

    SQLite stores NUMERIC as REAL (loses precision) and TIMESTAMP without
    tzinfo (drops the timezone). To assert on the values the mapper
    ACTUALLY wrote — not the lossy SQLite roundtrip — we snapshot
    a deep copy of the ORM instance at `add()` time.
    """
    def __init__(self, real: Session) -> None:
        self._real = real
        self.added: list[SignalRow] = []

    def add(self, obj: object) -> None:
        if isinstance(obj, SignalRow):
            self.added.append(SignalRow(...))  # snapshot before commit
        return self._real.add(obj)
```

---

### 25. `tests/test_registry.py` *(new)* — test-suite / loader + hash stability

**Analog:** `tests/test_metadata.py:223-253` (Decimal exactness — byte-equality test pattern).

**Test cases:**
1. **Registered set loads** — `load_parameter_set("trend-pullback", "baseline-v1")` returns `ParameterSet` with correct hash.
2. **Hash stable across key orderings** — same TOML parsed twice → identical hash.
3. **Decimal precision preserved** — `Decimal("1.50")` vs `Decimal("1.5")` → different hashes.
4. **Schema version mismatch raises** — TOML with `schema_version = 2` raises `RegistrySchemaMismatch`.
5. **Unknown strategy key raises** — TOML with unknown key raises `StrategyKeyOutsideRegistry`.

---

### 26. `tests/test_registry_gate.py` *(new)* — test-suite / negative tests

**Analog:** `tests/test_collector.py:216-260` (per-symbol failure isolation — negative test pattern).

**Test cases:**
1. **Unregistered set fails closed** — `load_parameter_set("trend-pullback", "does-not-exist")` raises `UnregisteredParameterSet`.
2. **Mutated set fails closed** — copy seed TOML, flip one digit, `verify_parameter_set(..., expected_hash)` raises `ParameterSetMutated`.
3. **Strategy key outside registry raises** — env var `STRATEGY_SWING_LOOKBACK=50` present → loader fails closed (D-06).
4. **CI gate workflow exists** — `.github/workflows/registry-gate.yml` (or extended `research-gate.yml`) references `params/` and `parameterSetHash`.

---

### 27. `tests/test_fixture_harness.py` *(new)* — test-suite / golden triple loads

**Analog:** `tests/test_metadata.py:152-187` (golden fixture loads + asserts) + `tests/conftest.py:30-49` (golden_exchange_info fixture).

**Test cases:**
1. **Golden triple loads** — `phase3_candles`, `phase3_parameters`, `phase3_expected_signals`, `phase3_expected_plans` all load without error.
2. **Placeholder expectations byte-exact** — empty signals/plans match the harness output.
3. **Registry round-trip** — `load_parameter_set` from `phase3_parameters` returns matching `ParameterSet`.

---

### 28. `tests/test_no_lookahead.py` *(new)* — test-suite / no-lookahead determinism

**Analog:** `tests/test_collector.py:268-304` (skipped tick — expected vs observed, no interpolation) + `src/data/backfill.py:337-342` (drop forming candle — Pitfall 1 precedent).

**Test cases:**
1. **Appended bars never change earlier outputs** — run over prefix ending at T, append arbitrary bars after T, re-run; outputs at/before T byte-identical.
2. **Forming candle excluded** — signal absent on the forming candle, appears exactly once after close.

**Shape** (verbatim from `03-RESEARCH.md:551-571` §Code Examples):
```python
# Source: 03-RESEARCH.md:551-571 — no-lookahead suite skeleton
def test_appended_bars_never_change_earlier_outputs(phase3_candles) -> None:
    before = run_domain_pipeline(phase3_candles[:N])          # placeholder fn per D-09
    after = run_domain_pipeline(phase3_candles[:N] + EXTRA_BARS)
    assert canonical_of(after[:N]) == canonical_of(before)    # byte comparison via canonical_bytes
```

---

### 29. `tests/test_prefix_invariance.py` *(new)* — test-suite / prefix-invariance determinism

**Analog:** `tests/test_collector.py:622-694` (per-symbol resume — idempotent re-run pattern).

**Test cases:**
1. **Same prefix → byte-identical prefix outputs** — same prefix in two different longer inputs → byte-identical prefix outputs (stdlib `hashlib` over canonical JSON of outputs for the byte comparison).

---

### 30. `tests/test_candle_close_timing.py` *(new)* — test-suite / candle-close-timing determinism

**Analog:** `src/adapters/binance_usdm.py:49-55` (`Kline.close_time_utc <= now_utc` invariant) + `src/data/backfill.py:337-342` (drop forming candle).

**Test cases:**
1. **No signal before source candle close** — signal absent on the forming candle, appears exactly once after close.
2. **Close-time invariant** — `Kline.close_time_utc <= now_utc` enforced (TESTING_STRATEGY §4).

**Shape** (verbatim from `03-RESEARCH.md:559-562` §Code Examples):
```python
# Source: 03-RESEARCH.md:559-562 — candle-close-timing suite skeleton
def test_no_signal_before_source_candle_close(phase3_candles) -> None:
    assert run_domain_pipeline(phase3_candles[:N-1]) == run_domain_pipeline(phase3_candles[:N-1])
    # forming-candle input: no signal referencing close(N); closed-candle input: exactly one
```

---

### 31. `tests/test_domain_boundary.py` *(new)* — test-suite / boundary determinism

**Analog:** `tests/test_collector.py:505-543` (healthcheck with/without watermarks — boundary pattern).

**Test cases:**
1. **Empty input** — `run_domain_pipeline([])` returns explicit invalid reason, never crashes.
2. **Single bar** — `run_domain_pipeline([one_bar])` returns explicit invalid reason (warm-up insufficient).
3. **Warm-up insufficient** — `run_domain_pipeline(too_few_bars)` returns explicit invalid reason.

---

### 32. `tests/test_domain_no_float.py` *(new)* — test-suite / AST no-`float(` guard extended

**Analog:** `tests/test_metadata.py:256-292` (`_find_float_calls` + `test_no_float_call_in_metadata_or_adapter`) + `tests/test_coverage.py:650-662` (same pattern for coverage) + `tests/test_backup.py:431-441` (same pattern for backup).

**Shape** (verbatim from `tests/test_metadata.py:256-292`):
```python
# Source: tests/test_metadata.py:256-292 — AST no-float guard pattern
def _find_float_calls(src: str) -> list[tuple[int, str]]:
    """AST-walk source and return `(line_no, line_text)` for every call to `float(...)`."""
    import ast
    calls: list[tuple[int, str]] = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "float":
                calls.append((node.lineno, src.splitlines()[node.lineno - 1].strip()))
    return calls

def test_no_float_call_in_domain_or_mappers() -> None:
    """Static guard: the domain path must not contain any explicit `float(...)` call.

    D-12 + ENGINEERING_PRINCIPLES: float is banned for exchange-sensitive
    values. Extended to src/domain/ + src/db/mappers.py.
    """
    repo_root = Path(__file__).resolve().parent.parent
    for rel in (
        "src/domain/enums.py", "src/domain/canonical.py", "src/domain/ids.py",
        "src/domain/signal.py", "src/domain/trade_plan.py", "src/domain/approval.py",
        "src/domain/order.py", "src/domain/fill.py", "src/domain/position.py",
        "src/domain/journal.py", "src/domain/registry.py",
        "src/db/mappers.py",
    ):
        path = repo_root / rel
        src = path.read_text(encoding="utf-8")
        offenders = _find_float_calls(src)
        assert not offenders, (
            f"{rel} must not contain any explicit `float(...)` call — "
            f"Decimal is the only allowed exchange-sensitive type. "
            f"Found: {offenders}"
        )
```

---

### 33. `.github/workflows/registry-gate.yml` *(new, or extend research-gate.yml)* — ci-gate / registry-rejection

**Analog:** `.github/workflows/research-gate.yml:1-135` (Phase-1 D-07 gate — freeze check + identity-tuple check + registry-path tripwire).

**Shape** (extend Phase-1 gate story):
```yaml
# Source: .github/workflows/research-gate.yml:1-135 — extend Phase-1 gate story
name: registry-gate
on:
  pull_request:
    branches: [master]
  push:
    branches: [master]
jobs:
  registry-gate:
    name: registry-gate (D-05)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Registry hash check (every params/** file must hash to its recorded value)
        run: |
          set -eu
          # For each params/<strategy_id>/<parameter_set_id>.toml, compute SHA256
          # and compare against the hash recorded in any referencing run record.
          # Vacuous-green on empty registry (same tripwire story as Phase-1 D029).
          find params -name '*.toml' -type f | while read -r f; do
            echo "checking $f"
            # …hash computation + comparison
          done
      - name: Unregistered-set rejection (negative test)
        run: |
          set -eu
          uv run pytest tests/test_registry_gate.py -x -q
```

**Why extend Phase-1 gate:** D-05 — "rejected by gate, not by convention". The CI gate is the enforcement mechanism; the loader exception is the runtime mechanism.

---

## Shared Patterns

### Domain boundary (cross-cutting, applies to all `src/domain/` files)

Per D-01 + `src/adapters/binance_usdm.py:1-15` (adapter boundary precedent):

```text
src/domain/  ── ONLY ──> stdlib (dataclasses, enum, hashlib, json, tomllib, datetime, decimal)
        │
        └── frozen dataclasses (Signal, TradePlan, Approval, Order, Fill, Position, JournalEvent)
                    │
                    ▼
        src/db/mappers.py  (to_row / from_row, thin, total)
                    │
                    ▼
        src/db/models.py  (7 ORM tables, NUMERIC(38,18), TIMESTAMPTZ)
```

**Apply to:** every file in `src/domain/`. The domain package must be importable without SQLAlchemy, Pydantic, Polars, or the Binance SDK. Phase 4 pure functions import these types with zero DB/network weight.

### Frozen dataclass + Decimal + UTC + Enum (cross-cutting, applies to all 7 entities)

Per `src/adapters/binance_usdm.py:49-67` (Kline frozen dataclass) + D-12:

```python
# Source: src/adapters/binance_usdm.py:49-67 — frozen dataclass + Decimal + UTC
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

@dataclass(frozen=True)
class Signal:
    signal_id: str
    # …money/qty/price fields are Decimal
    # …timestamps are datetime with tzinfo=UTC
    # …status fields are Enum (D-10)
    # …nullable timestamps only for "transition never happened" (D-11)
```

**Apply to:** all 7 entities. No `float` anywhere on the Decimal path. No naive datetimes. No stringly-typed statuses.

### Canonical-hash identity (cross-cutting, applies to registry + IDs)

Per `03-RESEARCH.md:425-463` §Code Examples canonicalizer + RFC 8785 JCS profile:

```python
# Source: 03-RESEARCH.md:425-463 — canonical_bytes + sha256_hex
import hashlib
import json

def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(canonical_scalars(payload), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")

def sha256_hex(payload: dict) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()
```

**Apply to:** `src/domain/canonical.py` (shared by `ids.py` + `registry.py`). Same normalizer for `parameterSetHash` and `SignalId` — one source of truth for byte-equality.

### Fail-closed posture (cross-cutting, applies to registry + mappers + tests)

Per `src/data/store.py:43-91` (fail-closed immutability) + `src/data/quality.py:98-210` (fail-closed structural gate) + D-04/D-05/D-06:

```text
unknown parameter set    → UnregisteredParameterSet (D-04)
mutated parameter set    → ParameterSetMutated (D-04/D-05)
schema version mismatch  → RegistrySchemaMismatch (D-04)
strategy key outside     → StrategyKeyOutsideRegistry (D-06)
unknown status           → ValueError via Enum(value) (D-10)
float in canonical input → TypeError (D-12)
naive datetime in hash   → ValueError (D-12)
```

**Apply to:** `src/domain/registry.py`, `src/domain/canonical.py`, `src/db/mappers.py`, all test suites. Never a silent fallback.

### UTC-internally / HCMC-display-edge (cross-cutting, applies to every timestamp)

Per `src/data/coverage.py:190-199` (`_format_utc` — UTC store, HCMC display edge) + D-06:

```python
# Source: src/data/coverage.py:190-199 — UTC store, HCMC display edge
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

def _format_utc(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    hcmc = dt.astimezone(DISPLAY_TZ)
    return f"{dt.isoformat()}  ({hcmc.strftime('%Y-%m-%d %H:%M %Z')})"
```

**Apply to:** every model field of type `datetime` (use `TIMESTAMPTZ` not `TIMESTAMP`), every CLI output, every log line. Domain stores UTC only; `Asia/Ho_Chi_Minh` only at display edges.

### Decimal-only for exchange-sensitive values (cross-cutting)

Per `src/adapters/binance_usdm.py:9-15` (Decimal-only discipline) + D-12:

```text
✓ Decimal / integer tick-step arithmetic for prices, quantities, notional, filters
✗ float()  for any persisted financial value
```

**Apply to:** all 7 entities (money/qty/price fields), `src/db/mappers.py` (Decimal → NUMERIC(38,18)), `src/domain/registry.py` (Decimal preserved in canonical hash), `src/domain/canonical.py` (float rejected loudly). AST no-`float(` guard extended to all new files.

### Single-Base + parity-gate discipline (cross-cutting, applies to ORM + migration)

Per `src/db/models.py:33-39` (single `Base`) + `scripts/check_migration_parity.py:137-154, 178-210` (offline DDL diff):

```python
# Source: src/db/models.py:33-39 — single declarative base
class Base(DeclarativeBase):
    """Single declarative base for every model in `src/db/`.

    The Alembic env (src/db/alembic/env.py) binds this Base.metadata as
    `target_metadata` so a single source of schema truth covers the
    baseline migration and every later reviewed migration.
    """
```

**Apply to:** `src/db/models.py` (extend with 7 tables on existing `Base`), `src/db/alembic/versions/0002_domain_registry.py` (same convention as `0001_baseline.py`). `scripts/check_migration_parity.py` covers new tables with zero script changes.

### CapturingSession pattern (cross-cutting, applies to all mapper tests)

Per `tests/test_metadata.py:89-145` (CapturingSession for SQLite NUMERIC lossiness):

```python
# Source: tests/test_metadata.py:89-145 — CapturingSession for SQLite NUMERIC lossiness
class CapturingSession:
    """Wraps a SQLAlchemy session and records every `add()` call.

    SQLite stores NUMERIC as REAL (loses precision) and TIMESTAMP without
    tzinfo (drops the timezone). To assert on the values the mapper
    ACTUALLY wrote — not the lossy SQLite roundtrip — we snapshot
    a deep copy of the ORM instance at `add()` time.
    """
    def __init__(self, real: Session) -> None:
        self._real = real
        self.added: list[SignalRow] = []

    def add(self, obj: object) -> None:
        if isinstance(obj, SignalRow):
            self.added.append(SignalRow(...))  # snapshot before commit
        return self._real.add(obj)
```

**Apply to:** `tests/test_domain_mappers.py` (per-entity round-trip ×7). Document PG-vs-SQLite boundary in test docstring as Phase 2 did.

### AST no-`float(` guard (cross-cutting, applies to all new domain code)

Per `tests/test_metadata.py:256-292` + `tests/test_coverage.py:650-662` + `tests/test_backup.py:431-441`:

```python
# Source: tests/test_metadata.py:256-292 — AST no-float guard pattern
def _find_float_calls(src: str) -> list[tuple[int, str]]:
    """AST-walk source and return `(line_no, line_text)` for every call to `float(...)`."""
    import ast
    calls: list[tuple[int, str]] = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "float":
                calls.append((node.lineno, src.splitlines()[node.lineno - 1].strip()))
    return calls
```

**Apply to:** `tests/test_domain_no_float.py` (extended file list: all `src/domain/*.py` + `src/db/mappers.py`). D-12 — float is banned for exchange-sensitive values.

### TDD RED→GREEN discipline (cross-cutting, applies to all test suites)

Per `tests/test_metadata.py:1-16` (TDD discipline docstring) + `tests/test_collector.py:1-18` (same):

```python
# Source: tests/test_metadata.py:1-16 — TDD discipline docstring
"""Tests for the versioned symbol metadata module (02-04 Task 1).

The 02-04 plan calls out four behaviors (02-04-PLAN §tasks[1].behavior):
  1. Golden exchangeInfo fixture inserts one new version row per live-5
     symbol with Decimal tick and step.
  2. Second refresh with identical filters still inserts a new observed-at
     version rather than updating.
  3. Filter strings parse to Decimal exactly with no float conversion
     anywhere on the path.
  4. Unknown symbol fields outside the live-5 are ignored without failing
     the refresh.

TDD discipline: RED → GREEN. These tests are the RED phase — they MUST
fail until `src/data/metadata.py` is implemented.
"""
```

**Apply to:** every test file. Tests are the RED phase; they MUST fail until the corresponding implementation lands. Atomic commits per behavior.

### Verification grep suite (cross-cutting, applies to the entire phase gate)

Per `02-PATTERNS.md` §Verification grep suite (Phase 2 precedent) + `03-RESEARCH.md` §Validation Architecture:

```bash
# DOMN-01: 7 entities persist separately; GLOSSARY enums round-trip
grep -rn "SignalStatus\|TradePlanStatus\|ApprovalAction\|OrderStatus" src/domain/

# DOMN-01: Migration 0002 matches ORM 1:1
uv run python scripts/check_migration_parity.py

# DOMN-01: No float( in domain/mapper/registry code
grep -rn "float(" src/domain/ src/db/mappers.py

# DOMN-02: Registered set loads; hash stable across key orderings
uv run pytest tests/test_registry.py -x -q

# DOMN-02: Unregistered set raises; mutated set raises
uv run pytest tests/test_registry_gate.py -x -q

# DOMN-03: Golden triple loads; placeholder expectations byte-exact
uv run pytest tests/test_fixture_harness.py -x -q

# DOMN-03: No-lookahead / prefix-invariance / candle-close-timing / boundary suites green
uv run pytest tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_candle_close_timing.py tests/test_domain_boundary.py -x -q

# Cross-cutting: domain boundary (no SQLAlchemy/Pydantic/Polars/SDK imports)
grep -rln "from sqlalchemy\|from pydantic\|import polars\|from binance_sdk" src/domain/

# Cross-cutting: UTC discipline
grep -rn "tzdata\|ZoneInfo\|timezone.utc" src/domain/
```

**Apply to:** every plan in the phase. Run at phase gate (`/gsd-verify-work`); failures block merge per RESEARCH.md §Validation Architecture.

---

## No Analog Found

| File | Module Role | Module Data Flow | Reason |
|------|-------------|------------------|--------|
| `params/<strategy_id>/<parameter_set_id>.toml` | domain-registry (data) | versioned TOML parameter set | Greenfield — no existing `params/` directory in repo. Format reference: `docs/configuration/CONFIGURATION.md` §§2-7 (parameter-set identity contract) + `03-RESEARCH.md:465-509` §Code Examples registry loader. The D-04 immutability rule + SHA256 identity is the analog, not a project TOML file to copy. |
| `tests/fixtures/phase3/candles.csv` | test-fixture (golden) | hand-built boundary-covering bars | Greenfield — no existing `tests/fixtures/phase3/` directory in repo. Format reference: `docs/testing/TESTING_STRATEGY.md:25-29` (candle CSV column order) + `tests/fixtures/exchange_info_sample.json` (recorded golden fixture precedent). The boundary-covering bar set is the analog, not a project CSV to copy. |
| `tests/fixtures/phase3/expected_signals.json` / `expected_plans.json` | test-fixture (golden) | byte-exact expected outputs | Greenfield — no existing Phase-3 expectations in repo. Format reference: `docs/testing/TESTING_STRATEGY.md:13-22` §2 golden-fixture model + D-09 (minimal placeholders). The byte-exact comparison contract is the analog, not a project JSON to copy. |

All other 30 files have a clear in-repo analog — either a Phase-2 module that ships the verbatim pattern (frozen dataclass, single-Base, CapturingSession, AST no-`float(` guard, frozen_clock, parity-gate) or a RESEARCH.md §Code Examples block that ships the verbatim Python shape.

---

## Metadata

**Analog search scope:** `src/**/*.py` (15 files — adapter, data, db, ops) + `tests/**/*.py` (11 files — conftest, test_metadata, test_collector, test_coverage, test_backup, test_adapter_strictness, test_backfill, test_quality_gates, test_tracer_slice, test_wave0_sanity) + `scripts/check_migration_parity.py` + `.github/workflows/research-gate.yml` + `pyproject.toml` + `docs/**/*.md` (DATA_MODEL, GLOSSARY, CONFIGURATION, RESEARCH_PROTOCOL, TESTING_STRATEGY, ENGINEERING_PRINCIPLES, TECHNOLOGY_STACK) + `03-RESEARCH.md` §Architecture Patterns (lines 142-252) and §Code Examples (lines 313-571).

**Files scanned:** 15 src + 11 tests + 1 script + 1 CI workflow + 1 pyproject + 7 docs + 1 RESEARCH.

**Tracked-source verification:** All cited in-repo analogs are git-tracked under `git ls-files`:
- `src/adapters/binance_usdm.py` (508 lines, tracked)
- `src/db/models.py` (228 lines, tracked)
- `src/db/alembic/versions/0001_baseline.py` (111 lines, tracked)
- `src/db/alembic/env.py` (77 lines, tracked)
- `src/data/quality.py` (210 lines, tracked)
- `src/data/backfill.py` (678 lines, tracked)
- `src/data/collector.py` (943 lines, tracked)
- `src/data/metadata.py` (90 lines, tracked)
- `src/data/store.py` (91 lines, tracked)
- `src/data/coverage.py` (610 lines, tracked)
- `tests/conftest.py` (56 lines, tracked)
- `tests/test_metadata.py` (324 lines, tracked)
- `tests/test_collector.py` (852 lines, tracked)
- `tests/test_coverage.py` (675 lines, tracked)
- `tests/test_backup.py` (618 lines, tracked)
- `scripts/check_migration_parity.py` (226 lines, tracked)
- `.github/workflows/research-gate.yml` (135 lines, tracked)
- `pyproject.toml` (80 lines, tracked)

The 27 new files Phase 3 will create do not exist yet — they will be created by Phase-3 plans. The 3 greenfield files (`params/` TOML seeds, `tests/fixtures/phase3/` golden triple) have no in-repo analog; format reference is RESEARCH.md §Code Examples + TESTING_STRATEGY.md §2.

**Pattern extraction date:** 2026-09-22

## PATTERN MAPPING COMPLETE

**Phase:** 03 — Domain + Registry + Fixtures
**Files classified:** 33 (27 new + 6 modified/extended)
**Analogs found:** 30 with in-repo analogs / 33 (3 greenfield files — `params/` TOML seeds, `tests/fixtures/phase3/` golden triple — reference doc policy, not project prior art)

### Coverage
- Files with exact in-repo analog: 30
- Files with no in-repo analog (greenfield data): 3

### Key Patterns Identified
- **Frozen dataclass + Decimal + UTC + Enum** is the operative pattern for all 7 domain entities (precedent: `src/adapters/binance_usdm.py:49-67` `Kline`).
- **Single-Base + parity-gate discipline** extends directly to 7 new ORM tables + migration 0002 (precedent: `src/db/models.py:33-228` + `src/db/alembic/versions/0001_baseline.py:1-111` + `scripts/check_migration_parity.py:137-154, 178-210`).
- **CapturingSession pattern** for SQLite NUMERIC lossiness extends directly to mapper round-trip tests (precedent: `tests/test_metadata.py:89-145`).
- **AST no-`float(` guard** extends directly to all new domain code (precedent: `tests/test_metadata.py:256-292` + `tests/test_coverage.py:650-662` + `tests/test_backup.py:431-441`).
- **Canonical-hash identity** (sorted keys + compact separators + scalar whitelist + `allow_nan=False`) is the shared normalizer for `parameterSetHash` and `SignalId` (precedent: `03-RESEARCH.md:425-463` §Code Examples).
- **Fail-closed registry loader** with custom exception types (precedent: `src/data/store.py:43-91` + `src/data/quality.py:98-210` + `03-RESEARCH.md:465-509` §Code Examples).
- **TDD RED→GREEN discipline** with atomic commits per behavior (precedent: `tests/test_metadata.py:1-16` + `tests/test_collector.py:1-18`).
- **CI gate extension** for registry rejection (precedent: `.github/workflows/research-gate.yml:1-135` Phase-1 D-07 gate).
