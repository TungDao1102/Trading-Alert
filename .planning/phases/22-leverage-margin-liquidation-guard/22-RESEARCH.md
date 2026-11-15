# Phase 22: Leverage, Margin + Liquidation Guard - Research

**Researched:** 2026-10-23
**Domain:** Binance USDⓈ-M symbol configuration (margin type, leverage), leverage brackets, isolated-margin liquidation price, available-margin check, fail-closed guard in front of the entry placement, margin column on the Phase 21 reservation table
**Confidence:** HIGH for the Binance endpoint contracts (official OpenAPI document of the docs site, read this session) and for the code seams; MEDIUM for the liquidation formula (the official page prints it as an image: it is reconstructed from the page's variable definitions and reproduces both of the page's worked examples to the cent); LOW for the items in the Assumptions Log (mainly: what `availableBalance` deducts, and what the exchange reports as `liquidationPrice` for an isolated position, neither of which any recorded payload shows)

## Evidence labels used in this file

| Label | Meaning |
|-------|---------|
| `[CITED: OpenAPI]` | The official OpenAPI 3.0.2 document of the Binance docs site, "Futures (USDⓈ-M) REST API 1.0.0": `https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/1.0.0/schema.yaml` (642.5 KB, fetched with WebFetch on 2026-10-23, read locally). It is the source the rendered endpoint pages are built from. The per-endpoint HTML pages themselves could NOT be read this session (curl answered HTTP 202 with an empty body; WebFetch returned the landing page or a bundle truncated before the margin endpoints). |
| `[CITED: llms-full]` | `https://developers.binance.com/en/docs/llms-full.txt` (curl HTTP 200, 8,291,297 bytes, 2026-10-23): the official error-code page, the change-log and the general-info page of the USDⓈ-M product. |
| `[CITED: FAQ-liq]` `[CITED: FAQ-protocols]` `[CITED: FAQ-margin]` `[CITED: FAQ-wallet]` | Binance support-center articles (URLs in Sources). Official Binance text, but it is the support center, not the API reference. |
| `[SDK: path]` | The installed `binance-sdk-derivatives-trading-usds-futures 17.4.0` read this session. |
| `[demo-observed, not mainnet]` | A recorded Demo payload in the repo (`.planning/phases/19-execution-plan-binding-price-check/evidence/fixtures/`). |
| `[VERIFIED: file:lines]` | An in-repo value whose source file was opened with Read this session; the value is quoted verbatim beside the claim. |
| `[VERIFIED: computed]` | A number computed by a script run this session (Python Decimal, scratchpad scripts `liq_check.py`, `liq_golden.py`). |
| `[ASSUMED]` | Not verified this session. Every such item is in the Assumptions Log. |

## Claim-source rules that bind this phase

- "Missing contract => TBD, never invent" (AGENTS.md). Where the API pages are silent (what `availableBalance` deducts, the error code of a leverage above the maximum, the isolated `liquidationPrice` value) this file says so and specifies the owner-run Demo case (D-18) that would settle it.
- Demo payloads are `demo-observed, not mainnet`. The Demo bracket table (first bracket 125x) differs from the mainnet figure the official change-log quotes for BTCUSDT (150x, see 2.2), so no bracket value may enter production code or a parameter.

<user_constraints>
## User Constraints (from CONTEXT.md)

Copied verbatim from `22-CONTEXT.md` (gathered 2026-10-23 with `--auto`, single pass; the owner has little domain knowledge and asked the assistant to choose; items marked OWNER-OPEN must not be implemented with a number until the owner decides).

### Locked Decisions

All decisions below are the recommended option, or a direction already recorded by the owner (D035, `22-NOTES.md`). They are defaults the owner may override. Every Binance fact (endpoints, field names, error codes, the liquidation formula) is read from the official documentation by the researcher, never taken from this file or from memory (AGENTS.md, Constraints: exchange authority).

#### Setting and verifying margin type and leverage (criterion 1, F-011, F-964)
- **D-01:** REST is the truth. Before an approved entry is sent, a guard reads `GET /fapi/v1/symbolConfig` for the symbol. If `marginType` is ISOLATED and `leverage` equals the target, nothing is changed. Otherwise the guard calls `change_margin_type` and then `change_initial_leverage`, and reads `symbolConfig` again; only a read that shows the target lets the plan continue. Any other result is NO_TRADE for that plan. The system never relies on the account default. — **Reversibility:** reversible — one guard and its tests.
- **D-02:** The target leverage is the D035 cap itself (5), held as one named constant of the guard module with the D035 reference. The plan is also refused when the leverage it would need exceeds the cap or the exchange maximum for its notional bracket (D-11). Whether the system may set a lower leverage is OWNER-OPEN O-1; the default is exactly the cap. — **Reversibility:** reversible — a constant and the guard's comparison.
- **D-03:** Both changes are mutating signed calls and follow the project's placement rule (Q5, D080): one call per guard run, never retried, never slept on. An ambiguous result (timeout, unknown error) is resolved with one `symbolConfig` read; if that read does not show the target, the symbol is NO_TRADE and an alert is raised. The adapter methods use the shared REST gate and the error taxonomy like every other signed method; the signed registry grows by the new methods (currently sixteen, `tests/test_binance_usdm_signed_calls.py`). — **Reversibility:** costly — new signed adapter surface and the registry that other tests pin.
- **D-04:** If the symbol has an open position, an open order or an open algo order and its configuration does not already match the target, the guard changes nothing and the plan is NO_TRADE (the exchange also refuses a margin-type change in that state; the researcher confirms the codes from the docs). The system never cancels or closes anything to make room for a configuration change. This also protects a position the owner opened by hand. — **Reversibility:** reversible — a precondition in the guard.
- **D-05:** The verified `marginType` and `leverage` are written to the plan constraint snapshot, so that `PlanConstraintSnapshot` can become COMPLETE together with the Phase 21 equity (G4-039, `22-NOTES.md`). A test builds a COMPLETE snapshot from the recorded Demo `symbolConfig` plus the Phase 21 equity and checks `snapshot_is_valid_for_live`. — **Reversibility:** reversible — fields that already exist and are `None` today.
- **D-06:** The configuration read also checks `isAutoAddMargin` is false; true is NO_TRADE (an automatic top-up would defeat the liquidation guard's input). — **Reversibility:** reversible.

#### Position mode and margin mode (criterion 4, F-965, F-020)
- **D-07:** The guard calls the existing position-mode read (`get_position_mode`) and the Phase 21 `accountConfig` read (`multiAssetsMargin`). Hedge Mode (`dualSidePosition` true) and multi-asset mode are NO_TRADE `UNCERTAIN_ACCOUNT_STATE` or a dedicated reason (D-16), never silently accepted. The Change-Position-Mode wording is re-confirmed on the official page before the one-way check relies on it (inherited item G3-001, DECISIONS D044). — **Reversibility:** reversible.

#### The liquidation guard (criterion 2, F-964)
- **D-08:** The liquidation price is computed locally before the entry, in a pure module (stdlib and `Decimal` only, no clock, no float), from the symbol's leverage bracket (`GET /fapi/v1/leverageBracket`: notional floor and cap, maintenance margin ratio, cumulative amount, initial leverage), the planned entry price, quantity, side and the verified leverage. The formula comes from the official documentation (isolated margin), is written into the module's docstring with its source, and is checked against a recorded Demo position's `liquidationPrice` where one exists (the position snapshot already carries `liquidation_price`). Hard-coded maintenance margin values or bracket tables never appear in code (criterion 2). — **Reversibility:** costly — a pure module that the guard, the plan check and the tests all call.
- **D-09:** The plan is accepted only if the liquidation price lies beyond the stop-loss by at least the buffer: for a long, `liquidation_price < stop_loss - buffer`; for a short, `liquidation_price > stop_loss + buffer`. At the entry price used (the limit price, the worst case for a resting entry that fills at that price or better). A missing, stale or unparsable bracket, a notional above the top bracket cap, or a leverage above the bracket's initial leverage is NO_TRADE (fail closed). — **Reversibility:** reversible — one predicate.
- **D-10:** The buffer is defined as a fraction of the entry price (a gap or slippage on the stop scales with price, not with the setup's own stop distance). The number is the owner's (O-2). Where it lives is also OWNER-OPEN: the default is a new required key in `config/execution/execution-limits-v1.toml` (`NOT_CONFIGURED`, provenance `DECISION` after the owner sets it), because a hash-locked registry parameter would force a new parameter set, a new `strategy_version` and regenerated research records (D075, D076) while the backtest has no liquidation model. `docs/trading/RISK_MANAGEMENT.md` section 9 says "registry parameter"; the planner records the deviation and the owner's DECISIONS row settles it. No number is chosen from backtest results (RESEARCH_PROTOCOL). — **Reversibility:** costly — moving the buffer into the registry later means a new parameter set and strategy version.
- **D-11:** The brackets are read with a signed GET through the shared gate and kept only for a bounded age (an execution-limits key, `NOT_CONFIGURED`, owner number O-3). Older than the bound, or never read, is NO_TRADE. — **Reversibility:** reversible — a gate predicate and one key.
- **D-12:** After the first fill, the guard compares the exchange `liquidationPrice` of the position with the local one. If the exchange value does not satisfy the D-09 predicate with the same buffer, the plan goes to the existing protection path as an unprotected-exposure case (CLOSE_REQUIRED, reduce-only MARKET close, alert). A difference between the two numbers that still satisfies the predicate is journalled and alerted for calibration only. Whether a failed post-fill check closes the position (default) or only alerts is OWNER-OPEN O-4. — **Reversibility:** reversible — a branch in the coordinator step.

#### The available-margin check (criterion 3, F-966)
- **D-13:** The check passes only if the fresh `availableBalance` (same freshness rule as the Phase 21 equity, `account.max_equity_age_ms`) covers: the new order's initial margin (notional divided by the verified leverage), the entry and stop commissions (taker rate on both, D036), the initial margin of approved-but-unplaced plans, and a headroom (a fraction of the margin needed; the number is the owner's, O-3, `NOT_CONFIGURED`). The Binance `availableBalance` already deducts the initial margin of orders resting on the exchange (the researcher confirms this from the docs and the recorded `totalOpenOrderInitialMargin` field), so resting entries are not subtracted a second time; an owner-run Demo case reads `availableBalance` before and after one far resting limit order to prove it (D-18). A source that cannot be read or is stale is NO_TRADE. — **Reversibility:** reversible — a pure predicate and a limit key.
- **D-14:** Approved-but-unplaced plans are counted from the Phase 21 `risk_reservations` rows. The margin each plan will need is stored with the reservation so that the sum is read inside the same approval transaction that takes the day-row lock (`reserve_in`, F-407): two approvals cannot both pass on the same free margin. This needs a new Alembic migration (0012) on the reservation table; the planner chooses the column design. — **Reversibility:** costly — a migration and a persisted schema that Phase 21 code reads.
- **D-15:** The margin check, the liquidation check and the configuration guard run in one fixed order and the first refusal wins, each with its own plain reason code (D-16). Backtest parity: the backtest has no margin or liquidation model, so these checks are live-only gates like the Phase 21 equity age and reservation gate; sizing and quantization are unchanged (AGENTS.md: quantization floors, never rounds up). — **Reversibility:** reversible.

#### Vocabulary and evidence
- **D-16:** New plain reason codes (for example for a configuration mismatch, a liquidation too close, insufficient margin, unsupported position or margin mode) are added deliberately: `RejectionReason` is pinned at 21 members by `tests/test_phase21_gate.py` invariant 3, and the GLOSSARY lists the codes, so the plan updates both in the same change. No existing code is reused with a changed meaning. — **Reversibility:** costly — an enum other modules, the gate tests and the glossary pin.
- **D-17:** Nothing here is composed into a running process (Phase 24). The adapter methods, the pure modules and the guard are libraries proven with fakes, local PostgreSQL where the reservation changes, and recorded Demo payloads labelled "demo-observed, not mainnet". Live placement stays disabled (`LIVE_ORDERS_DISABLED`).
- **D-18:** Demo evidence that only the owner can produce is registered as owner-run probe cases (the owner runs every `--execute`): changing the BTCUSDT configuration from x20 CROSSED to ISOLATED x5 and reading it back, the exchange's answer to a margin-type change while an order rests, the answer to a leverage above the bracket maximum, a margin-insufficient entry at the new leverage, and `availableBalance` with and without a resting order. The planner adds the cases to `scripts/demo_probe.py` as opt-in cases in the sj1/sj2 style, with a limits-file key per case; no agent runs one. — **Reversibility:** reversible.
- **D-19:** Everything Demo-observed is labelled "demo-observed, not mainnet" in code comments, docs and tests. No trading parameter is chosen from Demo.

#### OWNER-OPEN (record, do not implement with a number)
- **O-1:** Whether the target leverage is exactly the 5x cap (default) or lower, and whether the system may change the leverage and margin type of a symbol on the account the owner also uses by hand (the guard only changes a flat symbol with no orders, D-04).
- **O-2:** The liquidation buffer: its number, its definition (default: fraction of the entry price) and its home (default: an execution-limits key; the alternative is a registry parameter with a new parameter set and strategy version). A DECISIONS row is needed before any number is set, as for D084.
- **O-3:** The numbers of the bracket maximum age (D-11) and of the margin headroom (D-13). Both `NOT_CONFIGURED` until the owner sets them.
- **O-4:** Whether a failed post-fill liquidation check closes the position (default, D-12) or only alerts.

### Claude's Discretion
- Module placement (`src/risk/` for the pure liquidation and margin predicates, `src/execution/` for the guard), the exact names of the new adapter methods and reason codes, the column design and table split of migration 0012, the order of the checks inside the plan check, the fixtures and fakes (reuse `tests/support/`), and the plan and wave split.

### Deferred Ideas (OUT OF SCOPE)
- Monitoring the liquidation distance of an open position over time (mark price versus `liquidationPrice`) and any automatic reduction when it narrows — belongs with the reconcile loop and Phase 24/25; not in the four criteria.
- Dynamic or volatility-scaled leverage — a trading-rule change that needs the research protocol.
- Automatic margin top-up (`isAutoAddMargin`) — contradicts the fixed-risk model.
- Registering the liquidation buffer as a hash-locked registry parameter with a backtest liquidation model — only if the owner chooses it under O-2; it needs a new strategy version and regenerated research records.
- Mainnet attestation of brackets, formulas and the configuration calls — Phases 25 and 26.

Reviewed todos (not folded): none.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description (REQUIREMENTS.md) | Research Support |
|----|-------------------------------|------------------|
| RISK-01 | Sizes positions from equity x risk-rate / SL-distance incl. modeled costs, floors to stepSize, identical logic in backtest/paper/live | Sizing and quantization are NOT touched. Phase 22 adds live-only gates after the unchanged `evaluate_risk` (section 1, P1-P3); the notional the guard judges is the sized quantity times the snapped limit price. REQUIREMENTS.md marks RISK-01 Complete (Phase 5): Phase 22 does not reopen it, it adds the margin/liquidation consequences of the sized order |
| RISK-02 | Portfolio limits and fail closed on uncertain account/risk state | Unknown/stale `availableBalance`, unreadable `symbolConfig`/brackets, hedge or multi-asset mode, `isAutoAddMargin` true, a margin type or leverage that cannot be verified: all NO_TRADE (sections 1 and 2.3 to 2.7). Reservation rows carry the margin each approved-but-unplaced plan needs (P4). REQUIREMENTS.md marks RISK-02 Complete (Phase 5) |
| EXEC-01 | Execution manager places LIMIT-zone entries and Algo-Order protective exits | The guard sits in `execute_approved_plan` after gate 5f and before the approval is consumed (section 3.2); the verified margin type and leverage unblock TP placement through `snapshot_is_valid_for_live` (P5). Stays **Pending** (Demo/mainnet proof is Phases 24-26); this phase must not flip it |
| EXEC-02 | Reconciliation compares local state against open orders, algo orders, positions; forces SAFE_MODE on divergence | The guard's "flat symbol, no orders" precondition reads the exchange truth (open normal orders, open algo orders, positions) the reconciler already reads; a configuration that cannot be verified raises a DIVERGENCE-class alert (P7); the post-fill liquidation comparison feeds the existing protection path (P6). Stays **Pending**; no reconcile loop changes |
</phase_requirements>

## Summary

Phase 22 is a thin, fail-closed layer in front of the entry: one new pair of signed READ methods (symbol configuration, leverage brackets), one new pair of signed MUTATING methods (change margin type, change initial leverage), a pure liquidation-price module, a pure margin predicate, a guard that composes them, a margin column on the Phase 21 reservation row (migration 0012), a post-fill comparison hook, and the owner-run Demo cases. No new package is needed. Everything pure goes in `src/risk/`, the guard goes in `src/execution/`, and the guard is invoked from `execute_approved_plan` between gate 5f (position mode) and gate 5g (hand-off record), i.e. before anything is consumed, so a refusal leaves no intent row and the plan can be retried.

The Binance contract is now settled from the official OpenAPI document (section 2): `POST /fapi/v1/marginType` and `POST /fapi/v1/leverage` weigh 1; `GET /fapi/v1/symbolConfig` weighs 5 and is the only v1 read that returns `marginType`, `leverage`, `isAutoAddMargin` and `maxNotionalValue`; `GET /fapi/v3/positionRisk` indeed has no leverage or margin-type field (its v2 predecessor has them and is announced for deprecation); `GET /fapi/v1/leverageBracket` weighs 1. Requesting the margin type the symbol already has is an ERROR (-4046), not a no-op, and a margin-type change with open orders or a position is -4047 / -4048, none of which is in the project's error table today, so each would classify as UNKNOWN_EXCHANGE_ERROR (SAFE_MODE-eligible) unless the table is extended. The official documentation does NOT define what `availableBalance` deducts; the support-center article does (cross wallet + cross unrealized PnL - cross initial margin - isolated open-order initial margin), and no recorded Demo payload contains a resting order, so CONTEXT D-13's "confirmed from the recorded `totalOpenOrderInitialMargin`" cannot be supported; D-18 must settle it and the code must hold the choice in one function.

The liquidation formula is printed as an image on the official page; its variables, the isolated-margin rule (`TMM = 0`, `UPNL = 0`, `WB` = the isolated position's wallet balance) and two numeric examples are text. The reconstruction implemented in section 2.5 reproduces both examples (1153.26 and 26316.89) [VERIFIED: computed] and follows algebraically from the stated liquidation condition. It excludes fees and funding. The maintenance tier must be the one that contains the notional AT the liquidation price (the page's tier-change rule); using the entry tier is non-conservative for a long (section 2.5, golden G3). No recorded Demo position has an isolated `liquidationPrice` (all 15 recorded rows are cross margin and read `"0"`), so the local figure can only be cross-checked on the exchange by an owner-run case.

**Primary recommendation:** Build `src/risk/liquidation.py` (pure, tier-consistent, fail-closed) and `src/risk/margin_check.py` (pure, one `free_margin_basis` function), `src/execution/margin_guard.py` (ports, order: configuration -> liquidation -> margin), four adapter methods, migration 0012 (`required_margin` on `risk_reservations`), limits keys expressed as positive integers (basis points and milliseconds), plain-string reason codes plus the already-reserved `INSUFFICIENT_MARGIN`, and the D-18 probe cases; keep the authoritative margin check at placement time, not inside the approval transaction.

## CONTEXT decisions this research recommends changing

The owner delegated these choices, so the facts below override the defaults. Each is argued in the section named.

| # | CONTEXT item | Problem found | Corrected default | Section |
|---|--------------|---------------|-------------------|---------|
| C1 | D-13 premise | "`availableBalance` already deducts resting-order margin, confirmed from the docs and the recorded `totalOpenOrderInitialMargin`": the API docs say only "Available balance."; the support-center article says it, but no recorded payload has a resting order (every recorded `totalOpenOrderInitialMargin` is `0.00000000`) | Treat as `[CITED: FAQ-wallet]` + `[ASSUMED]` mapping; implement the basis in ONE function (`free_margin_basis`, like Phase 21's `equity_basis`); count "other" claims conservatively; D-18 case settles it | 2.6, P3 |
| C2 | D-14 (sum read inside the approval transaction) | The exchange reading cannot be taken inside the synchronous DB transaction (`make_reserving_save_atomic` takes only synchronous callables); a cached reading would conflict with the 15 s freshness rule | Migration 0012 still adds the stored margin; the AUTHORITATIVE sum check runs at placement (async, fresh reading), counting other RESERVED rows. An approval-time pre-check with a cached reading is optional and weaker | 3.2, P4 |
| C3 | D-16 (new reason codes: touch the enum) | Enum size 21 is pinned in at least eight tests plus GLOSSARY 9.1 and gate GL-03; `INSUFFICIENT_MARGIN` already exists and is documented as "first emitted by the Phase 22 margin guard"; the Phase 19 pre-placement codes (`SYMBOL_HAS_POSITION`, `HEDGE_MODE_UNSUPPORTED`, ...) set the precedent of plain strings listed in GLOSSARY 9.3 | Emit `INSUFFICIENT_MARGIN` from the enum; add the other codes as plain strings in GLOSSARY 9.3 (module constants), no enum change. If the owner prefers enum promotion, section 3.5 lists every pin | 3.5 |
| C4 | D-10/D-11/D-13 (limits keys) | The limits loader accepts only a positive integer or `NOT_CONFIGURED`; a "fraction" cannot be stored, and `0` cannot be stored | Keys in basis points (`..._bps`) and milliseconds (`..._ms`) | 3.2, 5.4 |
| C5 | D-07 (call `get_position_mode`) | `GET /fapi/v1/positionSide/dual` weighs 30; `GET /fapi/v1/accountConfig` weighs 5 and returns BOTH `dualSidePosition` and `multiAssetsMargin`; the manager already calls `get_position_mode` at gate 5f and refuses hedge with `HEDGE_MODE_UNSUPPORTED` | Reuse gate 5f for the one-way check; add `dual_side_position`/`multi_assets_margin` from the single `accountConfig` read that `LiveEquitySource.refresh` already makes | 2.8, 2.9 |
| C6 | D-08 ("checked against a recorded Demo position's `liquidationPrice` where one exists") | None exists: all 15 recorded position rows have `"row_0_liquidation_price": "0"` (cross margin) | Golden tests = the official page's two examples + the Demo bracket numbers in 5.1; exchange cross-check = owner-run isolated case (D-18) | 2.5, 5.1 |
| C7 | D-15 (order) | The list names margin, liquidation, configuration; but the initial margin (`notional / verified leverage`) and the bracket test both need the VERIFIED leverage | Fixed order: (1) configuration guard (read, maybe change, verify), (2) liquidation, (3) margin | P1-P3 |
| C8 | D-05 (snapshot) | The persisted `plan_constraint_snapshots` row is write-once (append-only trigger; a different snapshot for the same plan is `RowConflict`); production code never calls the store's `is_valid_for_live`; only the in-memory snapshot in `RestingEntry` gates TP placement | Fill margin type and leverage by `dataclasses.replace` on the in-memory snapshot handed to `RestingEntry` after the guard; the persisted evidence row stays INCOMPLETE unless Phase 24 builds it later | 3.3, P5 |
| C9 | D-03 (alert) | `ALERT_EVENTS` is a closed set pinned by `tests/test_alerts.py:235` and the OPS-05 matrix tests | Reuse `DIVERGENCE` (HIGH) with a reason code, or add one event and update the pins deliberately (listed in 4.7) | 3.5 |
| C10 | D-12 (cost) | The coordinator is 2,905 lines with a pinned state machine; a post-fill branch needs a new branch code, journal event and tests; the exchange value `"0"` is a cross-margin sentinel | Keep O-4's default, but plan it as its own isolated plan with a port; treat `"0"` as unknown (fail closed) | P6 |

Not wrong, but clarified: D-02's "the leverage it would need" is not a quantity the system computes (the target is fixed at 5); the real refusals are `notional > maxNotionalValue`, `bracket.initialLeverage < target`, and `INSUFFICIENT_MARGIN`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Read symbol config / brackets (signed GET) | Adapter (`src/adapters/binance_usdm.py`) | — | SDK types never leave the adapter; same pattern as `account_config_snapshot` |
| Change margin type / leverage (signed POST) | Adapter | Guard decides when | Mutating, one call, never retried; classified as an order-surface method for the shadow isolation control |
| Liquidation price, tier selection, buffer predicate | Pure risk (`src/risk/liquidation.py`) | — | Stdlib + Decimal only; same code for guard and tests |
| Initial margin, fees, free-margin predicate | Pure risk (`src/risk/margin_check.py`) | — | One function holds the `availableBalance` basis |
| Order of checks, ports, no-consume-on-refusal | Execution (`src/execution/margin_guard.py`, call site in `manager.py`) | — | Imports no adapter/store/SDK; talks through ports (Phase 21 pattern) |
| Margin needed by approved-but-unplaced plans | Database (`risk_reservations.required_margin`, migration 0012) | Pure sum in `src/risk` | Durable, rebuilt on restart; sum read at placement |
| Plan constraint snapshot fields | Execution (`constraint_snapshot.py`, in-memory copy) | Persistence (write-once row) | See C8 |
| Post-fill liquidation comparison | Execution (protection coordinator step via a port) | Pure predicate | Reuses CLOSE_REQUIRED path |
| Owner-run Demo evidence | Scripts (`scripts/demo_probe.py`, `.planning/DEMO-EVIDENCE-PLAN.md`) | Probe adapter | The owner runs every `--execute` |

## Standard Stack

### Core (all installed; nothing to add)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `binance-sdk-derivatives-trading-usds-futures` | 17.4.0 [VERIFIED: `uv pip list` this session] | `symbol_configuration`, `notional_and_leverage_brackets`, `change_margin_type`, `change_initial_leverage` | Only Binance client in the project. Signatures: `TradeApi.change_initial_leverage(symbol, leverage: int, recv_window=None)` (`trade_api.py:589-642`), `TradeApi.change_margin_type(symbol, margin_type: ChangeMarginTypeMarginTypeEnum, recv_window=None)` (`trade_api.py:644-702`), `AccountApi.symbol_configuration(symbol=None, recv_window=None)` (`account_api.py:942`), `AccountApi.notional_and_leverage_brackets(symbol=None, recv_window=None)` (`account_api.py:856`) [SDK] |
| `decimal.Decimal` | stdlib | All money/price math | `tests/test_domain_no_float.py` |
| SQLAlchemy 2.0.54 / psycopg 3.3.6 / Alembic 1.20.0 | installed [VERIFIED: `uv pip list`] | Migration 0012 | Phase 21 stores use exactly these |
| pytest 9.1.1 / pytest-asyncio 1.4.0 / pytest-xdist 3.8.0 | dev extra | Tests | AGENTS.md |

SDK enum, verbatim [SDK: `rest_api/models/enums.py:215-217`]:
```
class ChangeMarginTypeMarginTypeEnum(Enum):
    ISOLATED = "ISOLATED"
    CROSSED = "CROSSED"
```
exported from `binance_sdk_derivatives_trading_usds_futures.rest_api.models` (`models/__init__.py:536`). The adapter imports the SDK lazily inside methods (existing pattern, `binance_usdm.py:1291-1295`).

**Installation:** none. `uv.lock` does not change.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| New `CallKind.CONFIG` | Reuse `CallKind.PLACEMENT` for the two changes | `CallKind` is a 5-member enum `PLACEMENT, CANCEL, QUERY, LISTEN_KEY, TIME` (`src/domain/exchange_errors.py:59-66`); `_every(...)` entries and the retry set depend on it. PLACEMENT already means "mutating, never retried" (`retry_eligible` is False for it). Recommended: reuse PLACEMENT, note it in the code comment |
| Separate `account_margin_snapshot()` read | Extend `AccountInformationSnapshot` with `available_balance` | A second REST read costs weight 5 and gives equity and margin different stamps. Recommended: extend the existing snapshot (one read, one stamp); update the fakes listed in 3.6 |
| Registry parameter for the buffer | Limits key in bps | See C4 and D-10; the registry route changes the strategy version |

## Package Legitimacy Audit

No external package is added or changed. `gsd_run query package-legitimacy check` was not run because there is nothing to check.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## 1. Architecture Patterns

### System Architecture Diagram

```
 approved plan --> execute_approved_plan (src/execution/manager.py)
   gates 0..4  (identity, binding, enablement, LIMITS, SAFE_MODE, cost rates)         [unchanged]
   gate 4b evaluate_risk -> sized {quantity, realized_risk}                            [unchanged]
   gate 5/5b/5c/5d  (placement gates, quantity bound, snapped geometry, TP1 sizing)   [unchanged]
   gate 5e  live reads: mark, last, open normal orders, open algo orders, positions   [unchanged]
            evaluate_pre_placement  (SYMBOL_HAS_POSITION / SYMBOL_HAS_OPEN_ORDER ...)  [unchanged]
   gate 5f  get_position_mode -> HEDGE_MODE_UNSUPPORTED                                [unchanged]
 ================================ NEW: gate 5f2 margin_guard =============================================
   (1) CONFIG GUARD
        accountConfig (w5, from the equity refresh)  --> hedge / multi-asset  => NO_TRADE
        GET symbolConfig (w5) --+-- ISOLATED && leverage==5 && !autoAdd  -----------------+
                                +-- else: flat + no orders? (from 5e reads)                 |
                                      no  => NO_TRADE (nothing changed, D-04)               |
                                      yes => POST marginType ISOLATED (w1, once)            |
                                             POST leverage 5          (w1, once)            |
                                             GET symbolConfig (w5) -> must show target -----+--> verified {marginType, leverage, maxNotionalValue}
   (2) LIQUIDATION  GET leverageBracket (w1, bounded age) --> pure liquidation_price(side, limit_price, qty, 5x, bracket)
                    long: LP < SL - buffer ; short: LP > SL + buffer ; bracket.initialLeverage >= 5 ; notional <= maxNotionalValue
   (3) MARGIN       fresh availableBalance >= IM_new + fees + open_loss + sum(other RESERVED margin, stored in 0012) + headroom
                    -> INSUFFICIENT_MARGIN
 ==========================================================================================================
   -> in-memory snapshot replace(margin_type, leverage, equity_used) -> RestingEntry
   gate 5g resting entry, consume approval (ENTRY intent), place GTD LIMIT   [unchanged; one POST, never re-sent]
   fill -> protection coordinator -> stop; NEW: post-fill step compares positionRisk.liquidationPrice with the same predicate
```

### Recommended Project Structure (names are proposals, [ASSUMED: names])
```
src/
├── risk/
│   ├── liquidation.py        # pure: Bracket, LiquidationInputs, liquidation_price(), buffer predicate, tier fixed point
│   └── margin_check.py       # pure: initial_margin(), free_margin_basis(), margin_verdict(); no clock, no float
├── adapters/
│   └── binance_usdm.py       # + symbol_config_snapshot(), leverage_brackets_snapshot(), change_margin_type(), change_initial_leverage()
├── execution/
│   ├── margin_guard.py       # ports + ordered checks; imports no adapter/store/SDK
│   └── liquidation_watch.py  # post-fill comparison (port used by the protection coordinator)
├── persistence/risk_reservations.py   # + required_margin on request/row; sum of other RESERVED rows
└── db/alembic/versions/0012_reservation_margin.py
scripts/gen_phase22_fixtures.py        # generates tests/fixtures/phase22/recorded_demo/ from the Phase 19 capture
config/execution/execution-limits-v1.toml  # + keys (5.4)
```

### Pattern P1: Configuration guard (criterion 1, D-01..D-06)
One run = at most two mutating POSTs, each sent once. The run ends with the verification read; ONLY that read decides. Therefore the outcome of each POST (success, -4046, -4047, a timeout) never decides the plan: after the POSTs (or after any exception) the guard reads `symbolConfig` once and compares. Exact comparison: `marginType == "ISOLATED"` (upper-case; the request enum and the recorded Demo answer both use upper-case, `"0.marginType": "CROSSED"`), `leverage == TARGET_LEVERAGE` (int), `isAutoAddMargin is False`. Any other value, a missing field, a symbol mismatch or an empty array is NO_TRADE. There is no setter for `isAutoAddMargin` in the USDⓈ-M OpenAPI (only `POST /fapi/v1/positionMargin`, add/reduce isolated margin) [CITED: OpenAPI, grep this session], so `true` can only be refused.

### Pattern P2: Pure liquidation module (criterion 2, D-08/D-09)
Inputs: side, limit price, quantity, verified leverage, the symbol's bracket list (Decimal fields), stop trigger price, buffer. Steps: (1) validate the bracket list (contiguous, ascending, floors/caps non-negative, ratios in [0,1), `cum >= 0`); (2) compute the candidate liquidation price for every bracket with the isolated closed forms of 2.5 and keep the bracket whose range contains `quantity * LP` (maintenance margin `n*rate - cum` is continuous at every bracket edge on the recorded table [VERIFIED: computed], so exactly one candidate is self-consistent; at an edge both give the same value); (3) none self-consistent, a notional above the top cap, `initialLeverage < target`, or any non-finite/non-positive result => unknown => NO_TRADE; (4) compare with the stop and the buffer. No bracket constant, no rate and no leverage default appears in the module.

### Pattern P3: Pure margin predicate (criterion 3, D-13)
`required = IM_new + fees + open_loss + sum(other_unplaced_margin)`; pass iff `available >= required + required_headroom` where `IM_new = notional / verified_leverage` with `notional = quantity * limit_price` [CITED: FAQ-margin: one-way flat symbol, a single buy order: `Max(Abs(0 + Bid Order Value), Abs(0 - 0)) / Leverage`], `fees = notional * (fee_rate_entry + fee_rate_exit)` from the already-verified `risk_kwargs["cost_rates"]` (`CostRates.fee_rate_entry`, `fee_rate_exit`, `src/risk/cost_rates.py:72-75`), `open_loss = max(0, (limit_price - mark) * quantity)` for a BUY and `max(0, (mark - limit_price) * quantity)` for a SELL [ASSUMED formula: the FAQ says cost = "initial margin and open loss (if any)" and defers the definition to another article], and `headroom = required * headroom_bps / 10000`. The basis of `available` lives in the single function `free_margin_basis(reading)` (default: the top-level `availableBalance`, which is `[CITED: FAQ-wallet]` to be net of cross initial margin and isolated open-order initial margin) so that if D-18 shows otherwise the change is one line. "Other unplaced" = rows of `risk_reservations` with status RESERVED (excluding this plan) plus PLACED rows whose `placed_at_utc` is later than the reading's `observed_at_utc` (the exchange has not yet shown them in `availableBalance`). A row with a NULL `required_margin` makes the sum unknown => NO_TRADE.

### Pattern P4: Reservation margin and migration 0012 (D-14)
Table `risk_reservations` today (migration 0011) has no margin column [VERIFIED: `src/db/alembic/versions/0011_risk_reservations.py`, columns listed in its docstring: `trade_plan_id, approval_id, plan_hash, symbol, position_side, quantity, realized_risk, status, release_reason, requested_at_utc, reserved_at_utc, placed_at_utc, opened_at_utc, released_at_utc, updated_at_utc`]. Add, nullable so every Phase 21 row and constructor keeps working: `required_margin NUMERIC(38,18) NULL` with `CHECK (required_margin IS NULL OR required_margin > 0)`; recommended auditable companions `margin_entry_price NUMERIC(38,18) NULL` and `margin_leverage INTEGER NULL` (same CHECK style). `ReservationRequest` (`src/risk/reservations.py:131`) and `CountedReservation` (`:154`) gain optional `required_margin: Decimal | None = None`; `register_request` includes it in the identity comparison (`risk_reservations.py:248-254`); `_counted_from_row` (`:149`) fills it. Hand-written migration that imports no project module (0009-0011 style), real downgrade. The request is registered "at plan issue" (module docstring), where quantity and the plan zone are known: `required_margin = quantity * entry_price / TARGET_LEVERAGE`.

### Pattern P5: Snapshot COMPLETE (D-05)
After the guard returns `{margin_type, leverage}` the manager builds `snapshot = dataclasses.replace(live_context.plan_constraint_snapshot, margin_type=..., leverage=..., equity_used=<Phase 21 resolved equity>)` and passes it to `RestingEntry(plan_constraint_snapshot=...)` (`manager.py:998`). `snapshot_is_valid_for_live` then returns True iff all ten fields are non-None and the exchangeInfo capture is within the TTL (`constraint_snapshot.py:394-416`); `margin_type` must be non-empty text of at most 16 characters and not the literal `UNKNOWN`, `leverage >= 1`, `equity_used > 0` (`:165-195`). Test: build from the recorded Demo `symbolConfig` (after the guard) + Phase 21 equity and assert True; with `margin_type=None` assert False (the Phase 21 `tests/test_snapshot_live_equity.py` pair already exists for the stubbed case).

### Pattern P6: Post-fill liquidation comparison (D-12)
`PositionSnapshot.liquidation_price: Decimal | None` already exists (`binance_usdm.py:351`, filled at `:1919`). A new port `LiquidationWatch.check(entry, position) -> Verdict` is called from the coordinator after the first fill is confirmed. Rules: `liquidation_price is None`, `<= 0`, or equal to `"0"` (the cross-margin sentinel on every recorded Demo row) => UNKNOWN => treated as a failed check under the O-4 default; a value that satisfies the D-09 predicate with the same buffer => OK (a difference from the local figure is journalled as a DIVERGENCE-class alert with a reason code, calibration only); a value that does not => `CLOSE_REQUIRED` through the existing path. Plan it as its own plan (C10).

### Pattern P7: Error handling and alerts
The two POSTs go through `_sdk_call(CallKind.PLACEMENT, ...)` so they use the shared gate and are never retried. Definitive configuration rejections must be classified, otherwise they are UNKNOWN_EXCHANGE_ERROR, which `safe_mode_eligible` marks True (section 2.9). The guard itself returns NO_TRADE with a plain code; it does not enter SAFE_MODE (D-03 says NO_TRADE and an alert).

### Anti-Patterns to Avoid
- **Deciding on the POST answer.** Only the verification read decides (P1).
- **Using the entry-tier maintenance parameters.** Use the tier of `quantity * LP` (P2, golden G3).
- **Subtracting resting entries again from `availableBalance` without evidence**, or ignoring them (C1).
- **Reading the exchange inside the approval transaction** (C2).
- **Converting SDK bracket floats with `Decimal(float)`.** The SDK models bracket `maintMarginRatio` and `cum` as `Union[StrictFloat, StrictInt]` [SDK: `notional_and_leverage_brackets_response1_inner_brackets_inner.py:43-49`]; convert with `Decimal(repr(value))` (shortest round-trip text) and reject non-finite; caps and floors are `StrictInt`.
- **Putting a bracket table, maintenance ratio or default leverage in code or params** (criterion 2).
- **Adding a numeric default for a limits key** (`tests/test_no_unratified_defaults.py` scans `src` and `scripts`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Signed call with policy, gate, no retry | Own HTTP/signing | `BinanceUsdmAdapter._sdk_call` (`binance_usdm.py:813-842`) | Refuses without a policy, honours 418/429 pause, calls the -1021 hook, re-raises the original exception |
| Error classification | Message parsing | `classify(ErrorFacts, CallKind)` (`exchange_errors.py:631`) + new table entries | Code/class/kind only; no message text is ever read |
| Equity/freshness | New age predicate | `LiveEquitySource` + `check_equity_reading` (`account_equity.py`, `live_equity.py`): `age > ttl or age < 0` is stale | Same predicate everywhere; `account.max_equity_age_ms` = 15000 (D084) |
| Fee rates | A fee constant | `risk_kwargs["cost_rates"]` (`CostRates.fee_rate_entry/fee_rate_exit`) | Already verified at gate 4a |
| Open orders/positions of the symbol | A new read | gate 5e reads (`normal_orders`, `algo_orders`, `positions`) and `evaluate_pre_placement` | Already refuses SYMBOL_HAS_POSITION / SYMBOL_HAS_OPEN_ORDER |
| Limits file | Own TOML parse | `execution_limits.py` loader + `tests/support/execution_limits.py` | Fail-closed, provenance labels |
| Fixtures | Hand-typed JSON | `scripts/gen_phase22_fixtures.py` from the Phase 19 capture (pattern of `scripts/gen_phase21_fixtures.py`) | AGENTS.md: never hand-type fixtures |
| Canonical JSON/hash of the snapshot | Own serializer | `src.domain.canonical` via `snapshot_sha256` | Unchanged |

**Key insight:** every decision (alerts, error table, reservation store, equity freshness) already has a seam; the new code is two pure modules, four thin adapter methods and a guard that sequences them.

## 2. Binance contract findings (answers to questions 1-10)

### 2.1 Change Margin Type (question 1)
- `POST /fapi/v1/marginType`, IP weight 1, security TRADE, signed [CITED: OpenAPI `/fapi/v1/marginType`: `x-ip-weight: 1`, `x-security-type: TRADE`, `x-signed: true`].
- Body (form-urlencoded): `symbol` (required string), `marginType` (required, enum `ISOLATED`, `CROSSED`), `recvWindow` (max 60000), `timestamp` (required) [CITED: OpenAPI].
- 200 response: `{"code": 200, "msg": "success"}` (`code` int64 example 200, `msg` string example "success") [CITED: OpenAPI]. SDK model `ChangeMarginTypeResponse(code: Optional[int], msg: Optional[str])` [SDK: `change_margin_type_response.py`].
- Errors [CITED: llms-full, error-code page, verbatim]:
  - `### -4046 NO_NEED_TO_CHANGE_MARGIN_TYPE` - "No need to change margin type." => requesting the type the symbol already has is an ERROR. (HTTP status not stated on the page; not observed on Demo.)
  - `### -4047 THERE_EXISTS_OPEN_ORDERS` - "Margin type cannot be changed if there exists open orders."
  - `### -4048 THERE_EXISTS_QUANTITY` - "Margin type cannot be changed if there exists position."
  - `### -4168 JOINT_MARGIN_REJECT_WITH_ISOLATED` - "Unable to adjust to isolated-margin mode under the Multi-Assets mode." => it does NOT work in multi-asset mode; and `-4167` - "Unable to adjust to Multi-Assets mode with symbols of USDⓈ-M Futures under isolated-margin mode." is the converse.
  - Whether a pending conditional (algo) order counts as an "open order" for -4047 is not documented [ASSUMED no]. The guard refuses on open algo orders itself (D-04), so the answer does not matter for safety.
- Side effects: the stream reports `ACCOUNT_UPDATE` with reason `MARGIN_TYPE_CHANGE` (in the documented reason list) and `ACCOUNT_CONFIG_UPDATE` for a leverage change (`ac.s`, `ac.l`) [CITED: llms-full user-data-streams, lines "Account Configuration Update"]; the project already parses both (`binance_userdata_events.py:101`, `:674`). Not needed by the guard (REST is the truth).
- SDK method: `TradeApi.change_margin_type(symbol, margin_type, recv_window=None)`, `Weight(IP): 1`, path `/fapi/v1/marginType` [SDK: `trade_api.py:644-702`]. Through the project's wrapper: `await self._sdk_call(CallKind.PLACEMENT, self._sdk.rest_api.change_margin_type, symbol=symbol, margin_type=ChangeMarginTypeMarginTypeEnum.ISOLATED)` [`rest_api.py:2527` exposes it on the REST facade].

### 2.2 Change Initial Leverage (question 2)
- `POST /fapi/v1/leverage`, weight 1, TRADE, signed [CITED: OpenAPI]. Body: `symbol` (required), `leverage` (required int64, `minimum: 1`), `recvWindow`, `timestamp`. Description of `leverage`, verbatim: "Target initial leverage. The maximum is symbol-specific: use `initialLeverage` of bracket 1 from `GET /fapi/v1/leverageBracket`."
- 200 response: `leverage` (int), `maxNotionalValue` (string, example "1000000"), `symbol` [CITED: OpenAPI]; SDK `ChangeInitialLeverageResponse` [SDK].
- Change-log 2026-10-09, verbatim: "`POST /fapi/v1/leverage` (Change Initial Leverage): removed the documented fixed maximum of 125 on `leverage`. The maximum is symbol-specific and equals `initialLeverage` of bracket 1 from `GET /fapi/v1/leverageBracket` (e.g. 150 for BTCUSDT and ETHUSDT). Documentation correction only, reflecting current backend behavior." [CITED: llms-full]. The recorded Demo bracket 1 says `"0.brackets.0.initialLeverage": "125"` [demo-observed, not mainnet], so Demo and the documentation example differ.
- Errors [CITED: llms-full error-code]: `-4028 INVALID_LEVERAGE` ("Invalid leverage", "Leverage `%s` is not valid", "Leverage `%s` already exist with `%s`"); `-4209 ADJUST_LEVERAGE_SYMBOL_FAILED` ("The max leverage of Symbol is 20x", "Leverage adjustment failed. Current symbol max leverage limit is %sx"); `-4161 ISOLATED_LEVERAGE_REJECT_WITH_POSITION` ("Leverage reduction is not supported in Isolated Margin Mode with open positions"); `-2028 MIN_LEVERAGE_RATIO` ("Leverage is smaller than permitted: insufficient margin balance."); order-time `-2027 MAX_LEVERAGE_RATIO` ("Exceeded the maximum allowable position at current leverage."); account-age/region limits `-4202`, `-4203`, `-4205`, `-4206`, `-4208`, `-4403` (all concern leverage above 20x or a regional cap; not expected at 5x [ASSUMED]).
- Which code a leverage above the symbol maximum returns is NOT stated: -4028 and -4209 are the candidates. Owner-run case (D-18) records it.
- Behaviour with an open position: only -4161 (reduction in isolated mode) is documented; the effect of raising it is unspecified. D-04 avoids the question.
- A leverage change to the value the symbol already has: not documented as an error (only -4028's third text "already exist with" hints at it) [ASSUMED]. The read-first design never sends it.
- SDK: `TradeApi.change_initial_leverage(symbol, leverage: int, recv_window=None)`, `Weight(IP): 1` [SDK: `trade_api.py:589-642`]. Pass a Python `int`.

### 2.3 Symbol Configuration (question 3)
- `GET /fapi/v1/symbolConfig`, weight 5, USER_DATA, signed; `symbol` optional (omitted: all symbols); `recvWindow`, `timestamp` [CITED: OpenAPI `/fapi/v1/symbolConfig`: `x-ip-weight: 5`].
- Response: array of objects `{symbol: string, marginType: string (example "CROSSED"), isAutoAddMargin: boolean, leverage: integer, maxNotionalValue: string (example "1000000")}` [CITED: OpenAPI]. SDK model `SymbolConfigurationResponseInner` has exactly these five properties, `leverage: StrictInt`, `maxNotionalValue: StrictStr`, `is_auto_add_margin: StrictBool` [SDK: `symbol_configuration_response_inner.py`]. Only v1 exists [CITED: OpenAPI path list; llms-full change-log 2024: "`GET /fapi/v1/symbolConfig`: Query user symbol configuration."].
- Recorded Demo payload, verbatim [demo-observed, not mainnet] (`account_read_only_capture-rest-004-symbol_config.json`): `"0.isAutoAddMargin": "false"`, `"0.leverage": "20"`, `"0.marginType": "CROSSED"`, `"0.maxNotionalValue": "20000000"`, `"0.symbol": "BTCUSDT"`. The value `ISOLATED` has never been observed in a symbolConfig answer [ASSUMED upper-case]; the Demo case must record it.
- `maxNotionalValue` at leverage 20 equals the cap of the Demo bracket whose `initialLeverage` is 20 (`"0.brackets.3.notionalCap": "20000000"`) [demo-observed]. This supports the order-time rule in [CITED: FAQ-margin]: an order is accepted only if "Notional value after the order is placed <= Notional value limit for each leverage". The guard therefore also requires `quantity * limit_price <= maxNotionalValue`.
- Relation to positionRisk: `GET /fapi/v3/positionRisk` (weight 5) returns `symbol, positionSide, positionAmt, entryPrice, breakEvenPrice, markPrice, unRealizedProfit, liquidationPrice, isolatedMargin, notional, marginAsset, isolatedWallet, initialMargin, maintMargin, positionInitialMargin, openOrderInitialMargin, adl, bidNotional, askNotional, updateTime` and NO `leverage`, `marginType`, `isAutoAddMargin` or `maxNotionalValue` [CITED: OpenAPI `/fapi/v3/positionRisk`]. The v2 endpoint has `marginType`, `isAutoAddMargin`, `leverage`, `maxNotionalValue` [CITED: OpenAPI `/fapi/v2/positionRisk`], and the change-log says V3 removed "Configuration-related fields ... can now be queried from `GET /fapi/v1/symbolConfig`" and lists `GET /fapi/v2/positionRisk` among endpoints "deprecated in the coming months" [CITED: llms-full change-log]. The ROADMAP statement "positionRisk v3 has no leverage field" is VERIFIED.

### 2.4 Notional and Leverage Brackets (question 4)
- `GET /fapi/v1/leverageBracket`, weight 1, USER_DATA, signed; `symbol` optional [CITED: OpenAPI].
- Response is a `oneOf` (array of `{symbol, notionalCoef?, brackets[]}` or a single object of the same shape); each bracket: `bracket` (int, "Notional bracket"), `initialLeverage` (int, "Max initial leverage for this bracket"), `notionalCap` (int, "Cap notional of this bracket"), `notionalFloor` (int, "Notional threshold of this bracket"), `maintMarginRatio` (number, "Maintenance ratio for this bracket"), `cum` (number in the array variant, integer in the object variant, "Auxiliary number for quick calculation") [CITED: OpenAPI]. `notionalCoef` (number): "user symbol bracket multiplier, only appears when user's symbol bracket is adjusted" [CITED: OpenAPI]. The SDK models the same `oneOf` (`NotionalAndLeverageBracketsResponse` -> `Response1` list or `Response2` object) [SDK]; the recorded Demo answer is the array variant (`"0.symbol": "BTCUSDT"`). The adapter must unwrap both shapes and require exactly one entry for the requested symbol.
- Which bracket applies to a notional: the endpoint page does not say. The support-center article says the rate and amount are looked up "on the level of position notional" [CITED: FAQ-liq]. The recorded table has `notionalFloor` of each bracket equal to the previous `notionalCap`; whether an exact edge belongs to the lower or upper bracket is undocumented, and it does not matter because `n*rate - cum` is continuous at every recorded edge (50000: 200 = 200; 250000: 1200 = 1200; 3000000: 28700 = 28700; ... ) [VERIFIED: computed on the Demo table].
- Dependence on the account's current leverage: none observed. The table was recorded while the symbol was at x20 and still lists brackets with `initialLeverage` 125, 100 and 50 [demo-observed]. The only account-specific element is `notionalCoef`; its exact meaning (are floors/caps already multiplied?) is undocumented [ASSUMED]. Fail closed: a present `notionalCoef` that is not exactly 1 => bracket data unusable => NO_TRADE, until the owner decides.
- Recorded Demo BTCUSDT table (verbatim fields, [demo-observed, not mainnet]; fixture only, never production data):

| bracket | initialLeverage | notionalFloor | notionalCap | maintMarginRatio | cum |
|---|---|---|---|---|---|
| 1 | 125 | 0 | 50000 | 0.004 | 0.0 |
| 2 | 100 | 50000 | 250000 | 0.005 | 50.0 |
| 3 | 50 | 250000 | 3000000 | 0.01 | 1300.0 |
| 4 | 20 | 3000000 | 20000000 | 0.025 | 46300.0 |
| 5 | 10 | 20000000 | 40000000 | 0.05 | 546300.0 |
| 6 | 5 | 40000000 | 100000000 | 0.1 | 2546300.0 |
| 7 | 4 | 100000000 | 120000000 | 0.125 | 5046300.0 |
| 8 | 3 | 120000000 | 200000000 | 0.15 | 8046300.0 |
| 9 | 2 | 200000000 | 300000000 | 0.25 | 28046300.0 |
| 10 | 1 | 300000000 | 500000000 | 0.5 | 103046300.0 |

### 2.5 Isolated-margin liquidation price, one-way mode (question 5)
**Official text** [CITED: FAQ-liq, `https://www.binance.com/en/support/faq/how-to-calculate-liquidation-price-of-usd%E2%93%A2-m-futures-contracts-b3c689c1f50a44cabb3a84e663b81d93`]. The general formula is an image on that page and cannot be quoted as text. What is text:
- Variables: `WB` wallet balance ("In Cross margin mode, WB is crossWalletBalance"); `TMM1` maintenance margin of all other contracts; `UPNL1` unrealized PnL of all other contracts; `cumB` maintenance amount of the BOTH position (one-way); `Side1BOTH` direction of the BOTH position, 1 long, -1 short; `Position1BOTH` absolute size; `EP1BOTH` entry price; `MMR B` maintenance margin rate of the BOTH position; `MP` mark price.
- Isolated rule: "If it is an isolated margin mode, then TMM=0, UPNL=0", `WB` is the wallet balance of the isolated position, "substitute the position quantity, MMR, cum into the formula".
- Maintenance margin: "Maintenance Margin = Position Notional * Maintenance Margin Rate on the level of position notional" minus the maintenance amount of that level (example: 10 BTCUSDT at mark 26,000, rate 1%, amount 1,300 => 10 x 26,000 x 1% - 1,300 = 1,300 USDT).
- Tier rule: "you must use the maintenance margin rate and the amount corresponding to the other margin levels" when the notional implied at the liquidation price lies in a different level.
- Worked cross-margin examples with inputs and results (ETHUSDT liquidation price 1153.26; BTCUSDT 26,316.89), "there may be a slight variation due to decimals".
- Trigger: "Liquidation occurs when the Mark Price hits the liquidation price of a position." Fees and funding: the page does not include fees; funding enters only indirectly through the mark price; the Liquidation Clearance Fee is deducted after liquidation and is not part of the liquidation price [CITED: FAQ-protocols].

**Reconstruction** (stated liquidation condition: margin balance <= maintenance margin, [CITED: FAQ-wallet] "Positions are liquidated once Margin Balance is less than or equal to the Maintenance Margin", with `Margin Balance = Wallet Balance + Unrealized PNL`): for one BOTH position of size `Q`, side `s` (+1/-1), entry `EP`, isolated wallet `WB`, rate `m`, amount `cum`, mark `P`:
`WB + s*Q*(P - EP) = Q*P*m - cum`  =>  `LP = (WB + cum - s*Q*EP) / (Q*m - s*Q)`.
This is the general formula with `TMM = UPNL = 0`. It reproduces both official examples: ETHUSDT 1153.26 and BTCUSDT 26316.89 [VERIFIED: computed, `liq_check.py`; inputs from the page: WB 1,535,443.01, TMM1 71,200.81144, UPNL1 -56,354.57, cumB 135,365, 3683.979 ETH, EP 1456.84, MMR 10%; and TMM1 356,512.508, UPNL1 -448,192.89, cumB 16,300, 109.488 BTC, EP 32,481.98, MMR 2.5%]. Neither example exercises a short or an isolated position; the short side follows from the same condition with `s = -1`.

**Closed forms for the guard** (isolated, `WB = Q*EP/L` at the moment of the fill, `L` the verified leverage):
- LONG:  `LP = (EP*(1 - 1/L) - cum/Q) / (1 - m)`
- SHORT: `LP = (EP*(1 + 1/L) + cum/Q) / (1 + m)`
`m` and `cum` are those of the bracket that contains `Q*LP` (the tier rule), not of the bracket that contains `Q*EP`.

**Entry-price assumption.** For a position that does not exist yet the formula is exact only if (a) the position fills at `EP`, (b) its isolated wallet equals the initial margin `Q*EP/L`, (c) the entry commission does not reduce that wallet, and (d) no funding has been paid. (b)-(d) are [ASSUMED]; the page is silent. Using the LIMIT price as `EP` is the worst case in both directions: a BUY LIMIT fills at or below its limit price (a lower `EP` lowers the long's `LP`, away from the stop), a SELL LIMIT fills at or above it (a higher `EP` raises the short's `LP`, away from the stop) [reasoned from the closed forms]. Effect of a fee `F` taken from the isolated wallet: `LP` moves toward the entry by `F / (Q*(1 -/+ m))`, about 0.05% of price for a 0.05% taker fee [reasoned; assumption (c)]. The buffer must cover it; the post-fill comparison with the exchange value is the real check.

**Which endpoint returns the exchange value.** `GET /fapi/v3/positionRisk` field `liquidationPrice` (string, "liquidation price"), together with `isolatedMargin`, `isolatedWallet`, `maintMargin`, `positionInitialMargin` [CITED: OpenAPI]. The page gives no isolated-specific semantics and its example value is `"0"`. All 15 recorded Demo rows read `"row_0_liquidation_price": "0"` (cross margin, 5000+ USDT of wallet) [demo-observed, not mainnet]; no isolated sample exists. `PositionSnapshot.liquidation_price` carries it (`binance_usdm.py:351`).

### 2.6 `availableBalance` semantics (question 6)
- API reference: `GET /fapi/v3/account` top-level `availableBalance` is described only as "Available balance. USDT only in single-asset mode; USD-denominated in multi-assets mode."; `totalOpenOrderInitialMargin`: "Initial margin required for open orders."; `totalPositionInitialMargin`: "Initial margin required for positions."; `totalInitialMargin`: "Total initial margin requirement."; `maxWithdrawAmount`: "Maximum transferable/withdrawable amount."; per-asset rows carry `availableBalance`, `openOrderInitialMargin`, `positionInitialMargin`, `initialMargin` [CITED: OpenAPI `/fapi/v3/account`]. The API docs do NOT say whether `availableBalance` is net of open-order margin.
- Support-center article, verbatim formula: "Available for Order = max(0, crossWalletBalance + SUM cross Unrealized PNL - (SUM Cross Initial Margin + SUM Isolated Open Order Initial Margin))" and "Isolated Open Order Initial Margin = abs(Isolated Present Notional) * IMR - abs(Size) * IMR * Mark Price" [CITED: FAQ-wallet, `https://www.binance.com/en-IN/support/faq/how-to-check-my-futures-wallet-balance-5d62f8be18d24544b5b6156094c16bf7`]. So per that article resting open-order initial margin IS deducted (cross and isolated), and the term is floored at zero. That the API field `availableBalance` equals this "Available for Order" is [ASSUMED]. `maxWithdrawAmount` is not defined anywhere read and is not the input.
- Recorded Demo payloads: every `totalOpenOrderInitialMargin` and `totalPositionInitialMargin` is `"0.00000000"` and `availableBalance` equals the wallet (`"4999.09343961"`, `"4998.39137539"`) [demo-observed]; the -2019 case was rejected, so no payload contains a resting order. CONTEXT's "confirmed from the recorded `totalOpenOrderInitialMargin` field" is not supportable.
- Right input for "can this new order be afforded": the top-level `availableBalance` of the SAME single-asset read that produced the equity, cross-checked against the USDT row of `assets[]` of the same response; subtract nothing already inside it; add the margin of claims the exchange cannot yet see (other approved-but-unplaced plans and placements newer than the reading). Isolated mode: the isolated position's wallet is carved out of `crossWalletBalance`, so `availableBalance` excludes margin already locked in isolated positions [reasoned from the formula above; ASSUMED mapping].
- Owner-run case that settles it (D-18): read `GET /fapi/v3/account` (`availableBalance`, `totalOpenOrderInitialMargin`, the USDT row) before; place ONE far resting BUY LIMIT of the owner's approved quantity (the existing `insufficient_margin_order` machinery already records these figures before and after, `scripts/demo_probe.py:4299-4350`); read again; expected if the FAQ holds: `totalOpenOrderInitialMargin` rises by about `notional / leverage` and `availableBalance` falls by the same amount; run it once at the account's current cross x20 and once after the guard has set ISOLATED x5 (the isolated term differs).

### 2.7 Initial margin of a new order (question 7)
[CITED: FAQ-margin, `https://www.binance.com/en/support/faq/how-to-calculate-the-margin-requirement-on-binance-futures-trading-4f83b65d83654b5e933f85ef12bf769d`], one-way mode: "Margin Requirement = Max(Abs(Position Notional Value + Bid Order Value), Abs(Position Notional Value - Ask Order Value)) / Leverage", position notional = size x mark price, order value = size x limit price; "only open limit orders occupy margin"; pending stop orders reserve none but are margin-checked on submit and trigger; no margin check for close-position orders. An order goes through when "Cost <= Available Balance" where cost "includes initial margin and open loss (if any)", and "Notional value after the order is placed <= Notional value limit for each leverage". The page does not say whether trading fees are part of the check and does not cover isolated margin. For a flat symbol and one BUY limit: `IM = qty * limit_price / leverage`. Demo agrees with the shape: a 10 BTC far BUY at x20 (notional 785,709) needed about 39,285 against 4,998.39 available and got `-2019` "Margin is insufficient." [demo-observed; 785709/20 = 39285.45, computed]. The open-loss definition is deferred to another article => the formula in P3 is [ASSUMED] and covered by the headroom.

### 2.8 Position mode and the G3-001 wording (question 8)
Quoted from the official OpenAPI [CITED: OpenAPI `/fapi/v1/positionSide/dual`]:
- GET, "Get Current Position Mode (USER_DATA)": "Get user's position mode (Hedge Mode or One-way Mode ) on ***EVERY symbol***"; response `dualSidePosition` boolean, description `"true": Hedge Mode; "false": One-way Mode`; IP weight **30**.
- POST, "Change Position Mode (TRADE)": "Change user's position mode (Hedge Mode or One-way Mode ) on ***EVERY symbol***. **After CM migration**, UM and CM share the **same** `dualSidePosition` setting. Calling this endpoint flips both UM and CM at once. If either side has any open order or open position, the change is rejected: `-4067` (open orders exist), `-4068` (open position exists)"; weight 1. Error texts: `-4067 POSITION_SIDE_CHANGE_EXISTS_OPEN_ORDERS` "Position side cannot be changed if there exists open orders."; `-4068 POSITION_SIDE_CHANGE_EXISTS_QUANTITY` "Position side cannot be changed if there exists position."; `-4059 NO_NEED_TO_CHANGE_POSITION_SIDE` "No need to change position side." [CITED: llms-full].
This settles inherited item G3-001 and DECISIONS D044's wording ("rejected when open orders (-4067) or an open position (-4068) exist"; `docs/SOURCES.md:46` still says "not fetched": the planner updates that row with this reading). `GET /fapi/v1/accountConfig` (weight 5) also returns `dualSidePosition` (boolean) and `multiAssetsMargin` [CITED: OpenAPI + SDK `futures_account_configuration`]; `account_config_snapshot` already reads both and requires real bools (`binance_usdm.py:1684-1706`).

### 2.9 Weights, the REST gate and the error taxonomy (question 9)
IP weights [CITED: OpenAPI, `x-ip-weight`]: `POST marginType` 1; `POST leverage` 1; `GET symbolConfig` 5; `GET leverageBracket` 1; `GET accountConfig` 5; `GET v3/account` 5; `GET v3/balance` 5; `GET v3/positionRisk` 5; `GET positionSide/dual` 30; `GET multiAssetsMargin` 30; `POST positionMargin` 1. Per-minute IP limits come from `exchangeInfo.rateLimits` (not a constant) [CITED: llms-full general-info "LIMITS"]. The shared gate has no weight budget: `src/adapters/binance_ratelimit_gate.py` contains no weight accounting [VERIFIED: grep for "weight" in that file returns nothing]; it only holds a 418 ban / 429 pause and refuses every REST call while one is active, "of every call kind including placements" (module docstring). So the new calls "fit" by construction (they go through `_sdk_call` -> `gate.check()`); a guard run on the happy path costs 5 (symbolConfig) + 1 (brackets) + the equity refresh (15) and, when it has to change, + 2 + 5.

Error taxonomy: `classify` decides from (HTTP class, code, `CallKind`); a code missing from `ERROR_CODE_TABLE` is `UNKNOWN_EXCHANGE_ERROR`, which `safe_mode_eligible` marks True [VERIFIED: `exchange_errors.py:648-679`]. None of the codes below is in the table today (table keys include -2019, -2018, -4164, -4400, -4401 for PLACEMENT; verified by reading the whole table). Proposed entries (category per the file's own rule for definitive refusals of a mutating call: `REJECTED_DEFINITIVE` on `CallKind.PLACEMENT`, evidence `documented`, new read date 2026-10-23):

| Code | Name | Category (PLACEMENT) | Why needed |
|------|------|----------------------|-----------|
| -4046 | NO_NEED_TO_CHANGE_MARGIN_TYPE | REJECTED_DEFINITIVE | already-requested type is an error; guard then verifies by read |
| -4047 | THERE_EXISTS_OPEN_ORDERS | REJECTED_DEFINITIVE | margin type with open orders |
| -4048 | THERE_EXISTS_QUANTITY | REJECTED_DEFINITIVE | margin type with a position |
| -4028 | INVALID_LEVERAGE | REJECTED_DEFINITIVE | leverage not valid |
| -4161 | ISOLATED_LEVERAGE_REJECT_WITH_POSITION | REJECTED_DEFINITIVE | reduction in isolated mode with a position |
| -4168 | JOINT_MARGIN_REJECT_WITH_ISOLATED | REJECTED_DEFINITIVE | isolated under multi-assets |
| -4209 | ADJUST_LEVERAGE_SYMBOL_FAILED | REJECTED_DEFINITIVE | symbol maximum |
| -2027 / -2028 | MAX/MIN_LEVERAGE_RATIO | REJECTED_DEFINITIVE | order-time leverage/notional limits (an entry rejection) |

Others (-4202..-4206, -4208, -4403) stay UNKNOWN on purpose: not expected at 5x. A table change requires editing `_EXPECTED_BY_CODE` in `tests/test_exchange_errors.py` (`set(ERROR_CODE_TABLE) == set(_EXPECTED_BY_CODE)`, line 213) and the read-date expectation (`_expected_read_date`, line 231), plus `docs/integration/BINANCE.md` / `docs/SOURCES.md` rows.

### 2.10 Other account factors (question 10)
- `isAutoAddMargin`: read from symbolConfig, boolean; no UM setter exists (2.3 / P1). `true` => NO_TRADE.
- Multi-assets: incompatible with ISOLATED (-4168/-4167). Refuse (Phase 21 O-3 default, already `multi_assets_margin` true => `UNCERTAIN_ACCOUNT_STATE`).
- Portfolio Margin: separate `/papi/v1/um/...` endpoints (`POST /papi/v1/um/leverage`, `GET /papi/v1/um/leverageBracket`) [CITED: llms-full index]; every call in this phase targets `/fapi`. A Portfolio Margin account is out of scope [ASSUMED the project account is a classic futures account].
- Demo vs mainnet known differences: Demo minimum notional 50 vs the 5 of the documentation text (R-4164) and Demo first bracket 125x vs 150x quoted for mainnet (2.2) [demo-observed vs CITED]; Demo `liquidationPrice` untested in isolated mode. The error-code and bracket behaviour of the Demo host for the new calls is unobserved: that is what D-18 is for.

## 3. Codebase integration register (questions a-d)

### 3.1 Adapter surface and the tests that pin it (question a)
- Seams in `src/adapters/binance_usdm.py`: `_sdk_call` (`:813-842`), `get_position_mode` (`:1558-1581`), `account_information_snapshot` (`:1624-1653`), `account_config_snapshot` (`:1684-1706`), `AccountInformationSnapshot` (`:517-532`), `AccountConfigSnapshot` (`:549-559`). Add four methods in the same style (lazy SDK imports, Decimal-only parse, `ValueError` naming the field, nothing logged).
- Signed-call registry `SIGNED` in `tests/test_binance_usdm_signed_calls.py:557-615` (dict method -> (call, SDK name)); `SIGNATURE_SNAPSHOTS` `:622-662`; `assert len(SIGNED) == 16` at `:666`; comment "sixteen" at `:556` and `:779`; fake SDK payload table `_payloads` `:132-198` (it serves `SimpleNamespace` objects: any NEW attribute the adapter reads from `account_information_v3`, e.g. `available_balance`, must be added there, otherwise `AttributeError`). Four new methods => 20. All the parametrized tests (recv-window, no-policy, gate refusal, 418/429 never retried, -1008, -1021) then run on them automatically; each needs its `SIGNED` row and a `_payloads` entry: `symbol_configuration`, `notional_and_leverage_brackets`, `change_margin_type`, `change_initial_leverage`.
- Shadow isolation: `ORDER_SURFACE` (`tests/test_paper_shadow_isolation.py:61-76`) lists the spied order/read methods; `test_negative_control_the_spy_list_covers_every_public_order_method_of_the_adapter` (`:633-656`) asserts `public_async - market_data == set(ADAPTER_ORDER_METHODS)`. A new public async adapter method must be classified: the two changes go into `ORDER_SURFACE` (spied; a reach from the SHADOW closure fails), the two reads into the `market_data` set next to the Phase 21 reads (`"account_information_snapshot"`, `"account_balances_snapshot"`, `"account_config_snapshot"`, `"user_trades_in_window"`, `"income_in_window"`). The same file bans `src.adapters.binance_usdm` and non-allowlisted `src.execution.*` modules from the SHADOW import closure: the guard and watch modules live under `src/execution/` and need no allowlist entry; the pure risk modules must not import them.
- Gate invariants a new module will meet: `tests/test_phase21_gate.py` pure modules (`PHASE21_PURE_MODULES`: no wall clock, no float constructor, no `src.adapters/persistence/execution/ops/paper`, `binance*`, `polars`, `pandas`, `numpy`, `httpx`, no `"USDT"` string constant) and execution modules (`EXECUTION_FORBIDDEN_IMPORTS`: `src.adapters`, `src.persistence`, `binance*`, `sqlalchemy`; no clock, no `"USDT"`); Phase 22 should add its own gate file with the same checks (`tests/support/ast_guards.py`: `wall_clock_calls`, `float_constructor_calls`, `forbidden_imports`).

### 3.2 Pre-placement seam (question b)
`execute_approved_plan` (`src/execution/manager.py:469`). Order (verified by reading `:611-1028`): identity/replay -> binding -> `LIMITS_NOT_CONFIGURED` (`:737`, any unset key) -> SAFE_MODE -> cost-rate gate -> `evaluate_risk` -> `decide_placement` -> limit/stop price snap (`:831-843`: `limit_price = quantize_price(price=derive_limit_price(...), ...)`, `sl_trigger_price`) -> quantity bound (5b) -> snapped geometry (5c) -> TP1 sizing (5d) -> live reads and `evaluate_pre_placement` (5e, `:899-959`) -> position mode (5f, `:961-973`: `position_mode_reason = check_position_mode(position_mode)`) -> resting-entry hand-off record (5g, `:976-1006`) -> consume the approval (`:1023+`) -> place. Insert the guard after `:973` and before `:976`: every input it needs is in scope (`bound.symbol`, `bound.side`, `quantity`, `limit_price`, `sl_trigger_price`, `positions`, `normal_orders`, `algo_orders`, `mark_reading`, `risk_kwargs["cost_rates"]`). Because gates 2, 2b and 3 run earlier, the guard (a mutating call) cannot run while `LIVE_ORDERS_DISABLED`, while a limit is `NOT_CONFIGURED`, or in SAFE_MODE. A refusal returns `ExecutionOutcome(is_no_trade=True, reason_code=...)` before anything is consumed.
- Call-site wiring: `LivePlacementContext` (`live_context.py:32-110`, frozen kw_only dataclass; only 8 constructor sites: `tests/test_execution_manager.py`, `scripts/demo_rehearsal.py`) gains a REQUIRED `margin_guard` port (no `None` default that skips, the CR-07 rule stated in the manager docstring). `ExecutionAdapter` Protocol (`manager.py:156-194`) needs no new method if the guard owns its adapter port. `gate_kwargs` keys are pinned (`_GATE_KWARG_KEYS`, `:440`, check at `:622`): do not use it.
- Phase 21 reservation store: `PgRiskReservationStore` (`src/persistence/risk_reservations.py`): `register_request` (`:207`), `reserve_in` (`:267`, locks `daily_risk_days` then the plan row, `reservation_verdict`), `mark_placed` (`:342`), `list_counted` (`:197`), `make_reserving_save_atomic` (`:477`, `daily_loss_quote: Callable[[date], Decimal | None]` is a SYNC callable). Migration head is `0011_risk_reservations` (`tests/test_phase21_gate.py:205`). What 0012 adds: P4. Tests that must change for 0012: `tests/test_phase21_gate.py` invariant 6; `tests/test_persistence_migration_pg.py` (head pin and upgrade/downgrade/ORM parity cases, per Phase 21 research); `src/db/models.py` `RiskReservationRow`; `tests/test_risk_reservations.py` / `_pg.py` constructors (new fields optional so old calls stay valid).
- Execution limits: keys in `EXECUTION_LIMIT_KEYS` (`execution_limits.py:45`), field map `EXECUTION_LIMIT_FIELDS` (`:77`), dataclass `ExecutionLimits` (`:143`, all fields required), loader rule `if value <= 0:` with message "(must be a positive integer)" (`:267`). Files to change together for each new key: `execution_limits.py`, `config/execution/execution-limits-v1.toml` (value AND `[provenance.*]` mirror), `config/execution/README.md`, `tests/support/execution_limits.py` (`TEST_ONLY_EXECUTION_LIMIT_VALUES`, odd-looking fake values), `tests/test_execution_limits.py` (pins: `EXPECTED_UNSET`, `ALL_REQUIRED_KEYS`, `assert len(limits.unset_keys()) == 14` at `:699`, per-section counts `:461-463`, "account is the last section" `:710`, committed-file tests), `tests/test_no_unratified_defaults.py` (`GUARDED_NAMES` derives from the keys: add the new names so an invented default is caught), `tests/test_phase19_gate.py:467-480`, `tests/test_phase20_gate.py` (`PHASE20_LIMIT_KEYS` stays; a Phase 22 gate should do the same for its keys), `docs/GLOSSARY.md`/`README` text, `tests/test_execution_manager.py` where a fully-set limits object is built.
- Docs: `docs/trading/RISK_MANAGEMENT.md` section 9 line 137 says "the buffer is a registry parameter whose value is chosen in Phase 22 (D035 fixes no number)"; DECISIONS D044 follow-up (5) and `STATE.md` ("11-04: liquidation buffer stays a registry parameter") say the same. D-10's deviation needs the owner's DECISIONS row (a new row D085 breaks `tests/test_phase20_gate.py::test_invariant_6` which asserts `after_d078 == ["D079", "D080", "D081", "D082", "D083", "D084"]`; update it on purpose, as Phase 21 did for D084) and an edit of that RISK_MANAGEMENT line. No `params/**/*.toml` file changes.

### 3.3 Constraint snapshot (question c)
`PlanConstraintSnapshot` (`constraint_snapshot.py:137-214`): `margin_type: str | None`, `leverage: int | None`, `equity_used: Decimal | None`; `live_inputs_status` COMPLETE only if margin type, leverage, equity and the seven filter values are all non-None (`:197-214`); `build_plan_constraint_snapshot(..., *, margin_type=None, leverage=None, equity_used=None, captured_at_utc)` (`:222-264`) has no caller in `src/` (grep: only a docstring mention in `src/risk/live_equity.py:173`); its one script caller is `scripts/demo_rehearsal.py:1946` (`**dict(ctx.snapshot_live_inputs or {})`). The persisted row is write-once evidence (`src/persistence/snapshots.py` docstring: "write-once evidence ... a different snapshot for the same plan is `RowConflict`"; append-only trigger of migration 0004); it is NOT consulted at placement (`snapshot_is_valid_for_live` is called only on the in-memory snapshot: `manager.py:1811`, `protection.py:2314`). See C8 / P5. Existing probe reads to reuse: `BinanceProbeAdapter.symbol_config` and `leverage_brackets` (`binance_probe.py:1143-1161`, sdk names `symbol_configuration`, `notional_and_leverage_brackets`, both already in `SDK_REST_METHODS`) and the recorded fixtures `account_read_only_capture-rest-004-symbol_config.json`, `-005-leverage_brackets.json`; the capture files are flattened `summary` maps (keys like `0.brackets.3.cum`, every value text), so `scripts/gen_phase22_fixtures.py` must unflatten them into the SDK wire shape exactly as `scripts/gen_phase21_fixtures.py` does for the account payloads (it also drops `accountAlias`).

### 3.4 Owner-run Demo probe cases (question d)
`scripts/demo_probe.py` (6,446 lines): groups `CAPTURE_CASES`, `SJ1_CASES` (`:341`), `SJ2_CASES` (`:349`); `OPTIONAL_CASES` maps a limits-file key to a case id (`:293-323`); `CASE_ORDER = (*REQUIRED_CASES, *OPTIONAL_CASES.values())` (`:325`) with `gtd_expiry` kept last; `FIXTURE_CASES` (`:360`) lists the groups whose REST answers are written as scrubbed fixtures; a write case is an `async def _x(case: _WriteCase) -> CaseResult` wrapped by `run_write_case(...)` (`:4632-4639` for `insufficient_margin_order`), with its own bound function when it must not use the order cap (`margin_order_refusal`, `:1304-1340`). The owner's limits file keys are parsed in `src/ops/operator_evidence.py` (`_MARGIN_QUANTITY = "insufficient_margin_quantity"`, `:234`; `optional_cases` flags), documented in `.planning/DEMO-EVIDENCE-PLAN.md` (sections 16-23; the `insufficient_margin` case is section 19, `:238-244`). The probe adapter has NO mutating configuration method and its `SDK_REST_METHODS` allowlist (`binance_probe.py:~118-141`) lacks `change_margin_type` / `change_initial_leverage`; tests pinning the case lists and counts: `tests/test_demo_probe_sj2_cases.py`, `tests/test_demo_probe_cases.py`, `tests/test_demo_probe_capture_cases.py`, `tests/test_demo_probe_evidence.py`, `tests/test_binance_probe.py`. Suggested new group `SJ3_CASES` (names are proposals): `symbol_config_change_to_isolated` (flat symbol: read config, change to ISOLATED x5, read back, record the casing of `marginType`, the answers, `maxNotionalValue`), `margin_type_change_with_resting_order` (far resting BUY, try the change, record -4047 text/HTTP class, clean up), `leverage_above_bracket_maximum` (record the exact code for `bracket1.initialLeverage + 1`), `margin_insufficient_at_target_leverage` (reuse `insufficient_margin_order` after the change), `available_balance_with_resting_order` (before/after, 2.6), `isolated_position_liquidation_price` (open the approved quantity at ISOLATED x5, read `positionRisk.liquidationPrice` and the account figures, close; the only way to obtain the missing isolated golden). Each case flag goes in `OPTIONAL_CASES`, `operator_evidence.py` accepts the key, the plan document gets a section, and none runs without the owner's `--execute`. The owner decides whether the probe restores the original x20 CROSSED configuration afterwards (the guard will set ISOLATED x5 again anyway).

### 3.5 Error taxonomy, alerts and reason vocabulary (questions e, 9)
- `RejectionReason` has 21 members and already includes `INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"` [VERIFIED: `src/domain/enums.py:122-160`, line 135]; GLOSSARY says, verbatim, "`INSUFFICIENT_MARGIN` is reserved: no code emits it yet; it is first emitted by the Phase 22 margin guard." [VERIFIED: `docs/GLOSSARY.md:182`]. Pins of the size 21 (all must change if the enum grows): `tests/test_phase21_gate.py:181`, `tests/test_phase20_gate.py:278-279` (also pins GLOSSARY 9.1 = 21 codes), `tests/test_phase19_gate.py:419` and `:677-684` (listed set equals the enum and is disjoint from the Phase 19 plain codes), `tests/test_domain_enums.py:239` and `:312`, `tests/test_pre_placement.py:601`, `tests/test_backtest_engine.py:535`, `tests/test_daily_loss.py:542`, `tests/test_decision_alignment_bookkeeping.py:82-85`, `tests/test_geometry_audit_doc.py:246`, plus `scripts/decision_alignment/bookkeeping.py` gate GL-03 and `docs/GLOSSARY.md` 9.1/9.2 text ("21 members"). Plain-string codes need only GLOSSARY 9.3 rows and a module constant (precedent: `SYMBOL_HAS_POSITION`, `HEDGE_MODE_UNSUPPORTED`, `LIMITS_NOT_CONFIGURED` in `pre_placement.py:39-56`; the Phase 19 gate checks that each new plain code is listed in 9.3 with "proposed canonical, promote in Phase N", `tests/test_phase19_gate.py:653-660`). Do not add constants to `pre_placement.py`: `test_every_public_pre_placement_constant_is_classified` (`tests/test_live_risk_inputs.py`) classifies every public constant there. Proposed plain codes in the new guard module: `MARGIN_CONFIG_UNVERIFIED` (symbolConfig does not show the target), `MARGIN_CONFIG_CHANGE_REFUSED` (exchange refused or symbol not flat), `AUTO_ADD_MARGIN_ENABLED`, `MARGIN_MODE_UNSUPPORTED` (multi-asset), `LIQUIDATION_TOO_CLOSE`, `LIQUIDATION_INPUT_UNAVAILABLE` (bracket missing/stale/unusable), `LEVERAGE_ABOVE_BRACKET`, `NOTIONAL_ABOVE_MAX` [ASSUMED: names]; `INSUFFICIENT_MARGIN` from the enum; hedge keeps `HEDGE_MODE_UNSUPPORTED`; unknown account reading keeps `UNCERTAIN_ACCOUNT_STATE`.
- Alerts: `ALERT_EVENTS` (`src/ops/alerts.py:95-120`) is a closed mapping; an event outside it "is a programming error and raises ValueError". Pins: `tests/test_alerts.py:235` (`set(ALERT_EVENTS) == {...}`) and `tests/test_alerts_ops05_matrix.py`. Recommended: use the existing `DIVERGENCE` (HIGH) event with a reason code for "configuration not verified" and "liquidation price differs"; use the existing `CLOSE_REQUIRED` (CRITICAL) path for a failed post-fill check. Alert fields must match `[A-Z][A-Z0-9_]{0,63}` / the subject regex: never an amount.

### 3.6 Fakes and fixtures to extend
`tests/support/account_fakes.py` (`ScriptedAccountReader`, `build_demo_adapter`, `demo_account_snapshots`) over `tests/fixtures/phase21/recorded_demo/`; `FakeExecutionAdapter` in `tests/test_execution_manager.py:149` and `tests/test_execution_gates.py:141`; `AccountInformationSnapshot` / `AccountEquityReading` gain `available_balance` (Decimal) and `total_open_order_initial_margin`; `check_equity_reading` identity checks (`src/risk/live_equity.py`) stay; the `_payloads` fake in `tests/test_binance_usdm_signed_calls.py` and `tests/test_account_reads_adapter.py` must serve the new attributes.

## 4. Never build (summary for the planner)
A bracket table, a rate constant, a second REST gate, a second freshness predicate, a second alert sink, a retrying wrapper for the POSTs, a snapshot serializer, a Telegram message (Phase 23).

## 5. Code Examples

### 5.1 Golden values for the pure liquidation module
Computed this session with Python `Decimal` (precision 40), on the recorded Demo BTCUSDT table of 2.4, leverage 5, entry 80000. The formula is the one of 2.5 (validated against the official examples). Evidence label: `[VERIFIED: computed]` for the arithmetic, `[demo-observed, not mainnet]` for the bracket inputs, `[ASSUMED]` for equality with the exchange's own figure (never observed). The tests should recompute with the module and compare with these values to the module's own quantum (the full-precision values are given so a test can use exact `Decimal` equality before quantization).

| Case | Side | Qty | Entry notional | Entry bracket | Self-consistent bracket | Liquidation price (exact to 12 dp) |
|------|------|-----|----------------|---------------|-------------------------|------------------------------------|
| G1 | LONG | 0.01 | 800 | 1 | 1 | 64257.028112449799 |
| G2 | SHORT | 0.01 | 800 | 1 | 1 | 95617.529880478088 |
| G3 | LONG | 0.75 | 60000 | 2 | **1** (`Q*LP` = 48192.77 < 50000) | 64257.028112449799 (the entry-tier value 64254.606365159129 is WRONG: closer to entry by 2.42) |
| G4 | SHORT | 0.75 | 60000 | 2 | 2 (`Q*LP` = 71691.54) | 95588.723051409619 |
| G5 | LONG | 0.7 | 56000 | 2 | 1 (`Q*LP` = 44979.92) | 64257.028112449799 (entry-tier value 64249.820531227566 wrong) |

Derivation of G1 in the closed form: `(80000 * (1 - 1/5) - 0/0.01) / (1 - 0.004) = 64000 / 0.996 = 64257.02811...`. G2: `(80000 * 1.2 + 0) / 1.004 = 95617.52988...`. G3 entry-tier attempt: `(64000 - 50/0.75) / 0.995 = 64254.606...`, whose notional `0.75 * 64254.61 = 48190.95` lies in bracket 1, so the bracket-1 solution is the consistent one. Other guard numbers: initial margin of G1 = `0.01 * 80000 / 5 = 160`; the recorded -2019 case: `785709 / 20 = 39285.45` against `availableBalance` 4998.39 (R-2019).
Two structural facts the tests should pin: (i) for the recorded table `n*rate - cum` is continuous at all nine bracket edges; (ii) at 5x the long liquidation sits about 19.7% below entry and the short about 19.5% above (G1/G2), so the guard refuses mainly very wide stops; the owner's buffer (O-2) is therefore a sensitivity knob, not the main filter.

### 5.2 Pure liquidation module (shape; names are proposals)
```python
# Source: closed forms of section 2.5; every number comes from the caller (bracket rows are inputs).
@dataclass(frozen=True)
class Bracket:
    bracket: int
    initial_leverage: int
    notional_floor: Decimal
    notional_cap: Decimal
    maint_margin_ratio: Decimal
    cum: Decimal

def liquidation_price(*, side: str, entry_price: Decimal, quantity: Decimal,
                      leverage: int, brackets: Sequence[Bracket]) -> Decimal | None:
    """None = unknown (fail closed). Isolated, one-way, no fees, no funding (CITED: FAQ-liq)."""
    ...
    for tier in brackets:
        lev = Decimal(leverage)
        if side == "LONG":
            lp = (entry_price * (1 - 1 / lev) - tier.cum / quantity) / (1 - tier.maint_margin_ratio)
        else:
            lp = (entry_price * (1 + 1 / lev) + tier.cum / quantity) / (1 + tier.maint_margin_ratio)
        notional_at_lp = quantity * lp
        if tier.notional_floor <= notional_at_lp <= tier.notional_cap:
            return lp
    return None
```
The buffer predicate: `long_ok = lp < stop - buffer`; `short_ok = lp > stop + buffer` with `buffer = entry_price * buffer_bps / Decimal(10000)`; strict inequality as in D-09; a missing result is NO_TRADE.

### 5.3 Adapter method shape (two reads, two changes)
```python
# Source: pattern of BinanceUsdmAdapter.account_config_snapshot (binance_usdm.py:1684-1706).
async def change_margin_type(self, *, symbol: str, margin_type: str) -> None:
    from binance_sdk_derivatives_trading_usds_futures.rest_api.models.enums import (
        ChangeMarginTypeMarginTypeEnum,
    )
    await self._sdk_call(CallKind.PLACEMENT, self._sdk.rest_api.change_margin_type,
                         symbol=symbol, margin_type=ChangeMarginTypeMarginTypeEnum(margin_type))
```
The answer body is not trusted (the verification read decides); the exception propagates unchanged so the guard can classify it with `error_facts`.

### 5.4 Limits keys (integers only)
```
[margin]
liquidation_buffer_bps   = "NOT_CONFIGURED"   # O-2: buffer as basis points of the entry price
max_bracket_age_ms       = "NOT_CONFIGURED"   # O-3 / D-11
margin_headroom_bps      = "NOT_CONFIGURED"   # O-3 / D-13: headroom as basis points of the margin needed
[provenance.margin]  (mirror each key; DECISION only after a DECISIONS row)
```
Section and key names are [ASSUMED: names]. The loader requires every section to appear in `EXECUTION_LIMIT_KEYS`, every key to appear in both blocks, and refuses `0`, floats and booleans (`execution_limits.py:253-270`).

## Common Pitfalls

### Pitfall 1: Entry tier instead of liquidation tier
**What goes wrong:** the maintenance rate and amount are taken from the bracket of the entry notional; for a long near a bracket edge the liquidation price is overstated toward the entry (non-conservative; G3: off by 2.42 on 64,257). **Avoid:** P2 fixed point, test G3/G5 and the edge case `Q*LP` exactly on a cap.

### Pitfall 2: Treating -4046 as a failure of the plan
**What goes wrong:** the margin type already was ISOLATED (race, manual change) and -4046 aborts a fine plan, or worse is treated as success without a read. **Avoid:** the verification read decides (P1). Because -4046 is a definitive rejection it must be in the error table, else SAFE_MODE-eligible.

### Pitfall 3: Unclassified configuration errors enter the SAFE_MODE path
**What goes wrong:** -4047/-4048/-4028 are UNKNOWN_EXCHANGE_ERROR; `safe_mode_eligible` is True for exactly that category. **Avoid:** extend the table (2.9) and make the guard's own error handler return NO_TRADE without SAFE_MODE.

### Pitfall 4: Float contamination from the SDK
**What goes wrong:** bracket `maintMarginRatio` and `cum` arrive as Python floats; `Decimal(0.004)` is `0.004000000000000000083...`. **Avoid:** `Decimal(repr(value))`, `is_finite()`, reject bool; keep the conversion in the adapter; the pure module accepts Decimal only. The project guard `tests/test_domain_no_float.py` covers domain/risk/backtest/core paths, so a float constructor in `src/risk/*` fails CI.

### Pitfall 5: Counting a claim twice, or not at all
**What goes wrong:** a PLACED entry is subtracted by the exchange (inside `availableBalance`) AND by the reservation sum, or a just-placed entry is in neither. **Avoid:** the rule of P3 (RESERVED others always; PLACED others only while newer than the reading); a fresh reading is taken inside the guard run; test both windows with a scripted clock.

### Pitfall 6: Freshness
**What goes wrong:** reusing a 15 s old equity reading for the margin check after another plan was placed. **Avoid:** the guard calls `LiveEquitySource.refresh()` itself and takes `now_utc` AFTER it returns (the documented contract, `account_equity.py` docstring), then `check`.

### Pitfall 7: `liquidationPrice` "0"
**What goes wrong:** the post-fill comparison reads `"0"` as "far away" (safe). **Avoid:** P6: `0`, None and non-positive are unknown.

### Pitfall 8: Casing and type of `marginType`
**What goes wrong:** the stream carries `"cross"`/`"isolated"` (position rows, `mt`), symbolConfig carries upper-case `"CROSSED"` (Demo). **Avoid:** compare exact upper-case `"ISOLATED"` for symbolConfig; anything else fails closed; the Demo case records the real casing of an isolated symbol.

### Pitfall 9: The guard mutates the owner's account
**What goes wrong:** a symbol the owner trades by hand is switched to x5 ISOLATED. **Avoid:** D-04 (flat, no orders, no algo orders) and O-1; log the previous config in the journal before the change (evidence), never auto-restore.

### Pitfall 10: Persisted snapshot is write-once
See C8: do not try to update `plan_constraint_snapshots`; `RowConflict`.

### Pitfall 11: `notionalCoef`, 150x vs 125x, and bracket age
Brackets change per account and per time; the documented maximum leverage was a documentation correction on 2026-10-09; `notionalCoef` appears only for adjusted users. **Avoid:** bounded age (D-11), refuse `notionalCoef != 1`, never copy bracket numbers into code.

### Pitfall 12: Weight 30 for the position-mode GET
Calling `get_position_mode` per plan costs 30 weight (gate 5f already does); do not add a second call (C5).

### Pitfall 13: Migration and tests
`tests/test_phase21_gate.py` pins head `0011`; `tests/test_persistence_migration_pg.py` pins the head and every object; PG tests silently skip without `TEST_DATABASE_URL` in the process environment (`tests/pg_support.py` does not read `.env`); run with `TRADING_CI_STRICT=1` at the gate.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `GET /fapi/v2/positionRisk` (leverage, marginType, maxNotionalValue inline) | `GET /fapi/v3/positionRisk` + `GET /fapi/v1/symbolConfig` | change-log entry introducing v3/symbolConfig; v2 "will be deprecated in the coming months" | configuration needs its own read (this phase) |
| Documented fixed max leverage 125 | Max = bracket 1 `initialLeverage` (e.g. 150 for BTCUSDT) | 2026-10-09 | never hard-code a maximum |
| Entry-time stop | Fill-driven protection (D079) | 2026-10-22 | the post-fill liquidation check sits next to the stop placement |

**Deprecated/outdated:** `GET /fapi/v2/account`, `/fapi/v2/balance`, `/fapi/v2/positionRisk` (announced); do not use them.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The API field `availableBalance` equals the support-center "Available for Order" (net of cross initial margin and isolated open-order initial margin) | 2.6, P3 | resting entries counted twice (refuses valid plans) or not at all (admits an unaffordable plan, which the exchange then rejects with -2019: no loss) |
| A2 | Isolated wallet at fill = `Q*EP/L`; entry fee not deducted from it; no funding before the check | 2.5 | local LP slightly optimistic (about the fee fraction of price); post-fill comparison catches it |
| A3 | The exchange `liquidationPrice` of an isolated one-way position equals the formula of 2.5 (tier-consistent) | 2.5, P6 | false CLOSE_REQUIRED or missed danger; settled only by the isolated Demo case |
| A4 | Open-loss formula for a marketable limit (`max(0, (limit-mark)*qty)` for BUY) | P3 | margin under/over-estimated by a small amount; covered by headroom |
| A5 | `marginType` for an isolated symbol is returned as upper-case `ISOLATED` | 2.3, P1 | guard never passes; found by the first Demo case |
| A6 | Error code for a leverage above the symbol maximum is -4028 or -4209; HTTP class BAD_REQUEST for -4046/-4047/-4048 | 2.2, 2.9 | classification table entries wrong; D-18 records them |
| A7 | -4047 does not count conditional (algo) orders | 2.1 | none (the guard refuses on algo orders itself) |
| A8 | `notionalCoef` semantics (are floors/caps already multiplied?) | 2.4 | refused when present and not 1; owner decision if it ever appears |
| A9 | Setting the same leverage again is not an error / is -4028 | 2.2 | never sent (read first) |
| A10 | The project account is a classic (not Portfolio Margin) USDⓈ-M account | 2.10 | /fapi calls would not apply |
| A11 | Leverage-age/KYC/region errors (-4202..-4206, -4208, -4403) do not occur at 5x | 2.2 | they stay UNKNOWN_EXCHANGE_ERROR (fail closed) |
| A12 | Module, table, column, key and reason-code names in this file | 1 | cosmetic |
| A13 | Under ISOLATED margin the Phase 21 identities (`totalMarginBalance = wallet + unrealized`, equality with the USDT asset row and the balance endpoint) still hold (Phase 21 A1) | P3 | the equity read could fail closed after the symbol is switched; the Demo case re-captures the account |

## Open Questions

1. **What `availableBalance` deducts, and the isolated `liquidationPrice`** (A1, A3). Blocks "VERIFIED" for criteria 2 and 3 but not the build: the code is written behind `free_margin_basis` and the formula module; the D-18 cases produce the evidence. Recommendation: plan the cases first, build against fakes, record the outcome in a Phase 22 evidence file; do not claim criterion 2/3 Demo-proven.
2. **Approval-time vs placement-time margin check (C2).** Recommendation: placement-time only plus the stored column; revisit with Phase 24 wiring.
3. **Alert event for "configuration not verified" (C9).** Recommendation: `DIVERGENCE` + reason code; otherwise update the pins listed in 3.5.
4. **Whether the persisted snapshot row must also become COMPLETE (C8).** Recommendation: no; Phase 24 builds the snapshot at issue time with the symbolConfig read it will have by then.
5. **`CallKind` for the POSTs.** Recommendation: `PLACEMENT`. If the owner wants a distinct kind, `CallKind` and every `_every(...)` entry and the parametrized tests change.
6. **Owner items O-1..O-4 stay open.** Nothing in this file sets a number. Note for the owner (fact, not a number): at 5x on the recorded Demo table the long liquidation is about 19.7% below the entry (5.1).
7. **Post-fill action default (O-4):** close when the exchange value fails the same predicate, or when it is unknown (P6); alert only when it passes but differs.
8. **Probe restore behaviour** after the Demo configuration cases (3.4).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | all commands | yes | 0.12.17 | — |
| Python | all | yes | 3.13.15 | — |
| PostgreSQL via `TEST_DATABASE_URL` | migration 0012 and reservation tests | yes (variable set in this shell, value not printed) | — | none: PG tests skip locally, fail under `TRADING_CI_STRICT=1` |
| Binance SDK | adapter | yes | 17.4.0 / binance-common 4.4.0 | — |
| Network to developers.binance.com | doc re-reads | partly: `llms-full.txt` via curl yes; per-endpoint pages no (HTTP 202 empty); WebFetch of `schema.yaml` yes | — | the OpenAPI document and `llms-full.txt` (Sources) |
| Binance Demo REST | D-18 evidence | owner-run only | — | recorded Phase 19 fixtures |
| Docker | `-m docker` suite only | not needed | — | — |

**Missing dependencies with no fallback:** none. **Missing with fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1, pytest-asyncio (`asyncio_mode = "auto"`), pytest-xdist [VERIFIED: `uv pip list`, AGENTS.md] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_<file>.py -x` |
| Full suite command | `uv run pytest -m "not docker" -n 4` (orchestrator only, about 9-10 min); recorded gates run sequentially with `TEST_DATABASE_URL` and `TRADING_CI_STRICT=1` |
| TDD | `workflow.tdd_mode: true` per the Phase 21 research; plan tests first |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RISK-02 / crit 2 | Golden G1-G5; continuity at every edge; unknown on non-contiguous/stale brackets, notional above top cap, leverage above `initialLeverage`; strict buffer predicate boundaries; no float/clock/bracket constant | unit | `uv run pytest tests/test_liquidation_price.py -x` | Wave 0 |
| RISK-02 / crit 3 | Margin verdict: exact boundary (equal passes), headroom, fees, open loss, other-reserved sum, NULL margin => unknown, stale/future reading => `UNCERTAIN_ACCOUNT_STATE`, recorded -2019 shape => `INSUFFICIENT_MARGIN` | unit | `uv run pytest tests/test_margin_check.py -x` | Wave 0 |
| EXEC-01 / crit 1 | Guard: matches => no POST; CROSSED x20 flat => exactly one marginType POST, one leverage POST, one re-read; open order/algo/position with mismatch => zero POSTs; -4046/-4047/-4048/timeout then read decides; `isAutoAddMargin` true; read failure; never two POSTs of the same kind; never retried | unit with scripted fakes | `uv run pytest tests/test_margin_guard.py -x` | Wave 0 |
| EXEC-01 | Adapter methods: recv-window, gate refusal, no retry on 418/429, -1008, -1021 for all four new methods; brackets `oneOf` unwrap; float -> Decimal; missing field raises | unit | `uv run pytest tests/test_binance_usdm_signed_calls.py tests/test_leverage_margin_adapter.py -x` | extend + Wave 0 |
| EXEC-01 | Manager integration: guard runs after gate 5f and before consume; refusal leaves no intent row; `LIVE_ORDERS_DISABLED`/SAFE_MODE/limits unset => guard never called (zero POSTs) | unit | `uv run pytest tests/test_execution_manager.py -k margin_guard -x` | extend |
| EXEC-01 / D-05 | COMPLETE snapshot from recorded symbolConfig + Phase 21 equity is valid for live; `margin_type=None` is not | unit | `uv run pytest tests/test_snapshot_margin_leverage.py -x` | Wave 0 |
| RISK-02 / D-14 | Migration 0012 upgrade/downgrade/ORM parity; `required_margin` stored/read; NULL legacy row => unknown; sum excludes the candidate | PG | `uv run pytest tests/test_persistence_migration_pg.py tests/test_risk_reservation_margin_pg.py -x` | update + Wave 0 |
| RISK-02 | Position mode: hedge => `HEDGE_MODE_UNSUPPORTED` (existing), multi-assets => `MARGIN_MODE_UNSUPPORTED`/`UNCERTAIN_ACCOUNT_STATE` | unit | `uv run pytest tests/test_margin_guard.py -k mode -x` | Wave 0 |
| EXEC-02 / D-12 | Post-fill: exchange LP satisfying predicate => OK + calibration alert on difference; failing/`0`/None => CLOSE_REQUIRED path (O-4 default) | unit with coordinator fakes | `uv run pytest tests/test_liquidation_watch.py -x` | Wave 0 |
| Taxonomy | New codes classify `REJECTED_DEFINITIVE` on PLACEMENT; others still UNKNOWN | unit | `uv run pytest tests/test_exchange_errors.py -x` | update |
| Limits | New keys required, `NOT_CONFIGURED`, positive-integer-only, guarded against defaults | unit | `uv run pytest tests/test_execution_limits.py tests/test_no_unratified_defaults.py -x` | update |
| Gate | `tests/test_phase22_gate.py`: pure modules (no clock/float/client/bracket literal/"USDT"), execution modules (no adapter/store/SDK), keys `NOT_CONFIGURED`, `RejectionReason` still 21, migration head `0012_...`, requirement-to-test names resolve, owner items O-1..O-4 named in a Phase 22 owner/deferred record | structural | `uv run pytest tests/test_phase22_gate.py -x` | Wave 0 (pattern: `tests/test_phase21_gate.py`) |
| Probe | New opt-in cases registered, refused without the flag, bounded by the owner limits, none runs without `--execute` | unit | `uv run pytest tests/test_demo_probe_sj3_cases.py -x` | Wave 0 |
| Shadow isolation | New methods classified; shadow runtime reaches none | unit | `uv run pytest tests/test_paper_shadow_isolation.py -x` | update |

### Tests that must change (checked against the files read)
`tests/test_binance_usdm_signed_calls.py` (16 -> 20, `SIGNED`, `SIGNATURE_SNAPSHOTS`, `_payloads`, comments), `tests/test_paper_shadow_isolation.py` (`ORDER_SURFACE`, `market_data`), `tests/test_phase21_gate.py` (invariant 6 head `0012`; invariant 3 only if the enum changes), `tests/test_persistence_migration_pg.py` (head and objects), `tests/test_execution_limits.py` / `tests/support/execution_limits.py` / `tests/test_no_unratified_defaults.py` / `tests/test_phase19_gate.py:467-480` (new keys), `tests/test_exchange_errors.py` (`_EXPECTED_BY_CODE`, read dates), `tests/test_phase20_gate.py::test_invariant_6` (only when the owner's DECISIONS row D085 lands), `tests/test_account_reads_adapter.py` + `tests/support/account_fakes.py` (new snapshot fields), `tests/test_live_equity.py` / `tests/test_account_equity_source.py` (reading fields), `tests/test_execution_manager.py` (the 8 `LivePlacementContext` constructor sites and the fake adapter), `tests/test_demo_probe_*` (case lists, only if the SJ3 group is added), `tests/test_alerts.py:235` and `tests/test_alerts_ops05_matrix.py` (only if a new alert event is added). If the enum is promoted instead (not recommended): all pins in 3.5.

### Sampling Rate
- **Per task commit:** the touched test files with `-x`, plus `uv run ruff check` and `uv run mypy src` on touched modules.
- **Per wave merge:** subagents run only their own tests (AGENTS.md); PG files need `TEST_DATABASE_URL` in the process environment.
- **Phase gate (orchestrator):** sequential `uv run pytest -m "not docker"` with `TEST_DATABASE_URL` and `TRADING_CI_STRICT=1`, `uv run python scripts/verify_decision_alignment.py all`, `uv lock --check`, ruff format/check, mypy.

### Wave 0 Gaps
- [ ] `scripts/gen_phase22_fixtures.py` + `tests/fixtures/phase22/recorded_demo/` (`symbol_config.json`, `leverage_brackets.json`, positions with `liquidationPrice`) + `DERIVATIONS.md`, generated from the Phase 19 capture (never hand-typed; unflatten the `summary` maps; deterministic output)
- [ ] `tests/test_liquidation_price.py`, `tests/test_margin_check.py`, `tests/test_margin_guard.py`, `tests/test_leverage_margin_adapter.py`, `tests/test_snapshot_margin_leverage.py`, `tests/test_liquidation_watch.py`, `tests/test_risk_reservation_margin_pg.py`, `tests/test_phase22_gate.py`
- [ ] Fakes in `tests/support/` for a scripted guard adapter (symbolConfig/brackets/changes with error injection) reusing `ScriptedAccountReader` and the virtual clock
- [ ] Framework install: none

## Security Domain

`security_enforcement: true`, `security_asvs_level: 1`, `security_block_on: high` (`.planning/config.json`).

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (no new auth) | existing signed adapter; keys are owner-attested (OPS-02) |
| V3 Session Management | no | — |
| V4 Access Control | yes | the mutating config calls are reachable only through the guard, which runs after enablement (`LIVE_ORDERS_DISABLED`), limits-ready and SAFE_MODE gates; the two POST methods are on the spied order surface of the shadow isolation test; symbol comes from the bound plan (`bound.symbol`, live-5 check `_require_live5_symbol`), never from a caller value |
| V5 Input Validation | yes | exchange payloads parsed to Decimal/int with type, finite and presence checks; unknown field or shape => unknown => NO_TRADE; classify errors by (class, code, kind), never by message |
| V6 Cryptography | no | — |
| V7 Error Handling and Logging | yes | structlog with class names only; no balances, no account identifiers, no URLs; alert fields are enum-like codes |
| V8 Data Protection | yes | no new secret; evidence fixtures scrubbed (`accountAlias` stays dropped) |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Stale bracket or reading lets a too-close liquidation or an unaffordable order through | Tampering | bounded ages (`max_bracket_age_ms`, 15000 ms equity), `age > ttl or age < 0` stale |
| Config change on a symbol with a manual position/orders | Elevation / Tampering | D-04 precondition from the same exchange reads; never cancel or close to make room |
| Double mutation (retry) of a signed POST | Tampering | `_sdk_call` never retries; one POST per kind per run; verification read decides |
| Misclassified error enters SAFE_MODE or hides a refusal | DoS / Repudiation | extend the error table; tests assert category per code |
| Float drift in bracket maths | Tampering | Decimal-only pure module, `repr` conversion in the adapter, AST float guard |
| Race between approvals on free margin | Tampering | RESERVED-others sum with a stored margin; placement-time fresh reading; PG test with two connections |
| Account alias or key in fixtures/logs | Information disclosure | generator drops the field; existing scan test pattern |
| Config mutation while live is disabled | Elevation | guard placed after gates 2/2b/3; test: zero POSTs when disabled |

## Sources

### Primary (HIGH confidence)
- Official OpenAPI "Futures (USDⓈ-M) REST API 1.0.0": `https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/1.0.0/schema.yaml` (paths `/fapi/v1/marginType`, `/fapi/v1/leverage`, `/fapi/v1/symbolConfig`, `/fapi/v1/leverageBracket`, `/fapi/v1/positionSide/dual`, `/fapi/v1/accountConfig`, `/fapi/v3/account`, `/fapi/v3/balance`, `/fapi/v3/positionRisk`, `/fapi/v2/positionRisk`, `/fapi/v1/positionMargin`)
- Official docs bundle `https://developers.binance.com/en/docs/llms-full.txt`: error-code page (`/products/derivatives-trading-usds-futures/error-code`), change-log (`.../change-log`, entries 2026-10-09, symbolConfig/v3 introduction, 2022-02-10, 2020-06-15), general-info "LIMITS", user-data-streams "Account Configuration Update"
- Installed SDK `binance-sdk-derivatives-trading-usds-futures 17.4.0`: `rest_api/api/trade_api.py:589-702, 757-800, 1757-1803`, `rest_api/api/account_api.py:856-990`, `rest_api/models/{symbol_configuration_response_inner,change_margin_type_response,change_initial_leverage_response,notional_and_leverage_brackets_response*,position_information_v3_response_inner}.py`, `models/enums.py:215-217`
- Repo files read this session (paths and lines in the text): `src/adapters/binance_usdm.py`, `binance_probe.py`, `binance_ratelimit_gate.py`, `src/domain/exchange_errors.py`, `src/domain/enums.py`, `src/execution/{manager,pre_placement,constraint_snapshot,execution_limits,live_context,account_equity}.py`, `src/persistence/risk_reservations.py`, `src/persistence/snapshots.py`, `src/risk/{reservations,live_equity,cost_rates}.py`, `src/db/alembic/versions/0011_risk_reservations.py`, `src/ops/alerts.py`, `config/execution/execution-limits-v1.toml`, `scripts/demo_probe.py`, `tests/test_binance_usdm_signed_calls.py`, `tests/test_paper_shadow_isolation.py`, `tests/test_phase19_gate.py`, `tests/test_phase20_gate.py`, `tests/test_phase21_gate.py`, `tests/test_exchange_errors.py`, `tests/test_execution_limits.py`, `tests/support/{execution_limits,account_fakes}.py`, `docs/DECISIONS.md` (D035, D036, D044, D075, D076, D080, D084), `docs/trading/RISK_MANAGEMENT.md`, `docs/GLOSSARY.md`, `docs/SOURCES.md`
- Recorded Demo evidence: `.planning/phases/19-execution-plan-binding-price-check/evidence/fixtures/account_read_only_capture-rest-004-symbol_config.json`, `-005-leverage_brackets.json`, `-006-position_mode.json`, `insufficient_margin_order-rest-004..007`, `commission_vs_realized_pnl-rest-003-positions.json`, `19-OWNER-GAPS.md` sections 2a/2b

### Secondary (MEDIUM confidence, Binance support center)
- Liquidation price formula: `https://www.binance.com/en/support/faq/how-to-calculate-liquidation-price-of-usd%E2%93%A2-m-futures-contracts-b3c689c1f50a44cabb3a84e663b81d93` (formula is an image; variables, isolated rule, tier rule and two examples are text)
- Liquidation protocols: `https://www.binance.com/en/support/faq/binance-futures-liquidation-protocols-360033525271`
- Margin requirement: `https://www.binance.com/en/support/faq/how-to-calculate-the-margin-requirement-on-binance-futures-trading-4f83b65d83654b5e933f85ef12bf769d`
- Futures wallet balance: `https://www.binance.com/en-IN/support/faq/how-to-check-my-futures-wallet-balance-5d62f8be18d24544b5b6156094c16bf7`

### Tertiary (LOW confidence)
- Nothing from third-party sites is relied on. The Assumptions Log lists everything not verified.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new dependency; SDK signatures read.
- Binance contracts (endpoints, params, weights, error codes): HIGH - official OpenAPI and error page read; HTTP classes of the new codes and the isolated casing are unobserved.
- Liquidation formula: MEDIUM - reconstruction validated on the official examples; exchange equality for an isolated position unverified.
- `availableBalance` semantics: LOW-MEDIUM - official support text exists, API docs silent, no Demo evidence.
- Architecture/seams: HIGH - read in code; test-impact lists derived from the files.
- Pitfalls: MEDIUM-HIGH.

**Research date:** 2026-10-23
**Valid until:** 2026-11-22 for the code seams (re-read `src/execution/manager.py` if another phase lands first); re-fetch the OpenAPI document before implementation (the docs site changes: the leverage maximum was corrected on 2026-10-09).
