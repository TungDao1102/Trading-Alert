# Phase 21: Account Equity + Daily Loss from Binance - Research

**Researched:** 2026-10-22
**Domain:** Binance USDⓈ-M account equity read (REST + user-data stream), D033 daily-loss accounting, DAILY_STOP behaviour, atomic portfolio risk reservation on PostgreSQL
**Confidence:** HIGH for the code seams and the recorded Demo payloads (read this session); MEDIUM for Binance semantics that only Demo or the SDK model text shows; LOW for the items in the Assumptions Log

Evidence label for every Binance fact below: **demo-observed, not mainnet** unless it says `[CITED: docs]`.

<user_constraints>
## User Constraints (from CONTEXT.md)

Copied verbatim from `21-CONTEXT.md` (gathered 2026-10-22, `--auto`, single pass; items marked OWNER-OPEN must not be implemented until the owner decides).

### Locked Decisions

All decisions below are the recommended option or a direction already recorded by the owner (D033, D035, `21-NOTES.md`). They are defaults the owner may override.

#### Equity source and field (criterion 1, F-012)
- **D-01:** Equity is read from `GET /fapi/v3/account` (and `/fapi/v3/balance`) and kept current by `ACCOUNT_UPDATE` from the user-data stream; REST is the truth, the stream is the freshness path. A REST read at start and after every stream gap (Demo: frames sent during a gap are not replayed after reconnect).
- **D-02:** The equity field is chosen and documented in the phase: the account-level margin-balance style total (wallet balance plus unrealized PnL) for the USDT asset, not `availableBalance` (that is Phase 22's margin check). The plan names the exact field after reading the recorded Demo capture (`evidence/fixtures/account_read_only_capture-rest-001-account_information.json`, `-002-account_balance_all.json`) and the current docs; if the docs and the capture disagree, the capture wins and the difference is recorded. The Demo account has `multiAssetsMargin=false`; multi-asset mode is a refusal (NO_TRADE), not a code path.
- **D-03:** Unknown, unreadable or stale equity is NO_TRADE with `UNCERTAIN_ACCOUNT_STATE` (F-012). A stale age uses a registry/limits key; the key stays `NOT_CONFIGURED` until the owner sets the number (same pattern as `commission_rate_ttl_seconds` in `src/risk/live_commission.py`). Age is `> ttl` or negative = stale, exactly ttl passes (same predicate as `check_portfolio`). — **Reversibility:** reversible — a gate predicate and one key.
- **D-04:** Equity is a Decimal parsed from the exchange text; no float at any point (`tests/test_domain_no_float.py`). A zero or negative equity is NO_TRADE (`AccountState` already requires positive equity).
- **D-05:** `src/core/types.py` `AccountState` stays the pure core input (equity, risk_rate). The new live source lives outside `src/core` (adapter/risk boundary) and builds `AccountState`; paper and backtest keep their ratified-config/ledger equity (D-12 of Phase 12: live-only code path).

#### Daily loss, UTC day, persisted state (criterion 2, D033)
- **D-06:** Daily loss follows D033 exactly: UTC day, `realized PnL + commissions + funding`, base = account equity at the UTC day start, thresholds from the params (warning 0.5%, stop 1%, `daily_loss_warning_threshold` / `daily_loss_stop_threshold`). The pure state machine (`src/risk/portfolio.py` daily state, `src/backtest/ledger.py` `daily_loss_quote`) is reused; Phase 21 supplies the live input.
- **D-07:** Day-start equity and the running day figures are persisted (PostgreSQL via the Phase 17 stores, new Alembic migration if a table is needed) so a restart inside the UTC day does not reset the day or move the base. A missing or unreadable persisted day state while a position or resting entry exists is fail-closed (NO_TRADE, alert), never "start a fresh day". — **Reversibility:** costly — a migration and a persisted schema other code reads.
- **D-08:** The day boundary uses the injected clock (no wall clock in pure modules). A day rollover captures a new day-start equity from a fresh REST read; if that read fails, the day stays unrolled-and-blocked (NO_TRADE) until it succeeds.
- **D-09:** Components come from Binance data, not from a local estimate: realized PnL and commission from `ORDER_TRADE_UPDATE` (`rp`, `n`/`N`; G3-009 owns parsing `commission` and `commissionAsset` and feeding this phase) cross-checked against REST (`/fapi/v1/userTrades`); funding from `FUNDING_FEE` income rows. Demo showed `/fapi/v1/income` returned 0 rows in four tries, so income-based funding is NOT confirmed on Demo; the plan treats funding as a REST-read component with an explicit "source unverified on Demo" label and does not rely on income rows for the stop decision until observed (OWNER-OPEN: accept trade-list-only counting in the meantime, or require income rows first).
- **D-10:** `realizedPnl` semantics: Demo trades show `realizedPnl` excludes commission (A9, demo-observed, not mainnet). The loss therefore adds commission explicitly. `LIVE_NET_PNL_SEMANTICS_VERIFIED` stays False and live R stays INCOMPLETE until Phase 24 verifies on mainnet (G2-042); this phase must not flip that flag.
- **D-11:** A commission asset other than USDT (BNB discount) is converted only with a rate the exchange reported at the time; if no rate exists, the daily loss is unknown and the result is fail-closed (the BNB discount is never used to shrink modeled cost, F-031).

#### DAILY_STOP behaviour (criterion 2, F-013, F-963)
- **D-12:** At DAILY_STOP: cancel pending (unfilled) entries, keep the protective stops of open positions, alert. Never cancel a stop, never open anything new. This reuses Phase 19/20 pieces (coordinator, sweeper rules); cancel of entries is a REST action that honours the rate-limit gate and must not bypass a 429/418 pause (D081).
- **D-13:** The `DAILY_STOP` and daily-loss `WARNING` alert producers are built here (D-23 of Phase 20; `src/ops/alerts.py` `OPS05_MATRIX`, `emit_daily_state_alert` is a test trigger today). They emit through the existing journal-first sink. The producers stay unwired in a running process until Phase 24 (nothing in Phase 21 starts a process).
- **D-14:** DAILY_STOP is sticky for the rest of the UTC day: a later equity rise does not lift it; it clears only at the next UTC day start. Persisted with D-07.

#### Portfolio caps and atomic risk reservation (criterion 3, F-407, F-955)
- **D-15:** Portfolio caps (max open positions, aggregate risk, cluster cap) count open positions, resting entries and approved-but-unplaced plans. `risk_inputs.open_positions` today excludes the last two.
- **D-16:** Approval reserves risk atomically: the reservation and the approval transition commit in one database transaction (a reservation row or counter guarded by the same transaction as the approval, uniqueness/locking decided by the planner against the Phase 17 stores). Two concurrent approvals cannot both pass a cap that only one fits. A reservation is released on every terminal plan state (expired, rejected, canceled, closed) and is rebuilt from durable rows on restart, never kept only in memory. — **Reversibility:** costly — touches the approval path and a migration.
- **D-17:** A plan whose reservation cannot be written (DB error) is refused, not approved (fail closed). Reading the current reserved total is part of the same decision as the gate (no check-then-act across two transactions).

#### Constraint snapshot and TP unblocking (21-NOTES, G4-039)
- **D-18:** When equity has a live source, the plan constraint snapshot's equity field is filled from it. The snapshot becomes COMPLETE only together with Phase 22's margin type and leverage; Phase 21 adds a test that a snapshot built from the live equity, plus stubbed Phase 22 inputs, passes `snapshot_is_valid_for_live` (so the Demo rehearsal can stop reporting the known gap). No placeholder equity is ever fed to the re-size path.
- **D-19:** Margin type and leverage stay `UNKNOWN` in this phase. The Demo account is x20 CROSSED by account default and the system never sets it (D035 is Phase 22); Phase 21 must not set, change or assume either.

#### Scope guards from the owner decisions
- **D-20:** No live order placement is enabled (`LIVE_ORDERS_DISABLED`). New REST reads are read-only (`GET`), signed via the existing adapter, behind the shared `RestRateLimitGate`; a -1003 ban end time is handled as D083 says (the clock-margin key stays `NOT_CONFIGURED`).
- **D-21:** OPS-02 (no-withdrawal keys, IP allowlist) is an owner attestation, not code. Phase 21 does not claim it; it only keeps secret-free logging (equity and PnL values are not secrets but account identifiers and keys never appear in logs or evidence).
- **D-22:** Everything Demo-observed is labelled "demo-observed, not mainnet" in code comments, docs and tests (D-17 of Phase 18). No trading parameter is chosen from Demo.

#### OWNER-OPEN (record, do not implement)
- **O-1:** The stale-equity maximum age (D-03) and the number of days/retention of the persisted day state.
- **O-2:** Whether trade-list-only daily-loss counting is acceptable while income rows are unobserved (D-09).
- **O-3:** Multi-asset margin mode: refuse (D-02 default) versus support later.
- **O-4:** Whether a DAILY_STOP produced from an unverified-PnL-semantics day may stay hard (default) or only warn until G2-042 is verified.

### Claude's Discretion
- Module placement (`src/risk/` vs `src/execution/` vs a new `src/account/`), table and column names, the reservation's locking mechanism, test layout and fakes (reuse `tests/support/`), and plan/wave split.

### Deferred Ideas (OUT OF SCOPE)
- Margin type, leverage, liquidation guard, available-margin check: Phase 22.
- Live wiring of the equity refresher, the reservation release job and the alert producers in a running process: Phase 24.
- Mainnet verification of `realizedPnl` versus commission and of income rows: Phase 24/26.
- Phase 20 review findings (34, none fixed): tracked in `20-REVIEW.md`; fix before Phase 24 at the latest.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description (REQUIREMENTS.md) | Research Support |
|----|-------------------------------|------------------|
| RISK-01 | Sizes positions from equity x risk-rate / SL-distance incl. modeled costs, floors to stepSize, identical logic in backtest/paper/live | Live equity resolver feeds the existing `AccountState` -> `size_and_quantize` unchanged (section "Architecture Patterns" P1); parity point about backtest equity convention (Open Question 1) |
| RISK-02 | Portfolio limits (max open positions, aggregate risk, cluster cap, DAILY_STOP states) and fail closed on uncertain account/risk state | Daily-state store + live daily-loss input (P2, P3); reservation counting resting + approved-but-unplaced (P4); UNCERTAIN_ACCOUNT_STATE on unknown/stale equity |
| EXEC-01 | Execution manager places LIMIT-zone entries ... (stays Pending: Demo-proven) | Phase 21 supplies the equity/daily-loss/caps inputs the manager currently takes from the caller (`risk_kwargs`), and the DAILY_STOP entry cancel through the existing `expire_pending_entry`; requirement stays Pending (Demo/mainnet proof is Phases 24-26) |
| OPS-02 | No-withdrawal keys, IP allowlist, off-source secrets, secret-free logging | Owner attestation only; Phase 21 contributes secret-free reads/logging and must NOT claim it (Demo account config shows `canWithdraw` `"true"`) |
</phase_requirements>

## Summary

The pure risk machinery already exists and is shared by backtest, paper and live: `AccountState(equity, risk_rate)` -> `size_and_quantize` -> `check_portfolio` (gate order cluster, aggregate, count, daily state), `derive_daily_state` (inclusive boundaries), and the backtest `Ledger` (UTC-day roll, `daily_loss_quote = max(0, -day_pnl)`, resting plans registered as exposures, thresholds resolved against equity at day start). What is missing is entirely the **live inputs**: nothing reads `/fapi/v3/account` outside the probe, no store holds day-start equity or day figures, no live producer builds `OpenPosition` rows, the approval transition reserves nothing, and nothing produces the DAILY_STOP/WARNING alerts or the DAILY_STOP entry cancel. Phase 21 is therefore (a) one new signed read-only adapter method plus a pure fail-closed resolver, (b) a persisted day-state + loss-component store and a pure live daily-loss function over the existing state machine, (c) a PostgreSQL risk-reservation table written in the same transaction as the approval decision, (d) a DAILY_STOP orchestrator over existing cancel helpers and the alert sink, and (e) the equity field in the plan constraint snapshot. No new third-party package is needed.

The recorded Demo capture settles the equity field: `totalMarginBalance` (top-level, USDT only in single-asset mode) equals `totalWalletBalance + totalUnrealizedProfit` and equals `assets[USDT].marginBalance` (all `"4999.09343961"` with zero unrealized PnL). The Demo account also holds 5000 USDC and 0.01 BTC that are NOT in the totals, so summing `assets[]` would overstate equity. `ACCOUNT_UPDATE` carries only wallet-balance deltas (`wb`, `cw`, `bc`) and unrealized PnL only for positions in the event, so equity cannot be reconstructed from the stream: the stream is a trigger to re-read REST, exactly as D-01 says. A Demo-observed identity (wallet-balance change after a closing fill equals `rp - n`, to 8 decimals) gives a strong, threshold-free cross-check for the loss components.

Three things need the planner's attention beyond the locked decisions: (1) the backtest `Ledger` is realized-only (equity = wallet balance, no unrealized PnL) while D-02 picks margin balance; this is a RISK-01 parity question to put to the owner (Open Question 1); (2) the staleness key cannot be a registry parameter (registry values are numbers and hash-locked) so it must be a 15th key in `config/execution/execution-limits-v1.toml`; (3) the SL-triggered close fill is the largest loss component and the router only forwards fills of KNOWN client ids, so the loss feed must be proven to see it (Pitfall 4).

**Primary recommendation:** Implement `GET /fapi/v3/account` -> `totalMarginBalance` (with the wallet+unrealized identity and `multiAssetsMargin=false` checks) as a pure `resolve_live_equity` mirroring `live_commission.py`; persist a per-UTC-day risk state + idempotent loss-component rows in new PostgreSQL tables (migration 0010) with a sticky DAILY_STOP latch; reserve risk in the same transaction as the approval decision under a single-row `FOR UPDATE` lock; reuse `check_portfolio`, `derive_daily_state`, `expire_pending_entry` and the alert sink; add no new `RejectionReason` member.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Read account equity (signed GET) | Adapter (`src/adapters`) | — | SDK types never leave the adapter (AGENTS.md); same pattern as `snapshot_positions` |
| Equity staleness / unknown -> NO_TRADE | Pure risk (`src/risk`) | — | Pure function of injected `now_utc` + reading + ttl, like `resolve_live_cost_rates` |
| Equity freshness trigger from stream | Adapter router sink (`ACCOUNT_UPDATE`) | Risk resolver | Stream is a hint, REST is the arbiter (D-05 of Phase 18) |
| Daily-loss state machine (NORMAL/WARNING/DAILY_STOP) | Pure risk (`derive_daily_state`) | Persistence (sticky latch) | Rule already shared; Phase 21 only supplies inputs and the sticky/persisted wrapper |
| Day-start base, loss components, DAILY_STOP latch | Database / `src/persistence` | Pure risk function over rows | Must survive restart (D-07); idempotent keys |
| Atomic risk reservation + cap check | Database transaction (approval store) | Pure `check_portfolio` | Check and write must be one transaction (D-16/D-17) |
| DAILY_STOP cancel of resting entries | Execution (`src/execution/manager.py` helpers) | Reconcile REST snapshot | REST open-orders is the truth for what rests; cancels honour the REST gate |
| DAILY_STOP / WARNING alerts | Ops (`src/ops/alerts.py` sink) | Pure risk (state change event) | Journal-first sink exists; producers are new |
| Constraint snapshot `equity_used` | Execution (`constraint_snapshot.py`) | Pure risk resolver | Snapshot is evidence; value comes from the resolver |

## Standard Stack

### Core (all already installed; nothing to add)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `binance-sdk-derivatives-trading-usds-futures` | 17.4.0 [VERIFIED: `uv pip list` this session] | `rest_api.account_information_v3` (GET /fapi/v3/account), `futures_account_balance_v3`, `account_trade_list`, `get_income_history` | Only Binance client in the project; the probe already calls these two account methods by name (`src/adapters/binance_probe.py:1034-1081`) |
| SQLAlchemy 2.0 + psycopg 3 + Alembic | `sqlalchemy>=2.0,<2.1`, `psycopg[binary,pool]>=3.3,<4`, `alembic>=1.19.2` (`pyproject.toml`) | New tables, `SELECT ... FOR UPDATE`, migration 0010 | Phase 17 stores use exactly these; `OperationalDatabase.transaction()` is the unit of work |
| `decimal.Decimal` | stdlib | All money | Decimal-only guard `tests/test_domain_no_float.py` |
| structlog, tenacity | existing | Logging; the alert sender already retries MESSAGES only | Reuse; do not retry orders (Q5/D080) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest 9, pytest-asyncio (auto), pytest-xdist | dev extra | Test runner | Per `AGENTS.md` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Registry param for equity max age | `execution-limits-v1.toml` 15th key | Registry sets are hash-locked numbers (`commission_rate_ttl_seconds = 3600` is a SET value in `params/trend-pullback/baseline-v6.toml:67`); a registry key cannot be `NOT_CONFIGURED`, so only the limits file honours "no number invented" |
| Append-only `system_state_events` for day state | New dedicated tables | `system_state_events` accepts only `str|bool|None` values and a CHECK on the key list (`ck_system_state_events_state_key` allows `'SAFE_MODE', 'LIVE_ENABLEMENT', 'KILL_GATE'`); idempotent per-fill rows and a sticky latch fit dedicated tables better |
| Advisory lock for the reservation | `SELECT ... FOR UPDATE` on a one-row lock/day-state row | Both are valid on PostgreSQL; the row lock reuses the idiom already in `consume_and_record_entry_intent` (`FOR UPDATE` on the approval row) and needs no new primitive |

**Installation:** none. `uv sync --frozen --extra dev` already provides everything. `uv.lock` does not change.

**Version verification:** `binance-sdk-derivatives-trading-usds-futures 17.4.0` and `binance-common 4.4.0` confirmed by `uv pip list` in this session.

## Package Legitimacy Audit

No external package is added by this phase (stack above is installed and locked). The `package-legitimacy` check was not run because there is nothing to check.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                       Binance (Demo/mainnet)                          Operator (Telegram)
   REST GET /fapi/v3/account (w5) ---+        user-data stream            |  APPROVE
   REST GET /fapi/v1/accountConfig   |        ORDER_TRADE_UPDATE (rp,n,N)  v
   REST GET /fapi/v1/userTrades      |        ACCOUNT_UPDATE (wb,cw,bc,m)  dispatch_callback -> save_atomic(approval, mapping)
                |                    |             |                                    |
        BinanceUsdmAdapter           |      router (known orders only)                  v
        (_sdk_call -> RestRateLimitGate)           |  fill_sink / account_sink    PgApprovalStore._decide  <== ONE TRANSACTION
                |                                  v                                    |  1 lock risk row FOR UPDATE
                v                          LossComponentStore (idempotent rows)         |  2 read reservations + positions
        AccountBalanceSnapshot --------->  DayRiskStore (day base, latch)               |  3 check_portfolio(candidate, rows) 
                |                                  |                                    |  4 insert reservation / refuse
                v                                  v                                    v
        resolve_live_equity(now, ttl)      live_daily_loss(day rows, base) -------> APPROVED + risk_reservations row
          |  None/stale -> UNCERTAIN_ACCOUNT_STATE            |
          v                                                   v
   AccountState(equity, risk_rate)        derive_daily_state(thresholds from DAY-START base)
          |                                                   |
          v                                                   +--> WARNING / DAILY_STOP transition
   evaluate_risk(...) -> execute_approved_plan                          |  persist latch (sticky to next UTC day)
   (open_positions = filled + resting + reserved, EXCLUDING self)      |  alert via JournalFirstAlertSink (DAILY_STOP CRITICAL)
          |                                                            +--> cancel resting entries: REST open orders -> expire_pending_entry(trigger "daily_stop")
          v                                                                   (stops/algo legs never touched)
   PlanConstraintSnapshot.equity_used = resolved equity
```

### Recommended Project Structure

```
src/
├── risk/
│   ├── live_equity.py        # pure: AccountEquityReading, LiveEquityResult, resolve_live_equity (mirror of live_commission.py)
│   └── daily_loss.py         # pure: DayRiskState, loss-component fold, live_daily_loss, sticky latch rules (no clock)
├── adapters/
│   └── binance_usdm.py       # + account_balance_snapshot(), account_config_snapshot(), user_trades_since() (read-only)
├── persistence/
│   ├── day_risk.py           # PgDayRiskStore: day row + idempotent loss-component rows
│   └── risk_reservations.py  # PgRiskReservationStore (+ hook into PgApprovalStore._decide)
├── db/alembic/versions/
│   └── 0010_day_risk_and_reservations.py   # hand-written, imports no project module (0009 style)
├── execution/
│   └── daily_stop.py         # orchestrator: latch -> alert -> cancel resting entries (REST truth), never a stop
└── ops/alerts.py             # + production producer for DAILY_STOP / DAILY_LOSS_WARNING (OPS05_MATRIX rows)
tests/fixtures/phase21/        # generated by scripts/gen_phase21_fixtures.py from the Phase 19 Demo capture
```
Module placement is Claude's discretion (CONTEXT); this layout keeps `src/risk` pure (stdlib + Decimal + `src.domain`) and puts every I/O seam where its neighbours already are. [ASSUMED: names]

### Pattern 1: Live equity resolver (RISK-01, criterion 1)
**What:** A pure function that turns an adapter reading + injected `now_utc` + ttl into an `AccountState` or a NO_TRADE reason. **When:** every live sizing and every placement. **Fields (read from the recorded capture, see "Equity field" below):** `totalMarginBalance` is THE equity; reject (UNCERTAIN_ACCOUNT_STATE) when any of `totalMarginBalance`, `totalWalletBalance`, `totalUnrealizedProfit` is missing/non-Decimal, when `totalMarginBalance != totalWalletBalance + totalUnrealizedProfit`, when the USDT `assets[]` row disagrees, when equity `<= 0`, when `multiAssetsMargin` is not `false`, or when age `> ttl` or `< 0`.

```python
# Source: pattern of src/risk/live_commission.py (read this session); names are proposals.
@dataclass(frozen=True)
class AccountEquityReading:
    equity: Decimal            # totalMarginBalance, USDT only (single-asset mode)
    wallet_balance: Decimal    # totalWalletBalance
    unrealized_pnl: Decimal    # totalUnrealizedProfit
    observed_at_utc: datetime  # injected clock read BEFORE the request (age only over-estimated)

def resolve_live_equity(*, reading: AccountEquityReading | None, risk_rate: Decimal,
                        now_utc: datetime, ttl: timedelta) -> LiveEquityResult:
    _require_utc_aware(now_utc, "now_utc")
    if ttl <= timedelta(0):
        raise ValueError(f"ttl must be positive, got {ttl}")
    if reading is None:
        return LiveEquityResult(account_state=None, reason_code="UNCERTAIN_ACCOUNT_STATE")
    age = now_utc - reading.observed_at_utc
    if age > ttl or age < timedelta(0):          # same predicate as check_portfolio / live_commission
        return LiveEquityResult(account_state=None, reason_code="UNCERTAIN_ACCOUNT_STATE")
    if reading.equity <= Decimal("0"):
        return LiveEquityResult(account_state=None, reason_code="UNCERTAIN_ACCOUNT_STATE")
    return LiveEquityResult(AccountState(equity=reading.equity, risk_rate=risk_rate), "OK")
```
`ttl` comes from the new limits key; `ttl <= 0` is a programming error (raises), a missing/`NOT_CONFIGURED` key means the live path already refuses at `LIMITS_NOT_CONFIGURED`.

### Pattern 2: Persisted day state + idempotent loss components (criterion 2)
**What:** `daily_risk_days` (PK = UTC date): `equity_at_day_start`, `base_observed_at_utc`, `state` (NORMAL/WARNING/DAILY_STOP), `stop_latched_at_utc` (NULL = not latched), `warning_alerted_at_utc`, `created_at_utc`. `daily_loss_components` (PK = deterministic key): `utc_day`, `kind` (`FILL_PNL`, `FILL_COMMISSION`, `FUNDING`), `source_key` (e.g. `order_id:trade_id`, or funding `symbol:time_ms`), `amount` (signed `NUMERIC(38,18)`), `asset`, `event_time_utc`, `source` (`USER_DATA_EVENT` / `REST_USER_TRADES` / `REST_INCOME`). Idempotency by `ON CONFLICT DO NOTHING` on the key, the idiom of `insert_pending`/`consume_and_record_entry_intent`. The pure function folds rows into `daily_loss_quote = max(0, -(sum))` exactly like `backtest/ledger.daily_loss_quote`. Sticky latch: once `stop_latched_at_utc` is set the state is DAILY_STOP for the whole day regardless of the fold (D-14); the next UTC day row starts NORMAL only after a fresh REST base read succeeds (D-08).

### Pattern 3: Thresholds against the DAY-START base
`resolve_absolute_thresholds(parameter_set=..., equity=<equity_at_day_start>)` turns **all four** rate keys (`cluster_cap`, `max_aggregate_open_risk`, `daily_loss_warning_threshold`, `daily_loss_stop_threshold`) into absolute amounts. The backtest does this for all four against `equity_at_day_start` (`src/backtest/ledger.py:_resolve_thresholds`, "re-resolved against the equity at each UTC day start ... never per booking"). Paper's `make_context_factory` resolves once against `account.initial_equity` (`src/paper/market_inputs.py:186-188`) which is wrong for a live day; the live path must use the persisted day-start base, not current equity. `AccountState.equity` (sizing) stays the CURRENT resolved equity, as the backtest feeds `ledger.equity` for sizing and `ledger.thresholds` for gates (`src/backtest/engine.py:_size_and_register`).

### Pattern 4: Atomic reservation at the approval decision (criterion 3)
**Where:** `PgApprovalStore._decide` (`src/persistence/approvals.py:219-260`) is the PENDING -> decided UPDATE; `dispatch_callback` reaches it through the injected `save_atomic(approval, mapping)` (`src/adapters/telegram_callbacks.py:485-494`). The SaveAtomic signature is pinned by a mypy conformance block, so the reservation should be a composed callable (or a store method called inside the same `db.transaction()`), not a signature change.
**How:** inside the one transaction: (1) `SELECT ... FOR UPDATE` on the current day-risk row (serialises all approvals; single operator, so contention is irrelevant), (2) read reservation rows with `status IN (RESERVED, PLACED, OPEN)` plus the state, (3) call the existing pure `check_portfolio` with the candidate and those rows as `OpenPosition`s, (4) on pass `INSERT` the reservation row with `trade_plan_id` UNIQUE and flip the approval to APPROVED; on a cap failure raise a typed refusal so the transaction (including the decision) rolls back and the plan stays PENDING until expiry; on any `PersistenceError` refuse (D-17). The reserved amount needs a source: add a nullable `approvals.reserved_risk NUMERIC(38,18)` written with the PENDING insert, exactly the D078/migration-0006 `approved_quantity` pattern (`NULL` = not recorded, refuse to approve). `execution_intents.sized_realized_risk` (`src/db/models.py:556`, migration 0005) is written only at consume time, i.e. too late for the reservation.
**Single source of truth for exposure:** keep ONE reservation row per plan for its whole life (RESERVED -> PLACED -> OPEN -> RELEASED with `open_risk` scaled on partial close like `ledger.update_exposure`), and do not additionally count `execution_intents` rows, otherwise the same plan is counted twice (Pitfall 2). The consume transaction (`consume_and_record_entry_intent`) already holds the approval row `FOR UPDATE`; flip the reservation to PLACED in that same transaction.

### Pattern 5: DAILY_STOP orchestration (criterion 2)
Order: latch the state (persisted) -> journal-first alert -> release unplaced reservations (reason `DAILY_STOP`) -> read REST open normal orders -> for each project ENTRY order call `expire_pending_entry` with a NEW trigger. `_EXPIRY_TRIGGERS` today is `{"expiry_time", "invalidation", "superseded_plan", "mode_change", "operator_close", "protective_unconfirmed", "protection_handoff_failed"}` (`src/execution/manager.py:1952-1965`); add `"daily_stop"` (an unknown trigger raises `ValueError`). `expire_pending_entry` is risk-reducing (acts first, verifies with `confirm_entry_cancel`) and returns a `CancelVerdict`; a `FILLED_OR_PARTIAL` verdict belongs to the protection coordinator. Never call `cancel_algo_order`/`cancel_untriggered_protectives` here. Do not use SAFE_MODE for DAILY_STOP: SAFE_MODE exit needs a clean reconcile and is a different state machine; DAILY_STOP is a daily latch that ends at the next UTC day (D-14).

### Anti-Patterns to Avoid
- **Summing `assets[]` for equity:** Demo shows `USDC walletBalance 5000.00000000` and `BTC 0.01000000` outside the totals; only `totalMarginBalance` is the USDT-only total.
- **Using the USDT row's `updateTime` as `observed_at`:** it is the last balance change (`1792589257306`), not the read time. Stamp with the injected clock read before the request, like `ConstraintProvider.refresh` (`market_inputs.py:111-128`).
- **Resolving thresholds against current equity** (paper pattern) in live: they must use the persisted day-start base.
- **Passing the candidate's own reservation in `open_positions` at placement:** `check_portfolio` already adds `sized.realized_risk` for the candidate (Pitfall 2).
- **Adding a `RejectionReason` member:** the enum is pinned to 21 members by `tests/test_phase20_gate.py` and GLOSSARY 9.1; use `UNCERTAIN_ACCOUNT_STATE` (equity/day-state unknown) and `DAILY_STOP_BLOCK`.
- **Treating the stream as the equity or the loss authority:** frames sent during a gap are not replayed (CONTEXT D-01, Demo-observed).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Portfolio gates | A second cap/daily-state evaluator | `check_portfolio`, `derive_daily_state`, `resolve_absolute_thresholds` (`src/risk/portfolio.py`) | Same code in backtest/paper/live (D-02 parity); first-failure order is pinned |
| Daily-loss definition | New loss formula | `backtest/ledger.daily_loss_quote` semantics (`max(0, -day_pnl)`), UTC midnight belongs to the new day (`apply_booking` doc) | One definition (D033) |
| Freshness predicate | New comparison | `age > ttl or age < timedelta(0)` (`portfolio.py:287`, `live_commission.py:149`, `gates.py:195`) | WR-B6 of 20-REVIEW shows the future-timestamp hole when this is forgotten |
| Entry cancel + verify + audit | New cancel code | `expire_pending_entry` + `confirm_entry_cancel` + `act_then_record` | Already handles -2011, verification, spill |
| REST gate / 418 ban handling | Own limiter | `BinanceUsdmAdapter._sdk_call` + `RestRateLimitGate` | A read must not bypass a pause (D081); never retries, never sleeps |
| Alert dedupe, journal-first, message retry | Own queue | `JournalFirstAlertSink.alert(...)` | Contract and closed event list exist (`ALERT_EVENTS`) |
| Idempotent inserts / transactions | Own session handling | `OperationalDatabase.transaction()`, `pg_insert(...).on_conflict_do_nothing(...)` | Typed errors (`StoreUnavailable`, `RowConflict`) already fail closed |
| Canonical JSON for evidence | Own serializer | `src.domain.canonical` (`canonical_bytes`, `sha256_hex`) | Used by the constraint snapshot digest |

**Key insight:** every pure rule this phase needs already exists and is shared; the risk is re-implementing a variant of it. The new code is inputs, persistence and orchestration.

## Runtime State Inventory

Not a rename/refactor/migration phase. Omitted. (Additive migration 0010 only; no existing stored string changes meaning.)

## Findings by research focus

### (a) Equity field and payload shapes
**Equity field: `totalMarginBalance`** (top-level of `GET /fapi/v3/account`), USDT-only in single-asset mode. Verbatim from the recorded capture `account_read_only_capture-rest-001-account_information.json` lines 114-124 [VERIFIED: file read this session]:

```
"availableBalance": "4999.09343961",
"maxWithdrawAmount": "4999.09343961",
"totalCrossUnPnl": "0.00000000",
"totalCrossWalletBalance": "4999.09343961",
"totalInitialMargin": "0.00000000",
"totalMaintMargin": "0.00000000",
"totalMarginBalance": "4999.09343961",
"totalOpenOrderInitialMargin": "0.00000000",
"totalPositionInitialMargin": "0.00000000",
"totalUnrealizedProfit": "0.00000000",
"totalWalletBalance": "4999.09343961"
```
and the USDT asset row (lines 75-87): `"assets.5.asset": "USDT"`, `"assets.5.marginBalance": "4999.09343961"`, `"assets.5.walletBalance": "4999.09343961"`, `"assets.5.unrealizedProfit": "0.00000000"`, `"assets.5.updateTime": "1792589257306"`. The same capture lists `"assets.7.asset": "USDC"` with `"assets.7.walletBalance": "5000.00000000"` and `"assets.4.asset": "BTC"` with `"assets.4.walletBalance": "0.01000000"` that are NOT in `totalWalletBalance`.
The SDK model (installed 17.4.0, `account_information_v3_response.py:35-90` [VERIFIED: read this session]) types EVERY field `Optional[StrictStr]` with the description "Total margin balance. USDT only in single-asset mode; USD-denominated in multi-assets mode." and the aliases `totalMarginBalance`, `totalWalletBalance`, `totalUnrealizedProfit`, `availableBalance`. [CITED: https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Account-Information-V3 (WebFetch this session)]: V3 `GET /fapi/v3/account`, IP weight 5, signed USER_DATA. Docs and capture agree; no difference to record. Because every field is optional, a missing field must fail closed (None -> UNCERTAIN_ACCOUNT_STATE), never default to zero.
`GET /fapi/v3/balance` (`...-002-account_balance_all.json`) has per-asset `balance`, `crossWalletBalance`, `crossUnPnl`, `availableBalance`, `maxWithdrawAmount`, `marginAvailable`, `accountAlias`, `updateTime` and NO `marginBalance` and no totals: for USDT `"5.balance": "4999.09343961"`, `"5.crossUnPnl": "0.00000000"`. Use it only as a cross-check (`balance + crossUnPnl`); note `accountAlias` (`"uX"`) is an account identifier: never log it, drop it from generated fixtures.
`GET /fapi/v1/accountConfig` (`...-003-account_config.json`): `"multiAssetsMargin": "false"`, `"dualSidePosition": "false"`, `"canWithdraw": "true"` (Demo). Refuse when `multiAssetsMargin != "false"` (O-3 default).

**ACCOUNT_UPDATE shape** [VERIFIED: `src/adapters/binance_userdata_events.py:205-208`, `:571-650`, `:1105-1151`; recorded frame `commission_vs_realized_pnl-003-ACCOUNT_UPDATE.json`]:
```
ACCOUNT_UPDATE_WIRE_FIELDS: frozenset[str] = frozenset({"m", "B", "P", "S"})
ACCOUNT_BALANCE_WIRE_FIELDS: frozenset[str] = frozenset({"a", "wb", "cw", "bc"})
ACCOUNT_POSITION_WIRE_FIELDS: frozenset[str] = frozenset(
    {"s", "pa", "ep", "bep", "cr", "up", "mt", "iw", "ps"}
)
```
Recorded frame: `"B": [{"a": "USDT", "bc": "0", "cw": "4998.80966909", "wb": "4998.80966909"}]`, `"P": [{... "ma": "USDT", "mt": "cross", "pa": "0.0008", "ps": "BOTH", "s": "BTCUSDT", "up": "0.01653711"}]`, `"m": "ORDER"`. The balance rows carry NO unrealized PnL and no margin balance; position rows carry `up` only for positions in the event ("only symbols whose position changed are pushed", `docs/integration/BINANCE.md:74`). `AccountUpdateEvent` docstring: "Nothing here (or anywhere in this module) computes equity, margin or a position view from these rows; REST stays the authority (D-05)". Conclusion: equity cannot be rebuilt from the stream; use `ACCOUNT_UPDATE` (any `m`) and `after_gap=True` items as a trigger for an immediate REST re-read. The Demo position row also has an extra wire key `ma` that is not in `ACCOUNT_POSITION_WIRE_FIELDS`; the parser tolerates it (the recorded-frames test lists it at `tests/test_userdata_recorded_frames.py:90`).
`m` reasons (documentation vocabulary, verbatim from `docs/integration/BINANCE.md:74`): DEPOSIT, WITHDRAW, ORDER, FUNDING_FEE, WITHDRAW_REJECT, ADJUSTMENT, INSURANCE_CLEAR, ADMIN_DEPOSIT, ADMIN_WITHDRAW, MARGIN_TRANSFER, MARGIN_TYPE_CHANGE, ASSET_TRANSFER, OPTIONS_PREMIUM_FEE, OPTIONS_SETTLE_PROFIT, AUTO_EXCHANGE, COIN_SWAP_DEPOSIT, COIN_SWAP_WITHDRAW. The `B`/`P` field table did not render in the 2026-10-16 doc read; the field meanings rest on the SDK model (a second doc fetch in this session also failed to render the page; not retried further).

**Demo-observed cross-check identity** [VERIFIED: fixtures `triggered_close_position_bracket-003/009-ACCOUNT_UPDATE.json` and `-010-ORDER_TRADE_UPDATE.json`]: before the closing fill `wb = 4998.74798621`; the closing `ORDER_TRADE_UPDATE` has `"n": "0.02616201"`, `"rp": "-0.00327999"`, `"N": "USDT"`; after it `wb = 4998.71854421`. `4998.74798621 - 4998.71854421 = 0.029442 = 0.00327999 + 0.02616201`, i.e. `delta wb = rp - n` with `bc = "0"`. This is demo-observed, not mainnet, one sample, reason `ORDER` only.

### (b) Where equity and daily loss are injected today
| Site | Today | Phase 21 change |
|------|-------|-----------------|
| `src/paper/market_inputs.py:184-204` `make_context_factory` | `account_state = AccountState(equity=account.initial_equity, risk_rate=account.risk_rate)`; thresholds against `account.initial_equity`; `daily_loss_quote=risk_inputs.daily_loss_quote(close)` from the `RiskInputsProvider` port (no implementation in `src`; bound to the SHADOW ledger) | None (D-05: paper keeps config/ledger equity) |
| `src/paper/loop.py:578-601` | `account_state`, `open_positions`, `daily_loss_quote` parsed from `case_input` | None |
| `src/backtest/engine.py:~855-870` `_size_and_register` | `AccountState(equity=self.ledger.equity, ...)`, `open_positions_for_risk(self.ledger)`, `daily_loss_quote(self.ledger)`, `parameter_set=self.ledger.thresholds`, `ttl=timedelta(0)` | None; it is the parity reference |
| `src/execution/manager.py:469-` `execute_approved_plan` | Takes `risk_kwargs` from the CALLER (`account_state`, `open_positions`, `daily_loss_quote`, `parameter_set`, `ttl`, `cost_rates`); `decide_placement` re-judges with the same `risk_kwargs["open_positions"]` and `["daily_loss_quote"]` | Phase 21 supplies a builder for these live inputs; the manager signature does not change (Phase 24 wires it) |
| `src/execution/live_context.py` `LivePlacementContext` | No equity or daily-state field | Add nothing required; equity enters via `risk_kwargs["account_state"]` and the snapshot |
| `src/execution/constraint_snapshot.py:222-264` `build_plan_constraint_snapshot` | `equity_used: Decimal | None = None`; `live_inputs_status` is COMPLETE only when `margin_type, leverage, equity_used, max_quantity, market_lot_*, percent_price_*` are all non-None | Pass the resolved equity as `equity_used` |
| `src/execution/gates.py` `decide_placement` | Fail-closed on `daily_loss_quote is None or not positions_reconciled`; `derive_daily_state` first | Unchanged; feed it the live values |

`snapshot_is_valid_for_live` is `COMPLETE` AND `age <= ttl` AND `age >= 0` (`constraint_snapshot.py:394-416`). For the D-18 test: build a `PlanConstraintSnapshot` with `equity_used=<resolved>` plus STUBBED `margin_type="ISOLATED"`-style text and an `int` leverage plus all six `ExchangeFilterExtras` and `max_quantity`, and assert it returns True; with `equity_used=None` assert False. `margin_type` must be non-empty text <= 16 chars and not the literal `"UNKNOWN"`; `leverage >= 1`. The stub values are TEST data, never a production default.
`PlanConstraintSnapshot.equity_used` must be `> 0` (`_require_optional_positive_decimal`).

**Portfolio caps and open positions:** `OpenPosition(symbol, position_side, open_risk, daily_pnl_contribution)`; `check_portfolio` sorts by `(symbol, position_side)`, adds the candidate's `sized.realized_risk` to the cluster and aggregate sums, and counts `len(open_positions)` for `MAX_POSITIONS_REJECT` (the candidate is not counted). `CLUSTER_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"})` is hard-coded (F-908; see Open Question 4). Only the backtest (`open_positions_for_risk(ledger)`, resting plans registered as exposures) and the SHADOW ledger build `OpenPosition` rows; there is NO live producer in `src` (grep: `OpenPosition(` appears only in `backtest/ledger.py`, `paper/loop.py`, `paper/replay_inputs.py`). The live producer is new work: filled positions (REST `snapshot_positions` + the plan's `sized_realized_risk` scaled by remaining/filled quantity), resting entries and reservations, all from one durable table (Pattern 4).

### (c) Persistence and the approval path
- Alembic head is `0009_validated_lot_filters` [VERIFIED: `tests/test_persistence_migration_pg.py:101`]; migrations are hand-written and import no project module (`0009` header). `tests/test_persistence_migration_pg.py:470` pins the head, so migration 0010 requires updating that pin and its upgrade/downgrade/reversibility cases; the ORM-parity tests cover every object (`SystemStateEventRow` docstring).
- `SystemStateKey` members: `SAFE_MODE`, `LIVE_ENABLEMENT`, `KILL_GATE` (`src/domain/enums.py:301-310`); the table CHECK lists the same three. `PgSystemStateStore.append` rejects non-`str|bool|None` values (Decimals would have to be text). Not a good home for the day figures (see Alternatives).
- `approvals` columns include `approved_quantity NUMERIC(38,18) NULL` (migration 0006), `consumption_status`, `consumed_at_utc`; unique index `uq_approvals_one_decided_per_plan` (one non-PENDING approval per plan). `execution_intents` PK `(approval_id, role)`, `UNIQUE (trade_plan_id, role)` (`uq_execution_intents_plan_role`), `sized_realized_risk NUMERIC(38,18) NULL` with `CHECK (sized_realized_risk IS NULL OR (role = 'ENTRY' AND sized_realized_risk > 0))`.
- `consume_and_record_entry_intent` already reads the approval row `FOR UPDATE` inside one transaction (D078 (5)); the reservation flip to PLACED belongs in that transaction.
- `PgApprovalStore._decide` uses `session.begin_nested()` around the conditional UPDATE and translates `uq_approvals_one_decided_per_plan` into `ApprovalAlreadyDecided`; a reservation refusal must roll back the whole outer transaction (do not catch it inside `begin_nested`).
- The paper side already has the same concept in memory + journal: `ShadowReservations` / `Reservation(sized_realized_risk, planned_quantity, ...)` with "reserve-at-confirm" (Q-C) over `ShadowLedger.admit(...)` under `ledger.lock`, rebuilt from the journal on restart (`src/paper/shadow_ledger.py:596-720`). Mirror its semantics (idempotent per `(plan_hash, approval_id)`, released on expiry/cancel/close, rebuilt from durable rows) but store them relationally for live so the cap check and the write share a transaction.

### (d) ORDER_TRADE_UPDATE `rp`/`n`/`N`, G3-009, funding, income
- **Parsing is done (Phase 18):** `OrderUpdateEvent` has `commission: Decimal | None` (`o.n`, signed allowed), `commission_asset: str | None` (`o.N`), `realized_profit: Decimal | None` (`o.rp`), `trade_id` (`o.t`), `is_maker` (`o.m`) [VERIFIED: `binance_userdata_events.py:397-404`, `:1027-1034`]. `to_fill_event` carries them onto `FillEvent(commission, commission_asset, realized_pnl, is_maker)` for TRADE events with positive quantity (`:1419-1445`). So the G3-009 "parse" half is complete; what is missing is the durable consumer (no store reads `FillEvent.commission` for daily loss) and the persistence of fills in the live path (`FillRow.commission` is `NOT NULL` with `commission >= 0` and `commission_asset NOT NULL`, so a `FillEvent` with `commission=None` cannot be persisted as is: treat it as UNKNOWN loss, fail closed).
- **Demo values** [VERIFIED: fixtures]: closing market fill `"n": "0.02616201"`, `"N": "USDT"`, `"rp": "-0.00327999"`, `"t": 549733079`; Account Trade List row `row_0_commission "0.02616332"`, `row_0_commission_asset "USDT"`, `row_0_realized_pnl "0"`, `row_0_trade_id "549732632"` (trade-list `trade_id` equals the stream `t` key space; stream and REST agree on commission in the sample). An entry fill's `rp` is `"0"`.
- **Funding:** `ACCOUNT_UPDATE` with `m = "FUNDING_FEE"` and `a.S` (parser: `funding_symbol` accepted only for FUNDING_FEE) is the stream carrier; the amount would be the USDT `bc` of that event [ASSUMED: bc carries the funding amount; no FUNDING_FEE frame was ever recorded on Demo]. REST `GET /fapi/v1/income` returned `"count": "0"` in the recorded tries (`commission_vs_realized_pnl-rest-007/008-income_history*.json`) and `19-OWNER-GAPS.md` R-A9 records "0 rows in all four tries" for the same account that had just traded, so even the trade commission/PnL did not show up in income on Demo. Funding settles at 00:00/08:00/16:00 UTC [ASSUMED: training knowledge], which makes the 00:00 UTC funding coincide with the day boundary (Pitfall 6).
- **realizedPnl semantics:** Demo trade list shows `realizedPnl` excludes commission (A9) and the wallet-delta identity above agrees. Mainnet is unverified (G2-042, Phase 24): `src/analytics/live_outcomes.py:65` sets `LIVE_NET_PNL_SEMANTICS_VERIFIED: bool = False`; this phase must not change it. Commission is added explicitly, and a non-USDT `commission_asset` (BNB) makes the day loss UNKNOWN unless an exchange-reported rate for that moment exists (D-11).

### (e) Alert producers
`ALERT_EVENTS` already contains `"DAILY_STOP": AlertSeverity.CRITICAL` and `"DAILY_LOSS_WARNING": AlertSeverity.WARNING` (`src/ops/alerts.py:112-113`). `OPS05_MATRIX` rows for both read `producer = _PRODUCER_PHASE21` ("Phase 21") and `phase20_delivers = "contract and test trigger only (emit_daily_state_alert); not end-to-end"` (`:850-865`). `emit_daily_state_alert(sink, *, state, subject, now_utc)` calls `sink.alert(event=..., subject=subject, reason=state.value, now_utc=now_utc)`. Two tests pin the current "no production caller" fact: `tests/test_alerts.py:~729-745` (AST scan: no `src` module other than `alerts.py` references `emit_daily_state_alert`) and `tests/test_alerts_ops05_matrix.py:174,198` (rows say `producer == "Phase 21"`; scan of `src` for the name). Phase 21 must either call `sink.alert(...)` directly from the new producer (keeps the scan green) or update both tests and the matrix rows in the same change; the `OPS05_MATRIX` text and `docs` must then say the producer exists but is unwired until Phase 24. The alert text is a fixed template; `subject` must match `[A-Za-z0-9][A-Za-z0-9_-]{0,127}` and `reason` an upper-case code, so never put an amount or equity value in an alert field.

### (f) NOT_CONFIGURED keys and registry
- `config/execution/execution-limits-v1.toml` holds 14 keys in 5 sections (protection, pre_placement, reconcile, stale_feed, alerts), all `"NOT_CONFIGURED"` with `[provenance.*]` mirrors; `ExecutionLimits` (kw_only, no defaults) has 14 fields; `EXECUTION_LIMIT_KEYS`/`EXECUTION_LIMIT_FIELDS` are the single mapping; any unset key makes `execute_approved_plan` return `LIMITS_NOT_CONFIGURED` (gate 2b).
- **Needed new key:** the equity max age. Recommended: section `account`, key `max_equity_age_ms` (field `account_max_equity_age_ms`) [ASSUMED: name]. Files to change together: `execution_limits.py` (keys, fields, dataclass), the TOML + provenance block, `config/execution/README.md`, `tests/support/execution_limits.py`, `tests/test_execution_limits.py` (pins the fourteen dotted names in file order, `:96`), `tests/test_phase20_gate.py` (`PHASE20_LIMIT_KEYS` assertions), `tests/test_no_unratified_defaults.py` scan, `docs/operations/SECURITY_AND_OPERATIONS.md` (mentions `dedupe_window_ms`). A set value needs a DECISIONS row and provenance `DECISION`. No number is chosen here (O-1).
- **Registry:** `daily_loss_warning_threshold = 0.005` and `daily_loss_stop_threshold` exist in the sets (`params/trend-pullback/baseline-v6.toml:51`), `max_open_positions = 2` (`:48`), `commission_rate_ttl_seconds = 3600` (`:67`). No new registry key is required for Phase 21. Do NOT edit `params/**/*.toml` (hash-locked; `registry-gate.yml` re-hashes against `tests/fixtures/phase4/parameters.json`).
- **Other NOT_CONFIGURED items that interact:** the rate-limit clock-margin key (D083) stays unset; do not add a code path that needs a ban end time.

### (g) Phase 20 review findings that touch modules this phase calls
From `20-REVIEW.md` (34 findings, none fixed; reviewers' claims, partly unverified by the orchestrator):
- **CR-C1** `src/ops/spill.py:238-243`: `LocalSpill.scan()` returns "nothing pending" on any `OSError`. `expire_pending_entry` and the alert sink write through the spill; a DAILY_STOP cancel audit can be silently lost. Do not rely on spill health in any new "is it safe" check.
- **WR-B6** `src/reconcile/feed_freshness.py:101-106`: `now_utc - seen_at_utc > limit` is False for a future timestamp (fail-open). The new equity predicate must use `age > ttl or age < 0` (it does by design); do not reuse `assess_feeds` for equity.
- **WR-C6** `alerts.py:616-654`: a CRITICAL alert whose send failed is never re-queued in-process and the dedupe window suppresses repeats. A `DAILY_STOP` alert can be lost until restart: the persisted latch and journal row (journal-first) are the durable record; do not make the alert the only signal.
- **WR-C8** `alerts.py:410-413`: journal-first alert is a blocking write before the action. In the DAILY_STOP orchestrator cancel the entries BEFORE awaiting the alert, or run the alert off-loop, so a journal outage cannot delay the risk-reducing cancel.
- **WR-C7** `risk_first.py:114-116`: `act_then_record` does a synchronous fsync write-ahead before the cancel (up to ~0.4 s on Windows `PermissionError`); acceptable but note it for latency.
- **WR-B2** a normal TP1 fill enters SAFE_MODE `UNSYNCED_ALGO`: a winning day produces SAFE_MODE, unrelated to DAILY_STOP but it blocks entries; do not conflate.
- **WR-C2/C3/C4** REST-gate state-file issues: a gate pause blocks the new account read; the equity read must treat `RestGateRefusal` as "no reading" (UNCERTAIN), not as an error to retry.

## Common Pitfalls

### Pitfall 1: Equity from the wrong total
**What goes wrong:** `availableBalance`, `totalCrossWalletBalance`, or a sum over `assets[]` is used. **Why:** `availableBalance` is net of margin (Phase 22's check); cross-only totals exclude isolated-margin wallet once Phase 22 sets ISOLATED (D035) [ASSUMED]; `assets[]` includes USDC/BTC. **Avoid:** read `totalMarginBalance`, enforce the three identities (total = wallet + unrealized; equals the USDT asset row's `marginBalance`; `multiAssetsMargin=false`). **Warning sign:** equity differs by the USDC amount (5000) from expectations.

### Pitfall 2: Double counting or self counting in the caps
**What goes wrong:** one plan counted as reservation AND ENTRY intent AND position; or the candidate's own reservation included in `open_positions` when `evaluate_risk` runs at placement (candidate risk is added again by `check_portfolio`). **Avoid:** one row per plan for its whole life; at placement exclude the candidate's `trade_plan_id` from the rows passed as `open_positions`; test with a plan that fits exactly (aggregate == cap) and assert it still passes at placement.

### Pitfall 3: Check-then-act across two transactions
**What goes wrong:** read totals, evaluate, then write in a second transaction; two approvals both pass. **Avoid:** lock row -> read -> `check_portfolio` -> insert in ONE `db.transaction()`; prove it with a two-connection PG test (`tests/test_*_pg.py`, `pg_db` fixture) where the second transaction blocks and then fails the cap.

### Pitfall 4: The SL-triggered close fill never reaches the loss feed
**What goes wrong:** the biggest loss (stop hit) is a fill of an order the project did not place directly. The router's `_route_order` forwards a `RoutedFill` only when `known_order(event.client_order_id)` is not None, otherwise it raises an `UNKNOWN_ORDER` anomaly and routes no fill (`binance_userdata_router.py:541-560`). Demo-observed: the triggered algo's resulting `ORDER_TRADE_UPDATE` carries `c` equal to the algo's `caid` (`dprobe-tbs-20261022T120704Z-12`, `i` 28645789207, `rp -0.00327999`, `cp true`). Whether the injected `known_order` lookup resolves an algo client id was NOT verified [ASSUMED]. **Avoid:** loss accounting must not depend solely on the router sink; use REST `userTrades` per symbol since the day start as the arbiter (D-09 cross-check), take the LARGER loss when sources disagree, and add a test with the recorded triggered-bracket frames. Same for manual closes, emergency closes (`xc-` ids) and exchange-forced closes (parser anomalies `FORCED_CLOSE_ORDER`, `LIQUIDATION_EVENT`).

### Pitfall 5: Lost frames during a stream gap
**What goes wrong:** Demo-observed frames sent during a gap are not replayed, so stream-only loss misses fills. **Avoid:** on `after_gap=True` and at startup, backfill the UTC day from REST (`userTrades` for each live symbol from `day_start`); idempotency keys make the double source safe (`order_id:trade_id`).

### Pitfall 6: Day boundary races
**What goes wrong:** (i) the base is read minutes after 00:00 so fills already inside the base are counted again (over-counts the loss: conservative but record `base_observed_at_utc`); (ii) the 00:00 UTC funding event lands on either side of the base read; (iii) a restart after 00:00 with no persisted row and trades already made today hides earlier losses; (iv) the clock source for "UTC day" differs between modules. **Avoid:** persist `base_observed_at_utc`; "midnight belongs to the new day" (ledger convention); with no row for today and any trade since 00:00 UTC, stay UNCERTAIN (fail closed) until reconstructed from REST or acknowledged (D-07); only the injected clock decides the day.

### Pitfall 7: DAILY_STOP implemented as SAFE_MODE or as a stop cancel
**What goes wrong:** reusing SAFE_MODE (sticky until a clean reconcile and an operator exit) or calling the protective-leg cancel helpers. **Avoid:** separate latch; the only cancels are entry orders via `expire_pending_entry`; assert in a test that no `cancel_algo_order` call occurs and that the protection registry state is untouched.

### Pitfall 8: Threshold base drift
**What goes wrong:** using current equity (including today's losses or unrealized PnL) for the 0.5%/1% base lowers the absolute stop as the day goes badly, or raises it after gains. **Avoid:** thresholds from the persisted day-start base only (Pattern 3); a unit test where equity rises intraday must not change the stop amount.

### Pitfall 9: Quantity and risk units for the reservation
**What goes wrong:** reserving `risk_budget` (equity x risk_rate) instead of the realized risk after rounding. **Avoid:** reserve `SizedResult.realized_risk` (the value `check_portfolio` adds, and the value the backtest registers as `open_risk`).

### Pitfall 10: Hard-coded USDT and account identifiers
Phase 27 makes the quote asset configurable; do not add new `"USDT"` literals beyond one named constant, and treat any non-quote commission asset as unknown (D-11). `accountAlias` must not appear in logs, alerts, fixtures or evidence.

## Code Examples

### Reading the account (adapter, read-only)
```python
# Source: BinanceUsdmAdapter.snapshot_positions pattern (src/adapters/binance_usdm.py:930-955, read this session);
# SDK method name verified in src/adapters/binance_probe.py:1066-1074 ("account_information_v3").
async def account_balance_snapshot(self) -> AccountBalanceSnapshot:
    response = await self._sdk_call(CallKind.QUERY, self._sdk.rest_api.account_information_v3)
    model = response.data()
    # Fields are Optional[StrictStr]; None means "not published" -> the caller fails closed.
    # Decimal(text) only; never float(...). Do not log the response or any accountAlias.
```
Stamp `observed_at_utc` with the injected clock BEFORE the call (as `ConstraintProvider.refresh` does), and treat `RestGateRefusal`/any exception as "no reading".

### Loss fold (pure)
```python
# Source: src/backtest/ledger.py:201-204 (daily_loss_quote), read this session.
def daily_loss_from_components(amounts: Sequence[Decimal]) -> Decimal:
    day_pnl = sum(amounts, Decimal("0"))      # realized PnL + (-commission) + funding, signed
    loss = Decimal("0") - day_pnl
    return loss if loss > Decimal("0") else Decimal("0")
```
Signs: `FILL_PNL = rp`, `FILL_COMMISSION = -n` (commission is a cost), `FUNDING = bc` of the FUNDING_FEE event (negative when paid) [ASSUMED sign].

### Reservation inside the approval transaction (shape)
```python
# Source: idioms from PgExecutionStateStore.consume_and_record_entry_intent (FOR UPDATE, on_conflict_do_nothing)
with self._db.transaction() as session:
    day = session.execute(select(DayRiskRow).where(...).with_for_update()).scalar_one()   # the lock
    rows = reserved_and_open_rows(session)                                               # same txn
    verdict = check_portfolio(sized=..., open_positions=rows, daily_loss_quote=..., ...)  # pure
    if verdict.is_no_trade:
        raise RiskReservationRefused(verdict.reason_code)    # rolls the decision back too
    session.execute(pg_insert(RiskReservationRow).values(...).on_conflict_do_nothing(...))
    self._decide(session, approval)                          # PENDING -> APPROVED, same txn
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `GET /fapi/v2/account` | `GET /fapi/v3/account` (weight 5, same field descriptions) | current docs list both V2 and V3 [CITED: Account-Information-V3 page] | Use V3 (the SDK method is `account_information_v3`) |
| `GET /fapi/v2/balance` | `GET /fapi/v3/balance` (`futures_account_balance_v3`) | same | Use V3 |
| Entry-time stop | Fill-driven protection (D079) | 2026-10-22 | DAILY_STOP cancels the ENTRY only; stops already protect fills |

**Deprecated/outdated:** `risk_inputs.open_positions` counting only filled positions (F-908/F-955); caller-supplied `equity`/`daily_loss_quote` constants in the live path.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Under ISOLATED margin (Phase 22) `totalMarginBalance` still equals `totalWalletBalance + totalUnrealizedProfit` and includes isolated positions' PnL, while `totalCross*` do not | Pitfall 1 | Equity would be understated/overstated once Phase 22 lands; the identity check fails closed, so the cost is NO_TRADE, not a wrong order |
| A2 | `GET /fapi/v1/userTrades` needs `symbol`, supports `startTime`, with a 7-day window cap and weight 5 | (d), Pitfall 4/5 | Backfill design must change (per-symbol loop, paging) |
| A3 | A FUNDING_FEE `ACCOUNT_UPDATE` carries the funding amount in the USDT `bc` | (d) | Funding component unknown; D-09 already labels funding "source unverified on Demo" |
| A4 | The injected `known_order` lookup resolves a triggered algo's `c == caid` | Pitfall 4 | SL fills may never reach the stream-fed loss; REST arbiter mitigates |
| A5 | Funding settles at 00:00/08:00/16:00 UTC | Pitfall 6 | Boundary race analysis differs |
| A6 | A single-row `FOR UPDATE` lock is enough to serialise approvals (one operator, one process) | Pattern 4 | A second process would need an advisory lock; behaviour is the same on PostgreSQL |
| A7 | Module/table/column/limit-key names (`live_equity.py`, `daily_risk_days`, `account.max_equity_age_ms`, ...) | structure | Cosmetic; CONTEXT leaves naming to the planner |
| A8 | Sign of funding in the fold (`bc`) | Code Examples | Wrong sign hides or inflates funding loss |

## Open Questions

1. **Equity basis vs the backtest (RISK-01 parity) - needs an owner answer.**
   - Known: the backtest `Ledger` is "realized-only (D-18): there is no mark-to-market" (`src/backtest/ledger.py:4-5`), so its sizing equity equals wallet balance. D-02 picks margin balance (wallet + unrealized). With a flat account they are identical (Demo: both `4999.09343961`). With an open position they differ, and thresholds/sizing would then no longer be byte-equivalent across backtest and live.
   - Unclear: whether D-02 intends to accept the difference. Candidates: `totalMarginBalance` (D-02), `totalWalletBalance` (backtest parity), the smaller of the two (most conservative; no number invented).
   - Recommendation: implement D-02 (`totalMarginBalance`) behind ONE named function so the basis is a one-line change, parametrize the unit tests over the basis, and record the choice as a new OWNER-OPEN item (O-5) for the planner to put in the plan's decision log.
2. **Where in the Telegram flow the reservation happens, and what the operator sees on refusal.** Recommended: at the PENDING -> APPROVED transition in the same transaction; on a cap failure the approval stays PENDING and the dispatch returns `ok=False` with the cap's reason code (`AGGREGATE_CAP_REJECT`, `CLUSTER_CAP_REJECT`, `MAX_POSITIONS_REJECT`, `DAILY_STOP_BLOCK`). Telegram wording belongs to Phase 23.
3. **Cross-check tolerance between stream/trade-list loss and the wallet-balance delta.** No tolerance exists and none may be invented. Recommended: use the LARGER of the two losses and emit a WARNING-class journal record on any non-zero difference; make a gating tolerance a NOT_CONFIGURED limit if the owner wants one.
4. **Cluster membership (F-908, F-014).** `CLUSTER_SYMBOLS` is hard-coded and excludes BNB; moving it to the registry changes parameter sets (new set + new `strategy_version`). Not required by the three success criteria; recommend leaving it and recording it as carried (audit refs F-908/F-014 are about counting resting/approved exposure, which D-15 covers).
5. **Day base when no persisted row exists but trades already happened today** (Pitfall 6 iii). Recommended default: UNCERTAIN_ACCOUNT_STATE until REST reconstruction succeeds; ask the owner whether an operator acknowledgement path is wanted (part of O-1 retention).
6. **Reservation release job and DAILY_STOP trigger wiring** are Phase 24; Phase 21 delivers the functions and the PG-tested store only.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | all commands | yes | 0.12.17 | — |
| Python | all | yes | 3.13.15 | — |
| PostgreSQL via `TEST_DATABASE_URL` | `*_pg.py` tests, migration 0010, reservation concurrency test | yes (set; `tests/test_system_state_pg.py` passed 28 dots this session) | — | none: PG tests skip locally, fail under `TRADING_CI_STRICT=1` |
| Docker daemon | `-m docker` suite only | yes (client 29.8.0) | — | not needed for this phase |
| Binance Demo REST/WS | Evidence only | owner-run | — | Phase 21 uses recorded fixtures; no `--execute` by the agent |

**Missing dependencies with no fallback:** none. **Missing with fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9, pytest-asyncio (`asyncio_mode = "auto"`), pytest-xdist (`-n 4`) [VERIFIED: `pyproject.toml`, `AGENTS.md`] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_<module>.py -x` (single file, seconds) |
| Full suite command | `uv run pytest -m "not docker" -n 4` (about 9-10 min; the orchestrator runs it once per phase) |
| TDD | `workflow.tdd_mode: true` in `.planning/config.json`: plan tests first |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RISK-01 | `resolve_live_equity`: OK path; None / stale (`> ttl`) / negative age / zero / negative equity -> `UNCERTAIN_ACCOUNT_STATE`; exactly ttl passes | unit | `uv run pytest tests/test_live_equity.py -x` | Wave 0 |
| RISK-01 | Account parsing from the recorded Demo payload: field choice, identity checks, missing field -> unknown, USDC/BTC rows ignored, `multiAssetsMargin` true refused, no float | unit (golden from script) | `uv run pytest tests/test_account_balance_snapshot.py -x` | Wave 0 |
| RISK-01 | Backtest/paper/live parity: same `evaluate_risk` verdict for equal inputs (existing parity fixtures untouched) | unit | `uv run pytest tests/test_cost_parity.py tests/test_risk_parity.py -x` (names to confirm) | partly exists |
| RISK-02 | Daily loss fold: signed components, idempotent re-delivery, `max(0, -pnl)`, boundary equality at warning/stop inclusive, UTC midnight belongs to new day | unit | `uv run pytest tests/test_daily_loss.py -x` | Wave 0 |
| RISK-02 | Thresholds from the persisted day-start base (equity rise intraday does not move the stop) | unit | `uv run pytest tests/test_daily_loss.py::test_thresholds_use_day_start_base -x` | Wave 0 |
| RISK-02 | Sticky DAILY_STOP survives restart and an equity rise; clears only at next UTC day after a fresh REST base; failed base read -> blocked | PG | `uv run pytest tests/test_day_risk_pg.py -x` | Wave 0 |
| RISK-02 | Missing/unreadable day row with position or resting entry -> NO_TRADE + alert (never fresh day) | PG + unit | same file | Wave 0 |
| RISK-02 | Commission asset not USDT with no rate -> unknown loss -> NO_TRADE | unit | `tests/test_daily_loss.py` | Wave 0 |
| RISK-02 | Recorded triggered-bracket frames: SL-close `rp`/`n` reaches the loss; wallet-delta identity `delta wb = rp - n` | unit (recorded) | `uv run pytest tests/test_daily_loss_recorded.py -x` | Wave 0 |
| RISK-02 | Caps count resting + reserved + open; candidate excluded from its own check | unit | `uv run pytest tests/test_live_open_positions.py -x` | Wave 0 |
| RISK-02 / F-407 | Two concurrent approvals, one fits: second refused, decision rolled back; reservation released on EXPIRED/SKIPPED/closed; rebuilt after restart; DB error -> refused | PG (two connections) | `uv run pytest tests/test_risk_reservations_pg.py -x` | Wave 0 |
| RISK-02 | DAILY_STOP: entries cancelled via `expire_pending_entry("daily_stop")`, zero `cancel_algo_order` calls, honours `RestGateRefusal`, alert emitted | unit with fakes | `uv run pytest tests/test_daily_stop.py -x` | Wave 0 |
| EXEC-01 | `PlanConstraintSnapshot` with live equity + stubbed Phase 22 inputs is `snapshot_is_valid_for_live`; with `equity_used=None` it is not (D-18) | unit | `uv run pytest tests/test_constraint_snapshot.py -x` (extend) | exists, extend |
| EXEC-01 | `_EXPIRY_TRIGGERS` includes `daily_stop`; unknown trigger still raises | unit | existing manager cancel tests (extend) | exists |
| OPS-05/OPS-02 | DAILY_STOP/WARNING producers emit through the sink with enum-like fields only; no amounts or account ids in alert fields or logs | unit | `uv run pytest tests/test_alerts.py tests/test_alerts_ops05_matrix.py -x` (update the "no production caller" pins) | exists, update |
| OPS-02 | Secret-free: no `accountAlias`/keys in logs, fixtures or evidence | unit (scan) | extend `tests/test_agents_md.py`-style scan or a new scan | Wave 0 |
| Schema | Migration 0010 upgrade/downgrade/reversible, ORM parity, head pin | PG | `uv run pytest tests/test_persistence_migration_pg.py -x` (update head pin to 0010) | exists, update |
| Gate | `tests/test_phase21_gate.py`: pure modules read no clock/float/SDK; limit key NOT_CONFIGURED; RejectionReason still 21 members; requirement-to-test names resolve | structural | `uv run pytest tests/test_phase21_gate.py -x` | Wave 0 (pattern: `tests/test_phase20_gate.py`) |

### Sampling Rate
- **Per task commit:** the touched test file(s) with `-x`, plus `uv run ruff check` and `uv run mypy src` on touched modules.
- **Per wave merge:** `uv run pytest -m "not docker" -n 4` is NOT run by subagents (AGENTS.md); they run their own tests only. PG files need `TEST_DATABASE_URL` in the process environment.
- **Phase gate:** orchestrator runs the sequential `uv run pytest -m "not docker"` with `TEST_DATABASE_URL` set and `TRADING_CI_STRICT=1`, plus `uv run python scripts/verify_decision_alignment.py all`, `uv lock --check`, ruff, mypy.

### Wave 0 Gaps
- [ ] `tests/test_live_equity.py`, `tests/test_account_balance_snapshot.py`, `tests/test_daily_loss.py`, `tests/test_daily_loss_recorded.py`, `tests/test_live_open_positions.py`, `tests/test_daily_stop.py`, `tests/test_phase21_gate.py`
- [ ] `tests/test_day_risk_pg.py`, `tests/test_risk_reservations_pg.py` (use `pg_db` from `tests/pg_support.py`)
- [ ] `scripts/gen_phase21_fixtures.py` + `tests/fixtures/phase21/` (+ `DERIVATIONS.md`): generated from the Phase 19 Demo capture; NOTE the capture files are flattened `summary` maps (`"assets.5.marginBalance"`), not raw responses, so the script must unflatten them into an SDK-shaped fake; strip `accountAlias`; fixtures are never hand-typed (AGENTS.md)
- [ ] Fakes in `tests/support/` for the account reader and day-risk store; reuse `fake_binance_exchange.py`, `reconcile_doubles.py`, `stream_sinks.py`, `userdata_frames.py`
- [ ] Framework install: none

## Security Domain

`security_enforcement: true`, `security_asvs_level: 1`, `security_block_on: high` (`.planning/config.json`).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (no new auth) | Existing signed adapter; OPS-02 key hygiene is an owner attestation |
| V3 Session Management | no | — |
| V4 Access Control | yes | Reads are `GET` only; the reservation refusal path is fail-closed; `LIVE_ORDERS_DISABLED` unchanged |
| V5 Input Validation | yes | Exchange payloads parsed as Decimal from text with type/finite checks; missing/odd fields -> unknown, never defaulted; classify exchange errors by type/code never by message |
| V6 Cryptography | no | — |
| V7 Error Handling and Logging | yes | structlog with class names only; no account identifiers, keys, URLs, balances-as-secrets; `src/ops/redaction.py` |
| V8 Data Protection | yes | Equity and PnL are not secrets but `accountAlias` and keys never persist in DB, logs or evidence |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Stale or replayed account read lets sizing use old equity | Tampering / Spoofing | Injected-clock age predicate `> ttl or < 0` -> NO_TRADE |
| Concurrent approvals exceed a cap (F-407) | Tampering | Single-transaction lock + check + insert; PG two-connection test |
| Lost stream frames hide a loss | Repudiation | REST arbiter (`userTrades`), idempotent keys, take the larger loss |
| Alert/journal outage hides DAILY_STOP | Denial of service | Persisted latch is the record; cancel before awaiting the alert (WR-C8) |
| Secret/identifier leak (`accountAlias`, keys) through logs or fixtures | Information disclosure | Fixed-template alerts, scrub fixtures, redaction, scan test |
| REST read bypasses a 418/429 pause | Denial of service | Only through `_sdk_call` + `RestRateLimitGate` |
| Demo key with `canWithdraw: true` mistaken for production posture | Elevation of privilege | Do not claim OPS-02; Phase 24-26 attestation |

## Sources

### Primary (HIGH confidence)
- Code read this session: `src/risk/portfolio.py`, `src/risk/live_commission.py`, `src/risk/gating.py`, `src/risk/types.py`, `src/core/types.py` (`AccountState`), `src/backtest/ledger.py`, `src/backtest/engine.py` (`_size_and_register`), `src/paper/market_inputs.py`, `src/paper/loop.py`, `src/paper/shadow_ledger.py`, `src/execution/{manager,gates,live_context,constraint_snapshot,execution_limits,intent_store}.py`, `src/persistence/{approvals,execution_state,system_state,uow,errors}.py`, `src/db/models.py`, `src/adapters/{binance_userdata_events,binance_userdata_router,binance_probe,binance_usdm,telegram_callbacks}.py`, `src/ops/alerts.py`, `src/domain/enums.py`
- Recorded Demo evidence: `.planning/phases/19-execution-plan-binding-price-check/evidence/fixtures/` (`account_read_only_capture-rest-001..003`, `commission_vs_realized_pnl-*`, `triggered_close_position_bracket-*`), `19-OWNER-GAPS.md` section 2a
- Installed SDK 17.4.0 model `account_information_v3_response.py`
- Binance docs: [Account Information V3](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Account-Information-V3) (fetched once this session)
- Project docs: `docs/DECISIONS.md` D033/D035/D079-D083, `docs/trading/RISK_MANAGEMENT.md` sections 8, 12, `docs/integration/BINANCE.md`, `docs/SOURCES.md`

### Secondary (MEDIUM confidence)
- `20-REVIEW.md` findings (reviewers' claims; the orchestrator re-read only CR-C1, WR-B1, WR-B2)
- Audit report rows F-012, F-013, F-014, F-407, F-908, F-955, F-963 (`.planning/audits/2026-09-29-deep-audit/DEEP_AUDIT_REPORT.md`)

### Tertiary (LOW confidence)
- Training knowledge flagged `[ASSUMED]` in the Assumptions Log (A1-A8). The ACCOUNT_UPDATE docs page (`Event-Balance-and-Position-Update`) did not render in two fetches this session (landing shell); field meanings rest on the SDK model and the repo's recorded read of 2026-10-16.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new dependency; versions confirmed.
- Architecture: MEDIUM-HIGH - seams read in code; the reservation/day-state schema is a design recommendation within planner discretion.
- Pitfalls: MEDIUM - Pitfalls 1-3, 7-9 are code-grounded; 4-6 depend on unverified lookup behaviour and Demo-only observations.
- Equity field: HIGH on Demo (capture + SDK model + docs agree); isolated-margin behaviour is ASSUMED.

**Research date:** 2026-10-22
**Valid until:** 2026-11-21 (stable code seams; re-read `src/execution/manager.py` and `src/ops/alerts.py` if Phase 22 lands first)
