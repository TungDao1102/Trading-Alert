# Phase 22: Leverage, Margin + Liquidation Guard - Context

**Gathered:** 2026-10-23
**Status:** Ready for planning (gathered with `--auto` at the owner's request, single pass; the owner has little domain knowledge and asked the assistant to choose; items marked OWNER-OPEN must not be implemented with a number until the owner decides)

<domain>
## Phase Boundary

Before any entry the system sets ISOLATED margin and a leverage of at most 5x on the symbol and verifies it from the exchange; it refuses the plan unless the liquidation price lies beyond the stop-loss by a buffer and unless the available margin covers the new order plus the other claims on margin. Position mode must be One-way, single-asset margin only. Today nothing in the system reads or sets the symbol configuration (Demo, 2026-10-04: BTCUSDT was x20 CROSSED from the account defaults).

Requirements: RISK-01, RISK-02, EXEC-01, EXEC-02 (ROADMAP.md Phase 22, four success criteria; audit refs F-011, F-964, F-966, F-965, F-020, F-019). Depends on Phase 21 (equity, day state, `risk_reservations`).

Out of scope (stays elsewhere): wiring into a running live process, the step cadence and the loop that feeds fills (Phase 24); Telegram UX and money amounts (23); monitoring the liquidation distance of an OPEN position over time and any rule that closes a position because the mark price approaches its liquidation price (not in this phase's criteria; see Deferred); dynamic or volatility-based leverage; automatic margin top-up (`isAutoAddMargin` stays false); Hedge Mode and multi-asset mode support (refused); mainnet attestation (Phases 25 and 26).

Gathered with `--auto`, single pass. Inputs: ROADMAP Phase 22, `22-NOTES.md`, `21-CONTEXT.md`, `21-OWNER-DECISIONS.md`, `21-DEFERRED.md`, DECISIONS D035, D036, D084, `docs/trading/RISK_MANAGEMENT.md` section 9, the recorded Demo captures of 2026-10-22 and 2026-10-23 (`19-OWNER-GAPS.md` sections 2a and 2b). Nothing here edits `docs/DECISIONS.md` or the parameter registry. No number is invented.
</domain>

<decisions>
## Implementation Decisions

All decisions below are the recommended option, or a direction already recorded by the owner (D035, `22-NOTES.md`). They are defaults the owner may override. Every Binance fact (endpoints, field names, error codes, the liquidation formula) is read from the official documentation by the researcher, never taken from this file or from memory (AGENTS.md, Constraints: exchange authority).

### Setting and verifying margin type and leverage (criterion 1, F-011, F-964)
- **D-01:** REST is the truth. Before an approved entry is sent, a guard reads `GET /fapi/v1/symbolConfig` for the symbol. If `marginType` is ISOLATED and `leverage` equals the target, nothing is changed. Otherwise the guard calls `change_margin_type` and then `change_initial_leverage`, and reads `symbolConfig` again; only a read that shows the target lets the plan continue. Any other result is NO_TRADE for that plan. The system never relies on the account default. — **Reversibility:** reversible — one guard and its tests.
- **D-02:** The target leverage is the D035 cap itself (5), held as one named constant of the guard module with the D035 reference. The plan is also refused when the leverage it would need exceeds the cap or the exchange maximum for its notional bracket (D-11). Whether the system may set a lower leverage is OWNER-OPEN O-1; the default is exactly the cap. — **Reversibility:** reversible — a constant and the guard's comparison.
- **D-03:** Both changes are mutating signed calls and follow the project's placement rule (Q5, D080): one call per guard run, never retried, never slept on. An ambiguous result (timeout, unknown error) is resolved with one `symbolConfig` read; if that read does not show the target, the symbol is NO_TRADE and an alert is raised. The adapter methods use the shared REST gate and the error taxonomy like every other signed method; the signed registry grows by the new methods (currently sixteen, `tests/test_binance_usdm_signed_calls.py`). — **Reversibility:** costly — new signed adapter surface and the registry that other tests pin.
- **D-04:** If the symbol has an open position, an open order or an open algo order and its configuration does not already match the target, the guard changes nothing and the plan is NO_TRADE (the exchange also refuses a margin-type change in that state; the researcher confirms the codes from the docs). The system never cancels or closes anything to make room for a configuration change. This also protects a position the owner opened by hand. — **Reversibility:** reversible — a precondition in the guard.
- **D-05:** The verified `marginType` and `leverage` are written to the plan constraint snapshot, so that `PlanConstraintSnapshot` can become COMPLETE together with the Phase 21 equity (G4-039, `22-NOTES.md`). A test builds a COMPLETE snapshot from the recorded Demo `symbolConfig` plus the Phase 21 equity and checks `snapshot_is_valid_for_live`. — **Reversibility:** reversible — fields that already exist and are `None` today.
- **D-06:** The configuration read also checks `isAutoAddMargin` is false; true is NO_TRADE (an automatic top-up would defeat the liquidation guard's input). — **Reversibility:** reversible.

### Position mode and margin mode (criterion 4, F-965, F-020)
- **D-07:** The guard calls the existing position-mode read (`get_position_mode`) and the Phase 21 `accountConfig` read (`multiAssetsMargin`). Hedge Mode (`dualSidePosition` true) and multi-asset mode are NO_TRADE `UNCERTAIN_ACCOUNT_STATE` or a dedicated reason (D-16), never silently accepted. The Change-Position-Mode wording is re-confirmed on the official page before the one-way check relies on it (inherited item G3-001, DECISIONS D044). — **Reversibility:** reversible.

### The liquidation guard (criterion 2, F-964)
- **D-08:** The liquidation price is computed locally before the entry, in a pure module (stdlib and `Decimal` only, no clock, no float), from the symbol's leverage bracket (`GET /fapi/v1/leverageBracket`: notional floor and cap, maintenance margin ratio, cumulative amount, initial leverage), the planned entry price, quantity, side and the verified leverage. The formula comes from the official documentation (isolated margin), is written into the module's docstring with its source, and is checked against a recorded Demo position's `liquidationPrice` where one exists (the position snapshot already carries `liquidation_price`). Hard-coded maintenance margin values or bracket tables never appear in code (criterion 2). — **Reversibility:** costly — a pure module that the guard, the plan check and the tests all call.
- **D-09:** The plan is accepted only if the liquidation price lies beyond the stop-loss by at least the buffer: for a long, `liquidation_price < stop_loss - buffer`; for a short, `liquidation_price > stop_loss + buffer`. At the entry price used (the limit price, the worst case for a resting entry that fills at that price or better). A missing, stale or unparsable bracket, a notional above the top bracket cap, or a leverage above the bracket's initial leverage is NO_TRADE (fail closed). — **Reversibility:** reversible — one predicate.
- **D-10:** The buffer is defined as a fraction of the entry price (a gap or slippage on the stop scales with price, not with the setup's own stop distance). The number is the owner's (O-2). Where it lives is also OWNER-OPEN: the default is a new required key in `config/execution/execution-limits-v1.toml` (`NOT_CONFIGURED`, provenance `DECISION` after the owner sets it), because a hash-locked registry parameter would force a new parameter set, a new `strategy_version` and regenerated research records (D075, D076) while the backtest has no liquidation model. `docs/trading/RISK_MANAGEMENT.md` section 9 says "registry parameter"; the planner records the deviation and the owner's DECISIONS row settles it. No number is chosen from backtest results (RESEARCH_PROTOCOL). — **Reversibility:** costly — moving the buffer into the registry later means a new parameter set and strategy version.
- **D-11:** The brackets are read with a signed GET through the shared gate and kept only for a bounded age (an execution-limits key, `NOT_CONFIGURED`, owner number O-3). Older than the bound, or never read, is NO_TRADE. — **Reversibility:** reversible — a gate predicate and one key.
- **D-12:** After the first fill, the guard compares the exchange `liquidationPrice` of the position with the local one. If the exchange value does not satisfy the D-09 predicate with the same buffer, the plan goes to the existing protection path as an unprotected-exposure case (CLOSE_REQUIRED, reduce-only MARKET close, alert). A difference between the two numbers that still satisfies the predicate is journalled and alerted for calibration only. Whether a failed post-fill check closes the position (default) or only alerts is OWNER-OPEN O-4. — **Reversibility:** reversible — a branch in the coordinator step.

### The available-margin check (criterion 3, F-966)
- **D-13:** The check passes only if the fresh `availableBalance` (same freshness rule as the Phase 21 equity, `account.max_equity_age_ms`) covers: the new order's initial margin (notional divided by the verified leverage), the entry and stop commissions (taker rate on both, D036), the initial margin of approved-but-unplaced plans, and a headroom (a fraction of the margin needed; the number is the owner's, O-3, `NOT_CONFIGURED`). The Binance `availableBalance` already deducts the initial margin of orders resting on the exchange (the researcher confirms this from the docs and the recorded `totalOpenOrderInitialMargin` field), so resting entries are not subtracted a second time; an owner-run Demo case reads `availableBalance` before and after one far resting limit order to prove it (D-18). A source that cannot be read or is stale is NO_TRADE. — **Reversibility:** reversible — a pure predicate and a limit key.
- **D-14:** Approved-but-unplaced plans are counted from the Phase 21 `risk_reservations` rows. The margin each plan will need is stored with the reservation so that the sum is read inside the same approval transaction that takes the day-row lock (`reserve_in`, F-407): two approvals cannot both pass on the same free margin. This needs a new Alembic migration (0012) on the reservation table; the planner chooses the column design. — **Reversibility:** costly — a migration and a persisted schema that Phase 21 code reads.
- **D-15:** The margin check, the liquidation check and the configuration guard run in one fixed order and the first refusal wins, each with its own plain reason code (D-16). Backtest parity: the backtest has no margin or liquidation model, so these checks are live-only gates like the Phase 21 equity age and reservation gate; sizing and quantization are unchanged (AGENTS.md: quantization floors, never rounds up). — **Reversibility:** reversible.

### Vocabulary and evidence
- **D-16:** New plain reason codes (for example for a configuration mismatch, a liquidation too close, insufficient margin, unsupported position or margin mode) are added deliberately: `RejectionReason` is pinned at 21 members by `tests/test_phase21_gate.py` invariant 3, and the GLOSSARY lists the codes, so the plan updates both in the same change. No existing code is reused with a changed meaning. — **Reversibility:** costly — an enum other modules, the gate tests and the glossary pin.
- **D-17:** Nothing here is composed into a running process (Phase 24). The adapter methods, the pure modules and the guard are libraries proven with fakes, local PostgreSQL where the reservation changes, and recorded Demo payloads labelled "demo-observed, not mainnet". Live placement stays disabled (`LIVE_ORDERS_DISABLED`).
- **D-18:** Demo evidence that only the owner can produce is registered as owner-run probe cases (the owner runs every `--execute`): changing the BTCUSDT configuration from x20 CROSSED to ISOLATED x5 and reading it back, the exchange's answer to a margin-type change while an order rests, the answer to a leverage above the bracket maximum, a margin-insufficient entry at the new leverage, and `availableBalance` with and without a resting order. The planner adds the cases to `scripts/demo_probe.py` as opt-in cases in the sj1/sj2 style, with a limits-file key per case; no agent runs one. — **Reversibility:** reversible.
- **D-19:** Everything Demo-observed is labelled "demo-observed, not mainnet" in code comments, docs and tests. No trading parameter is chosen from Demo.

### OWNER-OPEN (record, do not implement with a number)
- **O-1:** Whether the target leverage is exactly the 5x cap (default) or lower, and whether the system may change the leverage and margin type of a symbol on the account the owner also uses by hand (the guard only changes a flat symbol with no orders, D-04).
- **O-2:** The liquidation buffer: its number, its definition (default: fraction of the entry price) and its home (default: an execution-limits key; the alternative is a registry parameter with a new parameter set and strategy version). A DECISIONS row is needed before any number is set, as for D084.
- **O-3:** The numbers of the bracket maximum age (D-11) and of the margin headroom (D-13). Both `NOT_CONFIGURED` until the owner sets them.
- **O-4:** Whether a failed post-fill liquidation check closes the position (default, D-12) or only alerts.

### Claude's Discretion
- Module placement (`src/risk/` for the pure liquidation and margin predicates, `src/execution/` for the guard), the exact names of the new adapter methods and reason codes, the column design and table split of migration 0012, the order of the checks inside the plan check, the fixtures and fakes (reuse `tests/support/`), and the plan and wave split.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Decisions and rules
- `docs/DECISIONS.md` D035 (margin ISOLATED, leverage cap 5x, buffer beyond SL, available margin includes other resting entries), D036 (taker fees on entry and stop exit), D044 (one-way mode wording, G3-001), D075 and D076 (simulator semantics and regeneration of research records), D080 (a placement is never re-sent), D084 (account.max_equity_age_ms 15000 ms)
- `AGENTS.md` — fail closed, Decimal-only, no wall clock in pure modules, `src/core` purity, hash-locked parameter sets, a placement is never re-sent
- `docs/trading/RISK_MANAGEMENT.md` section 8 (equity), section 9 (margin and leverage; the buffer wording), section 11 (quantization)
- `docs/trading/EXECUTION_SPEC.md` (pre-placement checks, section 6.3 fill-driven protection)
- `docs/research/RESEARCH_PROTOCOL.md` (frozen: no parameter chosen from backtest results)
- `docs/GLOSSARY.md` (reason codes; section 14 vocabulary of Phase 21)

### Phase inputs
- `.planning/phases/22-leverage-margin-liquidation-guard/22-NOTES.md` — hand-off from Phase 19
- `.planning/phases/21-account-equity-daily-loss/21-CONTEXT.md`, `21-OWNER-DECISIONS.md`, `21-DEFERRED.md`, `21-VERIFICATION.md` — equity, reservations, the freshness rule
- `.planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md` sections 2a and 2b — Demo facts (x20 CROSSED, -2019, -4164, brackets)
- `.planning/ROADMAP.md` Phase 22 (success criteria, inherited items G3-001 and G4-039)
- `docs/SOURCES.md`, `docs/GLOSSARY.md` — official-documentation sources; the Binance pages for symbolConfig, change margin type, change initial leverage, leverage bracket, position information and account information are read fresh by the researcher

### Recorded Demo payloads
- `.planning/phases/19-execution-plan-binding-price-check/evidence/fixtures/account_read_only_capture-rest-004-symbol_config.json` — x20 CROSSED, `isAutoAddMargin` false
- `.planning/phases/19-execution-plan-binding-price-check/evidence/fixtures/account_read_only_capture-rest-005-leverage_brackets.json` — the BTCUSDT bracket table (demo-observed, not mainnet)
- `.planning/phases/19-execution-plan-binding-price-check/evidence/fixtures/insufficient_margin_order-rest-004-account_information.json` and `-005-symbol_config.json`
- `tests/fixtures/phase21/recorded_demo/` — account information, balance, account config
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BinanceUsdmAdapter.get_position_mode` and `account_config_snapshot` (`src/adapters/binance_usdm.py`): the position-mode and multi-asset reads; the position snapshot already carries `liquidation_price`.
- `BinanceProbeAdapter.symbol_config` and `leverage_brackets` (`src/adapters/binance_probe.py`): read-only probe versions of the two reads this phase needs in the execution adapter.
- `src/execution/constraint_snapshot.py`: `PlanConstraintSnapshot` with `margin_type` and `leverage` fields that are `None` today, `snapshot_is_valid_for_live`.
- Phase 21 modules: `LiveEquitySource` (`src/execution/account_equity.py`, freshness rule), `PgRiskReservationStore.reserve_in` (`src/persistence/risk_reservations.py`, the atomic approval transaction), `make_reserving_save_atomic`, `build_live_risk_inputs`.
- `src/execution/execution_limits.py` and `config/execution/execution-limits-v1.toml`: the owner-number pattern (`NOT_CONFIGURED`, required, provenance `DECISION`); `tests/support/execution_limits.py` for test-only values.
- `src/risk/live_equity.py` and `src/risk/daily_loss.py`: examples of pure, clock-free, Decimal-only live modules and their gate tests (`tests/test_phase21_gate.py`).
- `scripts/demo_probe.py` opt-in cases and `.planning/DEMO-EVIDENCE-PLAN.md` for the owner-run cases.

### Established Patterns
- Live-only gates are pure predicates with the caller supplying `now_utc`; the first refusal returns NO_TRADE with a plain reason code (`UNCERTAIN_ACCOUNT_STATE` for unknown inputs).
- Mutating signed calls: one call, never retried, an ambiguous result is probed once and otherwise held unknown (Q5, D080).
- Limits that only the owner can choose are `NOT_CONFIGURED` keys; setting one needs a DECISIONS row and a coordinated change of the tests that pin it (D084).
- Signed adapter methods are listed in a registry pinned by `tests/test_binance_usdm_signed_calls.py`; the shadow isolation control classifies every public async adapter method (`tests/test_paper_shadow_isolation.py`) — a new read-only method goes into the market-data set, a new mutating method into the spied order surface.

### Integration Points
- The plan check inside `execute_approved_plan` / pre-placement (`src/execution/manager.py`, `src/execution/pre_placement.py`), after Phase 21's equity and reservation and before the GTD entry is sent.
- The reservation table (migration 0011) gains the margin the plan needs (migration 0012).
- The constraint snapshot builder fills `margin_type` and `leverage` (D-05).
- The protection coordinator step for the post-fill liquidation comparison (D-12) and the OPS-05 alert matrix.
</code_context>

<specifics>
## Specific Ideas

- The Demo BTCUSDT bracket table (125x down to 10x and below; first tier maintenance ratio 0.004, cumulative 0) is demo-observed, not mainnet, and is a fixture only; mainnet brackets are read live and may differ.
- The recorded `insufficient_margin_order` case (10 BTC at x20: implied margin about 39285 against 4998 available, error -2019) is the model for the margin-insufficient fixture.
- The owner gave no preference ("run it with --auto, I do not have much knowledge"); every default above is the assistant's recommendation and can be overridden.
</specifics>

<deferred>
## Deferred Ideas

- Monitoring the liquidation distance of an open position over time (mark price versus `liquidationPrice`) and any automatic reduction when it narrows — belongs with the reconcile loop and Phase 24/25; not in the four criteria.
- Dynamic or volatility-scaled leverage — a trading-rule change that needs the research protocol.
- Automatic margin top-up (`isAutoAddMargin`) — contradicts the fixed-risk model.
- Registering the liquidation buffer as a hash-locked registry parameter with a backtest liquidation model — only if the owner chooses it under O-2; it needs a new strategy version and regenerated research records.
- Mainnet attestation of brackets, formulas and the configuration calls — Phases 25 and 26.

### Reviewed Todos (not folded)
None — no pending todo matched this phase's scope.

</deferred>

---

*Phase: 22-Leverage, Margin + Liquidation Guard*
*Context gathered: 2026-10-23*

## Research amendments (2026-10-23, from 22-RESEARCH.md C1..C10)

The decisions above were chosen by the assistant under `--auto`; the research found facts that override ten of
their details. Where this section and a D-xx line differ, THIS section wins. Nothing here sets an owner number.

- A1 (D-13): "availableBalance already nets resting orders" is cited from a support article and an assumed
  mapping, not proven. Hold the basis in one function `free_margin_basis`; count other claims conservatively;
  the D-18 Demo case settles it. Criteria 2 and 3 are not Demo-proven until it runs.
- A2 (D-14): the exchange reading cannot be taken inside the synchronous approval transaction. Migration 0012
  still stores `required_margin` (nullable); the authoritative margin check runs at placement with a fresh async
  reading, summing the other RESERVED rows.
- A3 (D-16): do NOT change the `RejectionReason` enum. Emit the existing `INSUFFICIENT_MARGIN`; add the other
  codes as plain strings in GLOSSARY 9.3 (Phase 19 precedent).
- A4 (D-10/D-11/D-13): limits keys are positive integers only: express buffer and headroom in basis points
  (`..._bps`) and ages in milliseconds (`..._ms`); all start `NOT_CONFIGURED`.
- A5 (D-07): do not call `get_position_mode` per plan (gate 5f already does); take `dualSidePosition` and
  `multiAssetsMargin` from the single `accountConfig` read.
- A6 (D-08): no recorded isolated `liquidationPrice` exists; goldens are the official examples and the Demo
  bracket numbers in RESEARCH 5.1; the maintenance tier is the one containing `Q*LP`, not `Q*EP`.
- A7 (D-15): order is configuration guard, then liquidation, then margin; call site after gate 5f, before gate 5g.
- A8 (D-05): fill margin type, leverage and equity by `dataclasses.replace` on the in-memory snapshot carried by
  `RestingEntry`; the persisted write-once row is not touched.
- A9 (D-03): `ALERT_EVENTS` is pinned; reuse `DIVERGENCE` with a reason code unless the plan updates every pin.
- A10 (D-12): plan the post-fill liquidation comparison as its own isolated plan; an exchange `liquidationPrice`
  of "0" or None is unknown (fail closed). O-4 default unchanged.
