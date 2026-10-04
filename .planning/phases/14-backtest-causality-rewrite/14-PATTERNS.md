# Phase 14: Backtest Causality Rewrite - Pattern Map

**Mapped:** 2026-10-04
**Files analyzed:** 27 new/modified
**Analogs found:** 25 / 27 (all analogs are git-tracked source under src/, tests/, scripts/)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `src/backtest/semantics.py` | config/constants | n/a | `src/backtest/costs.py` lines 35-63 (key vocab consts) | role-match |
| `src/backtest/series.py` | utility (Protocol + validation) | streaming/windowed read | `src/backtest/simulator.py` `_parse_candle`, `src/data/case_input.py` `_group_intrabar` | partial |
| `src/backtest/entry.py` | service (state machine) | event-driven | `src/backtest/simulator.py::_resolve_entry` (355-545) | exact (rewrite) |
| `src/backtest/exits.py` | service | event-driven | `src/backtest/simulator.py::resolve_intrabar` (193-281) | exact (rewrite) |
| `src/backtest/funding.py` | service | transform | `src/backtest/simulator.py::_apply_costs` (628-731) | role-match |
| `src/backtest/ledger.py` | model/service | event-sourced | `src/risk/portfolio.py` (`resolve_absolute_thresholds`, 79-107) + `OpenPosition` (`src/risk/types.py:182-205`) | partial |
| `src/backtest/validator.py` | utility | validation | `src/backtest/experiment.py` (`IncompleteExperimentRecord`, `__post_init__` 90-153) | role-match |
| `src/backtest/simulator.py` (run orchestrator, TradeRecord fields) | orchestrator | request-response | itself, lines 731-940 | exact |
| `src/backtest/experiment.py` (typed fields) | model | CRUD | itself, lines 90-153, 252-318 | exact |
| `src/backtest/report.py` | service | transform | itself, lines 605-625 | exact |
| `src/backtest/costs.py` (funding_convention) | config | transform | itself, `OPTIONAL_COST_KEYS` 48-83 | exact |
| `src/data/case_input.py` | adapter | file-I/O lazy | itself, 131-190, 444+ | exact |
| `src/analytics/live_outcomes.py`, `inputs.py` | service | transform | itself, live_outcomes.py:238, inputs.py:24-64 | exact |
| shared R function (`src/risk/realized_risk.py`) | utility | transform | `src/risk/quantization.py:117`, `src/core/_decimal.py` | role-match |
| `src/core/types.py` `SetupResult.regime` (note: class lives in types.py, not strategy.py) | model | n/a | itself, 230-253 | exact |
| `tests/test_backtest_{entry,exits,funding,ledger,...}.py` | test | golden | `tests/test_backtest_simulator.py` | exact |
| `tests/fixtures/phase14/*` + `DERIVATIONS.md` | fixture | n/a | `tests/fixtures/phase5/DERIVATIONS.md` | exact |
| `scripts/gen_phase14_fixtures.py` | script | batch | `scripts/gen_phase6_fixtures.py` | exact |
| `scripts/smoke_backtest_realdata.py` | script | batch | `scripts/verify_decision_alignment.py` (CLI) | partial |
| `scripts/decision_alignment/protocol.py`, `tests/test_decision_alignment_protocol.py`, `tests/test_kill_gate_docs.py` | gate/test | validation | themselves | exact |

## Pattern Assignments

### Pure-domain header and local validators (all new `src/backtest/*.py`)
**Analog:** `src/backtest/simulator.py` lines 1-92. Copy the purity docstring ("imports NOTHING from Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic"), `from __future__ import annotations`, and the fail-closed validators:
```python
from src.core._decimal import _add, _div, _mul, _sub
...
def _require_utc_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")
```
`_coerce_money` (66-82) rejects float/bool, accepts Decimal/int/str: reuse for every JSON money field. Never use float, including funding time math.
**Trap:** add EVERY new module to the explicit list in `tests/test_domain_no_float.py` (lines ~45-52, the `src/backtest/...` block), else the float guard silently skips it.

### `src/backtest/entry.py` (state machine, event-driven)
**Analog:** `_resolve_entry` in simulator.py (355-545) is the logic being replaced. Limit/tick helpers to reuse (do not re-derive), from `src/execution/placement.py`:
```python
def derive_limit_price(*, entry_min_price, entry_max_price) -> Decimal:
    return _div(_add(entry_min_price, entry_max_price), Decimal("2"))   # :118-135
def entry_limit_rounding(*, candidate_position_side: str) -> str:
    return PRICE_ROUND_DOWN if candidate_position_side == _LONG else PRICE_ROUND_UP   # :190
```
Trade-through (RESEARCH Pattern 1): LONG `minute.low <= _sub(limit, tick)`, SHORT `minute.high >= _add(limit, tick)`; fill price = limit. Outcomes use `entry_kind` vocabulary / counters, NOT new `RejectionReason` members (enum pinned at 20, GLOSSARY gate).

### `src/backtest/exits.py`
**Analog:** `resolve_intrabar` (simulator.py:193-281) and frozen `IntrabarOutcome` (99-112): frozen dataclass with `exit_kind, price, fallback_applied, coverage_note, exit_time_utc`. Extend vocabulary (TP2, END_OF_DATA), keep `fallback_applied` + `coverage_note` flag-never-fabricate. Trigger snapping via `sl_trigger_rounding` / `tp_trigger_rounding` (placement.py:196-210). Stop-first tie-break.

### `src/backtest/funding.py`, cost booking
**Analog:** `_apply_costs` (simulator.py:628-731) and `src/backtest/costs.py`. Presence-driven optional key pattern for `funding_convention` (costs.py:48-83):
```python
OPTIONAL_COST_KEYS: tuple[str, ...] = ("exit_slippage_rate",)
...
keys = (*COST_KEYS, *OPTIONAL_COST_KEYS) if model.exit_slippage_rate is not None else COST_KEYS
payload[key] = _canonical_decimal_text(value) if key in _NUMERIC_HASH_KEYS else value
```
**Trap:** `funding_convention` is a STRING, so add it to `OPTIONAL_COST_KEYS` but NOT `_NUMERIC_HASH_KEYS`; legacy sets must keep their byte-locked seven-key `cost_model_hash` (test_cost_parity.py, test_backtest_binding.py).

### `src/backtest/ledger.py`
**Analog:** `resolve_absolute_thresholds(parameter_set=..., equity=...)` (`src/risk/portfolio.py:79-107`); project resting entries and positions to `OpenPosition(symbol, position_side, open_risk, daily_pnl_contribution)` (`src/risk/types.py:182-205`). Current code computes thresholds once (simulator.py:777); recompute at each UTC day roll. `AccountState` raises for `equity <= 0` (`src/core/types.py:302-307`): catch and fail closed.

### `src/backtest/validator.py`
**Analog:** `ExperimentRecord.__post_init__` (experiment.py:118-153): module-level exception class (`IncompleteExperimentRecord(Exception)` at :42), helpers `_require_non_empty_str`/`_require_64_hex`, plain `raise X(f"{field} ...")`. New: `class TradeRecordInvariantError(Exception)`; checks `entry_time > signal_close`, `exit_time >= entry_time`. Analytics boundary also calls it (inputs.py `normalize_backtest`, raising `AnalyticsInputError` like the duplicate check at inputs.py:34-35).

### `src/backtest/simulator.py` (run orchestrator) and TradeRecord
**Analog:** itself. `run(case_input) -> dict` (731+) parses with `_parse_*`; output dict `trades` = `TradeRecord.to_dict()` (159-169: Decimal -> str, datetime -> isoformat). 26-field frozen `TradeRecord` (121-157).
**Traps:**
- keep `from src.risk.gating import evaluate_risk` as a module global in simulator.py (tests monkeypatch `src.backtest.simulator.evaluate_risk`, and `src.paper.loop.evaluate_risk`).
- tests import private helpers `_make_record`, `_apply_costs`, `resolve_intrabar`, `_parse_candle`, `_parse_account_state` (also `tests/test_phase6_fixture_geometry.py:25`): keep names/signatures or update those tests.
- Every new `TradeRecord` field must be added to: `experiment._DECIMAL_TRADE_FIELDS`/`_DATETIME_TRADE_FIELDS` (experiment.py:252-266), `src/adapters/analytics_files.py` lists (~62-76) and `EVIDENCE_SCHEMA = "analytics-evidence/1"` bump (line 61, regenerate `tests/fixtures/phase10/loaders/evidence_sample.json`), and `tests/phase10_helpers.py` `_TRADE_DEFAULTS` + `_DECIMAL_FIELDS`/`_DATETIME_FIELDS` (`make_trade_record` raises KeyError on unknown overrides, lines 127-140).
- `src/analytics/lifecycle.py:45-46` hard-codes `_BACKTEST_FILLED_KINDS`/`_BACKTEST_UNFILLED_KINDS` (unknown kinds raise): add any new `entry_kind` (e.g. DAILY_STOP_CANCEL, PENDING_AT_DATA_END) there; `excursion.py:319` filters `exit_kind == "TP1"`.

### `src/backtest/experiment.py` typed fields
**Analog:** itself. Frozen dataclass + `__post_init__` raising `IncompleteExperimentRecord`; `_trade_from_dict` (306-318) rebuilds typed fields:
```python
data = dict(t)
for fname in _DECIMAL_TRADE_FIELDS:
    data[fname] = _coerce_trade_decimal(data.get(fname), fname)
```
`ExperimentRecord(**fields)` constructed in `analytics_files.py:506`, tests (test_analytics_files.py:93, test_analytics_report.py:112, test_backtest_report.py:51, test_backtest_experiment.py:555-578).
**CI trap:** never name a committed file `experiment*.json`/`backtest*.json`; never emit JSON keys `parameters`/`parameters_json` alongside `parameter_set_id` (use `parameter_values`) - `.github/workflows/research-gate.yml` tripwire. git subprocess for code version stays outside pure package.

### `src/backtest/report.py`
**Analog:** itself, `build()` 605-625 counts every record:
```python
for trade in trade_records:
    by_symbol[_safe_str(trade.get("symbol"), "UNKNOWN")] += 1
    by_regime[_safe_str(trade.get("regime"), "UNKNOWN")] += 1
```
Change to count only closed filled trades (exclude non-fills, END_OF_DATA separately); plateau section (728-753) becomes "not computed (BKTS-03 pending)"; report digest pin changes (test_backtest_report.py, test_analytics_digest.py).

### `src/data/case_input.py`
**Analog:** itself. `CaseInputData` frozen dataclass with `Row` tuples; `to_case_input(**scenario)` refuses key collisions (`CaseInputError`); `dataset_identity` (208-219) covers all files incl. funding; `build_case_input_data(raw_root, *, symbol, ...)` is single-symbol (444-455); `_group_intrabar` (416-436) is what to replace with a lazy `MinuteSource` impl (Polars allowed only in `src/data/`, `frozen` day-partitioned reads, small LRU). Gap definition via `gap_ranges_for_files`/`GapRange` (`src/data/coverage.py:340-398`). Metadata history reader: only a writer exists (`src/data/metadata.py:41,108`); mirror its SQL style. Exceptions: `CaseInputError`/`CaseInputRangeError`/`CaseInputGapError` (101-109). Mark rows have no `volume`: needs adapter before `_parse_candle`.

### `src/analytics/live_outcomes.py` + shared R denominator
**Analog:** live_outcomes.py:238-241:
```python
realized_risk: Decimal | None = plan.risk_budget
if plan.risk_budget <= _ZERO:
    realized_risk = None
    incomplete.add((plan.signal_id, IncompleteReason.NO_RISK_VALUE))
```
Replace with a call to one pure function (sized_realized_risk x filled/planned, built with `_mul/_div`, placed beside `src/risk/quantization.py:117` `realized_risk = _mul(rounded, risk_per_unit)`); `normalize_backtest` (inputs.py:24-64) and `report._r_multiple` (report.py:412-421), `excursion._r_form` (171-177) all use it. Add new module to the no-float list.

### `SetupResult.regime`
**Analog:** `src/core/types.py:230-253` (frozen dataclass with `reason_code` validated in `__post_init__` via `_require_non_empty`). Add `regime: str | None = field(default=None)` with default so existing constructors keep working; strategy sets it from `_resolve_regime` (strategy.py:98).

### Tests (`tests/test_backtest_*.py`)
**Analog:** `tests/test_backtest_simulator.py` header lines 1-50: golden fixture pair loaded by `_load_input`/`_load_expected` from `tests/fixtures/phaseN/<case>/`, `sha256_hex` over canonical trade dicts; `tests/phase10_helpers.py` `make_candle(s)`, `make_trade_record`. pytest `asyncio_mode="auto"`, `addopts="-q"`. Prefer hand-built `TradePlan` lifecycle goldens over full strategy runs (warm-up cost, Phase 15 geometry change).

### `tests/fixtures/phase14/*` + `DERIVATIONS.md`
**Analog:** `tests/fixtures/phase5/DERIVATIONS.md`: title "Hand arithmetic behind ... golden cases", statement that numbers come from an independent Decimal computation and "never from the output of the code under test", then "Common inputs" table, "Formulas (all Decimal)", per-case sections. Each case dir = `input.json` + `expected.json`. Generator analog `scripts/gen_phase6_fixtures.py` (deterministic, committed, re-run gives byte-identical fixtures; geometry checked by an independent test, `tests/test_phase6_fixture_geometry.py`). Generator must never put 1m data inside the signal bar.

### Protocol/DECISIONS/DOC_STATUS pins
**Analogs and traps (same commit):**
- `scripts/decision_alignment/protocol.py:140-163`: `_header_version`, `check_header` (Frozen on stays `2026-09-19`; Amended on + Supersedes change). Keep heading "Pre-registered thresholds (v1.1.0)" (REQUIRED_PREREGISTRATION_PHRASES ~line 56); `check_backtest_spec` (~310) requires `"v1.1.0" in norm`.
- `tests/test_kill_gate_docs.py:40-49`: `PINNED_PROTOCOL_LINES` (Amended on `2026-09-30`, Supersedes `v1.0.1`), `D043_ROW_PREFIX`, `W3_FREEZE_ROW`, `W2_INDEX_LINE`: rewrite to read version from header.
- `tests/test_decision_alignment_protocol.py`: `"protocol_version": "v1.1.0"` (line ~40), witness tests build stale/no_row via `replace("v1.1.0", ...)` (57-59); `docs/research/holdout_consumed.json` protocol_version.
- New DECISIONS row D052 (contiguous IDs) whose Decision text contains `protocol v2.0.0 frozen` (regex `^\| D\d+ \| .*protocol v{version} frozen`); one DOC_STATUS index line with the version; `bookkeeping.py:470-471` DC-03 keeps D043 row. Do not touch the `### Quantization` block.

### `scripts/smoke_backtest_realdata.py`
**Analog:** `scripts/verify_decision_alignment.py` (argparse CLI shape) and `scripts/gen_phase6_fixtures.py` header docstring style. Not in CI; reports RSS and a deterministic digest.

## Shared Patterns

- **Decimal only:** `from src.core._decimal import _add, _div, _mul, _sub` (prec 28); canonical text via `src.domain.canonical.canonical_decimal_text`, hashes via `sha256_hex`.
- **Fail closed:** TypeError/ValueError for malformed inputs; domain exceptions are plain `Exception` subclasses with f-string messages.
- **Serialization:** Decimal -> `str`, datetime -> `isoformat()` (TradeRecord.to_dict).
- **Do not add `RejectionReason` members** (20 pinned).

## No Analog Found

| File | Reason |
|---|---|
| `src/backtest/series.py` MinuteSource Protocol / lazy LRU reader | No Protocol-based lazy reader exists; use RESEARCH Pattern 2 |
| `src/backtest/ledger.py` event-sourced ledger | No existing ledger; use RESEARCH Pattern 3 plus portfolio helpers above |

## Metadata

**Analog search scope:** src/backtest, src/data, src/analytics, src/core, src/risk, src/execution, tests, scripts
**Pattern extraction date:** 2026-10-04
