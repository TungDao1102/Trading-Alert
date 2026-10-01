# Phase 7: Paper Forward Observation - Pattern Map

**Mapped:** 2026-09-26
**Files analyzed:** 14 new files (8 src + 6 tests + fixtures)
**Analogs found:** 14 / 14 (all matched)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/paper/__init__.py` | barrel | n/a | `src/backtest/__init__.py` | exact |
| `src/paper/loop.py` | service | event-driven (closed-candle dispatch) | `src/backtest/simulator.py` | exact |
| `src/paper/supervisor.py` | service | event-driven (WS lifecycle) | `src/data/collector.py` | role-match |
| `src/paper/resync.py` | service | request-response (REST backfill + gap detect) | `src/data/backfill.py` | exact |
| `src/paper/journal.py` | service | CRUD (attributed record assembly) | `src/db/mappers.py` | role-match |
| `src/paper/attribution.py` | utility | transform (three-way split) | `src/domain/enums.py` | role-match |
| `src/paper/freeze.py` | service | CRUD (epoch pin + diff monitor) | `src/backtest/binding.py` | exact |
| `src/paper/notify.py` | service | event-driven (SIMULATE send) | `src/data/collector.py` | role-match |
| `src/adapters/paper_ws.py` | adapter | streaming (WS kline subscription) | `src/adapters/binance_usdm.py` | exact |
| `tests/fixtures/phase7/` | test fixture | n/a | `tests/fixtures/phase6/` | exact |
| `tests/test_paper_closed_candle.py` | test | n/a | `tests/test_candle_close_timing.py` | exact |
| `tests/test_paper_resync.py` | test | n/a | `tests/test_collector.py` | exact |
| `tests/test_paper_feed_gates.py` | test | n/a | `tests/test_collector.py` | role-match |
| `tests/test_paper_parity.py` | test | n/a | `tests/test_fixture_harness.py` | exact |
| `tests/test_paper_attribution.py` | test | n/a | `tests/test_collector.py` | role-match |
| `tests/test_paper_freeze.py` | test | n/a | `tests/test_backtest_binding.py` | exact |

## Pattern Assignments

### `src/paper/__init__.py` (barrel)

**Analog:** `src/backtest/__init__.py`

**Imports pattern** (lines 1-56): barrel re-exports public symbols from each submodule; no logic lives here. The package docstring declares the purity contract (stdlib + Decimal + `src/core/_decimal.py` only — no Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic).

**Core pattern** (lines 14-32): `from .module import Name` for each public symbol, then `__all__ = [...]` listing every exported name. The barrel is the single import surface for downstream consumers.

**Apply to:** `src/paper/__init__.py` — re-export `loop`, `supervisor`, `resync`, `journal`, `attribution`, `freeze`, `notify` public symbols. Mirror the purity-contract docstring verbatim (Phase-4 D-10 / Phase-5 D-05 / Phase-6 D-05 precedent).

---

### `src/paper/loop.py` (service, event-driven)

**Analog:** `src/backtest/simulator.py`

**Imports pattern** (lines 17-35): stdlib + `src/core/_decimal.py` + `src/core/planner.plan` + `src/core/strategy.evaluate` + `src/core/types` + `src/domain/canonical.sha256_hex` + `src/domain.registry.load_parameter_set` + `src/domain.trade_plan.TradePlan` + `src/risk.gating.evaluate_risk` + `src/risk.portfolio.resolve_absolute_thresholds` + `src/risk.types` + `.costs.CostModel/build_cost_model/modeled_costs_per_unit`. NO Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic.

**Core pattern** (lines 699-900, `simulator.run`): the canonical call chain — `load_parameter_set(strategy_id, parameter_set_id)` → `resolve_absolute_thresholds(parameter_set=..., equity=...)` → for each closed bar: `evaluate(snapshot, account_state, strategy_version, parameter_set)` → if `is_no_trade` continue → `plan(signal, setup_candles, parameter_set, account_state, created_at_utc)` → if `is_no_trade` emit reject → `evaluate_risk(trade_plan, candidate_position_side, account_state, constraint_snapshot, open_positions, daily_loss_quote, now_utc, ttl, modeled_costs_per_unit, minimum_risk_utilization_after_rounding, parameter_set=absolute_thresholds)` → if `is_no_trade` emit reject → `resolve_intrabar(direction, stop_loss, take_profit_1, intrabar)` for simulated fill.

**Validation helpers** (lines 42-87): `_require_decimal`, `_require_utc_aware`, `_require_non_empty`, `_coerce_money` (rejects float, accepts Decimal/str/int), `_parse_utc_aware`. All raise loudly on bad input — fail-closed posture.

**Error handling pattern** (lines 773-797, 822-832): `is_no_trade` short-circuits with `reason_code` preserved; the first NO_TRADE wins. NO_TRADE is data, not an exception — emit a journal record with the reason code and continue.

**Apply to:** `src/paper/loop.py` — copy the canonical call chain verbatim. The paper loop calls the IDENTICAL functions the backtest executes (D-02). The only differences: (a) `now_utc` is wall-clock (injected clock for tests), not the fixture's `now_utc`; (b) the `intrabar` for `resolve_intrabar` comes from the WS 1m stream, not a fixture; (c) every emitted record carries the three-way attribution field (system / user-executed-sim / opportunity) and the full timestamp lineage (signal/approve(sim)/order(fill-sim)/fill).

---

### `src/paper/supervisor.py` (service, event-driven)

**Analog:** `src/data/collector.py`

**Imports pattern** (lines 40-65): stdlib + `structlog` + `tenacity` + `src.adapters.binance_usdm.BinanceUsdmAdapter/Kline/is_rate_limit_error` + `src.data.backfill.LIVE_5` + `src.db.models.TICK_WIDE_SYMBOL/CollectorGap/CollectorWatermark`. The collector is the canonical reconnect/collect loop precedent.

**Core pattern** (lines 342-434, `async_oi_tick`): per-symbol isolation — for each symbol in the universe, call the adapter; on exception, record a per-symbol gap row and continue; healthy symbols still commit. The fail-closed posture: any failed poll writes ONE gap row with expected vs observed timestamps and never advances the watermark.

**Reconnect pattern** (lines 194-223, `fetch_page_with_retry` in `backfill.py`): tenacity-bounded retry with `stop_after_attempt | stop_after_delay`, `wait_random_exponential`, `reraise=True`. Never infinite retry on order-adjacent paths.

**Watermark pattern** (lines 318-335, `_advance_watermark`): upsert the watermark row for one (symbol, data_class) — atomic with the snapshot insert.

**Gap pattern** (lines 278-310, `_record_gap`): idempotent insert via `session.merge(CollectorGap(...))` on PK `(symbol, data_class, expected_utc)`. `TICK_WIDE_SYMBOL` sentinel for tick-wide failures (never NULL — PG rejects NULL in PK columns).

**Apply to:** `src/paper/supervisor.py` — copy the per-symbol isolation + gap-journal pattern. The supervisor owns the WS lifecycle (subscribe, keepalive, 24h rotation, reconnect trigger). On unsolicited disconnect or missed close, call `reconnect_and_resync` (delegates to `src/paper/resync.py`) and journal the gap. The 24h server-initiated rotation is treated as scheduled (proactive resubscribe + REST-resync), not an outage incident.

---

### `src/paper/resync.py` (service, request-response)

**Analog:** `src/data/backfill.py`

**Imports pattern** (lines 33-43): stdlib + `structlog` + `tenacity` + `src.adapters.binance_usdm.BinanceUsdmAdapter/Kline/is_rate_limit_error` + `src.data.quality.check_batch` + `src.data.store.DEFAULT_RAW_ROOT/publish_batch`.

**Core pattern** (lines 231-523, `backfill_symbol_interval`): paginate `[start_ms, end_ms)` in fixed interval windows; call the adapter page-by-page with `limit=1500`; drop the still-forming candle (`close_time_utc > now_utc`) before publishing (Pitfall 1 — no future-bar leakage); retry 429/418 via tenacity with exponential backoff + jitter; send every batch through the quality gate; persist per-file via `publish_batch` (D-04 immutability — file already on disk raises `FileExistsError`).

**Cursor pattern** (lines 128-176, `CursorStore`): per-(symbol, interval) cursor persistence for idempotent re-runs. Atomic persist via tmp + `os.replace`. A re-run reads the cursor and resumes at the next open_time, so a killed run never double-publishes.

**Bounded retry pattern** (lines 194-223, `fetch_page_with_retry`): tenacity `AsyncRetrying(retry=retry_if_exception(lambda e: _is_rate_limit(e)), stop=stop_after_attempt(max_retries), wait=wait_exponential_jitter(initial=0.5, max=jitter_max_seconds * 4), reraise=True)`.

**Apply to:** `src/paper/resync.py` — copy the paginator + cursor + bounded-retry pattern. The resync module is called by the supervisor on reconnect/rotation. It REST-fetches missed closes via `adapter.klines(symbol, interval, start_ms=ms(last_close_utc))`, diffs against in-memory state, and journals any holes as gap rows (never synthesizes candles — D-09 flag-never-fabricate).

---

### `src/paper/journal.py` (service, CRUD)

**Analog:** `src/db/mappers.py`

**Imports pattern** (lines 17-40): stdlib + `src.db.models.{SignalRow, TradePlanRow, ApprovalRow, OrderRow, FillRow, JournalEventRow}` + `src.domain.{approval, enums, fill, journal, order, position, signal, trade_plan}`.

**Core pattern** (lines 45-91, `signal_to_row` / `signal_from_row`): thin total mappers between domain entities and ORM rows. Every field mapped 1:1. Enum translation is the only bridge: `Enum.value` for storage, `Enum(value)` for restore (raises ValueError on unknown — D-10). Round-trip tested: `from_row(to_row(x)) == x`.

**Apply to:** `src/paper/journal.py` — copy the thin-mapper pattern. The journal module assembles attributed paper records (Signal/TradePlan/Approval(action=SIMULATE)/Order(simulated)/Fill(simulated)/JournalEvent) and persists them via the existing seven-entity ORM rows. No new tables needed unless the planner adds a paper-specific column (extend `data_class` on `CollectorGap` with `'paper-1h'` rather than inventing a parallel table — RESEARCH Pattern 3).

---

### `src/paper/attribution.py` (utility, transform)

**Analog:** `src/domain/enums.py`

**Imports pattern** (lines 1-14): stdlib only — `from enum import Enum`.

**Core pattern** (lines 16-70, `SignalStatus` / `ApprovalAction` / `ApprovalResult`): `class X(str, Enum)` with verbatim string values from GLOSSARY. The `str, Enum` mixin keeps ORM/JSON `.value` storage trivial while preserving Enum identity for mypy checks.

**Apply to:** `src/paper/attribution.py` — define the three-way attribution enum:
```python
class AttributionKind(str, Enum):
    SYSTEM = "system"  # engine emitted
    USER_EXECUTED_SIM = "user-executed-sim"  # SIMULATE fill (incl. approval-delay modeling)
    OPPORTUNITY = "opportunity"  # skipped/expired with reason code (retained, never dropped)
```
Plus a `PaperApprovalAction` extension or reuse `ApprovalAction.SIMULATE` for the simulated approval. The attribution field is a first-class column on every paper record, not a post-hoc join.

---

### `src/paper/freeze.py` (service, CRUD)

**Analog:** `src/backtest/binding.py`

**Imports pattern** (lines 25-29): stdlib + `src.domain.registry.ParameterSet` + `.costs.COST_KEYS/CostModel/build_cost_model`. NO Polars/pandas/NumPy/Binance SDK/SQLAlchemy/Pydantic.

**Core pattern** (lines 43-61, `assert_cost_model_binds_registry`): the gate compares the loaded ParameterSet's cost-key slice against the caller-supplied CostModel and raises a dedicated exception on hash inequality — before any record exists. Comparison is canonical-hash-to-hash (`build_cost_model(registry_slice).cost_model_hash == passed.cost_model_hash`). Absent slice keys propagate as bare `KeyError` from `build_cost_model` (fail closed, never silent defaults).

**Exception pattern** (lines 32-40, `CostModelBindingMismatch`): distinct from `ExperimentReproducibilityBroken` (that means *replay drift* on an existing record; this means *assembly refusal* before any record exists). A mismatched binding is a programming/identity error, not a market outcome, and the project fail-closed posture demands a loud raise.

**Apply to:** `src/paper/freeze.py` — at stream start, record `(parameterSetId, parameterSetHash)` via `load_parameter_set` + `assert_cost_model_binds_registry`. A periodic job re-hashes the registry files and compares; any diff ⇒ log + new epoch, evidence windows stay per-epoch. PAPER-03 artifact = the diff log. The freeze module owns the epoch pin + diff monitor; the paper loop reads the pinned hash at startup and refuses to start if the binding gate fails.

---

### `src/paper/notify.py` (service, event-driven)

**Analog:** `src/data/collector.py` (notify pattern) + `src/domain/approval.py` (SIMULATE action)

**Imports pattern** (lines 40-65): stdlib + `structlog` + `tenacity` + `telegram.Bot` + `telegram.InlineKeyboardButton` + `telegram.InlineKeyboardMarkup` (the `python-telegram-bot` import lives behind the adapter edge — paper-core never imports it directly).

**Core pattern** (RESEARCH §Code Examples, SIMULATE notify payload): `Bot.send_message(chat_id=AUTHORIZED_CHAT, text=text, reply_markup=InlineKeyboardMarkup(keyboard))` with the 12 APRV-01 fields (symbol, direction, setup, entry, SL, TP(s), RR, risk, expiry, invalidation, exposure, reason codes). No `Application` poller in Phase 7 — callbacks are inert labels until Phase 8 hardens them.

**Journal-first ordering** (RESEARCH §Pitfall 5): notify in its own bounded-retry block AFTER the journal row commits. Notify failure must never lose a signal — journal first, notify second, journal the notify outcome. Notify exception never blocks the loop, never auto-approves.

**Apply to:** `src/paper/notify.py` — the notify module formats the SIMULATE payload (12 APRV-01 fields) and sends via `Bot.send_message`. The `Bot` client itself lives behind an adapter-edge wrapper (the paper-core never imports `python-telegram-bot` directly — same isolation pattern as `src/adapters/binance_usdm.py` for the SDK). Bounded retry via tenacity; notify outcome journaled as a `JournalEvent` (never as attribution).

---

### `src/adapters/paper_ws.py` (adapter, streaming)

**Analog:** `src/adapters/binance_usdm.py`

**Imports pattern** (lines 17-33): stdlib + `structlog` + `from binance_sdk_derivatives_trading_usds_futures.websocket_streams import DerivativesTradingUsdsFuturesWebSocketStreams` + `from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.enums import KlineCandlestickStreamsIntervalEnum`. This is the ONLY module allowed to import the WS surface (mirrors the REST adapter's SDK-isolation rule).

**Frozen dataclass pattern** (lines 49-68, `Kline`): `@dataclass(frozen=True)` with `Decimal` prices/quantities, `datetime` with `tzinfo=UTC` timestamps, and the invariant `close_time_utc <= now_utc` documented in the docstring (RESEARCH §Pitfall 1 — never include the forming candle).

**Adapter pattern** (lines 200-453, `BinanceUsdmAdapter`): project-owned wrapper around the SDK. Constructed without arguments → uses the default `prod` host. Tests inject a fake `sdk_client` so unit tests never touch the network. The adapter normalizes SDK response models to frozen dataclass instances — SDK types never leak past the boundary.

**Apply to:** `src/adapters/paper_ws.py` — copy the frozen-dataclass + adapter-isolation pattern. The WS client wraps `DerivativesTradingUsdsFuturesWebSocketStreams` and exposes:
- `subscribe(symbol, interval)` → returns a stream handle
- `on_kline(callback)` → invokes callback with a frozen `Kline` on each event
- `reconnect()` / `schedule_reconnect()` → SDK-provided reconnect (24h rotation, ping/pong)
- `close()` → clean shutdown

The paper loop subscribes via this adapter; the WS surface never leaks into `src/paper/`.

---

### `tests/fixtures/phase7/` (test fixture)

**Analog:** `tests/fixtures/phase6/`

**Layout pattern** (per `tests/fixtures/phase6/`): per-case subdirectory with `input.json` + `expected.json`. Cases: `clean_run`, `reconnect_resync`, `unrecoverable_gap`, `epoch_rollover`, `attribution_split`, `feed_stale_no_trade`, `warmup_invalid_no_trade`, `parity_overlapping_history`.

**Apply to:** `tests/fixtures/phase7/` — create the per-case subdirectories with `input.json` (feed sequences: forming updates interleaved with closed candles, reconnect events, gap windows, epoch diff events) and `expected.json` (byte-exact expected journal/attribution/epoch records). The fixtures are the canonical correctness mechanism (TESTING_STRATEGY §2 golden-fixture model).

---

### `tests/test_paper_closed_candle.py` (test)

**Analog:** `tests/test_candle_close_timing.py`

**Test pattern** (lines 155-196, `test_forming_candle_contributes_no_setup_signal`): build a snapshot with closed bars + a forming bar (close > now); call `evaluate`; assert that if a SETUP is emitted, its `detected_at_utc` does NOT equal the forming bar's close. The double gate (`x is True` AND `close_time_utc <= now_utc`) is the invariant.

**Apply to:** `tests/test_paper_closed_candle.py` — test that the paper loop's closed-candle gate rejects forming-candle updates. Inject a feed sequence with interleaved forming updates before the close marker; assert no signal is emitted from the forming bar.

---

### `tests/test_paper_resync.py` (test)

**Analog:** `tests/test_collector.py`

**Test pattern** (lines 216-260, `test_oi_tick_symbol_failure_records_per_symbol_gap_healthy_symbols_commit`): per-symbol isolation — one bad symbol records its own gap row while healthy symbols still commit. The fail-closed posture: any failed poll writes ONE gap row and never advances the watermark.

**Apply to:** `tests/test_paper_resync.py` — test that on reconnect, the supervisor calls `adapter.klines` to backfill missed closes, diffs against in-memory state, and journals any holes as gap rows. Never synthesizes candles. The test injects a `FakeAdapter` that returns a partial page (some closes missing) and asserts the gap row is written with the correct expected vs observed timestamps.

---

### `tests/test_paper_feed_gates.py` (test)

**Analog:** `tests/test_collector.py`

**Test pattern** (lines 268-308, `test_oi_skipped_tick_records_expected_vs_observed_no_interpolation`): skipped tick records expected vs observed timestamps, no fabricated value. D-09: flag-never-fabricate.

**Apply to:** `tests/test_paper_feed_gates.py` — test that warm-up invalid → NO_TRADE + reason code, and stale feed → NO_TRADE + reason code. Inject a feed with insufficient warm-up history; assert the paper loop emits a NO_TRADE record with `reason_code=WARMUP_INSUFFICIENT` (or the canonical `RejectionReason` value). Inject a stale feed (last close > N seconds ago); assert NO_TRADE + `reason_code=DATA_STALE`.

---

### `tests/test_paper_parity.py` (test)

**Analog:** `tests/test_fixture_harness.py`

**Test pattern** (lines 143-166, `test_harness_output_matches_expected_files_digest_exactly`): harness output matches expected files digest-exactly via `sha256_hex`. Any unregistered semantic change to domain outputs fails here.

**Apply to:** `tests/test_paper_parity.py` — test that the paper loop on overlapping history produces byte-identical records to the backtest simulator. Run both on the same fixture input; assert the trade lists match digest-exactly. The divergence gate is the acceptance criterion (IMPLEMENTATION_PLAN Phase 2 exit gate: no material divergence).

---

### `tests/test_paper_attribution.py` (test)

**Analog:** `tests/test_collector.py`

**Test pattern** (lines 316-354, `test_funding_sweep_uses_separate_partition_and_watermark_namespace`): the funding sweep writes to its own partition and watermark namespace, distinct from OI. The test asserts the partition directory exists for the expected namespace and NOT for the other.

**Apply to:** `tests/test_paper_attribution.py` — test that every paper record carries the three-way attribution field (system / user-executed-sim / opportunity) and the full timestamp lineage (signal/approve(sim)/order(fill-sim)/fill). Test that skipped/expired plans are retained with reason codes (never dropped). Test that the attribution enum values match the canonical vocabulary.

---

### `tests/test_paper_freeze.py` (test)

**Analog:** `tests/test_backtest_binding.py`

**Test pattern** (per `src/backtest/binding.py:43-61`): the gate raises `CostModelBindingMismatch` on hash inequality. Absent slice keys propagate as bare `KeyError` from `build_cost_model` (fail closed, never silent defaults).

**Apply to:** `tests/test_paper_freeze.py` — test that at stream start, the freeze module pins `(parameterSetId, parameterSetHash)` via `load_parameter_set` + `assert_cost_model_binds_registry`. Test that a registry diff against the pinned set opens a new epoch (evidence windows stay per-epoch). Test that the PAPER-03 artifact (diff log) is written on every monitor tick.

---

## Shared Patterns

### Adapter Boundary Isolation

**Source:** `src/adapters/binance_usdm.py:1-15` (module docstring) + `src/adapters/binance_usdm.py:27-33` (SDK imports)

**Apply to:** All modules that touch the Binance SDK or `python-telegram-bot`. The adapter is the ONLY module allowed to import the SDK; downstream consumers receive frozen dataclass instances.

```python
# src/adapters/binance_usdm.py:27-33
from binance_sdk_derivatives_trading_usds_futures import (
    DerivativesTradingUsdsFutures,
    RateLimitBanError,
    TooManyRequestsError,
)
```

**Rule:** `src/paper/` core must be as dependency-free as `src/core|risk|backtest/` (stdlib + Decimal only). The WS client and the Telegram `Bot` stay behind edge wrappers (`src/adapters/paper_ws.py` and the notify adapter).

---

### Fail-Closed Gap Journaling

**Source:** `src/data/collector.py:278-310` (`_record_gap`) + `src/data/collector.py:342-434` (`async_oi_tick`)

**Apply to:** All paper-loop paths that can fail (WS reconnect, REST resync, feed staleness, warm-up invalid). Any failed poll writes ONE gap row with expected vs observed timestamps and never advances the watermark.

```python
# src/data/collector.py:300-310
session.merge(
    CollectorGap(
        symbol=symbol,
        data_class=data_class,
        expected_utc=expected_utc,
        observed_utc=observed_utc,
        reason=reason[:256],
        recorded_at_utc=datetime.now(UTC),
    )
)
session.commit()
```

**Rule:** Downstream MUST treat gap rows as missing, NEVER as zero / interpolated values. Idempotent inserts: a second gap for the same expected tick is a no-op via the (symbol, data_class, expected_utc) PK. Tick-wide failures use `TICK_WIDE_SYMBOL` (never NULL) as the symbol.

---

### Frozen Dataclasses with UTC-Aware Datetimes

**Source:** `src/domain/signal.py:37-78` + `src/domain/trade_plan.py:46-105` + `src/domain/approval.py:30-70` + `src/domain/journal.py:35-77`

**Apply to:** All paper-record domain types. Every domain entity is a `@dataclass(frozen=True)` with `Decimal` money/qty/price fields, `datetime` with `tzinfo=UTC` timestamps, and `__post_init__` validation that raises loudly on bad input.

```python
# src/domain/signal.py:37-78
@dataclass(frozen=True)
class Signal:
    signal_id: str
    strategy_id: str
    strategy_version: str
    parameter_set_id: str
    parameter_set_hash: str
    symbol: str
    direction: str
    setup_type: str
    source_timeframe: str
    source_candle_close_utc: datetime  # aware UTC
    detected_at_utc: datetime
    status: SignalStatus  # explicit — never inferred (D-11)
    expires_at_utc: datetime
    invalidated_at_utc: datetime | None = None  # None = "never happened"

    def __post_init__(self) -> None:
        for fname in ("signal_id", "strategy_id", ...):
            _require_non_empty(getattr(self, fname), fname)
        _require_utc_aware(self.source_candle_close_utc, "source_candle_close_utc")
        ...
```

**Rule:** No `Optional` status; `Optional` is reserved for "transition never happened" timestamps only. `status` is explicit (D-11); NULL timestamps mean "transition never happened".

---

### Content-Hash IDs

**Source:** `src/domain/ids.py:19-60` + `src/domain/canonical.py:39-89`

**Apply to:** All paper-record IDs (SignalId, TradePlanId, ApprovalId, OrderId, FillId, JournalEventId). IDs are content-hash SHA256 over the canonical JSON of the identity tuple — never passed in by callers.

```python
# src/domain/ids.py:19-46
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

**Rule:** `sha256_hex` uses canonical JSON (sorted keys, compact separators, `ensure_ascii=True`, `allow_nan=False`). Decimal → str() preserving full precision. datetime → UTC-normalized isoformat. Enum → .value. set/frozenset → REJECTED. float → REJECTED.

---

### Registry Hash Binding Gate

**Source:** `src/backtest/binding.py:43-61` (`assert_cost_model_binds_registry`)

**Apply to:** Stream bootstrap (freeze module pins the registry hash). The gate compares the loaded ParameterSet's cost-key slice against the caller-supplied CostModel and raises `CostModelBindingMismatch` on hash inequality — before any record exists.

```python
# src/backtest/binding.py:43-61
def assert_cost_model_binds_registry(parameter_set: ParameterSet, cost_model: CostModel) -> None:
    registry_slice = {k: parameter_set.params[k] for k in COST_KEYS}
    expected = build_cost_model(registry_slice)
    if expected.cost_model_hash != cost_model.cost_model_hash:
        raise CostModelBindingMismatch(
            f"cost_model_hash {cost_model.cost_model_hash!r} != registry-derived "
            f"{expected.cost_model_hash!r} for "
            f"{parameter_set.strategy_id}/{parameter_set.parameter_set_id}"
        )
```

**Rule:** Absent slice keys propagate as bare `KeyError` from `build_cost_model` (fail closed, never silent defaults). The gate reuses `COST_KEYS` and `build_cost_model` from `.costs` — never re-implements hashing.

---

### Single-Base ORM + Parity-Gate Discipline

**Source:** `src/db/models.py:42-48` (`Base`) + `src/db/alembic/env.py:39` (`target_metadata = Base.metadata`) + `src/db/alembic/versions/0002_domain_registry.py` (migration pattern)

**Apply to:** Any paper-journal migration. The Alembic env binds `Base.metadata` as `target_metadata` so a single source of schema truth covers the baseline migration and every later reviewed migration. No `create_all()` in production code paths.

```python
# src/db/models.py:42-48
class Base(DeclarativeBase):
    """Single declarative base for every model in `src/db/`.

    The Alembic env (src/db/alembic/env.py) binds this Base.metadata as
    `target_metadata` so a single source of schema truth covers the
    baseline migration and every later reviewed migration.
    """
```

**Rule:** Every DATA_MODEL change ships as a reviewed migration. Never `create_all` in production code paths. JSON-as-TEXT for portable, PG-version-agnostic metadata blobs. PKs are content-hash IDs (D-03); no auto-increment anywhere. Nullable columns ONLY for "transition never happened" timestamps (D-11).

---

### Decimal-Only + UTC-at-Boundary Discipline

**Source:** `src/core/types.py:48-56` (`_require_decimal`) + `src/core/types.py:38-46` (`_require_utc_aware`) + `src/domain/canonical.py:63-66` (float rejection)

**Apply to:** All exchange-sensitive arithmetic in `src/paper/`. Decimal-only for money/qty/price/risk fields. UTC-aware datetimes only. Float is banned repo-wide (AST guards `tests/test_domain_no_float.py`).

```python
# src/core/types.py:48-56
def _require_decimal(value: object, field_name: str) -> None:
    """Reject non-Decimal values for money/qty/price fields (D-12)."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, got {type(value).__name__}")
```

**Rule:** `Decimal` (or integer tick/qty-step arithmetic) for all exchange-sensitive values; floats allowed only inside statistical/feature code that never gates an order. UTC internally always; `Asia/Ho_Chi_Minh` presentation only at the display edge.

---

### structlog Decision-Lineage Logging

**Source:** `src/adapters/binance_usdm.py:33` + `src/data/collector.py:65` + `src/backtest/simulator.py` (no log calls — pure)

**Apply to:** All paper-loop modules that touch I/O (supervisor, resync, notify, freeze). The decision lineage (snapshot → signal → plan → approval → fill) must be traceable post-hoc via structured JSON logs.

```python
# src/data/collector.py:65
log = structlog.get_logger()
```

**Rule:** Every deterministic decision must be explainable post-hoc; structured logs + journal rows are the audit trail. Plain `logging` with JSON formatter is an acceptable substitute — do not build a custom logger. Secret-free structured logging (no token/secret in log fields).

---

### Tenacity Bounded Retry

**Source:** `src/data/backfill.py:194-223` (`fetch_page_with_retry`)

**Apply to:** WS reconnect, REST resync, Telegram sends. Bounded retry with `stop_after_attempt | stop_after_delay`, `wait_random_exponential`, `reraise=True`. Never infinite retry on order-adjacent paths.

```python
# src/data/backfill.py:205-208
retry = tenacity.retry_if_exception(lambda e: _is_rate_limit(e))
stop = tenacity.stop_after_attempt(max_retries)
wait = tenacity.wait_exponential_jitter(initial=0.5, max=jitter_max_seconds * 4)
decorator = tenacity.AsyncRetrying(retry=retry, stop=stop, wait=wait, reraise=True)
```

**Rule:** Retry policy is a safety feature (fail-closed): cap attempts, then NO_TRADE/SAFE_MODE — never infinite retry on order paths.

---

## No Analog Found

All 14 new files have close analogs in the existing codebase. No files require RESEARCH.md patterns as the primary source.

## Metadata

**Analog search scope:** `src/adapters/`, `src/backtest/`, `src/core/`, `src/data/`, `src/db/`, `src/domain/`, `src/risk/`, `tests/`, `tests/fixtures/`
**Files scanned:** 47 source files + 37 test files + 52 fixture files
**Pattern extraction date:** 2026-09-26
**All analog paths verified git-tracked:** yes (via `git ls-files`)
