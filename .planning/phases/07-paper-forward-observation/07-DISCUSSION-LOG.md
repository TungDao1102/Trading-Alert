# Phase 7: Paper Forward Observation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-26
**Phase:** 7-Paper Forward Observation
**Areas discussed:** Realtime ingestion + reconnect/resync + warm-up + gap journaling, Engine reuse + backtest parity, Three-way attribution + paper journal storage, No-tuning freeze proof, Run scope + Telegram SIMULATE boundary + soak operations

---

## Realtime ingestion + reconnect/resync + warm-up + gap journaling

| Option | Description | Selected |
|--------|-------------|----------|
| SDK WS behind adapters, REST resync, journaled gaps, fail-closed | WS Streams via official SDK behind src/adapters; REST kline resync on reconnect; Phase-4 warm-up flags; gaps journaled, never fabricated; stale feed → NO_TRADE | ✓ |
| Direct WS with in-loop synthesis | Faster to build; synthesizes missing candles in-loop | |

**User's choice:** SDK WS behind adapters, REST resync, journaled gaps, fail-closed (recommended default, auto-selected via --auto)
**Notes:** Follows Phase-2 D-09 / Phase-4 D-04 flag-never-fabricate precedent and Phase-5 D-04 fail-closed posture. No interactive prompts (--auto mode).

---

## Engine reuse + backtest parity

| Option | Description | Selected |
|--------|-------------|----------|
| Identical engine calls with divergence gate | Paper calls src/core + src/risk + backtest fill/cost semantics identically; paper-vs-backtest divergence on overlap is an acceptance gate | ✓ |
| Paper-local simplified engine | Separate lightweight paper engine, reconciled later | |

**User's choice:** Identical engine calls with divergence gate (recommended default, auto-selected via --auto)
**Notes:** IMPLEMENTATION_PLAN Phase-2 exit gate (no material divergence) becomes a CI/gate check; divergence fixed in engine, never at call site. No interactive prompts (--auto mode).

---

## Three-way attribution + paper journal storage

| Option | Description | Selected |
|--------|-------------|----------|
| Three-way attribution, PG rows + Parquet mirror | System vs simulated-execution vs opportunity with full timestamp lineage; PG operational rows on seven-entity shapes + Parquet extracts | ✓ |
| Log-file-only paper journal | Append-only logs, structured later | |

**User's choice:** Three-way attribution, PG rows + Parquet mirror (recommended default, auto-selected via --auto)
**Notes:** Skipped/expired plans retained with reason codes (opportunity leg); identity on every record; single-Base ORM + parity-gate discipline for any migration. No interactive prompts (--auto mode).

---

## No-tuning freeze proof

| Option | Description | Selected |
|--------|-------------|----------|
| Pinned registry + diff-proof monitor, per-epoch evidence | Stream pins parameterSetId+hash at start; diff monitor proves zero tuning; mid-soak change opens a new epoch, never rewrites old evidence | ✓ |
| Convention-based no-tuning discipline | Team agreement not to touch the running set | |

**User's choice:** Pinned registry + diff-proof monitor, per-epoch evidence (recommended default, auto-selected via --auto)
**Notes:** Builds on the 07.1 assemble()-time binding gate; PAPER-03 acceptance artifact is the diff log. No interactive prompts (--auto mode).

---

## Run scope + Telegram SIMULATE boundary + soak operations

| Option | Description | Selected |
|--------|-------------|----------|
| Live-5, 4H/1H, SIMULATE-notify only, hardening in Phase 8 | Live-5 universe, 4H regime + 1H setup, 1m for fill resolution only; Telegram SIMULATE read-only; APPROVE/SKIP idempotency deferred to Phase 8; 3–6 mo soak with signal-frequency evidence gate | ✓ |
| Full approval loop now | Build idempotent APPROVE/SKIP inside Phase 7 | |

**User's choice:** Live-5, 4H/1H, SIMULATE-notify only, hardening in Phase 8 (recommended default, auto-selected via --auto)
**Notes:** Phase-8 construction may overlap the soak; enablement gates on paper evidence per ROADMAP. No interactive prompts (--auto mode).

---

## Agent's Discretion

Module layout inside the paper loop package, WS client structure, journal field choices, Parquet extract layout, soak-monitor mechanics, SIMULATE formatting, epoch-rollover mechanics, and plan slicing — all at planner/researcher discretion within D-01–D-05.

## Deferred Ideas

- Telegram APPROVE/SKIP idempotency hardening + reconciliation/orphan-sweeper/SAFE_MODE rehearsal → Phase 8.
- Live Algo exits + placement-time revalidation → Phase 9.
- Journal depth (MFE/MAE, latencies, approval-delay impact) + kill-gate operations → Phase 10.
- REFN-01/02/03/04/05 (15M refinement, OI/funding features, correlation model, extra families) → v2.
