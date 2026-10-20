# Phase 19: Execution Plan Binding + Pre-Placement Checks - Research

**Researched:** 2026-10-19
**Domain:** Binance USDⓈ-M execution safety: plan-to-order binding, pre-placement price checks, fill-driven protective stop (model (a) of D055), emergency reduce-only close, TP legs after the entry is terminal
**Confidence:** HIGH on the repository facts (every in-repo value below was read this session), MEDIUM on Binance REST facts (WebFetch summaries of the official pages), MEDIUM-HIGH on Binance user-data event value lists (raw markdown of the current page read 2026-10-19, see "Gap pass results"), UNVERIFIED only on `t` per partial fill, the full `rm` list, and the reduce-only/closePosition-with-position behavior

Label legend used for Binance behavior (from `19-NOTES.md`): `[DOC]` official page read this session (small-model summary, not a verbatim copy), `[DEMO]` observed on Demo in Phase 18 evidence, `[DESIGN]` reasoning, `[UNVERIFIED]` not confirmed anywhere. Provenance tags: `[VERIFIED: path:lines]` = the file was opened this session and the value is quoted verbatim; `[CITED: url]` = official page read this session; `[ASSUMED]` = not verified (all listed in the Assumptions Log).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

All decisions below were taken in `--auto` mode: the recommended option, or the direction the owner already adopted in `19-NOTES.md` (owner words 2026-10-18: "adopt kèm các điểm trên"). Nothing here edits `docs/DECISIONS.md`; the proposed D055 closure is a draft for the owner (`19-DEC-D055-DRAFT.md`).

**Binding the order to the hashed plan (criterion 1)**
- **D-01:** `execute_approved_plan` and `attach_protectives_to_fill` derive symbol and side from the hashed `TradePlan`, never from a caller argument. A caller-supplied symbol or side that disagrees is a rejection, not an override. The plan hash is re-derived and compared, not trusted.
- **D-02:** The placement quantity is `min`-bounded: it may be at most the approved quantity; a larger value rejects the plan and is never clipped up or down silently.
- **D-03:** SL and entry geometry is asserted again after the tick snap (G4-020: the planner has no tick size, so a stop within one tick of the zone edge can be snapped by the risk layer). A failed assertion is NO_TRADE with a reason code.
- **D-04:** `workingType = MARK_PRICE` is recorded on the plan (D037, F-507) and carried to every protective payload.

**Pre-placement refusals (criterion 2)**
- **D-05:** The entry is refused when mark or last price has crossed the SL or left the entry zone, when remaining validity is below the minimum, when another plan or position exists on the same symbol, or when `TradePlan.status` or the invalidation rule says the plan is invalid. GTD is set as the exchange-side expiry backstop.
- **D-06:** The live price is read through a new narrow adapter read (mark price) injected into the manager; the manager never reads the clock or the network itself (existing purity rule). A failed or stale price read is NO_TRADE (fail closed).
- **D-07:** The minimum remaining validity and the price-staleness bound are NOT chosen here. They are added to the versioned limits as `NOT_CONFIGURED`; the live path refuses while they are unset (same pattern the repo already tests for ratified keys). The owner fills the numbers.
- **D-08:** `INVALIDATED` keeps two meanings today (planner D-07 reject versus approval and binding invalidation, G4-017). Introduce a distinct reason code for the pre-placement invalidation when criterion 2 is built, without renaming the existing one.
- **D-09:** An executed plan stays `APPROVED`; `expiry_utc` governs only an unfilled entry and nothing moves an executed plan to `EXPIRED` (G4-036, D051 item i). The plan-status check must not contradict this.

**Protection model after the fill (criterion 3, D055 direction)**
- **D-10:** One model only: STOP_MARKET `closePosition=true` placed after the first fill with positive quantity (stream or REST; PARTIALLY_FILLED counts). No `quantity`, no `reduceOnly` on that leg. The current placement of the stop right after the entry (gate 6, near `manager.py:613` and the SL intent near `:818`) is replaced by fill-driven placement. — **Reversibility:** costly — changes the order of every entry flow and the intent state machine; undoing it needs a new migration of intent states and re-proving on Demo.
- **D-11:** A position is not protected until Binance confirms the stop by REST query; `NEW`, HTTP success or `ALGO_UPDATE FINISHED` alone is not evidence. No new entry while any position is unprotected.
- **D-12:** On the first fill, stop placement and the cancel of the entry remainder start together, neither waits for the other; both are reconciled until the stop is confirmed and the entry is terminal. The failure branches (stop confirmed but entry not terminal; entry terminal but stop unconfirmed; both ambiguous; a new fill after the stop triggered; `-2021` after a fill) follow `19-NOTES.md` section "Fill, stop and entry remainder" verbatim.
- **D-13:** Two deadlines, kept separate: `max_unprotected_ms` and `entry_terminal_timeout`. Both are `NOT_CONFIGURED` limits keys; the live path refuses while they are unset; no placeholder number is a decision. The owner sets them after the probes.
- **D-14:** Hedge Mode is not supported in V1: if position mode detection returns hedge, the live path refuses (fail closed). Hedge payload differences are tested offline only.

**Emergency close (criterion 3, D034)**
- **D-15:** `ExecutionAdapter` gains a MARKET reduce-only close method (One-way: `reduceOnly=true`, closing side) with a deterministic client order id per attempt; an ambiguous result is queried by that id before anything is resent; never a duplicate close. A failed emergency close never declares the position safe.
- **D-16:** Above the symbol's MARKET_LOT_SIZE max, close in valid parts, re-check the position after each part, every part within live exchangeInfo filters. If no valid part can be built or a part fails or is ambiguous: SAFE_MODE, critical alert, keep reconciling, manual intervention. Splitting is proven offline with fake filters.
- **D-17:** `attach_protectives_to_fill`'s statement "no rescue placement is ever issued (D-02)" is corrected: D034 supersedes D-02. `emergency_manual_close` keeps its operator role; the automatic close is a separate path.

**TP legs (criterion 4)**
- **D-18:** No continuous TP1 resizing for late fills (settles G2-032 for the normal flow). TP1 and TP2 are placed only after the entry is terminal and the final quantity equals the reconciled real position. TP1 quantity comes from real exposure, floored to stepSize, never above the closable position; TP2 is `closePosition=true` without quantity or reduceOnly. One-way and Hedge payloads are tested separately.
- **D-19:** TP legs are quantized to LOT_SIZE (MARKET_LOT_SIZE for a triggered market exit, filters read from exchangeInfo at runtime). The system does not rely on a MIN_NOTIONAL exemption for reduce-only legs and treats their rejection as a possible failure.
- **D-20:** TP intent rows are written ahead with `record_protective_intent`, and `snapshot_is_valid_for_live` is checked before placement; a stale snapshot is re-sized or refused (G4-038).

**Taxonomy and persistence**
- **D-21:** The manager reads the Phase 18 exchange-error taxonomy (`classify`, `retry_eligible`, `safe_mode_eligible`). A refusal raised before anything is sent (rate-limit gate, `EntriesBlocked`, `SignedCallPolicyMissing`) must not be treated as an ambiguous send (no spurious SAFE_MODE or UNKNOWN intent). This is src/WR-02 from the Phase 18 review.
- **D-22:** `realized_risk` is persisted with the live fill record so live R is no longer INCOMPLETE (G4-008, D052 item f). It needs an Alembic migration; follow the Phase 17 migration conventions.

### Claude's Discretion
- Module layout for the new fill-driven protection coordinator, naming of new reason codes, and how fakes model fill and cancel races.
- Test structure (one race test per branch in D-12, offline).

### Deferred Ideas (OUT OF SCOPE)
- Model (b): pre-placed explicit-quantity stop (Demo accepted it; not built).
- Hedge Mode support; TP1 far-half rule (999.1); maker or post-only entries; `binance-sdk-algo` TWAP/VP.
- Phase 18 review items WR-08, WR-01, WR-10 and the CR-02 liveness gap (owner decisions; see `19-NOTES.md`).
- G4-006: the live producer of the TP1 quantity and exit ladder uses the backtest fraction and `size_protectives_to_filled_qty`; wire it only when the producer exists.

### OWNER-OPEN (planner records them as blockers, does not implement)
- **O-01:** D055 closure as a DECISIONS row (draft in `19-DEC-D055-DRAFT.md`). Until the owner accepts it, LIVE stays blocked and the plan must make the D-10 flow the only flow but not enable live orders.
- **O-02 (T-04, EXEC-07):** the TP1 split fraction is a code constant by D052 item (c); EXEC-07 asks for a versioned registry parameter. Auto default: change nothing, keep the constant, leave EXEC-07 Pending with a note. Reconciling needs a protocol-level decision because the backtest fraction is frozen.
- **O-03 (G4-007):** criterion 4 says fall back to a single TP when a leg is below minQty; backtest rule D-27 says an un-sizeable TP1 is NO_TRADE. The two must move together. Auto default: implement the refusal (NO_TRADE) and do not implement the single-TP fallback until the owner decides.
- **O-04:** numeric limits (D-07, D-13) and the Phase 18 skipped review items WR-08, WR-01, WR-10 and the CR-02 liveness remainder (`19-NOTES.md`, last section).
- **O-05:** the 11 Demo probes listed in `19-NOTES.md`; the user runs every `--execute`.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description (REQUIREMENTS.md) | Research Support |
|----|-------------------------------|------------------|
| APRV-01 | Telegram alerts carry symbol, direction, setup, entry, SL, TP(s), RR, risk, expiry, invalidation, exposure, reason codes (status `[x]`, Phase 8) | Phase 19 closes the loop "what the human saw is what is placed": symbol and side must come from the persisted Signal bound to the hashed plan (section "Binding", Findings F1-F3). No new alert text is built here (Phase 23 owns Telegram UX). |
| APRV-02 | Approval bound to SignalId + strategy version + plan hash + expiry + chat + one-time token, idempotent (status `[x]`, Phase 8) | Plan-hash re-derivation from the TradePlan's own fields (F2); replay path stays before every new gate (F4). |
| EXEC-01 | LIMIT-zone entries and Algo-Order protective exits, both position modes, partial-fill protective sizing (Pending, Demo-proven evidence owned by Phase 24/25) | Fill-driven stop (D-10/D-12), GTD entry backstop, MARKET reduce-only emergency close, TP legs after entry terminal. Stays Pending after this phase (library-proven offline only). |
| EXEC-02 | Reconciliation compares local vs exchange, sweeps orphans, SAFE_MODE on divergence (Pending, Phase 8; Phase 20 hardens) | Phase 19 supplies the state vocabulary and durable rows Phase 20 consumes (F6, Pitfall P8). Stays Pending. |
| RISK-04 | Never increases risk because of previous losses or an unmet target; never adds to a losing position (Pending, Phase 19) | Same-symbol refusal (D-05), quantity <= approved (D-02), no TP1 resizing / no "carry on" after a stop-triggered new fill (D-12 branch 4). Test map in Validation Architecture. |
| EXEC-07 | TP1 split fraction, TP2 rule and time in force as versioned registry parameters, not code constants (Pending, Phase 19) | Blocked by O-02: default is no change, EXEC-07 stays Pending with a note. The GTD time in force is a structural choice of this phase, not a registry parameter. Guard test pins `TP1_QUANTITY_FRACTION` and the backtest parity. |
</phase_requirements>

## Project Constraints (from AGENTS.md; no `./CLAUDE.md` is read by the project config beyond `~/.claude/CLAUDE.md`)

- Python 3.13, `Decimal` for every exchange-sensitive value, `float` forbidden in execution core (tests `test_execution_core_has_no_float_in_placement_math`). Ruff line length 100, `mypy` strict on `src`, pytest `asyncio_mode = "auto"`.
- Pure core: `src/core` imports only stdlib and Decimal. The execution manager imports no SDK, no SQLAlchemy, no Pydantic, never reads the wall clock (injected `now_utc`).
- Fail closed: uncertain data/connection/account/risk gives NO_TRADE; SAFE_MODE blocks entries while monitoring and reconciliation continue.
- Exchange authority: Binance is canonical for orders, fills, positions, PnL, fees, conditional orders; dynamic exchangeInfo (stepSize, tick, notional), Algo-Order endpoints, position-mode detection, 200-conditional-order headroom are re-verified against current docs and never hard-coded from memory.
- Quantization: floor to stepSize, reject below min quantity, reject below min notional, reject below `minimum_risk_utilization_after_rounding`; NO_TRADE preferred over round-up; identical logic backtest/paper/live (RISK_MANAGEMENT section 11, D031).
- Parameter sets are versioned and hash-locked (`params/<family>/`): an existing set is never edited in place. A value is never chosen or tuned from backtest results.
- Source precedence when documents conflict: DECISIONS.md > `docs/` > AGENTS.md > `.planning/` (D031).
- Tech stack is fixed: no new dependency is needed by this phase (see Standard Stack).
- GSD workflow enforcement: file-changing work goes through a GSD command (research only writes this file).
- Network rule (orchestrator): on a Binance/Telegram connection error retry at most once, then record the gap. Applied; see "Network gaps".

## Summary

Phase 19 changes the order of the whole live entry flow. Today `execute_approved_plan` (src/execution/manager.py) places a LIMIT entry and immediately places a `closePosition` STOP_MARKET (gate 6, lines 614-907). Demo rejects that stop with -4509 while no position exists, so the flow always ends `ENTRY_WITHOUT_PROTECTIVE`. The new model (D-10, owner-adopted in `19-NOTES.md`) places the stop only after the first fill with positive quantity and cancels the entry remainder at the same moment. Nothing in `src/` drives protection from a fill today: `attach_protectives_to_fill` is called only by `scripts/demo_rehearsal.py` and tests. The main new work is therefore a **fill-driven protection coordinator** (async, injected clock/sleep/adapter/store, consumed by the Phase 18 router sinks) plus the pre-placement checks, an emergency MARKET reduce-only close with MARKET_LOT_SIZE splitting, and the persistence of `realized_risk`.

The research found six facts that the CONTEXT does not state and that change how the plans must be cut. (1) `TradePlan` has no symbol and no side; the hash covers only signal id, entry zone, SL, TP json, invalidation json, expiry (planner `_plan_hash`), so D-01 needs the persisted `Signal` (symbol, direction) bound by `plan.signal_id`, cross-checked against geometry and the plan constraint snapshot. (2) The ratified limits file `config/binance/binance-limits-v1.toml` is sha256-pinned in a DECISIONS row and its loader and README tests demand exactly 27 keys, so the `NOT_CONFIGURED` keys of D-07/D-13 must live in a **new** file with its own loader, not in the ratified file. (3) The risk-layer `ConstraintSnapshot` carries no MARKET_LOT_SIZE or max quantity; only `PlanConstraintSnapshot`/`SymbolFilters` do, so the emergency-close splitter needs its own filter input. (4) `size_protectives_to_filled_qty` is called directly by the frozen backtest (`protective_levels_for_fill`), so it must not be edited; TP leg sizing for Phase 19 needs a new live-only function. (5) The intent state machine and DB CHECKs allow only roles ENTRY/STOP_LOSS/TAKE_PROFIT_1/TAKE_PROFIT_2 with one row per (approval, role); an emergency close (several parts and attempts) cannot be stored there, and adding an `OrderRole` member ripples through enum-parity tests, the role CHECK, `ROLE_CODES` and GLOSSARY. (6) Binance's GTD time in force needs `goodTillDate` more than 600 seconds in the future with second precision [CITED], which sets a structural floor under the "minimum remaining validity" and must be honored independently of the owner's NOT_CONFIGURED number.

**Primary recommendation:** Build Phase 19 as pure, injected, offline-testable units in this order: (a) test scaffolding (stateful fake exchange with positions, partial fills, MARKET close, mark price, scripted completion order) and a new execution-limits loader; (b) pure modules for binding, pre-placement checks, geometry-after-snap, MARKET_LOT_SIZE splitting and TP leg sizing; (c) adapter methods (mark price, MARKET reduce-only close, GTD on `place_entry`, executed quantity on probes); (d) manager rewrite to the D-10 flow plus the protection coordinator with one race test per D-12 branch; (e) one hand-written Alembic migration 0005 (`realized_risk`, plus a durable table for close attempts if the planner adopts it) with the three head-pinned tests made head-agnostic in the same change. LIVE stays blocked on O-01; the code makes D-10 the only flow but does not enable live orders.

### Owner-open blockers (recorded, not designed around)

| ID | What blocks | Consequence for the plan |
|----|-------------|--------------------------|
| O-01 | D055 closure not accepted | Build the D-10 flow as the only flow; do not enable live orders; do not edit `docs/DECISIONS.md` or ROADMAP criteria; docs edits that assert the model wait for acceptance. |
| O-02 | EXEC-07 vs frozen `TP1_QUANTITY_FRACTION` | No code change to the constant or the backtest; EXEC-07 stays Pending with a note; add a guard test. |
| O-03 | single-TP fallback vs backtest D-27 | Implement NO_TRADE refusal for an un-sizeable TP1 at pre-placement; do not implement the fallback. |
| O-04 | numeric limits; WR-08, WR-01, WR-10, CR-02 remainder | New keys stay `NOT_CONFIGURED`; live path refuses while unset; tests use TEST_ONLY values. |
| O-05 | 11 Demo probes | No `--execute` by the executor; probes are written/validated offline only. |
| New, found by this research (not in CONTEXT) | (i) a 429/418 gate pause refuses protective placement, cancel and the emergency close too (Phase 18 review src/WR-12); (ii) the second `place_entry` attempt (`_ENTRY_MAX_ATTEMPTS = 2`) is not covered by D-21 and the reviewer asked for its removal or an explicit decision; (iii) no fresh-exchangeInfo fallback is decided for the emergency close | Do not decide these. Record as owner questions (Open Questions Q4, Q5, Q3). Plans must not claim they are solved. |

## Architectural Responsibility Map

The template's web tiers do not fit this system; tiers below are the project's own layers.

| Capability | Primary tier | Secondary tier | Rationale |
|------------|-------------|----------------|-----------|
| Plan-to-order binding (symbol, side, qty bound, hash re-derivation, geometry after tick snap) | Pure execution core (`src/execution`, new pure module) | Persistence read (Signal, PlanConstraintSnapshot by id) injected by caller | Decision logic must be a pure function of injected inputs; persisted rows are the only source of symbol/side. |
| Pre-placement price/validity/same-symbol/status/invalidation checks | Pure execution core | Adapter (mark price read), config (limits) | Manager never reads clock/network (D-06). |
| Mark price read | Binance adapter (`BinanceUsdmAdapter` or `BinancePublicMarketData`) | — | SDK imports are adapter-only. |
| GTD expiry backstop | Binance adapter payload (`good_till_date`) | Pure core computes the value from `plan.expiry_utc` | Exchange-side cancel when the process is dead. |
| Fill-driven stop + entry-remainder cancel, deadlines, CLOSE_REQUIRED | Protection coordinator (async, injected adapter/clock/sleep/store/safe-mode) | Phase 18 router sinks feed it; Phase 20 reconciler reads its state | Needs concurrency and deadlines; not a pure function. |
| Emergency MARKET reduce-only close + MARKET_LOT_SIZE splitting | Pure splitter + coordinator step + adapter method | Persistence of attempts | Splitting is arithmetic (pure, offline-provable); sending is adapter. |
| TP leg sizing from real exposure | New pure sizing function (live-only) | Reuses `quantize_price` and snap rules | `size_protectives_to_filled_qty` is shared with the frozen backtest and must not change. |
| Exchange-error taxonomy use in the manager | Domain (pure `classify`) with an injected exception-to-facts function or a pure pre-send-refusal marker | Adapter owns SDK exception mapping | Manager cannot import `binance_errors` (SDK). |
| Limits `NOT_CONFIGURED` | New config file + loader in `src/adapters` (like `binance_limits.py`) | Manager receives the loaded object | Ratified file is hash-pinned. |
| `realized_risk` persistence | PostgreSQL (migration 0005) via `PgExecutionStateStore` | Analytics reads it | Single writer at approval consumption. |

## Standard Stack

### Core (all already installed; versions from the lockfile statement in AGENTS.md and the venv)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.13.15 [VERIFIED: `uv run python` this session] | runtime | project baseline |
| binance-sdk-derivatives-trading-usds-futures | 17.4.0 [VERIFIED: docstring `src/adapters/binance_usdm.py:29` "Installed package: binance-sdk-derivatives-trading-usds-futures 17.4.0"] | `new_order` (MARKET, `reduce_only`, `good_till_date`), `new_algo_order`, `mark_price(symbol)` | the official connector; behind the adapter only |
| SQLAlchemy / psycopg / Alembic | 2.0.x / 3.3.x / >=1.19.2 (pyproject) | PostgreSQL stores and migration 0005 | Phase 17 conventions |
| pytest 9.1.1 + pytest-asyncio 1.4.0 [VERIFIED: `uv pip list`] | tests | `asyncio_mode = "auto"` |
| ruff 0.16.8 [VERIFIED: `uv run ruff --version`], mypy strict | gates | CI commands |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | 26.1.0 (AGENTS.md installed state) | log sites | only literal event names and scalar fields (secret-posture test) |
| `tests/support/virtual_time.py` (in repo) | — | injected clock and sleep for deadline tests | every deadline/race test |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Deterministic grid/parametrized tests for splitting | hypothesis | hypothesis is not installed and a new dependency is not justified; use exhaustive small grids with fake filters |
| New limits file | extend `binance-limits-v1.toml` | rejected: sha256-pinned by DECISIONS D072 row; loader refuses unknown keys (Findings F9) |

**Installation:** none. No package is added by this phase.

**Version verification:** the SDK enums and signatures below were read from the installed package this session:
`NewOrderTypeEnum` members `LIMIT`, `MARKET`, `STOP`, `STOP_MARKET`, `TAKE_PROFIT`, `TAKE_PROFIT_MARKET`, `TRAILING_STOP_MARKET`; `NewOrderTimeInForceEnum` members `GTC`, `IOC`, `FOK`, `GTX`, `GTD`, `RPI`; `new_order(... reduce_only: Optional[NewOrderReduceOnlyEnum] = None, ... good_till_date: Optional[int] = None, recv_window ...)`; `mark_price(self, symbol: Optional[str] = None,) -> ApiResponse[MarkPriceResponse]` [VERIFIED: .venv/Lib/site-packages/binance_sdk_derivatives_trading_usds_futures/rest_api/models/enums.py and rest_api/rest_api.py:1473-1476].

## Package Legitimacy Audit

No external package is installed or upgraded by this phase. `gsd-tools query package-legitimacy check` was not run because there is nothing to check.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Findings: current code (focus item 1)

### F1. Where symbol, side and quantity come from today
`execute_approved_plan` takes symbol from `risk_kwargs["constraint_snapshot"].symbol` and side from `risk_kwargs["candidate_position_side"]` (both caller-supplied dicts); quantity is `sized.quantity` from `evaluate_risk` [VERIFIED: src/execution/manager.py:615-649]:
```
    trade_plan = risk_kwargs["trade_plan"]
    constraint_snapshot = risk_kwargs["constraint_snapshot"]
    _require_live5_symbol(constraint_snapshot.symbol)
    ...
    candidate_side = risk_kwargs["candidate_position_side"]
    ...
    quantity: Decimal = sized.quantity
    entry_side = "BUY" if candidate_side == "LONG" else "SELL"
    sl_side = "SELL" if candidate_side == "LONG" else "BUY"
```
`attach_protectives_to_fill` takes `candidate_position_side`, `plan_hash`, `protective_template` and `constraint_snapshot` as caller arguments [VERIFIED: manager.py:1144-1156]. Nothing compares them with the approved plan.

### F2. `TradePlan` carries no symbol and no side
The dataclass fields are `trade_plan_id, signal_id, trade_plan_version, entry_model, entry_min_price, entry_max_price, stop_loss_price, take_profit_json, invalidation_rule_json, expiry_utc, expected_rr_json, risk_rate, risk_budget, suggested_quantity, quantity_before_rounding, quantity_after_rounding, quantization_decision, plan_hash, status, created_at_utc` [VERIFIED: src/domain/trade_plan.py:55-74]. The hash input is:
```
            "signal_id": signal_id,
            "entry_min_price": canonical_decimal_text(entry_min_price),
            "entry_max_price": canonical_decimal_text(entry_max_price),
            "stop_loss_price": canonical_decimal_text(stop_loss_price),
            "take_profit_json": take_profit_json,
            "invalidation_rule_json": invalidation_rule_json,
            "expiry_utc": expiry_utc,
```
[VERIFIED: src/core/planner.py:78-87]. So "derive symbol and side from the hashed TradePlan" (D-01) cannot be literal. What is hash-bound: the geometry (a LONG stop is below the zone, a SHORT stop above; `_plan_hash` includes all three prices) and `signal_id`. `Signal.symbol` and `Signal.direction` are plain fields of the persisted `Signal` (`src/domain/signal.py`); `signal_id = make_signal_id(... symbol=snapshot.symbol ... setup_fingerprint=fingerprint)` where the fingerprint hashes `direction` among zone/ATR/EMA values [VERIFIED: src/core/strategy.py:261-286 and 900-908, src/domain/ids.py:19-46]. The signal id cannot be recomputed from the stored `Signal` (the fingerprint inputs are not stored), so binding of symbol/direction rests on the persisted Signal row reached by `plan.signal_id`.
**Recommended binding [DESIGN]:** a pure function `bind_plan(trade_plan, signal, plan_constraint_snapshot_symbol, caller_symbol, caller_side)` that (1) re-derives the hash from the TradePlan's own fields and compares it with `plan.plan_hash`, `callback.plan_hash` and `approval.request_hash`; (2) requires `signal.signal_id == trade_plan.signal_id`; (3) takes `symbol = signal.symbol`, `side = signal.direction`; (4) requires the geometry-implied side (stop below entry_min = LONG, above entry_max = SHORT) to equal `signal.direction`; (5) requires `constraint_snapshot.symbol == signal.symbol` and the caller `candidate_position_side == signal.direction`; any mismatch is NO_TRADE with a reason code, never an override. Do NOT add symbol/direction to `plan_hash`: D051 item (c) records plan_hash as bound into approvals and fixtures (a one-way door) and the Phase 4 fixtures moved once already.
`_plan_hash` is private to `src/core/planner.py`; expose a public, behavior-identical re-derivation (for example a thin public wrapper) and pin it with a golden-hash test so the algorithm is provably unchanged.

### F3. Geometry rules that already exist
`_plan_geometry_is_valid` (src/risk/gating.py:43-60) accepts a stop inside the zone ("A stop inside the zone is deliberately NOT rejected here"); the planner rejects a stop not strictly outside the whole zone (STOP_TOO_TIGHT, D054 D-06) [VERIFIED: gating.py docstring lines 44-52; GLOSSARY 9.1 text]. The live code then snaps the limit price to the tick grid (BUY floors, SELL ceils) and the SL trigger toward the entry (`sl_trigger_rounding`: LONG up, SHORT down) [VERIFIED: placement.py:191-202]. A stop within one tick of the zone edge can therefore snap onto or past the limit. D-03 asserts, after both snaps: LONG `sl_trigger < limit_price`, SHORT `sl_trigger > limit_price`, and each of limit/SL still on the proper side of the zone edges. Test with a one-tick-wide margin grid.

### F4. Gate order and what must stay before/after
Fixed order today: 0 identity (+ stored-outcome replay with zero adapter calls, before the expiry gate), 1 binding+expiry, 1b approval-authorizes-plan, 2 enablement, 3 SAFE_MODE, 4a live cost rates, 4b risk, 5 placement gates, 6 placement [VERIFIED: manager.py:468-614]. New refusals (binding, status/invalidation, same-symbol, price, validity, limits NOT_CONFIGURED, hedge) are pre-placement and must NOT consume the approval (existing rule: "Pre-placement NO_TRADE verdicts above never consume"); they go after gate 5 and before the position-mode detection/`consume_and_record_entry_intent`. The binding re-derivation of the hash belongs with gate 1b. The replay path must keep returning the stored outcome before any new gate (tests `test_replay_after_expiry_returns_the_stored_outcome_with_zero_adapter_calls`).
`_GATE_KWARG_KEYS` pins exactly three keys: `frozenset({"open_algo_count", "planned_leg_count", "positions_reconciled"})` [VERIFIED: manager.py:313-315]. New live inputs (mark-price result, signal, open entry orders, latest closed-bar close, limits) must be new required keyword parameters, not extra `gate_kwargs` keys, or `test_missing_live_gates_raise_before_any_adapter_call` and the key-set check need deliberate changes.
`HEADROOM_LIMIT: int = 200` [VERIFIED: src/execution/gates.py:42] and `planned_leg_count` (4 for entry + SL + TP1 + TP2) must stay 4 at entry time: if headroom were checked only at entry with count 1, the later stop could be refused for lack of capacity and leave a naked position.

### F5. `TradePlan.status` handling (D-05, D-09)
`TradePlanStatus` members: `READY`, `APPROVAL_PENDING`, `APPROVED`, `EXPIRED`, `INVALIDATED`, `SUPERSEDED` [VERIFIED: src/domain/enums.py:32-40]. Legal moves: `APPROVED` goes only to `EXPIRED` or `INVALIDATED`; `SUPERSEDED` is illegal from `APPROVED` [VERIFIED: src/domain/transitions.py:98-120]. A grep of `src/` for `TradePlanStatus.APPROVED` finds only `transitions.py`: no production code sets a plan APPROVED yet [VERIFIED: grep this session]. Consequence: the status check must be a **deny-list** (refuse `EXPIRED`, `INVALIDATED`, `SUPERSEDED`), not "require APPROVED", otherwise every plan is refused today. A replayed approval of an executed plan returns the stored outcome before this check (D-09).
The plan's invalidation rule is `{"basis": "CANDLE_CLOSE", "level": <stop_loss_price>, "break_distance_atr": ...}` (planner.py:666-678); a CANDLE_CLOSE rule needs the latest **closed strategy-bar close**, which no current manager input provides. `src/backtest/entry.py:102-136` has the pure parser/predicate (`invalidation_level`, `is_invalidated`) [VERIFIED]. Do not import `src.backtest` from `src.execution` (backtest already imports `src.execution.placement`); re-implement the 20-line pair in the execution core (or lift to `src/core`) and pin parity with a test. The bar-close value is a new required input (Open Question Q6).

### F6. Intent state machine and persistence
`ExecutionIntentStatus` members: `INTENDED`, `SENT`, `ACKED`, `REJECTED`, `UNKNOWN`; transitions: INTENDED -> SENT, UNKNOWN, REJECTED; SENT -> ACKED, REJECTED, UNKNOWN; UNKNOWN -> ACKED, REJECTED; ACKED and REJECTED terminal [VERIFIED: src/domain/enums.py:259-272; src/domain/transitions.py:205-224]. Table `execution_intents`: PK `(approval_id, role)`, `UniqueConstraint("trade_plan_id", "role", name="uq_execution_intents_plan_role")`, role CHECK `"role IN ('ENTRY', 'STOP_LOSS', 'TAKE_PROFIT_1', 'TAKE_PROFIT_2')"`, status CHECK `"intent_status IN ('INTENDED', 'SENT', 'ACKED', 'REJECTED', 'UNKNOWN')"`, `intended_quantity` nullable (close-position legs carry none), client-id-by-role CHECK [VERIFIED: src/db/models.py:513-598].
Implications:
- The existing machine models "the send" only. It has no state for "fill detected", "stop confirmed (ACTIVE)", "CLOSE_REQUIRED" or "emergency close in progress". `CLOSE_REQUIRED` does not exist anywhere in `src`, `docs`, `config` or `tests` [VERIFIED: grep this session]. The CONTEXT sentence "changes the intent state machine ... needs a new migration of intent states" is **avoidable** for the stop: write the STOP_LOSS intent INTENDED at the moment of the first detected fill (its `intended_at_utc` is then the durable start of `max_unprotected_ms`), SENT before `place_algo_protective`, ACKED only when the response or a REST query is class ACTIVE (existing `_is_leg_confirmed` rule), else UNKNOWN. Keep the in-process protection state as a pure enum journaled on every transition; the exchange (REST) is the truth after a restart.
- TP intents: `record_protective_intent` has no `intended_quantity` parameter and inserts NULL quantity [VERIFIED: src/persistence/execution_state.py:207-243; Protocol src/execution/intent_store.py:100-118]. TP1 is an explicit-quantity leg, so D-20 needs the Protocol, `PgExecutionStateStore`, `InMemoryExecutionIntentStore`, `AlwaysWinsIntentStore`, `CrashAfter`, `FailingIntentStore` (and `BarrierBeforeConsume.__getattr__` passthrough) in `tests/support/intent_store_fakes.py` to change together. TP2 is `closePosition` (NULL quantity) and fits today.
- The emergency close needs several parts and attempts per plan, which one (approval, role) row cannot hold, and a new `OrderRole` member would require changing `ROLE_CODES` (order_ids.py:47-52), the role CHECK, the enum-parity tests (`test_enum_check_lists_exactly_the_current_enum_values`), GLOSSARY, `intent_recovery` and the analytics role maps. **Recommendation [DESIGN]:** do not extend `OrderRole`; add a small append-only table (for example `emergency_close_attempts`: `approval_id`, `attempt_no`, `client_order_id`, `part_quantity`, `status`, timestamps, FK to the plan) in migration 0005 together with `realized_risk`, with a deterministic id `x`-style prefix that fits 36 chars (prefix + hash slice + attempt counter). Alternative (journal events only) is lighter but is not queryable state after a restart. This is Claude's-Discretion territory: the planner must pick and justify.
- Restart: `resolve_unresolved_intents` marks any intent whose deterministic id is found as ACKED regardless of the algo status [VERIFIED: src/execution/intent_recovery.py:193-212: `if answer.found is True: target = ExecutionIntentStatus.ACKED`]. ACKED therefore means "the exchange knows the order", not "protection confirmed". The coordinator and Phase 20 must evaluate `exchange_status` through `is_protection_confirmed` (ACTIVE only).

### F7. Algo status classes (protection evidence)
`AlgoStatusClass` has ACTIVE, TERMINAL_OK, TERMINAL_FAILED, UNKNOWN; by the owner's 2026-10-16 decision TRIGGERING, TRIGGERED, FINISHED and CANCELED are UNKNOWN, NEW is ACTIVE, REJECTED and EXPIRED are TERMINAL_FAILED; only ACTIVE confirms protection [VERIFIED: src/domain/algo_status.py module docstring lines 9-18]. Consequence for D-12 branch 4: a stop in TRIGGERING/TRIGGERED/FINISHED is "consumed", never "protected"; the coordinator must decide with a REST position read, not with the algo class.

### F8. Adapter surface
`ExecutionAdapter` Protocol (manager.py:91-111) has seven methods: `place_entry(**kwargs)`, `place_algo_protective(**kwargs)`, `query_order_by_client`, `query_algo_order_by_client`, `get_position_mode`, `cancel_normal_order`, `cancel_algo_order`. `BinanceUsdmAdapter` additionally has `snapshot_positions`, `snapshot_open_normal_orders`, `snapshot_open_algo_orders`, `user_commission_rate`, and delegates `exchange_info`/klines/funding to `BinancePublicMarketData` (src/adapters/binance_usdm.py:542-1291). Gaps for Phase 19:
- **Mark price:** none. The only `mark_price` in src is a funding-history field and `mark_klines` (binance_public.py:145, 427-453). The SDK method exists (F-Binance-3). Add `get_mark_price(symbol) -> MarkPriceReading(symbol, mark_price, exchange_time_utc)` and unwrap the oneOf wrapper: `MarkPriceResponse` holds `actual_instance` = `MarkPriceResponse1` (single symbol) or a list; all fields are `Optional`, so a missing `markPrice`, `time` or a different `symbol` must raise (flag never fabricate), exactly like `user_commission_rate`.
- **MARKET reduce-only close:** none. `place_entry` hard-codes `NewOrderTypeEnum.LIMIT`; the manager docstring says "`ExecutionAdapter` has no close-position method" (manager.py:1604-1610). Add `place_market_close(symbol, side, position_side, quantity, new_client_order_id)` using `type=MARKET`, `reduce_only=NewOrderReduceOnlyEnum.TRUE` for One-way, no `_require_entries_allowed()` (the drift guard blocks entries only; protective/risk-reducing calls must not be blocked by it), one attempt, never retried.
- **GTD:** `place_entry(time_in_force: str, ...)` has no `good_till_date`; the SDK has `good_till_date: Optional[int]` and `NewOrderTimeInForceEnum.GTD`. Add the parameter (keyword, required when GTD). The fakes bind kwargs against the **real** signature (`_bind_real`), so adapter first, fakes second.
- **Fill detection by REST:** `OrderProbe` has only `found, order_id, status, update_time_utc` (binance_usdm.py:407-421); there is no executed quantity, so a REST-only PARTIALLY_FILLED cannot be sized. Add `executed_quantity` (and average price) to the probe built from `QueryOrderResponse`, or add a dedicated method; `AlgoOrderProbe` likewise lacks `actual_order_id`/executed quantity.
- **Exchange filters at close time:** `ExecutionAdapter` has no `exchange_info`. Inject a `filters_provider` or add a Protocol method; `SymbolFilters` carries `market_lot_min_quantity`, `market_lot_max_quantity`, `market_lot_step_size` (binance_public.py:182-184).
- **Signed policy / gate:** every signed call goes through `_sdk_call` -> `gate.check()` (a 418/429 pause refuses it, nothing sent). Pitfall P3.

### F9. Limits file and the numeric-default guard
`CANONICAL_KEYS` has exactly the 27 keys of sections client, signed_calls, drift, stream; the loader refuses a missing or unknown key and any section outside `client, signed_calls, drift, stream, provenance` [VERIFIED: src/adapters/binance_limits.py:43-80, 353-372]. The word `none` is accepted only for three nullable keys; a PLACEHOLDER provenance label refuses to load. `NOT_CONFIGURED` is not a value of this loader (it appears only in the environment rows of `binance_client.py` and in `tests/test_binance_limits_ratified_file.py:246`).
Three hard pins on the ratified file: `test_decisions_row_pins_the_limits_file_hash` compares the file's sha256 with the DECISIONS row (D072) [VERIFIED: tests/test_binance_limits_ratified_file.py:356-361]; the README key-list test asserts `assert len(keys) == len(set(keys)) == 27` [VERIFIED: tests/test_no_unratified_defaults.py:318]; the record-equality tests compare every key with the decision record. **Adding the Phase 19 keys to `binance-limits-v1.toml` or to `config/binance/README.md`'s `` - `section.key` - `` bullet format would break all three.** The CONTEXT phrase "added to the versioned limits as NOT_CONFIGURED" must be implemented as a **second file** (suggested `config/binance/binance-execution-limits-v1.toml`, README as a separate document) with its own loader module that:
- accepts a positive integer or the exact string `NOT_CONFIGURED` per key (maps to `None`);
- exposes `require_live_ready()` that raises a typed error naming unset keys (never values);
- has no numeric default in code, and the scan guard `GUARDED_NAMES` in `tests/test_no_unratified_defaults.py` is extended with the new key names (`max_unprotected_ms`, `entry_terminal_timeout`, the validity and price-staleness keys) so the "forbids numeric defaults" test covers them;
- is passed to the manager as a required parameter; unset means NO_TRADE (plain-string reason such as `LIMITS_NOT_CONFIGURED`, listed in GLOSSARY 9.3) before any adapter call;
- uses TEST_ONLY values from a `tests/support` module that production code may not import (same rule as `tests/support/limits.py`).
Key names for the four values are Claude's discretion; use the `_ms`/`_seconds` suffix convention and keep `max_unprotected_ms` and `entry_terminal_timeout` as written in D-13 (consider `entry_terminal_timeout_ms` for unit clarity and record the choice).

### F10. Reason codes
`RejectionReason` has exactly 20 members and a test pins it: `assert len(RejectionReason) == 20` [VERIFIED: tests/test_domain_enums.py:235]; GLOSSARY section 9.1 equals the enum (gate GL-03) and section 9.3 lists plain-string codes emitted outside the enum (`DISABLED`, `ENTRY_WITHOUT_PROTECTIVE`, `NO_FILL`, ...) [VERIFIED: docs/GLOSSARY.md:150-215]. `ExecutionOutcome.reason_code` accepts any non-empty string except `OK` for NO_TRADE. **Recommendation:** add the new codes (D-08 distinct pre-placement invalidation, price crossed SL, price left zone, validity too short, symbol busy, price read failed, limits not configured, hedge unsupported, binding mismatch) as plain strings with new rows in GLOSSARY 9.3 (and SAFE_MODE reasons such as `CLOSE_REQUIRED` in 9.4) instead of growing the enum, which would force the count test, GL-03, GLOSSARY 9.1 and every `PlacementGateVerdict` validation to move. Do not rename `INVALIDATED`.

### F11. Router sinks and fill sources
The Phase 18 router takes plain synchronous callables (`fill_sink(RoutedFill)`, `status_hint_sink(OrderStatusHint)`, `exchange_state_sink`, `algo_sink(AlgoRoute)`, `divergence_sink`) described as "record or enqueue"; a raising sink is journaled and does not stop routing [VERIFIED: src/adapters/binance_userdata_router.py:436-473 and module docstring]. `to_fill_event(OrderUpdateEvent)` yields a `FillEvent` only for a TRADE with positive last-filled quantity [VERIFIED: src/adapters/binance_userdata_events.py:1419-1433]. The coordinator must therefore expose a **non-blocking enqueue entry point** the sinks call, and run its own asyncio task; it must treat `RoutedFill.after_gap` and `FillSource.REST_FALLBACK` as valid first-fill evidence. `OrderStatusHint` is "never a state change"; a stream fill is a hint, REST is the authority (Phase 18 D-05), so the coordinator confirms entry-terminal and stop status by REST query.

### F12. Backtest coupling (what must NOT change)
`src/backtest/exits.py` calls `size_protectives_to_filled_qty` with `ProtectiveTemplate(tp1_quantity_fraction=TP1_QUANTITY_FRACTION)` ("nothing is re-derived") [VERIFIED: exits.py:5-6, 315-327]; `TP1_QUANTITY_FRACTION = Decimal("0.5")` and `SIMULATOR_SEMANTICS_VERSION = "2.3.0"` [VERIFIED: src/backtest/semantics.py:30,34]. Editing `size_protectives_to_filled_qty`, `quantize_protective_qty`, `build_sl_leg`, `ProtectiveTemplate` or the TP trigger rounding changes backtest results and needs the D032/D043 amendment procedure and a version bump. Phase 19 must add new live-only functions beside them and leave these untouched; add a regression test that calls both with identical inputs and asserts byte-identical legs.

### F13. Live R after G4-008
`normalize_live_outcomes(..., sized_risks: Mapping[str, SizedRisk] | None)` takes `SizedRisk(realized_risk, planned_quantity)` per `trade_plan_id`; a missing entry gives `INCOMPLETE(NO_RISK_VALUE)` [VERIFIED: src/analytics/live_outcomes.py:96-116, 182-207, 262-274]. Persisting `sized.realized_risk` fixes **NO_RISK_VALUE only**. `LIVE_NET_PNL_SEMANTICS_VERIFIED: bool = False` [VERIFIED: live_outcomes.py:77] keeps every closed live outcome INCOMPLETE(UNVERIFIED_EXCHANGE_SEMANTICS), and this session's read of the official Account Trade List page again found only the field names with "Realized Pnl." and no statement on commission [CITED: developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Account-Trade-List]. Define D-22's acceptance as "NO_RISK_VALUE no longer emitted when the intent row carries the figure", not "live R complete". **Recommended storage [DESIGN]:** nullable `sized_realized_risk NUMERIC(38,18)` on the ENTRY row of `execution_intents` (CHECK `>= 0` and only for role ENTRY), written inside `consume_and_record_entry_intent` (INSERT, no later UPDATE, so the terminal-status triggers are not touched), read back as `SizedRisk(realized_risk=row.sized_realized_risk, planned_quantity=row.intended_quantity)`. `IntentRecord` and the Protocol method gain a field/parameter (all four test doubles change).

## Findings: Binance facts (focus item 2)

| # | Fact | Tag | Source and exact words |
|---|------|-----|------------------------|
| B1 | `closePosition` on STOP_MARKET/TAKE_PROFIT_MARKET closes the whole current position when triggered (SELL closes long, BUY closes short); cannot be sent with `quantity` or `reduceOnly`; in Hedge Mode cannot be used with BUY in the LONG side or SELL in the SHORT side; `positionSide` must be sent in Hedge Mode | [DOC] | New Algo Order page (WebFetch 2026-10-19), plus repo docs/SOURCES.md row "closePosition constraints (not with quantity, not with reduceOnly, whole current position when triggered)" |
| B2 | The page is silent on whether `closePosition` needs an open position | [DOC] silent | same fetch: "The page does not say whether an open position is required." Demo answered -4509 while flat | 
| B3 | `-4509` text: "Time in Force (TIF) GTE can only be used with open positions. Please ensure that positions are available." Category `PRECONDITION_NO_POSITION` on PLACEMENT | [DEMO] | src/domain/exchange_errors.py:346-358; evidence/18-probe-check.txt line 38 |
| B4 | Probe 1 (closePosition stop **with** a position open) was never run; only a reduce-only explicit-quantity stop with a position open was accepted | [DEMO] gap | 18-DRAFT-D055 "What the probe could not observe" |
| B5 | Algo endpoint `POST /fapi/v1/algoOrder`: order-rate weight 1 on the 10s window and 1 on the 1min window, 0 on IP weight | [DOC] | New Algo Order fetch 2026-10-19 |
| B6 | `timeInForce` values on New Order: GTC, IOC, FOK, GTX, GTD, RPI. `goodTillDate`: "order cancel time for timeInForce `GTD`, mandatory when `timeInforce` set to `GTD`". Window: "The goodTillDate timestamp must be greater than the current time plus 600 seconds and smaller than 253402300799000." int64; "the timestamp only retains second-level precision, ms part will be ignored"; "In extreme market conditions, `timeInForce` `GTD` order auto-cancel time might be delayed compared to `goodTillDate`." | [DOC] | New Order page (WebFetch 2026-10-19). The page does not state the resulting status or expire reason, and `GTE_GTC` is not mentioned on New Order or New Algo Order. |
| B7 | `reduceOnly`: "Cannot be sent in Hedge Mode", default false. Nothing more about MARKET reduce-only was in the retrieved (truncated) text | [DOC] partial | New Order fetch; the MARKET reduce-only rejection codes are `-2022 REDUCE_ONLY_REJECT` "ReduceOnly Order is rejected." and `-2024 POSITION_NOT_SUFFICIENT` in the repo taxonomy [VERIFIED: src/domain/exchange_errors.py:496-509] |
| B8 | `LOT_SIZE`: quantity at least `minQty`, at most `maxQty`, difference from `minQty` an exact multiple of `stepSize`. `MARKET_LOT_SIZE` "sets quantity rules for MARKET orders" with the same three checks. `MIN_NOTIONAL` "defines the minimum notional value allowed for an order"; for market orders the mark price is used; no text on a reduce-only/closePosition exemption (the error-code page has "-4164 MIN_NOTIONAL Order's notional must be no smaller than %s (unless you choose reduce only)") | [DOC] | common-definition page (WebFetch 2026-10-19); 09-EXCHANGE-FACTS.md Fact 4 (archive snapshot 2026-06-16) |
| B9 | Demo filters BTCUSDT: market lot min 0.0001, max 120, step 0.0001; out-of-range case NOT_OBSERVED | [DEMO] | evidence/18-probe-check.txt line 46 |
| B10 | Mark price: `GET /fapi/v1/premiumIndex`, IP weight "1 with symbol, 10 without symbol"; optional `symbol`; fields `symbol, markPrice, indexPrice, estimatedSettlePrice, lastFundingRate, interestRate, nextFundingTime, time` (strings; `nextFundingTime` and `time` int64 ms). The page does not state the array variant's fields | [DOC] | Mark Price page (WebFetch 2026-10-19). SDK method `mark_price(symbol)`; `MarkPriceResponse` is a oneOf wrapper (`actual_instance`) with every field Optional [VERIFIED: SDK models mark_price_response*.py] |
| B11 | Account-wide limit of 200 conditional orders; `MAX_NUM_ALGO_ORDERS` filter removed 2025-12-29 | [CITED] | docs/SOURCES.md; 09-EXCHANGE-FACTS.md Fact 5 |
| B12 | ORDER_TRADE_UPDATE and ALGO_UPDATE field lists, execution types, order statuses, `t` presence on partial fills, ALGO_UPDATE status definitions | [DOC] for the value lists (x, X, er, ALGO_UPDATE statuses, read 2026-10-19 at `https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/user-data-streams.md`, raw markdown saved, not a summary); [UNVERIFIED] for `t` on every partial fill and the full `rm` value list | The field-level schema (`t`, `gtd`, `rm`) is an OpenAPI schema the page embeds and the tool could not render; the legacy page shows only example frames (`"t":0 // Trade Id`, `rm` = "Reduce Only reject"). The repository parsers (`OrderUpdateEvent`, `AlgoUpdateEvent`, `ORDER_STATUS_VOCABULARY`) and recorded Demo frames stay the working basis for field presence (probe 3 for `t`). |
| B13 | A `closePosition` algo order is tied to an open position (TIF "GTE" in -4509), and the ALGO_UPDATE page (archive snapshot 2026-01-13) says EXPIRED is "canceled by the system. An example would be when a user places a GTE_GTC Time-In-Force conditional order but then closes all positions on that symbol" | [CITED, archive] but applicability to a plain `closePosition` stop is [UNVERIFIED] | 09-EXCHANGE-FACTS.md Fact 6. Probe 6 of `19-NOTES.md` is the only way to settle it. Phase 20 NOTES item G4-035 asks the same question. |

## Architecture Patterns

### System Architecture Diagram

```
 Telegram APPROVE (Phase 23 owns UX)                    Phase 18 user-data stream (WS)
        |                                                ORDER_TRADE_UPDATE / ALGO_UPDATE
        v                                                         |
 execute_approved_plan                                            v
  0 identity -> stored-outcome replay (zero adapter calls)   UserDataRouter sinks (sync, enqueue only)
  1 binding+expiry -> 1b approval authorizes plan                 |
  [NEW] bind_plan: hash re-derived, Signal(symbol, side),         | RoutedFill / AlgoRoute / OrderStatusHint
        geometry, caller mismatch => NO_TRADE                      v
  2 enablement  3 SAFE_MODE  4a cost rates  4b risk          ProtectionCoordinator (async task)
  5 placement gates (planned_leg_count stays 4)                    |
  [NEW] pre-placement: limits ready? hedge? status deny-list,      | first positive fill (stream OR REST poll)
        invalidation(bar close), same-symbol, validity>600s+min,   v
        mark price (adapter read, staleness) vs SL/zone       asyncio.gather (start together)
  [NEW] snapped geometry assert (D-03)                       +-- place STOP_MARKET closePosition (write-ahead SL intent)
  position-mode detect (hedge => refuse)                     |        -> REST query => ACTIVE? = PROTECTED
  consume approval + ENTRY intent (+ sized_realized_risk)    +-- cancel entry remainder -> REST query => terminal?
  place_entry LIMIT, GTD = plan expiry (adapter)                   |
  (NO stop at entry time any more)                                 +--> branches B0..B5 (see Race tests)
        |                                                          |     deadlines: max_unprotected_ms, entry_terminal_timeout
        v                                                          v
   entry rests / fills ------------------------------------>  CLOSE_REQUIRED => emergency close:
                                                               MARKET reduceOnly parts (MARKET_LOT_SIZE split),
        when entry terminal AND stop ACTIVE AND position       query by id before resend, re-check position,
        reconciled: place TP1 (explicit qty, reduceOnly)        failure => SAFE_MODE + alert, never "safe"
        + TP2 (closePosition), write-ahead intents, snapshot
        validity check (D-20)
```

### Recommended Project Structure (names are Claude's discretion; this is a suggestion)
```
src/execution/
├── binding.py              # pure: bind_plan(), hash re-derivation, geometry-after-snap (D-01..D-04)
├── pre_placement.py        # pure: price/validity/same-symbol/status/invalidation verdicts (D-05..D-09)
├── lot_split.py            # pure: MARKET_LOT_SIZE part builder, LOT_SIZE+MARKET_LOT_SIZE quantizer (D-16, D-19)
├── tp_sizing.py            # pure, live-only TP1/TP2 from real exposure (D-18); does NOT touch placement.py sizing
├── protection.py           # async ProtectionCoordinator + ProtectionState enum + branch logic (D-10..D-12)
├── emergency_close.py      # async close loop using lot_split + adapter.place_market_close (D-15, D-16)
├── execution_limits.py     # (or src/adapters/) loader for the NOT_CONFIGURED file (D-07, D-13)
└── manager.py              # rewired flow; attach_protectives_to_fill corrected (D-17)
src/adapters/binance_usdm.py   # + get_mark_price, place_market_close, good_till_date, executed qty on probes
src/db/alembic/versions/0005_*.py  # hand-written; realized_risk (+ optional close-attempt table)
config/binance/binance-execution-limits-v1.toml + README (separate from the ratified file)
tests/support/  # stateful fake exchange v2, scripted-completion adapter, TEST_ONLY execution limits
```
Every new pure module must keep the manager's import discipline (stdlib + `src.domain` + `src.risk` + `src.execution`; no SDK, no SQLAlchemy, no clock) and must be added to `TARGET_RELPATHS` of `tests/test_execution_secret_posture.py` (a missing target fails; a new log site may carry only a literal event name and scalar fields, never `response`, `payload`, `data`, `body`, `token`).

### Pattern 1: Pure verdict functions with first-failure-wins reason codes
**What:** each pre-placement rule is a pure function returning `(ok, reason_code)`; the manager composes them in a fixed documented order. **When:** all D-01..D-09 checks. **Why:** testable by grids without fakes, same style as `decide_placement`.

### Pattern 2: Concurrent start, independent reconciliation (D-12)
**What:** on first positive fill the coordinator starts both coroutines with `asyncio.gather(..., return_exceptions=True)`; each coroutine is followed by an independent REST confirmation loop with an injected `sleep`. **Why:** the adapter cancel has an internal bounded retry of up to `_RECONCILER_CANCEL_MAX_DELAY_SECONDS: int = 30` [VERIFIED: binance_usdm.py:143] plus tenacity waits; serializing the cancel before the stop would put up to that time inside `max_unprotected_ms`.

### Pattern 3: Query-before-resend, reduce-only as the duplicate bound
**What:** a placement exception or `None` is ambiguous; query by the deterministic id; resend only after definitive absence. For the emergency close, the id is per attempt; because `reduceOnly` can never increase or reverse a position, a duplicate close on a flat position is rejected by the exchange (`-2022`/`-2024` in the taxonomy) instead of reversing [ASSUMED: exchange semantics of reduceOnly on a flat position; the repo taxonomy lists the codes as "documented" placement rejections]. Still never send a second close while the first is ambiguous and unqueried.

### Pattern 4: MARKET_LOT_SIZE part builder (pure, deterministic)
Given remaining quantity `R`, filters `(minQ, maxQ, step)` of MARKET_LOT_SIZE and of LOT_SIZE (the strict intersection), every part `p` must satisfy `minQ <= p <= maxQ` and `(p - minQ) % step == 0` in exact Decimal. Choose `p = min(maxQ_aligned, R_aligned)` but avoid leaving a remainder below `minQ`: when `R - maxQ_aligned < minQ`, take `p = R - minQ` aligned downward so the last part is still valid. If `R` itself is not representable (`(R - minQ) % step != 0`), no valid sequence exists for the full remainder: return a typed "cannot build" result, which D-16 turns into SAFE_MODE + critical alert + manual intervention (never round up). After each sent part the coordinator re-reads the position from REST and recomputes; it never trusts its own running total.

### Anti-Patterns to Avoid
- **Awaiting the entry cancel before the stop** (or the reverse): violates D-12 and inflates `max_unprotected_ms`.
- **Treating `NEW`/HTTP success/`FINISHED` as protection** (D-11); `is_protection_confirmed` ACTIVE only, confirmed by REST.
- **Extending `OrderRole`, `RejectionReason`, `ExecutionIntentStatus` or the ratified limits file** for convenience: each has parity/hash/count tests (F6, F9, F10).
- **Editing `placement.py` sizing functions** shared with the frozen backtest (F12).
- **Reading the clock, sleeping, or touching the SDK inside pure modules.** Inject `now_utc`, `sleep`, adapter.
- **Letting the replay path run any new gate before returning the stored outcome.**

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Tick snap, direction rounding | new rounding code | `quantize_price`, `entry_limit_rounding`, `sl_trigger_rounding`, `tp_trigger_rounding` (placement.py) | already exact-Decimal and tested; backtest parity |
| Fill folding/dedup | new fill accumulator | `fold_fills` with `expected_symbol/side/order_id`, `FillTotalsTracker` | idempotent by `(order_id, exchange_trade_id)`; raises on foreign fills |
| Protection evidence | string compare of statuses | `is_protection_confirmed`, `classify_algo_status` | owner-ratified classes |
| Error classification | message-text matching | `classify(error_facts_from_exception(exc), CallKind)`, `retry_eligible`, `safe_mode_eligible` | text is never read (threat T-18-13/14) |
| Deterministic ids | ad-hoc ids | `derive_client_order_id`/`derive_algo_client_id` (36 chars) and an extension of the same scheme for close attempts | probes by id depend on determinism |
| Plan hash | new hash | planner `_plan_hash` via a public wrapper, `canonical_decimal_text`, `sha256_hex` | frozen algorithm (D051 c) |
| Journal ids | random ids | `content_hash_event_id`, `correlated_event_id` | replay is a no-op |
| Transition checks | if/else on status | `assert_transition(TransitionKind.EXECUTION_INTENT, ...)` | DB triggers are the second line |
| Virtual time | `asyncio.sleep` in tests | `tests/support/virtual_time.VirtualTime` | deterministic races |
| Limits loading | `os.environ`/literals | the `binance_limits.py` loader pattern in a new module | refuse-by-default, names only in messages |

**Key insight:** almost every primitive exists; the risk is wiring them in the right order with the right durability, and not disturbing the frozen backtest, the ratified limits file and the parity tests.

## Common Pitfalls

### P1: Ratified limits file edited or extended
**What goes wrong:** the sha256 pin, the 27-key README test, the loader's unknown-key refusal and the record-equality tests all fail; worse, a "fix" re-pins the hash and changes a ratified file silently. **Avoid:** new file, new loader, new README (F9). **Warning sign:** any diff under `config/binance/binance-limits-v1.toml` or its README key bullets.

### P2: Alembic head hard-coded in three tests
`tests/test_pg_fixture_guard.py:184` asserts `version == "0004_persistence_integrity"`, `tests/test_execution_exactly_once_pg.py:205` repeats the string, and `tests/test_persistence_migration_pg.py` has a 0003 -> 0004 data-bearing upgrade test [VERIFIED: grep and reads this session]. A migration 0005 breaks the first two unless they derive the head from the script directory in the same change; the data-bearing test should gain a 0004 -> 0005 sibling. The compare-metadata test requires the ORM model, `ddl_if` objects and the migration to agree; enum CHECK literals in the migration are copied (immutable snapshot), not imported. Follow the 0004 header conventions (hand-written, no project imports, 0001-0004 byte-identical, TIMESTAMPTZ, NUMERIC(38,18), named constraints) [VERIFIED: src/db/alembic/versions/0004_persistence_integrity.py:1-33].

### P3: Rate-limit gate pause blocks the protection path (Phase 18 src/WR-12, not decided)
`_sdk_call` runs `gate.check()` first; during a 429 pause or 418 ban the stop placement, the entry cancel, the REST confirmations and the emergency MARKET close are all refused with nothing sent. A filled entry then has no stop until the pause ends. This is an owner decision (reduce-risk exemption vs a durable pending-cancel record). The plan must not claim "never naked" for this window; record it as an open owner question and make the coordinator treat `RestGateRefusal` as "not sent, retry after `retry_after_seconds`, deadline clock keeps running, CLOSE_REQUIRED escalation still attempted".

### P4: Pre-send refusals mistaken for ambiguous sends (D-21 / src/WR-02)
`_place_entry_no_blind_retry` catches every `Exception` as ambiguous and probes (manager.py:223-227). `EntriesBlocked` (drift guard), `SignedCallPolicyMissing` and `RestGateRefusal` mean "nothing was sent". The manager cannot import them (adapter/SDK). Options: define a pure marker base class in `src/domain/exchange_errors.py` that the three adapter exceptions inherit, or inject a `classify_exception` callable. Result mapping: pre-send refusal -> NO_TRADE, no SAFE_MODE, intent REJECTED (nothing sent) -> `INTENDED/SENT -> REJECTED` is legal [VERIFIED: transitions 205-224]; `STATUS_UNKNOWN` and `UNKNOWN_EXCHANGE_ERROR` -> probe; definitive rejection -> NO_TRADE. The retry count question stays with the owner (Q5).

### P5: Race semantics of "terminal"
`cancel_normal_order` treats ORDER_ABSENT (-2011) as success and returns `None`; for a **filled** entry the cancel also "succeeds". The coordinator must read the entry status by REST (`FILLED`, `CANCELED`, `EXPIRED`, `EXPIRED_IN_MATCH` are terminal per `TERMINAL_NOT_FILLED_STATUSES`/vocabulary) and the executed quantity before declaring the entry terminal, and fold fills until the executed quantity equals the folded sum. Late fills after a "terminal" cancel are impossible only if the status is truly terminal.

### P6: Stop triggered, then more fills
After the stop fires the position is flat; a late partial fill of the still-resting entry opens a new unprotected position. Branch B4 requires cancel of the remainder, a reduce-only close of the new exposure, and **no re-placement of the stop** (RISK-04: never add to a losing position). The stop's algo status will be TRIGGERING/TRIGGERED/FINISHED (all UNKNOWN class), so detect by position and executed quantity, not by class.

### P7: GTD vs the validity minimum
`goodTillDate` must exceed now + 600 s and keeps only second precision [CITED]. Compute it from `plan.expiry_utc` truncated to whole seconds; if `expiry_utc - now_utc` is not above 600 s plus the clock-drift limit, GTD cannot be sent: refuse (NO_TRADE) regardless of the owner's NOT_CONFIGURED minimum. The 600 s is a documented Binance structural floor (cite it as a named constant with the source), distinct from the owner's minimum. Which clock the page means is unstated (Assumption A1); use a margin tied to `ClockDriftGuard`.

### P8: Phase 20 coupling
Phase 20 criterion 2 presumes an entry-time SL on a resting entry and "never classifies it as an orphan" [VERIFIED: ROADMAP.md Phase 20 criterion 2 and inherited [D055]]. After D-10 there is none; an ENTRY ACKED with no STOP_LOSS row is the normal resting state, and a position without a STOP_LOSS ACKED/ACTIVE is the dangerous state. The reconciler also needs: the protection state names (stable), the SL intent's `intended_at_utc` as the unprotected-since time, the emergency-close attempt rows, and `StreamDivergenceKind.SINK_FAILURE`. Tell Phase 20 (via the phase summary) which rows/states exist; do not implement the reconciler loop here.

### P9: Backtest/live parity on TP1 (G4-007, O-03)
The backtest turns an un-sizeable TP1 into NO_TRADE (`protective_levels_for_fill` returns `ProtectiveReject`). Live criterion 4 says "fall back to a single TP". Per O-03 implement the NO_TRADE refusal at pre-placement using the **existing** `size_protectives_to_filled_qty(planned quantity)` as the check, and do not implement the fallback. A partial fill can still make TP1 un-sizeable after the entry: that is the existing CR-03 branch (keep the confirmed stop, SAFE_MODE, alert) per `19-NOTES.md`, not an automatic flatten.

### P10: Synchronous store on the critical path
The stores are synchronous and "called directly on the event loop" with engine bounds (connect, lock wait, statement timeouts) [VERIFIED: manager.py docstring lines 425-445]. The SL write-ahead (INTENDED then SENT) now sits inside the unprotected window. Keep the D034 rule (a store failure never stops the stop placement) and add the store latency to the budget that the owner will measure for `max_unprotected_ms`; Phase 24 may wrap in `asyncio.to_thread`.

### P11: Hedge refusal vs existing hedge tests
D-14 refuses hedge on the live path, but `test_hedge_mode_sends_explicit_position_side_on_entry_and_sl` (tests/test_execution_manager.py:1198) and the `placement.py` hedge matrix remain valid as **payload builder** tests. Move/rename them so they test the builders offline and add a manager test that a hedge detection returns NO_TRADE before any order.

### P12: Tests that assert the old rules must be rewritten
`test_unconfirmed_sl_leg_yields_entry_without_protective_with_zero_rescue` (tests/test_execution_attach.py:284), `test_entry_time_sl_is_adopted_not_duplicated` (:491), the golden placement fixture `tests/fixtures/phase9/placement_sequences/{input,expected}.json` (entry then SL; GTC), `test_rejected_sl_cancels_entry_and_forces_safe_mode`, the `test_cr01_*` store-down-after-ack tests in test_execution_manager.py, and `scripts/demo_rehearsal.py` (calls `execute_approved_plan` at ~2302 and `attach_protectives_to_fill` at ~2120) all encode the entry-time-stop flow. Inventory them in the plan (a "legacy-assertion rewrite" task) and regenerate the golden fixture deliberately with a written inventory (D048 style).

### P13: `RejectionReason`/`PlacementGateVerdict` coupling
`PlacementGateVerdict.__post_init__` validates `reason_code` against the enum plus `OK`. New pre-placement codes must NOT flow through that class; keep them in `ExecutionOutcome` (free string).

### P14: Secret posture and logging
New modules that touch exchange payloads must not log whole responses (`FORBIDDEN_LOG_FIELDS` includes `response`, `raw`, `payload`, `data`, `body`, `token`, `signature`). Journal payloads carry exception **type** names only (existing convention).

## Code Examples (value-free; names only, all literals live in the quoted sources above)

### Plan hash re-derivation (D-01) - behavior must equal `src/core/planner.py:59-88`
```python
# Source: src/core/planner.py _plan_hash (read this session). Expose a public wrapper; do not change the algorithm.
def recompute_plan_hash(plan: TradePlan) -> str:
    return plan_hash_from_fields(
        signal_id=plan.signal_id,
        entry_min_price=plan.entry_min_price,
        entry_max_price=plan.entry_max_price,
        stop_loss_price=plan.stop_loss_price,
        take_profit_json=plan.take_profit_json,
        invalidation_rule_json=plan.invalidation_rule_json,
        expiry_utc=plan.expiry_utc,
    )
# gate: recompute_plan_hash(plan) == plan.plan_hash == callback.plan_hash == approval.request_hash
```

### Pre-placement price verdict (pure; D-05/D-06)
```python
def check_mark_price(*, side, sl_trigger, entry_min, entry_max, mark, mark_age, max_age):
    if max_age is None or mark is None or mark_age is None or mark_age > max_age:
        return refuse("PRICE_UNAVAILABLE")          # fail closed; max_age comes from the limits object
    if crossed_stop(side, mark, sl_trigger):          # LONG: mark <= sl_trigger ; SHORT: mark >= sl_trigger
        return refuse("PRICE_CROSSED_STOP")
    if not (entry_min <= mark <= entry_max):          # inclusive zone, per D-05 "left the entry zone"
        return refuse("PRICE_LEFT_ZONE")
    return ok()
```
Reason strings here are placeholders for the planner to name (D-08); comparison direction follows `is_sl_touched` in `src/backtest/exits.py:349-365` (LONG low <= trigger, SHORT high >= trigger) [VERIFIED].

### GTD value for the entry backstop (B6)
```python
# goodTillDate must be > server_now + 600 s and keeps second precision (New Order page).
gtd_seconds = int(plan.expiry_utc.timestamp())            # whole seconds; adapter sends int milliseconds * 1000
if not (plan.expiry_utc - now_utc > STRUCTURAL_GTD_MIN_AHEAD + drift_margin):
    return refuse("VALIDITY_TOO_SHORT")
```
`STRUCTURAL_GTD_MIN_AHEAD` is a documented-constant (600 seconds, cited to the New Order page), not an owner limit; keep it out of the guarded names of the numeric-default scan or add an explicit allow-list entry with its reason.

## State of the Art

| Old approach | Current approach | Changed | Impact |
|--------------|------------------|---------|--------|
| closePosition stop right after the entry (Phase 9) | closePosition stop after first fill, fill-driven (D-10) | D055 direction, 2026-10-18 | every entry flow, golden fixture, rehearsal script |
| "no rescue placement ever" (Phase 8/9 D-02) | automatic reduce-only close and stop re-place allowed (D034, 2026-09-30) | D034 | `attach_protectives_to_fill` docstring and tests |
| Entry LIMIT GTC | LIMIT GTD with `goodTillDate` = plan expiry (backstop) | criterion 2 | adapter signature, fake binding, fixture |
| conditional orders via classic endpoints | Algo Service `POST /fapi/v1/algoOrder` (Dec 2025) | already adopted | `ALGO_UPDATE.o.rm` carries rejection text |

**Deprecated/outdated in the repo:** the manager docstring "no rescue placement is ever issued (D-02)"; `HEADROOM_LIMIT` comment saying 'per symbol' was already corrected; `LIVE_NET_PNL_SEMANTICS_VERIFIED` stays False.

## Runtime State Inventory

Not a rename/migration phase. One persistence change exists (migration 0005, `realized_risk`), covered above. Stored data: existing `execution_intents` rows in dev databases get NULL `sized_realized_risk` (nullable, no backfill). Live service config / OS-registered state / secrets / build artifacts: none touched (no new env var; credentials unchanged).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python / uv | all | yes | 3.13.15 | none needed |
| PostgreSQL 17 | PG tests, migration 0005 | yes, reachable via `TEST_DATABASE_URL` (database ending `_test`) | 17.11 [VERIFIED: connected this session] | tests skip without it; `TRADING_CI_STRICT=1` turns a missing URL into a failure |
| Docker | `docker`-marked tests only | yes | 29.5.3 | `pytest -m "not docker"` is the CI command |
| ruff / mypy | gates | yes | ruff 0.16.8 | none |
| Binance docs (REST pages) | fact checks | yes via WebFetch | read 2026-10-19 | repo docs |
| Binance docs (WS event pages) | B12 | no (landing page only) | - | repo parsers + Demo frames (see Network gaps) |
| Binance Demo / Telegram / EC2 | probes, alerts | not required for plan/build | - | O-05 probes are the owner's |

**Missing dependencies with no fallback:** none for planning/building.
**Missing with fallback:** the WS event schema fields `t` and `rm` (value lists are now [DOC], see "Gap pass results") -> use the Phase 18 parsers and recorded frames; label every dependent claim [UNVERIFIED] until the owner/probes confirm.

## Validation Architecture

> `workflow.nyquist_validation` is `true` in `.planning/config.json`.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`), tests in `tests/` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, marker `docker`) |
| Quick run command | `uv run pytest tests/test_execution_manager.py tests/test_execution_attach.py tests/test_execution_emergency.py tests/test_execution_partials.py -q` (about 174 tests with the limits tests, passes in seconds; measured this session) |
| Phase suite command | `uv run pytest tests/test_execution_*.py tests/test_binance_*.py tests/test_no_unratified_defaults.py tests/test_phase19_gate.py -q` |
| Full suite command | `uv run pytest -m "not docker"` then `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, `uv lock --check` (the commands CI runs, AGENTS.md); PG tests need `TEST_DATABASE_URL`, `TRADING_CI_STRICT=1` in CI |

### Phase Requirements -> Test Map (proposed new files; names are suggestions)
| Req ID | Behavior | Test type | Automated command | File exists? |
|--------|----------|-----------|-------------------|--------------|
| APRV-01 / D-01 | placed symbol and side equal the persisted Signal's; a caller symbol/side that disagrees is NO_TRADE, zero adapter calls; geometry side must equal Signal direction | unit grid | `uv run pytest tests/test_execution_binding.py -q` | Wave 0 |
| APRV-02 / D-01 | hash re-derivation equals `plan.plan_hash == callback.plan_hash == approval.request_hash`; a mutated TradePlan field is STALE_SETUP; golden hash unchanged (public wrapper == `_plan_hash`) | unit | `uv run pytest tests/test_execution_binding.py tests/test_core_planner.py tests/test_planner_geometry.py -q` | Wave 0 + existing |
| APRV-02 | replay returns stored outcome before every new gate | unit | `uv run pytest tests/test_execution_manager.py -k replay -q` | existing (extend) |
| EXEC-01 / D-02 | quantity above approved rejects (no clip); equal passes | unit | `uv run pytest tests/test_execution_binding.py -k quantity -q` | Wave 0 |
| EXEC-01 / D-03 | post-snap geometry grid: stop within one tick of zone edge, both sides | unit grid | `... -k snap -q` | Wave 0 |
| EXEC-01 / D-04 | `workingType` MARK_PRICE carried to SL/TP payloads and recorded | unit | `uv run pytest tests/test_execution_attach.py tests/test_execution_manager.py -k working_type -q` | extend |
| EXEC-01 / D-05, D-06 | price crossed SL, left zone, validity short (incl. 600 s floor), same-symbol (position and resting entry), status deny-list, invalidation, price read failure/stale -> each NO_TRADE with distinct code, approval not consumed | unit + manager | `uv run pytest tests/test_pre_placement.py -q` | Wave 0 |
| EXEC-01 / D-07, D-13 | limits NOT_CONFIGURED refuse live; TEST_ONLY values pass; no numeric default (scan extended) | unit | `uv run pytest tests/test_execution_limits.py tests/test_no_unratified_defaults.py -q` | Wave 0 + extend |
| EXEC-01 / D-08, D-09 | distinct reason code; INVALIDATED unchanged; executed plan stays APPROVED, no EXPIRED move | unit | `uv run pytest tests/test_pre_placement.py -k "invalidat or approved" -q` | Wave 0 |
| EXEC-01 / D-10, D-11 | entry flow places NO stop at entry time; stop placed after first fill (stream and REST sources); PARTIALLY_FILLED counts; protected only after REST ACTIVE | async manager/coordinator | `uv run pytest tests/test_protection_coordinator.py -q` | Wave 0 |
| EXEC-01 / D-12 | one race test per branch: B0 happy, B1 stop first/entry slow, B2 entry terminal first/stop unconfirmed, B3 both ambiguous, B4 new fill after stop triggered, B5 `-2021` after fill, plus -4509 (position gone) and REST-only fill | async with scripted fake + VirtualTime | `uv run pytest tests/test_protection_coordinator.py -k branch -q` | Wave 0 |
| EXEC-01 / D-14 | hedge detection -> NO_TRADE before any order; hedge payloads built correctly offline | unit | `uv run pytest tests/test_execution_manager.py tests/test_execution_modes.py -k hedge -q` | rewrite existing |
| EXEC-01 / D-15, D-16 | emergency close: reduceOnly MARKET, per-attempt deterministic id, ambiguous -> query before resend, no duplicate; split above MARKET_LOT_SIZE max with fake filters; remainder < min handled; unrepresentable remainder -> SAFE_MODE + alert; failure never declares safe | unit + async | `uv run pytest tests/test_emergency_market_close.py tests/test_market_lot_split.py -q` | Wave 0 |
| EXEC-01 / D-17 | auto close is a separate path; `emergency_manual_close` unchanged; old "zero rescue" tests rewritten | unit | `uv run pytest tests/test_execution_attach.py tests/test_execution_emergency.py -q` | rewrite |
| EXEC-01 / D-18..D-20 | TP legs only after entry terminal and reconciled; TP1 from real exposure floored, capped at closable position; TP2 closePosition; LOT_SIZE and MARKET_LOT_SIZE both honored; TP intents written ahead; stale snapshot refused/re-sized | unit + async | `uv run pytest tests/test_tp_sizing.py tests/test_protection_coordinator.py -k tp -q` | Wave 0 |
| EXEC-01 / D-21 | pre-send refusals (RestGateRefusal, EntriesBlocked, SignedCallPolicyMissing) -> NO_TRADE, no SAFE_MODE, no UNKNOWN intent; STATUS_UNKNOWN probes; definitive rejection no probe | unit + real-adapter binding | `uv run pytest tests/test_execution_manager.py tests/test_binance_usdm_error_routing.py -k refusal -q` | Wave 0 + extend |
| EXEC-02 | coordinator emits the states/rows Phase 20 reads; SL intent `intended_at_utc` is the unprotected-since time; restart rebuilds from REST | PG + unit | `uv run pytest tests/test_protection_persistence_pg.py -q` | Wave 0 |
| RISK-04 | no second entry on same symbol; qty never above approved; no stop re-place or carry-on after stop-triggered fill; sizing takes no prior-loss input | unit | `uv run pytest tests/test_pre_placement.py tests/test_protection_coordinator.py -k risk04 -q` | Wave 0 |
| EXEC-07 | guard: `TP1_QUANTITY_FRACTION` and `size_protectives_to_filled_qty` outputs byte-identical to before; requirement stays Pending | unit | `uv run pytest tests/test_execution_modes.py tests/test_backtest_exits.py -q` | extend |
| D-22 | `sized_realized_risk` persisted at consume; read back; NO_RISK_VALUE disappears when supplied; migration up/down/data-safe; ORM parity | PG | `uv run pytest tests/test_realized_risk_persistence_pg.py tests/test_persistence_migration_pg.py -q` | Wave 0 + extend |
| Adapter | `get_mark_price`, `place_market_close`, `good_till_date` bind to real signatures; oneOf unwrap; missing/other-symbol/None -> raise; single attempt; no entries gate on close | unit with fake SDK | `uv run pytest tests/test_live_mark_price_adapter.py tests/test_binance_usdm_signed_calls.py -q` | Wave 0 + extend |
| Gate | inventory + invariants of Phase 19 (artifacts exist, symbols importable, requirement tests resolvable, pure modules free of SDK/clock/float) | structural | `uv run pytest tests/test_phase19_gate.py -q` | Wave 0 (model on `tests/test_phase18_gate.py`) |

### Sampling Rate
- **Per task commit:** the quick command above plus the single new test file of the task.
- **Per wave merge:** phase suite command + `uv run ruff check` + `uv run mypy src`.
- **Phase gate:** full suite green (`pytest -m "not docker"` about 10,100 tests at the Phase 16 count; run with `TEST_DATABASE_URL`), `ruff format --check`, `uv lock --check`, before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/support/fake_binance_exchange.py` v2 (or a new `tests/support/fake_exchange_positions.py`): positions with signed amounts, partial fills (`fill(client_id, qty)`), MARKET reduce-only close (rejects on flat, `-2022`/`-2024` style), closePosition semantics incl. `-4509` while flat, algo trigger that consumes a position, mark price, scripted completion order (per-call `asyncio.Event` gates, injected failures/latency) so each D-12 branch is deterministic. Keep `_bind_real` binding to the real adapter signatures (adapter methods first).
- [ ] `tests/support/execution_limits.py` TEST_ONLY values (never imported by `src`/`scripts`; extend the import scan).
- [ ] Update the four store doubles in `tests/support/intent_store_fakes.py` for the new Protocol parameters (`sized_realized_risk`, TP `intended_quantity`).
- [ ] Head-agnostic migration tests (`tests/test_pg_fixture_guard.py:184`, `tests/test_execution_exactly_once_pg.py:205`) and a 0004 -> 0005 data-bearing upgrade test.
- [ ] Extend `GUARDED_NAMES`/README rules in `tests/test_no_unratified_defaults.py` for the new keys without touching the 27-key README test.
- [ ] Add every new `src/execution/*.py` to `TARGET_RELPATHS` in `tests/test_execution_secret_posture.py` and to the float/SDK/clock purity guards.
- [ ] Framework install: none.

## Security Domain

> `security_enforcement` is enabled (absent or true), ASVS level 1, block on high.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | no change (chat/token binding exists, Phase 8) | keep `check_binding_identity` before any lookup |
| V3 Session Management | no | - |
| V4 Access Control | yes: only the authorized chat's approved plan may place; caller cannot override symbol/side/quantity | binding gate, deny-by-default, no override path |
| V5 Input Validation | yes: exchange payloads (mark price, probes, fills) are validated at the adapter boundary | flag-never-fabricate: raise on missing/None/wrong-symbol; Decimal-only; reject non-finite |
| V6 Cryptography | yes (plan hash only) | existing SHA-256 canonical hash; never re-implement |
| V7 Error handling and logging | yes | journal exception **type** names only; no payload/response in logs; secret-posture test |
| V11 Business logic | yes: idempotency, race safety, fail-closed deadlines | write-ahead intents, deterministic ids, query-before-resend, reduce-only bound |
| V14 Configuration | yes | limits file with no defaults, refusal while unset, no secrets in repo |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Caller tampers symbol/side/quantity after approval | Tampering | bind_plan + hash re-derivation + qty <= approved |
| Replayed APPROVE places a second entry | Tampering/Repudiation | persisted ENTRY intent (existing), replay before new gates |
| Naked position after fill (stop lost, late, unconfirmed) | Denial of protection | fill-driven stop + REST confirmation + deadlines + automatic reduce-only close |
| Duplicate close order | Tampering | per-attempt deterministic id, query before resend, reduceOnly |
| Stale/forged price read decides placement | Spoofing | adapter validates symbol, `time`, staleness bound; failure is NO_TRADE |
| Secrets in logs/journal | Information disclosure | type-name-only errors; secret-posture and redaction tests |
| Rate-limit pause starves protection | DoS | open owner question P3; no silent claim |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The "current time" in the `goodTillDate > now + 600 s` rule is Binance server time | Findings B6, Pitfall P7 | GTD rejected near the boundary; mitigated by the drift margin |
| A2 | A GTD entry that expires is reported with status EXPIRED (and `er`/expire reason set) and counts as terminal | D-05, coordinator terminal rule | an expiring entry may look non-terminal; coordinator would wait to `entry_terminal_timeout` and escalate |
| A3 | `closePosition` algo orders are tied to an open position (TIF GTE) and are auto-cancelled by the exchange when the position closes | B13, Phase 20 coupling | orphan stops may remain after TP2/stop; affects sweeper, not Phase 19 correctness |
| A4 | A reduce-only MARKET order on a flat position is rejected (not executed); New Order page is silent (re-read 2026-10-19), Demo probe only | Pattern 3 | a duplicate close could open a position; mitigated by "never send a second close while the first is unqueried" |
| A5 | Demo can produce a partial fill at all | Test strategy, probe 3 | branch B1/B3 timing stays unproven on Demo (offline tests still prove logic) |
| A6 | Binance accepts a `closePosition` STOP_MARKET while a position is open (never probed) | D-10 | the whole model fails on first live fill; probe 1 gates D055 closure (O-01/O-05) |
| A7 | The `MARKET_LOT_SIZE` step is measured from its own `minQty` (same formula as LOT_SIZE) and a TAKE_PROFIT_MARKET algo leg is validated against MARKET_LOT_SIZE at trigger time (placement-time validation unknown) | D-19, Pattern 4 | a TP1 quantity valid for LOT_SIZE but not MARKET_LOT_SIZE is rejected at trigger; the quantizer uses the intersection |
| A8 | `-2022`/`-2024` are the exchange answers for a reduce-only MARKET with no/insufficient position (codes exist on the error page, but -2022 is documented as a conflict with existing open orders, not a flat position; which code a flat/oversized reduce-only MARKET returns is unproven, so treat both as "close rejected, requery the position") | Pattern 3 | classification of close failures |
| A9 | The Account Trade List `realizedPnl` semantics stay unverified, so live R stays INCOMPLETE after G4-008 | F13 | owner expectation of D-22 |
| A10 | Fetching fresh exchangeInfo during an emergency close is possible; a fallback to the plan-time snapshot is acceptable | Open Question Q3 | close blocked by a failed filter read |

## Open Questions

1. **Persistence of protection/close state (Q1)** - What we know: intent rows cannot hold multi-part closes; `OrderRole` extension is expensive. Unclear: whether the owner wants a new table in 0005. Recommendation: one hand-written migration 0005 with `sized_realized_risk` and a small `emergency_close_attempts` table; protection state itself stays derived (SL intent + REST) plus journaled transitions.
2. **Last price vs mark price (Q2)** - criterion 2 says "mark or last price"; D-06 specifies only a mark-price read. Recommendation: mark only (the stop triggers on MARK_PRICE, D037); record that a last-price read (`/fapi/v1/ticker/price`) is deliberately not added.
3. **Filters when exchangeInfo cannot be read during an emergency close (Q3)** - D-16 says every part within live filters. Recommendation: owner decides between refusing (SAFE_MODE) and using the plan-time `PlanConstraintSnapshot` (flagged stale). The splitter takes explicit filters so either policy is a caller choice.
4. **429/418 pause vs protection (Q4)** - Phase 18 src/WR-12, owner decision (reduce-risk exemption in `_sdk_call`, or a durable pending-cancel/stop record). Not decided here.
5. **Second `place_entry` attempt (Q5)** - `_ENTRY_MAX_ATTEMPTS: int = 2` is untouched by D-21; reviewer asked to remove it or decide explicitly. Keep as is, document, escalate.
6. **Invalidation input (Q6)** - the CANDLE_CLOSE rule needs the latest closed strategy-bar close; its producer is Phase 24 composition. Recommendation: required injected value; `None` is NO_TRADE (fail closed).
7. **Same-symbol "another plan" source (Q7)** - positions come from `open_positions`; a resting entry from another plan needs an exchange open-orders view (`snapshot_open_normal_orders`) or an intent query; intents alone cannot tell if an ACKED entry is still open. Recommendation: use the exchange snapshot as the authority and the intent store as a cross-check.
8. **Who runs the coordinator (Q8)** - the running process is Phase 24. Phase 19 delivers the coordinator, its sink adapters for the router, and tests; no running loop.

## Phase 18 review items that apply (focus item 5)

| Item | Applies to Phase 19? | Action |
|------|----------------------|--------|
| src/WR-02 (manager ignores taxonomy; refusals treated as ambiguous) | YES, = D-21 | Wire `classify`/pre-send marker (P4). Second-attempt removal stays an owner question (Q5). |
| src/WR-12 (429 pause blocks protection/cancel) | YES in effect (new D-10 path depends on protective calls) | Owner question Q4; do not claim solved. |
| src/WR-03 (event ordering, late event overwrites newer status) | Consumer side applies: the coordinator must not regress a terminal entry/stop status from an older event | Use REST as authority; compare `transaction_time_utc` if the router exposes it; schema/event-time column stays Phase 20. |
| src/WR-04 (SINK_FAILURE divergence) | The coordinator is a sink consumer | A raising enqueue must not lose a fill: make the enqueue infallible (unbounded or bounded with overflow = divergence) and journal. |
| src/WR-08, WR-01, WR-10, CR-02 liveness remainder | NO (owner decisions O-04, not implemented) | Record as blockers only. |
| src/WR-05 (supervisor TASK_DIED), WR-07, WR-09..11 | Phase 20/24 | Mention only. |

## Gap pass results (2026-10-19, WebFetch; see 19-GAP-RESEARCH-CHECKLIST.md)

**Correct current URLs** (the `docs/derivatives/usds-margined-futures/...` event paths return only the portal landing page; the old layout is under `legacy-docs/`): the site index is `https://developers.binance.com/en/docs/llms.txt`; the user-data page is `https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/user-data-streams.md` (raw markdown, all events on one page); errors are `.../derivatives-trading-usds-futures/error-code.md`. The `docs/derivatives/usds-margined-futures/trade/rest-api/{New-Order,New-Algo-Order,Account-Trade-List}` pages still resolve. **Field types confirmed 2026-10-19 from the installed SDK models** (generated from the same OpenAPI; `.venv/.../websocket_streams/models/order_trade_update_o.py`, `algo_update_o.py`, SDK 17.4.0, plus an independent check of the Rust SDK): `t` = int "Trade Id"; `gtd` = int "TIF GTD order auto cancel time"; `er` = string "Expiry Reason" (codes 0-9 on the page); ALGO_UPDATE `rm` = string "Algo order failed reason" (no enum anywhere, example "Reduce Only reject"), `gtd` = int, `ia` = bool. Every field is Optional in the generated models, which says nothing about presence, so `t` presence on non-TRADE or partial-fill events stays [UNVERIFIED] (probe 3). The repo parser types match (`_int_id_opt` for t/gtd, `_text_opt` for er/rm). Web-agent answers pasted by the owner were checked: one listed wrong ALGO_UPDATE statuses (PARTIALLY_FILLED/FILLED/CANCELLED instead of TRIGGERING/FINISHED/CANCELED); the page list above is authoritative. Field-level event schemas (`t`, `gtd`, `rm`) are embedded OpenAPI (`/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/~schemas#ordertradeupdate`, `#algoupdate`) and did not render, so field detail comes from the legacy example frames.

Read by WebFetch; the user-data and error-code pages were read as raw markdown (value lists verbatim); the REST pages are small-model extractions of quoted text. Label `[DOC]`.
- **Current page extras**: "Time in force" in the event page lists only GTC, IOC, FOK, GTX (no GTD, although `gtd` and the GTD New Order parameter exist). `er` codes 0-9 are defined, incl. 6 "expired as GTE condition unsatisfied" and 8 "initial order expired after the stop order is triggered". The same page still documents `CONDITIONAL_ORDER_TRIGGER_REJECT` ("update when a triggered TP/SL order got rejected"), which AGENTS.md calls gone after the Dec 2025 Algo migration: handle `ALGO_UPDATE.o.rm` as primary and treat that event as possibly still delivered (owner to confirm against the changelog).
- **ORDER_TRADE_UPDATE** (`legacy-docs/derivatives/usds-margined-futures/user-data-streams/Event-Order-Update`): `x` = NEW, CANCELED, CALCULATED (liquidation), EXPIRED, TRADE, AMENDMENT. `X` = NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, EXPIRED_IN_MATCH. `t` is only annotated "Trade Id" (example `0`); the page does not say it is present on every partial fill (A2 stays open, probe 3). `gtd` = "TIF GTD order auto cancel time"; `er` = expiry reason, 0 = none, codes 1-9 listed. B12 partly closed. A GTD expiry is expected as `x`/`X` = EXPIRED (A2 consistent, not stated explicitly).
- **ALGO_UPDATE** (`legacy-docs/derivatives/usds-margined-futures/user-data-streams/Event-Algo-Order-Update`): payload object is `o` with `caid, aid, at, o, s, S, ps, f, q, X, ai, ap, aq, act, tp, p, V, wt, pm, cp, pP, R, tt, gtd, rm, ia`; no `er`. `X`: NEW (in Algo Service, not triggered), CANCELED, TRIGGERING (forwarded to matching engine), TRIGGERED (in matching engine), FINISHED (filled or canceled there), REJECTED (matching engine denied, e.g. margin check), EXPIRED (canceled by the system, e.g. a GTE_GTC conditional order after all positions on the symbol are closed). `rm` = failure reason; only the example "Reduce Only reject" is given, no full value list. Supports A3 (system cancel maps to EXPIRED).
- **New Order**: `goodTillDate` "must be greater than the current time plus 600 seconds and smaller than 253402300799000" (A1: "current time" not specified; keep the drift margin). `timeInForce` enum = GTC, IOC, FOK, GTX, GTD, RPI; **`GTE_GTC` is not in it** (it appears only as a TIF in the ALGO_UPDATE docs). "In extreme market conditions, GTD auto-cancel time might be delayed compared to goodTillDate." `reduceOnly` "Cannot be sent in Hedge Mode". Re-read with an offset: the Notes end after the RESULT / selfTradePreventionMode / GTD-delay bullets and the mandatory-parameter table lists only LIMIT and MARKET, so the page is **silent** on reduce-only rejection with a flat or smaller position (not truncated). A4 stays unproven by docs, Demo probe only.
- **Error codes page** (raw markdown): -2022 REDUCE_ONLY_REJECT ("ReduceOnly Order is rejected. This indicates the new reduce-only order conflicts with existing open orders; cancel the existing order and resubmit"), so -2022 is documented for a conflict with open orders, NOT for a flat position (plan 19-10's "flat -> -2022" is unsupported); -2024 POSITION_NOT_SUFFICIENT ("Position is not sufficient"), -2026 reduceOnly not supported for the order type, -4118 REDUCE_ONLY_MARGIN_CHECK_FAILED, -4137/-4138 closePosition vs quantity/reduceOnly. -4509 is not listed. A8 confirms the codes exist but not which one a flat-position MARKET reduce-only returns; treat both -2022 and -2024 as "close rejected, position unknown", requery.
- **New Algo Order**: `closePosition` "Cannot be used with quantity" and "Cannot be used with reduceOnly"; error -4137/-4138 enforce this. The page is silent on needing an open position (C1 stays probe 1).
- **Account Trade List**: `realizedPnl` is described only as "Realized Pnl."; nothing on commission (D1 stays open, A9 unchanged).
- **Not read**: E1 (`MARKET_LOT_SIZE` step), E2.

## Network gaps (owner follow-up)

Superseded in part by "Gap pass results" above: item 1 is answered for value lists (old URLs were stale; current URL given there); item 2 is resolved as "the page is silent"; the GTE_GTC part of item 3 is answered (not in New Order / New Algo Order enums). The original text below is kept as the first-pass record.

No connection error occurred (each page answered), but two classes of content were not retrievable by the available tool. Per the orchestrator's rule, no retry loop was run and the affected facts are labelled UNVERIFIED.

1. **Event: Order Update (ORDER_TRADE_UPDATE) and Event: Algo Order Update (ALGO_UPDATE)** - URLs tried: `https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams/Event-Order-Update`, `.../Event-Algo-Order-Update`, then once the catalog path `https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/user-data-streams`; each returned only the portal landing page. UNVERIFIED: current execution-type and order-status value lists, whether `t` (trade id) is present on every partial fill, ALGO_UPDATE status definitions, whether `gtd`/expire reason appear for a GTD expiry. Working basis: repository parsers and Demo frames (Phase 18), plus archive text quoted in 09-EXCHANGE-FACTS.md Fact 2 and Fact 6.
2. **New Order page truncated** - the MARKET reduce-only section, the order-type rules table and any GTD status text were cut off in the WebFetch output. UNVERIFIED: exact MARKET reduceOnly rejection behavior on a flat or smaller position (A4, A8).
3. **Silent pages (not a network failure, a documentation gap)** - New Algo Order does not say whether `closePosition` needs an open position (Demo says yes); New Algo Order and New Order do not mention `GTE_GTC`; Account Trade List does not define whether `realizedPnl` includes commission. These stay owner/probe items (probes 1 and 6).
4. **Mark-price WebSocket stream** (`<symbol>@markPrice`) was not fetched; not needed because D-06 specifies a REST read.
5. **Telegram and Binance Demo were not contacted** (not needed to plan or build).

## Sources

### Primary (HIGH confidence): repository, read this session
- `src/execution/manager.py` (full), `placement.py`, `fill_monitor.py`, `intent_store.py`, `intent_recovery.py` (1-60, 110-262), `order_ids.py`, `gates.py` (1-248), `constraint_snapshot.py` (100-250, 385-444)
- `src/adapters/binance_usdm.py` (1-250, 305-432, 540-720, 815-880, 995-1291), `binance_limits.py`, `binance_errors.py`, `binance_userdata_events.py` (340-600, 1419-1433), `binance_userdata_router.py` (1-480), `binance_public.py` (140-345)
- `src/domain/{trade_plan,enums,transitions,exchange_errors,algo_status,ids,signal}.py`, `src/core/planner.py` (50-110, 640-738), `src/core/strategy.py` (255-300, 875-935), `src/risk/{gating,portfolio,types,realized_risk}.py`, `src/analytics/live_outcomes.py`, `src/backtest/{exits,entry,semantics}.py`
- `src/persistence/execution_state.py`, `src/db/models.py` (513-655), `src/db/alembic/versions/0004_persistence_integrity.py` (1-60, 682-690)
- Tests: `tests/test_execution_manager.py`, `test_execution_attach.py`, `test_execution_secret_posture.py`, `test_binance_limits_ratified_file.py`, `test_no_unratified_defaults.py`, `test_phase18_gate.py`, `test_persistence_migration_pg.py`, `test_pg_fixture_guard.py`, `test_execution_exactly_once_pg.py`, `tests/support/{fake_binance_exchange,intent_store_fakes,virtual_time,limits}.py`
- Planning: `19-CONTEXT.md`, `19-NOTES.md`, `19-DEC-D055-DRAFT.md`, ROADMAP Phase 19/20, `20-NOTES.md`, REQUIREMENTS.md, STATE.md, `18-DRAFT-D055-evidence-for-user.md`, `evidence/18-probe-check.txt`, `18-REVIEW.md` (WR-02, WR-03..06), `18-REVIEW-FIX.md`, `09-EXCHANGE-FACTS.md`, `docs/DECISIONS.md` rows D034, D037, D051, D052, D054, D055, D059, D072, `docs/GLOSSARY.md` section 9, `docs/trading/EXECUTION_SPEC.md` headings
- Installed SDK models and signatures (`.venv/.../binance_sdk_derivatives_trading_usds_futures/rest_api`)

### Secondary (MEDIUM confidence): official docs via WebFetch 2026-10-19 (small-model summaries)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order
- https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price
- https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Account-Trade-List

### Tertiary (LOW confidence): not usable as authority
- WS user-data event pages (not retrieved); archive-snapshot quotes inside 09-EXCHANGE-FACTS.md (dated up to 2026-06-17).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH, no new package; versions read from the venv.
- Architecture and code findings: HIGH, every file opened this session; design choices tagged [DESIGN].
- Binance facts: MEDIUM for REST (WebFetch summaries), [DOC] for WS event value lists (raw markdown), UNVERIFIED for `t`/`rm` field detail, flat-position reduce-only behavior and the closePosition-with-position case.
- Pitfalls: HIGH for the repo-pinned tests and coupling; MEDIUM for exchange race behavior (offline fakes only prove logic, Demo probes remain the owner's).

**Research date:** 2026-10-19
**Valid until:** 2026-10-26 for Binance facts (the change log moves; re-read before order paths), 30 days for the repository findings unless Phase 20 or 24 lands first.
