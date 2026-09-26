# Phase 7: Paper Forward Observation - Research

**Researched:** 2026-09-26
**Domain:** Realtime paper-trading forward-observation loop (Binance WS ingestion → closed-candle evaluation → attributed journaling → no-tuning soak proof)
**Confidence:** HIGH

## Summary

Phase 7 builds the schedule long pole: a single-asyncio-loop realtime paper engine that subscribes to Binance USDⓈ-M kline WS streams, evaluates **closed candles only** through the identical Phase-4 core (`compute_features`/`evaluate`/`plan`) and Phase-5 risk (`size_position`/`quantize`/`check_portfolio`/`evaluate_risk`) functions with backtest fill/cost semantics (`resolve_intrabar`, registry-bound `CostModel`), journals every record with three-way attribution in PostgreSQL (+ Parquet mirror), sends SIMULATE-style Telegram notifications, and proves zero tuning on the running stream via a pinned-registry epoch + diff monitor over a 3–6-month wall-clock envelope.

The good news: every hard dependency already exists in-repo. The WS surface was verified live this session against the installed SDK (`DerivativesTradingUsdsFuturesWebSocketStreams.kline_candlestick_streams`, SDK 17.4.0); the REST resync path exists (`BinanceUsdmAdapter.klines`); the gap-journaling precedent exists (`CollectorGap` + `CollectorWatermark`); the journal tables exist (seven entities on a single Base); the freeze-proof authority exists (`load_parameter_set` + `assert_cost_model_binds_registry`). The one gap: `python-telegram-bot` is in the canonical stack but **not** in `pyproject.toml`/`uv.lock` — the planner must add it behind a human-verify checkpoint.

**Primary recommendation:** Build a new dependency-free `src/paper/` package (loop + WS supervisor + resync + journal + freeze-monitor, tracer-first) that calls the canonical engine functions identically, journals gaps with the collector's flag-never-fabricate discipline, pins the registry hash at stream start, and emits SIMULATE notifications via `Bot.send_message` + `InlineKeyboardMarkup` (no `Application` poller needed for send-only Phase 7).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Single-asyncio-loop WS ingestion via the official `binance-sdk-derivatives-trading-usds-futures` WS Streams surface behind `src/adapters/` (never imported by domain/core/risk/backtest/paper-core), with REST kline resync on reconnect and warm-up gates reusing the Phase-4 validity flags (long-warm-up features report invalid until history suffices; invalid → NO_TRADE). Gaps are journaled with explicit gap records and flagged per the Phase-2 D-09 / Phase-4 D-04 flag-never-fabricate rule — never synthesized candles, never fabricated signals. Uncertain/stale feed state fails closed to NO_TRADE with reason code (Phase-5 D-04 posture extended to the feed).
- **D-02:** The paper loop calls the identical functions the backtest executes: `src/core/` feature/strategy/planner evaluation on closed candles, `src/risk/` sizing + quantization + portfolio gates, and backtest fill/cost semantics for simulated fills (1m-intrabar SL-first resolution, registry-versioned costs from run #1 — Phase-6 D-01/D-02). No paper-local setup logic, no simplified sizing, no cost-free path. Paper-vs-backtest divergence on overlapping history is an acceptance gate, reported as an incident and fixed in the engine, never patched at the call site. All exchange-sensitive arithmetic stays `Decimal`, tick/qty-step aware; UTC internally, Asia/Ho_Chi_Minh at the display edge.
- **D-03:** Every paper record carries the canonical identity (strategyVersion + parameterSetId + parameterSetHash + experiment linkage per CONFIGURATION §7 / RESEARCH_PROTOCOL §5, SignalId/plan hash per Phase-3/Phase-4) plus the full timestamp lineage signal/approve(simulated)/order(fill-simulated)/fill. Attribution splits three ways: system-generated, user-executed/simulated-execution (incl. approval-delay modeling), and opportunity (skipped/expired plans retained with reason codes — never dropped). Operational rows land in PostgreSQL on the Phase-3 seven-entity shapes (+ JournalEvent gap/attribution rows; single-Base ORM + offline parity-gate discipline for any migration); Parquet extracts mirror the journal for DuckDB/Polars analysis.
- **D-04:** The soak pins its registry version at start (parameterSetId + parameterSetHash, cost keys included via the 07.1 binding gate). Any registry diff against the pinned set halts the stream's evidence claim: the change is rejected-or-logged with a new stream epoch, and evidence windows are per-epoch. A soak monitor (registry diff check, CI or scheduled job at planner discretion) proves zero tuning on the paper stream; the PAPER-03 acceptance artifact is the diff log showing the pinned hash untouched for the whole window. Research may continue offline on other sets; only the pinned set's stream counts as forward evidence.
- **D-05:** Live-5 universe (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT) with the research universe reported separately if ever used; 4H regime + 1H setup closed-candle evaluation (1m for simulated fill resolution only, per backtest semantics). Telegram sends SIMULATE-style read-only notifications carrying the Phase-8 APRV-01 field set (symbol, direction, setup, entry, SL, TP(s), RR, risk, expiry, invalidation, exposure, reason codes) — APPROVE/SKIP idempotency hardening stays Phase 8; paper approvals are simulated timestamps for attribution, never order authorizations. Soak operations: 3–6-month wall-clock envelope with the minimum-evidence gate defined by actual signal frequency, no unexplained gaps/reconciliation drift, runbook exercised; Phase-8 construction may overlap the soak but its enablement gates on paper evidence.

### the agent's Discretion
- User runs `--auto --chain` (fully autonomous): all five gray areas auto-resolved to recommended defaults with no interactive prompts. Single-pass cap observed — no re-pass gap-hunting.
- Exact module layout of the paper loop (e.g. new `src/paper/` package shape, loop/supervisor/resync/journal-monitor splits), WS client structure inside `src/adapters/`, journal table vs JSON-as-TEXT field choices, Parquet extract layout, soak-monitor mechanics (CI job vs scheduled process), SIMULATE message formatting, epoch-rollover mechanics, and plan slicing (tracer-first realtime slice vs vertical slices) are at the planner/researcher discretion, provided D-01–D-05 semantics hold.
- Pre-answered from prior phases (not re-asked): purity contracts (stdlib + `Decimal` only in core/risk/backtest/paper-core, no `float`, AST no-`float(` guards + mypy strict); TDD RED→GREEN with atomic commits; frozen dataclasses; content-hash IDs; TOML registry + SHA256 with 07.1 cost-binding gate; six-field experiment identity permanence; Hive Parquet raw-immutable + versioned derived; flag-never-fabricate gaps; fail-closed posture; single-Base ORM + parity-gate discipline.

### Deferred Ideas (OUT OF SCOPE)
- Telegram APPROVE/SKIP idempotency hardening + reconciliation/orphan-sweeper/SAFE_MODE rehearsal → Phase 8 (paper rows are its input, SIMULATE payloads prefigure APRV-01 fields).
- Live Algo exits + placement-time revalidation → Phase 9; journal depth (MFE/MAE, execution-quality latencies, approval-delay impact) + kill-gate analytics → Phase 10.
- Correlation model upgrade (REFN-04), OI/funding as strategy features (REFN-02/REFN-03), 15M refinement (REFN-01), extra families (REFN-05) → v2 requirements, not Phase 7.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PAPER-01 | Realtime paper engine ingests WS market data with warm-up/reconnect/resync, evaluates closed candles only, journals gaps without fabricating signals | WS Streams surface + REST resync (§Standard Stack, Pattern 1); closed-candle gate (§Pitfall 1, Code Examples); CollectorGap precedent (§Patterns) |
| PAPER-02 | Paper loop records system vs user-executed vs opportunity attribution with signal/approve/order/fill timestamps | Three-way attribution schema on seven-entity rows + JournalEvent (§Patterns, Pattern 3); SIMULATE payload field set (§Code Examples) |
| PAPER-03 | Forward evidence accumulates over 3–6-month wall-clock envelope with no tuning on the paper stream | Pinned-hash epoch + diff monitor (§Pattern 4); per-epoch evidence windows; soak operations (§Pitfalls, Validation) |
</phase_requirements>

## Project Constraints (from AGENTS.md)

- **Determinism:** same snapshot + account state + strategy version + config = same decision; no repaint, no future-candle leakage, prefix-invariant, byte-equivalent outputs. Paper loop must evaluate closed candles only (Binance `x == true` flag), never the forming candle.
- **No-AI core:** LLM assists code/docs/tests only; never decides direction/entry/SL/TP/size/risk/parameters/signal-validity. No `ccxt`, no NautilusTrader foundation, no VectorBT canonical semantics.
- **Exchange authority:** Binance canonical; dynamic `exchangeInfo` (stepSize/tick/notional); user-data WS preferred realtime; re-verify SDK minor + changelog before wiring (Dec-2025 Algo-migration precedent). Never legacy `binance-connector` / `binance-futures-connector` (archived 2026-04-30).
- **Quantization:** floor to stepSize → realized-risk check (60% baseline) → min-qty/notional reject → NO_TRADE preferred over round-up; identical logic backtest/paper/live.
- **Approval safety:** Phase 7 sends SIMULATE read-only notifications only; idempotent APPROVE/SKIP hardening is Phase 8. Paper approvals are simulated timestamps, never order authorizations.
- **Fail closed:** uncertain data/connection/account/risk → NO_TRADE; SAFE_MODE blocks entries while monitoring continues.
- **Tech stack:** Python 3.13 (`uv run` — system python here is 3.14.3, must NOT be used), asyncio single loop, official SDK behind adapters, PostgreSQL 17 + Parquet/DuckDB, pytest + Ruff + mypy strict, `Decimal`/tick arithmetic for exchange-sensitive values.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| WS kline ingestion + reconnect/resync | API / Backend (adapter edge) | — | Network I/O behind `src/adapters/`; SDK types never leak past the boundary |
| Closed-candle evaluation (features/strategy/planner) | API / Backend (paper-core, pure) | — | Identical pure functions as backtest; stdlib + Decimal only |
| Sizing/quantization/portfolio gates | API / Backend (paper-core, pure) | — | Identical `src/risk/` calls; fail-closed reason codes |
| Simulated fills (1m intrabar SL-first) | API / Backend (paper-core, pure) | — | Backtest `resolve_intrabar` semantics, registry-versioned costs |
| Signal/plan/approval journal | Database / Storage (PostgreSQL) | Parquet mirror | ACID lifecycle rows; Parquet is the analytical canonical |
| SIMULATE Telegram notifications | API / Backend (notify edge) | — | Send-only; journal-first (notify failure never blocks journaling, never auto-approves) |
| No-tuning freeze proof | API / Backend (soak monitor) | CI / scheduled job | Registry-hash diff against pinned epoch; per-epoch evidence windows |
| Evidence analysis (divergence, attribution) | Database / Storage (DuckDB over Parquet) | — | Same pattern as Phase-6 D-03 extracts |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `binance-sdk-derivatives-trading-usds-futures` | 17.4.0 installed [VERIFIED: `uv run python -c importlib.metadata`] (constraint `>=17.3,<18` [VERIFIED: pyproject.toml]) | WS Streams kline subscription + REST kline resync + exchangeInfo snapshots | Official SDK; WS Streams class exposes `kline_candlestick_streams` + `reconnect`/`schedule_reconnect` [VERIFIED: installed package inspect this session]; legacy connectors archived 2026-04-30 [CITED: STACK.md / PyPI archived markers] |
| `python-telegram-bot` | `>=22.8,<23` [ASSUMED] (STACK floor; **not in pyproject/uv.lock — new dep**) | SIMULATE send-only notifications (`Bot.send_message` + `InlineKeyboardMarkup`) | asyncio-native since v20, fits single-loop architecture [CITED: https://docs.python-telegram-bot.org/en/stable/examples.inlinekeyboard.html]; Bot API 10.0 [CITED: STACK.md] |
| SQLAlchemy | 2.0.54 installed [VERIFIED: importlib.metadata] (constraint `>=2.0,<2.1` [VERIFIED: pyproject.toml]) | Async journal persistence (`create_async_engine("postgresql+psycopg://…")` + `async_sessionmaker`) | Documented current 2.0-style async API [CITED: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html]; single-Base ORM precedent in-repo |
| psycopg | 3.3.6 installed [VERIFIED: importlib.metadata] (`psycopg[binary,pool]>=3.3,<4` [VERIFIED: pyproject.toml]) | Sync + async PG driver | Official SQLAlchemy-async path; `binary` avoids Windows libpq builds [CITED: STACK.md] |
| tenacity | 9.1.4 installed [VERIFIED: importlib.metadata] (constraint `>=9` [VERIFIED: pyproject.toml]) | Bounded retries with jitter for WS reconnect, REST resync, Telegram sends | `@retry(stop=stop_after_attempt \| stop_after_delay, wait=wait_random_exponential, reraise=True)`; async-native sleeps [CITED: https://tenacity.readthedocs.io/en/latest/]; never infinite retry on order-adjacent paths |
| structlog | 26.1.0 installed [VERIFIED: importlib.metadata] (constraint `>=25` [VERIFIED: pyproject.toml]) | Structured JSON decision-lineage logs (snapshot → signal → plan → approval → fill) | Existing adapter/collector precedent (`structlog.get_logger()` in `binance_usdm.py`, `collector.py`) [VERIFIED: src/adapters/binance_usdm.py:33, src/data/collector.py:54] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Polars + pyarrow + DuckDB | installed per STACK (pyarrow>=19, DuckDB 1.5.5) | Parquet journal extracts + forward-evidence analysis | Same Phase-6 D-03 pattern: PG rows operational, Parquet files analytical-canonical |
| Alembic | >=1.19 [VERIFIED: pyproject.toml] | Any paper-journal migration | Single-Base + offline parity-gate discipline; never `create_all` in prod paths |
| tzdata | [VERIFIED: pyproject.toml] | `Asia/Ho_Chi_Minh` display edge on Windows | UTC internally always; presentation only at the edge |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SDK WS Streams | Direct `websockets` + hand-rolled subscribe | Hand-rolled loses `reconnect`/`schedule_reconnect`, enum-typed intervals, and changelog tracking — rejected per D-01 |
| `Bot.send_message` (send-only) | Full `Application` + poller | Phase 7 needs no inbound callbacks (hardening is Phase 8); a poller adds an idle update loop and second lifecycle to supervise for zero benefit |
| PG journal rows | Log-file-only journal | Loses ACID + attribution joins + Phase-8/10 inputs; rejected per D-03 |
| Scheduled-process soak monitor | CI-job diff check | Either satisfies D-04; planner's call — CI is cheaper, a process is more immediate |

**Installation:**
```bash
uv add "python-telegram-bot>=22.8,<23"   # ONLY new dependency; everything else is in uv.lock
```

**Version verification:** SDK 17.4.0, tenacity 9.1.4, structlog 26.1.0, SQLAlchemy 2.0.54, psycopg 3.3.6 — all confirmed via `importlib.metadata` under `uv run python` (3.13.15) this session. `python-telegram-bot` version NOT verified (absent from `uv.lock` — grep confirmed zero matches); resolve via `uv add` + lockfile at plan time.

## Package Legitimacy Audit

> `uv pip index` is unavailable in uv 0.12.17 (verified: `unrecognized subcommand 'index'`); registry metadata below comes from the local lockfile + installed environment, not a live registry lookup. The one new install is gated accordingly.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `binance-sdk-derivatives-trading-usds-futures` 17.4.0 | PyPI | years (v17 line current) | high (official Binance SDK) | github.com/binance | OK | Approved — installed, surface inspected |
| `python-telegram-bot` | PyPI | ~10 yrs (well-known) | ~M/mo [ASSUMED] | github.com/python-telegram-bot/python-telegram-bot [ASSUMED] | UNVERIFIED | **Flagged — planner must add `checkpoint:human-verify` before `uv add`** |
| tenacity 9.1.4 | PyPI | years | high | github.com/jd/tenacity | OK | Approved — in lockfile |
| structlog 26.1.0 | PyPI | years | high | github.com/hynek/structlog | OK | Approved — in lockfile |
| SQLAlchemy 2.0.54 / psycopg 3.3.6 | PyPI | years | high | official repos | OK | Approved — in lockfile |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** `python-telegram-bot` — not suspicious per se (canonical STACK choice, official docs sampled via Context7), but it is the only package not yet pinned in `uv.lock`; gate its install behind human verification per protocol.

*No `postinstall` scripts apply (all pure-Python wheels/sdists in this stack) [ASSUMED].*

## Architecture Patterns

### System Architecture Diagram

```text
Binance WS Streams (wss://fstream.binance.com, combined stream, lowercase symbols)
  │  <symbol>@kline_<1h|4h> events every 2s, x=false (forming) / x=true (closed)
  ▼
┌─ WS Supervisor (src/adapters/ + paper supervisor) ─────────────────┐
│ subscribe → on(event) → ping/pong keepalive → 24h planned rotation │
│ UNSOLICITED disconnect / missed close → tenacity-bounded reconnect │
│   → REST kline resync (adapter.klines, limit≤1500) → gap detect    │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ closed candles only (x==true + close_time<=now)
                               ▼
┌─ Paper Core (src/paper/, dependency-free: stdlib+Decimal only) ────┐
│ warm-up gate (Phase-4 validity flags; invalid → NO_TRADE)          │
│ compute_features → evaluate → plan (identical src/core/ calls)     │
│ size_position → quantize → check_portfolio → evaluate_risk         │
│   (identical src/risk/ calls; absolute-amount conversion by caller)│
│ simulated fills: resolve_intrabar SL-first on 1m + CostModel       │
│   (registry-bound via assert_cost_model_binds_registry)            │
│ uncertain/stale feed or account state → NO_TRADE + reason code     │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ signal/plan/approval(sim)/order(sim)/fill + gaps
                               ▼
┌─ Journal ──────────────────────────────────────────────────────────┐
│ PostgreSQL seven-entity rows + JournalEvent gap/attribution rows   │
│   → Parquet extracts (DuckDB/Polars analysis; files canonical)     │
│ Telegram SIMULATE notify (journal-first; failure → journaled,      │
│   never auto-approve, never blocks the loop)                       │
└──────────────────────────────┬─────────────────────────────────────┘
                               ▼
┌─ Soak Monitor ─────────────────────────────────────────────────────┐
│ pinned (parameterSetId, parameterSetHash) at stream start          │
│ periodic re-hash + diff → change ⇒ new epoch, per-epoch evidence   │
│ PAPER-03 artifact: diff log proving pinned hash untouched          │
└────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure
```text
src/
├── paper/           # NEW — dependency-free (stdlib + Decimal + core/_decimal only)
│   ├── __init__.py  # barrel: loop, supervisor, resync, journal, monitor, attribution
│   ├── loop.py      # closed-candle dispatch: features→strategy→planner→risk→sim-fill
│   ├── supervisor.py# WS lifecycle: subscribe, keepalive, 24h rotation, reconnect trigger
│   ├── resync.py    # REST backfill of missed closes + gap detection (no synthesis)
│   ├── journal.py   # attributed record assembly (identity + timestamp lineage)
│   ├── attribution.py # system vs user-executed(sim) vs opportunity split
│   ├── freeze.py    # epoch pin + registry diff monitor
│   └── notify.py    # SIMULATE payload formatting + Bot.send_message (SDK-free core;
│                    #   the Bot client itself lives behind an adapter-edge wrapper)
├── adapters/
│   └── paper_ws.py  # NEW — WS Streams client (ONLY module importing WS surface)
├── db/
│   └── alembic/versions/00XX_paper_journal.py  # only if new columns/tables needed
└── sql/             # DuckDB extract queries for divergence/attribution analysis
tests/
└── fixtures/phase7/ # feed sequences (incl. reconnects/gaps) → expected journal/
                     # attribution/epoch records, byte-exact
```

### Pattern 1: WS kline subscribe + closed-candle gate
**What:** Subscribe via the SDK WS Streams class; process a kline **only** when the stream marks it closed (`x == true`) **and** `close_time_utc <= now_utc` (the repo's `Kline` invariant — `src/adapters/binance_usdm.py:50-55` [VERIFIED: src/adapters/binance_usdm.py:50-55]).
**When to use:** Every ingestion tick for 1h setup + 4h regime streams (plus 1m only for simulated fill resolution).
**Example:**
```python
# Source: installed SDK 17.4.0 signatures inspected this session via python inspect
from binance_sdk_derivatives_trading_usds_futures.websocket_streams import (
    DerivativesTradingUsdsFuturesWebSocketStreams,
)
from binance_sdk_derivatives_trading_usds_futures.websocket_streams.models.enums import (
    KlineCandlestickStreamsIntervalEnum,  # '1m','1h','4h' members verified present
)
# (self, symbol, interval, id=None) -> RequestStreamHandle
ws.kline_candlestick_streams(symbol="btcusdt", interval=KlineCandlestickStreamsIntervalEnum.INTERVAL_1h)
ws.connect(url, configuration)        # raw or combined-stream URL
ws.reconnect(connection, configuration)  # on unsolicited drop; schedule_reconnect exists too
```
```python
# Closed-candle gate (project invariant — never trust x==true alone):
# Source: src/adapters/binance_usdm.py:50-68 (Kline dataclass, Read this session)
if event.k.x is True and event.k.close_time_utc <= now_utc:
    evaluate_closed_candle(kline)
else:
    hold_forming_candle_in_memory()  # never persisted, never evaluated
```

### Pattern 2: Bounded reconnect + REST resync (never synthesize)
**What:** tenacity-bounded reconnect (`stop_after_attempt | stop_after_delay`, `wait_random_exponential`, `reraise=True`), then REST `klines` to backfill missed closes; any unrecoverable window becomes an explicit gap row. Follows the collector's fail-closed precedent: failed poll writes ONE gap row, never advances the watermark [VERIFIED: src/data/collector.py:1-12].
**When to use:** Every disconnect, missed-close detection, and the 24h server-initiated rotation.
**Example:**
```python
# Source: https://tenacity.readthedocs.io/en/latest/ (CITED) + adapter surface verified
from tenacity import retry, stop_after_attempt, stop_after_delay, wait_random_exponential

@retry(stop=(stop_after_attempt(7) | stop_after_delay(120)),
       wait=wait_random_exponential(multiplier=1, max=60), reraise=True)
async def reconnect_and_resync(symbol, interval, last_close_utc):
    await ws_reconnect()
    # Source: src/adapters/binance_usdm.py — (self, symbol, interval,
    #   start_ms=None, end_ms=None, limit=1500) -> list[Kline] [VERIFIED: inspect]
    missed = await adapter.klines(symbol, interval, start_ms=ms(last_close_utc))
    return diff_against_memory(missed)  # holes → CollectorGap-style rows, never fills
```

### Pattern 3: Three-way attribution journal
**What:** Every paper record keeps canonical identity + full timestamp lineage; attribution is a first-class field, not a post-hoc join. PG rows use the seven-entity shapes (`SignalRow`, `TradePlanRow`, `ApprovalRow`(action=SIMULATE, simulated `acted_at_utc`), `OrderRow`/`FillRow`(simulated), `JournalEventRow`) [VERIFIED: src/db/models.py:190-300]; gap/attribution events reuse the `CollectorGap` shape (symbol, data_class, expected_utc, observed_utc, reason) [VERIFIED: src/db/models.py:132-154] — extend `data_class` with a paper value (e.g. `'paper-1h'`) rather than inventing a parallel table.
**When to use:** Every signal, plan, simulated-approval, simulated-fill, skip/expire, and gap.
**Attribution values:** `system` (engine emitted) / `user-executed-sim` (SIMULATE fill incl. approval-delay modeling) / `opportunity` (skipped/expired with reason code — retained, never dropped). Verbatim status vocabularies the journal must use:
```python
# Source: src/domain/enums.py:16-30, 43-54, 56-70 [VERIFIED — Read this session, quoted verbatim]
class SignalStatus(str, Enum):
    DETECTED = "DETECTED"
    NOTIFIED = "NOTIFIED"
    VIEWED = "VIEWED"
    APPROVED = "APPROVED"
    SKIPPED_USER = "SKIPPED_USER"
    SKIPPED_BUSY = "SKIPPED_BUSY"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
class ApprovalAction(str, Enum):
    SIMULATE = "SIMULATE"
    APPROVE = "APPROVE"
    SKIP_USER = "SKIP_USER"
    SKIP_BUSY = "SKIP_BUSY"
    CANCEL = "CANCEL"
class ApprovalResult(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SKIPPED = "SKIPPED"
    EXPIRED = "EXPIRED"
```

### Pattern 4: Pinned-epoch freeze monitor
**What:** At stream start, record `(parameterSetId, parameterSetHash)` via `load_parameter_set` + `assert_cost_model_binds_registry` (raises `CostModelBindingMismatch` on inequality, bare `KeyError` on absent keys — never silent defaults) [VERIFIED: src/backtest/binding.py:42-61]. A periodic job re-hashes the registry files and compares; any diff ⇒ log + new epoch, evidence windows stay per-epoch. PAPER-03 artifact = the diff log.
**When to use:** Stream bootstrap + every monitor tick (cadence at planner discretion; hourly-or-daily is plenty for a no-change proof).

### Anti-Patterns to Avoid
- **Evaluating the forming candle:** any use of `x == false` payloads or `close_time > now` in evaluation breaks determinism vs backtest. Gate twice (flag + timestamp).
- **Interpolating gaps:** synthesized candles contaminate forward evidence irreversibly. Journal the hole, fail closed, move on.
- **Paper-local sizing/costs:** any `if paper:` branch in sizing, quantization, or cost math invalidates the soak. Divergence is fixed in the engine, never at the call site.
- **Notify-before-journal:** Telegram failure must never lose a signal. Journal first, notify second, journal the notify outcome.
- **Retroactive epoch edits:** a mid-soak parameter change must open a new epoch, never rewrite the pinned hash of the running window.
- **Importing the SDK past adapters:** `src/paper/` core must be as dependency-free as `src/core|risk|backtest/` (stdlib + Decimal only); the WS client and the Telegram `Bot` stay behind edge wrappers.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WS reconnect/backoff | Custom sleep-loop | SDK `reconnect`/`schedule_reconnect` + tenacity bounded retry | 24h rotation, ping/pong (3-min server ping, 10-min pong timeout), 10 inbound msg/s limit are server-dictated edge cases [CITED: https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams] |
| Retry policy | Bare `while True` reconnect | tenacity `stop_after_attempt \| stop_after_delay` + `wait_random_exponential` | Infinite retry on a feed path hides outages; bounded-then-fail-closed is the safety posture |
| Async PG sessions | Hand-rolled connection handling | `create_async_engine("postgresql+psycopg://…")` + `async_sessionmaker` + `async with` | Documented lifecycle incl. `await engine.dispose()` [CITED: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html] |
| Telegram send + buttons | Raw httpx Bot API calls | `python-telegram-bot` `Bot.send_message` + `InlineKeyboardMarkup`/`InlineKeyboardButton(callback_data=…)` + mandatory `query.answer()` | Callback-query progress-bar semantics and answer-requirement are API-dictated [CITED: PTB stable docs via Context7] |
| Structured logs | Custom logger | structlog (already the repo standard) | Decision-lineage schema must be uniform across collector → paper → execution |
| Backtest comparison | Ad-hoc metric scripts | `ExperimentRecord`/`verify_experiment` + DuckDB Parquet extracts | Six-field identity + reproduce/verify is the canonical divergence gate |

**Key insight:** Paper's entire value is *sameness* — same functions, same math, same costs — observed over wall-clock time. Every custom re-implementation at the paper layer is a divergence source that destroys the evidence the phase exists to collect.

## Common Pitfalls

### Pitfall 1: Forming-candle leakage (repaint by another name)
**What goes wrong:** Evaluating `x == false` updates or trusting `x == true` without the timestamp check shifts entries a bar early vs backtest.
**Why it happens:** WS pushes forming-candle updates every 2s; they look like data.
**How to avoid:** Double gate (`x is True` AND `close_time_utc <= now_utc`); unit-test with a fixture that interleaves forming updates before the close marker (`test_candle_close_timing.py` precedent).
**Warning signs:** Paper signals consistently one bar earlier than backtest replay on the same window.

### Pitfall 2: The 24h WS rotation treated as an outage incident
**What goes wrong:** Server disconnects every 24h; a supervisor that only handles errors pages the operator daily.
**Why it happens:** Rotation is documented normal behavior [CITED: Binance WS streams docs].
**How to avoid:** Treat rotation as scheduled: proactively resubscribe + REST-resync around the 24h mark; keep error-path for unsolicited drops only.
**Warning signs:** Daily gap rows at ~same time with `reason=disconnect`.

### Pitfall 3: Running under system Python 3.14
**What goes wrong:** Bare `python` here is 3.14.3 while the project pins `requires-python == "==3.13.*"` [VERIFIED: pyproject.toml]; SDK/dependency behavior is only locked for 3.13.
**Why it happens:** Windows PATH default vs `uv run`.
**How to avoid:** All paper entrypoints run via `uv run` (3.13.15 verified this session); CI asserts `python --version`.
**Warning signs:** `uv.lock` resolution drift, wheel incompatibilities.

### Pitfall 4: Rate-to-absolute conversion forgotten at the risk call
**What goes wrong:** `check_portfolio` takes ABSOLUTE quote amounts; passing registry rates directly mis-gates every plan (deferred item in STATE.md).
**Why it happens:** Registry stores rates; risk API wants absolutes.
**How to avoid:** Paper caller converts via `resolve_absolute_thresholds` before every `check_portfolio` call; parity test pins it.
**Warning signs:** Caps triggering at absurd portfolio fractions.

### Pitfall 5: Telegram failure auto-skipping or blocking
**What goes wrong:** Notify exception either drops the signal or is misread as a SKIP.
**Why it happens:** Notify and journal share a try-block.
**How to avoid:** Journal-first ordering; notify in its own bounded-retry block; notify outcome journaled as an event, never as attribution.
**Warning signs:** Signals with no journal row but a Telegram message, or vice versa.

### Pitfall 6: Warm-up evaluated as valid on a fresh stream
**What goes wrong:** First hours of a fresh stream emit signals from under-warmed EMA200-4H-class features.
**Why it happens:** In-memory feature state starts empty; REST bootstrap history insufficient.
**How to avoid:** Bootstrap sufficient closed history via `adapter.klines` before subscribing; respect Phase-4 invalid flags (invalid → NO_TRADE) until history suffices.
**Warning signs:** Burst of signals in the first N bars after every restart.

### Pitfall 7: Tuning the running stream (evidence contamination)
**What goes wrong:** A mid-soak registry edit silently becomes "forward evidence".
**Why it happens:** Registry files are editable in place; nothing stops it by default.
**How to avoid:** Freeze monitor + epoch discipline (Pattern 4); make the monitor's diff log the PAPER-03 artifact, not a side note.
**Warning signs:** Any diff-log entry during the evidence window.

## Code Examples

### Closed-candle paper tick (canonical call chain)
```python
# Source: in-repo public surfaces (Read/inspected this session) — planner wires, never re-implements
from src.core import compute_features, evaluate, plan
from src.risk import size_position, quantize, check_portfolio, evaluate_risk
from src.backtest import resolve_intrabar, build_cost_model, assert_cost_model_binds_registry

features = compute_features(closed_1h + closed_4h_ctx)   # invalid flags honored
setup = evaluate(features, account_state, strategy_version, config)
if setup.is_no_trade:
    journal(reason_code=setup.reason_code)               # NO_TRADE is data
    return
trade_plan = plan(setup, ...)
sized = size_position(...)        # modeled costs included
qty = quantize(...)              # floor+reject; NO_TRADE preferred over round-up
verdict = check_portfolio(...)   # absolute amounts; converted by caller
outcome = resolve_intrabar(plan=trade_plan, intrabar_1m=...)  # SL-first simulated fill
```

### SIMULATE notify payload (APRV-01 field set, send-only)
```python
# Source: PTB stable docs via Context7 (CITED) + docs/integration/TELEGRAM.md §§4-5
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

keyboard = [[InlineKeyboardButton("SIMULATE-recorded", callback_data=f"SIM:{signal_id}"),
             InlineKeyboardButton("SKIP (Phase 8)", callback_data=f"SKIP:{signal_id}")]]
text = (f"{symbol} {direction} {setup_type}\nEntry {entry_min}–{entry_max} | SL {sl} | "
        f"TP {tps} | RR {rr} | risk {risk} | exp {expiry} | inv {invalidation}\n"
        f"Exposure {exposure} | Reasons {reason_codes}")  # all 12 APRV-01 fields
await bot.send_message(chat_id=AUTHORIZED_CHAT, text=text,
                       reply_markup=InlineKeyboardMarkup(keyboard))
# No Application/poller in Phase 7 — callbacks are inert labels until Phase 8 hardens them.
```

### Soak-monitor epoch check
```python
# Source: src/domain/registry.py (load_parameter_set) + src/backtest/binding.py:42-61
pinned = load_parameter_set(strategy_id, parameter_set_id)  # hash pinned at stream start
current = load_parameter_set(strategy_id, parameter_set_id)  # re-read each tick
if current.parameter_set_hash != pinned.parameter_set_hash:
    open_new_epoch(pinned, current)   # evidence windows stay per-epoch; never rewrite
    halt_evidence_claim("REGISTRY_DIFF")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Legacy `binance-connector` / `binance-futures-connector` | `binance-sdk-derivatives-trading-usds-futures` v17 line (17.4.0 installed) | Legacy archived 2026-04-30 | Old SDKs lack Algo-Order/conditional endpoints and current user-data events — never use |
| `CONDITIONAL_ORDER_TRIGGER_REJECT` event | `ALGO_UPDATE.o.rm` rejection reasons | Dec 2025 Algo migration | Paper-adjacent reconciler (Phase 8) must parse `ALGO_UPDATE`, not the old event |
| `create_async_engine("postgresql+asyncpg://…")` examples | `postgresql+psycopg://` async engine | Psycopg 3 succession | One driver for sync+async; asyncpg only on measured bottleneck |
| pytest-asyncio decorator-per-test | `asyncio_mode = "auto"` | Project pyproject already sets it [VERIFIED: pyproject.toml] | Async paper tests need no decorators |

**Deprecated/outdated:**
- `float` for any exchange-sensitive value: banned repo-wide (AST guards `tests/test_domain_no_float.py`); `Decimal`-only in paper-core.
- `ccxt` on order paths, Redis in V1, K8s/Kafka topology: all rejected per STACK (no measured need).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `python-telegram-bot` 22.x API (`Bot.send_message`, `InlineKeyboardMarkup`, `query.answer()` semantics) stable as sampled | Standard Stack / Code Examples | MEDIUM — pin via `uv lock`; re-verify at install time |
| A2 | WS kline payload shape (`e/k/t/T/o/c/h/l/v/n/x/q`) per public stream docs | Pattern 1 | LOW — adapter normalizes to `Kline`; shape mismatch surfaces in edge tests, not core |
| A3 | Combined-stream URL + 1024-stream cap + 10 msg/s inbound limit current | Pitfalls | LOW — Live-5 × 2 intervals = 10 streams, far under caps |
| A4 | PostgreSQL 17 + Docker Compose available at soak runtime; Telegram bot token + authorized chat provisioned by operator | Environment Availability | MEDIUM — missing PG/token blocks the soak; planner must add provisioning tasks |
| A5 | Minimum-evidence thresholds set by researcher from actual signal frequency (IMPLEMENTATION_PLAN exit gate) | Requirements | LOW — gate definition is a research input, not a code input |
| A6 | `uv.lock` resolves `python-telegram-bot` cleanly under Python 3.13 without forcing upgrades of pinned deps | Installation | LOW — failure surfaces at `uv add` time, before any code |

## Open Questions (RESOLVED)

> Resolved at plan-revision 1: each question below carries its decided outcome, embodied by the cited plan. No open questions remain.

1. **Soak-monitor mechanics: CI job vs scheduled process? — RESOLVED: scheduled CI workflow by default.**
   - Decision: the periodic invoker is a scheduled CI workflow (`.github/workflows/paper_freeze_check.yml`, hourly cron) calling the freeze check CLI; a soak-host scheduled process is the documented operator alternative when the soak host is long-lived anyway. Diff log persists append-only at `logs/paper/registry_diff.jsonl`.
   - Embodied by: 07-04-PLAN.md freeze task (pin plus check CLI plus workflow file plus diff-log path).
2. **Parquet extract layout for paper journal? — RESOLVED: mirror Phase-6 layout plus `epoch` partition; file extracts deferred to Phase 10.**
   - Decision: when built, extracts mirror the Phase-6 backtest extract layout with an added `epoch` partition key (StreamEpoch `epoch_id` already carried on every paper row, so future extraction is lossless). The extract pipeline itself is explicitly deferred to Phase 10, which owns journal analytics depth; Phase-7 acceptance rests on PostgreSQL journal rows plus golden fixtures.
   - Embodied by: 07-03-PLAN.md deferral record (epoch_id on PaperRecord, extracts deferred with rationale).
3. **Approval-delay modeling parameters for user-executed-sim attribution? — RESOLVED: fixed documented lag constant, Phase-10 calibrates.**
   - Decision: `APPROVAL_DELAY_LAG_SECONDS` fixed documented constant in `src/paper/attribution.py`, applied to the simulated `acted_at_utc`; calibrated against measured Telegram latency in Phase 10, never blocking Phase 7.
   - Embodied by: 07-03-PLAN.md attribution feature plus lag test.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 via `uv run` | All paper code | ✓ [VERIFIED: `uv run python --version` → 3.13.15] | 3.13.15 | — (bare `python` is 3.14.3 — forbidden) |
| `binance-sdk-derivatives-trading-usds-futures` | WS + REST | ✓ [VERIFIED: installed, surface inspected] | 17.4.0 | — |
| tenacity / structlog / SQLAlchemy / psycopg | reconnect / logs / journal | ✓ [VERIFIED: installed] | 9.1.4 / 26.1.0 / 2.0.54 / 3.3.6 | — |
| `python-telegram-bot` | SIMULATE notify | ✗ (absent from uv.lock) | — | `uv add` behind human-verify checkpoint |
| PostgreSQL 17 (Compose) | journal rows | NOT PROBED this session | — | No fallback — provisioning task required |
| Telegram bot token + authorized chat | notify | NOT PROBED this session | — | Degraded mode: journal-only, notify failures journaled (never blocking) |
| Binance network reachability (fstream + fapi) | feed + resync | NOT PROBED this session | — | No fallback — pre-soak connectivity smoke test required |

**Missing dependencies with no fallback:**
- PostgreSQL 17 availability + Telegram credentials + Binance reachability must each be verified by a pre-soak smoke task in the plan (none were probed from this research session).

**Missing dependencies with fallback:**
- `python-telegram-bot` uninstalled → `uv add` gated; until then, journal-only degraded mode keeps PAPER-01/03 progressing.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9 + pytest-asyncio (auto mode) [VERIFIED: pyproject.toml] |
| Config file | pyproject.toml (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| Quick run command | `uv run pytest tests/test_paper_<slice>.py -x` |
| Full suite command | `uv run pytest -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PAPER-01 | Closed-candle-only evaluation (forming updates ignored) | unit | `uv run pytest tests/test_paper_closed_candle.py -x` | ❌ Wave 0 |
| PAPER-01 | Reconnect → REST resync → gap journaled, nothing synthesized | unit + golden fixture | `uv run pytest tests/test_paper_resync.py -x` | ❌ Wave 0 |
| PAPER-01 | Warm-up invalid → NO_TRADE; stale feed → NO_TRADE + reason | unit | `uv run pytest tests/test_paper_feed_gates.py -x` | ❌ Wave 0 |
| PAPER-01 | Backtest↔paper parity on overlapping history (no material divergence) | golden fixture (byte-exact) | `uv run pytest tests/test_paper_parity.py -x` | ❌ Wave 0 |
| PAPER-02 | Three-way attribution + full timestamp lineage on every record | unit + golden fixture | `uv run pytest tests/test_paper_attribution.py -x` | ❌ Wave 0 |
| PAPER-02 | Skipped/expired plans retained with reason codes (never dropped) | unit | (same file as above) | ❌ Wave 0 |
| PAPER-03 | Registry diff opens new epoch; evidence windows per-epoch | unit | `uv run pytest tests/test_paper_freeze.py -x` | ❌ Wave 0 |
| PAPER-03 | 3–6-month soak envelope + no-unexplained-gaps | manual-only (wall-clock) | runbook exercise + diff-log review | manual — justified: wall-clock cannot be unit-tested |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_paper_<slice>.py -x` + `ruff check` + `mypy` on touched package
- **Per wave merge:** `uv run pytest -x` (full suite green — backtest↔paper parity must never regress)
- **Phase gate:** Full suite green + parity fixtures byte-exact before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/fixtures/phase7/` — feed sequences (clean run, reconnect+resync, unrecoverable gap, epoch rollover) + expected journal/attribution/epoch records, byte-exact
- [ ] `tests/test_paper_closed_candle.py`, `test_paper_resync.py`, `test_paper_feed_gates.py`, `test_paper_parity.py`, `test_paper_attribution.py`, `test_paper_freeze.py` — cover PAPER-01..03 per map above
- [ ] `src/paper/` package skeleton (dependency-free) + `src/adapters/paper_ws.py` edge — needed before any RED test can import
- [ ] Framework install: `uv add "python-telegram-bot>=22.8,<23"` behind `checkpoint:human-verify` — before notify tests

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Telegram `chat_id` allowlist (authorized chat only); bot token from env/secrets, never git |
| V3 Session Management | no | No user sessions in Phase 7 (send-only Telegram; no callbacks consumed) |
| V4 Access Control | yes | Paper approvals are simulated timestamps — must be structurally incapable of authorizing orders (no order path exists in Phase 7) |
| V5 Input Validation | yes | WS payloads validated at adapter edge into frozen `Kline` (Decimal + UTC-aware); pydantic at any webhook boundary (none new in Phase 7) |
| V6 Cryptography | partial | Approval-token hash discipline (`approval_token_hash`, `request_hash`) prefigured per Phase-3 shapes; no new crypto — never hand-roll |
| V7 Error Handling/Logging | yes | Fail-closed NO_TRADE + reason codes; structured secret-free logs (no token/secret in log fields) |
| V9 Communications | yes | TLS-only (wss/https); Telegram sends via official client; bounded retries, no secret leakage on failure paths |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Spoofed Telegram sender authorizing action | Spoofing | Phase 7 sends only (no inbound actions); Phase 8 binds chat + one-time token + idempotent replay |
| WS feed spoofing / stale-feed trading | Tampering | TLS WS + closed-candle + staleness gates → NO_TRADE; gap journaling makes tampering visible |
| Secret (bot token) in logs/repo | Information disclosure | Env-only secrets; secret-free structured logging; pre-commit secret scan |
| Registry tampering mid-soak | Tampering | Pinned-hash epoch monitor; diff ⇒ new epoch + halted evidence claim |
| Forged backfill (synthetic candles) | Tampering | Flag-never-fabricate: REST resync fills only exchange-returned closes; holes stay holes |

## Sources

### Primary (HIGH confidence)
- Installed `binance-sdk-derivatives-trading-usds-futures` 17.4.0 — WS Streams class/method/enum signatures inspected live via `python inspect` (`kline_candlestick_streams`, `connect`, `reconnect`, `KlineCandlestickStreamsIntervalEnum` with `1m/1h/4h`)
- In-repo source Read this session: `src/adapters/binance_usdm.py` (Kline invariant, adapter boundary), `src/data/collector.py` (gap-journal precedent), `src/domain/enums.py:16-236` (verbatim status vocabularies), `src/domain/journal.py`, `src/domain/approval.py`, `src/domain/signal.py`, `src/domain/registry.py`, `src/backtest/binding.py:42-61` (freeze-gate semantics), `src/db/models.py:102-309` (gap + journal tables), `pyproject.toml` (pins, pytest config)
- Context7 `/websites/sqlalchemy_en_20` — async engine + `async_sessionmaker` lifecycle
- Context7 `/websites/python-telegram-bot_en_stable` — inline keyboard + `CallbackQueryHandler` + mandatory `query.answer()`
- Binance official docs via web search — `/fapi/v1/klines` weight/params, WS market streams connection rules (24h rotation, ping/pong, 10 msg/s, 1024 streams), kline stream payload with `x` closed flag

### Secondary (MEDIUM confidence)
- Tenacity official docs via web search — bounded retry + `wait_random_exponential` + `AsyncRetrying` patterns
- STACK.md / TECHNOLOGY_STACK.md canonical versions (SDK floors, deprecation dates, Algo-migration precedent)

### Tertiary (LOW confidence)
- `python-telegram-bot` download counts / repo URL (training knowledge, [ASSUMED]); exact 22.x send-only API stability across minors (verify at `uv add` time)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — SDK surface + 5 installed versions verified by tool this session; one new dep flagged honestly
- Architecture: HIGH — all patterns reuse verified in-repo precedents; CONTEXT locks D-01–D-05 with no alternatives to explore
- Pitfalls: HIGH — each grounded in either verified repo state or cited official docs

**Research date:** 2026-09-26
**Valid until:** ~30 days (stable domain; re-verify SDK minor + Binance changelog before Phase-7 execution per the Dec-2025-migration precedent)
