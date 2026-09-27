# Phase 8: Approval + Reconciliation Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-27
**Phase:** 8-Approval + Reconciliation Hardening
**Areas discussed:** Approval binding + replay, Callback intake, Reconciliation + orphan sweeper + SAFE_MODE, Deterministic order IDs, RUNBOOK rehearsal

---

## Approval binding + replay

| Option | Description | Selected |
|--------|-------------|----------|
| Full identity binding | SignalId + version + plan hash + expiry + chat + one-time token; replay resolves to existing approval | ✓ |
| Chat-only approval | Any APPROVE from authorized chat acts on latest plan | |

**User's choice:** Full identity binding, replay resolves to existing approval ([auto] recommended default, no interactive prompt)
**Notes:** Extends Phase-7 D-05 no-auto-approve posture to the approval path; WR-07 coherence already on the entity.

---

## Callback intake

| Option | Description | Selected |
|--------|-------------|----------|
| PTB polling behind adapters | Application polling, authorized-chat gate first, short→full mapping, journaled receipts | ✓ |
| FastAPI webhook receiver | Inbound HTTP endpoint for Telegram callbacks | |

**User's choice:** PTB polling behind adapters ([auto] recommended default, no interactive prompt)
**Notes:** Keeps V1 inbound surface at zero; FastAPI stays webhook/health edge only. Webhook deferred to a measured need.

---

## Reconciliation + orphan sweeper + SAFE_MODE

| Option | Description | Selected |
|--------|-------------|----------|
| Three-source compare | Normal + algo + positions truth; cancel-only sweep; SAFE_MODE on divergence | ✓ |
| Local-state-only check | Verify local rows without exchange truth | |

**User's choice:** Three-source compare, cancel-only sweep, SAFE_MODE on divergence ([auto] recommended default, no interactive prompt)
**Notes:** Reconciler never places orders; injected-orphan/divergence drill is the acceptance proof.

---

## Deterministic order IDs

| Option | Description | Selected |
|--------|-------------|----------|
| Plan-hash + role derived | Same plan + role → same ID; exchange dedups across retry/restart/replay | ✓ |
| Random UUID per attempt | Fresh ID per send with local dedup table | |

**User's choice:** Plan-hash + role derived IDs ([auto] recommended default, no interactive prompt)
**Notes:** Exact scheme at planner discretion; fits DATA_MODEL §2.7 three-identifier fields.

---

## RUNBOOK rehearsal

| Option | Description | Selected |
|--------|-------------|----------|
| Full rehearsal, injected faults | All eight drills rehearsed with simulated faults; journaled drill log | ✓ |
| Paper-only walkthrough | Read-through of drill steps without execution | |

**User's choice:** Full rehearsal, injected faults, journaled drill log ([auto] recommended default, no interactive prompt)
**Notes:** Never real unprotected exposure; drill log is the OPS-01 acceptance artifact.

---

## Agent's Discretion

All five areas auto-resolved to recommended defaults under `--auto` (no user prompts). Module layout, mapping storage, reconciler cadence, ID scheme details, drill-harness mechanics, and plan slicing left to planner/researcher discretion.

## Deferred Ideas

- FastAPI inbound webhook receiver for Telegram callbacks — deferred (V1 uses PTB polling).
- Phase 9 (live Algo exits, placement revalidation), Phase 10 (journal depth, kill-gate) — out of scope per roadmap.
- v2 items (REFN-01–05) — not Phase 8.
