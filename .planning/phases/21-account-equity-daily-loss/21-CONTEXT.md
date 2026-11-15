# Phase 21: Account Equity + Daily Loss from Binance - Context

**Gathered:** 2026-10-22
**Status:** Ready for planning (gathered with `--auto`, single pass; items marked OWNER-OPEN must not be implemented until the owner decides)

<domain>
## Phase Boundary

Sizing and DAILY_STOP use Binance-canonical equity and the D033 daily-loss definition, never a caller-supplied constant. Today `AccountState.equity` and `daily_loss_quote` are injected by the caller (`src/paper/market_inputs.py`, `src/backtest/engine.py`, `src/paper/loop.py`).

Requirements: RISK-01, RISK-02, EXEC-01, OPS-02 (ROADMAP.md Phase 21, three success criteria). Depends on Phase 18 only.

Out of scope (stays elsewhere): margin type, leverage and the liquidation guard (Phase 22, D035); Telegram UX and money amounts (23); wiring into a running live process, the ORDER_TRADE_UPDATE event-time ordering and the REST rate-limit gate wiring (24); the verification that Binance `realizedPnl` excludes commission (G2-042, owned by Phase 24; this phase depends on its outcome); Demo/mainnet attestation of keys (24 to 26).

Gathered with `--auto`, single pass. Inputs: ROADMAP Phase 21, `21-NOTES.md`, `20-DEFERRED.md`, DECISIONS D033/D035/D079 to D083, Demo evidence of 2026-10-22 (`19-OWNER-GAPS.md` section 2a). Nothing here edits `docs/DECISIONS.md`. No number is invented.
</domain>

<decisions>
## Implementation Decisions

All decisions below are the recommended option or a direction already recorded by the owner (D033, D035, `21-NOTES.md`). They are defaults the owner may override.

### Equity source and field (criterion 1, F-012)
- **D-01:** Equity is read from `GET /fapi/v3/account` (and `/fapi/v3/balance`) and kept current by `ACCOUNT_UPDATE` from the user-data stream; REST is the truth, the stream is the freshness path. A REST read at start and after every stream gap (Demo: frames sent during a gap are not replayed after reconnect).
- **D-02:** The equity field is chosen and documented in the phase: the account-level margin-balance style total (wallet balance plus unrealized PnL) for the USDT asset, not `availableBalance` (that is Phase 22's margin check). The plan names the exact field after reading the recorded Demo capture (`evidence/fixtures/account_read_only_capture-rest-001-account_information.json`, `-002-account_balance_all.json`) and the current docs; if the docs and the capture disagree, the capture wins and the difference is recorded. The Demo account has `multiAssetsMargin=false`; multi-asset mode is a refusal (NO_TRADE), not a code path.
- **D-03:** Unknown, unreadable or stale equity is NO_TRADE with `UNCERTAIN_ACCOUNT_STATE` (F-012). A stale age uses a registry/limits key; the key stays `NOT_CONFIGURED` until the owner sets the number (same pattern as `commission_rate_ttl_seconds` in `src/risk/live_commission.py`). Age is `> ttl` or negative = stale, exactly ttl passes (same predicate as `check_portfolio`). — **Reversibility:** reversible — a gate predicate and one key.
- **D-04:** Equity is a Decimal parsed from the exchange text; no float at any point (`tests/test_domain_no_float.py`). A zero or negative equity is NO_TRADE (`AccountState` already requires positive equity).
- **D-05:** `src/core/types.py` `AccountState` stays the pure core input (equity, risk_rate). The new live source lives outside `src/core` (adapter/risk boundary) and builds `AccountState`; paper and backtest keep their ratified-config/ledger equity (D-12 of Phase 12: live-only code path).

### Daily loss, UTC day, persisted state (criterion 2, D033)
- **D-06:** Daily loss follows D033 exactly: UTC day, `realized PnL + commissions + funding`, base = account equity at the UTC day start, thresholds from the params (warning 0.5%, stop 1%, `daily_loss_warning_threshold` / `daily_loss_stop_threshold`). The pure state machine (`src/risk/portfolio.py` daily state, `src/backtest/ledger.py` `daily_loss_quote`) is reused; Phase 21 supplies the live input.
- **D-07:** Day-start equity and the running day figures are persisted (PostgreSQL via the Phase 17 stores, new Alembic migration if a table is needed) so a restart inside the UTC day does not reset the day or move the base. A missing or unreadable persisted day state while a position or resting entry exists is fail-closed (NO_TRADE, alert), never "start a fresh day". — **Reversibility:** costly — a migration and a persisted schema other code reads.
- **D-08:** The day boundary uses the injected clock (no wall clock in pure modules). A day rollover captures a new day-start equity from a fresh REST read; if that read fails, the day stays unrolled-and-blocked (NO_TRADE) until it succeeds.
- **D-09:** Components come from Binance data, not from a local estimate: realized PnL and commission from `ORDER_TRADE_UPDATE` (`rp`, `n`/`N`; G3-009 owns parsing `commission` and `commissionAsset` and feeding this phase) cross-checked against REST (`/fapi/v1/userTrades`); funding from `FUNDING_FEE` income rows. Demo showed `/fapi/v1/income` returned 0 rows in four tries, so income-based funding is NOT confirmed on Demo; the plan treats funding as a REST-read component with an explicit "source unverified on Demo" label and does not rely on income rows for the stop decision until observed (OWNER-OPEN: accept trade-list-only counting in the meantime, or require income rows first).
- **D-10:** `realizedPnl` semantics: Demo trades show `realizedPnl` excludes commission (A9, demo-observed, not mainnet). The loss therefore adds commission explicitly. `LIVE_NET_PNL_SEMANTICS_VERIFIED` stays False and live R stays INCOMPLETE until Phase 24 verifies on mainnet (G2-042); this phase must not flip that flag.
- **D-11:** A commission asset other than USDT (BNB discount) is converted only with a rate the exchange reported at the time; if no rate exists, the daily loss is unknown and the result is fail-closed (the BNB discount is never used to shrink modeled cost, F-031).

### DAILY_STOP behaviour (criterion 2, F-013, F-963)
- **D-12:** At DAILY_STOP: cancel pending (unfilled) entries, keep the protective stops of open positions, alert. Never cancel a stop, never open anything new. This reuses Phase 19/20 pieces (coordinator, sweeper rules); cancel of entries is a REST action that honours the rate-limit gate and must not bypass a 429/418 pause (D081).
- **D-13:** The `DAILY_STOP` and daily-loss `WARNING` alert producers are built here (D-23 of Phase 20; `src/ops/alerts.py` `OPS05_MATRIX`, `emit_daily_state_alert` is a test trigger today). They emit through the existing journal-first sink. The producers stay unwired in a running process until Phase 24 (nothing in Phase 21 starts a process).
- **D-14:** DAILY_STOP is sticky for the rest of the UTC day: a later equity rise does not lift it; it clears only at the next UTC day start. Persisted with D-07.

### Portfolio caps and atomic risk reservation (criterion 3, F-407, F-955)
- **D-15:** Portfolio caps (max open positions, aggregate risk, cluster cap) count open positions, resting entries and approved-but-unplaced plans. `risk_inputs.open_positions` today excludes the last two.
- **D-16:** Approval reserves risk atomically: the reservation and the approval transition commit in one database transaction (a reservation row or counter guarded by the same transaction as the approval, uniqueness/locking decided by the planner against the Phase 17 stores). Two concurrent approvals cannot both pass a cap that only one fits. A reservation is released on every terminal plan state (expired, rejected, canceled, closed) and is rebuilt from durable rows on restart, never kept only in memory. — **Reversibility:** costly — touches the approval path and a migration.
- **D-17:** A plan whose reservation cannot be written (DB error) is refused, not approved (fail closed). Reading the current reserved total is part of the same decision as the gate (no check-then-act across two transactions).

### Constraint snapshot and TP unblocking (21-NOTES, G4-039)
- **D-18:** When equity has a live source, the plan constraint snapshot's equity field is filled from it. The snapshot becomes COMPLETE only together with Phase 22's margin type and leverage; Phase 21 adds a test that a snapshot built from the live equity, plus stubbed Phase 22 inputs, passes `snapshot_is_valid_for_live` (so the Demo rehearsal can stop reporting the known gap). No placeholder equity is ever fed to the re-size path.
- **D-19:** Margin type and leverage stay `UNKNOWN` in this phase. The Demo account is x20 CROSSED by account default and the system never sets it (D035 is Phase 22); Phase 21 must not set, change or assume either.

### Scope guards from the owner decisions
- **D-20:** No live order placement is enabled (`LIVE_ORDERS_DISABLED`). New REST reads are read-only (`GET`), signed via the existing adapter, behind the shared `RestRateLimitGate`; a -1003 ban end time is handled as D083 says (the clock-margin key stays `NOT_CONFIGURED`).
- **D-21:** OPS-02 (no-withdrawal keys, IP allowlist) is an owner attestation, not code. Phase 21 does not claim it; it only keeps secret-free logging (equity and PnL values are not secrets but account identifiers and keys never appear in logs or evidence).
- **D-22:** Everything Demo-observed is labelled "demo-observed, not mainnet" in code comments, docs and tests (D-17 of Phase 18). No trading parameter is chosen from Demo.

### OWNER-OPEN (record, do not implement)
- **O-1:** The stale-equity maximum age (D-03) and the number of days/retention of the persisted day state.
- **O-2:** Whether trade-list-only daily-loss counting is acceptable while income rows are unobserved (D-09).
- **O-3:** Multi-asset margin mode: refuse (D-02 default) versus support later.
- **O-4:** Whether a DAILY_STOP produced from an unverified-PnL-semantics day may stay hard (default) or only warn until G2-042 is verified.

### Claude's Discretion
- Module placement (`src/risk/` vs `src/execution/` vs a new `src/account/`), table and column names, the reservation's locking mechanism, test layout and fakes (reuse `tests/support/`), and plan/wave split.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Decisions and rules
- `docs/DECISIONS.md` D033 (daily loss definition), D035 (margin/leverage, Phase 22), D077 to D083 (protection, Q3/Q4/Q5, symbol ownership, -1003 end time), D036 (taker fees on entry and stop exit)
- `AGENTS.md` — fail closed, Decimal-only, no wall clock in pure modules, placement never re-sent
- `docs/trading/RISK_MANAGEMENT.md` section 11 (quantization) and daily-loss sections
- `docs/trading/EXECUTION_SPEC.md` 6.3 (fill-driven protection), section 8
- `docs/GLOSSARY.md` (DAILY_STOP, UNCERTAIN_ACCOUNT_STATE terms)

### Phase inputs
- `.planning/ROADMAP.md` Phase 21 section (criteria, inherited items G4-039, G2-042) and line for G3-009
- `.planning/phases/21-account-equity-daily-loss/21-NOTES.md` — TP unblocking and snapshot test
- `.planning/phases/20-reconcile-safe-mode-hardening/20-DEFERRED.md` — DAILY_STOP/WARNING alert producers belong to Phase 21
- `.planning/phases/20-reconcile-safe-mode-hardening/20-REVIEW.md` — open Phase 20 findings (not fixed; CR-C1 and WR-B6 are fail-open in modules this phase may call: `src/ops/spill.py`, stale-feed check)
- `.planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md` section 2a — Demo facts (A9 `realizedPnl`, income rows 0, account One-way, x20 CROSSED)
- `.planning/REQUIREMENTS.md` RISK-01, RISK-02, EXEC-01, OPS-02

### Evidence (demo-observed, not mainnet)
- `.planning/phases/19-execution-plan-binding-price-check/evidence/fixtures/account_read_only_capture-rest-001-account_information.json` (v3/account fields)
- `.planning/phases/19-execution-plan-binding-price-check/evidence/fixtures/account_read_only_capture-rest-002-account_balance_all.json` (v3/balance)
- `.planning/phases/19-execution-plan-binding-price-check/evidence/demo-probe-EVIDENCE-20261022T115616Z.json`, `...T120704Z.json`, `...T124048Z.json` (income retest)
- `.planning/DEMO-EVIDENCE-AUDIT.md`

### Code
- `src/risk/portfolio.py`, `src/risk/live_commission.py`, `src/risk/gating.py`, `src/risk/types.py`
- `src/core/types.py` (`AccountState`), `src/backtest/ledger.py` (`daily_loss_quote`, `daily_state`)
- `src/paper/market_inputs.py` (`RiskInputsProvider`, `make_context_factory`)
- `src/execution/constraint_snapshot.py` (`snapshot_is_valid_for_live`), `src/execution/gates.py`, `src/execution/manager.py`
- `src/adapters/binance_probe.py` (account reads), `src/adapters/binance_userdata_events.py` (`AccountUpdateEvent`, `parse_account_update`), `src/adapters/binance_usdm.py`
- `src/ops/alerts.py` (`OPS05_MATRIX`, `emit_daily_state_alert`)
- `src/adapters/binance_ratelimit_gate.py`, `src/ops/rest_gate_state.py` (shared REST gate)
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/risk/portfolio.py` daily-state thresholds and `check_portfolio` freshness predicate (age > ttl or negative is stale).
- `src/risk/live_commission.py` — the template for a fail-closed live account input (`UNCERTAIN_ACCOUNT_STATE`, injected `now_utc` and TTL, no clock read).
- `src/backtest/ledger.py` — daily loss from a ledger; same definition as D033.
- `src/adapters/binance_probe.py` account reads and `binance_userdata_events.py` `ACCOUNT_UPDATE` parsing; fixtures with real Demo payloads.
- `src/ops/alerts.py` journal-first sink and the OPS-05 matrix.
- Phase 17 stores and Alembic migrations for persisted day state and reservations.

### Established Patterns
- Live-only input resolvers are pure functions fed by an injected clock and a fresh observation; stale or missing returns NO_TRADE with a reason, never a default.
- Exchange values are parsed as Decimal from text; exchange text is classified by type/code, never by message.
- Parameters carry provenance labels and `NOT_CONFIGURED` keys stay unset until the owner decides (`config/execution/execution-limits-v1.toml`); `params/**/*.toml` is hash-locked (a behaviour change = new set + new `strategy_version`).

### Integration Points
- `make_context_factory` / `RiskInputsProvider` (paper) and the live context (`src/execution/live_context.py`): where equity and daily loss are injected today.
- The approval path (`src/approval/`) for the atomic reservation.
- The user-data stream supervisor for `ACCOUNT_UPDATE` and gap handling.
- `src/ops/alerts.py` for DAILY_STOP/WARNING producers; unwired until Phase 24.
</code_context>

<specifics>
## Specific Ideas

- Treat `AccountUpdateEvent` as a freshness signal and REST as the arbiter, as for orders (Phase 18/20).
- Add a golden fixture from the recorded Demo `v3/account` payload; fixtures are generated by script, never typed by hand (AGENTS.md).
</specifics>

<deferred>
## Deferred Ideas

- Margin type, leverage, liquidation guard, available-margin check: Phase 22.
- Live wiring of the equity refresher, the reservation release job and the alert producers in a running process: Phase 24.
- Mainnet verification of `realizedPnl` versus commission and of income rows: Phase 24/26.
- Phase 20 review findings (34, none fixed): tracked in `20-REVIEW.md`; fix before Phase 24 at the latest.
</deferred>

---

*Phase: 21-account-equity-daily-loss*
*Context gathered: 2026-10-22*
