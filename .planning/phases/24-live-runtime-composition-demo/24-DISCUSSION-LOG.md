# Phase 24: Live Runtime Composition + Demo Rehearsal - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-30
**Phase:** 24-live-runtime-composition-demo
**Areas discussed:** process topology; composition root and wiring tests; startup/recovery order; schedulers and cadence; user-data stream routing; Telegram runner; live risk-input producer; DB access on the event loop; health/DEGRADED/enablement; deployment and heartbeat; Demo rehearsal; inherited-item triage

Mode: `--auto`, single pass. No AskUserQuestion was used; the recommended option was chosen for every question (the owner has little domain knowledge and asked the assistant to choose in Phases 21 to 23).

---

## Process topology
| Option | Description | Selected |
|--------|-------------|----------|
| One live process, one asyncio loop, new `src/live/` | Single compose service, all tasks in one loop | ✓ |
| Separate processes per role (bot, executor, schedulers) | More isolation, cross-process state and gate sharing needed | |
| Extend `src/paper/runtime.py` | Reuses code, mixes paper and live credentials | |

**User's choice:** auto — recommended (first) option.

## DB access on the event loop (G4-040)
| Option | Description | Selected |
|--------|-------------|----------|
| `asyncio.to_thread` via one `StoreExecutor` seam | No new dependency | ✓ |
| Async PostgreSQL pool | New dependency, no measured need | |
| Record decision only, leave on loop | Keeps P16R-03 risk | |

**User's choice:** auto — recommended option. Needs owner ratification (O-7).

## Other areas
Each followed the same pattern: the recommended default was taken from prior-phase decisions (Q5/D080, D079, D041, Phase 20 to 23 CONTEXT) and registered owner-open items were left without numbers (CONTEXT `<owner_open>`).

## Claude's Discretion
Package layout, scheduler API, migration split, formatter wording, smoke-script parameters.

## Deferred Ideas
Direct `/private` transport, failure campaign (Phase 25), enablement gate and canary (Phase 26), USDC (Phase 27), async pool, local-time display.
