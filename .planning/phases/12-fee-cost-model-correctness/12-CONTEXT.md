# Phase 12: Fee + Cost Model Correctness - Context

**Gathered:** 2026-09-30
**Status:** Ready for planning
**Mode:** `--auto` (Claude chose the recommended option for every gray area; each choice is logged in 12-DISCUSSION-LOG.md and can be overridden before planning)

<domain>
## Phase Boundary

Make backtest, paper and live size and book trades with every cost term in **quote currency per unit of base**, so a stop-loss exit never loses more than `allowed_risk` (= equity × risk_rate) plus bounded slippage. Live sizing uses the account's real commission rate, never zero.

Delivers: the corrected cost-per-unit producer and sizing math, corrected slippage in simulated PnL, a minimum stop distance and a cost-to-risk ceiling that yield NO_TRADE, the live `commissionRate` read, new versioned parameter sets, deliberately regenerated fixtures/hashes with a DECISIONS entry, and the SL-loss property test.

Out of scope (owned elsewhere): simulator causality, mark-price triggers, funding modeling (Phase 14); user-data stream and adapter hardening (Phase 18); live runtime wiring (Phase 24); quote-asset generalization (Phase 27). The 0.0005 entry fee stays a parameter until this phase reads the account rate (D044 follow-up 8).

Requirements: RISK-01, BKTS-01, DOMN-02. Audit refs: F-001, F-801, F-601, F-306, F-002, F-962, F-005, F-028, F-031, F-608.
</domain>

<decisions>
## Implementation Decisions

### Cost-per-unit formula and sizing (F-001, F-801, F-962)
- **D-01:** `modeled_costs_per_unit` becomes price-aware. It takes the entry reference price, the stop price, the side and the cost model, and returns **quote per unit of base**:
  `entry_ref × (fee_rate_entry + entry_slippage_rate) + stop_price × (fee_rate_exit + exit_slippage_rate)`.
  Entry is a taker fill (D036), so the entry slippage term is included; this is stricter than the roadmap sketch and is the conservative reading of F-962. Fix the docstring, which currently claims quote currency while returning a rate sum. Its unit must scale linearly with price (contract test, F-801). — **Reversibility:** costly — sizing, gating, backtest, paper and execution all consume the producer.
- **D-02:** `size_position` keeps `risk_per_unit = sl_distance + modeled_costs_per_unit`; the fix is in the producer and its callers (`src/backtest/simulator.py:803`, `src/paper/loop.py:504`, `src/risk/gating.py`), not in a second formula. The same function is called in backtest, paper and live (Phase 5 D-02 parity).
- **D-03:** Use the **adverse edge of the entry zone** (LONG: `entry_max`; SHORT: `entry_min`) for the entry price and the SL distance, replacing the zone-mid `entry_ref` of Phase 5 D-02. Reason: the roadmap invariant "loss at SL ≤ risk budget" must hold for a fill anywhere in the zone, and zone-mid under-sizes when the fill lands on the adverse edge. The planner must confirm this against `src/risk/gating.py` and the quantizer's `reference_price`, and record the supersession of the zone-mid rule in DECISIONS. — **Reversibility:** one-way — changes every sized quantity and every golden fixture; the DECISIONS entry pins it.
- **D-04:** All fee and slippage rates are decimal fractions. The loader rejects any fee or slippage rate above `0.01` as a unit error (F-028). The protocol wording that says "basis points" cannot be edited in place (v1.1.0 is frozen); if it needs a bump, record it as a follow-up.

### Slippage model (F-306)
- **D-05:** Simulated PnL books slippage per leg as `fill_price × quantity × rate` (currently `quantity × rate`, which is 60,000× too small on BTC). Entry uses `expected_slippage`; the stop exit uses a **separate `exit_slippage_rate`** because a stop-market fills worse than a limit. Take-profit exits use `expected_slippage`. — **Reversibility:** costly — changes realized PnL in every trade record and the experiment hash inputs.
- **D-06:** New parameter `exit_slippage_rate`, baseline **0.0003 (3 bps)**, within the audit's 2–5 bps range for stop exits. The planner checks that value against the protocol's stress convention before freezing it, and never tunes it after seeing results.

### Guards: minimum stop distance and cost-to-risk ceiling (F-002)
- **D-07:** Two registry parameters, both risk gates that produce NO_TRADE before quantization:
  - `min_stop_distance_rate` (SL distance ÷ entry ref), baseline **0.003 (0.3%)**;
  - `max_cost_to_risk` (round-trip modeled cost ÷ `risk_per_unit`), baseline **0.15** (audit F-002 research baseline).
  The computed ratio is recorded on the sizing result.
- **D-08:** Two new canonical rejection codes, `STOP_TOO_TIGHT` and `COST_TO_RISK_EXCEEDED`, added to GLOSSARY §9 first (D016: GLOSSARY is the enum source), then to `RejectionReason` and the rejection-code tests. No synonym of an existing code. Phase 11 already reserved `INSUFFICIENT_MARGIN`; do not touch it.
- **D-09:** D044 follow-up 1 lands here: remove the five deprecated `RejectionReason` aliases and update `tests/test_domain_enums.py` in the same change as D-08, so the enum has one edit window.

### Live commission rate (F-962, F-031)
- **D-10:** Live reads `GET /fapi/v1/commissionRate` per symbol through the adapter layer (SDK models never leak). Sizing uses `max(parameter_rate, account_rate)` **per side** (entry uses taker per D036, stop exit uses taker). The BNB discount is ignored in sizing (F-031).
- **D-11:** If the account rate is unavailable, stale beyond a TTL, or malformed, live entries **fail closed** (NO_TRADE with the existing account-state-uncertain reason). It never falls back to zero, and it does not silently fall back to the parameter rate either: the parameter rate is a floor, not a substitute for an unknown account state. The TTL is a registry parameter; the planner picks a baseline (suggest 1 hour) and documents it.
- **D-12:** Backtest and paper keep the **versioned parameter fees** so runs are reproducible from the parameter-set hash. Only live substitutes the account rate. The rates actually used, and their source (`PARAMETER` vs `ACCOUNT_MAX`), are recorded on the sizing result and journal input (not on the frozen Phase-4 `TradePlan`, to avoid changing plan identity).
- **D-13:** Exact endpoint path, weight, response fields and demo/testnet behavior are re-verified against current official Binance docs before implementation (AGENTS.md exchange-authority rule); the researcher records the source URL and fetch date in `docs/SOURCES.md`. This phase adds the adapter method plus fixture-driven tests only. Runtime wiring (scheduler, cache refresh loop) belongs to Phase 24.

### Parameter sets, hashes, fixtures (F-608, D044 follow-up 2)
- **D-14:** Never edit an existing `params/**/*.toml` (F-810). Create the next versioned sets (`baseline-v5` for the three families, plus matching no-trade and simple-trend successors) carrying `exit_slippage_rate`, `min_stop_distance_rate`, `max_cost_to_risk` and the commission TTL, with headers naming what they supersede. Old sets stay byte-identical and hash-locked. If extending `COST_KEYS` would change old sets' hashes or make old sets unloadable, the loader treats the new keys as required only for the new strategy_version, and the planner records the decision.
- **D-15:** Fix the hash-spelling trap (`partial_fill_fraction` `1` vs `1.0` hashing differently, D044 follow-up 2): canonicalize numeric cost values to a single Decimal string form before hashing. This changes cost hashes, so it gets its own DECISIONS entry and is done in the same window as the deliberate regeneration below, never silently.
- **D-16:** Golden fixtures and experiment hashes are regenerated **deliberately**: one DECISIONS entry lists every fixture and hash that moved and why (F-608). Phase-5 fixtures stop using hand-typed cost values (`"1.0"`/`"0.0"`) and instead feed values produced by the corrected producer, with expected outputs hand-derived in a comment or sidecar file rather than emitted by the code under test.

### Verification (F-601)
- **D-17:** Property test (explicit Decimal grid; the planner checks whether `hypothesis` is already a dev dependency and does not add one without cause): across prices (BTC ~60,000, ETH ~3,000, XRP ~0.5), stop widths (0.3%–3%), both sides and fill positions across the entry zone, the simulated SL-exit loss including fees and slippage is `<= allowed_risk` plus a stated Decimal tolerance. Includes the low-price XRP case.
- **D-18:** Hand-computed oracle tests for the producer and for `_apply_costs` at a fixed BTC and a fixed XRP case, so the property test is not the only guard. A contract test asserts linear price scaling. The test that recomputes the same buggy formula (`tests/test_backtest_simulator.py` Test 11) is replaced, not kept.
- **D-19:** Parity: backtest, paper and the risk pipeline call one shared producer; a test asserts identical output for identical inputs across the three call sites.

### Claude's Discretion
- File and function names for the new guard module, provided guards run inside the existing `evaluate_risk` pipeline before quantization.
- Exact baseline value for the commission TTL, subject to D-11.
- Whether the property test is one module or split by unit/integration.
- Test fixture folder layout for the regenerated goldens.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authority and decisions
- `docs/DECISIONS.md` — D031 (authority), D036 (taker entry), D037 (mark-price triggers, context only), D038 (partial-fill sensitivity), D043/D044 (Phase 11 follow-ups 1, 2, 8)
- `AGENTS.md` — Decimal-only rule, quantization order, fail-closed, determinism
- `.planning/ROADMAP.md` §"Phase 12" — goal and 4 success criteria
- `.planning/REQUIREMENTS.md` — RISK-01, BKTS-01, DOMN-02
- `.planning/phases/11-decision-alignment/11-CONTEXT.md` — D-06, D-07 (param-set versioning), D-15 (GLOSSARY as enum source)

### Audit
- `.planning/audits/2026-09-29-deep-audit/DEEP_AUDIT_REPORT.md` and `findings.json` — F-001, F-801, F-601, F-306, F-002, F-962, F-005, F-028, F-031, F-608

### Docs to amend
- `docs/trading/RISK_MANAGEMENT.md` §2 (sizing formula), §3 (costs), §11 (quantization canonical statement)
- `docs/GLOSSARY.md` §9 — canonical rejection codes (add `STOP_TOO_TIGHT`, `COST_TO_RISK_EXCEEDED`; remove deprecated aliases)
- `docs/configuration/CONFIGURATION.md` — new registry parameters
- `docs/research/RESEARCH_PROTOCOL.md` (v1.1.0 FROZEN) — read-only; the fee-unit wording (F-028) may need a follow-up instead of an in-place edit
- `docs/SOURCES.md` — record the `commissionRate` source URL and fetch date
- Binance integration doc under `docs/integration/` — commission endpoint (planner locates the path)

### Code
- `src/backtest/costs.py` — `CostModel`, `COST_KEYS`, `build_cost_model`, `modeled_costs_per_unit` (line ~184)
- `src/backtest/simulator.py` — `_apply_costs` (line ~625), risk call site (line ~803)
- `src/paper/loop.py` — risk call site (line ~504)
- `src/risk/sizing.py`, `src/risk/gating.py`, `src/risk/types.py` — `size_position`, `evaluate_risk`, `SizedResult`
- `src/domain/registry.py` — parameter validation, cost-key hash normalization
- `src/domain/enums.py` — `RejectionReason`
- `src/execution/manager.py` (line ~322) — consumer of the cost value
- `params/trend-pullback/baseline-v4.toml` and siblings — current cost keys and comments
- `tests/test_backtest_simulator.py`, `tests/test_domain_enums.py`, `tests/test_registry.py`, `tests/fixtures/phase5/`, `tests/fixtures/phase6/` — tests and fixtures affected
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/core/_decimal.py` (`_add/_sub/_mul/_div`): pinned prec-28 helpers; use for all new math.
- `CostModel.__post_init__` hash verification (CR-09): the model for how new cost keys must be hashed and verified.
- `evaluate_risk` pipeline (size → quantize → portfolio): the single place to add the two guards so all modes share them.

### Established Patterns
- Frozen artifacts are versioned, never edited in place (params, protocol).
- Enum values come from GLOSSARY first (D016).
- Adapters isolate SDK models; tests use recorded fixtures, never live endpoints.

### Integration Points
- Three call sites of `modeled_costs_per_unit` (simulator, paper loop, risk gating) plus `src/execution/manager.py`.
- `_apply_costs` feeds `TradeRecord` fields that flow into `ExperimentRecord` hashes.
- Phase 14 rewrites the simulator; keep this phase's simulator edits minimal and localized to cost math so they merge cleanly.
</code_context>

<specifics>
## Specific Ideas

- Audit worked example: at $800 equity and 0.5% risk ($4.00), a 0.5% SL currently loses about $4.64 (1.16×), a 0.3% SL about $5.07 (1.27×), up to 1.4× with a taker entry. The property test must fail on the old code and pass on the new.
- BTC ~60,000 shows the slippage error at 60,000× and XRP at ~0.5 shows it the wrong way (2× too large); use both as oracle cases.
</specifics>

<deferred>
## Deferred Ideas

- Funding cost in sizing and PnL: Phase 14 (F-905, F-021).
- Mark-price trigger evaluation and causal fills: Phases 13–14.
- Commission cache refresh loop and scheduler wiring: Phase 24.
- Generalizing the quote asset and USDC fee tiers: Phase 27.
- Protocol wording change from "basis points" to "decimal fraction" if it needs a v1.2.0 bump: follow-up, not an in-place edit of v1.1.0.

None of the pending todos matched this phase.
</deferred>

---

*Phase: 12-Fee + Cost Model Correctness*
*Context gathered: 2026-09-30*
