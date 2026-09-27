# Phase 8: Approval + Reconciliation Hardening - Context

**Gathered:** 2026-09-27
**Status:** Ready for planning

## Phase Boundary

Phase 8 lands human control and exchange-truth safety before any live order exists: Telegram alerts graduate from SIMULATE-only to idempotent APPROVE/SKIP bound to plan identity, a reconciliation loop compares local state against open normal orders + open algo orders + positions and sweeps orphan protectives into SAFE_MODE on divergence, deterministic order identifiers make retries/restarts/replays duplicate-free, and the RUNBOOK failure drills are rehearsed and logged. Much of it is built during the paper soak; enablement gates on paper evidence. No order placement against live capital (Phase 9), no journal-depth/kill-gate analytics (Phase 10). Success means a human — and only that human, once per plan — authorizes action, and the exchange is always the truth that local state is checked against.

## Implementation Decisions

### Approval binding + idempotent replay

- **D-01:** Every approval binds SignalId + strategyVersion + parameterSetId/Hash + plan hash + expiry + authorized chat + one-time token. The raw token is never persisted or logged — only its hash on `Approval.approval_token_hash`. A replayed callback resolves to the existing Approval (WR-07 coherence holds: PENDING ⟺ `acted_at_utc` is None), so 5× duplicate-callback replay produces exactly one state transition. Stale plans (past expiry, plan-hash mismatch, superseded signal) are unapprovable with a reason code. Notification failure leaves the approval PENDING — never auto-approves (Phase-7 D-05 posture extended to the approval path). — **Reversibility:** costly — the binding fields enter Approval rows, callback payloads, and the replay-acceptance test.
- [auto] Approval binding — Q: "Full identity binding (signal+version+hash+expiry+chat+token) with replay-to-existing vs chat-only approval?" → Selected: "Full identity binding, replay resolves to existing approval" (recommended default)

### Callback intake mechanics

- **D-02:** Inbound callbacks arrive via a `python-telegram-bot` Application (polling) behind `src/adapters/` — same single-asyncio-loop precedent as the WS supervisor, no new inbound HTTP surface in V1 (FastAPI stays webhook/health edge only). The authorized-chat gate runs first: unknown chats are rejected before touching any state. `callback_data` stays within the 64-byte limit via the short-id scheme (`sha256(signal_id)[:32]`, Phase-7 CR-05); Phase 8 adds the server-side short→full mapping so callbacks resolve to SignalId + plan. Every callback receipt is journaled as a JournalEvent (at-least-once audit trail). Only `src/adapters/` imports `python-telegram-bot`; the approval core consumes a Protocol-typed bot, mirroring the Phase-7 `TelegramBot` seam. — **Reversibility:** costly — the intake transport and callback-data format enter adapter code, journal rows, and Telegram UX.
- [auto] Callback intake — Q: "PTB polling Application behind adapters vs FastAPI webhook receiver for callbacks?" → Selected: "PTB polling behind adapters, authorized-chat gate first, short→full mapping" (recommended default)

### Reconciliation loop + orphan sweeper + SAFE_MODE

- **D-03:** The reconciler compares local open-intent state against three Binance-truth sources: open normal orders, open algo (conditional) orders, and positions — user-data WS preferred realtime, REST fallback (D002 posture). An orphan (protective without a live entry, entry without its protective) is swept by cancelling the orphan protective; the reconciler never places orders. Any divergence forces SAFE_MODE: new entries blocked while monitoring and reconciliation continue. Check cadence (scheduled tick, not per-event) is at the planner's discretion. The injected-orphan/divergence drill is the EXEC-02 acceptance proof. — **Reversibility:** one-way — SAFE_MODE transitions and sweep actions enter the operational safety contract Phase 9 live rollout depends on.
- [auto] Reconciliation — Q: "Three-source compare (normal+algo+positions) with cancel-only sweeper and SAFE_MODE on divergence vs local-state-only check?" → Selected: "Three-source compare, cancel-only sweep, SAFE_MODE on divergence" (recommended default)

### Deterministic order identifiers

- **D-04:** `client_order_id` / `algo_client_id` derive deterministically from the plan hash + order role (entry vs protective leg), so retries, restarts, and replayed events reuse the same identifier and the exchange dedups them — duplicate entry orders are structurally impossible, not just unlikely. Entry vs protective roles never collide. The exact derivation scheme (prefix + plan-hash slice + role code) is at the planner's discretion, verified by a retry/restart/replay acceptance test. Fits the DATA_MODEL §2.7 three-identifier fields (`client_order_id`, `exchange_order_id`, `algo_client_id`). — **Reversibility:** one-way — identifiers enter exchange-side order history permanently.
- [auto] Order IDs — Q: "Plan-hash + role derived deterministic IDs vs random UUID per attempt?" → Selected: "Deterministic plan-hash + role IDs, exchange dedups" (recommended default)

### RUNBOOK rehearsal + SAFE_MODE operations

- **D-05:** Every RUNBOOK drill is rehearsed and logged before live enablement: unprotected, orphan, duplicate, API-down, stale-feed, DB-failure, manual-close, restore. Rehearsal uses simulated/injected faults — never real unprotected exposure. Each drill lands as a JournalEvent with its outcome; the drill log is the OPS-01 acceptance artifact. SAFE_MODE semantics: blocks new entries, monitoring + reconciliation continue, exit only via the rehearsed restore path. — **Reversibility:** reversible — drills and log format grow additively.
- [auto] RUNBOOK rehearsal — Q: "All eight drills rehearsed with injected faults and journaled outcomes vs paper-only walkthrough?" → Selected: "Full rehearsal, injected faults, journaled drill log" (recommended default)

### Agent's Discretion

- User runs `--auto --chain` (fully autonomous per `modes/auto.md`): all five gray areas above auto-resolved to recommended defaults with no interactive prompts. Single-pass cap observed — no re-pass gap-hunting.
- Exact module layout (e.g. new `src/approval/` vs `src/paper/` extension, reconciler/orphan-sweeper/SAFE_MODE splits), callback receiver structure inside `src/adapters/`, short→full mapping storage (PG row vs in-memory + journal), reconciler tick cadence, order-ID derivation scheme details, drill-harness mechanics, and plan slicing (approval-first vs reconciliation-first) are at the planner/researcher discretion, provided D-01–D-05 semantics hold.
- Pre-answered from prior phases (not re-asked): Approval frozen shape + `approval_token_hash` field + WR-07 PENDING⟺acted coherence (Phase 3); journal-first SIMULATE notify + inert callback labels + 64-byte short-id note (Phase 7); adapter isolation — only adapters import `python-telegram-bot` / Binance SDK (Phases 2/7); purity contracts (stdlib + `Decimal` only in core/risk/backtest/paper-core, AST no-`float(` guards + mypy strict); TDD RED→GREEN with atomic commits; frozen dataclasses; content-hash IDs; TOML registry + SHA256 with 07.1 cost-binding gate; fail-closed posture; single-Base ORM + parity-gate discipline.
- ApprovalResult value set (PENDING/APPROVED/SKIPPED/EXPIRED) was a planner assumption (D-10, user confirmation pending per STATE.md) — carried forward as locked for Phase 8 scope; planner must not relitigate it.

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Approval contract (what to build)

- `docs/trading/SIGNAL_AND_ALERTS.md` — signal/plan schema, SIMULATE/APPROVE/SKIP payload fields, no-stale-approval rule, approve/expire timestamp lineage; APRV-01/APRV-02 source.
- `docs/integration/TELEGRAM.md` — Telegram mechanics (§4: the 12 APRV-01 fields), callback conventions; Phase-7 SIMULATE baseline Phase 8 hardens.
- `docs/data/DATA_MODEL.md` — §2.5 Approval fields (incl. `approval_token_hash`, `request_hash`), §2.7 Order three identifier fields, §2.8 Fill as event; entity shapes to conform to.
- `docs/configuration/CONFIGURATION.md` — §7 experiment identity + cost-model hashing; §§2/4/5 registry identity + immutability; plan-hash binding authority.

### Execution + safety contract (what to build)

- `docs/trading/EXECUTION_SPEC.md` — Algo-Order migration (CONDITIONAL endpoints, `ALGO_UPDATE.o.rm` rejections), order lifecycle, position modes, 200-conditional-order headroom; re-verify SDK minor + changelog before wiring (Dec-2025 precedent). EXEC-02/EXEC-03 source.
- `docs/operations/RUNBOOK.md` — failure drills (unprotected/orphan/duplicate/API-down/stale-feed/DB-failure/manual-close/restore); the rehearsal checklist OPS-01 consumes.
- `docs/operations/SECURITY_AND_OPERATIONS.md` — credential handling (no-withdrawal keys, IP allowlisting, off-source secrets), backup/restore, secret-free logging; safety posture for the approval/execution edge.

### Domain + risk inputs (what to reuse)

- `docs/GLOSSARY.md` — canonical enums (ApprovalAction, ApprovalResult); authority for status naming.
- `docs/DECISIONS.md` — D001–D021 plus Phase-1 D022–D028; determinism (D001), approval-safety, fail-closed bind this phase.
- `docs/trading/RISK_MANAGEMENT.md` — §§1–12: sizing, costs, portfolio caps, DAILY_STOP, fail-closed, quantization; SAFE_MODE interacts with these gates.
- `docs/01_ENGINEERING_PRINCIPLES.md` — determinism + fail-closed posture; Decimal-only and UTC-at-boundary rules.

### Exchange connectivity (how to reconcile)

- `docs/integration/BINANCE.md` — WS/REST surface, user-data streams (preferred realtime), exchangeInfo dynamics; reconciler truth sources.
- `docs/TECHNOLOGY_STACK.md` — `binance-sdk-derivatives-trading-usds-futures>=17.3` (never legacy connectors), adapter-layer isolation, asyncio single loop, python-telegram-bot approval loop (at-least-once replay to existing state, expiring approvals), tenacity bounded retries (never infinite on order-adjacent paths).

### Project context

- `.planning/PROJECT.md` — project context, constraints (determinism, quantization, approval safety, fail-closed, exchange authority), key decisions.
- `.planning/REQUIREMENTS.md` — APRV-01, APRV-02, EXEC-02, EXEC-03, OPS-01.
- `.planning/ROADMAP.md` — Phase 8 goal and success criteria (no per-phase Canonical-refs block; refs above assembled from REQUIREMENTS + EXECUTION_SPEC + scout).
- `.planning/phases/07-paper-forward-observation/07-CONTEXT.md` — Phase 7 locks (SIMULATE-notify boundary, inert callbacks, journal-first, short-id note; "APPROVE/SKIP idempotency hardening stays Phase 8").
- `.planning/phases/03-domain-registry-fixtures/03-CONTEXT.md` — Phase 3 locks (Approval frozen shape + token hash + WR-07 coherence, content-hash IDs, single-Base ORM).
- `.planning/phases/05-risk-engine/05-CONTEXT.md` — Phase 5 locks (portfolio caps + DAILY_STOP, fail-closed gating, dependency-free `src/risk/`) SAFE_MODE composes with.
- `.planning/phases/04-pure-core-feature-strategy-planner/04-CONTEXT.md` — Phase 4 locks (pure core, plan-hash contract) the approval binding references.

## Existing Code Insights

### Reusable Assets

- `src/domain/approval.py` (frozen Approval + `approval_token_hash` + `request_hash` + WR-07 coherence check) — the entity Phase 8 binds callbacks to; replay logic trusts its shape.
- `src/paper/notify.py` (journal-first SIMULATE send, bounded tenacity retry, `on_outcome` journaling, 12 APRV-01 fields) — graduates to APPROVE/SKIP payloads; journal-first ordering already proven.
- `src/adapters/telegram_notify.py` (`TelegramBot` Protocol seam, `send_simulate`, `_short_signal_id` short-id scheme with short→full mapping note) — the adapter the callback receiver extends; paper-core never imports PTB directly.
- `src/domain/order.py` (three identifier fields) + `src/domain/position.py` + `src/domain/journal.py` — reconciler input/output shapes.
- `src/risk/gating.py` + `src/risk/portfolio.py` (fail-closed gates, DAILY_STOP states) — SAFE_MODE composition point.
- `src/paper/freeze.py` (`check_registry_unchanged`, SAFE-adjacent halt semantics) — precedent for halt-and-continue-monitoring behavior.
- `src/db/models.py` + `src/db/mappers.py` (single-Base ORM, Enum translation) + parity-gate discipline — persistence pattern for Approval/callback/mapping rows.

### Established Patterns

- TDD RED→GREEN per behavior with atomic commits; frozen dataclasses; INSERT-only versioning; fail-closed loader/quality posture; structured lineage logging.
- Decimal-only + UTC-at-boundary + Asia/Ho_Chi_Minh display-edge discipline (Phases 2–7).
- Adapter-edge isolation for all SDK types (Binance SDK, python-telegram-bot); core/paper packages stay dependency-free.
- Tracer-first rollout precedent (Phases 4–7): land the approval-binding slice first, then reconciler/sweeper, then drills.

### Integration Points

- New approval/callback handling (e.g. `src/approval/` at planner discretion, or `src/paper/` extension) consuming Telegram callbacks + registry-pinned plans, emitting Approval transitions + JournalEvents.
- Callback receiver extension inside `src/adapters/` (paper/approval-core never imports PTB directly).
- New reconciler (e.g. `src/reconcile/` at planner discretion) consuming user-data WS + REST truth, emitting sweeps + SAFE_MODE transitions + JournalEvents.
- New `tests/fixtures/phase8/` golden files (callback replay sequences, injected-orphan/divergence scenarios, retry/restart ID determinism, drill logs).
- Phase 9 consumes hardened approvals + deterministic IDs + rehearsed SAFE_MODE for first live orders; Phase 10 deepens analytics on approval-delay impact.

## Specific Ideas

- No "I want it like X" references — `--auto` mode, open to standard approaches within the locked decisions above (same delegation pattern as Phases 1–7.1).
- Prior delegation precedent (Phases 1–7.1 CONTEXTs): user delegates implementation choices to recommended defaults; planner/researcher discretion governs layout and slicing.

## Deferred Ideas

- Live Algo exits + placement-time revalidation → Phase 9; journal depth (MFE/MAE, execution-quality latencies, approval-delay impact) + kill-gate operations → Phase 10.
- FastAPI inbound webhook receiver for Telegram callbacks → deferred (V1 uses PTB polling; revisit only with a measured need).
- Correlation model upgrade (REFN-04), OI/funding as strategy features (REFN-02/REFN-03), 15M refinement (REFN-01), extra families (REFN-05) → v2 requirements, not Phase 8.
- None — discussion stayed within phase scope.

---

*Phase: 8-Approval + Reconciliation Hardening*
*Context gathered: 2026-09-27*
