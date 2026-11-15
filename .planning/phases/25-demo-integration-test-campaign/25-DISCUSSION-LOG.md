# Phase 25: Binance Demo Integration Test Campaign - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-11-07
**Phase:** 25-demo-integration-test-campaign
**Areas discussed:** who runs Demo steps, suite shape, same code path as live, soak registration, Demo-vs-mainnet document, inherited gating items, owner decisions (all auto-selected, `--auto`)

---

## Who runs what
[auto] Demo/signed-request steps are owner-only (AGENTS.md) -> Selected: agents write and dry-run against fakes; owner runs `pytest -m demo`, `--execute`, soak. Alternative not taken: agents run Demo scenarios (violates AGENTS.md).

## Suite shape
[auto] new `demo` marker excluded from default/CI, reuse Phase 24 harness and fake exchange, one scenario per ROADMAP bullet plus G2-016 drills and P20-DEMO items, each with a CI twin on fakes. Alternative not taken: a separate scenario framework.

## Same code path as live
[auto] no Demo-only branch in execution/live/risk, guarded by a test; DEGRADED Demo runs never count as readiness evidence (D056).

## Soak
[auto] pre-registered, hashed registration file before the first order (>= 21 days, live-5, pass criteria, restart rule); reuse existing soak tooling; reduce health-tick journal volume (R-25) first.

## Demo-vs-mainnet differences
[auto] single document `docs/operations/DEMO_VS_MAINNET.md` with evidence labels; fill 09-EXCHANGE-FACTS Demo cross-check lines.

## Inherited gating items
[auto] R-24 and R-25 done in this phase; R-23, R-28 deferred.

## Claude's Discretion
Scenario file layout, evidence JSON field names within the Phase 24 shape, wave split, plan count.

## Deferred Ideas
Mainnet CANARY (Phase 26); async rewrite of OperatorCommands DB work (R-23); strategy changes from Demo results (out of scope).

## Not decided (OWNER)
R-21 margin reservation stamping (needs a DECISIONS row), R-22 cancel-on-stop (touches D079), P20-ERR1003 error -1003 text parsing (needs a D-10 exception), scenario dates and soak start date.
