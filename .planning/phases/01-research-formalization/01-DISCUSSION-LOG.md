# Phase 1: Research Formalization - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-19
**Phase:** 1-Research Formalization
**Areas discussed:** Protocol artifact shape, Family specification format, Contradiction-resolution mechanics, Gate enforcement mechanism

---

## Protocol artifact shape

| Option | Description | Selected |
|--------|-------------|----------|
| New canonical doc docs/research/RESEARCH_PROTOCOL.md | Versioned, freezable protocol stating splits, cost model, execution assumptions, gates | ✓ |
| Section inside TRADING_STRATEGY_RESEARCH.md | Living doc, cannot be frozen | |
| .planning-only artifact | Does not outlive planning | |

**User's choice:** New canonical doc docs/research/RESEARCH_PROTOCOL.md ([auto] recommended default)
**Notes:** --auto mode; no interactive prompt used. Living research doc and planning-local artifacts rejected for freezability/longevity reasons.

---

## Family specification format

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed 7-slot template per concept + per-family sheet | Informal → machine-detectable → alternatives → bias → parameters → backtest; mutually comparable | ✓ |
| Freeform prose per family | Incomparable across families | |

**User's choice:** Fixed 7-slot template per concept + per-family sheet ([auto] recommended default)
**Notes:** --auto mode; no interactive prompt used.

---

## Contradiction-resolution mechanics

| Option | Description | Selected |
|--------|-------------|----------|
| Direct canonical-doc edits + DECISIONS.md row each + DOC_STATUS bump | Batched in a single Phase-1 plan; satisfies RSCH-03 explicit-resolution requirement | ✓ |
| Leave docs untouched, note in CONTEXT only | Fails RSCH-03 success criterion | |

**User's choice:** Direct canonical-doc edits + DECISIONS.md row each + DOC_STATUS bump ([auto] recommended default)
**Notes:** --auto mode; no interactive prompt used. Covers C1–C7.

---

## Gate enforcement mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Registry loader + CI check that fails closed | Runs without registered parameterSetId+parameterSetHash rejected by gate | ✓ |
| Convention and documentation only | Fails the "rejected by gate, not by convention" criterion | |

**User's choice:** Registry loader + CI check that fails closed ([auto] recommended default)
**Notes:** --auto mode; no interactive prompt used.

---

## the agent's Discretion

- Exact section layout inside RESEARCH_PROTOCOL.md and per-family sheet cosmetics.
- Plan slicing within the phase (fine granularity).

## Deferred Ideas

None — discussion stayed within phase scope.
