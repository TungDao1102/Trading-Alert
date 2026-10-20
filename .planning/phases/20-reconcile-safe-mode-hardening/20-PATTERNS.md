# Phase 20: Reconcile + SAFE_MODE Hardening + Alerts - Pattern Map

**Mapped:** 2026-10-20
**Files analyzed:** 33 production files (16 create, 17 modify) plus the test and doc sets
**Analogs found:** 31 / 33 (all analog paths are git-tracked; `git ls-files` checked for the modified files and the `src/` trees named below)

Line numbers are from the files as read this session. The RESEARCH file (20-RESEARCH.md, "Recommended Project Structure") is the source of the file list.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `src/reconcile/compare.py` (modify) | pure utility | transform | itself (v1) | exact |
| `src/reconcile/classify.py` (new) | pure utility | transform | `src/reconcile/compare.py` (kind vocabulary + frozen dataclasses) | role-match |
| `src/reconcile/loop.py` (new) | orchestrator service | request-response (step-driven tick) | `src/execution/protection.py` (`ProtectionCoordinator.step`) | role-match |
| `src/reconcile/startup.py` (new) | orchestrator service | batch | `src/execution/intent_recovery.py` (`resolve_unresolved_intents`) | role-match |
| `src/reconcile/feed_freshness.py` (new) | pure utility | transform | `src/reconcile/compare.py` (pure, injected clock) | partial |
| `src/reconcile/safe_mode.py` (modify) | state machine | event-driven | itself | exact |
| `src/reconcile/sweeper.py` (modify) | service | request-response | itself | exact |
| `src/ops/spill.py` (new) | utility | file-I/O | `src/data/store.py` (`replace_with_retry`, `atomic_write_parquet`) | role-match |
| `src/ops/risk_first.py` (new) | utility | request-response | none in repo for act-first; design in RESEARCH "Code Examples" | no analog |
| `src/ops/alerts.py` (new) | service | event-driven | `src/paper/shadow.py` (`_send_bounded`, `send_shadow_alert`) | role-match |
| `src/execution/pending_actions.py` (new) | model + Protocol | CRUD | `src/persistence/system_state.py` (`SystemStateRecord`) | partial |
| `src/execution/protection_rebuild.py` (new) | pure utility | transform | `src/execution/protection.py` (`_transition` payload is its input) | role-match |
| `src/execution/lot_filter_source.py` (new) | service | request-response | `src/persistence/snapshots.py` (snapshot store) | partial |
| `src/persistence/pending_actions.py` (new) | store | CRUD | `src/persistence/system_state.py` (`PgSystemStateStore`) | exact (shape) |
| `src/persistence/lot_filters.py` (new) | store | CRUD (upsert) | `src/persistence/snapshots.py` | role-match |
| `src/persistence/safe_mode_store.py` (new) | adapter | CRUD | `src/persistence/system_state.py` | exact |
| `src/db/alembic/versions/0007_reconcile_hardening.py` (new) | migration | DDL | `0006_approval_quantity.py` (style), `0004_persistence_integrity.py` (create_table) | exact |
| `src/db/models.py` (modify, two new Row classes) | model | CRUD | `SystemStateEventRow` (lines 871-904) | exact |
| `src/execution/protection.py` (modify) | coordinator | event-driven | itself | exact |
| `src/execution/emergency_close.py` (modify) | service | request-response | itself | exact |
| `src/execution/manager.py` (modify) | service | request-response | itself | exact |
| `src/execution/enablement.py` (modify) | controller | event-driven | itself | exact |
| `src/execution/intent_recovery.py` (modify) | service | batch | itself | exact |
| `src/execution/execution_limits.py` + toml + README (modify) | config | config | itself | exact |
| `src/execution/order_ids.py` (modify, add predicates) | pure utility | transform | itself | exact |
| `src/domain/enums.py` (modify) | model | n/a | itself | exact |
| `src/persistence/entities.py` (`update_position_snapshot`) | store | CRUD | `transition_position` (645-687) | DEFERRED to Phase 24 (CONTEXT D-13 revised; no caller, no independent local source) |
| `src/ops/drills.py` (modify) | test harness | event-driven | itself (`make_unprotected_drill` ... `make_restore_drill`) | exact |
| `tests/*` (new/rewrite) | test | request-response | `tests/test_system_state_pg.py`, `tests/test_reconcile.py`, `tests/support/ast_guards.py` | exact |

## Pattern Assignments

### `src/reconcile/compare.py` (modify, pure, transform)

**Analog:** itself. Keep the stdlib + `src.domain.enums` only rule (module docstring lines 30-32).

**Kind vocabulary to extend** (lines 51-65): add constants and extend `_DIVERGENCE_KINDS`; the five existing names stay byte-identical.
```python
DIVERGENCE_KIND_ORPHAN_PROTECTIVE: str = "ORPHAN_PROTECTIVE"
...
_DIVERGENCE_KINDS: frozenset[str] = frozenset({ DIVERGENCE_KIND_ORPHAN_PROTECTIVE, ... })
```
`Divergence.__post_init__` (lines 140-148) rejects unknown kinds, so a new kind must be added to the frozenset first.

**Carriers to extend with optional fields** (lines 73-104): `LocalOrderIntent`, `LocalAlgoIntent`, `LocalPositionIntent` are frozen dataclasses; add fields with defaults (`plan_hash: str | None = None`, `max_abs_amount: Any = None`, expected side) so existing fixtures keep working. `position_amt` is typed `Any` to stay dependency-free; compare with `Decimal` only.

**Position check (CONTEXT D-01a, review 2026-10-21):** bound check only: sign equals the plan side, `abs(exchange amount) <= intended_quantity`, per symbol. Document in the docstring that it cannot see an over-fill below the intended quantity. If two local plans share a symbol, or an exposure has no determinable owning plan, emit a divergence and let SAFE_MODE follow; never pick one plan. Do not read from or write to a `positions` table here (no independent local source exists; exact comparison is Phase 24).

**Index build to modify for D-03 duplicates** (lines 223-224) silently keeps the last row:
```python
truth_normal_by_client_id: dict[str, Any] = {o.client_order_id: o for o in truth_normal_orders}
truth_algo_by_client_id: dict[str, Any] = {o.client_algo_id: o for o in truth_algo_orders}
```
Replace with a counting loop that emits `DUPLICATE_EXCHANGE_ID`.

**Local intent index + malformed-identity divergence** (lines 227-273) is the template for the reverse pass: iterate the truth rows, skip ids in `local_normal_by_client_id`, else emit a `Divergence` (see RESEARCH "Foreign-order reverse pass" sketch). Use `_get_field(entry, name)` for duck typing.

**Orphan rule (entry-aware change for D-05)** lines 304-333: the `is_protective and not has_position` branch is where the "plan's ENTRY still open/resting" exemption is added.

**Import of prefixes:** do not re-type `x-`, `xa-`, `xc-`. Import predicates added to `src/execution/order_ids.py` (see that entry). Run the layering test after adding the import.

---

### `src/reconcile/safe_mode.py` (modify, state machine)

**Analog:** itself.

**Store hook** goes in the constructor (lines 130-147). Pattern: a `Protocol` defined in this module next to `AdapterLike` / `JournalLike` (lines 49-73), so the module keeps importing nothing from `src.persistence`:
```python
class JournalLike(Protocol):
    def record(self, event: Any) -> None: ...
```
Add `class SafeModeStateStore(Protocol): save(...) / load()` the same way.

**Enter ordering** (lines 248-255): flip first, then journal. Add `store.save` after the journal call; a save failure leaves memory in SAFE_MODE (fail closed).

**Exit ordering to keep and extend** (lines 346-359): journal FIRST, then flip. New order: journal (with `operator_id` in payload) -> `store.save` -> flip.
```python
self._journal_safe_mode_event(event_type="SAFE_MODE_EXIT", reason="clean_three_source_compare", now_utc=effective_now)
self._in_safe_mode = False
```
**Fix F2 (vacuous exit)** lines 326-341: remove `local_open_orders or []`. A missing local source or a read error BLOCKS the exit (CONTEXT D-15): require `local_intent_fn` (or explicit lists proven read) and refuse when absent; an empty list is valid only after a successful read. Add exit preconditions through injected callables (no import from persistence): fresh Binance data for positions, open orders and algo orders; no unresolved divergence, `UNKNOWN` intent, `UNPROTECTED`, `CLOSE_REQUIRED` or pending protective action. The operator id is recorded for audit only. `safe_mode.py` still falls back to `datetime.now(UTC)` (lines 233, 320); new code must not copy that.

**Strict state format** (lines 404-443): `_STATE_KEYS` and `_parse_state` must gain `last_exit_operator_id`, `last_exit_at_utc`; keep the "in_safe_mode false but entry time set" invariants. `state_snapshot()` (189-202) and `rehydrate()` (149-187) change together; `rehydrate` is the startup load path.

**Operator id validation:** copy `_validate_operator_id` from `src/execution/enablement.py` (used at its line 277).

**Remove** `SAFE_MODE_TICK_SECONDS` (line 41) and its export (line 454, plus `src/reconcile/__init__.py`).

**Journal event builder** (lines 363-395) is the template for any new controller event: `content_hash_event_id(prefix="safe_mode", ...)`, `correlation_id="reconcile_safe_mode"`.

---

### `src/reconcile/sweeper.py` (modify)

**Analog:** itself.

**Skip path that must now journal (IN-14)** lines 196-207: today appends a `SweepSkip` only. Add a best-effort journal call modelled on `_record_failure_best_effort` (used at lines 220-225; defined line 306).
```python
if not (_is_zero_like(first_read) and _is_zero_like(second_read)):
    skip_reason = (f"transient_position_gap: ...")
    skipped.append(SweepSkip(symbol=symbol, client_algo_id=client_algo_id, reason=skip_reason))
    continue
```
**Probe-failure error style** (lines 217-233): record the exception TYPE only (`f"probe_failed: {type(exc).__name__}"`), never the message (T-18-14). Every new journal/alert text in this phase follows this rule.

**Pre-image journal before cancel** (lines 247-255) is the thing F-702 changes to spill-first/journal-after; the post-cancel verification (F-502) is added after `cancel_algo_order` (line 258).

---

### `src/reconcile/loop.py` (new, orchestrator, step-driven)

**Analog:** `src/execution/protection.py` `ProtectionCoordinator` (step-driven, injected clock, Protocol-typed adapters, `_transition` journaling). Read `_step_plan` (line 718) for the per-item dispatch shape, `_guarded` (1239-1244) for returning exceptions instead of raising:
```python
@staticmethod
async def _guarded(awaitable: Any) -> Any:
    try:
        return await awaitable
    except Exception as exc:  # noqa: BLE001 - returned so the caller journals it
        return exc
```
Exchange reads come from the three `snapshot_*` methods already declared in `AdapterLike` (`safe_mode.py` lines 58-62). Gate check uses `RestRateLimitGate.restriction()` / `remaining_seconds()` in `src/adapters/binance_ratelimit_gate.py`. No `datetime.now`: take `now` per call. The module must contain no `place_*` / `new_order` / `new_algo_order` call (narrowed static guard, RESEARCH Anti-Patterns).

---

### `src/reconcile/startup.py` (new, batch)

**Analog:** `src/execution/intent_recovery.py` `resolve_unresolved_intents` (lines 215-262).
```python
_require_utc(now_utc, "now_utc")
try:
    records = tuple(store.list_unresolved_intents())
except PersistenceError:
    safe_mode_controller.enter_safe_mode(reason=_DB_FAILURE, now_utc=now_utc)
    raise
```
Same shape for the startup order (RESEARCH Pattern 8): an unreadable store enters SAFE_MODE and re-raises ("nothing to resolve" must never equal "could not look").

---

### `src/execution/intent_recovery.py` (modify, D-11 and F5)

**Analog:** itself. The block to change is lines 196-201:
```python
elif answer.found is False and now_utc - record.intended_at_utc < lookup_window:
    target = ExecutionIntentStatus.REJECTED  # definitive absence of a young intent
else:
    return status
```
For ENTRY intents that went UNKNOWN after an ambiguous error, and for protective legs of a live plan (F5), this must leave the status `UNKNOWN`. Closing an UNKNOWN ENTRY (CONTEXT D-11) needs N consecutive `found=False` probes, GTD plus grace passed, a clean position read and open-orders read, and `ExitEvidence(REST_RECONCILE, ...)` per step; the terminal `REJECTED` then carries reason code `RECONCILED_ABSENT` (`RecordedOutcome.reason_code` is a free string; confirm `record_result` accepts it), never the code of a definite Binance rejection. An INTENDED entry keeps the existing REJECTED rule with its own reason. Closing an intent never exits SAFE_MODE. `_record(...)` (line 146) is the writer; its return value signals a failed write (`PersistenceError` -> False, line 166). Journal the evidence source per D-11/D-12.

---

### `src/ops/spill.py` (new, file-I/O)

**Analog:** `src/data/store.py` lines 41-99 (tmp file in the same directory, fsync, `os.replace` with a Windows `PermissionError` retry, tmp cleanup in `finally`).
```python
REPLACE_MAX_ATTEMPTS = 5
REPLACE_RETRY_SLEEP_SECONDS = 0.1

def replace_with_retry(tmp: Path, path: Path) -> None:
    for attempt in range(1, REPLACE_MAX_ATTEMPTS + 1):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == REPLACE_MAX_ATTEMPTS:
                raise
            time.sleep(REPLACE_RETRY_SLEEP_SECONDS)
```
`replace_with_retry` is importable; reuse it rather than copying. Note it calls `time.sleep` in `src/data/store.py`, so `spill.py` should import it, not re-implement it, to avoid tripping `wall_clock_calls` (which lists `time.time`, `time.monotonic` etc., not `sleep`). Name each file by the journal event id (idempotent replay; `PgJournalStore` is `ON CONFLICT DO NOTHING`). Temp name pattern: `f".{path.name}.{os.getpid()}.tmp"`. Replay deletes a file only after `journal.record` succeeds.

---

### `src/ops/alerts.py` (new, event-driven, Telegram I/O edge)

**Analog:** `src/paper/shadow.py` `_send_bounded` (746-771) and the tenacity predicates (700-743); `send_shadow_alert` (774-864) for the journal-on-success / journal-on-failure split.
```python
async def _send_bounded(bot, chat_id, text, keyboard, sleep) -> tuple[int, TelegramFailure | None]:
    """... never raises."""
    attempts = 0
    try:
        async for attempt in AsyncRetrying(stop=_stop, wait=_wait, retry=_retryable_state, reraise=True, sleep=sleep):
            with attempt:
                attempts += 1
                await send_text(bot, chat_id, text, keyboard)
    except Exception as exc:  # noqa: BLE001 - classified and journaled, never raised
        return attempts, _failure_of(exc)
    return attempts, None
```
Retryable kinds: `RATE_LIMITED`, `TRANSIENT`, `UNKNOWN`; `ValueError/KeyError/TypeError` are not retried (lines 700-708). Failure journal payload carries `error_class` only (lines 849-860), never message text. Imports to reuse: `send_text`, `TelegramSendError`, `classify_telegram_error` from `src/adapters/telegram_notify.py`; retry constants `NOTIFY_MAX_ATTEMPTS`, `NOTIFY_MAX_DELAY_SECONDS` from `src/paper/notify.py` (lines ~111-114). `_send_bounded` is module-private; either import it with care or lift the shared bits (planner choice).

**Sink contract to adapt** (`src/execution/protection.py` lines 401-406):
```python
class CriticalAlertSink(Protocol):
    def critical(self, *, event: str, plan_hash: str, symbol: str, reason: str, now_utc: datetime) -> None: ...
```
It is synchronous and called from async code; `CriticalAlertAdapter` forwards to the new `OperationalAlert` sink so the coordinator and closer call sites do not change.

---

### `src/persistence/safe_mode_store.py` (new, adapter, CRUD)

**Analog:** `src/persistence/system_state.py`.

**Imports** (lines 27-46): `from src.domain.enums import SystemStateKey`, `from src.persistence.uow import OperationalDatabase`, `from src.persistence.errors import ...`.

**Write path** `PgSystemStateStore.append(key, state, *, now_utc, tx=None)` (152-220): validates `state` as `str | bool | None` (floats and ints refused), writes the journal event and the state row in one transaction, retry is the caller's job on `RowConflict`. `latest(key)` (222-) returns the highest version or `None`, and raises `ValueError` on a malformed row.
```python
def append(self, key: SystemStateKey, state: Mapping[str, StateValue], *, now_utc: datetime, tx: Session | None = None) -> SystemStateRecord:
```
The adapter maps `save(state)` to `append(SystemStateKey.SAFE_MODE, state, now_utc=...)` and `load()` to `latest(...)`; `load()` raising must be treated as "start in SAFE_MODE" (RESEARCH Pattern 3). No DDL change: `SAFE_MODE` is already in the CHECK (models.py 897-900).

---

### `src/persistence/pending_actions.py` and `src/persistence/lot_filters.py` (new, CRUD)

**Analog:** `src/persistence/system_state.py` for structure (`_unit` context manager lines 143-150, `_require_utc_aware` lines 74-81, `IntegrityError` mapping to `RowConflict` / `ParentRowMissing` lines 198-213, frozen record dataclass with `__post_init__` validation lines 117-133). For the lot-filter upsert and write-once JSON, also read `src/persistence/snapshots.py` (not re-read here; RESEARCH cites `PgPlanConstraintSnapshotStore`, canonical JSON + sha256).

```python
@contextmanager
def _unit(self, tx: Session | None) -> Iterator[Session]:
    if tx is not None:
        yield tx
        return
    with self._db.transaction() as session:
        yield session
```
The Row classes follow `SystemStateEventRow` (`src/db/models.py` 871-904): `__tablename__`, `Mapped[...]` columns, `__table_args__` with `PrimaryKeyConstraint`, named `UniqueConstraint`, and PostgreSQL-only `CheckConstraint(...).ddl_if(dialect="postgresql")`. The partial unique index `(plan_hash, pending_kind) WHERE state='PENDING'` is new; model it as an `Index(..., postgresql_where=...)` and mirror it in the migration (an ORM parity test exists).

---

### `src/db/alembic/versions/0007_reconcile_hardening.py` (new, migration)

**Analog:** `0006_approval_quantity.py` for the header and conventions; `0004_persistence_integrity.py` (line 72 and 480, `op.create_table`) for creating tables.
```python
revision: str = "0006_approval_quantity"
down_revision = "0005_live_sized_risk"
branch_labels = None
depends_on = None
```
New file: `revision = "0007_reconcile_hardening"`, `down_revision = "0006_approval_quantity"`. Docstring states hand-written, imports no project module, TIMESTAMPTZ UTC, NUMERIC(38,18), named constraints, a real downgrade. Use `op.create_check_constraint` / named constraints as in 0006 lines 49-53; downgrade drops in reverse order.

---

### `src/execution/protection.py` (modify, D-07, D-08, D-19, F6)

**Analog:** itself.

**Stop-lost decision to reuse (do not duplicate)** `_on_stop_lost` lines 1203-1237: sets `stop_lost_at` once (`if tracked.stop_lost_at is None: tracked.stop_lost_at = self._now()`), then CLOSE_REQUIRED on exposure, FLAT after two flat reads, else UNPROTECTED. D-07 supervision after `PROTECTED` / `COMPLETE` / `TP_UNAVAILABLE` calls this same method from `_attach_take_profits` (line 1397) and `_watch_exit` (line 1505) after a stop read; `_apply_stop_answer` (1246-) returns the `_StopReading` enum and is the stop-read interpreter.

**Transition journal payload = rebuild input** `_transition` lines 1648-1686: payload keys `approval_id, from, reason, seq, symbol, to, trade_plan_id`, correlation `f"{_CORRELATION_PREFIX}{entry.plan_hash}"`, event type `EVENT_PROTECTION_TRANSITION`, id from `correlated_event_id(... step=f"{tracked.seq}:{previous}->{new_state.value}")`. `protection_rebuild.py` reads exactly this.

**Fail-open bug to fix (F6)** `blocks_new_entries` line 625: `any(t.state in BLOCKING_STATES ...)` over an empty dict after restart. Add a `_restore_pending` flag.

**Diagnostic journal style** `_journal_note` lines 1688-1715: fixed text and exception TYPE names only.

---

### `src/execution/emergency_close.py` (modify, D-08, D-21)

**Analog:** itself. `self._pending: dict[str, _PendingAttempt]` (line 307); adoption of an unknown attempt already exists at lines 380-381:
```python
adopted.mark_unknown(CODE_HISTORY_NOT_TERMINAL)
self._pending[entry.plan_hash] = adopted
```
Restore from `EMERGENCY_CLOSE` journal rows and the spill uses this same adoption path, so nothing is sent until REST proves the attempt terminal. `discover_next_attempt_no` (line 248) stays the REST backstop for numbering. Exported code `CODE_HISTORY_NOT_TERMINAL` (line 832).

---

### `src/execution/manager.py` and `src/execution/enablement.py` (modify, F-702, F-502, F1, EXEC-06)

**Analog:** themselves.

- `LiveEnablementController.disable` (`enablement.py` 266-289) is journal-first then flip: change to flip, then journal with spill fallback.
```python
self._journal_enablement_event(event_type="LIVE_ORDERS_DISABLED", operator_id=operator_id, now_utc=now_utc, disabled_after=True)
self._disabled = True
```
- `manager.py`: `expire_pending_entry` (1963), `cancel_untriggered_protectives` (2049), `emergency_manual_close` (2147; F1: calls `cancel_untriggered_protectives` at about 2236-2245 with the position possibly open). New `operator_close_position` / `operator_protect_position` copy the operator-id validation and the `MarketEmergencyCloser` use of `emergency_close.py`. `operator_protect_position` trigger price comes only from `entry.sl_trigger_price` and the id from `derive_algo_client_id(plan_hash=..., role=STOP_LOSS)`.

---

### `src/execution/order_ids.py` (modify, add `is_system_client_id`, `plan_slice_of`)

**Analog:** itself, lines 40-65 and 100-140.
```python
_CLIENT_PREFIX = "x-"      _CLIENT_PLAN_SLICE_LEN = 32
_ALGO_PREFIX = "xa-"       _ALGO_PLAN_SLICE_LEN = 31
_CLOSE_PREFIX = "xc-"      _CLOSE_PLAN_SLICE_LEN = 29
```
Build predicates from these constants (note `x-` is a prefix of nothing else, but check `xa-`/`xc-` first or use `startswith` on the tuple). Ids are 36 chars (`_ID_LENGTH`). Keep the existing `ROLE_CODES` table as the only place role-code literals appear.

---

### `src/execution/manager.py` (modify, `emergency_manual_close`, CONTEXT D-09 defect)

**Analog:** itself, lines 2224-2245. Today `expire_pending_entry` then `cancel_untriggered_protectives` (2049-2110, SL, TP1, TP2 in order, journal pre/post image per leg, per-leg isolation raised as `ExceptionGroup`) run with no position read. Keep the per-leg isolation and journal-first shape of `cancel_untriggered_protectives`, but move the protective cancel behind a gate: two independent fresh REST position reads flat, entry terminal, closer-confirmed close; then verify no orphan remains, else keep SAFE_MODE and alert. Never cancel while the position is not flat or the entry is open. Tests in `tests/test_phase8_audit_reviewfix.py` / `tests/test_reconcile.py` that assert the old unconditional cancel are rewritten (F-604).

---

### Also constrained by CONTEXT after review (no new file)

- **Queue priority (D-20):** the pending-actions queue orders protective, emergency-close, entry-remainder-cancel and the deciding queries before new entries; ordering only once the REST gate allows sending; the 429/418 cooldown is never bypassed (RESEARCH Pattern 10).
- **Alerts (D-24):** add `PROTECTIVE_REJECTED` (high severity, rides the D034/CLOSE_REQUIRED flow) next to the `_send_bounded` style sender; distinct from `PROTECTION_HANDOFF_FAILED`. DAILY_STOP / daily-loss WARNING: contract, dispatcher, dedupe and test trigger only.
- **State safety (D-29):** `protection.py` state changes go through the checked `_transition`; a stale or duplicate event cannot lower `CLOSE_REQUIRED`, erase `UNPROTECTED` or clear SAFE_MODE. No event-time column or Order monotonic rule in Phase 20.
- **Config (D-25):** new keys in `config/execution/execution-limits-v1.toml` under `reconcile.*`, `stale_feed.*`, `alerts.*`, `protection.*`; `SAFE_MODE_TICK_SECONDS` replaced by `reconcile.tick_interval_ms` (the test pinning it at `tests/test_reconcile.py:675` is rewritten).

---

### `src/persistence/entities.py` (`update_position_snapshot`) — DEFERRED to Phase 24 (CONTEXT D-13)

Do not implement in Phase 20. Kept only as a reference for Phase 24. **Analog:** `transition_position` lines 645-687 (same file): `with self._unit(tx) as session:`, `row = _lock(session, _POSITION, position_id)`, `_apply(session, _POSITION, position_id, "status", old_status.value, changes)` where `changes` includes `"updated_at_utc": now_utc`. The new method updates quantity and PnL columns the same way and journals via `exit_evidence_event` only when leaving UNKNOWN (evidence rule already enforced, F4).

---

### `src/ops/drills.py` (modify, G2-016)

**Analog:** itself. Factories `make_unprotected_drill` (458), `make_stale_feed_drill` (697), `make_manual_close_drill` (781), `make_restore_drill` (851) each define nested `inject()` / `assert_outcome(journal: DrillLog, context)`; `run_drill` (268) and `run_all_drills` (327) drive them, `_build_drill_outcome_event` (378) writes the outcome. `make_restore_drill` must pass an operator id and a `local_intent_fn` after the `exit_safe_mode` signature change. Per F10 the never-emitted outcomes are `OUTCOME_SAFE_MODE_BLOCKED` and `OUTCOME_NO_PLACE_ORDER_INVARIANT` (lines 98-103); the second encodes the old rule and is retired, not emitted.

---

### Tests

- PG tests: copy `tests/test_system_state_pg.py` and `tests/pg_support.py` (`TEST_DATABASE_URL`, database name ends in `_test`; unset means silent skip, `TRADING_CI_STRICT=1` fails it).
- Fake exchange style: `tests/test_reconcile.py` (fake adapter at lines 245-251; rewrite list in RESEARCH "Tests to create / rewrite").
- AST gate: `tests/support/ast_guards.py` exposes `module_imports`, `forbidden_imports`, `float_constructor_calls`, `wall_clock_calls(path)` and `WALL_CLOCK_CALLS`; `tests/test_phase20_gate.py` asserts an empty result for every new pure/orchestrator module.
```python
WALL_CLOCK_CALLS: tuple[str, ...] = ("datetime.now", "datetime.utcnow", "date.today", "time.time", "time.time_ns", "time.monotonic", ...)
```

## Shared Patterns

### Journal event identity
**Source:** `src/domain/journal.py` `content_hash_event_id` / `correlated_event_id`; example use `src/reconcile/safe_mode.py` 378-394 and `src/execution/protection.py` 1669-1685.
**Apply to:** alerts, spill records, pending actions, SAFE_MODE exit, rebuild. Deterministic ids make a spill replay a no-op.

### Error text hygiene
**Source:** `src/reconcile/sweeper.py` 217-233 (`type(exc).__name__` only). **Apply to:** every new journal payload and alert body; never exchange text, URL, token.

### UTC-injected clocks
**Source:** `safe_mode.py` 233-237 (the `now_utc` validation, `tzinfo is None` / `utcoffset() != timedelta(0)`); `system_state._require_utc_aware` (74-81). **Apply to:** all new modules. Note `safe_mode.py` still falls back to `datetime.now(UTC)` (lines 233, 320); do not copy that fallback into new pure modules.

### Fail closed on store failure
**Source:** `intent_recovery.py` 233-237 and `safe_mode.py` rehydrate (160-164). **Apply to:** startup, SAFE_MODE load, pending-action load.

### Limits with provenance
**Source:** `config/execution/execution-limits-v1.toml` + `src/execution/execution_limits.py` (`EXECUTION_LIMIT_KEYS`) + `tests/support/execution_limits.py`, `tests/test_execution_limits.py`, `tests/test_no_unratified_defaults.py`. **Apply to:** cadence, stale-feed, WS-silence, probe count and unknown-grace keys; all `NOT_CONFIGURED`.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `src/ops/risk_first.py` | utility | act-first / journal-after | No act-then-record helper exists; every current path is journal-first. Use the RESEARCH "Risk-first helper" sketch plus `spill.py`. |
| `src/reconcile/feed_freshness.py` | pure utility | transform | No freshness predicate module exists in `src/reconcile`; RUNBOOK freshness thresholds and `src/ops/health.py` are the nearest sources (not read this session). |

## Metadata

**Analog search scope:** `src/reconcile`, `src/execution`, `src/persistence`, `src/db`, `src/ops`, `src/paper`, `src/data`, `tests/support`.
**Files read this session:** 20-CONTEXT.md, 20-RESEARCH.md (lines 1-601 of 762; the remainder was not needed for the file list), compare.py, safe_mode.py, sweeper.py (141-260), system_state.py (1-240), 0006 migration, intent_recovery.py (165-262), protection.py excerpts, shadow.py excerpts, data/store.py excerpt, order_ids.py excerpt, enablement.py excerpt, models.py excerpt.
**Not read (flagged):** `src/persistence/snapshots.py`, `src/execution/manager.py` bodies, `src/execution/emergency_close.py` bodies, `src/ops/health.py`, `tests/test_reconcile.py`; the entries that depend on them cite RESEARCH line references and should be re-read by the executor.
**Pattern extraction date:** 2026-10-20
