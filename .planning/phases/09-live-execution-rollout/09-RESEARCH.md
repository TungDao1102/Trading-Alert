# Phase 9: Live Execution Rollout - Research

**Researched:** 2026-09-28
**Domain:** Live order execution on Binance USDⓈ-M Futures (LIMIT entry + CONDITIONAL algo protective exits, approval-gated, reconciled)
**Confidence:** HIGH

## Summary

Phase 9 wires the first cautious live orders: an approved plan places a LIMIT-zone entry via `POST /fapi/v1/order` and protective exits (STOP_MARKET / TAKE_PROFIT_MARKET legs) via `POST /fapi/v1/algoOrder` with `algoType=CONDITIONAL`, all through the official `binance-sdk-derivatives-trading-usds-futures` behind `src/adapters/binance_usdm.py`. The installed SDK is **17.4.0** [VERIFIED: `uv run` metadata + `inspect.signature` this session], and its placement-relevant signatures (`new_order`, `new_algo_order`, `get_current_position_mode`, `query_order`, `cancel_algo_order`, `current_all_algo_open_orders`, `query_algo_order`) were re-verified by introspection during this research — no public REST signature change vs the 08-04 record.

The decisive Binance semantics for this phase are: `closePosition=true` is valid only with STOP_MARKET/TAKE_PROFIT_MARKET and is mutually exclusive with quantity/reduceOnly; `reduceOnly` **cannot be sent in Hedge Mode**; `positionSide` defaults to `BOTH` in one-way mode and is **mandatory** in hedge mode; conditional orders live in the Algo Service since the Dec 2025 migration (`CONDITIONAL_ORDER_TRIGGER_REJECT` is gone — rejections arrive in `ALGO_UPDATE.o.rm`); and the per-symbol cap is **200 open conditional orders** (the `MAX_NUM_ALGO_ORDERS` exchangeInfo filter was removed Dec 2025) [CITED: developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/* via web search excerpts].

**Primary recommendation:** Build a pure `src/execution/` manager (stdlib + `Decimal` only) that reuses `evaluate_risk`, `derive_client_order_id`/`derive_algo_client_id`, the Phase-8 approval binding, and the three-source reconciler verbatim; extend `BinanceUsdmAdapter` with `place_entry` (`new_order`), `place_algo_protective` (`new_algo_order`), `query_order_by_client`, and `get_current_position_mode` wrappers; gate every placement on live exchangeInfo revalidation + reconciled-state DAILY_STOP with fail-closed reason codes; ship behind `LIVE_ORDERS_DISABLED` default with no-withdrawal keys, IP allowlisting, and off-source secrets.

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Entry is a LIMIT-zone order on the normal order endpoint; protective exits (STOP_MARKET / TAKE_PROFIT_MARKET legs) go through `POST /fapi/v1/algoOrder` with `algoType=CONDITIONAL` — never the legacy `/fapi/v1/order` conditional assumption. SDK surface (request method names, required/optional params, `ALGO_UPDATE.o.rm` rejection semantics) is re-verified against the installed `binance-sdk-derivatives-trading-usds-futures` version plus the Binance Futures changelog at plan time, following the 08-04 precedent ("no public REST signature change 17.3.1→17.4.0; Algo field semantics are WS-side") — the researcher records the installed version and any delta before execution code is written. User-data WS is the preferred realtime source for order/fill/position events (D002 posture); REST is fallback plus the periodic authoritative reconciliation tick (never WS-only). Ambiguous placement responses follow EXECUTION_SPEC §10 no-blind-recovery: never blind-retry, query by deterministic client/algo ID first (08-03/08-04 query-by-ID posture), retry only if absence is confirmed. — **Reversibility:** one-way — placed live orders and exchange-side fills are permanent financial facts.
- **D-02:** Position mode (one-way vs hedge) is detected dynamically at startup and re-checked at placement time — never assumed, never hard-coded. Protective parameters are mode-correct per EXECUTION_SPEC §5: the one-way pattern (SL `closePosition=true`, TP1 `reduceOnly` + explicit quantity, TP2 `closePosition=true`) is one branch, hedge mode carries explicit `positionSide` with its own parameter constraints, verified against current Algo Order API semantics at implementation time. Partial fills are first-class: remaining entry quantity is cancellable, protective exits are sized against the actual filled quantity (never the planned quantity), and fill events arriving out of order or replayed reconcile to a single position view. Entry-without-protective is a divergence that forces SAFE_MODE via the Phase-8 reconciler (sweeper never places rescue protection). — **Reversibility:** one-way — mode handling and fill-sizing enter live order history permanently.
- **D-03:** Every placement revalidates live constraints from exchangeInfo at placement time: tick/stepSize, min/max qty, notional minimums, plus open algo-order count against the 200-conditional-order-per-symbol limit with operational headroom left (EXECUTION_SPEC §12 — never depend on the removed `MAX_NUM_ALGO_ORDERS` filter). Constraint snapshots carry `metadata_observed_at_utc` with the Phase-5 D-04 registry TTL; stale snapshots fail closed to no new orders. Portfolio caps and DAILY_STOP (`NORMAL / WARNING / DAILY_STOP`, Phase-5 D-03) are evaluated against the live/reconciled position set — never plan-local assumptions — with the same enforcement order (per-trade sizing → cluster cap → aggregate cap → position count → daily state) and first-failing-gate reason code. Uncertain account/risk/reconciliation state fails closed to NO_TRADE with reason code (`STALE_CONSTRAINTS`, `UNCERTAIN_ACCOUNT_STATE`, `DAILY_STOP_BLOCK` vocabulary inherited). — **Reversibility:** costly — revalidation cadence and headroom policy enter the execution safety contract Phase 10 operates.
- **D-04:** Live credentials use no-withdrawal keys with IP allowlisting, secrets encrypted at rest off-source (never in git, never in logs), and paper/test credentials strictly separated from live ones. Deployment default is `LIVE_ORDERS_DISABLED`; live execution requires an explicit operator enable step. Logs are structured (correlation ID, SignalId, client/algo order IDs, symbol, strategy version, UTC timestamp, event type, result) and secret-free — API keys/signatures never logged. Health checks are green before and during live enablement: market-feed freshness, last closed-candle time, WS connection state, user-data stream state, REST error rate, reconciliation drift, DB writes, Telegram delivery, unprotected positions, orphaned orders. Rollout scope is smallest capital in the live-5 universe only (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT); smallest-capital sizing and the enable/disable + manual-close + SAFE_MODE emergency controls (EXECUTION_SPEC §11) are acceptance gates for the first order. — **Reversibility:** costly — credential handling and the enablement gate enter the operational security contract.
- **D-05:** A new execution manager (e.g. `src/execution/` extension at planner discretion — placement, protective attach, fill monitor, expiry/cancel paths) calls the identical Phase-5 `src/risk/` sizing + quantization functions (same inputs → byte-identical outputs incl. reason codes; no live-local sizing), gates every placement on the Phase-8 approval binding (SignalId + strategyVersion + parameterSetId/Hash + plan hash + expiry + authorized chat + one-time token; stale/mismatched/superseded plans unapprovable), reuses the deterministic `src/execution/order_ids.py` derivation for all client/algo IDs (retry/restart/replay-safe), and composes with the three-source reconciler + cancel-only sweeper + SAFE_MODE (any divergence blocks new entries while monitoring continues). Execution internals stay pure (stdlib + `Decimal` only for placement math and ID derivation, UTC datetimes in, deterministic ordering — same contract as `src/execution/order_ids.py`, `src/reconcile/`, `src/risk/`); all SDK imports live in `src/adapters/` (only adapters import the Binance SDK). Every placement, fill, cancel, divergence, and SAFE_MODE transition lands as a JournalEvent with full identity (strategyVersion + parameterSetId + parameterSetHash + SignalId + plan hash + experiment linkage). TDD RED→GREEN with atomic commits; fixtures under `tests/fixtures/phase9/` (placement sequences, partial-fill sizing, both position-mode branches, idempotent retry/restart, headroom-reject, DAILY_STOP-block). — **Reversibility:** costly — module paths, journal shapes, and fixture vocabulary persist in Phase-10 analytics inputs.

### Agent's Discretion
- User runs `--auto --chain` (fully autonomous): all five gray areas auto-resolved to recommended defaults with no interactive prompts. Single-pass cap observed — no re-pass gap-hunting.
- Exact module layout inside `src/execution/`, adapter method additions in `src/adapters/binance_usdm.py`, reconciler tick cadence for the live loop, entry-zone limit-price policy details, TP1/TP2 split mechanics, expiry/invalidation cancel wiring, health-check mechanics, enablement-flag storage, and plan slicing are at planner/researcher discretion, provided D-01–D-05 semantics hold.
- Pre-answered from prior phases (approval binding, PTB polling, three-source reconciler + cancel-only sweeper + SAFE_MODE, deterministic IDs ≤36 chars, RUNBOOK drills, identical engine calls, closed-candle core, risk-owned quantization + DAILY_STOP, six-field identity, adapter isolation, purity contracts, TDD, frozen dataclasses, content-hash IDs, TOML registry, fail-closed, single-Base ORM).

### Deferred Ideas (OUT OF SCOPE)
- Journal depth (MFE/MAE, execution-quality latencies, approval-delay impact) + kill-gate operations → Phase 10.
- Correlation model upgrade (REFN-04), OI/funding as strategy features (REFN-02/REFN-03), 15M refinement (REFN-01), extra families (REFN-05) → v2.
- FastAPI inbound webhook receiver for Telegram callbacks → deferred (V1 uses PTB polling).
- TWAP/VP execution algos (`binance-sdk-algo`) → Phase 3+ evaluation only, not V1.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EXEC-01 | Execution manager places LIMIT-zone entries and Algo-Order protective exits (re-verified against current Binance docs), supports both position modes and partial-fill protective sizing | SDK 17.4.0 signatures verified by introspection; mode-correct parameter matrix (closePosition/reduceOnly/positionSide rules); order_ids + approval + reconciler reuse contracts |
| OPS-02 | Live credentials use no-withdrawal keys, IP allowlisting, off-source secret storage, structured secret-free logging with health checks | SECURITY_AND_OPERATIONS §§1–8 controls; Phase-8 drill harness + SAFE_MODE + structured-logging precedents; env availability audit |

## Project Constraints (from AGENTS.md)

- Determinism: same snapshot + account + strategy version + config = same decision; no repaint, no future-candle leakage, byte-equivalent outputs.
- No-AI core: LLM never decides direction/entry/SL/TP/size/risk/parameters/signal-validity.
- Exchange authority: Binance canonical; user-data WS preferred realtime; dynamic exchangeInfo, Algo-Order endpoints, position-mode detection, 200-conditional-order headroom — all re-verified against current docs, never hard-coded from memory.
- Quantization: floor to stepSize → realized-risk check (60% baseline) → min-qty/notional reject → NO_TRADE over round-up; identical backtest/paper/live.
- Approval safety: explicit, auditable, idempotent, expiring; at-least-once replay; no auto-approve; stale plans unapprovable.
- Fail closed: uncertain data/connection/account/risk → NO_TRADE; SAFE_MODE blocks entries.
- Stack: Python 3.13 + uv (`uv run --python 3.13`); official Binance connector 3.10+ behind adapters; FastAPI edge-only; PostgreSQL + Parquet/DuckDB; Polars/pandas/NumPy/SciPy; VectorBT exploratory-only; pytest+Ruff+mypy; Docker; Decimal/tick arithmetic for exchange-sensitive values.
- Purity: core/risk/backtest/reconcile/execution stay dependency-free (stdlib + `Decimal`); only adapters import the Binance SDK.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Entry/protective placement decisions (what/when/how much) | Execution manager (`src/execution/`, pure) | — | Deterministic math must be testable without network; SDK never imported here |
| Wire transport (REST calls, response projection) | Adapter (`src/adapters/binance_usdm.py`) | — | Sole SDK importer; projects SDK models to frozen Decimal/UTC dataclasses |
| Fill/position realtime events | User-data WS consumer | Adapter | D002 posture: WS preferred realtime, REST fallback + periodic authoritative tick |
| Approval authorization gate | `src/approval/binding.py` (pure) | — | Fixed gate order chat→expiry→hash→version→token; placement calls it, never reimplements |
| Divergence detection + SAFE_MODE | `src/reconcile/` (pure) | — | Cancel-only sweeper; sweeper never places rescue protection |
| Credential storage, enablement flag, health | Ops/runtime edge | — | Off-source secrets, `LIVE_ORDERS_DISABLED` default, health checklist per SECURITY_AND_OPERATIONS §4 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `binance-sdk-derivatives-trading-usds-futures` | **17.4.0 installed** [VERIFIED: `uv run` metadata this session]; pin `>=17.3,<18` | All REST placement/query/cancel + position-mode read | Official SDK; covers `new_order`, `new_algo_order` (CONDITIONAL), `query_order`, `cancel_algo_order`, `current_all_algo_open_orders`, `get_current_position_mode`, `position_information_v3` |
| `src/risk/` (`sizing`, `quantization`, `portfolio`, `gating`) | in-repo, frozen | Identical sizing/quantization/caps/DAILY_STOP | D-05: placement calls `evaluate_risk` identically — no live-local sizing |
| `src/execution/order_ids.py` | in-repo, pinned | Deterministic `x-`/`xa-` 36-char IDs | Retry/restart/replay-safe dedup; charset is strict subset of Binance rule |
| `src/approval/` + `src/reconcile/` | in-repo, frozen | Auth gate + three-source compare + SAFE_MODE | Phase-8 hardened contracts; placement composes, never duplicates |
| tenacity | >=9 (in lockfile) | Bounded retries on adapter cancel/query paths | Existing ceilings precedent (3 attempts / 30s); never infinite on order paths |
| structlog | >=25 (in lockfile) | Structured secret-free lineage logs | Correlation ID + SignalId + IDs + symbol + version + UTC + event + result |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| SQLAlchemy 2.0.x + psycopg 3 + Alembic | in lockfile | Order/Fill/Position/JournalEvent persistence | Any new execution-lifecycle migration follows single-Base + parity-gate discipline |
| python-telegram-bot 22.x | in lockfile | Live status updates (placement/fill/divergence) | Reuse `telegram_notify.py` send-only posture; callbacks unchanged |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Official SDK placement | Direct httpx REST | Only where SDK lacks an operation; SDK owns the wire by default |
| `closePosition=true` SL (one-way) | Explicit-quantity SL with reduceOnly | Explicit qty needed for TP1 anyway; close-all SL is the EXECUTION_SPEC §5 one-way pattern — keep it, but verify coexistence with TP1/TP2 legs (Open Question 1) |
| Manual cancel on expiry | GTD `goodTillDate` entry | GTD auto-cancel exists (`goodTillDate` must be > now+600s) [CITED: Binance New Order docs]; planner chooses, manual cancel is the EXECUTION_SPEC §4-explicit path |

**Installation:** none — all dependencies already in `pyproject.toml` / lockfile. No `uv add` required for this phase.

**Version verification:** `binance-sdk-derivatives-trading-usds-futures` → **17.4.0** [VERIFIED: `uv run --python 3.13 python -c "import importlib.metadata..."` this session]. 08-04 docstring already records 17.4.0; delta 17.3.1→17.4.0 remains "no public REST signature change in touched methods" [VERIFIED: `inspect.signature` on `new_order`, `new_algo_order`, `get_current_position_mode`, `query_order`, `cancel_algo_order`, `current_all_algo_open_orders`, `query_algo_order` this session].

## Package Legitimacy Audit

No new external packages are recommended or required by this research — the phase extends the in-repo execution manager + adapter using the already-pinned SDK. Gate skipped with reason: zero-install phase.

| Package | Registry | Verdict | Disposition |
|---------|----------|---------|-------------|
| (none — no installs) | — | — | — |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none.

## Architecture Patterns

### System Architecture Diagram

```text
Approved plan (SignalId + version + paramSet + plan_hash + expiry + token)
  ↓  [1. approval binding gate: chat→expiry→hash→version→token]
evaluate_risk (identical Phase-5 pipeline, live ConstraintSnapshot + reconciled positions)
  ↓  PASS with quantized qty / FAIL with reason code (NO_TRADE)
Placement-time revalidation (exchangeInfo tick/step/notional + algo-count headroom + position mode)
  ↓
ENTRY: new_order(LIMIT, qty, price, new_client_order_id=x-…) ──ambiguous?──→ query_order by orig_client_order_id → retry only if absent
  ↓  (fill monitor: user-data WS preferred + REST tick; partials → size protectives to FILLED qty)
PROTECTIVES: new_algo_order(algoType=CONDITIONAL, STOP_MARKET SL + TAKE_PROFIT_MARKET TP1/TP2, client_algo_id=xa-…)
  ↓
Three-source reconciler (local vs open normal vs open algo vs positions) → divergence → SAFE_MODE (entries blocked, monitoring continues)
  ↓
JournalEvent per transition (placement/fill/cancel/divergence/SAFE_MODE) + Telegram status + health checks
```

### Recommended Project Structure
```text
src/
├── execution/
│   ├── __init__.py          # existing
│   ├── order_ids.py         # frozen — reuse as-is
│   ├── manager.py           # NEW: approve→risk→revalidate→place→attach pipeline (pure orchestration, Protocol-typed deps)
│   ├── placement.py         # NEW: placement math (Decimal only: protective sizing from FILLED qty)
│   ├── fill_monitor.py      # NEW: fill-event folding (out-of-order/replay → single position view)
│   └── enablement.py        # NEW: LIVE_ORDERS_DISABLED gate + emergency controls (§11)
├── adapters/
│   └── binance_usdm.py      # EXTEND: place_entry / place_algo_protective / query_order_by_client / get_position_mode
├── risk/ approval/ reconcile/ # reuse verbatim — no changes expected
└── ops/
    └── health.py            # NEW (or extend): §4 checklist probes
tests/fixtures/phase9/      # placement sequences, partial-fill sizing, mode branches, retry/headroom/DAILY_STOP cases
```

### Pattern 1: Adapter-edge placement with Decimal→float conversion at the boundary
**What:** Execution core computes everything in `Decimal`; the adapter converts to the SDK's `float` params via `float(str(d))` on already-quantized values, and projects responses back to `Decimal`/`UTC` frozen dataclasses.
**When to use:** Every new adapter placement method.
**Example:**
```python
# Source: SDK signatures verified by inspect.signature on installed 17.4.0 this session
response = await asyncio.to_thread(
    self._sdk.rest_api.new_order,
    symbol=symbol,  # str
    side=side,  # NewOrderSideEnum.BUY/SELL
    type=type,  # NewOrderTypeEnum.LIMIT
    position_side=position_side,  # "BOTH" one-way / "LONG"/"SHORT" hedge (mandatory in hedge) [CITED: Binance New Order docs]
    time_in_force=time_in_force,  # GTC (LIMIT requires timeInForce+quantity+price) [CITED: Binance New Order docs]
    quantity=float(str(qty)),  # quantized Decimal → float at the edge only
    price=float(str(price)),
    new_client_order_id=client_order_id,  # deterministic x-… 36-char [VERIFIED: src/execution/order_ids.py:37-51]
)
```

### Pattern 2: Mode-correct CONDITIONAL protective legs
**What:** One branch per position mode; never send `reduceOnly` in hedge mode; never combine `closePosition=true` with quantity/reduceOnly.
**When to use:** `place_algo_protective` for SL/TP1/TP2.
```python
# Source: Binance New-Algo-Order semantics [CITED: developers.binance.com/trade/rest-api/Current-All-Algo-Open-Orders excerpts + connector-js NewAlgoOrderRequest docs]
# One-way:  SL  = new_algo_order(algoType=CONDITIONAL, type=STOP_MARKET,  close_position=True)   # no quantity, no reduceOnly
#           TP1 = new_algo_order(algoType=CONDITIONAL, type=TAKE_PROFIT_MARKET, quantity=.., reduce_only=True, trigger_price=..)
#           TP2 = new_algo_order(algoType=CONDITIONAL, type=STOP_MARKET/TAKE_PROFIT_MARKET, close_position=True)
# Hedge:    same legs + position_side="LONG"/"SHORT" mandatory, reduceOnly OMITTED everywhere,
#           closePosition=true forbidden on BUY-in-LONG / SELL-in-SHORT sides.
```

### Pattern 3: Query-by-ID no-blind-recovery
**What:** On ambiguous placement response: `query_order(symbol, orig_client_order_id=…)` / `query_algo_order(client_algo_id=…)` first; place only if absence confirmed. SDK supports both probes [VERIFIED: signatures this session; `query_algo_order_by_client` already in adapter].
**When to use:** Every placement path, including restarts (deterministic IDs make this replay-safe).

### Anti-Patterns to Avoid
- **Placing rescue protection from the sweeper:** sweeper stays cancel-only; entry-without-protective → SAFE_MODE + HIGH alert, never auto-attach (D-02, EXECUTION_SPEC §6).
- **Sizing protectives to planned quantity:** always size to actual filled quantity; partial fills are the norm, not the edge case (D-02).
- **Caching position mode or exchangeInfo:** detect mode at startup AND re-check at placement; snapshots carry TTL and stale fails closed (D-02/D-03).
- **Trusting WS-only state:** user-data WS is preferred realtime but the periodic REST truth tick is mandatory (08-04 T-8-33).
- **Logging raw SDK responses or tokens:** raw token never persisted/logged (08-01 D-02); API keys/signatures never logged (SECURITY §1/§6).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Order placement/transport | Custom HMAC REST client | Official SDK 17.4.0 behind adapter | Signing, recvWindow, weights, error taxonomy; direct HTTP only for SDK gaps |
| Position-mode source of truth | Config flag / assumption | `get_current_position_mode` at startup + placement | Account-level setting rejectable with open orders; hard-coding forks live behavior |
| Retry/backoff | Hand-rolled sleep loops | tenacity bounded retry (transient-only predicate) | Existing `_cancel_retry_predicate` precedent; infinite retry on order paths is a safety bug |
| Structured logging | Custom logger / print | structlog JSON lineage schema | Correlation ID + identity fields are the audit trail Phase 10 consumes |
| Secrets handling | Env files in repo / config constants | Off-source encrypted secrets, paper/live separated | SECURITY §1; `LIVE_ORDERS_DISABLED` default + explicit enable step |
| Client-order-ID uniqueness | UUID/random per attempt | `derive_client_order_id` / `derive_algo_client_id` | Exchange-side dedup requires deterministic reuse across retry/restart/replay |

**Key insight:** Every live-safety property in this phase (idempotency, mode-correctness, fail-closed) already exists as a hardened in-repo contract — the phase's job is composition + adapter extension, not invention.

## Common Pitfalls

### Pitfall 1: Hedge-mode `reduceOnly` rejection
**What goes wrong:** Protective legs copied from the one-way template send `reduceOnly=true` in hedge mode → exchange rejects → position unprotected.
**Why it happens:** Binance forbids `reduceOnly` in Hedge Mode on both normal and algo endpoints [CITED: Binance New Order + New-Algo-Order docs].
**How to avoid:** Mode branch omits `reduceOnly` entirely in hedge; TP1 uses explicit quantity + `positionSide` instead. Cover both branches in `tests/fixtures/phase9/`.
**Warning signs:** `-1102`/`-1111`-class param errors on algo placement in testnet/hedge rehearsal.

### Pitfall 2: `closePosition=true` combined with quantity
**What goes wrong:** SL leg sends both `closePosition=true` and `quantity` → rejected.
**Why it happens:** Close-All is mutually exclusive with quantity/reduceOnly, and only valid with STOP_MARKET/TAKE_PROFIT_MARKET [CITED: Binance New-Algo-Order docs].
**How to avoid:** SL/TP2 close-all legs pass quantity=None; adapter asserts this before calling (fail-closed at the edge).
**Warning signs:** Algo placement 400 with closePosition/quantity conflict message.

### Pitfall 3: TP1 partial + TP2 close-all interaction
**What goes wrong:** After TP1 takes part of the position, TP2 `closePosition=true` semantics vs remaining quantity — mis-sized TP2 leaves dust or over-closes.
**Why it happens:** Close-All closes "all current" at trigger time, which is correct for the remainder but must be reasoned about after partial TP1 fills [ASSUMED — needs testnet confirmation].
**How to avoid:** Sequence fixtures: full-fill, partial-entry, TP1-then-TP2; confirm TP2 close-all closes the remainder on testnet before live.
**Warning signs:** Residual dust positions after TP2 trigger in rehearsal.

### Pitfall 4: float Leakage into placement math
**What goes wrong:** SDK takes `float` qty/price; converting early poisons quantization.
**Why it happens:** `new_order`/`new_algo_order` accept `quantity: float | None` [VERIFIED: inspect.signature].
**How to avoid:** Convert once at the adapter boundary via `float(str(quantized_decimal))`; execution core never sees float (AST no-`float(` guard scope extended).
**Warning signs:** mypy/ruff violations; qty differing from `quantize()` output in fixtures.

### Pitfall 5: Headroom miscount against the 200-algo limit
**What goes wrong:** Planner counts only own legs; account-level 200-per-symbol cap hit → protective placement rejected → unprotected position.
**Why it happens:** Limit is per-symbol account-wide, filter removed from exchangeInfo Dec 2025 — must count `current_all_algo_open_orders(symbol)` live [CITED: EXECUTION_SPEC §12 + Binance changelog].
**How to avoid:** Placement gate queries open algo count per symbol, requires headroom for ALL planned legs (entry + 3 protectives minimum), else `EXCHANGE_CONSTRAINT` NO_TRADE.
**Warning signs:** Algo rejects with limit-violation code during multi-position holds.

### Pitfall 6: Stale fill view double-sizes protectives
**What goes wrong:** Replayed/out-of-order fill events counted twice → protective qty exceeds position → rejects or over-close.
**Why it happens:** At-least-once delivery on user-data streams.
**How to avoid:** Fill monitor folds events idempotently keyed by (order ID + trade ID) — mirrors `FillRow` unique (order_id, exchange_trade_id) precedent [VERIFIED: STATE.md 03-04 decision]; single position view per symbol+side.
**Warning signs:** Protective qty ≠ exchange position_amt in reconciler diff.

## Code Examples

### LIMIT-zone entry placement (adapter)
```python
# Source: SDK new_order signature [VERIFIED: inspect.signature, installed 17.4.0] + client-ID rule ^[.A-Z:/a-z0-9_-]{1,36}$ [CITED: Binance New Order docs]
resp = await adapter.place_entry(
    symbol="BTCUSDT",
    side="BUY",
    position_side="BOTH",  # or LONG/SHORT in hedge
    quantity=quantized_qty,
    price=limit_price,
    time_in_force="GTC",
    client_order_id=derive_client_order_id(plan_hash=ph, role="ENTRY"),
)
# Ambiguous response → query_order(symbol=symbol, orig_client_order_id=...) before any retry (EXECUTION_SPEC §10).
```

### CONDITIONAL protective leg (adapter)
```python
# Source: SDK new_algo_order signature [VERIFIED: inspect.signature] — algoType enum is CONDITIONAL-only [VERIFIED: NewAlgoOrderAlgoTypeEnum]
resp = await adapter.place_algo_protective(
    algo_type="CONDITIONAL",
    symbol="BTCUSDT",
    side="SELL",
    type="STOP_MARKET",
    trigger_price=sl_trigger,
    close_position=True,
    working_type="MARK_PRICE",
    client_algo_id=derive_algo_client_id(plan_hash=ph, role="STOP_LOSS"),
)
# STOP/TAKE_PROFIT (non-MARKET) variants accept timeInForce (default GTC) + price [CITED: Binance New-Algo-Order notes].
```

### Position-mode detection (adapter)
```python
# Source: get_current_position_mode(recv_window=None) [VERIFIED: inspect.signature, installed 17.4.0]
mode = await adapter.get_position_mode()  # One-way (positionSide BOTH) vs Hedge (LONG/SHORT)
# Re-check at placement time per D-02; never cache across placements.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| STOP_MARKET/TP via `POST /fapi/v1/order` | CONDITIONAL legs via `POST /fapi/v1/algoOrder` (Algo Service) | Dec 2025 migration | Legacy conditional assumption hard-fails; D-01 mandates algo endpoint |
| `CONDITIONAL_ORDER_TRIGGER_REJECT` WS event | Rejection reasons inside `ALGO_UPDATE.o.rm` | Dec 15 2025 deprecation | Fill/reject monitor must parse `ALGO_UPDATE`, not the old event |
| `MAX_NUM_ALGO_ORDERS` exchangeInfo filter | 200-open-conditional-order limit per symbol | Dec 2025 | Headroom must be counted live via `current_all_algo_open_orders`, never read from a filter |
| Legacy `binance-connector` / `binance-futures-connector` | `binance-sdk-derivatives-trading-usds-futures` 17.4.0 | Archived 2026-04-30 | Never use legacy connectors (AGENTS.md What-NOT-to-use) |

**Deprecated/outdated:**
- `CONDITIONAL_ORDER_TRIGGER_REJECT` event: gone; use `ALGO_UPDATE`.
- `MAX_NUM_ALGO_ORDERS` filter: removed; use live algo-count + headroom.
- Margin check before conditional trigger: no longer performed post-migration — sizing/risk math is the only pre-trigger guard [CITED: Binance Dec 2025 changelog].

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | TP1-partial then TP2 close-all closes exactly the remainder with no dust | Pitfall 3 | Dust positions accumulate; needs testnet confirmation before live |
| A2 | Entry expiry via explicit cancel wiring (GTD as planner-chosen alternative) | Alternatives | LIMIT left open indefinitely violates EXECUTION_SPEC §4; planner must pick one |
| A3 | Live-5 universe = BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT (from CONTEXT D-04) | Summary/D-04 | Planner must treat as locked scope, not research suggestion |
| A4 | `ALGO_UPDATE.o.rm` rejection parsing can reuse the existing WS supervision shape from `src/paper/` | Patterns | If WS payload shape differs, adapter needs a new projection type |

## Open Questions

1. **TP1/TP2 split mechanics (quantity fractions, trigger vs limit price on TAKE_PROFIT legs)?**
   - What we know: TP1 uses explicit quantity + reduceOnly (one-way); TP2 close-all; planner owns zone/TP levels from Phase-4 contract.
   - What's unclear: Exact split fractions and whether TP legs useMARKET vs limit-price variants.
   - Recommendation: Planner discretion per CONTEXT; fixtures pin whatever is chosen.
2. **Entry-zone limit-price policy (zone edge vs mid, time-in-force, GTD vs manual cancel)?**
   - What we know: LIMIT-zone V1 style; LIMIT requires timeInForce+quantity+price; GTD needs `goodTillDate` > now+600s.
   - What's unclear: Which price/TIF the strategy wants.
   - Recommendation: Planner discretion; default GTC + explicit expiry-cancel wiring (EXECUTION_SPEC §4 lists 5 cancel triggers).
3. **Reconciler tick cadence for the live loop?**
   - What we know: 60s precedent (`SAFE_MODE_TICK_SECONDS`, notify/resync ceilings).
   - What's unclear: Whether live placement wants a tighter tick.
   - Recommendation: Keep 60s default; rate-limit budget favors it for 4H/1H swing cadence.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 + uv | All work | ✓ | 3.13 / SDK 17.4.0 verified | — |
| `binance-sdk-derivatives-trading-usds-futures` | Placement/query/cancel | ✓ | 17.4.0 | — |
| tenacity / structlog / SQLAlchemy / PTB | Retries / logs / persistence / notify | ✓ | in lockfile | — |
| Live Binance credentials (no-withdrawal + allowlist) | First live order | ✗ (expected) | — | Testnet rehearsal first; operator provisions before enablement |
| Telegram bot token + authorized chat | Live status/approval | ✗ (08-02 LIVE-TAP GATE pending) | — | Same gate blocks live; must clear before Phase 9 acceptance |

**Missing dependencies with no fallback:**
- Live credentials + Telegram tap confirmation must be operator-provisioned; planner must add explicit enablement/checkpoint tasks (cannot be fabricated in fixtures).

**Missing dependencies with fallback:**
- None — testnet + fakes cover all pre-live verification.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9 + pytest-asyncio (auto mode) |
| Config file | `pyproject.toml` (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| Quick run command | `uv run --python 3.13 pytest tests/ -q -x` |
| Full suite command | `uv run --python 3.13 pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| EXEC-01 | LIMIT entry + CONDITIONAL protectives placed with deterministic IDs | unit (fake adapter) | `pytest tests/test_execution_manager.py -x` | ❌ Wave 0 |
| EXEC-01 | Both position-mode branches (one-way close-all vs hedge explicit side) | unit | `pytest tests/test_execution_modes.py -x` | ❌ Wave 0 |
| EXEC-01 | Protectives sized to filled qty on partials; idempotent retry/restart | unit | `pytest tests/test_execution_partials.py -x` | ❌ Wave 0 |
| EXEC-01 | Headroom reject + no-blind-recovery query-by-ID | unit | `pytest tests/test_execution_gates.py -x` | ❌ Wave 0 |
| OPS-02 | `LIVE_ORDERS_DISABLED` default; enablement + emergency controls; secret-free logs | unit | `pytest tests/test_execution_enablement.py -x` | ❌ Wave 0 |
| OPS-02 | DAILY_STOP on live reconciled state; stale snapshot fail-closed | unit | `pytest tests/test_execution_gates.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run --python 3.13 pytest tests/ -q -x`
- **Per wave merge:** full suite + `ruff check` + `mypy src`
- **Phase gate:** Full suite green + testnet placement rehearsal before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/fixtures/phase9/` — placement sequences, partial-fill sizing, mode branches, retry/headroom/DAILY_STOP rejects (byte-exact golden files)
- [ ] `tests/test_execution_*.py` — manager, modes, partials, gates, enablement suites (names at planner discretion)
- [ ] Testnet rehearsal task — real LIMIT + CONDITIONAL round-trip on smallest qty before live enablement
- [ ] 08-02 LIVE-TAP GATE clearance (Telegram token + chat) — prerequisite for live acceptance

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | No-withdrawal API keys + IP allowlisting; paper/live credential separation |
| V3 Session Management | yes | User-data listen-key lifecycle (heartbeat/keepalive/reconnect per SECURITY §3/§8) |
| V4 Access Control | yes | `LIVE_ORDERS_DISABLED` default + explicit operator enable; approval binding gate before any placement |
| V5 Input Validation | yes | Frozen Decimal/UTC dataclasses at adapter edge; deterministic-ID validation; exchangeInfo revalidation |
| V6 Cryptography | yes | Secrets encrypted at rest off-source, never in git/logs; raw approval tokens hashed (SHA-256), never persisted |
| V7 Error Handling/Logging | yes | Secret-free structured logs; fail-closed reason codes; no stack-trace secret leakage |
| V9 Communications | yes | TLS via SDK; webhook auth deferred (PTB polling in V1) |
| V10 Malicious Code | no | No third-party code added this phase |
| V14 Configuration | yes | Locked deps (`uv.lock`), Python 3.13 pinned, SDK 17.4.0 pinned; upgrades re-verified + rehearsed on testnet |

### Known Threat Patterns for Live-Execution Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Leaked/withdrawable API key | Spoofing / Elevation | No-withdrawal keys + IP allowlist + off-source encrypted secrets + paper/live separation |
| Replay of APPROVE callback → duplicate orders | Repudiation / Tampering | One-time token-hash binding + deterministic IDs (exchange dedup) + query-by-ID no-blind-retry |
| Stale plan approved after invalidation | Tampering | Expiry + plan-hash + version/param-set binding; stale/mismatched/superseded unapprovable |
| Unprotected position (protective rejected silently) | Denial of service / Tampering | Protective-confirmation requirement (§6) + reconciler ENTRY_WITHOUT_PROTECTIVE → SAFE_MODE + HIGH alert |
| Orphan protective triggers on zero position | Tampering | Cancel-only sweeper with two-read zero verification + journal pre/post-image |
| Secret leakage via logs | Information disclosure | structlog schema allowlist; raw tokens/keys/signatures never logged; review gate on log-call sites |

## Sources

### Primary (HIGH confidence)
- Installed `binance-sdk-derivatives-trading-usds-futures` 17.4.0 — `inspect.signature` on `new_order`, `new_algo_order`, `get_current_position_mode`, `query_order`, `cancel_algo_order`, `current_all_algo_open_orders`, `query_algo_order` + `NewAlgoOrderAlgoTypeEnum`/`NewAlgoOrderTypeEnum`/`NewOrderTypeEnum`/`NewAlgoOrderSideEnum`/`WorkingType`/`TimeInForce` enumerations (this session).
- `src/execution/order_ids.py:37-51` (ROLE_CODES, 36-char shapes), `src/adapters/binance_usdm.py` docstring + reconciler surface, `src/approval/binding.py:1-60` (gate order), `src/risk/gating.py:27-63` (evaluate_risk parity), `src/reconcile/safe_mode.py:29-41` (60s tick), `src/domain/enums.py` (OrderRole, RejectionReason, DailyState) — all read this session.
- `docs/trading/EXECUTION_SPEC.md` §§1–12, `docs/operations/SECURITY_AND_OPERATIONS.md` §§1–10, `docs/integration/BINANCE.md` §§1–11 (project-canonical).

### Secondary (MEDIUM confidence)
- Binance New-Algo-Order + New-Order REST docs via web search excerpts (algoType=CONDITIONAL required; closePosition/reduceOnly/positionSide constraints; client-ID regex `^[.A-Z:/a-z0-9_-]{1,36}$`; LIMIT mandatory params; GTD rules) — cross-checked against installed SDK enums.
- Binance changelog excerpts (Dec 2025 Algo migration; `CONDITIONAL_ORDER_TRIGGER_REJECT` deprecation Dec 15 2025; 200-per-symbol conditional limit; `MAX_NUM_ALGO_ORDERS` removal; no pre-trigger margin check) — consistent with EXECUTION_SPEC §§2/12 and 08-04 record.
- Binance Connector-JS `NewAlgoOrderRequest`/`NewAlgoOrderResponse` interface docs (reduceOnly-forbidden-in-hedge, positionSide-mandatory-in-hedge, closePosition semantics) — mirrors REST docs above.

### Tertiary (LOW confidence)
- None — no unverified-standalone claims remain; open uncertainties are logged in Assumptions (A1–A4).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — installed SDK introspected this session; all other deps in lockfile.
- Architecture: HIGH — reuse contracts read in-repo; adapter extension points identified.
- Pitfalls: HIGH — mode/param rules CITED from official docs and cross-checked with SDK enums; one testnet-confirmation item flagged (A1).

**Research date:** 2026-09-28
**Valid until:** ~30 days for stack/architecture; Binance endpoint semantics must still be re-checked at implementation time per D-01 (exchange-side changes are the residual risk).
