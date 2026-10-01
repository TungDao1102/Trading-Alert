# Phase 12: Fee + Cost Model Correctness - Pattern Map

**Mapped:** 2026-09-30
**Files analyzed:** 18 (new + modified)
**Analogs found:** 17 / 18 (all analogs are git-tracked; `src/risk/*`, `src/adapters/binance_usdm.py` verified via `git ls-files`)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `src/risk/cost_rates.py` (NEW: CostRates, AccountCommission, resolve_cost_rates, per_unit_round_trip_cost, check_cost_guards) | utility / pure core | transform | `src/risk/portfolio.py` (freshness/fail-closed) + `src/backtest/costs.py` (formula) | role-match |
| `src/risk/gating.py` (MOD) | service (pipeline) | request-response | itself (lines 27-122) | exact |
| `src/risk/types.py` (MOD: SizedResult optional fields) | model | transform | itself | exact |
| `src/backtest/costs.py` (MOD) | model / utility | transform | itself | exact |
| `src/backtest/simulator.py` (MOD `_apply_costs`, call site ~803) | service | transform | itself (624-661, 803-821) | exact |
| `src/paper/loop.py` (MOD call site ~504) | service | request-response | simulator call site | exact |
| `src/adapters/binance_usdm.py` (MOD: `user_commission_rate`, `CommissionRates`) | adapter | request-response | `get_position_mode` + `PositionModeResult` | exact |
| `src/domain/registry.py` (MOD: STRATEGY_KEYS, INT_KEYS, unit guard) | config/validator | transform | `constraint_snapshot_ttl_seconds` / `working_type` handling | exact |
| `src/domain/enums.py` (MOD RejectionReason) | model | n/a | itself lines 130-156 | exact |
| `docs/GLOSSARY.md` §9, `docs/DECISIONS.md` (D046/D047), `docs/SOURCES.md`, `docs/integration/BINANCE.md`, RISK_MANAGEMENT/CONFIGURATION | docs | n/a | existing rows/tokens (append only) | role-match |
| `params/*/baseline-v5.toml`, `baseline-no-trade-v3`, `baseline-simple-trend-v3` (NEW) | config | n/a | `params/trend-pullback/baseline-v4.toml` | exact |
| `tests/fixtures/phase4/parameters.json` + `scripts/decision_alignment/params.py` (PA-07 new gate) | test/gate | batch | `check_new_set_facts` (PA-04) | exact |
| `scripts/decision_alignment/bookkeeping.py`, `tests/test_domain_enums.py` (alias removal) | gate/test | batch | themselves | exact |
| `tests/test_cost_per_unit.py`, `test_risk_cost_guards.py`, `test_commission_rates.py`, `test_cost_parity.py`, `test_sl_loss_property.py` (NEW) | test | request-response | `tests/test_risk_portfolio.py`, `tests/test_risk_sizing.py` | role-match |
| `tests/test_adapter_strictness.py` (EXTEND) | test | request-response | itself (fake REST + SDK model instances) | exact |
| `tests/test_backtest_simulator.py` (replace Test 11) | test | transform | itself | exact |
| `tests/fixtures/phase5/6/7/8/9/*`, `scripts/gen_phase6_fixtures.py` | fixture | batch | existing generator | exact |
| Commission TTL check inside `resolve_cost_rates` | (see cost_rates.py) | | `check_portfolio` freshness block | exact |

## Pattern Assignments

### `src/risk/cost_rates.py` (NEW, pure core, transform)

**Purity contract analog:** `src/risk/portfolio.py` lines 14-24 (stdlib + Decimal + `src.core._decimal` only; no SDK, clock, env).
```python
from __future__ import annotations
from datetime import datetime, timedelta
from decimal import Decimal
from src.core._decimal import _add, _mul
from src.domain.enums import RejectionReason
```
Helpers to copy from `portfolio.py` 36-50: `_require_decimal`, `_require_utc_aware`.

**Freshness/TTL fail-closed** (`src/risk/portfolio.py` 296-306): mirror exactly.
```python
_require_utc_aware(constraint_observed_at_utc, "constraint_observed_at_utc")
age = now_utc - constraint_observed_at_utc
if age > ttl or age < timedelta(0):
    return PortfolioVerdict(is_no_trade=True, sized=None,
        reason_code=RejectionReason.STALE_CONSTRAINTS.value, ...)
```
In `resolve_cost_rates` return `UNCERTAIN_ACCOUNT_STATE` instead; a real account rate of 0 is legitimate (floored by `max`), None/stale/future/malformed/symbol mismatch is not.

**Producer** (from RESEARCH Pattern 1): `_add(_mul(entry_price, _add(fee_in, slip_in)), _mul(stop_price, _add(fee_out, exit_slip)))`. Structlog lineage on guard reject: copy `_emit_lineage` in `src/risk/quantization.py` line 192 (local `import structlog` at call site to preserve purity).

### `src/risk/gating.py` (MOD)

**Analog:** itself. Replace lines 69-81 zone-mid `entry_ref` with adverse edge (LONG `entry_max`, SHORT `entry_min`) as sizing entry; keep `quantize(reference_price=zone_mid)` (line 108). Replace the `modeled_costs_per_unit` kwarg (line 37) with required keyword-only `cost_rates`, `min_stop_distance_rate`, `max_cost_to_risk` (same style as `minimum_risk_utilization_after_rounding`, line 38). Order: size_position -> STOP_TOO_TIGHT -> COST_TO_RISK_EXCEEDED -> quantize -> check_portfolio. Short-circuit reject shape to copy (lines 84-96): call `check_portfolio(sized=sized, ..., positions_reconciled=True, constraint_observed_at_utc=constraint_snapshot.metadata_observed_at_utc)`. Existing direction validation at lines 64-68 stays.

### `src/backtest/costs.py` (MOD)

**Analog:** itself. Add `exit_slippage_rate: Decimal | None` field (presence-driven; hash over 7 legacy keys when None, 8 when present, RESEARCH Option B). Hash check pattern lines 133-142 (CR-09) is the model for the canonicalized hash; keep verify-if-supplied. Range check pattern lines 117-128 (`_require_non_negative`, `_require_in_range`): add `[0, 0.01]` for the fee and slippage rates. `_coerce_decimal` (38-58) rejects bool/float: keep. Canonicalization D-15: `format(value.normalize(), "f")` applied before `sha256_hex`, in both `build_cost_model` and `__post_init__`. `modeled_costs_per_unit` (184-204) keeps its name, gains `entry_price`, `stop_price`, delegates to `src/risk/cost_rates.per_unit_round_trip_cost` (risk must not import backtest); fix docstring. Existing exports in `__all__` (207-212) preserved.

### `src/backtest/simulator.py` (MOD, `_apply_costs` 624-661; call site 803-821)

Current buggy line 654: `slippage = _mul(quantity, cost_model.expected_slippage)`. Replace with per-leg `_mul(_mul(price, quantity), rate)` (fees at 651-652 already follow that shape, copy it). SL and EOD exits use `exit_slippage_rate`; TP1 and entry use `expected_slippage`. Call site: drop the `modeled_costs_per_unit(cost_model=..., side=...)` pre-computation (lines 803-806) and pass `cost_rates` + guard rates into `evaluate_risk` (807-821). Guard rates read like line 817-819: `Decimal(str(parameter_set.params["..."]))`. Keep edits minimal (Phase 14 rewrites simulator). Same change at `src/paper/loop.py:504-522`.

### `src/adapters/binance_usdm.py` (MOD)

**Analog:** `PositionModeResult` (line 410-417) and `get_position_mode` (1231-1249).
```python
@dataclass(frozen=True)
class PositionModeResult: ...


async def get_position_mode(self) -> PositionModeResult:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models import (
        GetCurrentPositionModeResponse,
    )

    response = await asyncio.to_thread(self._sdk.rest_api.get_current_position_mode)
    raw: GetCurrentPositionModeResponse = response.data()
    return PositionModeResult(dual_side_position=bool(raw.dual_side_position))
```
New: `CommissionRates(symbol, maker_rate, taker_rate)`; `asyncio.to_thread(self._sdk.rest_api.user_commission_rate, symbol=symbol)`; local model import `UserCommissionRateResponse`; raise `ValueError` on None/non-decimal/negative/>0.01/symbol mismatch (flag-never-fabricate). No clock in the adapter. Error handling precedent for wrapped SDK errors: `query_order` lines 1204-1227 (re-raise unknown).

### `src/domain/registry.py` (MOD)

Add four keys to `STRATEGY_KEYS`, `commission_rate_ttl_seconds` to `INT_KEYS` next to `constraint_snapshot_ttl_seconds` (lines ~109, 277); follow the `working_type` "optional, absent in sets that predate it" precedent (110-115); unit guard >0.01 in `_check_param_types` raising `StrategyKeyOutsideRegistry`. Does not affect `parameter_set_hash` (414-420).

### `src/domain/enums.py` + GLOSSARY + tests (alias removal, D-08/D-09)

Edit order: GLOSSARY §9.1 first, then `RejectionReason` (lines 130-156; remove `RISK_LIMIT`, `CORRELATED_RISK_LIMIT`, `DAILY_STOP`, `QUANTIZATION_REJECT`, `MIN_NOTIONAL_REJECT`; add `STOP_TOO_TIGHT`, `COST_TO_RISK_EXCEEDED`), then `tests/test_domain_enums.py` (~200-224), `scripts/decision_alignment/bookkeeping.py` (ALIASES 26-32, GL-01, GL-03), `tests/test_backtest_simulator.py:207`. Do not touch `INSUFFICIENT_MARGIN`.

### `params/*/baseline-v5.toml` etc. (NEW config)

**Analog:** `params/trend-pullback/baseline-v4.toml` (copy byte-for-byte for non-cost keys; no edits to existing files). Add:
```toml
exit_slippage_rate = 0.0003
min_stop_distance_rate = 0.003
max_cost_to_risk = 0.15
commission_rate_ttl_seconds = 3600
```
Header "Supersedes baseline-v4"; `strategy_version = "v4.0.0"`. Successors: `baseline-no-trade-v3`, `baseline-simple-trend-v3`. Pin hashes in `tests/fixtures/phase4/parameters.json`.

### `scripts/decision_alignment/params.py` (PA-07 new gate)

**Analog:** `check_new_set_facts` (line 184-209): loop over ids, `_set_path`, `_parse`, version check, header `Supersedes` check, append to `problems: list[str]`. Add a new tuple and expected version rather than editing PA-04's constants `EXPECTED_NEW_VERSION`/`NEW_SET_IDS`; keep PA-05 on v4.

### Adapter tests (EXTEND `tests/test_adapter_strictness.py`)

Pattern (lines 1-60): build real SDK model instances (`UserCommissionRateResponse(...)`) and feed via fake REST/response object; cases: ok, missing taker, `"abc"`, negative, `"0.5"`, symbol mismatch.

### New pure-core tests

Analog: `tests/test_risk_portfolio.py` (hand-built kwargs, e.g. lines 941-970) and `tests/test_risk_sizing.py`. Oracle literals must be hard-coded from RESEARCH "Hand-derived oracle cases" (BTC LONG qty 0.035, loss 49.1079400; XRP LONG 5750.4, loss 49.999728) and never call the code under test. Property test uses an explicit Decimal grid (no `hypothesis`) with a mutation check on the old rate-sum formula.

## Shared Patterns

### Decimal-only pinned arithmetic
**Source:** `src/core/_decimal.py` (`_add/_sub/_mul/_div`, prec 28). **Apply to:** all new money math. No `float`.

### Fail closed, never default
**Source:** `src/backtest/costs.py` `build_cost_model` (absent key raises `KeyError`) and `portfolio.py` freshness block. **Apply to:** missing `exit_slippage_rate` in sizing/simulation (refuse), account rate resolution.

### Frozen artifacts are versioned, not edited
**Source:** params files, PA-02/PA-03 hash locks. Old sets stay byte-identical.

### Enum from GLOSSARY first (D016)
**Source:** `docs/GLOSSARY.md` §9 -> `src/domain/enums.py`; `src/risk/types.py` `_REASON_CODES` auto-derives.

### Doc edits append-only
Keep Phase 11 gate tokens (`baseline-v4`, `taker`, `D036`, `Canonical order (D031):`, D044/D045 rows). Next DECISIONS ids: D046, D047.

## Call sites of `evaluate_risk` that must change (kwarg swap)

`src/backtest/simulator.py:803-821`, `src/paper/loop.py:504-522`, `src/execution/manager.py:418` (kwargs from caller; docstring 320-323), `tests/test_risk_portfolio.py:941-970`, `tests/test_execution_manager.py:385-415`, `tests/test_risk_sizing.py`, `test_risk_quantization.py`, `test_risk_parity.py`, `tests/phase10_helpers.py`, fixtures phase5 `input.json`, phase9 `placement_sequences/input.json`.

## No Analog Found

| File | Role | Reason |
|---|---|---|
| Regenerated fixture geometry (`scripts/gen_phase6_fixtures.py` rescale) | fixture | Generator exists but its +0.10/bar step yields ~0.064% stops, so it must be rescaled (RESEARCH Pitfall 1); no example of a guard-clearing geometry exists. Use RESEARCH Pitfall 2 (stop >= ~0.79% of price). |

## Metadata

**Analog search scope:** `src/risk/`, `src/backtest/`, `src/adapters/`, `src/domain/`, `scripts/decision_alignment/`, `tests/`, `params/`
**Files read directly:** gating.py, costs.py, portfolio.py (excerpts), simulator.py (excerpts), binance_usdm.py (excerpts), test_adapter_strictness.py (head), params.py (PA-04); rest via 12-RESEARCH.md verified citations.
**Pattern extraction date:** 2026-09-30
