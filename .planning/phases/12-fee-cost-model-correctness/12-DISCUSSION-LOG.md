# Phase 12: Fee + Cost Model Correctness - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-30
**Phase:** 12-fee-cost-model-correctness
**Areas discussed:** Cost formula and sizing, Slippage model, Stop/cost guards, Live commission rate, Params/hashes/fixtures, Verification
**Mode:** --auto (recommended option selected for every question)

---

## Cost formula and sizing

| Option | Description | Selected |
|--------|-------------|----------|
| Price-aware producer | Entry + exit legs incl. entry slippage, adverse zone edge | ✓ |
| Roadmap sketch only | Zone-mid, no entry slippage | |
| Keep rate sum | Convert to quote inside `size_position` | |

[auto] Cost formula — Q: "Which entry reference and cost legs?" → Selected: adverse edge, both legs with slippage (recommended: makes the SL-loss invariant hold anywhere in the zone).

## Slippage model

| Option | Description | Selected |
|--------|-------------|----------|
| Separate stop rate | price × qty × rate; exit_slippage_rate 3 bps | ✓ |
| Single rate | One slippage rate for all legs | |

[auto] Slippage — Q: "One rate or separate stop rate?" → Selected: separate `exit_slippage_rate` 0.0003.

## Stop/cost guards

| Option | Description | Selected |
|--------|-------------|----------|
| Two new canonical codes | min_stop_distance_rate 0.3% + max_cost_to_risk 0.15 | ✓ |
| Reuse EXCHANGE_CONSTRAINT | Synonym of an existing code | |
| Ceiling only | No minimum stop distance | |

[auto] Guards — Q: "Which rejection codes?" → Selected: new canonical codes via GLOSSARY first (D016); deprecated alias cleanup folded in.

## Live commission rate

| Option | Description | Selected |
|--------|-------------|----------|
| max(param, account), fail closed | Per side; unavailable → NO_TRADE | ✓ |
| Fall back to parameter rate | When account rate unavailable | |
| Account rate only | Ignore parameter floor | |

[auto] Commission — Q: "Behavior when the rate is unavailable?" → Selected: fail closed, never zero.

## Params, hashes, fixtures

| Option | Description | Selected |
|--------|-------------|----------|
| New v5 sets | Canonical Decimal hashing, deliberate regen + DECISIONS entry | ✓ |
| Edit v4 in place | Violates F-810 | |

[auto] Params — Q: "How to add new cost keys?" → Selected: new versioned sets, old sets byte-identical.

## Verification

| Option | Description | Selected |
|--------|-------------|----------|
| Property grid + oracles + parity | BTC/ETH/XRP, hand-derived expected values | ✓ |
| Property test only | | |

[auto] Verification — Q: "Test oracle?" → Selected: property + hand-computed oracles.

## Claude's Discretion

Guard module naming, commission TTL baseline (~1 h), test layout.

## Deferred Ideas

Funding in sizing (Phase 14); commission refresh loop (Phase 24); USDC fees (Phase 27); protocol "basis points" wording follow-up.
