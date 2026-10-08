# Phase 16: Paper Runtime Composition + SHADOW Approval Mode - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-07
**Phase:** 16-paper-runtime-composition
**Mode:** --auto, single pass, with the owner's rule that an agent never auto-picks money or safety decisions
**Areas discussed:** Locked inputs (D061 and others), Runtime composition, WS adapter fix, SHADOW mode and simulated fills, Decision-surface parity, Freeze check and evidence, Research runner, Kill-gate guard, Soak-host deployment, Open user decisions

[auto] Selected all gray areas: the ten areas above.
Only IMPLEMENTATION style choices were auto-selected (recommended option). Every item D061, STATE or ROADMAP lists as open for the user is recorded in CONTEXT.md under "Open user decisions (NOT decided by auto mode)" with no selection.

---

## Runtime composition

| Option | Description | Selected |
|--------|-------------|----------|
| New `src/paper/runtime.py` composition root with incremental state around the stateless `run_paper_tick` | Keeps tick semantics and parity fixtures unchanged | ✓ |
| Rewrite `run_paper_tick` as a stateful engine | Cleaner state but changes the digest contract used by parity tests | |
| Script outside `src/` | Faster, but not testable under mypy strict or reusable by Phase 24 | |

[auto] Runtime composition — Q: "Where does the process live and who owns state?" → Selected: "runtime.py plus Phase 17 PG stores" (recommended default)
**Notes:** State persistence reuses `PgJournalStore`, approvals and `system_state_events`; no new persistence mechanism.

---

## WS adapter fix

| Option | Description | Selected |
|--------|-------------|----------|
| Async adapter methods, plain string interval, SDK PROD `stream_url`, SDK-signature-bound fakes | Matches the 2026-10-04 probe findings | ✓ |
| Keep sync wrapper and run coroutines with `asyncio.run` inside | Hides the loop ownership problem | |

[auto] WS adapter — Q: "How are the three live-probe defects fixed?" → Selected: "async adapter with contract test against SDK signatures" (recommended default)

---

## SHADOW mode, simulated fills, approvals

| Option | Description | Selected |
|--------|-------------|----------|
| Call Phase 14 lifecycle functions on live closed 1m bars; minimal SHADOW CONFIRM module reusable by Phase 23 | One fill semantics, no copied logic | ✓ |
| Re-implement fills inside the paper loop | Risks semantic drift from the backtest | |
| Wait for Phase 23 for the CONFIRM step | Violates SC5 (CONFIRM journaled in SHADOW) | |

[auto] SHADOW — Q: "How are fills simulated and how is isolation proved?" → Selected: "reuse lifecycle plus three-layer isolation (import graph, environment, behavior spy)" (recommended default)
**Notes:** Source of live 1m mark-price bars is left to the planner as a research item with a source URL; recommendation is the REST poll through the existing minute source.

---

## Decision-surface parity

| Option | Description | Selected |
|--------|-------------|----------|
| Pure observer over shared core functions, tolerance zero | Satisfies D061 B without touching the simulator | ✓ |
| Extend the simulator to emit NO_TRADE and signal-less bars | Changes Phase 14 semantics and hashes; forbidden without a new decision | |

[auto] Parity — Q: "How is paper compared with backtest at decision level?" → Selected: "non-semantic observer" (recommended default)

---

## Freeze check and evidence

| Option | Description | Selected |
|--------|-------------|----------|
| Allowlist-driven CLI mode that writes SKIPPED with an empty allowlist | Matches D061 A | ✓ |
| Keep a default set when the allowlist is empty | Forbidden (no fallback) | |

[auto] Freeze check — Q: "What happens with an empty allowlist?" → Selected: "SKIPPED (allowlist empty), exit 0" (locked by D061 A)
**Notes:** The durable evidence location was NOT selected (open user decision O-01).

---

## Research runner and kill-gate guard

| Option | Description | Selected |
|--------|-------------|----------|
| Separate infrastructure-only runner that refuses to run without a user authorization artifact bound to the grid hash | Enforces "approving the grid is not authorizing the run" | ✓ |
| Runner that also proposes or ranks candidates | Forbidden (D061 C, E) | |

[auto] Research runner — Q: "How is the run authorization enforced?" → Selected: "artifact with grid hash checked by the runner" (recommended default; the artifact's form and content stay a user decision, O-03)
[auto] Kill-gate guard — Q: "How is the Phase 26 dependency enforced now?" → Selected: "versioned registry of WR-01, WR-06, WR-12, WR-13 read by the report entrypoints plus a test" (recommended default)

---

## Soak-host deployment

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated Compose project, own PG volume, digest-pinned image, guard against `down -v`, backup and restore drill first | Matches D061 iso and hosts | ✓ |
| Share the development stack | Forbidden by D061 | |

[auto] Deployment — Q: "What is the concrete tested configuration?" → Selected: "dedicated project with guard script and test" (recommended default)

---

## Open user decisions (not selected)

No option was selected for any of: durable evidence location, hypothesis and grid approval, research-run authorization (including data window, universe and split dates), exact-hash allowlist entry, D055 model, OQ-1, healthy-feed definition and freshness thresholds, SHADOW approval validity window, SHADOW simulated equity and risk inputs, `modeled_costs_per_unit` restoration, closure-chain triggers on the soak host, EC2 sizing and budget numbers. Options and recommendations are in CONTEXT.md.

## Claude's Discretion

Module and file names where not given, test file names, log event names, queue sizes, evidence file layouts (provided no threshold or location is decided), wave order, runbook wording.

## Deferred Ideas

D055 and Demo probe (18, 24, 25); full Telegram hardening (23); reconcile thresholds (20); WR-06 env split (24); kill-gate WR fixes (26); incremental feature series; TP1 far-half rule; maker/post-only entries; requirements re-map for BKTS-03.
