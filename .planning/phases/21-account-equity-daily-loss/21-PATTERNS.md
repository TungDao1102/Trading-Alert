# Phase 21: Account Equity + Daily Loss from Binance - Pattern Map

**Mapped:** 2026-10-22
**Files analyzed:** 13 (new or modified)
**Analogs found:** 13 / 13 (all git-tracked `src/`, `tests/`, `config/` paths; none is a gitignored mirror)

Module placement follows the layout proposed in 21-RESEARCH (Claude's discretion). Excerpts below are from files read in this pass; line numbers are as read.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `src/risk/live_equity.py` (new) | utility (pure resolver) | transform | `src/risk/live_commission.py` | exact |
| `src/risk/daily_loss.py` (new) | utility (pure fold + latch rules) | transform | `src/backtest/ledger.py` (`daily_loss_quote`, `_roll`, `_resolve_thresholds`) + `src/risk/portfolio.py::derive_daily_state` | role-match |
| `src/adapters/binance_usdm.py` (modify: `account_balance_snapshot`, `account_config_snapshot`, `user_trades_since`) | adapter | request-response (signed GET) | `snapshot_positions` (same file, lines 930-955) | exact |
| `src/persistence/day_risk.py` (new) | store | CRUD, idempotent insert | `src/persistence/lot_filters.py` | role-match |
| `src/persistence/risk_reservations.py` (new) + hook in `src/persistence/approvals.py::_decide` | store | CRUD in one transaction | `src/persistence/execution_state.py` (`with_for_update`, lines ~385-410) and `approvals.py` lines 219-260 | role-match |
| `src/db/alembic/versions/0010_day_risk_and_reservations.py` (new) | migration | batch DDL | `0009_validated_lot_filters.py` | exact |
| `src/db/models.py` (modify: ORM rows, `approvals.reserved_risk`) | model | CRUD | `ValidatedLotFiltersRow`, `ApprovalRow` (same file) | exact |
| `src/execution/daily_stop.py` (new) | service (orchestrator) | event-driven | `expire_pending_entry` in `src/execution/manager.py` (line 2120) | role-match |
| `src/execution/manager.py` (modify: add `"daily_stop"` to `_EXPIRY_TRIGGERS`, line ~1952) | service | request-response | itself | exact |
| `src/ops/alerts.py` (modify: producer, `OPS05_MATRIX` rows 850-865) | service | pub-sub (alert sink) | `emit_daily_state_alert` (line 890) | exact |
| `src/execution/constraint_snapshot.py` (call site: fill `equity_used`) | model/service | transform | `build_plan_constraint_snapshot` (lines 222-264) | exact |
| `config/execution/execution-limits-v1.toml`, `src/execution/execution_limits.py`, `config/execution/README.md`, `tests/support/execution_limits.py` (add 15th key `account.max_equity_age_ms`) | config | config | the existing 14 keys | exact |
| `tests/test_live_equity.py`, `tests/test_daily_loss.py`, `tests/test_*_pg.py` (reservation race, day state), `scripts/gen_phase21_fixtures.py`, `tests/fixtures/phase21/` | test | mixed | `tests/test_lot_filters_pg.py`, `scripts/gen_phase14_fixtures.py` | role-match |

## Pattern Assignments

### `src/risk/live_equity.py` (pure resolver, transform)

**Analog:** `src/risk/live_commission.py` (read whole, 173 lines). Copy its structure one for one: module docstring with fail-closed rule and "reads no clock", `_require_utc_aware`, a frozen reading dataclass validated in `__post_init__`, a result dataclass whose `__post_init__` couples `reason_code` to presence of the value, and a resolver with keyword-only args.

**Imports and constants** (lines 37-49):
```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from src.domain.enums import RejectionReason

_OK = "OK"
_REASON_CODES = frozenset({r.value for r in RejectionReason})
_UNCERTAIN = RejectionReason.UNCERTAIN_ACCOUNT_STATE.value
```

**Result-coupling pattern** (lines 101-111):
```python
def __post_init__(self) -> None:
    if self.rates is None:
        if self.reason_code == _OK or self.reason_code not in _REASON_CODES:
            raise ValueError(...)
    elif self.reason_code != _OK:
        raise ValueError(...)
```

**Freshness and programming-error split** (lines 140-150):
```python
_require_utc_aware(now_utc, "now_utc")
if ttl <= timedelta(0):
    raise ValueError(f"ttl must be positive, got {ttl}")
if account_commission is None:
    return LiveCostRatesResult(rates=None, reason_code=_UNCERTAIN)
age = now_utc - account_commission.observed_at_utc
if age > ttl or age < timedelta(0):
    return LiveCostRatesResult(rates=None, reason_code=_UNCERTAIN)
```
Apply: output is `AccountState(equity=..., risk_rate=...)` from `src/core/types.py`. Extra checks from RESEARCH Pattern 1 (identity `totalMarginBalance == totalWalletBalance + totalUnrealizedProfit`, `<= 0`, `multiAssetsMargin`). Purity: stdlib, Decimal, `src.domain`, `src.core.types` only. No new `RejectionReason` member (pinned at 21).

---

### `src/adapters/binance_usdm.py` new read methods (adapter, signed GET)

**Analog:** `snapshot_positions`, lines 930-955. Same shape for `account_balance_snapshot` (SDK `rest_api.account_information_v3`), `account_config_snapshot`, `user_trades_since` (`account_trade_list`):
```python
response = await self._sdk_call(
    CallKind.QUERY,
    self._sdk.rest_api.position_information_v3,
    symbol=symbol,
)
raw = response.data()
rows: Sequence[PositionInformationV3Response] = raw if isinstance(raw, list) else [raw]
...
snapshot = _row_to_position_snapshot(item)   # private row->frozen dataclass mapper
```
Rules: every call goes through `_sdk_call` (line 702) so `RestRateLimitGate` applies; SDK types never leave the adapter, so return a project frozen dataclass built by a private `_row_to_*` mapper; all SDK fields are `Optional[StrictStr]`, so None or unparsable maps to "no reading" (never zero); parse with `Decimal(str)`; the adapter takes no clock (caller stamps `observed_at_utc` before the request). A `RestGateRefusal` propagates and the caller treats it as UNCERTAIN, never retries. Do not carry `accountAlias`.

---

### `src/risk/daily_loss.py` (pure fold, transform)

**Analogs:** `src/backtest/ledger.py` and `src/risk/portfolio.py`.

**Loss definition** (ledger.py 201-204): `loss = _sub(_ZERO, ledger.day_pnl); return loss if loss > _ZERO else _ZERO`.

**UTC-day rule** (119-121): `at_utc.replace(hour=0, minute=0, second=0, microsecond=0)`; midnight belongs to the new day. `_require_utc` at 112-116.

**Thresholds against day-start base** (124-137): `resolve_absolute_thresholds(parameter_set=params, equity=equity)` when equity > 0, else all `RATE_THRESHOLD_KEYS` resolve to 0 (fail closed). Live passes the persisted `equity_at_day_start`, never current equity.

**State derivation** (portfolio.py 144-166): `derive_daily_state(daily_loss_quote=..., parameter_set=...)`; inclusive boundaries; None loss returns NORMAL, so the caller's own gate must reject unknown loss. `cancel_resting_required(ledger)` (ledger 215-217) is the DAILY_STOP semantic to mirror.

Add: sticky latch (once `stop_latched_at_utc` is set, state is DAILY_STOP until the next UTC day), non-USDT commission asset makes loss unknown (D-11), take the larger loss when stream and REST disagree (Pitfall 4).

---

### `src/persistence/day_risk.py` (store, idempotent CRUD)

**Analog:** `src/persistence/lot_filters.py` (lines 1-110 read).

**Unit-of-work join pattern** (62-69):
```python
@contextmanager
def _unit(self, tx: Session | None) -> Iterator[Session]:
    if tx is not None:
        yield tx
        return
    with self._db.transaction() as session:
        yield session
```
**Imports** (21-32): `sqlalchemy.select`, `sqlalchemy.dialects.postgresql.insert as pg_insert`, `Session`, row classes from `src.db.models`, `OperationalDatabase` from `src.persistence.uow`. `_require_utc_aware` helper at 46-53.

**Idempotent insert**: `pg_insert(Row).values(**values).on_conflict_do_nothing(index_elements=[...])` (same idiom at `approvals.py:153`, `execution_state.py:241`). Components keyed by `order_id:trade_id` (and funding `symbol:time_ms`). Decimals in and out via `NUMERIC(38,18)`; no delete method; unreachable DB raises `StoreUnavailable` from the unit of work, no retry loop.

---

### `src/persistence/risk_reservations.py` and the `_decide` hook (atomic reservation)

**Analog 1:** `src/persistence/approvals.py::_decide` lines 219-260 (the transaction to extend). Key facts: conditional UPDATE inside `session.begin_nested()`; `IntegrityError` mapped to `ApprovalAlreadyDecided`; `RowConflict` for anomalies. A reservation refusal must propagate OUT of the outer `db.transaction()` (not inside `begin_nested`) so the decision rolls back too.

**Analog 2:** `src/persistence/execution_state.py` ~385-410, row lock then conditional state change:
```python
with self._db.transaction() as session:
    current = session.execute(
        select(ExecutionIntentRow.intent_status, ...)
        .where(ExecutionIntentRow.approval_id == approval_id, ExecutionIntentRow.role == role)
        .with_for_update()
    ).one_or_none()
    if current is None:
        raise IntentStateConflict(...)
    if <identical repeat>: return   # idempotent no-op
    if current.intent_status != required.value:
        raise IntentStateConflict(...)
```
Apply: lock the day-risk row `FOR UPDATE`, read reservations (`RESERVED/PLACED/OPEN`), call pure `check_portfolio`, insert reservation (`trade_plan_id` UNIQUE) in the same transaction. Do not change the `SaveAtomic` signature (mypy conformance block); compose a callable. Reserve `SizedResult.realized_risk` (Pitfall 9). One row per plan for its life; exclude the candidate's own row at placement (Pitfall 2). Flip to PLACED inside `consume_and_record_entry_intent`'s transaction. Source of reserved amount: nullable `approvals.reserved_risk NUMERIC(38,18)` written by `insert_pending` like `approved_quantity` (`quantize_for_storage`, `PrecisionError` on more than 18 fractional digits; NULL means refuse to approve).

---

### `src/db/alembic/versions/0010_day_risk_and_reservations.py` (migration)

**Analog:** `0009_validated_lot_filters.py` (lines 1-90 read). Hand-written, imports no project module, docstring lists every column and CHECK, header block:
```python
revision: str = "0009_validated_lot_filters"
down_revision = "0008_pending_protective_actions"
branch_labels = None
depends_on = None
```
New: `revision = "0010_day_risk_and_reservations"`, `down_revision = "0009_validated_lot_filters"`. Columns: `sa.Numeric(38, 18)`, `sa.DateTime(timezone=True)`, named `PrimaryKeyConstraint("...", name="pk_...")`, named `CheckConstraint(..., name="ck_<table>_<what>")`, a real `downgrade()`. Also update the head pin at `tests/test_persistence_migration_pg.py:101` and `:470`, and ORM-parity tests.

---

### `src/execution/daily_stop.py` and `_EXPIRY_TRIGGERS` (orchestrator)

**Analog:** `src/execution/manager.py::expire_pending_entry` (line 2120) with signature `(*, plan_hash, symbol, adapter, journal, now_utc, trigger_reason, spill=None) -> CancelVerdict`. Add `"daily_stop"` to `_EXPIRY_TRIGGERS` (frozenset at ~1952-1965, with a comment line citing the decision, like the existing entries); an unknown trigger raises `ValueError`. Order: latch, cancel entries, then alert (WR-C8), release unplaced reservations. Never call `cancel_algo_order` or the protective-leg cancels. A `FILLED_OR_PARTIAL` verdict is left to the protection coordinator.

---

### `src/ops/alerts.py` (producers)

**Analog:** `emit_daily_state_alert(sink, *, state, subject, now_utc)` (line 890): `sink.alert(event=..., subject=subject, reason=state.value, now_utc=now_utc)`. `ALERT_EVENTS` already has `DAILY_STOP` (CRITICAL) and `DAILY_LOSS_WARNING` (WARNING) at lines 112-113. `OPS05_MATRIX` rows at ~850-865 carry `producer = _PRODUCER_PHASE21`. Call `sink.alert(...)` directly from the new producer, or update `tests/test_alerts.py` (~729-745 AST scan) and `tests/test_alerts_ops05_matrix.py:174,198` in the same change. `subject` matches `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`, `reason` is an upper-case code; no amounts in alert fields.

---

### `src/execution/constraint_snapshot.py` (equity into snapshot)

**Analog:** `build_plan_constraint_snapshot` lines 222-264 and `snapshot_is_valid_for_live` lines 394-416. Pass the resolved equity as `equity_used` (must be `> 0`). D-18 test: with stubbed `margin_type` (non-empty, at most 16 chars, not `"UNKNOWN"`), `leverage >= 1` and the filter extras plus `max_quantity`, assert `snapshot_is_valid_for_live` is True; with `equity_used=None` assert False. Stub values are test data only.

---

### Execution-limits 15th key (config)

**Analog:** the existing 14 keys. Touch together: `config/execution/execution-limits-v1.toml` (`[account] max_equity_age_ms = "NOT_CONFIGURED"` plus `[provenance.*]`), `src/execution/execution_limits.py` (`EXECUTION_LIMIT_KEYS`, `EXECUTION_LIMIT_FIELDS`, dataclass field), `config/execution/README.md`, `tests/support/execution_limits.py`, `tests/test_execution_limits.py:96` (dotted-name order pin), `tests/test_phase20_gate.py` (`PHASE20_LIMIT_KEYS`), `tests/test_no_unratified_defaults.py`. Do not edit `params/**/*.toml`.

---

### Tests and fixtures

**Analogs:** `tests/test_lot_filters_pg.py` (PG store test; `*_pg.py` needs `TEST_DATABASE_URL`, `pg_db` fixture), shared fakes in `tests/support/` (`stream_sinks.py`, `userdata_frames.py`, `reconcile_doubles.py`, `virtual_time.py`). Fixtures are generated by `scripts/gen_phase21_fixtures.py` (pattern of `scripts/gen_phase14_fixtures.py`) from the Phase 19 Demo capture; never typed by hand; drop `accountAlias`. Required cases: two-connection reservation race (second approval blocks then fails cap), staleness boundary (age exactly ttl passes, ttl+1 and negative fail), threshold base does not move when intraday equity rises, SL-triggered close fill reaches the loss feed (recorded triggered-bracket frames), no `cancel_algo_order` call at DAILY_STOP, `test_domain_no_float` still green.

## Shared Patterns

### Fail closed to UNCERTAIN_ACCOUNT_STATE
**Source:** `src/risk/live_commission.py` 140-150. **Apply to:** `live_equity.py`, `daily_loss.py` (unknown day state with open exposure), snapshot equity.
Staleness is always `age > ttl or age < timedelta(0)`; exactly ttl passes.

### Injected clock, UTC validation
**Source:** `_require_utc_aware` (live_commission.py 52-57) / `_require_utc` (ledger.py 112-116). **Apply to:** every new pure module and store (stores use the lot_filters.py 46-53 variant). No wall clock reads in pure modules (`tests/support/ast_guards.py`).

### Unit of work and idempotent writes
**Source:** `lot_filters.py` 62-69 and `on_conflict_do_nothing` idiom. **Apply to:** `day_risk.py`, `risk_reservations.py`.

### Read-only REST through the gate
**Source:** `snapshot_positions` via `_sdk_call(CallKind.QUERY, ...)`. **Apply to:** all new adapter reads; `RestGateRefusal` means "no reading".

### Decimal-only
All amounts parsed from exchange text with `Decimal`; no `float(` constructor (`tests/test_domain_no_float.py`).

### Demo labelling
Comments, docs and tests label Binance facts "demo-observed, not mainnet" (D-22). Do not flip `LIVE_NET_PNL_SEMANTICS_VERIFIED` (`src/analytics/live_outcomes.py:65`).

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| Live `OpenPosition` producer (filled + resting + reserved rows) | service | transform | `OpenPosition(` is built only in `backtest/ledger.py`, `paper/loop.py`, `paper/replay_inputs.py`. Use `open_positions_for_risk(ledger)` (ledger.py 321) as the shape reference and the paper `ShadowReservations` (`src/paper/shadow_ledger.py` 596-720) for reserve/release/rebuild semantics. |
| Funding component feed | adapter | event-driven | No FUNDING_FEE frame was ever recorded on Demo and `/fapi/v1/income` returned 0 rows (O-2 owner-open). Use RESEARCH (d), label "source unverified on Demo". |

## Metadata

**Analog search scope:** `src/risk`, `src/backtest`, `src/persistence`, `src/db/alembic/versions`, `src/adapters/binance_usdm.py`, `src/execution`, `src/ops/alerts.py`, `tests/`, `tests/support/`.
**Files read this pass:** live_commission.py, approvals.py (1-60, 215-265), binance_usdm.py (925-985), lot_filters.py (1-110), 0009 migration (1-90), ledger.py (112-225), plus targeted greps of execution_state.py, manager.py, alerts.py, portfolio.py.
**Not read (RESEARCH lines 377-557 were not loaded; check them for the Code Examples, Open Questions and Assumptions Log before planning).**
**Pattern extraction date:** 2026-10-22
