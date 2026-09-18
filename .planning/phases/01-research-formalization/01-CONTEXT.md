# Phase 1: Research Formalization - Context

**Gathered:** 2026-09-19
**Status:** Ready for planning

## Phase Boundary

Phase 1 delivers a frozen, auditable research contract: a versioned frozen protocol document, three independently specified candidate strategy families, and all seven known Core Docs v0.3 contradictions (C1–C7) resolved as explicit recorded decisions. No parameter work, no backtests, no code — this phase produces documents and gates only. Success means a researcher can read the frozen protocol and acceptance gates before any parameter run exists, and any parameter run attempted without a frozen protocol plus registered parameter set is rejected by gate, not by convention.

## Implementation Decisions

### Protocol artifact

- **D-01:** The frozen research protocol lives in a new canonical doc `docs/research/RESEARCH_PROTOCOL.md` — versioned and freezable, stating dataset splits, cost model, execution assumptions, and acceptance gates.
- **D-02:** It is NOT a section inside `TRADING_STRATEGY_RESEARCH.md` (a living document cannot be frozen) and NOT a `.planning`-only artifact (the contract must outlive planning).

### Family specification format

- **D-03:** Each of the three families (Trend Pullback, Breakout+Retest, Range Mean-Reversion) is specified with a fixed 7-slot template per concept: informal definition → machine-detectable definition → alternative definitions → advantages/disadvantages → look-ahead-bias analysis → testable parameters → backtest path — plus one per-family sheet (hypothesis, timeframe mapping, variants).
- **D-04:** Freeform prose specs are rejected: family specs must be mutually comparable under the same framework.

### Contradiction resolution

- **D-05:** C1–C7 are resolved by direct canonical-doc edits (preserving each doc's purpose) plus one `DECISIONS.md` row per contradiction plus a `DOC_STATUS.md` bump, batched in a single Phase-1 plan — not by leaving docs untouched.
- **D-06:** Per documentation authority (DECISIONS.md > product scope > engineering principles > GLOSSARY > frozen SPEC > supporting specs > research notes); `TRADING_STRATEGY_SPEC.md` stays TBD wherever research has not produced a validated rule.

### Gate enforcement

- **D-07:** "Rejected by gate, not by convention" means a registry loader plus CI check: any run without a registered `parameterSetId` + `parameterSetHash` fails closed. Convention/documentation-only enforcement is explicitly rejected.
- **D-08:** Strategy V1 family selection stays TBD (D012) — no phase output may declare a winner without backtest plus out-of-sample evidence.

### the agent's Discretion

- Exact section layout inside `RESEARCH_PROTOCOL.md` and the per-family sheet cosmetics are at the planner/researcher discretion, provided the D-01/D-03 content requirements are met.
- Plan slicing within the phase (fine granularity) is at the planner's discretion.

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Research contract

- `docs/research/TRADING_STRATEGY_RESEARCH.md` — living research draft v0.1; candidate families A/B/C, Q1–Q12, backlog P0–P2, anti-overfitting rules, stop conditions (source material to formalize, NOT the frozen protocol)
- `docs/strategy/TRADING_STRATEGY_SPEC.md` — TEMPLATE/NOT FROZEN; defines the slot structure the family specs must eventually fill; must stay TBD where unvalidated

### Decision recording

- `docs/DECISIONS.md` — decision log D001–D021; receives one row per resolved contradiction C1–C7
- `docs/DOC_STATUS.md` — doc status index; bumped when contradictions are resolved
- `docs/GLOSSARY.md` — canonical enums and terminology; authority for C2/C3/C5/C7 resolutions

### Methodology

- `docs/backtest/BACKTEST_SPEC.md` — acceptance gates and dataset-split discipline the frozen protocol must encode
- `docs/configuration/CONFIGURATION.md` — parameter-set identity (parameterSetId + parameterSetHash) the gate enforces

### Project context

- `.planning/PROJECT.md` — project context, constraints, key decisions
- `.planning/REQUIREMENTS.md` — RSCH-01, RSCH-02, RSCH-03
- `.planning/ROADMAP.md` — Phase 1 goal and success criteria
- `.planning/research/SUMMARY.md` — research synthesis and roadmap implications

## Existing Code Insights

### Reusable Assets

- None — greenfield code. The `docs/` corpus (28 files, Core Docs v0.3) is the working material, not code to reuse.

### Established Patterns

- Research → Strategy Spec → Code separation (`docs/implementation/AGENT_INSTRUCTIONS.md`): missing rules stay TBD and become research tasks; agents must not invent production behavior.

### Integration Points

- Phase 2 (Data Foundation) consumes the frozen protocol's dataset requirements; Phase 3 (Domain + Registry + Fixtures) implements the registry the D-07 gate specifies; Phase 6 (Backtest) executes under the frozen protocol.

## Specific Ideas

- Contradiction backlog for reference: C1 SystemMode naming (`LIVE_AUTONOMOUS` vs `LIVE_AUTONOMOUS_DISABLED`, missing `SAFE_MODE`), C2 `SIGNAL_AND_ALERTS.md` §4 execution states inside signal states, C3 `EXECUTION_SPEC.md` §3 `APPROVED` vs `GLOSSARY.md` OrderStatus, C4 `Asia/Bangkok` vs `Asia/Ho_Chi_Minh`, C5 research §12 non-canonical status names, C6 duplicate/gapped section numbers, C7 `SignalStatus.APPROVED` vs `TradePlanStatus.APPROVED` ownership.

## Deferred Ideas

None — discussion stayed within phase scope.

---

*Phase: 1-Research Formalization*
*Context gathered: 2026-09-19*
