# Phase 19: Execution Plan Binding + Pre-Placement Checks - Pattern Map

**Mapped:** 2026-10-19
**Files analyzed:** 22 (new or modified)
**Analogs found:** 21 / 22 (all analog paths are git-tracked source; no `.gsd/` mirror paths)

Scope note: module names for new files are suggestions from 19-RESEARCH.md (Claude's discretion). The analogs are what matter.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/execution/binding.py` (new) | pure verdict module | request-response | `src/execution/gates.py` (`decide_placement`, `PlacementGateVerdict`) | role-match |
| `src/execution/pre_placement.py` (new) | pure verdict module | request-response | `src/execution/gates.py` | role-match |
| `src/execution/lot_split.py` (new) | pure arithmetic util | transform | `src/execution/placement.py` (Decimal quantize) | role-match |
| `src/execution/tp_sizing.py` (new) | pure util (live-only) | transform | `src/execution/placement.py` `size_protectives_to_filled_qty` (FROZEN, copy style only) | role-match |
| `src/execution/protection.py` (new) | async coordinator | event-driven | `src/adapters/binance_userdata_router.py` sinks + `src/execution/fill_monitor.py` | partial |
| `src/execution/emergency_close.py` (new) | async service | request-response (query-before-resend) | `manager._place_entry_no_blind_retry` | role-match |
| `src/adapters/binance_execution_limits.py` (new; loader) | config loader | batch | `src/adapters/binance_limits.py` | exact |
| `config/binance/binance-execution-limits-v1.toml` + README (new) | config | file-I/O | `config/binance/binance-limits-v1.toml` + `README.md` | exact (format only; do NOT edit the original, it is sha256-pinned) |
| `src/execution/manager.py` (modify) | orchestrator | request-response | itself (gate order 0..7) | exact |
| `src/execution/intent_store.py` (modify Protocol) | store interface | CRUD | itself | exact |
| `src/persistence/execution_state.py` (modify) | store | CRUD | itself (`record_protective_intent` ~207-243) | exact |
| `src/db/models.py` (modify, `ExecutionIntentRow` ~513-598) | model | CRUD | itself | exact |
| `src/db/alembic/versions/0005_*.py` (new) | migration | batch | `0004_persistence_integrity.py` | exact |
| `src/adapters/binance_usdm.py` (modify: `get_mark_price`, `place_market_close`, GTD, probe qty) | adapter | request-response | `user_commission_rate` (line 1252) | exact |
| `tests/support/fake_binance_exchange.py` (modify; stateful fake v2) | test double | event-driven | itself (`BinanceSemanticsFakeAdapter`) | exact |
| `tests/support/intent_store_fakes.py` (modify) | test doubles | CRUD | itself (5 classes) | exact |
| `tests/support/execution_limits.py` (new; TEST_ONLY values) | test support | config | `tests/support/limits.py` | exact |
| `tests/test_no_unratified_defaults.py` (modify `GUARDED_NAMES`) | guard test | static scan | itself | exact |
| `tests/test_execution_secret_posture.py` (modify `TARGET_RELPATHS`) | guard test | static scan | itself | exact |
| head-pinned tests (3 places) | test | — | `tests/test_execution_exactly_once_pg.py:205`, `tests/test_pg_fixture_guard.py:184` | exact |
| race tests, one per D-12 branch (new) | test | event-driven | `tests/support/virtual_time.py` users: `tests/test_userdata_supervisor.py` | role-match |
| `docs/GLOSSARY.md` 9.3/9.4 (modify) | doc | — | existing rows | exact |

## DO NOT TOUCH (frozen; backtest imports them)

`size_protectives_to_filled_qty`, `quantize_protective_qty`, `build_sl_leg`, `ProtectiveTemplate` (all `src/execution/placement.py`), `TP1_QUANTITY_FRACTION` and `SIMULATOR_SEMANTICS_VERSION` (`src/backtest/semantics.py:30,34`), `src/backtest/exits.py` (calls them at ~315-327), `config/binance/binance-limits-v1.toml` and `config/binance/README.md` key bullets (sha256-pinned by D072; `len(keys) == 27` at `tests/test_no_unratified_defaults.py:318`), `RejectionReason` (pinned at 20), `OrderRole`, `ExecutionIntentStatus`, `HEADROOM_LIMIT` (`gates.py:42`), `_GATE_KWARG_KEYS` (`manager.py:313-315`; add new live inputs as new required keyword params instead). Add a regression test that calls the new live TP-sizing function and the frozen one with identical inputs and asserts byte-identical legs where they overlap.

## Pattern Assignments

### New limits file + loader with NOT_CONFIGURED keys

**Analog:** `src/adapters/binance_limits.py` (loader) and `tests/support/limits.py` (TEST_ONLY values). Do not extend `CANONICAL_KEYS` (27-key pins).

Structure to copy (lines 43-80 keys map, 115-125 errors, 132-155 validators, 286-320 `_table`/`_read_value`, 392-407 `load_*`):
```python
CANONICAL_KEYS: Mapping[str, tuple[str, ...]] = MappingProxyType({...})
PROVENANCE_SECTION = "provenance"
ALLOWED_SECTIONS: frozenset[str] = frozenset((*CANONICAL_KEYS, PROVENANCE_SECTION))

class LimitsNotRatified(Exception):  # message names keys/sections only, never value or path
    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("binance limits not ratified: " + "; ".join(self.problems))
class LimitsFileMissing(LimitsNotRatified): ...

def _require_positive_int(owner, name, value):
    if type(value) is not int: raise ValueError(f"{owner}.{name} must be an int (not a bool)")
    if value <= 0: raise ValueError(f"{owner}.{name} must be positive")

@dataclass(frozen=True, kw_only=True)   # every field required, keyword-only, NO default
class BinanceLimits: ...

def load_binance_limits(path: Path | str) -> BinanceLimits:
    file = Path(path)
    if not file.is_file():
        raise LimitsFileMissing([...])
    try:
        raw = tomllib.loads(file.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
        raise LimitsNotRatified(["... not valid TOML"]) from None
    return parse_binance_limits(raw)
```
Differences for the new loader: each key accepts a positive int OR the exact string `NOT_CONFIGURED` (maps to `None`; mirror `NULLABLE_KEYS`/`NONE_WORD` handling in `_read_value`, lines 296-320, but the word is `NOT_CONFIGURED` and every key is nullable). Field type `int | None` with no default. Add `require_live_ready()` raising a typed error that names unset keys only. Keep the provenance table and label check (`_check_provenance`, lines 323-350). Suggested keys: `max_unprotected_ms`, `entry_terminal_timeout_ms`, plus min-remaining-validity and price-staleness keys (`_ms`/`_seconds` suffix). Manager takes the loaded object as a required param; unset gives plain-string NO_TRADE `LIMITS_NOT_CONFIGURED` before any adapter call.

**TEST_ONLY values** (copy `tests/support/limits.py` lines 1-50 style): module docstring that values are not ratified, deliberately odd numbers (e.g. 1234, 777), prefix `TEST_ONLY_`, never imported by `src` or `scripts`; includes a TOML writer helper.

**Guard registration** (`tests/test_no_unratified_defaults.py`):
- `GUARDED_NAMES` is built at lines 33-36 as `frozenset(CANONICAL_KEYS keys) | RATE_LIMIT_FIELD_NAMES`; extend with the new key names (lowercase; the scanner lower-cases names, line ~125-127). Add the new dataclass name to `LIMIT_CLASS_NAMES` (lines ~40-50 block).
- The count assertions will break and must be updated deliberately: `assert len(GUARDED_NAMES) == 30` at line 189 and `tests/test_phase18_gate.py:474`. Keep `ALLOW_LIST` empty.
- Scanner flags numeric defaults in Assign, AnnAssign, call keywords, and parameter defaults (`_parameter_defaults`, lines ~70-85), so no `def f(max_unprotected_ms: int = 5000)` anywhere in `src`/`scripts`.

### Fake-exchange test double

**Analog:** `tests/support/fake_binance_exchange.py` (`BinanceSemanticsFakeAdapter`, lines 92-306).

Key patterns to extend (not replace):
```python
@staticmethod
def _bind_real(method_name, kwargs):          # lines 119-122: contract guard against REAL signature
    from src.adapters.binance_usdm import BinanceUsdmAdapter
    inspect.signature(getattr(BinanceUsdmAdapter, method_name)).bind(None, **kwargs)

def _record_call(self, method, kwargs): self.calls.append({"method": method, "kwargs": dict(kwargs)})
def calls_to(self, method): ...

def fill(self, client_id):   # test-side transition: leaves open book, frees id
    record = self.open_orders.pop(client_id); record.status = STATUS_FILLED
    record.had_fill = True; record.updated_at_utc = self.now_utc; self.history[client_id] = record
```
- Errors are SDK-shaped: `raise BadRequestError(error_message=..., status_code=-4116)` (line ~170); new rejections (-4509 flat-position stop, -2022/-2024 reduce-only, -2021) must use the same class and the real int codes.
- `place_entry` returns the real `EntryPlacementResult` (lines ~178-191); new `place_market_close`, `get_mark_price` must return the real result types.
- Order of work: adapter first, then fake (fake binds against the real signature, so a missing real method fails fast).
- New capabilities to add: position book (signed qty per symbol), partial fill (`fill(client_id, quantity=...)` keeping the order open), scripted completion order for stop/cancel races (so each D-12 branch is one deterministic test), MARKET reduce-only close that reduces the position, `-4509` for a closePosition stop while flat, mark price setter, executed quantity on probes, MARKET_LOT_SIZE filters.
- Deadline tests: use `tests/support/virtual_time.py` `VirtualTime` (injected `now()`/`sleep()`, `advance()`, `yield_to_loop`, `SETTLE_ROUNDS`); no `asyncio.sleep`.

### Intent-store test doubles

**Analog:** `tests/support/intent_store_fakes.py`. Five doubles share the Protocol in `src/execution/intent_store.py:100-118`: `InMemoryExecutionIntentStore` (52), `AlwaysWinsIntentStore` (229), `CrashAfter` (314), `BarrierBeforeConsume` (428; `__getattr__` passthrough at 473, so only `consume_and_record_entry_intent` is overridden), `FailingIntentStore` (490).

Every change to the Protocol must be applied to all of them in the same change. Current `record_protective_intent` signature (copy in each double; add `intended_quantity: Decimal | None` for TP1 per D-20, and a `sized_realized_risk` param on `consume_and_record_entry_intent` per D-22):
```python
def record_protective_intent(
    self, *, approval_id: str, role: str, trade_plan_id: str, plan_hash: str,
    algo_client_id: str, symbol: str, side: str, intended_price: Decimal, now_utc: datetime,
) -> bool:
    key = (approval_id, role)
    with self._lock:
        if key in self._rows:
            return False
        self._rows[key] = IntentRecord(..., intended_quantity=None, intent_status=ExecutionIntentStatus.INTENDED, ...)
        return True
```
Wrapper pattern (`CrashAfter.record_protective_intent`, 360-385): delegate to `self._inner...`, then `self._maybe_crash("sl_intent")`; `FailingIntentStore` calls `self._maybe_fail("record_protective_intent", role)` first. Add a crash step for the new fill-driven write-ahead (stop intent written at first fill) following the same step-name convention. Real store counterpart: `src/persistence/execution_state.py:207-243` (inserts NULL quantity today).

### Alembic migration 0005

**Analog:** `src/db/alembic/versions/0004_persistence_integrity.py`.

Conventions (docstring lines 1-31, header 33-40):
```python
"""... Hand-written (never autogenerated). Enum literals COPIED at authoring time; imports no project module.
Conventions: all timestamps TIMESTAMPTZ (UTC), money NUMERIC(38,18), no auto-increment,
nullable only for "transition never happened" and fields that do not apply to a role.
Revision ID: 0005_...
Revises: 0004_persistence_integrity
"""
from __future__ import annotations
import sqlalchemy as sa
from alembic import op
revision: str = "0005_..."
down_revision = "0004_persistence_integrity"
branch_labels = None
depends_on = None
```
Use `op.add_column("execution_intents", sa.Column("sized_realized_risk", sa.Numeric(38, 18), nullable=True))` and `op.create_check_constraint("ck_execution_intents_...", "execution_intents", "sized_realized_risk IS NULL OR (role = 'ENTRY' AND sized_realized_risk >= 0)")` (named CHECKs, as in 0004 lines 48-61). Optional `emergency_close_attempts` table: copy `op.create_table("execution_intents", ...)` column style (String(128) ids, Numeric(38,18), DateTime(timezone=True)), FK ON DELETE RESTRICT, named CHECKs, and the append-only/terminal-status trigger pattern from 0004. Write a real `downgrade()` (the chain must be reversible: `tests/test_persistence_migration_pg.py` upgrade head / downgrade base / upgrade head). Mirror the `ExecutionIntentRow` model change in `src/db/models.py` (~513-598); the enum-parity and CHECK-list tests (`test_enum_check_lists_exactly_the_current_enum_values`) stay green because no enum or role changes.

**Head-pinned tests to make head-agnostic in the same change** (all assert the literal `"0004_persistence_integrity"`): `tests/test_execution_exactly_once_pg.py:205`, `tests/test_pg_fixture_guard.py:184`, and the third head-pinned test the research names (find with `grep -rn 0004_persistence tests`; only two literal hits exist today, so locate the third via the Alembic script directory head check in `tests/test_persistence_migration_pg.py`).

### AST / secret-posture guard registration

**Analog:** `tests/test_execution_secret_posture.py`.

`TARGET_RELPATHS` (lines 35-45) is a tuple of repo-relative paths; a missing target FAILS (`_resolve`, lines 107-110). Add every new module that touches the exchange or logs:
```python
TARGET_RELPATHS: tuple[str, ...] = (
    "src/adapters/binance_usdm.py", "src/ops/health.py", "src/execution/__init__.py",
    "src/execution/enablement.py", "src/execution/fill_monitor.py", "src/execution/gates.py",
    "src/execution/manager.py", "src/execution/order_ids.py", "src/execution/placement.py",
    # add: binding.py, pre_placement.py, lot_split.py, tp_sizing.py, protection.py,
    #      emergency_close.py, and the new limits loader
)
```
Rules enforced: no credential-shaped literal; log calls (`LOG_METHODS`, line ~100) take a literal event name and scalar fields only, never `response`, `payload`, `data`, `body`, `token`.

Purity tests to extend to the new pure modules (analog `tests/test_execution_manager.py:908-957`): `test_execution_core_does_not_import_binance_sdk` (regex on `import binance_sdk`/`from binance_sdk`) and `test_execution_core_has_no_float_in_placement_math` (regex `\bfloat\s*\(`), both iterate a 2-path tuple (`manager.py`, `placement.py`); add the new pure modules to those tuples. Stronger helpers exist in `tests/support/ast_guards.py`: `forbidden_imports(path, prefixes)`, `float_constructor_calls(path)`, `wall_clock_calls(path)` (used by `tests/test_ast_guards.py`, `tests/test_binance_limits.py`); prefer them for the new modules (forbid `sqlalchemy`, `pydantic`, `binance_sdk`, wall clock).

### Pure verdict modules (binding, pre_placement)

**Analog:** `src/execution/gates.py` (`decide_placement`, lines 97-190; `PlacementGateVerdict` lines 53-95).

Copy: keyword-only args, injected `now_utc`, first-failure-wins ordered gates, frozen dataclass verdict validated in `__post_init__`, module docstring "dependency-free: stdlib + Decimal + src/risk only". Difference: `PlacementGateVerdict.__post_init__` rejects any reason code outside `RejectionReason | OK`, so new verdicts need their own dataclass accepting plain strings (D-08 etc.; research F10: add plain strings to GLOSSARY 9.3/9.4, do not grow the enum).
```python
valid_codes = {r.value for r in RejectionReason} | {_OK}
if self.reason_code not in valid_codes:
    raise ValueError(f"PlacementGateVerdict: unknown reason_code {self.reason_code!r}")
```
Reuse `ExecutionOutcome.reason_code` (any non-empty string except `OK` for NO_TRADE). Binding inputs: `Signal` via `plan.signal_id` (symbol, direction), `constraint_snapshot.symbol`, caller args; hash re-derivation needs a public wrapper over `src/core/planner.py` `_plan_hash` (lines 78-87) pinned by a golden-hash test. Invalidation parser/predicate: re-implement the 20-line pair from `src/backtest/entry.py:102-136` (do not import `src.backtest`) with a parity test.

### Adapter additions (`get_mark_price`, `place_market_close`, GTD)

**Analog:** `BinanceUsdmAdapter.user_commission_rate` (`src/adapters/binance_usdm.py:1252-1291`).
```python
response = await self._sdk_call(CallKind.QUERY, self._sdk.rest_api.user_commission_rate, symbol=symbol)
raw = response.data()
if raw is None:
    raise ValueError(f"... empty for {symbol}: refusing to fabricate ...")
if raw.symbol is None or raw.symbol != symbol:
    raise ValueError("... symbol mismatch ...")
```
Copy: SDK import inside the method, `_sdk_call(CallKind.QUERY, ...)` (goes through the rate-limit gate), flag-never-fabricate (every Optional field checked, wrong symbol raises, no fallback), no clock inside the adapter. `MarkPriceResponse` is a oneOf wrapper: unwrap `actual_instance`. `place_market_close`: model on `place_entry` (type=MARKET, `reduce_only=NewOrderReduceOnlyEnum.TRUE`, deterministic `new_client_order_id`) but without `_require_entries_allowed()`, one attempt, never retried. GTD: add `good_till_date` keyword to `place_entry` (must be > now+600s, second precision). The fake binds the real signature, so update the adapter before the fake.

### Manager rewrite (`src/execution/manager.py`)

**Analog:** itself. Keep: fixed gate order 0..7 with replay of the stored outcome before any new gate (zero adapter calls); pre-placement NO_TRADE verdicts must not consume the approval (new refusals go after gate 5 and before position-mode detection and `consume_and_record_entry_intent`); `_place_entry_no_blind_retry` (probe before re-send) as the template for the emergency-close query-before-resend; `RecordingSafeModeController` / journal-first pattern as in `tests/test_execution_manager.py` (`test_rejected_sl_cancels_entry_and_forces_safe_mode`, ~line 960: journal `pre_cancel`/`post_cancel`, `safe_mode_controller.entered_reasons`). `planned_leg_count` stays 4 at entry time. Tests that assert the entry-time stop (CR-05 tests, `test_execution_manager.py` ~960+) encode the OLD flow and must be rewritten with D-10, not patched.

### Protection coordinator (event-driven; weakest analog)

**Analog (partial):** Phase 18 router sinks in `src/adapters/binance_userdata_router.py:436-473` (plain sync callables `fill_sink(RoutedFill)`, `algo_sink(AlgoRoute)`, `status_hint_sink`; a raising sink is journaled and does not stop routing) plus `src/execution/fill_monitor.py` and `src/execution/intent_recovery.py:193-212` (REST query then resolve intent). Sink test doubles: `tests/support/stream_sinks.py`; frames: `tests/support/userdata_frames.py`. The coordinator needs a non-blocking enqueue entry the sinks call, an own asyncio task, `asyncio.gather(stop, cancel, return_exceptions=True)` for D-12, injected `sleep`/clock/adapter/store, and REST as authority (`is_protection_confirmed`, ACTIVE only; `to_fill_event` yields a fill only for TRADE with positive last-filled quantity, `binance_userdata_events.py:1419-1433`).

## Shared Patterns

### Purity and fail-closed
**Source:** `src/execution/gates.py` module docstring, `src/execution/manager.py`.
**Apply to:** every new pure module. stdlib + Decimal + `src.domain`/`src.risk`/`src.execution`; injected `now_utc`; no `float(`; required (non-`None`) live-safety inputs; unknown state means NO_TRADE or SAFE_MODE.

### Flag-never-fabricate adapter reads
**Source:** `src/adapters/binance_usdm.py:1252-1291`. **Apply to:** `get_mark_price`, probe executed quantity, exchangeInfo filter reads for the close splitter.

### Error messages name keys, never values or paths
**Source:** `src/adapters/binance_limits.py:115-125`. **Apply to:** the new limits loader and its `require_live_ready()` error.

### Test doubles bind the real signature
**Source:** `tests/support/fake_binance_exchange.py:119-122`. **Apply to:** every new adapter method fake.

### Virtual time for deadlines
**Source:** `tests/support/virtual_time.py`. **Apply to:** all `max_unprotected_ms` / `entry_terminal_timeout` race tests (one per D-12 branch) and the D-16 split test with fake filters.

### Taxonomy for pre-send refusals (D-21)
**Source:** `src/domain/exchange_errors.py` (`classify`, `retry_eligible`, `safe_mode_eligible`). **Apply to:** manager placement paths; the manager cannot import `binance_errors` (SDK), so inject an exception-to-facts function or a pure pre-send-refusal marker. Refusals raised before sending (`EntriesBlocked`, `SignedCallPolicyMissing`, rate-limit gate) must not yield UNKNOWN intent or SAFE_MODE.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `src/execution/protection.py` (async fill-driven coordinator with deadlines) | coordinator | event-driven | Nothing in `src/` drives protection from a fill today (only `scripts/demo_rehearsal.py` calls `attach_protectives_to_fill`). Use the router-sink and `intent_recovery` patterns above plus RESEARCH Pattern 2 and `19-NOTES.md` branch list. |
| MARKET_LOT_SIZE part builder (`lot_split.py`) | pure util | transform | No existing splitter; follow RESEARCH Pattern 4 and the Decimal style in `placement.py`. |

## Metadata

**Analog search scope:** `src/execution`, `src/adapters`, `src/db/alembic/versions`, `src/persistence`, `tests/support`, guard tests under `tests/`, `config/binance`.
**Tracked-source check:** `git ls-files` confirmed `src/db/alembic/versions/*`, `tests/support/*`, `src/execution/manager.py`, `src/execution/intent_store.py`; no analog lives under `.gsd/`.
**Not re-read:** 19-RESEARCH.md lines 348-630 (validation architecture, race-test map, open questions Q1-Q6) were outside the pages loaded; the planner should read them for the test map.
**Pattern extraction date:** 2026-10-19
