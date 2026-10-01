# Phase 8: Approval + Reconciliation Hardening - Research

**Researched:** 2026-09-27
**Domain:** Telegram approval loop (python-telegram-bot) + Binance USDⓈ-M reconciliation (Algo/conditional orders, positions) + deterministic idempotency + RUNBOOK drill harness
**Confidence:** HIGH

## Summary

Phase 8 hardens the Phase-7 SIMULATE-only notification path into a fully bound, idempotent APPROVE/SKIP loop and adds the exchange-truth reconciliation safety net that Phase 9 live rollout depends on. The building blocks already exist in-repo: the frozen `Approval` entity with `approval_token_hash` + WR-07 coherence, the journal-first `notify_simulate` sender with bounded tenacity retries, the `TelegramBot` Protocol seam with the 64-byte-safe short-id scheme, the three-identifier `Order` entity, and the fail-closed risk gates that SAFE_MODE composes with.

The installed environment is ready: `python-telegram-bot` 22.8 and `binance-sdk-derivatives-trading-usds-futures` 17.4.0 are both in the project venv (SDK is one minor ahead of the STACK doc's 17.3.1 — inside the `>=17.3,<18` floor, but the planner must re-read the 17.4 changelog before wiring). All three reconciler REST endpoints plus the cancel path were confirmed present on the installed SDK class this session, and the `Application.run_polling` + `CallbackQueryHandler` intake surface was confirmed on installed PTB 22.8. No new external packages are needed — token hashing, HMAC comparison, and ID derivation are stdlib (`hashlib`/`secrets`/`hmac`).

**Primary recommendation:** Build approval-first (`src/approval/` pure core: bind → replay → expiry gates, all stdlib+Decimal), then the PTB polling receiver as a thin extension of `src/adapters/telegram_notify.py`, then the reconciler/sweeper/SAFE_MODE slice against the three verified SDK methods, then the drill harness — each slice with `tests/fixtures/phase8/` golden files (replay sequences, injected-orphan scenarios, retry/restart determinism, drill logs).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Every approval binds SignalId + strategyVersion + parameterSetId/Hash + plan hash + expiry + authorized chat + one-time token. The raw token is never persisted or logged — only its hash on `Approval.approval_token_hash`. A replayed callback resolves to the existing Approval (WR-07 coherence holds: PENDING ⟺ `acted_at_utc` is None), so 5× duplicate-callback replay produces exactly one state transition. Stale plans (past expiry, plan-hash mismatch, superseded signal) are unapprovable with a reason code. Notification failure leaves the approval PENDING — never auto-approves (Phase-7 D-05 posture extended to the approval path).
- **D-02:** Inbound callbacks arrive via a `python-telegram-bot` Application (polling) behind `src/adapters/` — same single-asyncio-loop precedent as the WS supervisor, no new inbound HTTP surface in V1 (FastAPI stays webhook/health edge only). The authorized-chat gate runs first: unknown chats are rejected before touching any state. `callback_data` stays within the 64-byte limit via the short-id scheme (`sha256(signal_id)[:32]`, Phase-7 CR-05); Phase 8 adds the server-side short→full mapping so callbacks resolve to SignalId + plan. Every callback receipt is journaled as a JournalEvent (at-least-once audit trail). Only `src/adapters/` imports `python-telegram-bot`; the approval core consumes a Protocol-typed bot, mirroring the Phase-7 `TelegramBot` seam.
- **D-03:** The reconciler compares local open-intent state against three Binance-truth sources: open normal orders, open algo (conditional) orders, and positions — user-data WS preferred realtime, REST fallback (D002 posture). An orphan (protective without a live entry, entry without its protective) is swept by cancelling the orphan protective; the reconciler never places orders. Any divergence forces SAFE_MODE: new entries blocked while monitoring and reconciliation continue. Check cadence (scheduled tick, not per-event) is at the planner's discretion. The injected-orphan/divergence drill is the EXEC-02 acceptance proof.
- **D-04:** `client_order_id` / `algo_client_id` derive deterministically from the plan hash + order role (entry vs protective leg), so retries, restarts, and replayed events reuse the same identifier and the exchange dedups them — duplicate entry orders are structurally impossible, not just unlikely. Entry vs protective roles never collide. The exact derivation scheme (prefix + plan-hash slice + role code) is at the planner's discretion, verified by a retry/restart/replay acceptance test. Fits the DATA_MODEL §2.7 three-identifier fields (`client_order_id`, `exchange_order_id`, `algo_client_id`).
- **D-05:** Every RUNBOOK drill is rehearsed and logged before live enablement: unprotected, orphan, duplicate, API-down, stale-feed, DB-failure, manual-close, restore. Rehearsal uses simulated/injected faults — never real unprotected exposure. Each drill lands as a JournalEvent with its outcome; the drill log is the OPS-01 acceptance artifact. SAFE_MODE semantics: blocks new entries, monitoring + reconciliation continue, exit only via the rehearsed restore path.

### The agent's Discretion
- Exact module layout (e.g. new `src/approval/` vs `src/paper/` extension, reconciler/orphan-sweeper/SAFE_MODE splits), callback receiver structure inside `src/adapters/`, short→full mapping storage (PG row vs in-memory + journal), reconciler tick cadence, order-ID derivation scheme details, drill-harness mechanics, and plan slicing (approval-first vs reconciliation-first) are at the planner/researcher discretion, provided D-01–D-05 semantics hold.
- ApprovalResult value set (PENDING/APPROVED/SKIPPED/EXPIRED) was a planner assumption (D-10, user confirmation pending per STATE.md) — carried forward as locked for Phase 8 scope; planner must not relitigate it.

### Deferred Ideas (OUT OF SCOPE)
- Live Algo exits + placement-time revalidation → Phase 9; journal depth (MFE/MAE, execution-quality latencies, approval-delay impact) + kill-gate operations → Phase 10.
- FastAPI inbound webhook receiver for Telegram callbacks → deferred (V1 uses PTB polling; revisit only with a measured need).
- Correlation model upgrade (REFN-04), OI/funding as strategy features (REFN-02/REFN-03), 15M refinement (REFN-01), extra families (REFN-05) → v2 requirements, not Phase 8.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| APRV-01 | Telegram alerts (SIMULATE/APPROVE/SKIP) carrying the 12-field set (symbol, direction, setup, entry, SL, TP(s), RR, risk %, expiry, invalidation, exposure, reason codes) | `format_simulate` 12-field renderer proven in Phase 7; PTB `Application` + `CallbackQueryHandler` + `answer()` intake pattern verified on installed 22.8; 64-byte `callback_data` limit confirmed |
| APRV-02 | Approval bound to SignalId + version + plan hash + expiry + chat + one-time token, idempotent across at-least-once replays, no auto-approve | Frozen `Approval` + `approval_token_hash` + WR-07 coherence verified in-repo; token-hash + constant-time-compare + replay-to-existing patterns documented below |
| EXEC-02 | Reconciliation loop vs open normal + open algo orders + positions, orphan sweep, SAFE_MODE on divergence | All three REST truth endpoints + cancel path verified present on installed SDK 17.4.0; `ALGO_UPDATE.o.rm` rejection semantics + 200-order headroom confirmed from Binance docs |
| EXEC-03 | Deterministic client/algo order IDs across retries, restarts, replays | Derivation scheme (prefix + plan-hash slice + role code) using stdlib `hashlib`; fits the three-identifier `Order` fields verified in-repo |
| OPS-01 | SAFE_MODE blocks entries while monitoring continues; RUNBOOK 8-drill rehearsal before live | `SystemMode.SAFE_MODE` enum + fail-closed gates verified in-repo; drill-harness mechanics + per-drill fault-injection mapping documented below |
</phase_requirements>

## Project Constraints (from AGENTS.md)

- **Determinism:** same snapshot + account + strategy version + config = same decision; no repaint, no future-candle leakage, prefix-invariant, byte-equivalent outputs. Approval/replay/ID-derivation logic must be pure and deterministic.
- **No-AI core:** LLM never decides direction/entry/SL/TP/size/risk/parameters/signal-validity. Phase 8 logic is mechanical (binding checks, replay resolution, set comparison) — compliant by construction.
- **Exchange authority:** Binance canonical; user-data WS preferred realtime, REST fallback; dynamic exchangeInfo; Algo-Order endpoints; position-mode detection; 200-conditional-order headroom — re-verified against current docs, never hard-coded from memory.
- **Quantization/Decimal:** `Decimal`/tick arithmetic for all exchange-sensitive values; `float(` forbidden in core (AST guards + mypy strict).
- **Approval safety:** explicit, auditable, idempotent, expiring; at-least-once replay to existing state; no auto-approve; stale/invalid unapprovable.
- **Fail closed:** uncertain data/connection/account/risk → NO_TRADE; SAFE_MODE blocks entries while monitoring/reconciliation continues.
- **Tech stack:** Python 3.13, asyncio single loop, official Binance SDK behind adapters, FastAPI edge-only, PostgreSQL + Parquet/DuckDB, pytest+Ruff+mypy, TDD.
- **Adapter isolation:** only `src/adapters/` imports `python-telegram-bot` / Binance SDK; core/paper/approval packages stay dependency-free (stdlib + `Decimal` + `src/core/_decimal.py` only).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Approval binding + replay resolution | API / Backend (in-process approval core) | — | Pure deterministic state machine; no exchange or Telegram types cross the boundary |
| Telegram callback intake (polling) | API / Backend edge (`src/adapters/`) | — | I/O adapter translating `Update` → domain callback intent; PTB types never leak inward |
| Reconciliation compare + orphan sweep | API / Backend (reconciler) | — | Compares local intent vs exchange truth; cancel-only — never places orders |
| SAFE_MODE enforcement | API / Backend (risk gates) | — | Composes with existing fail-closed gates (`evaluate_risk`, DAILY_STOP); blocks entries, monitoring continues |
| Approval/callback/mapping persistence | Database / Storage (PostgreSQL via single-Base ORM) | — | ACID transitions, unique constraints on token hash / short-id mapping |
| Drill rehearsal + drill log | API / Backend (drill harness) | Database (JournalEvent rows) | Injected faults + journaled outcomes; OPS-01 acceptance artifact |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `python-telegram-bot` | 22.8 (installed, verified this session via `uv pip show`) [VERIFIED: project venv] | APPROVE/SKIP callback intake via `Application` polling + `CallbackQueryHandler` | asyncio-native since v20, fits the single-loop architecture; already the locked Phase-7 sender; Bot API 10.0 |
| `binance-sdk-derivatives-trading-usds-futures` | 17.4.0 (installed, verified this session via `uv pip show`) [VERIFIED: project venv] | Reconciler REST truth: open normal orders, open algo orders, positions; orphan cancel | The official connector; covers post-migration `algoOrder` endpoints + `ALGO_UPDATE` models. NOTE: one minor ahead of STACK doc's 17.3.1 — planner must re-read the 17.4 changelog (pyproject floor `>=17.3,<18` already admits it) |
| stdlib `hashlib` + `secrets` + `hmac` | 3.13 stdlib | One-time token generation (`secrets.token_urlsafe`), token hashing (SHA-256), constant-time comparison (`hmac.compare_digest`) | No new dependency; secret-free logging compatible (only hashes persisted) |
| SQLAlchemy 2.0.x + psycopg 3 + Alembic | per pyproject floors | Approval rows, short→full mapping, JournalEvent drill/callback audit trail | Existing single-Base ORM + parity-gate discipline; every DATA_MODEL-touching change ships as a reviewed migration |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tenacity | >= 9 (per pyproject) | Bounded retries on Telegram sends and reconciler REST fallback calls | Same posture as `notify_simulate` (3 attempts / 30 s precedent); never infinite retry on order-adjacent paths |
| structlog | >= 25 (per pyproject) | Structured lineage logs (callback receipt, replay hit, divergence, sweep, drill outcome) | Every approval/reconciliation decision post-hoc explainable; secret-free (hashes only, never raw tokens) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| PTB polling `Application` | FastAPI webhook receiver | Webhook needs a public inbound HTTPS surface + HMAC auth + replay handling anyway; CONTEXT D-02 defers it (revisit only with measured need) |
| `arbitrary_callback_data=True` (PTB object passthrough) | Short-id + server-side mapping (chosen) | Arbitrary objects avoid the mapping table but keep state in-process memory — lost on restart, breaking replay-after-restart idempotency; the mapping row is the restart-safe choice |
| REST periodic reconciler tick | Pure WS-event-driven reconciliation | WS events are lossy under disconnects (BINANCE.md §10 mandates periodic authoritative reconciliation); D-03 specifies scheduled tick — WS is the fast path, REST tick is the truth |

**Installation:**
```bash
# No new packages. Phase 8 builds on the locked environment:
uv sync   # python-telegram-bot 22.8 + binance-sdk 17.4.0 already in uv.lock range
```

**Version verification:** `uv pip show` run this session returned `python-telegram-bot 22.8` and `binance-sdk-derivatives-trading-usds-futures 17.4.0`, both satisfying the pyproject floors (`python-telegram-bot>=22.8,<23`, `binance-sdk-derivatives-trading-usds-futures>=17.3,<18`) [VERIFIED: project venv].

## Package Legitimacy Audit

No new external packages are introduced by this phase — all Phase-8 logic uses the locked environment plus stdlib. No registry lookups for new names were needed, so there are no SLOP/SUS candidates.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `python-telegram-bot` 22.8 | PyPI (installed in venv, verified this session) | ~10 yrs (v20 asyncio rewrite 2022; 22.x 2025–2026) | ~high (standard Telegram bot library) | github.com/python-telegram-bot/python-telegram-bot | OK | Approved — already locked in pyproject |
| `binance-sdk-derivatives-trading-usds-futures` 17.4.0 | PyPI (installed in venv, verified this session) | SDK family 2024+; 17.x 2026 | official Binance SDK | github.com/binance/binance-sdk-* | OK | Approved — already locked in pyproject; planner must diff 17.3.1→17.4.0 changelog |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*No `postinstall` scripts apply (pure-Python wheels, no new installs). The legacy `binance-connector` / `binance-futures-connector` remain forbidden (archived 2026-04-30) [CITED: AGENTS.md stack section].*

## Architecture Patterns

### System Architecture Diagram

```text
Telegram user press (APPROVE/SKIP, at-least-once redelivery)
        │
        ▼
PTB Application (polling) — src/adapters/telegram_callbacks.py
  │ authorized-chat gate FIRST (unknown chat → reject, no state touch)
  │ parse callback_data (SIM:/APR:/SKP: + short-id, ≤64 bytes)
  │ journal callback receipt (JournalEvent, at-least-once audit)
        │
        ▼
Approval core — src/approval/ (pure: stdlib + Decimal + domain only)
  │ short→full mapping resolve → SignalId + TradePlan
  │ binding checks: version + parameterSetHash + plan hash + expiry
  │   + chat + one-time token hash (hmac.compare_digest)
  │ replay? → return existing Approval (WR-07: PENDING ⟺ acted=None)
  │ stale? → unapprovable + reason code (APPROVAL_EXPIRED / STALE_SETUP…)
  │ notify-failure? → stays PENDING (never auto-approve)
        │
        ▼
PostgreSQL (Approval row transition + JournalEvent, single transaction)

Reconciler — src/reconcile/ (scheduled tick, cancel-only)
  │ local open-intent (Orders PLANNED/NEW/PARTIALLY_FILLED + Positions OPEN)
  │   vs ① GET /fapi/v1/openOrders (current_all_open_orders)
  │   vs ② GET /fapi/v1/openAlgoOrders (current_all_algo_open_orders)
  │   vs ③ GET /fapi/v1/positionRisk (position_information_v3)
  │      (user-data WS: ORDER_TRADE_UPDATE + ALGO_UPDATE = fast path;
  │       REST tick = authoritative truth)
        ├── orphan protective (no live entry / zero position) → DELETE cancel
        │     (normal: cancel via origClientOrderId; algo: cancel_algo_order)
        │     + journal sweep; NEVER places orders
        └── any divergence → SAFE_MODE (block entries; monitor+reconcile on)
```

File-to-implementation mapping belongs in PLAN.md, not in the diagram.

### Recommended Project Structure

```text
src/
├── approval/          # NEW: pure core — bind/replay/expiry gates (stdlib+Decimal+domain only)
│   ├── binding.py     # binding-check function (plan hash + version + expiry + chat + token)
│   ├── replay.py      # token-hash lookup → existing Approval resolution (WR-07)
│   └── tokens.py      # secrets.token_urlsafe issue + SHA-256 hash + compare_digest verify
├── adapters/
│   ├── telegram_notify.py    # EXTEND: keep send path; add callback receiver (only PTB importer)
│   └── binance_usdm.py       # EXTEND: reconciler REST surface (3 query + 2 cancel methods)
├── reconcile/         # NEW: three-source compare, orphan sweeper, SAFE_MODE transitions
│   ├── compare.py     # set-difference: local intent vs 3 exchange-truth sets
│   ├── sweeper.py     # cancel-only orphan sweep + journal
│   └── safe_mode.py   # SAFE_MODE enter/exit guard composing with risk gates
├── ops/
│   └── drills.py      # NEW (or src/ops/ extension): 8-drill injected-fault harness + drill log
└── db/
    └── models.py      # EXTEND: short→full mapping table (if PG-backed) via migration
tests/
└── fixtures/
    └── phase8/        # NEW: replay sequences, orphan/divergence scenarios, ID determinism, drill logs
```

### Pattern 1: Approval binding + idempotent replay (D-01)
**What:** Single pure function `resolve_callback(*, short_id, action, chat_id, token, now_utc, ...)` that (1) resolves short→full, (2) runs binding checks in fixed order (chat → expiry → version/hash → token), (3) on token-hash hit returns the existing `Approval` untouched, (4) else performs exactly one PENDING→decided transition. WR-07 coherence (`status == PENDING ⟺ acted_at_utc is None`) is the invariant the replay path trusts.
**When to use:** Every inbound callback, including duplicates, delayed redeliveries, and post-restart replays.
**In-repo anchor:** `Approval` frozen shape with `approval_token_hash`, `request_hash`, nullable `acted_at_utc`, and the WR-07 guard [VERIFIED: src/domain/approval.py:44-70]:

```python
# src/domain/approval.py:44-55 (field list, verbatim)
approval_id: str
trade_plan_id: str  # FK to TradePlan
signal_id: str  # FK to Signal
action: ApprovalAction
result: ApprovalResult
status: ApprovalResult  # explicit — never inferred (D-11)
approval_token_hash: str
requested_at_utc: datetime  # aware UTC
acted_at_utc: datetime | None = None  # None = "never happened" (D-11)
actor_id: str = ""
telegram_message_id: str | None = None  # None = "no message yet"
request_hash: str = ""
```

```python
# src/domain/approval.py:66-70 (WR-07 coherence guard, verbatim)
if self.status == ApprovalResult.PENDING and self.acted_at_utc is not None:
    raise ValueError("PENDING approval must have acted_at_utc=None")
if self.status != ApprovalResult.PENDING and self.acted_at_utc is None:
    status_name = getattr(self.status, "value", self.status)
    raise ValueError(f"{status_name} approval must set acted_at_utc")
```

**Token handling:** issue with `secrets.token_urlsafe(32)`, persist only `hashlib.sha256(token).hexdigest()` into `approval_token_hash`, verify with `hmac.compare_digest` (constant-time; defeats timing probing) [ASSUMED — standard practice, confirm in plan review]. Never log the raw token — structured logs carry `approval_token_hash[:16]` prefixes at most.

### Pattern 2: PTB polling intake behind adapters (D-02)
**What:** `Application.builder().token(...).build()`, `add_handler(CallbackQueryHandler(on_callback, pattern=...))`, `await app.run_polling(...)` living in exactly one adapter module; the handler answers the query (`await query.answer(...)` so the client spinner clears), journals receipt, then calls the pure approval core with a parsed intent. `run_polling`, `add_handler`, `start/stop` confirmed on installed PTB 22.8 this session [VERIFIED: project venv via `python -c "from telegram.ext import Application..."`]. `callback_data` 1–64 bytes limit [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.inlinekeyboardbutton.html]; `CallbackQueryHandler` with optional pattern filter + `CallbackQuery.answer()` shortcut [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.ext.callbackqueryhandler.html, https://docs.python-telegram-bot.org/en/stable/telegram.callbackquery.html].
**When to use:** All V1 inbound Telegram traffic. FastAPI stays webhook/health edge only.
**Example:**
```python
# Source: PTB 22.8 stable docs (Context7) + in-repo short-id scheme
from telegram.ext import Application, CallbackQueryHandler


async def on_callback(update, context) -> None:
    query = update.callback_query
    await query.answer()  # clear client spinner FIRST (fast, before I/O)
    chat_id = query.message.chat_id
    if chat_id != AUTHORIZED_CHAT_ID:  # gate FIRST — no state touch
        await query.answer("unauthorized", show_alert=True)
        return
    intent = parse_callback(query.data)  # "APR:<short32>" / "SKP:<short32>"
    journal_callback_receipt(intent)  # JournalEvent, at-least-once audit
    result = resolve_callback(intent, chat_id=chat_id, now_utc=utcnow())
    await query.edit_message_text(render(result))


app = Application.builder().token(TOKEN).build()
app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^(APR|SKP|SIM):"))
await app.run_polling(allowed_updates=["callback_query"])  # same asyncio loop as WS supervisor
```
**In-repo anchor:** the 64-byte-safe scheme to extend (`SIM:{sha256[:32]}`, assert ≤64) [VERIFIED: src/adapters/telegram_notify.py:68-100]:

```python
# src/adapters/telegram_notify.py:78 + :96-100 (verbatim)
return hashlib.sha256(signal_id.encode("utf-8")).hexdigest()[:32]
sim_data = f"SIM:{short}"
skip_data = f"SKIP:{short}"
assert len(sim_data.encode("utf-8")) <= 64
assert len(skip_data.encode("utf-8")) <= 64
```

`arbitrary_callback_data=True` exists in PTB [CITED: https://docs.python-telegram-bot.org/en/stable/telegram.ext.applicationbuilder.html] but is REJECTED for V1 (in-memory cache dies on restart → replay-after-restart breaks; see Alternatives Considered).

### Pattern 3: Three-source reconciler + cancel-only sweeper + SAFE_MODE (D-03, EXEC-02)
**What:** Scheduled tick (planner's discretion on cadence; ~60 s aligns with the Phase-7 `STALENESS_THRESHOLD_SECONDS=60` freshness precedent [ASSUMED — confirm tick vs event-driven mix in planning]) that snapshots (① open normal orders, ② open algo orders, ③ positions) via REST and set-diffs against local open intent. Orphan = protective order whose entry position reads zero / plan closed → cancel after authoritative position verification, journal, re-scan. Any divergence → SAFE_MODE (block new entries; monitoring + reconciliation continue; exit only via rehearsed restore path). The reconciler never places orders — not even "rescue" protection (RUNBOOK §3 requires risk validation / manual intervention for that path).
**Endpoint map (all confirmed present on the installed SDK class this session** [VERIFIED: installed SDK 17.4.0 via `uv run python dir(DerivativesTradingUsdsFuturesRestAPI)`]):

| Truth source | REST endpoint | Installed SDK method |
|---|---|---|
| Open normal orders | `GET /fapi/v1/openOrders` | `current_all_open_orders` |
| Open algo (conditional) orders | `GET /fapi/v1/openAlgoOrders` | `current_all_algo_open_orders` |
| Positions | `GET /fapi/v1/positionRisk` | `position_information_v3` |
| Cancel normal order | `DELETE /fapi/v1/order` | `cancel_order` (sibling on same class — listed in SDK file manifest; confirm signature in planning) [ASSUMED] |
| Cancel algo order | `DELETE /fapi/v1/algoOrder` | `cancel_algo_order` |
| Single algo query (no-blind-retry) | `GET /fapi/v1/algoOrder` | `query_algo_order` |
| Position mode detect | `GET /fapi/v1/positionSide/dual` | `get_current_position_mode` |

**Binance semantics the sweeper must encode:**
- Conditional lifecycle moved to the Algo Service: `CONDITIONAL_ORDER_TRIGGER_REJECT` is deprecated (effective 2025-12-15); rejection reasons arrive inside `ALGO_UPDATE.o.rm` — the sweeper/reconciler must parse `ALGO_UPDATE`, not the old event [CITED: Binance change-log via web search 2026-09-27]. The installed SDK ships `algo_update` / `algo_update_o` WS-stream models, confirming the event family is first-class [VERIFIED: installed SDK 17.4.0 file manifest].
- 200-open-conditional-order limit per symbol; `MAX_NUM_ALGO_ORDERS` exchangeInfo filter removed Dec 2025 — never read it [CITED: docs/trading/EXECUTION_SPEC.md §12 + Binance change-log].
- New Algo Order weight follows order rate limits (1 on 10 s + 1 min order-count limits, 0 IP weight) [CITED: Binance change-log 2026-06-20 entry via web search] — reconciler query load is cheap, but placement-adjacent cancels still count against order limits: sweep in bounded batches.
- User-data WS (`ORDER_TRADE_UPDATE` + `ALGO_UPDATE`) is the fast path; REST tick is authoritative truth (BINANCE.md §10 startup/reconnect sequences) [CITED: docs/integration/BINANCE.md §§5/9/10].

### Pattern 4: Deterministic order identifiers (D-04, EXEC-03)
**What:** `client_order_id` / `algo_client_id` = fixed scheme over (plan hash + order role), e.g. `tr8{plan_hash[:20]}{role_code}` within Binance's client-order-ID charset/length rules. Same approved plan retried/restarted/replayed → same IDs → exchange dedups; entry vs protective roles never collide by construction (distinct role codes).
**In-repo anchor:** three independent identifier fields [VERIFIED: src/domain/order.py:77-79]:

```python
# src/domain/order.py:77-79 (verbatim)
client_order_id: str | None
exchange_order_id: str | None
algo_client_id: str | None
```

**Role-code vocabulary warning:** `OrderRole` enum carries `ENTRY / STOP_LOSS / TAKE_PROFIT_1 / TAKE_PROFIT_2` [VERIFIED: src/domain/enums.py:219-226], while DATA_MODEL §2.7 prose says `ENTRY / STOP / TP / CANCEL_REPLACE / OTHER` and `Order.order_role` is still a validated non-empty string [VERIFIED: src/domain/order.py:65]. The planner must pin the exact role→code mapping (and whether `OrderRole` promotion has landed) before freezing the derivation scheme — a mismatch here silently breaks the never-collide guarantee.
**Binance-side check:** `origClientOrderId` query support exists for normal orders (`query_current_open_order`); algo side has `query_algo_order` with `clientAlgoId` param per the CLI surface [CITED: binance-cli USD-S examples via web search]. Re-verify exact param names against installed SDK signatures during planning (no-blind-recovery EXECUTION_SPEC §10 depends on it).

### Pattern 5: Drill harness with injected faults + journaled drill log (D-05, OPS-01)
**What:** A `run_drill(name, *, inject, assert_outcome)` harness where each of the 8 RUNBOOK drills (unprotected/orphan/duplicate/API-down/stale-feed/DB-failure/manual-close/restore) declares: fault to inject (in-memory fake / recorded fixture — never real unprotected exposure), expected SAFE_MODE/sweep/journal outcome, and the JournalEvent `event_type` it emits. The drill log (ordered JournalEvents + outcome summary) is the OPS-01 acceptance artifact.
**RUNBOOK anchor:** SAFE_MODE trigger list + 8 procedure blocks [CITED: docs/operations/RUNBOOK.md §§2–12]; SAFE_MODE semantics (no new orders, protection stays, monitoring+journaling continue) [CITED: docs/operations/SECURITY_AND_OPERATIONS.md §7]; restart sequence (reconcile before resume) [CITED: same doc §8].
**Precedent in-repo:** `src/paper/freeze.py` halt-and-continue-monitoring behavior and `src/paper/resync.py` gap-as-explicit-record (never synthesize) are the stylistic templates for drill fault injection [CITED: 08-CONTEXT.md Existing Code Insights].

### Anti-Patterns to Avoid
- **Auto-approve on notification failure:** retrying the send is fine; inferring consent from silence violates APRV-02 and Phase-7 D-05. Failure → PENDING + journal.
- **Chat gate after state access:** checking the token/mapping before verifying the chat leaks oracle information and touches state for strangers. Gate order is fixed: chat → receipt-journal → resolve.
- **Blind retry after ambiguous placement/cancel:** EXECUTION_SPEC §10 — query by client/algo ID first (`query_algo_order` / `query_current_open_order`), retry only on confirmed absence.
- **Sweeper that places orders:** the reconciler cancels orphans and raises SAFE_MODE; submitting "rescue" protection is a separate risk-validated/manual path (RUNBOOK §3).
- **Raw token in logs/journal:** hashes only. A log line with a replayable token is a credential leak (ASVS V7).
- **`float` in ID derivation or binding compare:** hash slices and string compares only; any float formatting is locale/precision-dependent and breaks byte-equivalence.
- **Trusting WS events alone:** periodic REST reconciliation is mandatory (BINANCE.md §10); WS is the fast path.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Telegram MTProto / raw Bot HTTP API | Custom HTTP polling + update parsing | `python-telegram-bot` 22.8 `Application` + handlers | Update offsets, retry/backoff, `answer()` semantics, 64-byte enforcement edge cases |
| One-time token generation | `random` / timestamp-based nonces | `secrets.token_urlsafe` | CSPRNG; `random` is predictable, timestamps collide on restart |
| Token comparison | `==` string equality | `hmac.compare_digest` | Timing side-channel on the approval gate |
| Order/position/algo REST surface | Raw `httpx` signing for covered endpoints | Installed SDK methods (`current_all_open_orders`, `current_all_algo_open_orders`, `position_information_v3`, `cancel_algo_order`, `query_algo_order`) | Request signing, recvWindow/timestamp, response models, changelog tracking |
| Retry/backoff | Hand-rolled sleep loops | `tenacity` bounded retries (precedent: `notify_simulate` 3 attempts / 30 s) | Jitter, stop conditions, exception filtering; never infinite on order-adjacent paths |
| Structured audit logging | `print` / custom JSON logger | `structlog` (locked) with correlation/SignalId/order-ID fields | Decision-lineage schema per SECURITY_AND_OPERATIONS §6 |
| Exchange ID dedup bookkeeping | Local "already-sent" boolean flags | Deterministic client/algo IDs (exchange is the dedup authority) | Flags die on restart; the exchange remembers |

**Key insight:** every hand-rolled variant of these fails exactly on restart/replay — the two conditions Phase 8 exists to survive. Restart-safe state (PG rows, exchange-side IDs) beats in-process memory everywhere in this phase.

## Common Pitfalls

### Pitfall 1: Callback replay creates a second Approval/order intent
**What goes wrong:** 5× duplicate delivery → 5 transitions or 5 order intents.
**Why it happens:** Lookup by callback payload instead of by one-time-token hash; transition without WR-07 guard.
**How to avoid:** Token-hash is the idempotency key; replay resolves to the existing row; WR-07 (`PENDING ⟺ acted_at_utc is None`) enforced at construction AND re-checked in the transition transaction (compare-and-set on `status=PENDING`).
**Warning signs:** Approval row count > 1 per `trade_plan_id`; test with fewer than 5 replays.

### Pitfall 2: Stale plan approved after expiry/supersede
**What goes wrong:** User taps APPROVE on yesterday's message; order intent for a dead plan.
**Why it happens:** Expiry checked at notify time but not at callback time; plan-hash not re-compared.
**How to avoid:** Binding checks run at callback resolution against current plan row (expiry, plan hash, SUPERSEDED/EXPIRED/INVALIDATED status) with reason codes (`APPROVAL_EXPIRED`, `STALE_SETUP`, `INVALIDATED` — all canonical [VERIFIED: src/domain/enums.py:130-144]).
**Warning signs:** Any APPROVED approval whose `acted_at_utc > expiry_utc`.

### Pitfall 3: Orphan sweep cancels the wrong leg
**What goes wrong:** Sweeper cancels a live protective during a transient position-query gap.
**Why it happens:** Position read races the fill event; single-sample truth.
**How to avoid:** Cancel only after authoritative position verification (re-query positions, confirm zero across two consecutive reads or position + order-truth agreement); journal pre/post images; re-scan after sweep (RUNBOOK §4 sequence).
**Warning signs:** Sweep journal rows without a preceding position-zero verification row.

### Pitfall 4: SAFE_MODE exit without restore proof
**What goes wrong:** Operator clears SAFE_MODE while divergence persists → entries resume into unknown state.
**Why it happens:** Exit is a boolean flip instead of the rehearsed restore path (reconcile → verify protection → resume).
**How to avoid:** Exit requires a clean three-source compare + drill-logged restore event; model as explicit transition guarded by a fresh reconciliation snapshot.
**Warning signs:** `SAFE_MODE → LIVE_APPROVAL` transition with no reconciliation snapshot in the same transaction.

### Pitfall 5: OrderRole vocabulary drift breaks ID roles
**What goes wrong:** Derivation uses `STOP` but domain writes `STOP_LOSS` → two roles map to one code (collision) or one role maps to none (sweep misses).
**Why it happens:** Three competing vocabularies (DATA_MODEL prose vs `OrderRole` enum vs `Order.order_role` string).
**How to avoid:** Planner pins one canonical role→code table in PLAN.md; derivation + sweeper + fixtures all import it from one module.
**Warning signs:** Any string literal role code outside the canonical module.

### Pitfall 6: Journal-after-send loses the audit trail
**What goes wrong:** Callback processed, process crashes before journaling → replay looks like a first touch.
**Why it happens:** Side effect before durable record.
**How to avoid:** Journal-first ordering (Phase-7 `notify_simulate` precedent: commit receipt row BEFORE acting; outcome journaled after). Callback receipt row must exist before `resolve_callback` runs.
**Warning signs:** `resolve_callback` reachable without a preceding journal commit in the call path.

### Pitfall 7: SDK 17.4.0 drift from STACK's 17.3.1
**What goes wrong:** Planner codes to remembered 17.3.1 shapes; a renamed field/method breaks at runtime.
**Why it happens:** Minor bumps in this SDK track REST/WS changes.
**How to avoid:** Planner diffs the 17.3.1→17.4.0 changelog and re-verifies every touched signature (`current_all_algo_open_orders`, `query_algo_order`, `cancel_algo_order`, `position_information_v3`) against the installed package before writing PLAN.md.
**Warning signs:** PLAN.md citing endpoint semantics without an installed-SDK signature check.

## Code Examples

Verified patterns from official sources and the installed environment:

### PTB polling intake skeleton
```python
# Source: PTB 22.8 stable docs via Context7 (CallbackQueryHandler + answer + 64-byte limit)
# + authorized-chat-first gate per CONTEXT D-02
from telegram.ext import Application, CallbackQueryHandler

app = Application.builder().token(TOKEN).build()
app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^(APR|SKP|SIM):"))
# V1: polling only; allowed_updates narrowed to callbacks reduces noise
await app.run_polling(allowed_updates=["callback_query"])
```

### SDK reconciler truth calls (names verified on installed 17.4.0)
```python
# Source: installed SDK 17.4.0 — method names confirmed via
# `uv run python dir(DerivativesTradingUsdsFuturesRestAPI)` this session.
# Signatures (params, pagination, response models) must be re-checked
# from the installed package during planning — names only are verified here.
rest.current_all_open_orders(...)  # GET /fapi/v1/openOrders
rest.current_all_algo_open_orders(...)  # GET /fapi/v1/openAlgoOrders
rest.position_information_v3(...)  # GET /fapi/v1/positionRisk
rest.query_algo_order(...)  # GET /fapi/v1/algoOrder (no-blind-retry probe)
rest.cancel_algo_order(...)  # DELETE /fapi/v1/algoOrder (orphan sweep)
rest.get_current_position_mode(...)  # position-mode detect (one-way vs hedge)
```

### Deterministic order-ID derivation (scheme shape — planner freezes exact lengths)
```python
# Source: scheme per CONTEXT D-04; stdlib only. Exact prefix/slice/code
# lengths are planner's discretion — verify against Binance client-order-ID
# charset/length rules during planning (re-check installed SDK validator).
import hashlib


def derive_client_order_id(plan_hash: str, role_code: str) -> str:
    # role_code from the ONE canonical role table (see Pitfall 5)
    digest = hashlib.sha256(f"{plan_hash}:{role_code}".encode()).hexdigest()
    return f"tr8{digest[:20]}{role_code}"  # placeholder shape — planner pins
```

### Token issue / hash / verify
```python
# Source: standard library practice [ASSUMED — confirm in plan review].
import hashlib, hmac, secrets

raw_token = secrets.token_urlsafe(32)  # sent in callback_data mapping, never stored
stored = hashlib.sha256(raw_token.encode()).hexdigest()  # → Approval.approval_token_hash
ok = hmac.compare_digest(stored, hashlib.sha256(presented.encode()).hexdigest())
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `STOP_MARKET` / `TAKE_PROFIT_MARKET` via `/fapi/v1/order` | Algo/conditional orders via `/fapi/v1/algoOrder` (`algoType=CONDITIONAL`), lifecycle via `ALGO_UPDATE` | Dec 2025 migration [CITED: Binance change-log] | Reconciler must query `openAlgoOrders` + parse `ALGO_UPDATE.o.rm`, not legacy endpoints/events |
| `CONDITIONAL_ORDER_TRIGGER_REJECT` event | Rejection reasons inside `ALGO_UPDATE.o.rm` | Deprecated effective 2025-12-15 [CITED: Binance change-log] | Orphan/reject triage reads the `ALGO_UPDATE` object |
| `MAX_NUM_ALGO_ORDERS` exchangeInfo filter | 200-open-conditional-order limit per symbol | Removed Dec 2025 [CITED: EXECUTION_SPEC §12] | Headroom tracked by counting `openAlgoOrders`, never by reading the removed filter |
| Legacy `binance-connector` / `binance-futures-connector` | `binance-sdk-derivatives-trading-usds-futures` ≥ 17.3 | Archived 2026-04-30 [CITED: AGENTS.md] | Never use legacy connectors; SDK 17.4.0 installed |
| SIMULATE-only notify, inert callbacks | Bound APPROVE/SKIP with replay-to-existing | This phase | Phase-7 sender graduates; wire format (`SIM:`/`SKIP:` short-ids) stays stable |

**Deprecated/outdated:**
- `CONDITIONAL_ORDER_TRIGGER_REJECT` handling: gone — use `ALGO_UPDATE`.
- FastAPI webhook callback receiver: deferred, not deprecated — revisit only with measured need.
- `arbitrary_callback_data=True` for approval callbacks: rejected for V1 (restart-unsafe).

## Assumptions Log

> Claims tagged `[ASSUMED]` in this research — planner and discuss-phase must confirm before locking.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `secrets.token_urlsafe` + SHA-256 + `hmac.compare_digest` is the right token scheme | Pattern 1 | LOW — standard practice, but plan review should confirm hash choice and log-prefix policy |
| A2 | Reconciler tick ~60 s (aligned with `STALENESS_THRESHOLD_SECONDS=60`) is a sane default | Pattern 3 | MEDIUM — wrong cadence = either rate-limit pressure or slow orphan detection; planner sets with justification |
| A3 | `cancel_order` exists as sibling SDK method for normal-order orphan cancel | Pattern 3 table | LOW — file manifest lists cancel models; planner confirms signature from installed package |
| A4 | `origClientOrderId` / `clientAlgoId` query params available for no-blind-retry probes | Pattern 4 | MEDIUM — EXECUTION_SPEC §10 compliance depends on it; planner verifies against installed SDK signatures |
| A5 | Exact Binance client-order-ID charset/length rules for the derivation scheme | Pattern 4 / Code Examples | MEDIUM — over-long or illegal-char IDs rejected at placement; planner re-verifies before freezing scheme |
| A6 | `ApprovalResult` PENDING/APPROVED/SKIPPED/EXPIRED set (D-10 planner assumption) | User Constraints | LOW for Phase 8 (locked scope) — user confirmation still pending per STATE.md; planner must not relitigate |

**If this table is empty:** n/a — six assumptions above need confirmation.

## Open Questions

1. **Short→full mapping storage: PG row vs in-memory + journal?**
   - What we know: CONTEXT leaves it to planner discretion; restart-safe replay favors a PG row (unique on short-id) written in the same transaction as the Approval.
   - What's unclear: whether the planner accepts a new table + migration or prefers reusing an existing row shape.
   - Recommendation: PG row via Alembic migration (restart-proof, queryable); planner decides table name.
2. **SDK 17.4.0 vs STACK 17.3.1 — what changed?**
   - What we know: installed version is 17.4.0, inside the pyproject floor; all reconciler method names verified present.
   - What's unclear: field-level changes in algo/position models between 17.3.1 and 17.4.0.
   - Recommendation: planner runs a changelog diff + signature check as PLAN Wave 0 before any reconciler task.
3. **Reconciler tick cadence and WS-vs-REST mix?**
   - What we know: D-03 says scheduled tick at planner discretion; user-data WS preferred realtime per D002.
   - What's unclear: exact cadence and whether WS events also trigger compare (event-driven + periodic) or only REST tick.
   - Recommendation: REST tick (60 s default, A2) + WS `ALGO_UPDATE`/`ORDER_TRADE_UPDATE` as opportunistic fast-path hints that still go through the same compare function.
4. **OrderRole vocabulary freeze?**
   - What we know: three competing vocabularies (DATA_MODEL prose, `OrderRole` enum, `Order.order_role` string) — see Pitfall 5.
   - What's unclear: whether Phase 4's Enum promotion has landed for `order_role`.
   - Recommendation: planner greps current `OrderRole` usage and pins the canonical role→code table in PLAN.md Wave 0.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `python-telegram-bot` | Callback intake (D-02) | ✓ | 22.8 (venv) | — |
| `binance-sdk-derivatives-trading-usds-futures` | Reconciler REST (D-03) | ✓ | 17.4.0 (venv) | — |
| tenacity / structlog | Retries + lineage logs | ✓ (pyproject locked) | per uv.lock | — |
| SQLAlchemy + psycopg + Alembic | Approval/mapping/journal persistence | ✓ (pyproject locked) | per uv.lock | — |
| pytest + pytest-asyncio (`asyncio_mode = "auto"`) | TDD RED→GREEN | ✓ (pyproject `[tool.pytest.ini_options]`) | pytest ≥ 9 | — |
| PostgreSQL 17 | Approval/mapping rows at runtime | [ASSUMED — not probed] | — | SQLite for unit tests; Compose PG for integration |
| Telegram Bot token + authorized chat | Live callback delivery | ✗ (operator-provisioned) | — | Fake-`TelegramBot` injection in tests (Phase-7 seam); human-verify gate for live wiring |
| Binance API keys (read-only suffices) | Reconciler integration proof | ✗ (operator-provisioned) | — | Recorded exchangeInfo/algo-order fixtures; human-verify gate for live wiring |

**Missing dependencies with no fallback:**
- None that block planning or unit-testable implementation (all core logic is testable with fakes + fixtures).

**Missing dependencies with fallback:**
- Telegram token / Binance keys: operator-provisioned; tests use the fake-bot seam + recorded fixtures; planner adds `checkpoint:human-verify` before any live-wiring task.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ≥ 9 + pytest-asyncio (`asyncio_mode = "auto"` — no decorators needed) [VERIFIED: pyproject.toml:47-53] |
| Config file | `pyproject.toml` (`testpaths = ["tests"]`) |
| Quick run command | `uv run pytest tests/ -x -q` |
| Full suite command | `uv run pytest tests/ -q` (+ `ruff check` + `mypy src` per AGENTS.md quality gates) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| APRV-01 | APPROVE/SKIP message carries all 12 fields; callback_data ≤ 64 bytes | unit | `uv run pytest tests/test_approval_message.py -x` | ❌ Wave 0 |
| APRV-02 | 5× replay = exactly one transition; stale (expiry/hash/supersede/chat/token) unapprovable with reason code; notify-failure stays PENDING | unit (golden replay sequences) | `uv run pytest tests/test_approval_replay.py -x` | ❌ Wave 0 |
| EXEC-02 | Injected orphan swept (cancel + journal + re-scan); divergence forces SAFE_MODE; reconciler never places orders | unit + fake-exchange adapter | `uv run pytest tests/test_reconcile.py -x` | ❌ Wave 0 |
| EXEC-03 | Same plan retried/restarted/replayed → identical client/algo IDs; role codes never collide | unit (determinism property) | `uv run pytest tests/test_order_ids.py -x` | ❌ Wave 0 |
| OPS-01 | All 8 drills rehearsed with injected faults; drill log journaled; SAFE_MODE exit only via restore path | unit (drill harness) | `uv run pytest tests/test_drills.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_<module>.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -q`
- **Phase gate:** Full suite green + `ruff check` + `mypy src` before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/fixtures/phase8/` — replay sequences (5× duplicate callbacks), injected-orphan/divergence scenarios, retry/restart ID determinism vectors, drill-log goldens
- [ ] `tests/test_approval_replay.py` — covers APRV-02
- [ ] `tests/test_approval_message.py` — covers APRV-01 (extends Phase-7 notify goldens)
- [ ] `tests/test_reconcile.py` — covers EXEC-02 (fake three-source exchange adapter)
- [ ] `tests/test_order_ids.py` — covers EXEC-03
- [ ] `tests/test_drills.py` — covers OPS-01
- [ ] Migration for short→full mapping table (if planner chooses PG-backed mapping) — confirm in Wave 0
- [ ] SDK 17.3.1→17.4.0 changelog diff + signature re-check (Open Question 2) — Wave 0 prerequisite for reconciler tasks

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | One-time token per approval (`secrets` + SHA-256 hash + `hmac.compare_digest`); raw token never stored/logged |
| V3 Session Management | partial | Approval expiry (`expiry_utc`); PENDING approvals cannot be resurrected after expiry (→ EXPIRED with reason code) |
| V4 Access Control | yes | Authorized-chat gate FIRST, before any state touch; unknown chats rejected + journaled |
| V5 Input Validation | yes | `callback_data` strict parse (`^(APR\|SKP\|SIM):[0-9a-f]{32}$` shape); Pydantic-v2 boundary validation on any webhook-shaped input; Decimal-only money fields |
| V6 Cryptography | yes | No custom crypto — stdlib `secrets`/`hashlib`/`hmac` only; token hashes, not tokens, at rest |
| V7 Logging | yes | Secret-free structured logs (token-hash prefixes only); correlation/SignalId/order-ID per SECURITY_AND_OPERATIONS §6 |
| V8 Data Protection | yes | Bot token + API keys from env/off-source secrets, never git; no-withdrawal keys; IP allowlisting where practical |
| V9 Communications | yes | Telegram via official SDK (TLS); Binance REST signed endpoints via SDK; bounded retries, no secret leakage on failure paths |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Callback replay → duplicate order intent | Spoofing / Repudiation | Token-hash idempotency key + WR-07 compare-and-set; replay returns existing state |
| Stale-message approval (yesterday's APPROVE tap) | Tampering | Callback-time binding re-check (expiry + plan hash + status) with reason codes |
| Unauthorized chat approves plan | Elevation of privilege | Chat gate first; chat id part of the binding tuple |
| Orphan protective triggers against closed position | Tampering (state divergence) | Cancel-only sweeper after authoritative position verification; SAFE_MODE on divergence |
| Ambiguous cancel/place response → blind retry → duplicate | Repudiation | Query-by-client/algo-ID before retry (EXECUTION_SPEC §10) |
| Raw approval token in logs/journal | Information disclosure | Hash-only persistence + logging; `approval_token_hash` is the only stored form |
| Testnet/paper credentials used against live | Elevation of privilege | Separate credentials per SECURITY_AND_OPERATIONS §1; explicit live-enablement gate (Phase 9) |

## Sources

### Primary (HIGH confidence)
- Installed `python-telegram-bot` 22.8 — `Application.run_polling`/`add_handler`/`CallbackQueryHandler` surface probed via `python -c` this session [VERIFIED: project venv]
- Installed `binance-sdk-derivatives-trading-usds-futures` 17.4.0 — reconciler method names (`current_all_open_orders`, `current_all_algo_open_orders`, `position_information_v3`, `cancel_algo_order`, `query_algo_order`, `get_current_position_mode`) + `algo_update` WS models confirmed via `uv run python dir(...)` + file manifest this session [VERIFIED: project venv]
- Context7 `/websites/python-telegram-bot_en_stable` — `callback_data` 1–64 byte limit, `CallbackQueryHandler` pattern filter, `answer()` shortcut, `arbitrary_callback_data` builder option
- In-repo source-of-truth reads this session: `src/domain/approval.py:44-70`, `src/domain/order.py:65-79`, `src/domain/enums.py:43-70/219-226/130-144`, `src/adapters/telegram_notify.py:68-100`, `src/paper/notify.py:111-114`, `pyproject.toml:47-53`
- Canonical docs: `docs/trading/EXECUTION_SPEC.md` (§§7/9/10/12), `docs/operations/RUNBOOK.md` (§§2–12), `docs/operations/SECURITY_AND_OPERATIONS.md` (§§6–8), `docs/integration/BINANCE.md` (§§5/9/10), `docs/integration/TELEGRAM.md` (§§3/4/6), `docs/data/DATA_MODEL.md` (§§2.5/2.7), `docs/GLOSSARY.md` (§§4/8/9)

### Secondary (MEDIUM confidence)
- Binance Developer Docs via web search 2026-09-27: USDⓈ-M change-log (Dec 2025 Algo migration, `CONDITIONAL_ORDER_TRIGGER_REJECT` deprecation 2025-12-15, 2026-06-20 algo-order weight entry, trailing-stop `ia` field), legacy `Query All Algo Orders` (`GET /fapi/v1/allAlgoOrders`), binance-cli USD-S examples (`query-algo-order --client-algo-id`), PyPI `binance-sdk-derivatives-trading-usds-futures` listing

### Tertiary (LOW confidence)
- Token-scheme specifics (`token_urlsafe(32)`, SHA-256 choice, hash-prefix log policy), reconciler tick default (60 s), SDK `cancel_order` sibling signature, client-order-ID charset/length rules — all flagged A1–A5 for planner confirmation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - both runtime libraries version-verified in the venv this session; no new packages needed
- Architecture: HIGH - all five patterns anchored to locked CONTEXT decisions + verified in-repo entities + confirmed SDK/PTB surfaces
- Pitfalls: HIGH - derived from canonical RUNBOOK/EXECUTION_SPEC procedures + in-repo precedents (journal-first, WR-07, fail-closed gates)
- Binance field-level semantics: MEDIUM - endpoint/method presence verified, but per-field shapes need the Wave-0 signature re-check (SDK drift 17.3.1→17.4.0)

**Research date:** 2026-09-27
**Valid until:** ~30 days (stable domain; re-verify SDK changelog + Binance algo docs before Phase 9 wiring regardless)
