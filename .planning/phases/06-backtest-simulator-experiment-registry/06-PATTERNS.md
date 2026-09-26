# Phase 6: Backtest Simulator + Experiment Registry - Pattern Map

**Mapped:** 2026-09-26
**Files analyzed:** 11 new files (4 modules in `src/backtest/` + 7 test files + 1 fixture dir)
**Analogs found:** 11 / 11 (strong, recent, role-aligned)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/backtest/__init__.py` | package-init | — | `src/risk/__init__.py` | role-match |
| `src/backtest/simulator.py` | service (event-driven engine) | event-driven (bar-by-bar replay) | `src/core/planner.py` + `src/core/strategy.py` (per-bar call pattern) + `src/risk/gating.py` (pipeline orchestration) | role-match + composition |
| `src/backtest/costs.py` | service (frozen value object + hasher) | transform | `src/domain/canonical.py` + `src/domain/registry.py` (hash-from-payload pattern) + `src/risk/types.py` (frozen Decimal dataclass) | role-match |
| `src/backtest/experiment.py` | service (identity + record assembly) | transform | `src/domain/registry.py` (six-field identity tuple) + `src/domain/ids.py` (content-hash ID) + `src/risk/types.py` (frozen record) | role-match |
| `src/backtest/report.py` | service (stats + bootstrap) | transform | `src/risk/quantization.py:192-220` (lineage emit) + no in-repo bootstrap (stdlib `random`/`statistics` is the pattern) | role-match (sibling) |
| `tests/fixtures/phase6/` | fixture-dir | — | `tests/fixtures/phase5/` | role-exact |
| `tests/test_backtest_intrabar.py` | test (golden) | request-response (over fixture) | `tests/test_candle_close_timing.py` + `tests/fixtures/phase5/<case>/input.json` pattern | role-match |
| `tests/test_backtest_limits.py` | test (golden) | request-response (over fixture) | `tests/test_risk_parity.py` (golden-fixture parity loop) + `tests/test_risk_quantization.py` | role-exact |
| `tests/test_backtest_parity.py` | test (parity) | request-response (over fixture) | `tests/test_risk_parity.py` | role-exact |
| `tests/test_backtest_registry.py` | test (identity gate) | request-response (over fixture) | `tests/test_registry.py` + `tests/test_registry_gate.py` | role-exact |
| `tests/test_backtest_baselines.py` | test (golden) | request-response (over fixture) | `tests/test_risk_parity.py` (degenerate-config pattern) | role-match |
| `tests/test_backtest_report.py` | test (golden) | request-response (over fixture) | `tests/test_fixture_harness.py` (digest pins) | role-exact |
| `tests/test_backtest_no_float.py` | test (AST guard) | static-analysis | `tests/test_domain_no_float.py` | role-exact (file-list extension) |

## Pattern Assignments

### `src/backtest/__init__.py` (package-init)

**Analog:** `src/risk/__init__.py`

**Pattern (from src/risk/__init__.py):** minimal package marker; re-export key public symbols if useful for callers.

```python
# src/risk/__init__.py — package marker; sized/quantize/portfolio/gating
# are imported via their submodule paths, never re-exported here.
```

**Apply to:** `src/backtest/__init__.py` — empty or with a single module docstring; expose `simulator.run`, `costs.build_cost_model`, `experiment.assemble`, `report.build` via explicit `__all__`.

---

### `src/backtest/simulator.py` (service, event-driven)

**Analog:** composition of `src/core/planner.py` (per-bar pure-function call shape) + `src/risk/gating.py` (pipeline orchestration in fixed order).

**Imports pattern** (`src/risk/gating.py:14-24`):
```python
from src.core._decimal import _add, _div, _mul, _sub
from src.core.types import AccountState
from src.domain.enums import Direction
from src.domain.trade_plan import TradePlan
from .portfolio import check_portfolio
from .quantization import quantize
from .sizing import size_position
from .types import ConstraintSnapshot, OpenPosition, PortfolioVerdict
```

**Per-bar pure call pattern** (`src/core/planner.py:294-329`):
```python
try:
    setup_frame = compute_features(
        symbol=signal.symbol,
        interval=signal.source_timeframe,
        candles=setup_candles,
        parameter_set=parameter_set,
    )
except ValueError:
    return PlanResult(is_no_trade=True, trade_plan=None,
                       reason_code=RejectionReason.DATA_STALE.value)
if not setup_frame.features_valid:
    # walk invalid features, pick first reason code
    return PlanResult(is_no_trade=True, trade_plan=None, reason_code=reason)
```

**Pipeline orchestration in fixed order** (`src/risk/gating.py:71-122`):
```python
entry_ref = _div(_add(trade_plan.entry_min_price, trade_plan.entry_max_price),
                Decimal("2"))
sized = size_position(
    trade_plan=trade_plan, account_state=account_state,
    entry_ref=entry_ref, modeled_costs_per_unit=modeled_costs_per_unit,
)
if sized.is_no_trade:
    return check_portfolio(...)   # short-circuit, preserve reason code
allowed_risk = _mul(account_state.equity, account_state.risk_rate)
sl_distance = abs(_sub(entry_ref, trade_plan.stop_loss_price))
risk_per_unit = _add(sl_distance, modeled_costs_per_unit)
quantized = quantize(sized=sized, constraint_snapshot=constraint_snapshot,
                     allowed_risk=allowed_risk, risk_per_unit=risk_per_unit,
                     minimum_risk_utilization_after_rounding=..., reference_price=entry_ref)
return check_portfolio(sized=quantized, ...)
```

**Deterministic iteration pattern** (`src/risk/portfolio.py:217-219`):
```python
sorted_positions = sorted(open_positions, key=lambda p: (p.symbol, p.position_side))
```

**Bar-iteration discipline (Pitfall 5)** — every collection iterated in a backtest is sorted by `(symbol, position_side, …)` before consumption; bootstrap RNG seeded via `random.Random(experiment_seed)`.

**Local structlog import (purity contract)** — `src/risk/quantization.py:207-220`:
```python
def _emit_lineage(*, raw_quantity, rounded_quantity, realized_risk,
                  allowed_risk, reason_code) -> None:
    import structlog   # local import preserves module-level purity
    ...
    structlog.get_logger().info("risk.quantize", ...)
```

**Apply to `simulator.run`:**
- Outer signature: `run(*, strategy_bars, intrabar_1m_map, parameter_set, account_state, constraint_snapshots, cost_model, open_positions, daily_loss_quote, now_utc, ttl, run_type, experiment_seed) -> SimulatorResult`.
- Inner bar loop (Pitfall 5 — sort positions first):
  ```python
  for bar in sorted(strategy_bars, key=lambda b: (b.close_time_utc, b.symbol)):
      closed_setup = closed_through(bar)        # closed-candle slice only
      snapshot = MarketSnapshot(symbol=bar.symbol, setup_candles=closed_setup,
                                context_candles=closed_context, source_timeframe="1h")
      setup = strategy.evaluate(snapshot=snapshot, account_state=acct,
                                strategy_version=parameter_set.strategy_version,
                                parameter_set=parameter_set)
      plan_result = planner.plan(signal=setup.signal, ...)
      # Delegate risk math identically — never re-implement:
      verdict = evaluate_risk(trade_plan=plan_result.trade_plan, ...)
      if verdict.is_no_trade:  # reject is a first-class outcome (D-02)
          trade_records.append(_reject_record(bar, plan_result, verdict))
          continue
      entries.update(bar, plan, verdict)        # touch-vs-fill / partial / expiry
      exits.resolve(bar, intrabar_1m_map[(bar.symbol, bar.close_time_utc)])
      trade_records.append(exits.last_emitted())
  ```
- Iteration order: `bars sorted by (close_time_utc, symbol)`; `positions sorted by (symbol, position_side)` before each pipeline call (Phase-5 D-04 precedent, `src/risk/portfolio.py:217`).
- `intrabar_1m_map` lookups: `dict[(symbol, strategy_bar_close_time_utc), list[Candle]]` — pre-sliced by the data-loading edge (never re-read Parquet inside fill logic).

**Apply to `simulator.resolve_intrabar`** (D-01 SL-first fallback):
```python
def resolve_intrabar(*, strategy_bar, intrabar: list[Candle] | None,
                     stop_loss, take_profits, direction) -> IntrabarOutcome:
    if intrabar is None:
        # Phase-2 D-09 flag-never-fabricate: conservative fallback,
        # log the flag on the trade record, never silent.
        return IntrabarOutcome(
            exit_kind="SL", price=stop_loss, fallback_applied=True,
            coverage_note="1m_intrabar_missing")
    # 1m path: walk the 1m sequence strictly inside (entry_bar.open, exit_bar.close].
    for minute in intrabar:
        if direction == "LONG":
            if minute.low <= stop_loss:
                return IntrabarOutcome(exit_kind="SL", price=stop_loss)
            if minute.high >= take_profits[0]:
                return IntrabarOutcome(exit_kind="TP1", price=take_profits[0])
        else:  # SHORT
            if minute.high >= stop_loss:
                return IntrabarOutcome(exit_kind="SL", price=stop_loss)
            if minute.low <= take_profits[0]:
                return IntrabarOutcome(exit_kind="TP1", price=take_profits[0])
    return IntrabarOutcome(exit_kind="EOD", price=intrabar[-1].close)
```

---

### `src/backtest/costs.py` (service, transform)

**Analog:** composition of `src/domain/canonical.py` (canonical hash) + `src/risk/types.py` (frozen Decimal dataclass) + `src/domain/registry.py:368-374` (hash-from-payload pattern).

**Frozen Decimal dataclass pattern** (`src/risk/types.py:64-94`):
```python
@dataclass(frozen=True)
class ConstraintSnapshot:
    symbol: str
    price_tick_size: Decimal
    quantity_step_size: Decimal
    min_quantity: Decimal
    min_notional: Decimal
    metadata_observed_at_utc: datetime
    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, "symbol")
        for fname in ("price_tick_size", "quantity_step_size",
                      "min_quantity", "min_notional"):
            _require_decimal(getattr(self, fname), fname)
        _require_positive(self.price_tick_size, "price_tick_size")
        _require_positive(self.quantity_step_size, "quantity_step_size")
        _require_positive(self.min_quantity, "min_quantity")
        _require_positive(self.min_notional, "min_notional")
        _require_utc_aware(self.metadata_observed_at_utc, "metadata_observed_at_utc")
```

**Canonical hash payload pattern** (`src/domain/registry.py:368-374`):
```python
hash_payload = {
    "strategy_id": strategy_id,
    "strategy_version": strategy_version,
    "parameter_set_id": parameter_set_id,
    "parameters": normalized_params,
}
parameter_set_hash = sha256_hex(hash_payload)
```

**Apply to `costs.py`:**
- `CostModel` frozen dataclass with Decimal fee/slippage fields + enum fields for `funding_treatment` / `slippage_model` / `spread_fill_assumptions`:
  ```python
  @dataclass(frozen=True)
  class CostModel:
      fee_rate_entry: Decimal
      fee_rate_exit: Decimal
      funding_treatment: str          # enum-validated string
      expected_slippage: Decimal
      slippage_model: str
      spread_fill_assumptions: str
      partial_fill_fraction: Decimal
      cost_model_hash: str            # computed in __post_init__

      def __post_init__(self) -> None:
          _require_decimal(self.fee_rate_entry, "fee_rate_entry")
          # ... non-negative + in-range guards ...
          if self.cost_model_hash == "":
              object.__setattr__(self, "cost_model_hash",
                  sha256_hex({k: getattr(self, k) for k in _COST_KEYS_SORTED}))
  ```
- `build_cost_model(parameter_set: ParameterSet) -> CostModel` reads cost keys (`fee_rate_entry`, `fee_rate_exit`, `expected_slippage` already whitelisted in `src/domain/registry.py:94-97`; Pitfall 7 mandates adding `funding_treatment`, `slippage_model`, `spread_fill_assumptions`, `partial_fill_fraction` to `STRATEGY_KEYS` in a new `baseline-vN.toml`).
- `modeled_costs_per_unit(trade_plan, cost_model, side) -> Decimal` — same formula used by `src/risk/sizing.py:35`; never re-derived inside the simulator body.
- `apply(trade_record, cost_model) -> TradeRecord` — entry fee + exit fee + funding + slippage on realized PnL; output carries per-leg decimal strings for hashing.

---

### `src/backtest/experiment.py` (service, transform)

**Analog:** composition of `src/domain/registry.py` (identity tuple + hash) + `src/domain/ids.py` (content-hash ID) + `src/risk/types.py:103-150` (frozen SizedResult discipline).

**Six-field identity discipline** (`docs/research/RESEARCH_PROTOCOL.md:286-297` verbatim, cited in RESEARCH.md:212-220):
```python
record = {
    "experimentId": sha256_hex(...),
    "strategyVersion": parameter_set.strategy_version,
    "parameterSetHash": parameter_set.parameter_set_hash,
    "parameterSetId": parameter_set.parameter_set_id,    # alongside per D-03
    "dataSnapshotId": dataset_version_hash,
    "codeVersion": engine_commit_sha,
    "costModelHash": cost_model.cost_model_hash,
    "time_range_start_utc": ...,
    "time_range_end_utc": ...,
    "universe_hash": sha256_hex(sorted(universe)),
    "run_type": "BASELINE_NO_TRADE" | "BASELINE_SIMPLE_TREND" | "CANDIDATE",
    "result_summary_json": json.dumps(...),
    "notes": "",
}
```

**Content-hash ID construction** (`src/domain/ids.py:19-46`):
```python
def make_signal_id(*, strategy_id, strategy_version, parameter_set_id,
                   symbol, source_timeframe, source_candle_close_utc,
                   setup_fingerprint) -> str:
    return sha256_hex({
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "parameter_set_id": parameter_set_id,
        "symbol": symbol,
        "source_timeframe": source_timeframe,
        "source_candle_close_utc": source_candle_close_utc,
        "setup_fingerprint": setup_fingerprint,
    })
```

**Frozen record + post-init validation** (`src/risk/types.py:103-150`):
```python
@dataclass(frozen=True)
class SizedResult:
    is_no_trade: bool
    quantity: Decimal | None
    quantity_before_rounding: Decimal
    quantity_after_rounding: Decimal
    quantization_decision: str
    realized_risk: Decimal
    reason_code: str = "OK"
    def __post_init__(self) -> None:
        _require_non_empty(self.quantization_decision, "quantization_decision")
        if self.quantization_decision not in _QUANTIZATION_DECISIONS:
            raise ValueError(...)
        # ... reject-on-mismatch mirrors ...
```

**Apply to `experiment.py`:**
- `ExperimentRecord` frozen dataclass carrying the six-field identity + dataset range + universe + full params + cost assumptions + result summary + notes.
- `assemble(*, parameter_set, cost_model, dataset_version, code_version, time_range, universe, trade_records, run_type, notes) -> ExperimentRecord`:
  - Build `experiment_id = sha256_hex(strategy_version + parameter_set_hash + data_snapshot_id + code_version + cost_model_hash + time_range + universe_hash)`.
  - Compute `result_summary_json` as `canonical_bytes({"trade_count": ..., "expectancy_after_costs_r": ..., ...})`.
  - `__post_init__` raises `IncompleteExperimentRecord` on any missing identity field (D-03 acceptance gate).
- `reproduce(experiment_record, simulator_inputs) -> list[TradeRecord]`:
  - Re-run the simulator with the same six-field tuple; assert trade lists byte-identical via `sha256_hex([canonical_trade(r) for r in trades])`.

---

### `src/backtest/report.py` (service, transform)

**Analog:** composition of `src/risk/quantization.py:192-220` (lineage emit discipline) + no in-repo bootstrap (stdlib `random.Random(seed)` + `statistics` per RESEARCH.md Pattern 4).

**Lineage emission pattern** (`src/risk/quantization.py:207-220`):
```python
import structlog
structlog.get_logger().info("risk.quantize",
    raw_quantity=str(raw_quantity),
    rounded_quantity=str(rounded_quantity),
    realized_risk=str(realized_risk),
    realized_to_allowed_ratio=str(ratio),
    reason_code=reason_code)
```

**Stationary block bootstrap (stdlib-only)** (`docs/research/RESEARCH_PROTOCOL.md:217-224` + RESEARCH.md:343-360):
```python
import random, statistics
rng = random.Random(experiment_seed)        # seed recorded in experiment
def stationary_bootstrap_mean(rs, probable=0.1, resamples=10_000):
    n = len(rs); means = []
    for _ in range(resamples):
        sample, i = [], rng.randrange(n)
        while len(sample) < n:
            sample.append(rs[i]); i = (i + 1) % n
            if rng.random() < probable: i = rng.randrange(n)
        means.append(statistics.fmean(sample))
    quantiles = statistics.quantiles(means, n=40)
    return statistics.fmean(rs), quantiles[0], quantiles[-1]
```

**Apply to `report.py`:**
- `build(experiment_record, trade_records, *, bootstrap_seed, resamples=10_000, probable=0.1) -> UncertaintyReport`:
  - Sections (BACKTEST_SPEC §10):
    1. `trade_count_overall` + per-(symbol, quarter, regime, strategy_version) slices.
    2. `r_distribution`: mean, median, std of `r_multiple = realized_pnl / realized_risk` per trade.
    3. `expectancy_bootstrap`: stationary block bootstrap of mean R + 95% CI (per Politis & Romano 1994).
    4. `drawdown_distribution` under resampling.
    5. `stability`: per-symbol and per-quarter R means.
    6. `parameter_plateau`: if multiple parameter sets supplied, group by region and report.
    7. `baselines`: candidate vs `no-trade` vs `simple-trend` (same engine, degenerate configs).
    8. `dual_universe`: `research_universe` + `live5_universe` slices shown side-by-side.
    9. `intrabar_coverage`: % bars with 1m + count of fallback-applied exits (Pitfall 6).
  - All numerics stay `Decimal` inside the report object; `float` appears only after the report boundary (extend `tests/test_domain_no_float.py` SCANNED_FILES list).
  - `baseline_no_trade(experiment_inputs) -> TradeRecord[]` + `baseline_simple_trend(experiment_inputs) -> TradeRecord[]` — same simulator, parameter-set degenerated to `minimum_rr = 0.01` (or to a single-condition trend filter).

---

### `tests/fixtures/phase6/` (fixture-dir)

**Analog:** `tests/fixtures/phase5/` (case-dir layout).

**Per-case input/output shape** (`tests/fixtures/phase5/happy_path_long/input.json:1-42`):
```json
{
  "trade_plan": {...},
  "account_state": {"equity": "10000.00", "risk_rate": "0.005"},
  "constraint_snapshot": {"symbol": "BTCUSDT", "price_tick_size": "0.10",
                          "quantity_step_size": "0.001",
                          "min_quantity": "0.001", "min_notional": "50",
                          "metadata_observed_at_utc": "..."},
  "parameter_set_id": "baseline-v2",
  "open_positions": [],
  "daily_loss_quote": "0",
  "now_utc": "2026-09-19T00:00:00+00:00",
  "ttl_seconds": "3600",
  "modeled_costs_per_unit": "1.0"
}
```

**Phase-6 case shapes (extended):**
- `tests/fixtures/phase6/intrabar_both_touched/` — strategy candles + 1m intrabar + parameters + costs → expected `TradeRecord[]` with `exit_kind=SL`, `fallback_applied=False`, exact 1m-pinned prices.
- `tests/fixtures/phase6/intrabar_missing_fallback/` — same but no 1m → expected `exit_kind=SL`, `fallback_applied=True`, `coverage_note="1m_intrabar_missing"`.
- `tests/fixtures/phase6/limit_touch_no_fill/` — entry zone touched, no fill inside the bar.
- `tests/fixtures/phase6/limit_partial_fill/` — partial-fill fraction applies.
- `tests/fixtures/phase6/limit_expiry/` — entry never fills before expiry.
- `tests/fixtures/phase6/invalidation_cancels_entry/` — invalidation fires before fill.
- `tests/fixtures/phase6/risk_parity_nonzero_costs/` — same inputs as phase5 `happy_path_long` + nonzero `modeled_costs_per_unit` → byte-identical SizedResult (D-02 + Pitfall 2 distinguishing case).
- `tests/fixtures/phase6/baselines/{no_trade,simple_trend}/` — degenerate parameter-set, expected empty / single-direction trade list.
- `tests/fixtures/phase6/report_slices/` — golden trade list → golden report JSON (slices, R stats, bootstrap CI, plateau, dual-universe).
- `tests/fixtures/phase6/candles.csv` — strategy candles (1H) — extended from `phase4/candles.csv` to cover gap bars + a both-touched bar.

---

### `tests/test_backtest_intrabar.py` (test, golden)

**Analog:** `tests/test_candle_close_timing.py` (single-purpose golden) + `tests/fixtures/phase5/<case>/` loading loop in `tests/test_risk_parity.py:36-49`.

**Loading loop** (`tests/test_risk_parity.py:36-49`):
```python
PHASE5_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase5"
def _load_input(case_dir: Path) -> dict:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))
def _load_expected(case_dir: Path) -> dict:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
```

**Apply to `test_backtest_intrabar.py`:**
- Parametrize over `intrabar_both_touched`, `intrabar_missing_fallback` cases.
- For each case: load `input.json` (strategy candles + 1m map + params + costs), run `simulator.run`, project `trade_records` to a canonical dict, `assert sha256_hex(actual) == sha256_hex(expected)`.
- Assert `fallback_applied` flag appears in the expected JSON for `intrabar_missing_fallback` (Pitfall 6 tripwire).

---

### `tests/test_backtest_limits.py` (test, golden)

**Analog:** `tests/test_risk_quantization.py` (5 case types parallel to D-01 limit kinds) + `tests/test_risk_parity.py:188-198` (parametrize pattern).

**Apply:**
- Parametrize over `limit_touch_no_fill`, `limit_partial_fill`, `limit_expiry`, `invalidation_cancels_entry` cases.
- Each test asserts `TradeRecord.entry_kind` + `TradeRecord.quantity` + `TradeRecord.fallback_flag` matches expected canonical hash.

---

### `tests/test_backtest_parity.py` (test, parity)

**Analog:** `tests/test_risk_parity.py` (full file pattern).

**Two-run identicality + cross-pipeline comparison** (`tests/test_risk_parity.py:138-150`):
```python
def test_risk_pipeline_byte_identical_across_runs() -> None:
    case_dir = PHASE5_FIXTURES_DIR / "happy_path_long"
    case_input = _load_input(case_dir)
    a = _run_pipeline(case_input)
    b = _run_pipeline(case_input)
    assert sha256_hex(_to_parity_dict(a)) == sha256_hex(_to_parity_dict(b))
    assert a.reason_code == b.reason_code
    assert a.is_no_trade == b.is_no_trade
```

**Apply:**
- Test 1 — two simulator runs over the same `risk_parity_nonzero_costs` fixture yield byte-identical trade lists.
- Test 2 — simulator's `modeled_costs_per_unit` matches the value computed by `costs.modeled_costs_per_unit(plan, cost_model, side)` for the same inputs (catches re-implementation drift).
- Test 3 — every reject reason code from `src/risk/types.py` (`MIN_QTY_REJECT`, `NOTIONAL_REJECT`, `UTILIZATION_REJECT`, `QUANTIZATION_REJECT`, `EXCHANGE_CONSTRAINT`, `CLUSTER_CAP_REJECT`, etc.) flows through to a first-class `TradeRecord.outcome_kind` without post-filtering (D-02).

---

### `tests/test_backtest_registry.py` (test, identity)

**Analog:** `tests/test_registry.py` (gate + mutation tests) + `tests/test_registry_gate.py` (run-time gate).

**Identity-bytes tripwire** (`tests/test_registry.py:44-58`):
```python
def test_load_parameter_set_returns_parameter_set_with_64_hex_hash() -> None:
    ps = load_parameter_set("trend-pullback", "baseline-v1")
    assert isinstance(ps, ParameterSet)
    assert len(ps.parameter_set_hash) == 64
    assert all(c in "0123456789abcdef" for c in ps.parameter_set_hash)
```

**Apply:**
- Test 1 — `experiment.assemble(...)` produces an `ExperimentRecord` whose six identity fields are all 64-hex strings and whose union hash is stable across reruns.
- Test 2 — `experiment.reproduce(experiment_record, inputs)` produces byte-identical trade lists (the D-03 reproducibility tripwire).
- Test 3 — `experiment.assemble(...)` with any missing identity field raises `IncompleteExperimentRecord` (acceptance-gate tripwire).
- Test 4 — `cost_model_hash` is stable across reruns; `fee_rate_entry="0.00020"` ≠ `fee_rate_entry="0.0002"` produce different hashes (mirror `tests/test_registry.py:452-499` trailing-precision discipline).
- Test 5 — `verify_experiment(experiment_record, simulator_inputs)` returns `None` when reproducible, raises `ExperimentReproducibilityBroken` when the engine drifts (mirror `tests/test_registry.py:171-203` mutation tripwire).

---

### `tests/test_backtest_baselines.py` (test, golden)

**Analog:** `tests/test_risk_parity.py` degenerate-config pattern.

**Apply:**
- Parametrize over `baselines/no_trade` and `baselines/simple_trend` cases.
- For `no_trade`: parameter set degenerated so `minimum_rr = 100`, entry zone unreachable → empty trade list.
- For `simple_trend`: parameter set with a single-condition trend filter → deterministic single-direction trade list.
- Assert canonical hashes match `expected.json`.

---

### `tests/test_backtest_report.py` (test, golden)

**Analog:** `tests/test_fixture_harness.py:143-166` (digest pin discipline).

**Digest pin** (`tests/test_fixture_harness.py:143-166`):
```python
EXPECTED_SIGNALS_DIGEST = "78abe5a2b4cc98cca7c4411e8caaee2a772a2e4301725f82af9b37f21a4e1a09"
def test_harness_output_matches_expected_files_digest_exactly(...):
    assert (
        sha256_hex({"signals": harness_signals_output})
        == sha256_hex({"signals": phase3_expected_signals["signals"]})
        == EXPECTED_SIGNALS_DIGEST
    )
```

**Apply:**
- Test 1 — `report.build(record, trades)` over `report_slices/input.json` produces a JSON whose `sha256_hex(canonical_bytes(report_dict))` matches the pinned digest in `EXPECTED_REPORT_DIGEST`.
- Test 2 — bootstrap section's CI is reproducible across reruns (seeded RNG).
- Test 3 — `intrabar_coverage` section lists 100% bars-with-1m for `intrabar_both_touched` and 0% for `intrabar_missing_fallback` (Pitfall 6 tripwire).
- Test 4 — `dual_universe` section includes both `research_universe` and `live5_universe` slices (D-04 §10.1 tripwire).

---

### `tests/test_backtest_no_float.py` (test, AST guard)

**Analog:** `tests/test_domain_no_float.py` (file-list extension).

**SCANNED_FILES extension** (`tests/test_domain_no_float.py:17-45`):
```python
SCANNED_FILES = (
    "src/domain/__init__.py",
    # ... existing Phase 3-5 files ...
    # Phase 5 plan 05-01 — pure risk engine (D-05).
    "src/risk/__init__.py",
    "src/risk/types.py",
    "src/risk/sizing.py",
    "src/risk/quantization.py",
    "src/risk/gating.py",
    # Phase 5 plan 05-02 — portfolio gates (D-03/D-04).
    "src/risk/portfolio.py",
)
```

**Walker function** (`tests/test_domain_no_float.py:48-79`):
```python
def _find_float_calls(src: str) -> list[tuple[int, str]]:
    found: dict[tuple[int, str], None] = {}
    lines = src.splitlines()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "float":
                found[(node.lineno, lines[node.lineno - 1].strip())] = None
            elif (isinstance(func, ast.Name) and func.id == "Decimal"
                  and node.args and isinstance(node.args[0], ast.Constant)
                  and isinstance(node.args[0].value, float)):
                found[(node.lineno, lines[node.lineno - 1].strip())] = None
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, float):
                found[(node.lineno, lines[node.lineno - 1].strip())] = None
        elif isinstance(node, ast.Attribute):
            if node.attr in {"float16", "float32", "float64", "floating"}:
                found[(node.lineno, lines[node.lineno - 1].strip())] = None
    return sorted(found)
```

**Apply to `test_backtest_no_float.py`:**
- Add the new scan list to `tests/test_domain_no_float.py:SCANNED_FILES`:
  ```python
  # Phase 6 plan 06-01 — pure backtest engine (D-05).
  "src/backtest/__init__.py",
  "src/backtest/simulator.py",
  "src/backtest/costs.py",
  "src/backtest/experiment.py",
  "src/backtest/report.py",
  ```
- Plus a sibling `tests/test_backtest_no_float.py` (or extend the existing one) that calls the same `_find_float_calls` walker over the new files — keeps the WAVE-0 failures localized.
- Keep the `Decimal(<float literal>)` walker entry — Phase 6 has fresh temptation to pass `Decimal(0.005)` from a `parameter_set.params[...]` value that may still be a `float` after a loader regression.

## Shared Patterns

### Pattern 1: Pure-Python purity contract (D-05)
**Source:** `src/risk/sizing.py:13-15` + `src/risk/quantization.py:13-17` (module docstrings).
**Apply to:** Every `src/backtest/*.py`.
**Mechanics:**
- Module docstring explicitly enumerates the purity boundary: stdlib + `Decimal` + `src/core/_decimal.py` only.
- No `import polars` / `import pandas` / `import numpy` / `import scipy` at module top — Polars/DuckDB live in the loading edge, not in `simulator.py`.
- `structlog` imports are local to the lineage emit call site (mirror `src/risk/quantization.py:207`).
- `_require_decimal` / `_require_utc_aware` / `_require_non_empty` / `_require_positive` helpers copied from `src/core/types.py:32-58` and `src/risk/types.py:32-58` into a `src/backtest/_validators.py` module to avoid cross-package leakage of implementation detail (or just `from src.core.types import _require_decimal, _require_utc_aware` if the team prefers).

### Pattern 2: Fail-closed validation in `__post_init__`
**Source:** `src/risk/types.py:81-94, 124-150` + `src/core/types.py:87-111`.
**Apply to:** Every frozen dataclass in `costs.py`, `experiment.py`, `report.py`.
**Mechanics:** All money/qty/price fields guarded by `_require_decimal` + `_require_non_negative`; all datetime fields guarded by `_require_utc_aware`; enum-typed fields validated against the closed vocabulary; one-way-strict (e.g. reject `bool` even where `int` is accepted).

### Pattern 3: Determinism via sorted iteration + seeded RNG
**Source:** `src/risk/portfolio.py:217-219` (sorted positions) + RESEARCH.md:343-360 (`random.Random(experiment_seed)` for bootstrap).
**Apply to:** Every collection iterated inside `simulator.py` and `report.py`.
**Mechanics:**
- `bars = sorted(strategy_bars, key=lambda b: (b.close_time_utc, b.symbol))`.
- `positions = sorted(positions, key=lambda p: (p.symbol, p.position_side))` before every pipeline call.
- `rng = random.Random(experiment_seed)` constructed exactly once per `report.build(...)` call; resample indices drawn from it.

### Pattern 4: Risk math delegation, never re-implementation
**Source:** `src/risk/gating.py:71-122` (pipeline orchestration) + `tests/test_risk_parity.py:188-198` (parity tripwire).
**Apply to:** Every sizing + quantization + portfolio decision in `simulator.py`.
**Mechanics:**
- `from src.risk.gating import evaluate_risk` and call it directly with the same kwargs paper/live would pass.
- The simulator owns the bar loop and entry/exit state machines; the risk pipeline owns the math. No `Decimal` arithmetic for `sl_distance * quantity` inside `simulator.py` other than delegations.
- Parity fixture (`tests/fixtures/phase6/risk_parity_nonzero_costs/`) pins byte-identity with `tests/fixtures/phase5/happy_path_long/` for the distinguishing nonzero-cost case.

### Pattern 5: Content-hash identity (six-field tuple)
**Source:** `src/domain/registry.py:368-374` + `src/domain/ids.py:19-46` + RESEARCH.md:212-220.
**Apply to:** `experiment.assemble()`.
**Mechanics:**
- `experiment_id = sha256_hex({strategy_version, parameter_set_hash, data_snapshot_id, code_version, cost_model_hash, time_range, universe_hash})`.
- Every identity field is itself a 64-hex SHA256; missing field raises typed exception at `__post_init__`.
- `parameterSetId` lives alongside `parameterSetHash` (not inside the hash payload) per `docs/configuration/CONFIGURATION.md:100-113`.

### Pattern 6: Golden-fixture parity loop
**Source:** `tests/test_risk_parity.py:32-49` + `tests/fixtures/phase5/<case>/{input,expected}.json`.
**Apply to:** `test_backtest_intrabar.py`, `test_backtest_limits.py`, `test_backtest_baselines.py`, `test_backtest_report.py`.
**Mechanics:**
- One case directory per behavior under `tests/fixtures/phase6/<behavior>/`.
- `input.json` = full deterministic inputs (strategy candles + 1m map + parameters + costs + constraint snapshot + account state).
- `expected.json` = canonical-JSON-safe dict of expected outputs (trade records, report sections).
- Test asserts `sha256_hex(canonical_bytes(actual)) == sha256_hex(canonical_bytes(expected))`.

### Pattern 7: No-float AST guard extension
**Source:** `tests/test_domain_no_float.py:17-45, 48-79`.
**Apply to:** `tests/test_backtest_no_float.py` (sibling) or extend `SCANNED_FILES`.
**Mechanics:** Same walker; new file list appended. Tripwire on `float(`, `Decimal(<float literal>)`, `np.float*`, `0.5` literal, `numpy.*` floating.

## No Analog Found

Files with no close existing match (planner may rely on RESEARCH.md patterns instead):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | — | — | Every Phase-6 file has a strong role-aligned analog. The event-driven bar loop is composed from existing planner/strategy/gating patterns; the six-field identity is composed from existing registry/canonical/ids patterns; the report module's bootstrap is stdlib-only per RESEARCH.md Pattern 4 (no in-repo bootstrap exists, but the stdlib path is documented and externally cited). |

## Metadata

**Analog search scope:** `src/core/`, `src/domain/`, `src/risk/`, `src/data/`, `src/adapters/`, `tests/`, `tests/fixtures/phase3..5/`, `docs/backtest/`, `docs/research/`, `docs/configuration/`, `docs/data/`, `docs/trading/`, `params/`.
**Files scanned:** 31 source files + 33 test files + 6 docs + 6 parameter TOMLs + 14 fixture case directories.
**Pattern extraction date:** 2026-09-26
**Confidence:** HIGH — every analog is git-tracked (`git ls-files` confirmed via the writeable-source gate), role-aligned, and recently-modified (Phases 3–5, all dated 2026-09-24/25). The Phase-6 composition is faithful to the existing project rhythm: frozen dataclasses, fail-closed validation, hash-identity, decimal-only, sorted iteration, parity fixtures, AST guards.
