# Phase 10: Journal Depth + Kill-Gate Operations - Pattern Map

**Mapped:** 2026-09-29
**Files analyzed:** 17 (new/modified)
**Analogs found:** 16 / 17 (all analog paths verified git-tracked)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `src/analytics/__init__.py` | package | n/a | `src/backtest/__init__.py` | exact |
| `src/analytics/metrics.py` (MFE/MAE, exec-quality latencies, approval-delay 3 reports, robustness slices) | service (pure) | transform | `src/backtest/report.py` | exact |
| `src/analytics/report.py` (AnalyticsReport + digest + dual-universe) | model/service | transform | `src/backtest/report.py` (`UncertaintyReport`, `DualUniverseSection`) | exact |
| `src/analytics/digest.py` (or inline) | utility | transform | `src/paper/journal.py::paper_records_digest` | exact |
| `src/analytics/kill_gate.py` (D013 evaluator + JournalEvent) | service (pure) | event-driven | `src/ops/health.py::_record_health_check_event` + `src/execution/enablement.py::_journal_enablement_event` | role-match |
| `src/analytics/adapter.py` (journal row reader, edge) | adapter | CRUD read | `src/db/mappers.py` (thin-mapper) | role-match |
| `src/analytics/render.py` (MD/HTML + JSON sidecar) | utility | transform | `src/backtest/report.py` digest/section style | partial |
| `src/analytics/__main__.py` / cli | entry | batch | none in src (see No Analog) | none |
| `src/domain/enums.py` + `docs/GLOSSARY.md` (`KillGateState`) | model | n/a | `DailyState` (enums.py ~L159-170; GLOSSARY §8.1) | exact |
| `src/execution/enablement.py` (`enable()` change) | service | request-response | itself, L146-283 | exact |
| `scripts/dev/journal-report.ps1` | script | batch | `scripts/dev/test.ps1` + `_common.ps1` | exact |
| `tests/test_analytics_*.py`, `tests/test_kill_gate_*.py` | test | golden fixture | `tests/test_backtest_report.py` | exact |
| `tests/fixtures/phase10/*` | fixture | n/a | `tests/fixtures/phase6/report_slices/<case>/{input,expected}.json`, `phase9/enablement/` | exact |
| `tests/test_domain_no_float.py` (SCANNED_FILES) | test | n/a | itself L18-70 | exact |
| `docs/DECISIONS.md` (D030) | doc | n/a | row D029 (L34) | exact |
| `docs/research/RESEARCH_PROTOCOL.md` amendment note | doc | n/a | D029 three-witness pattern | role-match |

## Pattern Assignments

### `src/analytics/metrics.py` and `report.py` (pure, Decimal, frozen, digest)

**Analog:** `src/backtest/report.py` (889 lines)

**Module docstring/purity + imports** (L1-37):
```python
from __future__ import annotations
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.core._decimal import _add, _div, _mul, _q, _sub
from src.core.types import _require_utc_aware
from src.domain.canonical import sha256_hex

LIVE5_SYMBOLS: frozenset[str] = frozenset({"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"})
class ReportBuildError(Exception): ...
```
Reuse `LIVE5_SYMBOLS`, `_r_multiple`, `_has_zero_risk`, `_decimal_mean/median/pstdev`, `_quantile`, `BootstrapInterval`, `DualUniverseSlice/Section` by import rather than re-derive (CONTEXT D-01).

**Section dataclass with per-section digest** (L44-64, L259-300): every section is `@dataclass(frozen=True)` with `def digest(self) -> str: return sha256_hex({...})`; Decimals go straight into `sha256_hex` (canonical). Top-level report (L324-375) validates in `__post_init__` (`_require_non_empty`-style raising `ReportBuildError`, `_require_utc_aware(self.built_at_utc, ...)`) and its `digest()` composes child digests.

**Zero-risk exclusion (must be counted, not silent)** (L412-437):
```python
def _r_multiple(trade):
    ...
    if risk == Decimal("0"): return None
    return _div(pnl, risk)
def _has_zero_risk(trade) -> bool: ...
```
Copy for MFE/MAE R-multiples; count exclusions and INCOMPLETE buckets explicitly. Low-n: flag (`insufficient_data: bool` like `DualUniverseSlice`), never drop. Empty live-5 slice: `trade_count=0, mean_r=None, insufficient_data=True` rendered "no data".

**Rules:** no `float(`, no float literals (use `Decimal("0.5")`); no Polars/SQLAlchemy imports in metric modules.

### Digest contract — `paper_records_digest` (`src/paper/journal.py` L431-496)
Sort records by a stable key, build list of plain dicts (enum `.value`, `datetime.isoformat()` or None), then `sha256_hex(payload)`. Mirror for `analytics_report_digest`; identical inputs must give byte-identical digest.

### `src/analytics/kill_gate.py`
**Analogs:** `src/ops/health.py` L87-91, L222-248; `src/execution/enablement.py` L200-262.

JournalLike seam (health.py L87-91):
```python
class JournalLike(Protocol):
    def record(self, event: Any) -> None: ...
```
Event construction with content-hash id (enablement.py L170-200 shape):
```python
payload_json = json.dumps({...}, separators=(",", ":"))   # add sort_keys=True for evidence dicts
event = JournalEvent(
    journal_event_id=content_hash_event_id(prefix="kill_gate", event_type="KILL_GATE_EVALUATION",
        entity_id="KILL_GATE_D013", occurred_at_utc=now_utc, payload_json=payload_json),
    occurred_at_utc=now_utc, event_type="KILL_GATE_EVALUATION", entity_type="KillGate",
    entity_id="KILL_GATE_D013", correlation_id="kill_gate_evaluation", payload_json=payload_json)
journal.record(event)
```
`content_hash_event_id` (`src/domain/journal.py` L20-45): same inputs -> same id, so replay is idempotent (D-03). `JournalEvent.__post_init__` requires non-empty correlation/entity ids and UTC-aware datetimes. Evaluator itself is pure `evaluate(families, experiments, clock_start_utc, now_utc) -> KillGateEvaluation`; the journaling wrapper is separate (journal-first, as enablement).

### `KillGateState` (`src/domain/enums.py`)
**Analog:** `DailyState` (L159-170):
```python
class DailyState(str, Enum):
    """GLOSSARY §8 ..."""
    NORMAL = "NORMAL"
```
Add `KillGateState(str, Enum)`: `WITHIN_BUDGET`, `PASSING_CANDIDATE`, `INSUFFICIENT_EDGE`; add GLOSSARY section following §8.1 style; `tests/test_domain_enums.py` pins enum values, extend it.

### `src/execution/enablement.py` `enable()` change
Current (L146-190): signature `enable(self, *, operator_id, now_utc, health_verdict)`; validation raise-before-journal, then journal-first, then flip. Add an analogous fail-closed check placed BEFORE `_journal_enablement_event`, matching the health-verdict check:
```python
if health_verdict is None or getattr(health_verdict, "is_no_trade", True) is not False ...:
    raise ValueError("enable: a passing health verdict is required ...")
```
Add optional kill-gate input (e.g. `kill_gate_state`); default must stay fail-closed (INSUFFICIENT_EDGE blocks; never auto-clear). Tests extend `tests/test_execution_enablement.py` using `tests/fixtures/phase9/enablement/` style. Beware changing the signature breaks existing callers/tests; grep call sites.

### `src/analytics/adapter.py` (edge reader)
**Analog:** `src/db/mappers.py` thin mappers; PaperRecord docstring (`src/paper/journal.py` L1-24) documents "ORM behind mappers, pure core gets frozen dataclasses". Adapter converts ORM rows to frozen inputs; only file allowed to import SQLAlchemy/Polars/DuckDB. Read-only.

### `scripts/dev/journal-report.ps1`
**Analog:** `scripts/dev/test.ps1`:
```powershell
. (Join-Path $PSScriptRoot '_common.ps1')
try {
    Assert-Uv
    uv run python -m src.analytics @args
    $code = $LASTEXITCODE
} finally { Exit-RepoRoot }
exit $code
```
Use `Import-DotEnv`/`Set-ScopedEnv` from `_common.ps1` only if DB access needed. Document in `scripts/dev/README.md`. Output dir must be git-ignored (update `.gitignore`).

### Tests + fixtures
**Analog:** `tests/test_backtest_report.py`: `PHASE6_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase6"`, per-case dir with `input.json` + `expected.json` (`_load_input/_load_expected`), Decimal via strings, docstring declaring RED->GREEN. Create `tests/fixtures/phase10/<case>/{input,expected}.json` for the cases listed in D-05 (incomplete trade, zero-risk, empty live-5, low-n, three kill-gate states, clock provenance, idempotent replay, digest regeneration). Enablement tests: `tests/test_execution_enablement.py` (fixture pairs, secret-free log scan).

### `tests/test_domain_no_float.py`
Append to `SCANNED_FILES` (L18-70) following the per-phase comment convention:
```python
    # Phase 10 — pure analytics package (D-01 purity).
    "src/analytics/__init__.py",
    "src/analytics/metrics.py",
    "src/analytics/report.py",
    "src/analytics/kill_gate.py",
```
Exclude adapter and render modules only if they legitimately need non-Decimal (keep adapter out; render should still avoid floats). Test asserts every listed file exists, so add entries only when files land. Also check `tests/test_domain_boundary.py`/`test_quality_gates.py` for import-boundary lists needing `src/analytics`.

### `docs/DECISIONS.md` D030 + protocol amendment
**Analog:** row D029 (L34): `| D029 | title | Accepted | rationale... |`. Add D030 recording D013 AND-reading is authoritative over RESEARCH_PROTOCOL "Kill gate D013" OR-wording. Protocol is FROZEN with three-witness gate (`.github/workflows/research-gate.yml`): the amendment note must not break the freeze check; read the workflow before editing the protocol, and prefer an appended "Amendment" section referencing D030.

## Shared Patterns

- **Purity/determinism:** stdlib + Decimal, frozen dataclasses, `sha256_hex` (`src/domain/canonical.py`), UTC via `_require_utc_aware`, AST no-float guard.
- **Journal-first, content-hash id:** `content_hash_event_id` + `JournalLike.record`.
- **Fail closed:** raise `ValueError`/`ReportBuildError` on malformed input; missing data -> `INCOMPLETE` bucket, not imputed.
- **Dual universe:** `DualUniverseSlice/Section` + `LIVE5_SYMBOLS`.
- **Provenance:** carry strategy_version, parameter_set_id/hash, experiment identity (`src/backtest/experiment.py` `ExperimentRecord`), attribution kind (`src/paper/attribution.py::AttributionKind`); keep backtest/paper/live unpooled.

## No Analog Found

| File | Role | Reason |
|---|---|---|
| `src/analytics/__main__.py` / CLI entry | entry | No Python CLI/`__main__` module exists in src; `scripts/check_migration_parity.py` is the nearest standalone-script style. |
| `src/analytics/render.py` (Markdown/HTML) | renderer | No existing renderer; follow UI-SPEC (10-UI-SPEC.md) and use sorted, deterministic output with Asia/Ho_Chi_Minh display edge via `zoneinfo`. |

## Metadata

**Analog search scope:** src/backtest, src/paper, src/ops, src/domain, src/execution, scripts/dev, tests, tests/fixtures
**Pattern extraction date:** 2026-09-29
