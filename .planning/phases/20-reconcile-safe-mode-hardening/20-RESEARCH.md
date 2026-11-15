# Phase 20: Reconcile + SAFE_MODE Hardening + Alerts - Research

**Researched:** 2026-10-20
**Domain:** Exchange reconciliation, protection supervision, durable SAFE_MODE, risk-reducing-first ordering, operational alerts (Python 3.13, asyncio, SQLAlchemy sync stores, Binance USD-M Futures, fakes only)
**Confidence:** MEDIUM-HIGH (code facts HIGH, read this session; Binance behaviour facts MEDIUM or ASSUMED because the official pages are silent on the manual-close question)

> **Review addendum (2026-10-21): where this file and `20-CONTEXT.md` differ, CONTEXT wins.** The reviewer resolutions changed these research recommendations: Q-B/D-13 is now a bound check only, no `positions` writer and no `update_position_snapshot` in Phase 20 (deferred to Phase 24 with the fills ledger and `Order` rows; `fills.order_id` has a foreign key to `orders`); Q-E/WR-03 is deferred to Phase 24 with the Phase 20 state-safety invariants (D-29); D-20 means queue order only; the closed-entry reason is `RECONCILED_ABSENT` (D-11); SAFE_MODE exit blocks on a missing local source and the operator id is audit only (D-15); `PROTECTIVE_REJECTED` is a new alert (D-24); the new keys go in `execution-limits-v1.toml` (D-25); OPS-05 is infrastructure plus test trigger until Phase 21 (D-23); the journal alone is not the rebuild source (D-30, Q-A). Treat the Open Questions below as answered by those decisions where they match.

<user_constraints>
## User Constraints (from CONTEXT.md)

Copied from `20-CONTEXT.md` (gathered with `--auto`; items marked OWNER-OPEN must not be implemented until the owner decides).

### Locked Decisions

All decisions below are the recommended option, or the direction the owner already recorded in `20-NOTES.md` (Q3, Q4, Q5, D077). Nothing here edits `docs/DECISIONS.md`. No number is invented: every window, probe count, threshold and cadence is a `NOT_CONFIGURED` key (O-04) and the live path refuses while it is unset.

**Compare: reverse pass and signed amounts (criterion 1, F-701)**
- **D-01:** `src/reconcile/compare.py` stays pure. It gains: a reverse pass over exchange normal and algo orders (an exchange order with no local intent is a divergence), a per-position signed-amount comparison (sign and magnitude), and a rule that every open exchange position has an ACTIVE STOP on the exchange. New `Divergence` kinds are added to `_DIVERGENCE_KINDS` for: doubled position, sign-flipped position, foreign order, TP-only position, position without stop. The existing five kinds keep their names and meaning.
- **D-02:** A foreign order (not created by this system, by client id prefix) is a divergence and an alert, never swept and never canceled. Only `ORPHAN_PROTECTIVE` stays sweepable, as today.
- **D-03:** Duplicate exchange client ids no longer collapse silently in the compare index (G2-019, 08-REVIEW IN-15): they become a divergence. Skipped sweeper cancels (IN-14) leave a journal row. - Reversibility: reversible.
- **D-04:** `StreamDivergenceKind.SINK_FAILURE` and the supervisor halt `TASK_DIED` (Phase 18) map to divergences the reconciler acts on, not only logs (20-NOTES, Phase 18 review).

**Protection supervision and re-placement (criterion 2, D034, D077, RISK-03)**
- **D-05:** Criterion 2 wording is reconciled with D077 and D-10 of Phase 19. There is no entry-time SL (the stop is placed after the first fill), so "the entry-time SL of a resting entry is never an orphan (F-401)" becomes: a protective of a plan whose entry is still resting or partially filled is never classified as an orphan. The wording change goes to ROADMAP and REQUIREMENTS in the same plan as the code. It stays tied to the open D055 closure; D055 is not closed here.
- **D-06:** A stop that was confirmed ACTIVE and later reads absent or not active is decided by the position, as in D077: confirmed exposure is a MARKET close (CLOSE_REQUIRED); unreadable or flat-but-entry-can-still-fill goes back to `UNPROTECTED` (blocking) with `stop_lost_at` set once. A stop is NOT blindly re-placed. A re-placement, where policy allows one, restores the original plan stop, never a wider one (RISK-03), and only after the position is reconciled first.
- **D-07:** Supervision continues after `PROTECTED`, `COMPLETE` and `TP_UNAVAILABLE`: while a position is open the reconciler checks that its stop is still ACTIVE. A stop cancelled or lost later is a divergence, not invisible.
- **D-08:** `stop_lost_at` and the coordinator's pending state are rebuilt on restart from the journal and intent rows, never restarted: the rebuild must not reset the `max_unprotected_ms` clock and must not re-place a stop (G4-029). This includes the closer's pending `EMERGENCY_CLOSE` attempt (`pre_send` / `ambiguous` rows), so an ambiguous attempt the exchange does not show is not forgotten and its number is not reissued. - Reversibility: costly - the rebuild reads rows shaped by Phases 17 and 19; changing it later touches the coordinator, the closer and the stores.
- **D-09:** Expiry and emergency close follow the WR-07 ordering rules, defined here (G2-026): expiry cancels a plan's protective legs only with zero fills, using the coordinator's fill state as the source; the emergency close is a reduce-only MARKET order (Phase 19 D-15), and the plan is never declared safe on a flat-confirmation alone. An executed plan stays `APPROVED` and is never moved to `EXPIRED` (G4-036).
- **D-10:** `ENTRY_WITHOUT_PROTECTIVE` is promoted into the `RejectionReason` enum and GLOSSARY 9.3 is updated (G3-005, D044).

**Closing what Q5 leaves UNKNOWN (OWNER-OPEN numbers)**
- **D-11:** `resolve_unresolved_intents` no longer records a not-found ENTRY intent that went `UNKNOWN` after an ambiguous error as `REJECTED`. Such an entry is closed only after repeated probes, the GTD expiry passing, and a clean position-and-open-order reconciliation, each with its evidence source written to the journal (G4-034, D051). The probe count, the window and `protection.entry_unknown_grace_ms` stay `NOT_CONFIGURED` (O-04); the owner sets them. A placement is never re-sent (Q5).
- **D-12:** Every Order or Position move out of `UNKNOWN` needs Binance evidence (REST reconcile or a user-data event) and records the evidence source.
- **D-13:** Reconcile updates position quantity and PnL through a new store method (`update_position_snapshot`, G4-043).

**SAFE_MODE durability and operator exit (criterion 3, F-711, F-127)**
- **D-14:** SAFE_MODE is persisted. `SafeModeController.state_snapshot` / `rehydrate` already exist; this phase adds the durable store write on enter and the load on start. Entering flips first and fails closed on a store failure; exit is journaled first (17-REVIEW WR-03 ordering stays).
- **D-15:** Exit needs an operator id recorded with the exit event, and still needs a fresh clean three-source compare. A boolean flip, a restart or a timer never exits SAFE_MODE. - Reversibility: costly - the operator-id field enters the persisted SAFE_MODE schema and the exit event; undoing it needs a migration.
- **D-16:** Risk-reducing actions execute first and are journaled afterwards, with a fallback when the journal or DB is down (F-702): `disable`, `expire_pending_entry`, `cancel_untriggered_protectives` and `emergency_manual_close` do not wait for the journal. The fallback keeps the record in a local durable spill that is replayed into the journal later. A DB outage never blocks them; it does block a new entry.
- **D-17:** A `-2011` cancel result is verified by a post-cancel query (F-502): the order is not counted canceled until the query shows it gone.

**Rate-limit pause versus protection (Q4, OWNER decided 2026-10-20)**
- **D-18:** An HTTP 429/418 pause is never bypassed. `Retry-After` is honoured, otherwise the configured cooldown; never assume the pause ended. `-1008` is not a rate-limit pause (quick task 261020-g1a).
- **D-19:** Before sending, the intent of a protective stop, an entry cancel or an emergency close is recorded durably; when the gateway blocks it, the explicit pending state is recorded (`STOP_NOT_SENT`, `PROTECTION_ENTRY_CANCEL_NOT_SENT`, `CLOSE_NOT_SENT`) in a durable store that survives restart (likely a migration). When sending is allowed again the reconciler reads the current state first and then decides; an old payload is never replayed blindly. If `max_unprotected_ms` runs out during the wait the plan moves to CLOSE_REQUIRED, and a queued old stop is not sent when policy already requires a close. - Reversibility: costly - a new table or column plus a state machine used by three actions.
- **D-20:** "Reserved priority for risk-reducing calls" is OWNER-OPEN: it is not defined. Plan it as a question for the owner (for example request-weight headroom or a queue ordering rule) and build nothing for it until answered. The queue never claims that a position always has a stop under every rate-limit condition.

**Emergency close without exchangeInfo (Q3, OWNER decided 2026-10-20)**
- **D-21:** The emergency close only may use the last validated MARKET_LOT_SIZE filters, stored with a `filters_stale` flag and the fetch time; a new entry never may. With no valid stored filters nothing is guessed: CLOSE_REQUIRED and SAFE_MODE stay, a critical alert goes out and reconciliation continues. The close quantity comes from the reconciled exposure, floored to the filters, never rounded up to reach minQty. A rejection caused by wrong filters is not re-sent; fresh filters are fetched when readable and the quantity recomputed. A split close still runs one part at a time (WR-03). The planner first checks whether `PlanConstraintSnapshot` is persisted or only in memory.

**Alerts (criterion 4, F-106, OPS-05)**
- **D-22:** A real `CriticalAlertSink` sender replaces the rehearsal-only one. Order: write the alert to the journal first, then send; a Telegram send failure has its own handling (journal row, bounded message retry). Retrying a message is allowed; retrying an order is not.
- **D-23:** Alert events: unprotected position; local-vs-exchange divergence; foreign or unknown order; DAILY_STOP; stale data; auth failure; and, from T-05, a duplicate execution attempt, a rejected protective action and a daily-loss WARNING. Already emitted by code and to be wired: `CLOSE_REQUIRED`, `TP_UNAVAILABLE`, `EMERGENCY_CLOSE_FAILED`, `EMERGENCY_CLOSE_NOT_SENT`.
- **D-24:** The entry path gets alerts for SAFE_MODE reasons `ENTRY_STATE_UNKNOWN`, `PROTECTION_HANDOFF_FAILED` and `DB_FAILURE`. NO_TRADE outcomes `ENTRY_REFUSED_BEFORE_SEND` and `EXCHANGE_CONSTRAINT` are journaled, not alerted, unless the owner asks for more (OWNER-OPEN).
- **D-25:** Stale feed (D058): this phase detects and handles a missing or stale mark-price or user-data feed (execution fails closed); Phase 24 owns the LIVE enablement gate. The reconcile cadence, the stale-feed threshold and the WS-silence threshold are registry parameters with provenance labels and `NOT_CONFIGURED` values (T-06); the owner sets the numbers.

**Manual emergency controls (EXEC-06) and tests (criterion 5)**
- **D-26:** The manual controls (cancel pending strategy orders, disable new entries, close strategy positions on explicit action, re-place protection, enter SAFE_MODE) are checked against EXEC-06 and gaps are closed; a close or re-placement by a human follows D-06 and D-16.
- **D-27:** Tests that assert the old rule "the reconciler never places" are rewritten (F-604) to the new rule, with the same fake-exchange style. Drills for UNPROTECTED, STALE_FEED and MANUAL_CLOSE (G2-016) are added to `src/ops/drills.py`; two drill outcomes never emitted (08-REVIEW IN-14, IN-15) are emitted.
- **D-28:** Manual close outside the system (G4-035): the code does not rely on either answer (orphan or auto-cancel). The sweeper and reconcile handle both; the behavior is proven on Demo in Phase 25, after the live Binance pages are re-read.

### Claude's Discretion
- Module layout of the new reconciler loop and the alert sender, naming of new divergence kinds, and test file split, as long as `src/core` stays pure, no wall clock is read in pure modules, and decimals are `Decimal`.
- The shape of the local durable spill for D-16, within the existing persistence patterns.

### Deferred Ideas (OUT OF SCOPE)
- "Reserved priority for risk-reducing calls" (D-20) until the owner defines it.
- The numeric values of every `NOT_CONFIGURED` key (O-04, T-06) are the owner's.
- Telegram UX for alerts and approval hardening: Phase 23.
- Demo proof of manual-close behavior and the 11 Demo probes: Phase 25 and the owner.
- Writing the DECISIONS rows (D079, D080 drafts and the Q3/Q4 row): owner, after the drafts.

Out of scope for the phase (CONTEXT `<domain>`): account equity and daily loss from Binance (Phase 21), leverage and liquidation guard (22), Telegram UX / two-step confirm / money amounts (23), the running live process and the caller wiring of intent recovery (24), the Demo campaign and the manual-close Demo proof (25). No Telegram, Binance or EC2 connection is needed to plan or build; tests use fakes and the local PostgreSQL 17.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EXEC-02 | Reconciliation loop compares local state against open normal orders, open algo orders and positions, sweeps orphan protective orders, forces SAFE_MODE on divergence | Compare v2 design (Pattern 1), entry-aware orphan rule, reconcile loop (Pattern 5), startup recovery order (Pattern 8). Library-proven with fakes only: the requirement text itself says Demo-proven evidence is Phases 24/25, so the plan must NOT mark it Complete. |
| OPS-01 | SAFE_MODE blocks entries while monitoring continues; RUNBOOK drills rehearsed | Durable SAFE_MODE + operator exit (Pattern 3), drills G2-016 (Pattern 9). Same caveat: real-stack rehearsal is Phases 25/26. |
| RISK-03 | A live stop is never loosened or removed while its position is open; re-placement restores the original plan stop, never wider | Finding F1 (`emergency_manual_close` cancels live stops today), Pattern 6 (supervision after PROTECTED), re-placement rule (same id, plan trigger price only). |
| EXEC-06 | Manual emergency controls: cancel pending orders, disable entries, close positions on explicit action, re-place protection, enter SAFE_MODE | Gap table in Pattern 7 (close and protect actions do not exist in code). |
| OPS-05 | Operational alerts for unprotected position, divergence, unknown/foreign order, duplicate execution attempt, stale data, rejected protective action, auth failure, daily-loss WARNING and DAILY_STOP | Alert design (Pattern 4) with an event-to-source table; DAILY_STOP/WARNING producers arrive in Phase 21, so Phase 20 ships the event types and a tested call surface only. |
</phase_requirements>

## Project Constraints (from CLAUDE.md / AGENTS.md)

Treated with the authority of locked decisions. [VERIFIED: AGENTS.md read this session]

- Always `uv run ...`, never bare `python`. Ruff line length 100; mypy `strict` on `src` only; pytest `asyncio_mode = "auto"`; every module starts with `from __future__ import annotations`; first-party imports absolute `src.*`.
- Decimal-only on domain/registry/risk/backtest/core/analytics (`tests/test_domain_no_float.py`); no wall clock in pure modules (`tests/support/ast_guards.py`, `WALL_CLOCK_CALLS`); `src/core` stays pure.
- Fail closed: uncertain data, connection, account or risk means NO_TRADE and no new order; SAFE_MODE blocks entries while monitoring and reconciliation continue.
- A placement is never re-sent (Q5). Plan binding: quantity may be at most the approved quantity, never larger.
- No AI/LLM in the decision path. Missing contract means TBD, never invented. Exchange facts must be re-read from current official docs.
- Never push, never merge to `master`. Stage explicit paths only; leave untracked `.gsd/`, `.planning/milestone.lock` and modified `.planning/config.json` alone. Commit trailer is the model that did the work.
- Secrets only in `.env`; never read `.env`; `src/ops/redaction.py` redacts logs; alert text must never contain a secret, a DB URL or a heartbeat URL.
- No mainnet or LIVE use; live placement stays disabled (`LIVE_ORDERS_DISABLED`); demo smoke/probe `--execute` is the owner's.
- Alembic reads `DATABASE_URL`; `alembic upgrade head` only; `create_all` never used. A new dependency needs a `DECISIONS` row (none is needed here).
- Parameter sets in `params/**` are hash-locked: do not touch. New operational numbers go in versioned config with `NOT_CONFIGURED` + provenance, not in `params/`.
- Do not run `gsd-tools generate-claude-md` on AGENTS.md. After editing AGENTS.md run `uv run python scripts/verify_decision_alignment.py all`.
- Network flaky: one retry at most.
- No project skills directory (`.claude/skills` absent).

## Summary

The reconcile package today is a pure, correct-but-narrow Phase 8 library (`compare`, `OrphanSweeper`, `SafeModeController`) with no loop, no persistence wiring, no alert sender and no caller. The Phase 19 coordinator (`ProtectionCoordinator`) and `MarketEmergencyCloser` carry all protection state in process memory. Phase 20 is therefore four jobs: (1) make the compare see what it is blind to (reverse pass, signed bounds, STOP required, entry-aware orphan rule, duplicate ids); (2) make state survive a restart (SAFE_MODE store, coordinator and closer rebuild, a durable pending-action table for the 429/418 window, filters for the emergency close); (3) make risk-reducing actions independent of the database (act first, write-ahead to a local spill, journal after) and verify cancels; (4) add a real alert sender and manual controls. No new third-party package is needed. Everything is tested with fakes and the local PostgreSQL 17.

Seven findings that the CONTEXT did not state (details in "Findings that change or sharpen the CONTEXT"): `emergency_manual_close` cancels the live stop of an open position today (violates EXECUTION_SPEC section 11 and RISK-03); `exit_safe_mode` exits on a vacuous empty local intent (F-711); nothing in production writes `orders`, `positions` or `fills` rows, so the "local" side of the compare must be derived from `execution_intents` plus the coordinator state; the store half of G4-034 (evidence on UNKNOWN exits) already exists from Phase 18; restart recovery would mark a `STOP_LOSS` intent `REJECTED` and so block the coordinator's own re-placement unless ordered correctly; the ProtectionRegistry reports "not blocking" until the rebuild has run; and the CONTEXT's reference to `docs/execution/EXECUTION_SPEC.md` is wrong (the file is `docs/trading/EXECUTION_SPEC.md`).

**Primary recommendation:** Build in this order: pure compare v2 and the SAFE_MODE controller changes first; then persistence (migration 0007, SAFE_MODE store adapter, spill); then the execution-side changes (risk-first, cancel verification, supervision after PROTECTED, pending actions, rebuild, Q3 filters, manual controls); then the reconcile loop, alert sender and drills; rewrite the old-rule tests in the same wave as the code that makes them false. Keep the reconcile package free of any placement call: the loop DECIDES and DELEGATES to the coordinator and the closer in `src/execution`, which keeps the "reconciler places nothing itself" static guard honest in a narrower form.

## Findings that change or sharpen the CONTEXT

Each row is a discrepancy between `20-CONTEXT.md` (or ROADMAP) and the code or docs read this session. The planner should treat these as plan inputs.

| # | Finding | Evidence | Consequence for the plan |
|---|---------|----------|--------------------------|
| F1 | `emergency_manual_close` cancels the SL/TP1/TP2 legs of a plan unconditionally, with the position possibly open. EXECUTION_SPEC section 11 says "protective stops and take-profits are never cancelled by this control" and "cancelling a protective stop is never part of any control above". | [VERIFIED: src/execution/manager.py:2236-2245] `await cancel_untriggered_protectives(` inside `emergency_manual_close`; [VERIFIED: docs/trading/EXECUTION_SPEC.md:247-258] "cancelling a protective stop is never part of any control above" | RISK-03 and EXEC-06 are violated by existing code. Fix is a task, not only a test rewrite: cancel protective legs only after a close is proven flat on two reads (D-09). |
| F2 | `exit_safe_mode` runs the compare with `local_open_orders or []` etc. when the caller passes nothing, so a clean exit is possible against an empty local intent (F-711, the audit's second leg). | [VERIFIED: src/reconcile/safe_mode.py:334-341] `local_open_orders=local_open_orders or [],` | D-15 must also make the local intent mandatory (`local_intent_fn` required, an empty result from a callable that read the store is fine, `None` is refused). |
| F3 | No production code writes `orders`, `positions` or `fills` rows: `insert_order`, `record_fill`, `insert_position`, `transition_position`, `update_order_exchange_state` have no caller outside `src/persistence` and tests. | [VERIFIED: grep this session, only `src/persistence/entities.py` definitions and test callers matched] | The "local intent" of the compare cannot come from those tables. It must be derived from `execution_intents` (ENTRY/STOP_LOSS/TP rows with status) plus the coordinator's protection state. D-13 (`update_position_snapshot`) needs a row writer too (see Open Question Q-B). Stream-sink wiring to these tables is NOT in the CONTEXT and stays out. |
| F4 | G4-034 store half is already built: `transition_order` / `transition_position` demand `ExitEvidence` when leaving UNKNOWN and journal it in the same transaction; `EvidenceSource` has `REST_RECONCILE` and `USER_DATA_EVENT`. D-12 only needs the reconciler to be the CALLER. | [VERIFIED: src/persistence/entities.py:316-346, 537-568]; [VERIFIED: src/domain/stream_records.py:64-68] `REST_RECONCILE = "REST_RECONCILE"` / `USER_DATA_EVENT = "USER_DATA_EVENT"` | Do not re-implement the store rule; add reconciler call sites and tests. |
| F5 | Restart recovery would terminate a `STOP_LOSS` intent: an INTENDED/SENT STOP intent probed "definitively absent" and younger than 3 days becomes `REJECTED` (terminal, DB trigger), after which the coordinator's own stop re-placement cannot record `ACKED`. | [VERIFIED: src/execution/intent_recovery.py:196-199] `elif answer.found is False and now_utc - record.intended_at_utc < lookup_window:` -> `REJECTED`; [VERIFIED: src/domain/transitions.py:205-219] REJECTED has no successors in the intent table (read lines 205-219) | Order matters in `run_startup_recovery`: rebuild the coordinator first, and make recovery SKIP protective legs of a plan whose ENTRY is ACKED/UNKNOWN and not FLAT (leave them to the coordinator), or have recovery mark them UNKNOWN only. Needs a test (Pitfall 1). |
| F6 | `ProtectionCoordinator.blocks_new_entries()` is `any(t.state in BLOCKING_STATES ...)` over an empty dict after a restart, so it answers False until the rebuild runs. | [VERIFIED: src/execution/protection.py:625-627] | The rebuild needs an explicit "restore pending" flag that makes `blocks_new_entries()` True until `restore` finishes (fail closed). |
| F7 | `CriticalAlertSink.critical(event, plan_hash, symbol, reason, now_utc)` requires a plan hash and a symbol. DAILY_STOP, stale feed, auth failure and foreign-order alerts have neither. | [VERIFIED: src/execution/protection.py:401-406] | Add a broader `OperationalAlert` / `AlertSink` and keep the old Protocol as a thin adapter so the coordinator and closer call sites and tests do not change. |
| F8 | SAFE_MODE persistence needs NO schema migration for the operator id: the state is a JSON text of `str | bool | None`. The CONTEXT says "undoing it needs a migration"; the DDL is untouched, the change is the controller's JSON format (a strict key set). | [VERIFIED: src/persistence/system_state.py:59] `type StateValue = str \| bool \| None`; [VERIFIED: src/reconcile/safe_mode.py:404] `_STATE_KEYS = frozenset({"in_safe_mode", "entered_at_utc", "entered_reason"})`; [VERIFIED: src/db/models.py:871-905] `state_json: Mapped[str] ... Text` | No DDL for D-14/D-15. The format change is still "costly" in the sense that persisted rows of the old format would be refused by a strict `_parse_state`; none exist (no production writer today). |
| F9 | `SAFE_MODE_TICK_SECONDS: int = 60` is a hard-coded cadence ("FLAGGED ASSUMPTION") and a test pins it. T-06 says the cadence must be a `NOT_CONFIGURED` registry value. | [VERIFIED: src/reconcile/safe_mode.py:41] `SAFE_MODE_TICK_SECONDS: int = 60`; [VERIFIED: tests/test_reconcile.py:675] `assert SAFE_MODE_TICK_SECONDS == 60` | Remove the constant and its export (`src/reconcile/__init__.py`), rewrite that test. A reconcile cadence in code would also trip the no-unratified-defaults scan once the key is guarded. |
| F10 | "Two drill outcomes never emitted" are `OUTCOME_SAFE_MODE_BLOCKED` and `OUTCOME_NO_PLACE_ORDER_INVARIANT` (08-REVIEW **IN-08**). CONTEXT D-27 cites IN-14/IN-15, which are the sweeper-skip and duplicate-id items already assigned to D-03. | [VERIFIED: 08-REVIEW.md:655-659] "IN-08: Two canonical drill outcomes are never emitted"; [VERIFIED: src/ops/drills.py:98-103]; [VERIFIED: grep of `return OUTCOME_` in drills.py: only ENTERED, ORPHAN_SWEPTED, REPLAY_TRANSITIONED, RESTORE_CLEAN_EXIT are returned] | `OUTCOME_NO_PLACE_ORDER_INVARIANT` encodes the old rule and must be retired or redefined, not "emitted" as is. |
| F11 | The EXECUTION_SPEC path in CONTEXT canonical refs (`docs/execution/EXECUTION_SPEC.md`) does not exist. | [VERIFIED: `ls docs/execution` fails; `docs/trading/EXECUTION_SPEC.md` exists] | Plans must edit `docs/trading/EXECUTION_SPEC.md`. |
| F12 | D-05 says the ROADMAP/REQUIREMENTS wording change ships "in the same plan as the code", but the Phase 19 owner-gap register lists ROADMAP Phase 20 criterion 2 among docs that "wait for the owner's acceptance of the D055 closure draft (O-01)" and says "no ROADMAP success criterion was edited". | [VERIFIED: 19-OWNER-GAPS.md section 5 and its "Hard limits" paragraph] | Ship the wording as a proposed text plus a `checkpoint:human-verify` task; do not silently edit a success criterion (Open Question Q-D). |
| F13 | `20-NOTES.md` carries Phase 18 `src/WR-03` (event-time ordering: `update_order_exchange_state` overwrites unconditionally and the router's `ExchangeStateUpdate` carries processing time only) and says it needs a schema migration and "the consumers are here". CONTEXT has no decision for it. | [VERIFIED: src/adapters/binance_userdata_router.py:211-218] `ExchangeStateUpdate` has `now_utc` only; [VERIFIED: src/persistence/entities.py:497-516] unconditional overwrite | Open Question Q-E. Because no code writes Order rows (F3), the risk is latent; recommend recording it as deferred with a reason unless the owner wants the column now. |
| F14 | Exchange facts read this session: the official New Algo Order / Cancel Algo Order pages are silent on what happens to a `closePosition` algo order when the position closes; `-2011` means "open order not found in the orderbook", i.e. it does not prove the order was canceled. | [CITED: developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order] "It does not say whether the order is cancelled automatically when the position is closed"; [CITED: developers.binance.com/docs/derivatives/usds-margined-futures/error-code] `-2011 CANCEL_REJECTED ... Cancel request failure as open order not found in the orderbook: "Unknown order sent".` | G4-035 stays unobserved: handle both outcomes (D-28). F-502 confirmed as a real defect class. |

## Architectural Responsibility Map

This system has no browser/CDN tiers. Tiers used: **Pure core** (stdlib + Decimal), **Execution/Orchestration** (async coordinators with injected adapters), **Adapter** (Binance/Telegram behind project interfaces), **Persistence** (SQLAlchemy stores, Alembic), **Ops/Local FS** (spill, drills, health).

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Three-source compare, divergence kinds, classification policy | Pure core (`src/reconcile`) | - | Must stay stdlib-only and deterministic; unit-testable with dicts. |
| Reconcile loop (`tick`), stale-feed detection, stream-divergence intake | Execution/Orchestration (`src/reconcile/loop.py`, Protocol-typed) | Adapter (reads) | Needs injected clock, adapter reads, stores; no SDK imports. |
| Re-placing a stop / market close / entry cancel | Execution (`src/execution/protection.py`, `emergency_close.py`) | Adapter | Reconcile package must never call a placement method itself; it delegates. |
| SAFE_MODE state machine | Pure core (`src/reconcile/safe_mode.py`) | Persistence via a plain-mapping Protocol | Module stays free of `src.persistence`; wiring adapter lives in persistence. |
| SAFE_MODE durability, pending actions, lot filters, positions snapshot | Persistence (`src/persistence`, migration 0007) | - | Append-only/typed stores with fail-closed errors. |
| Risk-reducing-first write-ahead (spill) | Ops/Local FS | Persistence (replay target) | Must work when PostgreSQL is down; atomic tmp + fsync + os.replace per record. |
| Operational alert sender (journal first, bounded Telegram retry) | Adapter (`telegram_notify.send_text`) wrapped by an Ops module | Persistence (journal), Local FS (spill) | Telegram send is an I/O edge; journaling is the audit record. |
| Manual emergency controls | Execution (`src/execution/manager.py`) | Ops | Operator-initiated, must reuse the closer and the same ordering rules. |
| Drills | Ops (`src/ops/drills.py`) | Reconcile | Rehearse through fakes; no SDK. |
| Exchange fact sources | Binance REST (truth) | User-data stream (hint only) | EXECUTION_SPEC section 9: do not rely only on the WS stream. |

## Standard Stack

No new package. [VERIFIED: pyproject.toml lines 17-41 read this session]

### Core (already installed, use as is)
| Library | Constraint in pyproject | Purpose | Why Standard |
|---------|-------------------------|---------|--------------|
| sqlalchemy | `>=2.0,<2.1` | Operational stores (sync) | Existing `PgSystemStateStore`, `PgJournalStore`, `OperationalDatabase.transaction()` |
| psycopg[binary,pool] | `>=3.3,<4` | PG driver | Engine already bounds connect/lock/statement/pool waits (`src/persistence/engine.py`) |
| alembic | `>=1.19.2` | Migration 0007 | Hand-written revisions, parity test against ORM |
| tenacity | `>=9` | Bounded message retry for Telegram | Pattern already in `src/paper/shadow.py` `_send_bounded` and `src/paper/notify.py` |
| python-telegram-bot | `>=22.8,<23` | Bot transport | Reuse `send_text`, `TelegramSendError`, `classify_telegram_error` from `src/adapters/telegram_notify.py` |
| structlog | `>=25` | Logging | Existing |
| pytest / pytest-asyncio / pytest-xdist | `>=9` / `>=1.4` / `>=3.8.0` | Tests | `asyncio_mode = "auto"` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| New keys in `EXECUTION_LIMIT_KEYS` (same file) | A separate `config/reconcile/reconcile-limits-v1.toml` + loader | Same file keeps ONE `require_live_ready()` gate and one README and needs only: dict + toml + README + `tests/support/execution_limits.py` + `tests/test_execution_limits.py` count assertions (`ExecutionLimits(**flat)` is built in exactly two places). A separate file avoids making the protection coordinator refuse because a reconcile-only number is unset. Recommend the same file (Phase 19 precedent); flagged in Open Question Q-F. |
| Per-symbol durable lot-filter table (Q3) | Reuse the persisted per-plan `plan_constraint_snapshots` row | Snapshot is persisted and immutable but is plan-time (can be days old), has TTL semantics and nullable market-lot fields. It is a valid second-tier fallback, not "the last validated filters" the owner asked for. |
| Spill = one file per record | Append-only JSONL with fsync | One-file-per-record reuses the repo's atomic-write pattern (`src/data/store.py`: tmp + fsync + `os.replace`, Windows `PermissionError` retry) and makes replay and delete idempotent per record. JSONL needs partial-line handling after a crash. |

**Installation:** none. `uv sync --frozen --extra dev` is the environment command.

**Version verification:** no new package, so no `npm view` / `pip index` step. The versions above are the constraints in `pyproject.toml`; the lock file wins (`uv lock --check` is a gate).

## Package Legitimacy Audit

No external package is installed or added by this phase. The `gsd-tools query package-legitimacy check` step was therefore not run (nothing to check).

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none) | - | - | - | - | - | - |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

AGENTS.md: a new dependency needs a DECISIONS row; this phase avoids that by design.

## Architecture Patterns

### System Architecture Diagram

```
                      RUNNER (Phase 24 composes; tests/drills drive it here)
                                      |
                      +---------------+----------------+
                      |                                |
              startup_recovery()                  ReconcileLoop.tick(now)
  1 load SAFE_MODE (unreadable => IN SAFE_MODE)          |
  2 load pending actions                    +------------+-------------+--------------------+
  3 rebuild coordinator + closer            |            |             |                    |
  4 resolve_unresolved_intents          REST gate    stream/feed    REST truth reads    pending actions
    (AFTER 3; skips live-plan stop legs)  restriction  intake         (3 snapshots)       (work off FIRST)
  5 first tick                              |            |             |                    |
                                            v            v             v                    v
                                     GATE_CLOSED?   StreamDivergence  compare v2        coordinator.step /
                                     skip reads,    (SINK_FAILURE,    (pure)            closer (delegate)
                                     keep clocks    TASK_DIED,            |
                                     running        stale)                v
                                            \           |         CompareDiff.divergences
                                             \          |               |
                                              +---------+---------------+
                                                        v
                                           classify(kind) -> policy (pure)
                         +--------------+---------------+------------------+----------------+
                         v              v               v                  v                v
                   SAFE_MODE enter   alert sink     sweeper (ORPHAN    delegate to        journal
                   (persisted)       (journal 1st,  only, entry-aware) coordinator:       (best effort,
                                      then Telegram)                   stop lost / no     spill on DB
                                                                       stop => decide by  outage)
                                                                       position (D077)
   Operator path (EXEC-06):  disable -> SAFE_MODE -> cancel entry (verified) -> [close via closer,
   flat on 2 reads] -> only then cancel protective legs;  protect = re-place plan SL, same id, never wider.
   Exit SAFE_MODE: operator_id + local_intent_fn + clean fresh compare + preconditions; journal 1st,
   persist 2nd, flip 3rd.

   Every risk-reducing send:  spill.write_ahead(record) -> exchange call -> journal.record (best effort)
   -> spill.delete on journal success; on restart spill.replay() -> journal (idempotent by event id).
```

### Recommended Project Structure (files to create or modify: feeds the pattern mapper)

**Create (production)**
```
src/reconcile/classify.py            # pure: divergence kind -> (SAFE_MODE reason, alert event, action)
src/reconcile/loop.py                # ReconcileLoop.tick(): gate, reads, compare, classify, delegate
src/reconcile/startup.py             # run_startup_recovery(): ordered startup (Pattern 8)
src/reconcile/feed_freshness.py      # pure stale-feed/WS-silence predicates (D058, D-25)
src/ops/spill.py                     # durable local spill (write-ahead) + replay into journal (D-16)
src/ops/risk_first.py                # act-first / journal-after helper built on the spill (D-16)
src/ops/alerts.py                    # OperationalAlert, AlertSink, JournalFirstAlertSink, TelegramAlertSender,
                                     #   CriticalAlertAdapter (old Protocol -> new sink)   (D-22, D-23)
src/execution/pending_actions.py     # PendingAction value objects + store Protocol (D-19)
src/execution/protection_rebuild.py  # pure rebuild of _Tracked from journal + intents (D-08)
src/execution/lot_filter_source.py   # LotFilterSource: live read -> store; closer-only stale fallback (Q3, D-21)
src/persistence/pending_actions.py   # PgPendingActionStore
src/persistence/lot_filters.py       # PgLotFilterStore (per-symbol last validated filters)
src/persistence/safe_mode_store.py   # adapter: SafeModeStateStore over PgSystemStateStore(SAFE_MODE)
src/db/alembic/versions/0007_reconcile_hardening.py   # pending_protective_actions, validated_lot_filters
config/execution/README.md           # (modify) new keys; see Limits below
```

**Modify (production)**
```
src/reconcile/compare.py             # reverse pass, signed bounds, STOP required, entry-aware orphan, duplicates, new kinds
src/reconcile/safe_mode.py           # state store hook, operator_id on exit, mandatory local intent, on_enter observer,
                                     #   refuse empty reason (IN-13), drop SAFE_MODE_TICK_SECONDS
src/reconcile/sweeper.py             # journal skipped cancels (IN-14), journal-after for cancels (F-702), verified cancel (F-502)
src/reconcile/__init__.py            # exports (remove SAFE_MODE_TICK_SECONDS, add new kinds/symbols)
src/execution/protection.py          # supervise stop after PROTECTED/COMPLETE/TP_UNAVAILABLE (D-07); restore API;
                                     #   pending-action writes on PreSendRefusal; blocks_new_entries until restored; DB-outage-safe
src/execution/emergency_close.py     # LotFilterSource (Q3), restore_pending from journal/spill (D-08), pending-action on NOT_SENT
src/execution/manager.py             # risk-first (F-702), confirm_cancel (F-502), fix emergency_manual_close (F1),
                                     #   operator_close_position, operator_protect_position (EXEC-06), duplicate-attempt alert hook
src/execution/enablement.py          # disable(): flip first, journal after, spill on failure (F-702)
src/execution/intent_recovery.py     # D-11 closing rule; do not terminate live-plan protective legs (F5)
src/execution/execution_limits.py    # new key sections (Limits below)
src/domain/enums.py                  # RejectionReason.ENTRY_WITHOUT_PROTECTIVE (20 -> 21 members)
src/persistence/entities.py          # update_position_snapshot (D-13)
src/ops/drills.py                    # drills G2-016, outcomes cleanup, restore drill with operator id
config/execution/execution-limits-v1.toml   # new keys, all "NOT_CONFIGURED", provenance "NOT_CONFIGURED"
```

**Modify (docs; edit `docs/trading/EXECUTION_SPEC.md`, not `docs/execution/...`)**
```
docs/GLOSSARY.md                     # 9.1 block + counts (20 -> 21), remove ENTRY_WITHOUT_PROTECTIVE row from 9.3,
                                     #   9.4 new reasons, new event/alert vocabulary
docs/trading/EXECUTION_SPEC.md       # section 9 (re-place wording vs D077), 10.1 (D-11 closing rule), 11 (controls)
docs/operations/SECURITY_AND_OPERATIONS.md   # section 7 (D034 re-place wording vs D077; implementation status), section 5 alerts
docs/operations/RUNBOOK.md           # operator SAFE_MODE exit procedure; drills; spill replay
docs/data/DATA_MODEL.md              # the two new tables
.planning/REQUIREMENTS.md, .planning/ROADMAP.md   # criterion 2 wording: PROPOSED text + owner checkpoint (F12); do not mark EXEC-02/OPS-01 Complete
```

**Tests to create / rewrite** (names are proposals)
```
tests/support/reconcile_doubles.py          # fake local-intent builder, recording alert sink, fake spill dir, recording journal that can fail
tests/test_reconcile_compare_v2.py
tests/test_reconcile_classify.py
tests/test_reconcile_loop.py
tests/test_reconcile_startup.py
tests/test_safe_mode_persistence.py  + tests/test_safe_mode_persistence_pg.py
tests/test_safe_mode_exit_operator.py
tests/test_risk_first_spill.py                # F-702 incl. journal always raising
tests/test_cancel_verification.py             # F-502
tests/test_manual_controls.py                 # EXEC-06 / F1
tests/test_protection_supervision.py          # D-07
tests/test_protection_rebuild.py              # D-08 (pure) + PG variant
tests/test_pending_actions_pg.py              # D-19
tests/test_emergency_close_filters.py         # Q3 / D-21
tests/test_intent_recovery_unknown_entry.py   # D-11 + F5
tests/test_alerts.py                          # D-22 / D-23 / D-24
tests/test_position_snapshot_pg.py            # D-13
tests/test_phase20_gate.py                    # AST guards (no wall clock in new modules), no placement call in src/reconcile,
                                              #   limit keys guarded, glossary/enums parity
REWRITE: tests/test_reconcile.py (lines 245-251 fake adapter, 527/672 counters, 675 tick constant, 902-922 static guard),
         tests/test_drills.py (lines 176-185 fake adapter, 972-992, 1136-1170 static guard),
         tests/test_domain_enums.py (len 20 -> 21), tests/test_backtest_engine.py:534, tests/test_decision_alignment_bookkeeping.py:80-83
         (and its PRE_PHASE_12 / PHASE_12 referenced-code sets if `RejectionReason.ENTRY_WITHOUT_PROTECTIVE` is referenced in src),
         tests/test_execution_limits.py + tests/support/execution_limits.py + tests/test_no_unratified_defaults.py (new key names),
         tests/test_controller_rehydrate.py, tests/test_journal_failure_paths.py, tests/test_phase8_audit_reviewfix.py
         (exit_safe_mode callers: 5 files total with src/ops/drills.py and src/reconcile/safe_mode.py)
```

### Pattern 1: Compare v2 (pure) [recommended design]

**What:** Keep the public `compare(...)` keyword signature. Extend the carriers (`LocalOrderIntent`, `LocalAlgoIntent`, `LocalPositionIntent`) with optional fields so existing dict/duck-typed fixtures keep working: `plan_hash` (algo and order), and for positions a signed expected side plus `max_abs_amount` (and optional `filled_amount` when a fills ledger exists). Add passes:
1. **Reverse pass:** every exchange normal order and algo order whose `client_order_id` / `client_algo_id` is not in the local indexes becomes `FOREIGN_ORDER` when the id does not carry this system's prefixes, or `UNSYNCED_*` (existing kinds) when it does carry them but no local intent exists. Prefixes (verbatim below): `x-` entry, `xa-` algo legs, `xc-` close.
2. **Signed amount:** for each non-zero exchange position compare sign with the expected side of its plan (`SIGN_FLIPPED_POSITION`) and `abs(amount)` with the bound (`DOUBLED_POSITION` = exceeds the bound). With a fills ledger use equality. Decimal only; never `float`.
3. **STOP required:** each non-zero exchange position needs an exchange algo order of this system's STOP role in an ACTIVE class (`is_protection_confirmed` / `classify_algo_status` from `src/domain/algo_status.py`). Missing: `POSITION_WITHOUT_STOP`; only TP legs present: `TP_ONLY_POSITION` (more specific, replaces the former).
4. **Entry-aware orphan rule (D-05, F-401):** a protective is not `ORPHAN_PROTECTIVE` while the same plan's ENTRY is locally open (ACKED/UNKNOWN with the coordinator not past entry-terminal) or present in the exchange open normal orders (match by the plan slice of the id).
5. **Duplicates (D-03/IN-15):** while building the truth indexes, count ids; a repeated `client_order_id` / `client_algo_id` yields `DUPLICATE_EXCHANGE_ID` instead of silently keeping the last row.

**When to use:** every tick and every `exit_safe_mode`.

**Why the bound check and not equality:** nothing writes a local fills/positions ledger (F3), so equality has no local operand today. A bound derived from `execution_intents.intended_quantity` (never larger than the approved quantity, D078) catches the doubled and flipped cases of F-701 without inventing a ledger. If the planner adds a fills ledger (Q-B) the same carrier takes `filled_amount`.

**Verbatim in-repo values the design must keep** [VERIFIED: src/reconcile/compare.py:51-65]:
```python
DIVERGENCE_KIND_ORPHAN_PROTECTIVE: str = "ORPHAN_PROTECTIVE"
DIVERGENCE_KIND_ENTRY_WITHOUT_PROTECTIVE: str = "ENTRY_WITHOUT_PROTECTIVE"
DIVERGENCE_KIND_UNSYNCED_NORMAL: str = "UNSYNCED_NORMAL"
DIVERGENCE_KIND_UNSYNCED_ALGO: str = "UNSYNCED_ALGO"
DIVERGENCE_KIND_UNSYNCED_POSITION: str = "UNSYNCED_POSITION"
```
[VERIFIED: src/execution/order_ids.py:50-55, 61-65]
```python
ROLE_CODES: dict[str, str] = {
    OrderRole.ENTRY.value: "EN",
    OrderRole.STOP_LOSS.value: "SL",
    OrderRole.TAKE_PROFIT_1.value: "T1",
    OrderRole.TAKE_PROFIT_2.value: "T2",
}
_CLIENT_PREFIX = "x-"
_ALGO_PREFIX = "xa-"
_CLOSE_PREFIX = "xc-"
```
Do not re-type the prefixes in `src/reconcile`: expose a small pure predicate in `order_ids.py` (`is_system_client_id(id)`, `plan_slice_of(id)`) and import it (reconcile may import `src.execution.order_ids`: it is stdlib + `src.domain.enums` only; check the layering test after adding the import).

**Footgun:** `src/execution/fill_monitor.py` and `src/ops/health.py` define their own copies of the kind strings `"ENTRY_WITHOUT_PROTECTIVE"` / `"ORPHAN_PROTECTIVE"` (`fill_monitor.py:28-30`, `health.py:77-78`). Keep all existing names byte-identical; new kinds are additions only.

### Pattern 2: Local intent derivation (the missing source)

Build `LocalOrderIntent` / `LocalAlgoIntent` / `LocalPositionIntent` from `ExecutionIntentStore.list_unresolved_intents()` plus a NEW read method for "ACKED intents of plans not yet FLAT" (e.g. `list_live_plan_intents()`), joined with the coordinator's `protection_of(plan_hash)` view. The signed expected side comes from the ENTRY intent `side` (BUY -> positive, SELL -> negative). Put the derivation in a pure function (`src/reconcile/local_intent.py` or inside `loop.py`) taking plain rows so it is unit-testable. `exit_safe_mode` receives the same function as `local_intent_fn`.

### Pattern 3: Durable SAFE_MODE and operator exit

- Add a `SafeModeStateStore` Protocol inside `safe_mode.py`: `save(state: Mapping[str, str | bool | None]) -> None` and `load() -> Mapping | None`. The module keeps importing nothing from `src.persistence`. Wiring lives in `src/persistence/safe_mode_store.py` over `PgSystemStateStore.append(SystemStateKey.SAFE_MODE, state, now_utc=...)` / `latest(...)`.
- State format (strict key set, extended): `in_safe_mode`, `entered_at_utc`, `entered_reason`, plus `last_exit_operator_id` and `last_exit_at_utc` (both `None` until a first exit). The append-only table keeps every version, so the exit history survives in `system_state_events` regardless.
- **Enter:** flip memory, journal `SAFE_MODE_ENTER` (existing), then `store.save`. A save failure keeps the controller in SAFE_MODE and surfaces the error to callers that already swallow it (`_enter_safe_mode` in the manager, `_enter_safe_mode_once` in the coordinator).
- **Exit:** `exit_safe_mode(*, operator_id, local_intent_fn, now_utc, ...)`: validate operator id (non-empty string, same rule as `_validate_operator_id` in `enablement.py`), REQUIRE `local_intent_fn` (F2), fresh three-source compare, journal `SAFE_MODE_EXIT` with the operator id in the payload FIRST, `store.save(exit state)` SECOND, flip memory LAST. If either write fails the controller stays in SAFE_MODE.
- **Startup:** `load()` raising (store unavailable, malformed row) -> start IN SAFE_MODE with a fixed reason (fail closed, F-127 and research C14: "A restart must never silently read SAFE_MODE as off"). `load()` returning `None` -> default controller.
- **Recommended extra exit preconditions (planner/owner to confirm, D-15 only mandates operator id + clean compare):** no unresolved intent, no OPEN pending action, REST gate not restricted, user-data stream state LIVE, coordinator reports nothing UNPROTECTED/CLOSE_*. These are pure checks passed in as a `ExitPreconditions` result so the controller stays dependency-free.
- **On-enter observer:** an optional `on_enter(reason, now_utc)` callback lets the alert sink fire once per entry/re-entry without changing the 24 callers (D-24).
- **Cleanups to take while there:** refuse an empty `reason` (08-REVIEW IN-13 text: "`enter_safe_mode` accepts an empty reason"); remove the `SAFE_MODE_TICK_SECONDS` constant (F9).

Verbatim values [VERIFIED: src/domain/enums.py:296-304]:
```python
class SystemStateKey(str, Enum):
    SAFE_MODE = "SAFE_MODE"
    LIVE_ENABLEMENT = "LIVE_ENABLEMENT"
    KILL_GATE = "KILL_GATE"
```
and the DB CHECK already lists them: `"state_key IN ('SAFE_MODE', 'LIVE_ENABLEMENT', 'KILL_GATE')"` [VERIFIED: src/db/models.py:871-905]. No new key means no DDL.

### Pattern 4: Alerts (journal first, then send; message retry only)

- New `OperationalAlert` (frozen dataclass): `event`, `severity` (CRITICAL / HIGH / WARNING), `subject` (plan_hash or symbol or "SYSTEM"), `reason` (fixed project text or exception CLASS NAME only, D-21), `occurred_at_utc`, optional `plan_hash`, `symbol`.
- `CriticalAlertAdapter` implements today's `CriticalAlertSink.critical(event, plan_hash, symbol, reason, now_utc)` and forwards to the new sink (F7). The coordinator and closer are untouched.
- `critical()` is SYNCHRONOUS in the existing Protocol and is called from async code. Design: `JournalFirstAlertSink.critical()` (a) builds the deterministic alert id (`content_hash_event_id`), (b) writes the journal row, falling back to the spill when the DB is down, (c) enqueues the message on an in-process queue and returns. A `TelegramAlertSender` drains the queue with the bounded tenacity pattern of `_send_bounded` (retry RATE_LIMITED / TRANSIENT / UNKNOWN, honour `retry_after`, stop on REJECTED) and journals `ALERT_SEND_FAILED` (class names only) when the budget is spent. A restart finds journaled alerts with no delivery row and re-enqueues them (an undelivered critical alert must not vanish).
- **Dedupe:** one critical alert per (event, subject, reason) episode, suppressed while the same SAFE_MODE reason is unchanged, with a count in the journal. Without it a stuck `CLOSE_FAILED` plan alerts on every step (the closer's own failure alert already repeats on every CLOSE_FAILED step: 19-OWNER-GAPS row WR-04 "IN-01, open").
- Alert body = fixed template + the fields above. Never exchange error text, never a URL, never a token (redaction is value-based; do not rely on it for alert bodies).
- Retry budget constants (3 attempts, 30 s, etc.) exist in `src/paper/notify.py:111-114` as code constants for MESSAGE retry; reuse them. They are not order limits and are not in the guarded names list.

**OPS-05 event map**

| OPS-05 / D-23 event | Source | Status today | Phase 20 work |
|---|---|---|---|
| Unprotected position | coordinator `CLOSE_REQUIRED`, compare `POSITION_WITHOUT_STOP` / `TP_ONLY_POSITION` / `ENTRY_WITHOUT_PROTECTIVE` | `CLOSE_REQUIRED` emitted; UNPROTECTED itself does not alert | Alert on entering `UNPROTECTED` once, and on the divergences |
| Local vs exchange divergence | `compare` | none | loop -> alert per kind |
| Unknown or foreign order | compare reverse pass, `StreamDivergenceKind.UNKNOWN_STREAM_ORDER/ALGO` | none | alert, never cancel (D-02) |
| Duplicate execution attempt | manager `if not consumed:` replay path and the stored-outcome early return | journaled silently | alert hook (needs a sink in `LivePlacementContext` or an optional kwarg) |
| Stale data | `feed_freshness` | none | detect + alert + SAFE_MODE `STALE_FEED` |
| Rejected protective action | coordinator B5 (`BRANCH_B5_STOP_REJECTED` -> CLOSE_REQUIRED alert), `TP_UNAVAILABLE`, `EMERGENCY_CLOSE_FAILED/NOT_SENT` | emitted | wire sink; add a `PROTECTIVE_REJECTED` event if the owner wants it distinct from CLOSE_REQUIRED (Q-G) |
| Auth failure | `ExchangeErrorCategory.AUTH_OR_SIGNATURE` | classified, never alerted | loop/coordinator classify via `adapter.error_facts` + `classify`, alert + SAFE_MODE; adapter untouched |
| Daily-loss WARNING / DAILY_STOP | `DailyState` (`WARNING`, `DAILY_STOP`) | no producer until Phase 21 | ship event types + a tested `raise_daily_state(state)` entry; no equity source here |
| SAFE_MODE `ENTRY_STATE_UNKNOWN`, `PROTECTION_HANDOFF_FAILED`, `DB_FAILURE` | `SafeModeController.on_enter` | none | on-enter observer (D-24) |

### Pattern 5: Reconcile loop (library with a `tick`)

`ReconcileLoop.tick(now)` is step-driven like the coordinator (no internal sleep; the clock is injected). Per tick:
1. Read `RestRateLimitGate.restriction()` (exists: [VERIFIED: src/adapters/binance_ratelimit_gate.py `restriction()` / `remaining_seconds()`]). If restricted: do NOT read; record `RECONCILE_SKIPPED_GATE` with the reason; still run clock-driven logic that needs no REST (the coordinator's deadline escalation keeps running in its own `step()`).
2. Work off OPEN pending actions first (D-19): for each, ask the coordinator/closer to run its normal step (which reads current state, then decides). Never replay a stored payload.
3. Drain stream divergences (`SINK_FAILURE`, `STREAM_ANOMALY`, `UNKNOWN_STREAM_*`, `STREAM_ALGO_TERMINAL_FAILED`, `STREAM_FILL_TOTAL_MISMATCH`) into targeted REST queries of the named client ids, then the full compare. Map the supervisor halt `TASK_DIED` to SAFE_MODE `USER_DATA_STREAM_HALTED` plus REST-only cadence (REST is truth).
4. Read the three truth snapshots, derive local intent (Pattern 2), run `compare`.
5. `classify` each divergence (pure table): SAFE_MODE reason, alert event, action in {NONE, SWEEP_ORPHAN, DELEGATE_STOP_LOST, ALERT_ONLY}. Foreign orders and unsynced positions are ALERT_ONLY (the system never cancels or closes what it did not open; closing is the human's EXEC-06 action).
6. Update `positions` snapshots (D-13) and move UNKNOWN rows with `ExitEvidence(REST_RECONCILE, ...)` (D-12).

**Invariant to enforce at construction:** the tick interval must be strictly less than `protection.max_unprotected_ms`, otherwise a position can sit unprotected past the deadline between ticks (Phase 24 owns the real cadence per the coordinator docstring; this phase only refuses an incompatible pair, inventing no number).

### Pattern 6: Supervision after PROTECTED and the re-placement rule

`_step_plan` sends `PROTECTED` to `_attach_take_profits` and `COMPLETE`/`TP_UNAVAILABLE` to `_watch_exit`; neither re-reads the stop. Add a stop read (by deterministic id, one REST query per step per open plan) to those three states. A confirmed stop reading ABSENT/NOT_ACTIVE while the position is open is routed to the existing `_on_stop_lost` (decided by the position, `stop_lost_at` once). Consequence the owner should know: with D077 a manual cancel of the stop by the owner leads to a MARKET close of the position (B4), not a re-placement. The reconcile compare's `POSITION_WITHOUT_STOP` is the independent second line and calls the same coordinator entry (`notify_divergence(plan_hash, kind)`), so there is one decision path.

Re-placement that remains allowed (D034 for a stop never confirmed, already in `_confirm`): same deterministic id (`derive_algo_client_id(plan_hash, STOP_LOSS)`), trigger price taken from the bound plan (`entry.sl_trigger_price`), never from the divergence, query-first, only when REST proved ABSENT before any confirmation. RISK-03 "never loosened" is enforced structurally by that source of the price; add a test that no re-placement call carries a price different from `sl_trigger_price`.

### Pattern 7: Manual emergency controls (EXEC-06)

| Control (EXEC-06) | Code today | Gap | Work |
|---|---|---|---|
| Cancel pending strategy orders | `expire_pending_entry` | journal-first (F-702); -2011 not verified (F-502) | risk-first + `confirm_cancel` |
| Disable new entries | `LiveEnablementController.disable` | journal raises before the flip (F-702) | flip first, journal after, spill |
| Close strategy positions on explicit action | none (`emergency_manual_close` only cancels; docstring says "the operator closes the position through the exchange UI/API") | missing | `operator_close_position(plan_hash, operator_id)` that reuses `MarketEmergencyCloser` (needs a `RestingEntry`, i.e. the rebuild) and records the operator id |
| Re-place protection | none | missing (EXECUTION_SPEC section 11 asks for an explicit protect action at the ORIGINAL plan SL) | `operator_protect_position(plan_hash, operator_id)`: refuse if the position is flat or unreadable, query-first, same id, plan trigger price only, record operator id |
| Enter SAFE_MODE | `safe_mode_freeze` | fine | persisted via D-14 |

Fix `emergency_manual_close` per F1: steps become disable -> SAFE_MODE -> cancel entry (verified) -> if a position exists, run the closer and require two flat reads -> only then cancel protective legs; if the position is unreadable, cancel NO protective leg.

### Pattern 8: Startup recovery order (library; Phase 24 calls it)

1. `SafeModeController.rehydrate` from the store (unreadable => in SAFE_MODE).
2. Load OPEN pending actions.
3. Rebuild the coordinator and the closer (Pattern 9). Until finished `blocks_new_entries()` is True (F6).
4. `resolve_unresolved_intents` with the D-11 rule and the F5 skip for live-plan protective legs.
5. Spill replay into the journal.
6. First `tick`. SAFE_MODE exit stays manual.

### Pattern 9: Coordinator and closer rebuild (D-08)

Sources, all already persisted [VERIFIED: protection.py module docstring and `_transition`]: `PROTECTION_TRANSITION` journal events (payload keys `approval_id`, `from`, `reason`, `seq`, `symbol`, `to`, `trade_plan_id`; correlation `protection_<plan_hash>`; read with `PgJournalStore.list_by_correlation`), the `STOP_LOSS` intent row (its `intended_at_utc` is "the durable 'unprotected since' time"), ENTRY intent (`side`, `intended_quantity`, `client_order_id`), the persisted `TradePlan` (stop/TP prices, `expiry_utc` -> GTD = floored expiry as in `manager.py:959`), the persisted `Signal`, `PgPlanConstraintSnapshotStore.get`, and `adapter.get_position_mode()`.

A pure function `rebuild_tracked(transitions, intents, plan, snapshot, now) -> RestoredPlan` produces the fields of `_Tracked` (`state`, `first_fill_at`, `stop_confirmed_at`, `stop_lost_at`, `entry_terminal_at`, `close_branch`, `seq`). Rules: `stop_lost_at` = `occurred_at_utc` of the FIRST transition whose `reason` is `STOP_LOST` (never `now`); `first_fill_at` = first transition into `UNPROTECTED` with a `FIRST_FILL_*` reason, else the STOP intent `intended_at_utc`; `close_branch` = `reason` of the transition into `CLOSE_REQUIRED`; `seq` continues from the max seen so transition ids do not collide. `sweep_done` is NOT restored: the sweep is idempotent ("ORDER_ABSENT of a CANCEL is success" in the adapter). Journal rows can be missing exactly when the DB was down, so the rebuild degrades conservatively: no transition rows but an ACKED ENTRY and a STOP intent => `UNPROTECTED` with `first_fill_at` = the STOP intent time and the deadline logic doing the rest.

Closer: `MarketEmergencyCloser._pending` is rebuilt from `EMERGENCY_CLOSE` events (correlation `emergency_close_<plan_hash>`, `phase` in `pre_send` / `ambiguous` / `post_send` without a later terminal phase) PLUS the spill (the closer's `pre_send` journal write is best-effort and is lost during a DB outage, so write-ahead the `pre_send` record to the spill). Adopt the attempt as pending with `unknown_code` set (the closer already has `CODE_HISTORY_NOT_TERMINAL`) so it sends nothing until REST proves it terminal; `discover_next_attempt_no` remains the REST backstop for the number.

### Pattern 10: Pending protective actions (D-19)

New table `pending_protective_actions` (migration 0007): `pending_id` PK (content hash of plan_hash + kind), `plan_hash`, `trade_plan_id`, `approval_id`, `symbol`, `pending_kind` CHECK IN (`STOP_NOT_SENT`, `PROTECTION_ENTRY_CANCEL_NOT_SENT`, `CLOSE_NOT_SENT`) (the owner's names, verbatim from CONTEXT D-19), `state` CHECK IN (`PENDING`, `RESOLVED`, `SUPERSEDED`), `gate_reason` (the `RestGateRefusal.reason` text: `IP_BAN_418` / `RATE_LIMIT_PAUSE_429`), `first_blocked_at_utc`, `last_blocked_at_utc`, `block_count`, `retry_after_until_utc` NULL, `resolved_at_utc` NULL, `resolution_note` NULL. A partial unique index on (`plan_hash`, `pending_kind`) WHERE `state = 'PENDING'`. It stores the INTENT, never a payload: the stop price and quantity are re-derived from the plan at send time, so "an old payload is never replayed blindly" holds by construction.
- Written when the gate blocks (`PreSendRefusal` branches already journal `STOP_NOT_SENT`, `PROTECTION_ENTRY_CANCEL_NOT_SENT`, `CLOSE_NOT_SENT`).
- The "durable before send" half must NOT depend on PostgreSQL (D-16 says a DB outage never blocks risk-reducing actions). Write-ahead the three intents to the local spill; the DB row records the blocked state. The STOP intent already has a DB write-ahead (`INTENDED` then `SENT`), kept as is.
- Resolution: the coordinator's next ordinary step reads current state (stop ABSENT? entry terminal? position?) and acts; a plan that has entered CLOSE_REQUIRED/CLOSE_FAILED/FLAT marks a pending STOP as `SUPERSEDED` and never sends the stale stop.
- The gate is in-process memory. After a restart the gate forgets an active 418; the first REST call may be refused by Binance again and re-arms the gate. Do not store a gate end time as truth.

Process facts to cite: HTTP 429/418 semantics [CITED: developers.binance.com/docs/derivatives/usds-margined-futures/general-info] "When a 429 is received, it's your obligation as an API to back off and not spam the API"; bans "scale in duration" from 2 minutes to 3 days. `-1008` is documented as exempt for reduce-only/close-position (and cancel) [CITED: same page]; the repo already treats `-1008` as `SYSTEM_THROTTLED`, never a pause (quick task 261020-g1a). The page excerpt I fetched did not mention a `Retry-After` header; the repo's ratified policy handles absent `Retry-After` by a configured wait (`config/binance/binance-limits-v1.toml`: `rate_limit_429_no_retry_after_wait_seconds = 120`, `rate_limit_418_no_retry_after_wait_seconds = 259200`).

### Pattern 11: Q3 stale filters for the emergency close

`PlanConstraintSnapshot` IS persisted (`PgPlanConstraintSnapshotStore`, table `plan_constraint_snapshots`, write-once, canonical JSON + sha256) [VERIFIED: src/persistence/snapshots.py:1-60]. It carries `market_lot_min_quantity`, `market_lot_max_quantity`, `market_lot_step_size` (nullable), `constraints_observed_at_utc`, but it is plan-time, immutable and has a TTL predicate (`snapshot_is_valid_for_live`). It is not "the last validated filters". Recommended: a per-symbol `validated_lot_filters` record (symbol, the `LotFilters` fields as text, `fetched_at_utc`), upserted on every successful `symbol_lot_filters` read (the reconcile tick refreshes it), and a `LotFilterSource` with two methods: `for_entry(symbol)` (live read only, TTL applies, NEVER stale) and `for_emergency_close(symbol)` returning `(LotFilters, filters_stale: bool, fetched_at)`; only the closer imports the second. Tier-2 fallback after a restart: the plan's persisted snapshot IF all market-lot fields and `max_quantity` are present. No valid source => `LOT_FILTERS_UNAVAILABLE` keeps CLOSE_REQUIRED/SAFE_MODE, critical alert, reconciliation continues (existing `_fail` path). A rejection attributed to wrong filters re-reads fresh filters when readable and recomputes; it does not re-send the same payload (reuse the closer's attempt/pending logic: a rejected attempt is terminal, the next attempt gets a new number). Interaction with Q4: the `exchange_info` read goes through the same REST gate, so under a 429/418 pause it is refused and the stored filters help only for timeouts and 5xx.

### Anti-Patterns to Avoid
- **A reconcile module that calls a placement method.** Keep `src/reconcile` free of `place_*`, `new_order`, `new_algo_order`; delegate to the coordinator/closer. The static guard is narrowed, not deleted.
- **Journal-first on a risk-reducing path.** Replace with spill-first (local, no DB), act, journal-after.
- **Counting `-2011` as canceled.** Query afterwards.
- **Rebuilding `stop_lost_at` from `now`.** Use the journaled time.
- **Reading exchange error text into alerts or journals.** Class names and fixed text only (D-21).
- **Treating a gate re-open as proof.** The gate docstring: "The end of a ban or of a pause proves nothing about an order, a cancel, a fill or a protective stop."
- **Wall-clock reads in new modules.** Inject `clock`/`now_utc`; add an AST guard (`wall_clock_calls`) over the new files.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Deterministic event ids and replay idempotency | Custom id scheme | `content_hash_event_id` / `correlated_event_id` (`src/domain/journal.py`), `PgJournalStore` `ON CONFLICT DO NOTHING` + `_verify_replay` | Replaying a spilled event twice is a no-op; a different event under an id raises `JournalConflict` |
| Durable SAFE_MODE | New table or file | `PgSystemStateStore(SAFE_MODE)` append-only with journal in one transaction | Already built in Phase 17, trigger-protected, `latest()` fail-closed |
| Evidence on UNKNOWN exits | New journaling | `ExitEvidence` + `transition_order/position(evidence=...)` | Already enforced in the store |
| Error classification | String matching on messages | `error_facts` + `classify(facts, CallKind)` (`src/domain/exchange_errors.py`) | D-21: never read message text |
| Rate-limit state | A new pause tracker | `RestRateLimitGate.restriction()` / `remaining_seconds()` | One process-wide instance; no method clears it |
| Algo status ACTIVE check | Ad-hoc string compare | `is_protection_confirmed`, `classify_algo_status` (`src/domain/algo_status.py`) | Ratified status classes |
| Lot splitting for the close | Own rounding | `next_close_part`, `plan_close_parts` (`src/execution/lot_split.py`) | Floors, never rounds up |
| Message retry/backoff | `while` loops | tenacity `AsyncRetrying` pattern of `src/paper/shadow.py::_send_bounded` | Honours `retry_after`, bounded budget |
| Atomic file write | `open(...).write` | tmp + fsync + `os.replace` helper pattern of `src/data/store.py` (Windows `PermissionError` retry) | Crash-safe on the dev OS |
| Close attempt ids | Counters | `derive_close_order_id` + `discover_next_attempt_no` | Numbers never reused across restarts |
| Telegram classification | Own exception parsing | `classify_telegram_error`, `TelegramSendError`, `send_text` | One place knows PTB classes |
| Config with provenance | Constants in code | `execution_limits.py` loader + `NOT_CONFIGURED` + provenance table | `tests/test_no_unratified_defaults.py` enforces |

**Key insight:** every piece of this phase already has a tested building block from Phases 8, 17, 18 or 19. The risk is in ordering and in the three places where today's code contradicts the new rule (F1, F2, F5), not in missing infrastructure.

## Common Pitfalls

### Pitfall 1: Restart recovery terminates the stop intent the coordinator needs
**What goes wrong:** `resolve_unresolved_intents` records an absent young `STOP_LOSS` intent `REJECTED`; the coordinator later re-places the stop, then `record_result(ACKED)` hits a terminal row.
**Why:** `REJECTED` has no successors (trigger + `transitions.py`), and `IllegalTransition` is a `ValueError`, not a `PersistenceError`, so `_store_write` does not catch it and the step logs `PROTECTION_STEP_ERROR` every step.
**How to avoid:** rebuild first; make recovery leave protective legs of live plans UNKNOWN (never REJECTED); add the test "crash after STOP_LOSS intent SENT, restart, stop placed once under the same id, intent ends ACKED".
**Warning signs:** repeated `PROTECTION_STEP_ERROR` after a restart test.

### Pitfall 2: Registry says "not blocking" before the rebuild
**What:** `blocks_new_entries()` is False on an empty tracked dict (F6). **Avoid:** restore-pending flag; test that an entry is refused between process start and `restore()` completion.

### Pitfall 3: Cancelling a live stop through the manual control
**What:** F1. **Avoid:** the new `emergency_manual_close` sequence; test with the fake exchange holding an open position and an ACTIVE stop: after the control the stop must still exist unless the position is proven flat twice.

### Pitfall 4: Vacuous SAFE_MODE exit
**What:** F2. **Avoid:** refuse when no local intent source; test with the fake adapter returning a doubled position and an empty store.

### Pitfall 5: `-2011` treated as canceled
**What:** the adapter returns `None` for both a real cancel and ORDER_ABSENT [VERIFIED: src/adapters/binance_usdm.py:1038-1050, 1091-1103]. For an entry, absent can mean FILLED. **Avoid:** do not change the adapter's contract; add `confirm_cancel(adapter, kind, ...)` in `src/execution` that, after a cancel returned (even normally), queries the order and returns an enum (`CANCELED`, `FILLED_OR_PARTIAL`, `STILL_OPEN`, `UNKNOWN`); journal `post_cancel` only for `CANCELED`, otherwise `cancel_unverified` with the observed status. For an algo order, ABSENT after a cancel may mean TRIGGERED/FINISHED: on a position-open plan treat "gone but not CANCELED" as a stop-lost signal.

### Pitfall 6: Synchronous database calls on the event loop
**What:** every store call blocks the loop up to the engine's bounded waits during an outage. **Avoid:** spill write is the only thing on the critical path; run journal/store writes of risk paths through `asyncio.to_thread` (the intent store docstring already records "Phase 24 may wrap it in asyncio.to_thread"), or accept and test the bounded delay.

### Pitfall 7: Alert flood and alert-as-secret-leak
**Avoid:** dedupe per episode; fixed templates; a test that feeds an exception with a fake token in its message and asserts the alert text lacks it.

### Pitfall 8: Spill on Windows
**What:** `os.replace` can raise `PermissionError` while an indexer holds the file [VERIFIED: src/data/store.py lines 41-56 comment]. **Avoid:** reuse the retry helper; one file per record named by the journal event id; replay deletes only after a successful `journal.record`.

### Pitfall 9: Foreign-order false positives
**What:** classifying by the `x-`/`xa-`/`xc-` prefix means any manual order the owner places in the Binance UI becomes a divergence and SAFE_MODE. That is intended (fail closed, D-02) but the RUNBOOK must say so; and a system order whose plan is no longer known locally must not be called foreign (it carries the prefix) - it is `UNSYNCED_*`.

### Pitfall 10: Enum member count is pinned in five places
Adding `ENTRY_WITHOUT_PROTECTIVE` changes: `src/domain/enums.py` (docstring says 20 members), GLOSSARY 9.1 block and the "20 members" prose (gate GL-03), `tests/test_domain_enums.py:235`, `tests/test_backtest_engine.py:534`, `tests/test_decision_alignment_bookkeeping.py:80-83` and possibly the referenced-code sets there. Research record JSONs do not enumerate zero-count members (checked: `"APPROVAL_EXPIRED"` is absent from `research-run-1-v2-3-0/*.json`), so no regeneration is expected [VERIFIED: grep this session].

### Pitfall 11: Tick interval versus `max_unprotected_ms`
A cadence at or above the deadline cannot meet it. Validate at construction (no invented number).

### Pitfall 12: Hedge mode rows
V1 refuses Hedge (`HEDGE_MODE_UNSUPPORTED`). Position rows with `position_side` LONG/SHORT must be treated as a divergence, not parsed as one-way `BOTH`.

## Code Examples

Illustrative sketches (not copy-paste). Values come from the verbatim quotes above.

### Risk-first helper (D-16)
```python
# Source: design for D-16 on the existing journal/spill patterns
async def act_then_record(*, spill, journal, event, action):
    """Write-ahead to the local spill (no DB), act, journal best-effort, then drop the spill."""
    token = spill.write(event)            # atomic tmp + fsync + os.replace; raises only on disk failure
    try:
        result = await action()           # the exchange call; never waits for the journal
    finally:
        _journal_then_discard(journal, spill, event, token)
    return result


def _journal_then_discard(journal, spill, event, token) -> None:
    try:
        journal.record(event)             # may raise StoreUnavailable during a DB outage
    except Exception:                     # noqa: BLE001 - the spill file stays and is replayed later
        return
    spill.discard(token)                  # only after the journal accepted the event
```

### Exit with operator id (D-15)
```python
# Source: design on src/reconcile/safe_mode.py exit_safe_mode (lines 284-359 read this session)
async def exit_safe_mode(self, *, operator_id: str, local_intent_fn, now_utc, preconditions=None) -> bool:
    _validate_operator_id(operator_id)
    if local_intent_fn is None:
        raise ValueError("exit needs a local intent source (F-711)")
    orders, algos, positions = local_intent_fn()          # a callable that read the store, even if empty
    diff = self._compare(local_open_orders=orders, local_open_algos=algos,
                         local_open_positions=positions, **await self._truth())
    if not diff.agreement or (preconditions and not preconditions.ok):
        return False
    self._journal_safe_mode_event(event_type="SAFE_MODE_EXIT", reason="operator_exit",
                                  now_utc=now_utc, operator_id=operator_id)   # journal FIRST
    self._store.save(self._exit_state(operator_id, now_utc))                  # persist SECOND
    self._in_safe_mode = False                                                # flip LAST
    return True
```

### Cancel verification (F-502)
```python
# Source: design; adapter contract unchanged
async def confirm_entry_cancel(adapter, *, symbol, client_order_id) -> CancelVerdict:
    probe = await adapter.query_order_by_client(symbol=symbol, orig_client_order_id=client_order_id)
    if probe.found is not True:
        return CancelVerdict.UNKNOWN                 # absent right after a cancel is not proof (Q5 reasoning)
    if probe.status == "CANCELED":
        return CancelVerdict.CANCELED
    if probe.status in ("FILLED", "PARTIALLY_FILLED"):
        return CancelVerdict.FILLED_OR_PARTIAL       # hand to the protection coordinator
    return CancelVerdict.STILL_OPEN
```
(Status strings are the Binance order statuses already used in `protection.py` `TERMINAL_ENTRY_STATUSES` = `{"FILLED", "CANCELED", "EXPIRED", "EXPIRED_IN_MATCH"}` and `FILLED_ENTRY_STATUSES` = `{"PARTIALLY_FILLED", "FILLED"}` [VERIFIED: src/execution/protection.py:192-195].)

### Foreign-order reverse pass (D-01/D-02)
```python
# Source: design on compare.py
for truth in truth_normal_orders:
    cid = truth.client_order_id
    if cid in local_normal_by_client_id:
        continue
    kind = (DIVERGENCE_KIND_UNSYNCED_NORMAL if is_system_client_id(cid)
            else DIVERGENCE_KIND_FOREIGN_ORDER)
    divergences.append(Divergence(kind=kind, symbol=truth.symbol, order_role="UNKNOWN",
                                  client_order_id=cid, client_algo_id=None,
                                  reason="exchange order with no local intent"))
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Cancel-only reconciler, never re-places (Phase 8 D-03, Phase 9 D-02) | D034: SAFE_MODE blocks entries only; D077 narrows re-placement to never-confirmed stops; lost confirmed stops are decided by the position | 2026-09-30 (D034), 2026-10-20 (D077) | Tests and docs asserting "never places" are wrong (F-604); docs 9 and SECURITY section 7 still describe auto re-placement of a lost stop and conflict with D077 |
| Entry-time SL (pre-fill) | Fill-driven stop after the first fill, GTD LIMIT entry, no entry-time stop (Phase 19 D-10; Demo -4509) | 2026-10-20 | F-401 wording must change (D-05) |
| Conditional orders via `/fapi/v1/order` | `POST /fapi/v1/algoOrder` (`algoType=CONDITIONAL`) | Dec 2025 | Query/cancel by `clientAlgoId`; the repo already uses it |
| In-memory SAFE_MODE | Append-only `system_state_events` + `rehydrate` | Phase 17 | Wiring is this phase |

**Deprecated/outdated in the repo:** `SAFE_MODE_TICK_SECONDS`; `OUTCOME_NO_PLACE_ORDER_INVARIANT`; the docstring claims in `src/reconcile/__init__.py` ("NEVER places a new order") and `compare.py` ("never swept - the sweeper never places rescue protection").

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Whether Binance auto-cancels a `closePosition` algo order when the position is closed manually is unknown. The official New Algo Order and Cancel Algo Order pages are silent. The code must handle both (D-28). | Findings F14, Pitfall 5 | If the exchange does auto-cancel, an ACTIVE stop vanishing after a manual close will look like "stop lost" and trigger CLOSE_REQUIRED on an already-flat position: harmless (flat) but noisy. If it does not, orphans remain and the sweeper handles them. |
| A2 | Weights of `GET /fapi/v1/openOrders`, the open-algo-orders endpoint and `positionInformationV3` could not be confirmed (page fetches truncated). Confirmed on the Trade page: Query Order 1, Query Algo Order 1, Cancel Algo Order 1, New Algo Order 1 on the 10 s and 1 min ORDER limits and 0 IP weight. | Pattern 5 | A cadence chosen later by the owner may exceed the IP-weight budget. Owner/planner re-read the three pages before fixing `reconcile.tick_interval_ms`. [ASSUMED] for the three read endpoints. |
| A3 | A Telegram message limit and per-chat rate (about 1 message per second per chat) shape the alert queue. Not verified this session; the repo's `docs/SOURCES.md` records Telegram wording as not verified against the live service. | Pattern 4 | A burst of alerts could be rate limited; the bounded retry honours `retry_after`, and dedupe lowers the rate. [ASSUMED] |
| A4 | A manual order placed by the owner in the Binance UI will not carry the `x-`/`xa-`/`xc-` prefixes. | Pitfall 9, Pattern 1 | A UI order with such a prefix would be classified as UNSYNCED instead of FOREIGN (still a divergence and an alert). Low impact. [ASSUMED] |
| A5 | Recommended extra SAFE_MODE exit preconditions (no unresolved intent, no OPEN pending action, gate open, stream LIVE, nothing UNPROTECTED) are acceptable to the owner; D-15 mandates only operator id + a clean compare. | Pattern 3 | Owner may want fewer or more gates. Confirm before building (Q-C). [ASSUMED] |
| A6 | A bound check (`abs(exchange) <= intended quantity`, sign from the plan side) is accepted as the "signed amount" comparison because no local fills ledger exists. | Pattern 1 | A small over-fill below the intended quantity is not detected; only a ledger gives equality. Confirm with the owner (Q-B). [ASSUMED] |
| A7 | Position `position_side` is "BOTH" in one-way mode and a LONG/SHORT row means Hedge (unsupported). From `PositionSnapshot` docstring: "The Binance-reported side (LONG / SHORT / BOTH)". | Pitfall 12 | If a one-way account ever reports LONG/SHORT rows, they would be flagged as divergences (fail closed). Low impact. |
| A8 | The sync PG stores can be called from async paths without `to_thread` in this phase, as in Phase 19, with bounded waits from `engine.py`. | Pitfall 6 | A DB outage stalls the loop for up to the connect timeout per call. The spill-first rule keeps risk actions out of that path. |

## Open Questions

Items 1-7 are OWNER-OPEN or owner-adjacent: the plan must flag them, not decide them.

1. **D-20 reserved priority for risk-reducing calls (OWNER-OPEN, Q4).** Not defined. What I found that bears on it: the gate is a single process-wide pause with no priority concept; `-1008` exempts reduce-only/close-position (and, per the general-info page, cancel) from system-level throttling but not from 429/418 [CITED: general-info]; protective calls cost 0 IP weight on placement (order-count limits only) and 1 on cancel/query. Candidate meanings for the owner: (a) request-weight headroom reserved for protective calls, (b) queue ordering so a pending close/stop/cancel is the first thing sent when the gate opens (cheap, fits Pattern 10), (c) a separate budget for reads. Build nothing; plan only the question. Recommendation: offer (b) as the default reading because it needs no new number.
2. **The numbers (O-04, T-06).** Proposed key NAMES only, all `NOT_CONFIGURED`, provenance `NOT_CONFIGURED`: `reconcile.tick_interval_ms` (replaces `SAFE_MODE_TICK_SECONDS`), `reconcile.entry_unknown_probe_count`, `reconcile.entry_unknown_probe_interval_ms`, `stale_feed.max_mark_price_age_ms` (separate from `pre_placement.max_mark_price_age_ms`, which gates placement), `stale_feed.max_user_data_silence_ms`, `alerts.dedupe_window_ms`, `reconcile.lot_filter_refresh_interval_ms`. `protection.entry_unknown_grace_ms` already exists. Note `src/paper/coverage.py` already has `max_ws_message_silence_seconds` for the paper runtime (a separate, user-owned number): decide whether the live WS-silence key may reuse it (it should not, different process). Where they live is Q-F.
3. **D-24 which NO_TRADE outcomes alert.** CONTEXT defaults: `ENTRY_REFUSED_BEFORE_SEND` and `EXCHANGE_CONSTRAINT` are journaled, not alerted. Confirm.
4. **D-05/F12 wording change vs the owner's O-01 gate.** Provide proposed text for ROADMAP criterion 2 and REQUIREMENTS RISK-03 and ask; do not edit the criterion silently.
5. **D-11 closing rule (numbers are the owner's).** Proposed shape, no numbers: an UNKNOWN ENTRY closes as `REJECTED` only when ALL hold: N consecutive probes by client order id (N = `reconcile.entry_unknown_probe_count`) answer a clean `found=False` spaced by `reconcile.entry_unknown_probe_interval_ms`; the GTD time plus `protection.entry_unknown_grace_ms` has passed (the entry cannot still be live: GTD ends it, A2 of the Phase 19 register assumes EXPIRED/terminal and is unobserved); a position read AND an open-orders read show no exposure and no open order for the symbol; each step is journaled with `ExitEvidence(REST_RECONCILE, ...)`. Otherwise it stays UNKNOWN and SAFE_MODE stays. Open: is `REJECTED` the right terminal for "never existed" or should a closing note distinguish it (the intent table has only ACKED/REJECTED as terminals)? Also an INTENDED (never SENT) ENTRY is provably unsent because `mark_sent` commits before `place_entry`; recommend keeping the existing REJECTED rule for INTENDED only.
6. **Operator identity.** `operator_id` is a free non-empty string in `LiveEnablementController`. Is any allow-list or second factor required before Phase 23/24 (Telegram chat id)? Recommend recording the id and leaving authorization to Phase 23/24.
7. **G4-035 manual-close behaviour.** Unobserved (A1). Phase 25 proves it on Demo; Phase 20 handles both.
8. **Q-A: Should rebuild source be journal-only (as D-08 says) or add a persisted protection-state table?** D-08 locks "journal and intent rows". Risk: journal rows are best-effort and can be missing exactly during a DB outage. Recommendation: follow D-08 with the conservative degrade rule and the spill as a second source for the closer; revisit only if the rebuild tests show gaps.
9. **Q-B: Who writes `positions` rows (D-13) and is there a fills ledger?** No production writer exists (F3). Options: the reconcile tick inserts/updates a Position row per symbol when it observes exposure for a tracked plan (`insert_position` then the new `update_position_snapshot`), or D-13 is limited to the store method with tests. Needs a decision on `position_id` derivation (content hash of plan_hash + symbol).
10. **Q-C: Extra SAFE_MODE exit preconditions (A5).**
11. **Q-E: WR-03 event-time ordering** (F13). Recommend deferring with a written reason to Phase 24 (where Order rows start to exist) unless the owner wants the column and monotonic rule now.
12. **Q-F: Where the new numbers live** (same `execution-limits-v1.toml` with new sections vs a separate file).
13. **Q-G: A separate `PROTECTIVE_REJECTED` alert event?** B5 and `TP_UNAVAILABLE` already alert under their own names.
14. **Q-H: WARNING / DAILY_STOP producers** arrive with Phase 21; Phase 20 ships the event types and a test-only trigger. Confirm that this satisfies OPS-05 for this phase.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python via `uv run` | everything | yes | 3.13.15 (uv 0.12.17) | - |
| PostgreSQL (tests `*_pg.py`, migration 0007) | pending actions, SAFE_MODE store, lot filters, position snapshot tests | yes: `TEST_DATABASE_URL` is set in the environment (value not read); `pg_isready` is not on PATH | PostgreSQL 17.x per STATE.md (native Windows service) | `*_pg.py` tests skip when unset; `TRADING_CI_STRICT=1` turns the skip into a failure |
| Docker | `-m docker` suite only | yes | 29.8.0 | not needed for this phase |
| Binance / Telegram network | none (fakes) | not used | - | owner runs Demo later |
| `.codegraph/` | agent exploration | yes | - | - |

**Missing dependencies with no fallback:** none. **With fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >= 9, pytest-asyncio >= 1.4 (`asyncio_mode = "auto"`), pytest-xdist >= 3.8.0 [VERIFIED: pyproject.toml:36-48] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_reconcile_compare_v2.py tests/test_safe_mode_exit_operator.py -x -q` (a per-task targeted file) |
| Wave command | `uv run pytest -m "not docker" -n 4 tests/test_reconcile*.py tests/test_safe_mode*.py tests/test_risk_first_spill.py tests/test_protection*.py tests/test_emergency_close*.py tests/test_alerts.py tests/test_drills.py` |
| Full suite command | `uv run pytest -m "not docker"` sequential with `TEST_DATABASE_URL` set and `TRADING_CI_STRICT=1` (the recorded gate form); `-n 4` for development |
| Static gates | `uv run ruff check && uv run ruff format --check`, `uv run mypy src`, `uv lock --check`, `uv run python scripts/verify_decision_alignment.py all` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EXEC-02 | Doubled, sign-flipped, foreign, TP-only, no-stop, duplicate-id fixtures are divergences; clean fixture agrees; resting-entry protective is not an orphan | unit (pure) | `uv run pytest tests/test_reconcile_compare_v2.py -x` | no - Wave 0 |
| EXEC-02 | `tick` reads three sources, classifies, enters SAFE_MODE, sweeps only orphans, delegates stop-lost, skips reads under a gate restriction | unit + fake exchange | `uv run pytest tests/test_reconcile_loop.py -x` | no - Wave 0 |
| EXEC-02 | Stream `SINK_FAILURE` and supervisor `TASK_DIED` produce actionable divergences | unit | `uv run pytest tests/test_reconcile_loop.py::test_stream_divergences -x` | no - Wave 0 |
| EXEC-02 | UNKNOWN exits carry `ExitEvidence(REST_RECONCILE)`; positions snapshot updated | PG | `uv run pytest tests/test_position_snapshot_pg.py -x` | no - Wave 0 |
| EXEC-02 | D-11 UNKNOWN-entry closing rule and F5 ordering | unit | `uv run pytest tests/test_intent_recovery_unknown_entry.py -x` | no - Wave 0 |
| OPS-01 | SAFE_MODE persisted on enter, rehydrated, unreadable store => in SAFE_MODE, exit needs operator id + local intent + clean compare, restart never exits | unit + PG | `uv run pytest tests/test_safe_mode_persistence.py tests/test_safe_mode_persistence_pg.py tests/test_safe_mode_exit_operator.py -x` | no - Wave 0 |
| OPS-01 | Drills UNPROTECTED, STALE_FEED, MANUAL_CLOSE under the new rule; outcomes emitted; restore drill uses operator id | unit | `uv run pytest tests/test_drills.py -x` | yes (rewrite) |
| OPS-01 | DB outage never blocks disable / cancel / close; journal always raising; spill replay idempotent | unit | `uv run pytest tests/test_risk_first_spill.py -x` | no - Wave 0 |
| RISK-03 | No call removes or loosens an open position's stop; re-placement price == plan SL; manual close cancels legs only after two flat reads | unit | `uv run pytest tests/test_manual_controls.py tests/test_protection_supervision.py -x` | no - Wave 0 |
| RISK-03 | Rebuild keeps `stop_lost_at` and never re-places; closer pending attempt restored | unit + PG | `uv run pytest tests/test_protection_rebuild.py -x` | no - Wave 0 |
| RISK-03 / Q4 | 429/418 pending actions persisted, worked off after the gate opens by reading state first, superseded by CLOSE_REQUIRED, stale stop never sent | PG + fake gate | `uv run pytest tests/test_pending_actions_pg.py -x` | no - Wave 0 |
| RISK-03 / Q3 | Emergency close uses stored filters flagged stale, entries never do, no filters => stays CLOSE_REQUIRED + alert, quantity floored | unit | `uv run pytest tests/test_emergency_close_filters.py -x` | no - Wave 0 |
| EXEC-06 | Five controls exist and obey D-06 / D-16; operator id recorded | unit | `uv run pytest tests/test_manual_controls.py -x` | no - Wave 0 |
| F-502 | `-2011` cancel verified by query; FILLED after cancel is not "canceled" | unit | `uv run pytest tests/test_cancel_verification.py -x` | no - Wave 0 |
| OPS-05 | Each OPS-05 event reaches the sink; journal first; Telegram failure journaled; message retried, order never; dedupe; no secret in text | unit | `uv run pytest tests/test_alerts.py -x` | no - Wave 0 |
| G3-005 | Enum member + GLOSSARY parity (21) | unit | `uv run pytest tests/test_domain_enums.py tests/test_decision_alignment_bookkeeping.py -x` | yes (update) |
| Guards | No wall clock / no `float` / no SDK / no placement call in new `src/reconcile` and new ops modules; new limit keys guarded | AST | `uv run pytest tests/test_phase20_gate.py tests/test_no_unratified_defaults.py -x` | partly |

### Sampling Rate
- **Per task commit:** the single targeted test file(s) of that task.
- **Per wave merge:** the wave command above plus `uv run ruff check && uv run mypy src`.
- **Phase gate:** the orchestrator runs the full suite once, sequentially, on a clean tracked tree with `TEST_DATABASE_URL` and `TRADING_CI_STRICT=1`; saved under the phase `evidence/` directory (AGENTS.md "recorded gate"). Subagents run only their own tests.

### Wave 0 Gaps
- [ ] `tests/support/reconcile_doubles.py`: recording alert sink, journal that can raise on demand, temp-dir spill, local-intent builders, a fake `RestRateLimitGate`-like restriction source.
- [ ] Extend `tests/support/fake_binance_exchange.py` (845 lines, signature-bound to the real adapter): ability to seed an exchange-only order, a doubled/negative position, duplicate client ids; confirm `cancel_*` can model "absent" vs "filled".
- [ ] Extend `tests/support/execution_limits.py` `TEST_ONLY_EXECUTION_LIMIT_VALUES` with the new keys (odd-looking fake values, labelled TEST_ONLY).
- [ ] `tests/test_phase20_gate.py` with AST guards from `tests/support/ast_guards.py` (`wall_clock_calls`, `float_constructor_calls`, `forbidden_imports`).
- [ ] Migration 0007 parity (ORM declared, named CHECKs) in `tests/test_persistence_migration_pg.py` style.

## Security Domain

`security_enforcement` is true in `.planning/config.json`. [VERIFIED: config read this session]

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | partly | Operator identity for SAFE_MODE exit and manual controls is a recorded string in this phase; real authentication of the operator is Phase 23/24 (Telegram chat allow-list). Do not claim more. |
| V3 Session Management | no | No sessions. |
| V4 Access Control | yes | Exit and manual controls require `operator_id`; foreign orders are never cancelled; the reconcile package cannot place orders (static guard). |
| V5 Input Validation | yes | Frozen dataclasses with explicit validation (existing style); `operator_id` non-empty; spill file names derived from validated event ids only (no path from external text). |
| V6 Cryptography | no new use | `content_hash_event_id` (sha256) already exists; do not add hand-rolled crypto. |
| V7 Error handling / logging | yes | Exception CLASS names only in journal and alerts (D-21); `src/ops/redaction.py` for logs; alert templates fixed. |
| V8 Data protection | yes | Spill directory holds journal event payloads (no credentials by construction); create with restrictive permissions where the OS allows (Windows ACLs are not POSIX modes: see `.planning/WINDOWS.md`). |
| V10 Malicious code / supply chain | yes | No new dependency. |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Alert injection through exchange-supplied text | Tampering | Alert body from fixed templates + enum values; never exchange text |
| Secret leakage in an alert or journal row | Information disclosure | No URL/token/DB string in any alert; test with a poisoned exception message |
| Spill tampering or replay of a forged record | Tampering | Journal replay is idempotent by deterministic id and rejects a different event under an existing id (`JournalConflict`); spill names validated |
| SAFE_MODE exit without operator | Elevation of privilege | `operator_id` required; local intent mandatory; fail-closed rehydrate |
| Alert flood / denial of operator attention | Denial of service | Per-episode dedupe; bounded retry budget |
| Stale stop sent after policy requires a close | Tampering with state | Pending STOP superseded when the plan is CLOSE_*; payload never stored |
| Race: two ticks acting on the same divergence | Tampering | Step lock (as in `ProtectionCoordinator.step`), idempotent deterministic ids |
| Repudiation of a manual close | Repudiation | Operator id + journal row + spill record for every manual control |

## Sources

### Primary (HIGH confidence): files read in full or in the relevant range this session
- `.planning/phases/20-reconcile-safe-mode-hardening/20-CONTEXT.md`, `20-NOTES.md`
- `src/reconcile/compare.py`, `safe_mode.py`, `sweeper.py`, `__init__.py`
- `src/execution/protection.py` (1-440, 440-780, 771-930, 930-1350, 1500-1825), `emergency_close.py` (1-140, 140-480, 476-555, 730-847), `manager.py` (440-470, 980-1075, 1880-2268), `intent_recovery.py`, `intent_store.py`, `enablement.py`, `execution_limits.py`, `constraint_snapshot.py` (1-250), `live_context.py`, `order_ids.py` (1-80)
- `src/persistence/system_state.py`, `journal.py`, `entities.py` (300-380, 460-690), `snapshots.py` (1-60), `src/db/models.py` (520-630, 670-712, 860-905)
- `src/adapters/binance_usdm.py` (255-490, 820-1105), `binance_ratelimit_gate.py`, `binance_userdata_router.py` (200-330), `binance_userdata_supervisor.py` (60-130), `telegram_notify.py` (255-420), `src/paper/shadow.py` (670-800)
- `src/ops/drills.py` (40-170, 450-600, 778-945), `src/domain/enums.py` (122-160, 259-304), `src/domain/stream_records.py` (64-150), `src/domain/exchange_errors.py` (59-130)
- `docs/DECISIONS.md` rows D034, D051, D055, D058, D077, D078; `docs/trading/EXECUTION_SPEC.md` sections 9-11; `docs/operations/SECURITY_AND_OPERATIONS.md` sections 4-8; `docs/GLOSSARY.md` section 9; `.planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md`; `.planning/audits/2026-09-29-deep-audit/DEEP_AUDIT_REPORT.md` (F-701, F-401, F-702 sections; F-502/F-711/F-127/F-106/F-604 rows); `.planning/phases/09-live-execution-rollout/09-REVIEW-FIX.md` (WR-07); `08-REVIEW.md` (IN-08, IN-13, IN-14, IN-15); ROADMAP Phase 20; REQUIREMENTS
- Tests: `tests/test_reconcile.py`, `tests/test_drills.py` (old-rule locations), `tests/support/*` (outlines), `tests/test_no_unratified_defaults.py` (header)

### Secondary (MEDIUM confidence): official Binance pages fetched this session (page fetches were sometimes truncated)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order (closePosition semantics; silent on auto-cancel; weights)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Cancel-Algo-Order (cancel/query algo; retention 3 days / 90 days; weights)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info (429/418, -1008 exemption wording)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/error-code (-1006, -1007, -1008, -2011, -2013, -2021, -2022, -2024, -4116, -4137, -4138; -4509 not listed)
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Position-Information-V3 (page returned the Trade endpoint table only)

### Tertiary (LOW confidence)
- WebSearch for "closePosition STOP_MARKET auto canceled on manual close": no Binance-authoritative result; other exchanges only. Used only to confirm absence of an official statement.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH (no new package; pyproject read)
- Architecture: MEDIUM-HIGH (patterns derive from code read in full; the local-intent derivation and rebuild have not been run, and Q-A/Q-B are open)
- Pitfalls: HIGH for F1, F2, F5, F6, F9 (read in code); MEDIUM for Windows spill behaviour (documented by repo comments, not exercised)
- Exchange behaviour: MEDIUM for 429/418, -2011, -1008 (official pages); ASSUMED for manual-close auto-cancel and read-endpoint weights

**Research date:** 2026-10-20
**Valid until:** 2026-11-03 for the Binance facts (re-read before Phase 25); the code facts hold until the next commit touching `src/reconcile`, `src/execution/protection.py`, `emergency_close.py` or `manager.py`.
