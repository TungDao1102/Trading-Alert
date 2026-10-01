# Phase 8: Approval + Reconciliation Hardening - Pattern Map

**Mapped:** 2026-09-27
**Files analyzed:** 17 (12 new + 5 extend)
**Analogs found:** 25 / 25 tracked-source matches

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/approval/tokens.py` (NEW) | utility | crypto/token-derivation (pure) | `src/paper/freeze.py` `_make_epoch_id` (lines 244-266) | exact (pure stdlib hash + construction-time guards) |
| `src/approval/binding.py` (NEW) | service | request-response (pure state machine) | `src/paper/notify.py` `format_simulate` validation pattern (lines 122-197) | exact (frozen dataclass guards + fail-closed validators) |
| `src/approval/replay.py` (NEW) | service | request-response (idempotent resolution) | `src/paper/journal.py` `assemble_paper_record` (lines 164-377) | role-match (pure function returning frozen dataclass) |
| `src/reconcile/compare.py` (NEW) | service | event-driven + REST snapshot | `src/paper/resync.py` `backfill_missed_closes` (lines 134-277) | exact (compare local intent vs external truth + diff → action list) |
| `src/reconcile/sweeper.py` (NEW) | service | cancel-only event-driven | `src/paper/supervisor.py` `on_disconnect` (lines 169-194) | role-match (lifecycle management + journal-first ordering) |
| `src/reconcile/safe_mode.py` (NEW) | service | state-machine compose | `src/risk/gating.py` `evaluate_risk` (lines 27-122) + `src/risk/portfolio.py` `check_portfolio` (lines 152-350) | exact (fail-closed gates + first-failure-wins pipeline) |
| `src/ops/drills.py` (NEW) | service | test harness + journaled outcomes | `src/ops/backup.py` `run_drill` (D-12 drill precedent) + `src/paper/freeze.py` `check_registry_unchanged` (lines 416-513) | role-match (fault-injection + outcome assertion + journal) |
| `src/adapters/telegram_notify.py` (EXTEND) | adapter | callback request-response + send | `src/adapters/telegram_notify.py` (existing `send_simulate` lines 45-65 + `_short_signal_id` lines 68-78) | exact (extend in place; only PTB importer) |
| `src/adapters/binance_usdm.py` (EXTEND) | adapter | REST reconciler truth | `src/adapters/binance_usdm.py` `klines` + `exchange_info` methods (lines 214-453) | exact (extend in place; SDK owner) |
| `src/db/models.py` (EXTEND) | model | ORM persistence | `src/db/models.py` (existing ApprovalRow lines 270-299 + JournalEventRow lines 423-450) | exact (single-Base; add ShortIdMappingRow + JournalEventRow already covers event_type="DRILL_OUTCOME") |
| `src/db/alembic/versions/0003_callback_mapping.py` (NEW migration) | migration | schema DDL | `src/db/alembic/versions/0002_domain_registry.py` (lines 96-241) | exact (same `op.create_table` shape + index convention) |
| `tests/fixtures/phase8/` (NEW golden fixtures) | fixtures | golden input/expected pairs | `tests/fixtures/phase7/pinned_epoch_clean/` (input.json + expected.json pair) | exact (same input/expected pair convention) |
| `tests/test_approval_replay.py` (NEW) | test | replay determinism | `tests/test_paper_notify.py` `_FakeBot` (lines 113-132) + golden-fixture loader pattern (lines 38-59) | role-match (fake-injection + fixture-driven) |
| `tests/test_approval_message.py` (NEW) | test | format + callback_data byte-check | `tests/test_paper_notify.py` `test_format_simulate_renders_all_12_aprv01_fields` (lines 67-104) | exact (byte-check rendering + 64-byte assert) |
| `tests/test_reconcile.py` (NEW) | test | reconciler fake-exchange scenarios | `tests/test_paper_resync.py` `FakeAdapter` (lines 77-99) + injected-fault pattern | exact (fake adapter with recorded calls + assertion on outcomes) |
| `tests/test_order_ids.py` (NEW) | test | ID determinism property | `tests/test_paper_freeze.py` golden fixtures (input → epoch hash assertion, lines 130-141) | role-match (determinism property on inputs → identical outputs) |
| `tests/test_drills.py` (NEW) | test | drill harness | `tests/test_paper_freeze.py` `test_check_registry_unchanged_opens_new_epoch_on_diff` (lines 250-335) | exact (fault-injection + outcome JSONL assertion) |

## Pattern Assignments

### `src/approval/tokens.py` (utility, crypto/token)

**Analog:** `src/paper/freeze.py` `_make_epoch_id` (lines 244-266)

**Pattern** — Pure stdlib hash derivation with construction-time guards. The freeze module derives `epoch_id` from a content-hash over `(strategy_id, parameter_set_id, parameter_set_hash, opened_at_utc)` using `src/domain/canonical.py:sha256_hex`. The tokens module needs the same shape: `derive_token_hash(plan_hash, action, chat_id) → str` using SHA-256 from stdlib `hashlib`, and `issue_one_time_token() → str` using `secrets.token_urlsafe(32)`. Raw token is never persisted — only the SHA-256 hash goes onto `Approval.approval_token_hash`; verification uses `hmac.compare_digest` (constant-time).

**Imports pattern** (mirrors `src/paper/freeze.py` lines 60-74):
```python
from __future__ import annotations
import hashlib
import hmac
import secrets

from src.domain.canonical import sha256_hex
```

**Construction-time validation pattern** (from `_make_epoch_id` lines 244-266):
```python
def _make_epoch_id(
    *,
    strategy_id: str,
    parameter_set_id: str,
    parameter_set_hash: str,
    opened_at_utc: datetime,
) -> str:
    _require_utc_aware(opened_at_utc, "opened_at_utc")
    return sha256_hex(
        {
            "strategy_id": strategy_id,
            "parameter_set_id": parameter_set_id,
            "parameter_set_hash": parameter_set_hash,
            "opened_at_utc": opened_at_utc,
        }
    )
```

**D-12 / WR-07 invariance:** Same shape as `epoch_id` — 64-hex lowercase, no floats, no naive datetimes. Token-hash prefix only ever appears in logs (full hash never logged).

**Tests mirror:** `tests/test_paper_freeze.py` lines 130-141 (epoch_id is 64-hex SHA256 lowercase assertion).

---

### `src/approval/binding.py` (service, request-response pure)

**Analog:** `src/paper/notify.py` `format_simulate` validation pattern (lines 158-197)

**Pattern** — Pure function that validates the binding tuple (signal_id + strategy_version + parameter_set_id/hash + plan_hash + expiry + chat + token hash) and returns either a valid `BindingCheck` frozen dataclass or raises with a canonical reason code. Fail-closed validation at every step, mirrors `format_simulate`'s `raise ValueError` posture for malformed inputs.

**Imports pattern** (mirrors `src/paper/notify.py` lines 39-62 — stdlib + Decimal only):
```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

import structlog
```

**Validation pattern** (from `format_simulate` lines 158-177):
```python
if not symbol:
    raise ValueError("symbol must be a non-empty string")
if not direction:
    raise ValueError("direction must be a non-empty string")
# ...
for field_name, value in (
    ("expiry_utc", expiry_utc),
    ("detected_at_utc", detected_at_utc),
):
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
```

**Reason-code vocabulary** (from `src/domain/enums.py` `RejectionReason` lines 122-156):
- `APPROVAL_EXPIRED` (line 143)
- `STALE_SETUP` (line 132)
- `INVALIDATED` (line 133)
- (new Phase-8 additions if planner adds them must be appended here per D-10)

**Binding-check gate order** (per CONTEXT D-01, fixed):
1. chat_id matches authorized chat
2. expiry_utc > now_utc
3. plan_hash matches the current TradePlan row
4. strategy_version + parameter_set_id + parameter_set_hash match
5. approval_token_hash matches via `hmac.compare_digest`

**Tests mirror:** `tests/test_paper_notify.py` lines 67-104 (byte-checked rendering + Decimal precision).

---

### `src/approval/replay.py` (service, idempotent resolution)

**Analog:** `src/paper/journal.py` `assemble_paper_record` (lines 164-377)

**Pattern** — Pure function `resolve_callback(*, short_id, action, chat_id, raw_token, now_utc, ...)` that (1) resolves short→full via the mapping table, (2) runs binding checks in fixed order, (3) on token-hash hit returns the existing Approval untouched (WR-07: PENDING ⟺ acted_at_utc is None), (4) else performs exactly one PENDING→decided transition. Returns a frozen `Approval` dataclass. Mirrors `assemble_paper_record`'s case-discrimination pattern (Case 1 filled / Case 2 skipped / Case 3 expired / fail closed).

**Imports pattern** (mirrors `src/paper/journal.py` lines 23-31):
```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.domain.approval import Approval
from src.domain.enums import ApprovalAction, ApprovalResult
```

**Case-discrimination pattern** (from `assemble_paper_record` lines 219-377):
```python
if skip_reason is not None and expired_at_utc is not None:
    raise ValueError("ambiguous outcome: skip_reason and expired_at_utc both set")
if skip_reason is not None and not skip_reason:
    raise ValueError("skip_reason must be a non-empty string")
# Case 1: filled in simulation
if approval is not None and order is not None and fill is not None:
    # ...
# Case 2: skipped
if skip_reason is not None:
    # ...
# Case 3: expired
if expired_at_utc is not None:
    # ...
# No valid case matched — fail closed
raise ValueError("assemble_paper_record requires either (approval + order + fill) ...")
```

**WR-07 coherence invariant** (from `src/domain/approval.py` lines 66-70):
```python
if self.status == ApprovalResult.PENDING and self.acted_at_utc is not None:
    raise ValueError("PENDING approval must have acted_at_utc=None")
if self.status != ApprovalResult.PENDING and self.acted_at_utc is None:
    status_name = getattr(self.status, "value", self.status)
    raise ValueError(f"{status_name} approval must set acted_at_utc")
```

**Replay-path contract:** When `approval_token_hash` matches an existing Approval, the function MUST return that exact Approval (byte-equal) without re-running the PENDING→decided transition.

**Tests mirror:** `tests/test_paper_notify.py` lines 113-174 (FakeBot pattern — adapt to FakeApprovalStore that records transition calls and asserts replay returns existing).

---

### `src/reconcile/compare.py` (service, event-driven + REST snapshot)

**Analog:** `src/paper/resync.py` `backfill_missed_closes` (lines 134-277)

**Pattern** — Pure function `compare_to_truth(*, local_intent, open_normal_orders, open_algo_orders, positions) → ReconcileDiff` that diffs three local-intent sets against three exchange-truth sets (snake_case field names — mirror the SDK method names exactly). Returns a frozen `ReconcileDiff` carrying `orphan_protectives: tuple[OrderIntent, ...]` (orphan list to sweep) and `divergences: tuple[Divergence, ...]` (orphan divergences to drive SAFE_MODE).

**Imports pattern** (mirrors `src/paper/resync.py` lines 17-29):
```python
from __future__ import annotations
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import structlog
```

**Paged-fetch + diff pattern** (from `backfill_missed_closes` lines 134-277):
```python
async def backfill_missed_closes(
    adapter: AdapterLike,
    *,
    symbol: str,
    interval: str,
    last_close_utc: datetime,
    now_utc: datetime,
) -> tuple[list[Kline], list[dict[str, Any]]]:
    # Normalize to UTC for arithmetic (callers may pass any tz-aware
    # datetime; the adapter's ms math is UTC-anchored).
    if last_close_utc.tzinfo is None:
        raise ValueError("last_close_utc must be UTC-aware")
    # ... set-difference against contiguous expectation ...
    gaps: list[dict[str, Any]] = []
    for expected_open in expected_open_times:
        if expected_open not in closed_open_times:
            # ... append gap dict ...
    return closed, gaps
```

**Compare function shape (Phase 8):**
- Three REST snapshots (`open_normal_orders`, `open_algo_orders`, `positions`)
- Local intent: `local_open_orders` (PLANNED/NEW/PARTIALLY_FILLED) + `local_open_algos` + `local_open_positions`
- Set diff:
  - `orphan_protectives` = local algo protectives with no matching local position AND no exchange position
  - `orphan_entries` = local orders with no matching exchange order (cancel/disappeared)
  - `unsynced_protectives` = exchange algo protectives with no local intent (suspicious — drives SAFE_MODE)
  - `unsynced_positions` = exchange positions with no local intent (suspicious — drives SAFE_MODE)
- Returns `ReconcileDiff` (frozen dataclass, mirror of `FreezeCheckOutcome` lines 178-205 in freeze.py)

**Tests mirror:** `tests/test_paper_resync.py` lines 77-99 (`FakeAdapter` pattern) + golden-fixture loader pattern (lines 36-49).

---

### `src/reconcile/sweeper.py` (service, cancel-only event-driven)

**Analog:** `src/paper/supervisor.py` `on_disconnect` (lines 169-194)

**Pattern** — Class `OrphanSweeper` that holds a reference to a canceller Protocol (matching the cancel-only posture — never places orders) and a journal-callback. `sweep(*, reconcile_diff, position_verifier) → SweepOutcome` iterates `reconcile_diff.orphan_protectives`, double-checks via `position_verifier` (two consecutive zero-position reads OR position + order-truth agreement per CONTEXT Pitfall 3), cancels via the adapter, and journals each sweep as a `JournalEvent` with `event_type="ORPHAN_SWEEP"`.

**Imports pattern** (mirrors `src/paper/supervisor.py` lines 21-37):
```python
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import structlog
import tenacity
```

**Bounded-retry posture** (mirrors supervisor.py `SUPERVISOR_*` constants lines 45-48):
```python
SWEEPER_MAX_ATTEMPTS: int = 3
SWEEPER_MAX_DELAY_SECONDS: int = 30
SWEEPER_WAIT_MULTIPLIER_SECONDS: int = 1
SWEEPER_WAIT_MAX_SECONDS: int = 10
```

**Adapter Protocol shape** (mirrors `WsAdapterLike` / `RestAdapterLike` lines 56-83):
```python
class CancellerLike(Protocol):
    """Anything that quacks like the project adapter for order/algo cancel."""

    async def cancel_normal_order(self, *, symbol: str, orig_client_order_id: str) -> object: ...

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> object: ...
```

**Per-symbol try/except isolation + journal-first** (mirrors supervisor.py lines 262-291):
```python
try:
    closes, gaps = await backfill_missed_closes(...)
except Exception as exc:
    # Per-symbol isolation: one failing pair journals
    # its gap and the remaining pairs still dispatch.
    gap = {
        "symbol": symbol,
        "data_class": f"paper-{interval}",
        "expected_utc": last,
        "observed_utc": now,
        "reason": f"backfill_exception:{type(exc).__name__}",
    }
    outage_gaps.append(gap)
```

**Tests mirror:** `tests/test_paper_supervisor_backfill.py` lines 46-92 (`_FakeWsAdapter` / `_FakeRestAdapter` pattern).

---

### `src/reconcile/safe_mode.py` (service, state-machine compose)

**Analog:** `src/risk/gating.py` `evaluate_risk` (lines 27-122) + `src/risk/portfolio.py` `check_portfolio` (lines 152-350)

**Pattern** — Functions `enter_safe_mode(*, reason: SafeModeReason, journal) → None` and `exit_safe_mode(*, reconcile_snapshot, journal) → None`. Exit requires a fresh, clean three-source compare snapshot per CONTEXT Pitfall 4. Composes with `evaluate_risk` so any new entry path checks `SystemMode.SAFE_MODE` first and short-circuits to NO_TRADE.

**Imports pattern** (mirrors `src/risk/gating.py` lines 9-24):
```python
from __future__ import annotations
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import structlog

from src.domain.enums import SystemMode
```

**First-failure-wins pipeline** (mirrors `check_portfolio` lines 152-350):
```python
def check_portfolio(
    *,
    sized: SizedResult,
    candidate_symbol: str,
    candidate_position_side: str,
    open_positions: Sequence[OpenPosition],
    daily_loss_quote: Decimal | None,
    parameter_set: dict[str, Any],
    now_utc: datetime,
    ttl: timedelta,
    positions_reconciled: bool = True,
    constraint_observed_at_utc: datetime | None = None,
) -> PortfolioVerdict:
    # ... validate inputs ...
    # Sort positions deterministically (Pitfall 4 — non-deterministic
    # iteration). Sort by (symbol, position_side) so two position lists
    # with different insertion orders yield identical verdicts.
    sorted_positions = sorted(open_positions, key=lambda p: (p.symbol, p.position_side))
    # ... gates 1..4 ...
    # All gates passed.
    return PortfolioVerdict(...)
```

**SystemMode vocabulary** (from `src/domain/enums.py` lines 107-119):
```python
class SystemMode(str, Enum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    LIVE_APPROVAL = "LIVE_APPROVAL"
    SAFE_MODE = "SAFE_MODE"
    LIVE_AUTONOMOUS_DISABLED = "LIVE_AUTONOMOUS_DISABLED"
```

**SAFE_MODE composition:** SAFE_MODE blocks new entries (mirrors DAILY_STOP_BLOCK behavior at `check_portfolio` lines 336-342), but monitoring + reconciliation continue.

**Tests mirror:** Golden-fixture pattern from `tests/test_paper_freeze.py` lines 192-242 (clean tick → outcome JSONL).

---

### `src/ops/drills.py` (service, test harness + journaled outcomes)

**Analog:** `src/ops/backup.py` (full module — drill precedent at module docstring lines 17-29) + `src/paper/freeze.py` `check_registry_unchanged` (lines 416-513)

**Pattern** — Function `run_drill(name: DrillName, *, inject: FaultInjection, assert_outcome: AssertionFn) → DrillOutcome`. Each of 8 RUNBOOK drills declares: fault to inject (in-memory fake / recorded fixture — never real unprotected exposure), expected SAFE_MODE/sweep/journal outcome, and the `JournalEvent.event_type` it emits. Drill log (ordered `JournalEvent`s + outcome summary) is the OPS-01 acceptance artifact.

**Imports pattern** (mirrors `src/paper/freeze.py` lines 56-73):
```python
from __future__ import annotations
import dataclasses
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

import structlog
```

**Frozen-dataclass outcome pattern** (mirrors `FreezeCheckOutcome` lines 178-205):
```python
@dataclass(frozen=True)
class FreezeCheckOutcome:
    pinned_epoch: StreamEpoch
    current_epoch: StreamEpoch
    halted_epoch: StreamEpoch | None
    halted: bool
    halted_reason: str
    diff_entry: DiffLogEntry
```

**JSONL drill-log writer** (mirrors `_append_diff_entry` lines 516-524):
```python
def _append_diff_entry(path: Path, entry: DiffLogEntry) -> None:
    """Append one JSONL line to the diff log, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(entry.to_jsonl() + "\n")
```

**Drill names vocabulary** (8 from RUNBOOK §§2-12):
- UNPROTECTED
- ORPHAN
- DUPLICATE
- API_DOWN
- STALE_FEED
- DB_FAILURE
- MANUAL_CLOSE
- RESTORE

**Tests mirror:** `tests/test_paper_freeze.py` lines 250-335 (registry diff → new epoch + halted epoch + diff-log JSONL assertion).

---

### `src/adapters/telegram_notify.py` (EXTEND) (adapter, callback intake + send)

**Analog:** existing `src/adapters/telegram_notify.py` (lines 45-119) — extend in place

**Pattern** — Add (1) `parse_callback_data(data: str) → CallbackIntent | None` that strictly parses `^(APR|SKP):[0-9a-f]{32}$`, (2) `build_approval_keyboard(signal_id) → InlineKeyboardMarkup` extending `build_simulate_keyboard`, (3) the callback receiver function as a separate function that the PTB `Application` registers via `CallbackQueryHandler`. The receiver does authorized-chat gate FIRST, journals receipt, then calls into `src/approval/replay.py:resolve_callback`.

**Existing imports pattern** (lines 20-25):
```python
from __future__ import annotations
import hashlib
from typing import Protocol

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
```

**TelegramBot Protocol seam** (lines 28-42 — DO NOT BREAK):
```python
class TelegramBot(Protocol):
    """Structural type for the Bot.send_message surface we consume."""

    async def send_message(
        self,
        *,
        chat_id: str | int,
        text: str,
        reply_markup: InlineKeyboardMarkup,
    ) -> object: ...
```

**Short-id scheme extension** (lines 68-100):
```python
def _short_signal_id(signal_id: str) -> str:
    """Compress a signal id to 32 hex chars (CR-05)."""
    return hashlib.sha256(signal_id.encode("utf-8")).hexdigest()[:32]


def build_simulate_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    short = _short_signal_id(signal_id)
    sim_data = f"SIM:{short}"
    skip_data = f"SKIP:{short}"
    assert len(sim_data.encode("utf-8")) <= 64
    assert len(skip_data.encode("utf-8")) <= 64
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("SIMULATE-recorded", callback_data=sim_data),
                InlineKeyboardButton("SKIP (Phase 8)", callback_data=skip_data),
            ]
        ]
    )
```

**Extension invariants:**
- 64-byte limit must hold for `APR:` + 32 hex chars = ≤64
- Short-id derived via `hashlib.sha256(signal_id.encode("utf-8")).hexdigest()[:32]` — same scheme
- Only `src/adapters/telegram_notify.py` imports `python-telegram-bot` — assertion test from `tests/test_paper_notify.py` lines 264-280 enforces this

**Tests mirror:** `tests/test_paper_notify.py` lines 214-280 (no-Application-poller / no-inbound-handler-mutates-approval / only-telegram-importer guards).

---

### `src/adapters/binance_usdm.py` (EXTEND) (adapter, REST reconciler)

**Analog:** existing `src/adapters/binance_usdm.py` `klines` + `exchange_info` methods (lines 214-453)

**Pattern** — Add 5 new async methods to `BinanceUsdmAdapter`:
1. `current_all_open_orders(symbol: str | None = None) -> list[OpenOrder]` — calls `self._sdk.rest_api.current_all_open_orders` (verified method name per RESEARCH §Pattern 3)
2. `current_all_algo_open_orders(symbol: str | None = None) -> list[OpenAlgoOrder]` — calls `self._sdk.rest_api.current_all_algo_open_orders`
3. `position_information_v3(symbol: str | None = None) -> list[PositionRisk]` — calls `self._sdk.rest_api.position_information_v3`
4. `cancel_order(*, symbol: str, orig_client_order_id: str) -> object` — calls `self._sdk.rest_api.cancel_order`
5. `cancel_algo_order(*, symbol: str, client_algo_id: str) -> object` — calls `self._sdk.rest_api.cancel_algo_order`
6. `query_algo_order(*, client_algo_id: str) -> AlgoOrder` — calls `self._sdk.rest_api.query_algo_order` (no-blind-retry probe per EXECUTION_SPEC §10)

All new methods return frozen dataclasses (mirrors `Kline` / `SymbolFilters` at lines 49-123) and project SDK response models — never leak SDK types into the domain layer.

**Existing pattern** (from `klines` lines 214-242):
```python
async def klines(
    self,
    symbol: str,
    interval: str,
    start_ms: int | None = None,
    end_ms: int | None = None,
    limit: int = 1500,
) -> list[Kline]:
    """Fetch one page of klines."""
    response = await asyncio.to_thread(
        self._sdk.rest_api.kline_candlestick_data,
        symbol=symbol,
        interval=interval,
        start_time=start_ms,
        end_time=end_ms,
        limit=limit,
    )
    raw = response.data()
    return [_row_to_kline(symbol, interval, row) for row in raw]
```

**Flag-never-fabricate pattern** (from `open_interest` lines 246-259):
```python
if oi.time is None or oi.open_interest is None:
    raise ValueError(f"open_interest response missing fields: {oi!r}")
```

**Rate-limit predicate** (from `is_rate_limit_error` lines 146-158 — extend to cover new methods):
```python
def is_rate_limit_error(exc: BaseException) -> bool:
    if isinstance(exc, _RATE_LIMIT_ERRORS):
        return True
    cls_name = type(exc).__name__
    return "TooManyRequests" in cls_name or "RateLimit" in cls_name
```

**Tests mirror:** `tests/test_paper_resync.py` lines 77-99 (`FakeAdapter` pattern — records calls + returns configured page).

---

### `src/db/models.py` (EXTEND) (model, ORM persistence)

**Analog:** existing `src/db/models.py` `ApprovalRow` (lines 270-299) + `JournalEventRow` (lines 423-450)

**Pattern** — Add `ShortIdMappingRow` table with `short_id` PK + `signal_id` FK + `trade_plan_id` FK + `created_at_utc`. `JournalEventRow` already covers the drill-outcome event_type (line 438 `event_type: Mapped[str]` is a String(64) — no schema change needed; new event_types "DRILL_OUTCOME" / "ORPHAN_SWEEP" / "RECONCILE_DIVERGENCE" / "SAFE_MODE_ENTER" / "SAFE_MODE_EXIT" land as plain strings).

**Single-Base convention** (lines 42-48):
```python
class Base(DeclarativeBase):
    """Single declarative base for every model in `src/db/`."""
```

**ApprovalRow convention** (lines 270-299):
```python
class ApprovalRow(Base):
    __tablename__ = "approvals"

    approval_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    trade_plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    signal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    approval_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acted_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

**Add row + mapper:**
- `ShortIdMappingRow` table with PK `short_id` (String(64) — covers `sha256(signal_id)[:32]` prefix + discriminator), FK `signal_id` (String(128)), FK `trade_plan_id` (String(128)), `created_at_utc` (DateTime(timezone=True))
- Add `short_id_mapping_to_row` / `short_id_mapping_from_row` to `src/db/mappers.py` (mirrors `approval_to_row` / `approval_from_row` lines 159-201)

**Tests mirror:** `tests/test_domain_mappers.py` + `tests/test_domain_mappers_pg.py` (round-trip property tests).

---

### `src/db/alembic/versions/0003_callback_mapping.py` (NEW migration)

**Analog:** `src/db/alembic/versions/0002_domain_registry.py` (lines 96-241)

**Pattern** — Single new table for short→full mapping with FK indexes. Reverses in downgrade.

**Migration shape** (mirrors 0002 lines 96-115):
```python
"""Short-id → full-id mapping table — Phase 8 callback intake (D-02).

Adds the `short_id_mappings` table that lets Telegram callbacks
(`APR:<short32>`) resolve to the full SignalId + TradePlan. Written
in the same transaction as the Approval row (CONTEXT D-02), unique
on short_id so a replayed callback cannot double-map.

Conventions (same as 0001/0002):
  - All timestamps TIMESTAMPTZ (UTC).
  - PKs are content-hash IDs (D-03).
  - Nullable columns ONLY for "transition never happened" timestamps (D-11).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_callback_mapping"
down_revision = "0002_domain_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "short_id_mappings",
        sa.Column("short_id", sa.String(length=64), nullable=False),
        sa.Column("signal_id", sa.String(length=128), nullable=False),
        sa.Column("trade_plan_id", sa.String(length=128), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("short_id"),
    )
    op.create_index(
        "ix_short_id_mappings_signal_id",
        "short_id_mappings",
        ["signal_id"],
        unique=False,
    )
    op.create_index(
        "ix_short_id_mappings_trade_plan_id",
        "short_id_mappings",
        ["trade_plan_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_short_id_mappings_trade_plan_id", table_name="short_id_mappings")
    op.drop_index("ix_short_id_mappings_signal_id", table_name="short_id_mappings")
    op.drop_table("short_id_mappings")
```

**Tests mirror:** `tests/test_paper_freeze.py` lines 372-442 (CLI round-trip with pinned-state file + diff-log JSONL).

---

### `tests/fixtures/phase8/` (NEW golden fixtures)

**Analog:** `tests/fixtures/phase7/pinned_epoch_clean/` (input.json + expected.json pair)

**Pattern** — Mirror Phase-7 convention: each case directory contains `input.json` (test inputs) + `expected.json` (canonical outputs / assertions). Phase-8 cases:
- `replay_5x/` — 5 duplicate APPROVE callbacks, expect exactly one state transition
- `stale_expired/` — callback for expired plan, expect `APPROVAL_EXPIRED` reason code
- `stale_superseded/` — callback for SUPERSEDED plan, expect rejection
- `orphan_protective/` — injected orphan protective, expect sweep + journal row + reconcile diff
- `divergence_safe_mode/` — injected local-vs-truth divergence, expect SAFE_MODE transition + journal
- `id_determinism/` — same plan hash + role → identical `client_order_id` / `algo_client_id` across retries/restarts
- `drill_<name>/` — one directory per RUNBOOK drill (8 total)

**Loader pattern** (from `tests/test_paper_freeze.py` lines 47-58):
```python
PHASE8_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "phase8"


def _load_input(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "input.json").read_text(encoding="utf-8"))


def _load_expected(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))


def _parse_utc(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError(f"naive datetime in fixture: {raw!r}")
    return value.astimezone(UTC)
```

---

### `tests/test_approval_replay.py` (NEW) (test, replay determinism)

**Analog:** `tests/test_paper_notify.py` `_FakeBot` (lines 113-132) + golden-fixture loader

**Pattern** — Uses fake `ApprovalStore` Protocol that records transition calls (mimics `_FakeBot.calls`) and golden-fixture input/expected pairs. Asserts:
1. 5× duplicate callback = exactly one transition (count `store.transitions == 1`)
2. WR-07 coherence holds (PENDING returns same Approval, transitioned returns same Approval)
3. Stale plan (expired/superseded/plan-hash mismatch) → `APPROVAL_EXPIRED` / `STALE_SETUP` reason code
4. Notify-failure keeps approval PENDING (never auto-approve per D-05 extended)

**Fake store pattern** (mirrors `_FakeBot` lines 113-132):
```python
class _FakeApprovalStore:
    def __init__(self) -> None:
        self.transitions: list[tuple[str, ApprovalResult]] = []
        self.by_token_hash: dict[str, Approval] = {}

    def get_by_token_hash(self, token_hash: str) -> Approval | None:
        return self.by_token_hash.get(token_hash)

    def insert_transition(
        self, *, approval_id: str, result: ApprovalResult, now_utc: datetime
    ) -> None:
        self.transitions.append((approval_id, result))
```

---

### `tests/test_approval_message.py` (NEW) (test, format + callback_data byte-check)

**Analog:** `tests/test_paper_notify.py` `test_format_simulate_renders_all_12_aprv01_fields` (lines 67-104)

**Pattern** — Byte-checks the approval message rendering (mirrors format_simulate test). Asserts all 12 APRV-01 fields present + `callback_data` ≤ 64 bytes + button labels match Phase-8 wire format (`APPROVE` / `SKIP`).

**Test structure** (mirrors lines 67-104):
```python
def test_format_approval_renders_all_12_aprv01_fields() -> None:
    from src.paper.notify import format_simulate  # if extended to approvals

    payload = _make_payload()
    text = format_simulate(**payload)
    assert "BTCUSDT" in text  # 1. symbol
    assert "LONG" in text  # 2. direction
    # ... 12 field assertions ...
    assert text.startswith("APPROVAL ")  # Phase-8 marker
```

**64-byte assert** (from `src/adapters/telegram_notify.py` lines 99-100):
```python
assert len(sim_data.encode("utf-8")) <= 64
assert len(skip_data.encode("utf-8")) <= 64
```

---

### `tests/test_reconcile.py` (NEW) (test, reconciler fake-exchange scenarios)

**Analog:** `tests/test_paper_resync.py` `FakeAdapter` (lines 77-99) + injected-fault pattern

**Pattern** — Fake `BinanceUsdmAdapter` exposes 3 query methods + 2 cancel methods as configured async functions. Tests inject:
1. Orphan protective scenario: local algo protective + zero local position + zero exchange position → expect sweep + cancel call + journal
2. Divergence scenario: exchange algo protective with no local intent → expect SAFE_MODE transition (no cancel)
3. Clean tick: local + exchange match → expect empty diff, no sweep, no SAFE_MODE
4. Position-read race: first read returns non-zero, second returns zero → no premature sweep

**Fake adapter pattern** (mirrors `FakeAdapter` lines 77-99):
```python
class FakeReconcileAdapter:
    """Fake Binance reconciler adapter."""

    def __init__(self) -> None:
        self.cancel_calls: list[dict[str, Any]] = []
        self._open_orders: list[Any] = []
        self._open_algos: list[Any] = []
        self._positions: list[Any] = []

    async def current_all_open_orders(self, *, symbol: str | None = None) -> list[Any]:
        return list(self._open_orders)

    # ... similar for open_algos / position_information_v3 ...

    async def cancel_algo_order(self, *, symbol: str, client_algo_id: str) -> object:
        self.cancel_calls.append({"symbol": symbol, "client_algo_id": client_algo_id})
        return {"status": "CANCELED"}
```

---

### `tests/test_order_ids.py` (NEW) (test, ID determinism property)

**Analog:** `tests/test_paper_freeze.py` epoch_id golden assertion (lines 130-141)

**Pattern** — Property-style test: same inputs (plan_hash + role_code) always produce identical `client_order_id` / `algo_client_id` outputs. Asserts:
1. Same plan + role → same ID across N invocations
2. Different role → different ID (never collide)
3. Restart simulation (re-instantiate the derive function) → same ID
4. Cross-role uniqueness: 1000 random plan hashes × 4 roles produce 4000 unique IDs

**Test structure** (mirrors freeze.py lines 130-141):
```python
def test_derive_client_order_id_is_deterministic() -> None:
    from src.approval.order_ids import derive_client_order_id

    plan_hash = "a" * 64
    role = "ENTRY"
    ids = {derive_client_order_id(plan_hash=plan_hash, role_code=role) for _ in range(100)}
    assert len(ids) == 1, f"expected 1 ID, got {len(ids)}: {ids}"


def test_derive_client_order_id_role_codes_never_collide() -> None:
    from src.approval.order_ids import derive_client_order_id

    plan_hash = "a" * 64
    id_entry = derive_client_order_id(plan_hash=plan_hash, role_code="ENTRY")
    id_stop = derive_client_order_id(plan_hash=plan_hash, role_code="STOP_LOSS")
    id_tp1 = derive_client_order_id(plan_hash=plan_hash, role_code="TAKE_PROFIT_1")
    assert len({id_entry, id_stop, id_tp1}) == 3
```

---

### `tests/test_drills.py` (NEW) (test, drill harness)

**Analog:** `tests/test_paper_freeze.py` `test_check_registry_unchanged_opens_new_epoch_on_diff` (lines 250-335)

**Pattern** — For each of 8 RUNBOOK drills: inject the fault via fake adapter, run `drills.run_drill(name, inject=..., assert_outcome=...)`, assert the expected SAFE_MODE transition + journal event + (for sweep drills) cancel call. Asserts the drill log JSONL line carries `event_type="DRILL_OUTCOME"`.

**Test structure** (mirrors lines 250-335):
```python
def test_drill_orphan_sweeps_and_journals() -> None:
    from src.ops.drills import run_drill, DrillName
    fake_adapter = FakeReconcileAdapter()  # with orphan protective pre-loaded
    fake_journal = _FakeJournal()
    outcome = run_drill(
        name=DrillName.ORPHAN,
        inject={"adapter": fake_adapter},
        assert_outcome=lambda d: d.sweeps == 1,
    )
    assert len(fake_adapter.cancel_calls) == 1
    journal_row = next(r for r in fake_journal.rows if r["event_type"] == "DRILL_OUTCOME")
    assert journal_row["payload_json"] contains "ORPHAN"
```

## Shared Patterns

### Authentication (one-time token + hash + constant-time compare)

**Source:** `src/paper/freeze.py` `_make_epoch_id` (lines 244-266) — pattern of stdlib-only SHA-256 content hashing; extend to one-time token issue/hash/verify.

**Apply to:** All approval callback resolution (`src/approval/replay.py`, `src/approval/binding.py`).

```python
import hashlib
import hmac
import secrets

# Issue: CSPRNG-generated token, never persisted.
raw_token = secrets.token_urlsafe(32)

# Hash: SHA-256 hex of the UTF-8 encoded token.
stored_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

# Verify: constant-time compare defeats timing probing.
ok = hmac.compare_digest(stored_hash, hashlib.sha256(presented.encode("utf-8")).hexdigest())
```

**Log policy:** Token-hash prefixes only (≤16 chars) appear in logs/journals. Raw tokens never appear in logs.

### Fail-closed Validation (D-12 + WR-07)

**Source:** `src/paper/notify.py` `format_simulate` (lines 158-197) — fail-closed validators reject empty/non-Decimal/non-UTC inputs loudly.

**Apply to:** All approval-binding / replay-resolution functions; all reconciler inputs.

```python
if not symbol:
    raise ValueError("symbol must be a non-empty string")
for field_name, value in (
    ("expiry_utc", expiry_utc),
    ("detected_at_utc", detected_at_utc),
):
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
```

### UTC-aware + Decimal-only at Boundaries (D-12)

**Source:** `src/domain/approval.py` `_require_utc_aware` (lines 20-27) — pattern reused across all domain entities.

**Apply to:** Every new datetime field in approval/callback/reconcile/safe_mode/drills.

```python
def _require_utc_aware(value: datetime, field_name: str) -> None:
    """Reject naive and non-UTC datetimes (D-12)."""
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be UTC-aware, got naive datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC, got offset {value.utcoffset()}")
```

### Adapter-Boundary Isolation (SDK / PTB containment)

**Source:** `src/adapters/telegram_notify.py` (full file, 119 lines) — only module allowed to import `python-telegram-bot`. `src/adapters/binance_usdm.py` (full file, 508 lines) — only module allowed to import the Binance SDK.

**Apply to:** Phase 8 callback receiver (extend `telegram_notify.py`) + reconciler REST methods (extend `binance_usdm.py`). New `src/approval/` + `src/reconcile/` + `src/ops/drills.py` import NOTHING from SDKs/PTB — they consume Protocol-typed adapters.

**Enforcement test:** `tests/test_paper_notify.py` lines 264-280 — grep all `src/*.py` for `from telegram import` / `import telegram`; assert exactly `[src/adapters/telegram_notify.py]`. Mirror this test for the Binance SDK importer set.

### Journal-First Ordering (D-05 extended)

**Source:** `src/paper/notify.py` `notify_simulate` (lines 205-335) — caller commits journal row BEFORE invoking notify; outcome journaled AFTER.

**Apply to:** Every callback receipt (journal BEFORE `resolve_callback`); every orphan sweep (journal BEFORE cancel call); every SAFE_MODE transition (journal BEFORE state change).

**Caller-supplied callback pattern** (from lines 205-217):
```python
async def notify_simulate(
    *,
    bot: TelegramBot,
    chat_id: str | int,
    payload: dict[str, Any],
    on_outcome: Callable[[NotifyOutcome], None],
) -> NotifyOutcome:
    """Send a SIMULATE notification with journal-first ordering (D-05).
    The caller MUST have committed the journal row BEFORE invoking
    this function. The notify function sends via tenacity-bounded
    retries, then invokes `on_outcome` with the `NotifyOutcome`.
    """
```

### Bounded Retry (D-05 fail-closed)

**Source:** `src/paper/resync.py` `RESYNC_*` constants (lines 45-48) + `src/paper/notify.py` `NOTIFY_*` constants (lines 111-114) — bounded attempts + wall-clock cap + jitter; transient-only retry filter (never retries `ValueError`/`KeyError`/`TypeError`).

**Apply to:** Adapter cancel calls (sweeper), REST reconciler queries, Telegram sends. Module-level named constants so the operator can audit them before live enablement.

```python
RESYNC_MAX_ATTEMPTS: int = 7
RESYNC_MAX_DELAY_SECONDS: int = 120
RESYNC_WAIT_MULTIPLIER_SECONDS: int = 1
RESYNC_WAIT_MAX_SECONDS: int = 60


def _is_transient(exc: BaseException) -> bool:
    return not isinstance(exc, (ValueError, KeyError, TypeError))


retry = tenacity.retry_if_exception(_is_transient)
stop = tenacity.stop_after_attempt(RESYNC_MAX_ATTEMPTS) | tenacity.stop_after_delay(
    RESYNC_MAX_DELAY_SECONDS
)
wait = tenacity.wait_random_exponential(
    multiplier=RESYNC_WAIT_MULTIPLIER_SECONDS,
    max=RESYNC_WAIT_MAX_SECONDS,
)
```

### Content-Hash ID Derivation (D-03 byte-stability)

**Source:** `src/domain/canonical.py` `sha256_hex` (lines 87-89) + `src/domain/ids.py` `make_signal_id` (lines 19-46) + `derive_child_id` (lines 49-55).

**Apply to:** Order/algo-client ID derivation (`src/approval/order_ids.py` or `src/execution/order_ids.py` per planner discretion — both work; planner picks).

```python
from src.domain.canonical import sha256_hex


def derive_client_order_id(*, plan_hash: str, role_code: str) -> str:
    digest = sha256_hex(
        {
            "plan_hash": plan_hash,
            "role_code": role_code,
        }
    )
    return f"tr8{digest[:20]}{role_code}"  # exact lengths are planner's discretion
```

### Single-Base ORM Discipline (D-02)

**Source:** `src/db/models.py` `Base` (lines 42-48) + `src/db/alembic/env.py` `target_metadata = Base.metadata` (line 39).

**Apply to:** `ShortIdMappingRow` (new) added to `src/db/models.py` — same `Base`, same `Mapped[...]` style, same TIMESTAMPTZ/NUMERIC(38,18)/JSON-as-TEXT conventions. Migrations via `alembic revision --autogenerate` against `target_metadata = Base.metadata`.

### Tenacity-Bounded Retry on Adapter Calls

**Source:** `src/paper/resync.py` `_fetch_page_with_retry` (lines 198-202) — tenacity `AsyncRetrying` with `reraise=True` for clean exception propagation.

**Apply to:** `current_all_open_orders` / `current_all_algo_open_orders` / `position_information_v3` / `cancel_order` / `cancel_algo_order` adapter calls inside the reconciler and sweeper.

```python
async def _fetch_page_with_retry(cursor_ms: int) -> list[Kline]:
    async for attempt in decorator:
        with attempt:
            return await _fetch_page(cursor_ms)
    raise RuntimeError("unreachable: tenacity.AsyncRetrying exhausted without reraise")
```

## No Analog Found

Files with no close match (planner should use RESEARCH.md patterns + Context7 docs):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none — all 17 mapped files have at least role-match analogs) | — | — | The codebase is rich enough across Phases 3/5/7 that every Phase 8 slice has a close in-repo analog. Planner can copy structure from `src/paper/freeze.py` (halt-and-monitor pattern) for SAFE_MODE, from `src/paper/resync.py` (compare + journal) for reconciler, and from `src/paper/notify.py` (format + send) for APPROVE/SKIP payloads. |

## Metadata

**Analog search scope:** `src/`, `tests/`, `tests/fixtures/`
**Files scanned:** 57 source files + 47 test files + 7 fixture directories
**Pattern extraction date:** 2026-09-27
**Tracked-source verification:** all 25 analog paths verified via `git ls-files` (non-empty output) — every analog is a tracked source file in the repository root (not a gitignored mirror).
