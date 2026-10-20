# Phase 20: Reconcile + SAFE_MODE Hardening + Alerts - Context

**Gathered:** 2026-10-20
**Status:** Ready for planning (gathered with `--auto`; items marked OWNER-OPEN must not be implemented until the owner decides)

<domain>
## Phase Boundary

Reconciliation sees every dangerous divergence. A protective stop is never canceled or left missing. SAFE_MODE survives restarts and exiting it needs an operator. A DB outage never blocks a risk-reducing action. Operational alerts have a real sender.

Requirements: EXEC-02, OPS-01, RISK-03, EXEC-06, OPS-05 (ROADMAP.md Phase 20, five success criteria).

Out of scope (stays elsewhere): account equity and daily loss from Binance (Phase 21), leverage and liquidation guard (22), Telegram UX, two-step confirm and money amounts (23), the running live process and the caller wiring of intent recovery (24), the Demo campaign and the manual-close Demo proof (25). No Telegram, Binance or EC2 connection is needed to plan or build; tests use fakes and the local PostgreSQL 17. All evidence is fake-exchange agreement, not Demo or mainnet.

Gathered with `--auto`, single pass. The input is `20-NOTES.md` plus ROADMAP Phase 20 and its inherited items.
</domain>

<decisions>
## Implementation Decisions

All decisions below are the recommended option, or the direction the owner already recorded in `20-NOTES.md` (Q3, Q4, Q5, D077). Nothing here edits `docs/DECISIONS.md`. No number is invented: every window, probe count, threshold and cadence is a `NOT_CONFIGURED` key (O-04) and the live path refuses while it is unset.

### Compare: reverse pass and signed amounts (criterion 1, F-701)
- **D-01:** `src/reconcile/compare.py` stays pure. It gains: a reverse pass over exchange normal and algo orders (an exchange order with no local intent is a divergence), a per-position signed-amount comparison (sign and magnitude), and a rule that every open exchange position has an ACTIVE STOP on the exchange. New `Divergence` kinds are added to `_DIVERGENCE_KINDS` for: doubled position, sign-flipped position, foreign order, TP-only position, position without stop. The existing five kinds keep their names and meaning.
- **D-02:** A foreign order (not created by this system, by client id prefix) is a divergence and an alert, never swept and never canceled. Only `ORPHAN_PROTECTIVE` stays sweepable, as today.
- **D-03:** Duplicate exchange client ids no longer collapse silently in the compare index (G2-019, 08-REVIEW IN-15): they become a divergence. Skipped sweeper cancels (IN-14) leave a journal row. — **Reversibility:** reversible.
- **D-04:** `StreamDivergenceKind.SINK_FAILURE` and the supervisor halt `TASK_DIED` (Phase 18) map to divergences the reconciler acts on, not only logs (20-NOTES, Phase 18 review).

### Protection supervision and re-placement (criterion 2, D034, D077, RISK-03)
- **D-05:** Criterion 2 wording is reconciled with D077 and D-10 of Phase 19. There is no entry-time SL (the stop is placed after the first fill), so "the entry-time SL of a resting entry is never an orphan (F-401)" becomes: a protective of a plan whose entry is still resting or partially filled is never classified as an orphan. The wording change goes to ROADMAP and REQUIREMENTS in the same plan as the code. It stays tied to the open D055 closure; D055 is not closed here.
- **D-06:** A stop that was confirmed ACTIVE and later reads absent or not active is decided by the position, as in D077: confirmed exposure is a MARKET close (CLOSE_REQUIRED); unreadable or flat-but-entry-can-still-fill goes back to `UNPROTECTED` (blocking) with `stop_lost_at` set once. A stop is NOT blindly re-placed. A re-placement, where policy allows one, restores the original plan stop, never a wider one (RISK-03), and only after the position is reconciled first.
- **D-07:** Supervision continues after `PROTECTED`, `COMPLETE` and `TP_UNAVAILABLE`: while a position is open the reconciler checks that its stop is still ACTIVE. A stop cancelled or lost later is a divergence, not invisible.
- **D-08:** `stop_lost_at` and the coordinator's pending state are rebuilt on restart from the journal and intent rows, never restarted: the rebuild must not reset the `max_unprotected_ms` clock and must not re-place a stop (G4-029). This includes the closer's pending `EMERGENCY_CLOSE` attempt (`pre_send` / `ambiguous` rows), so an ambiguous attempt the exchange does not show is not forgotten and its number is not reissued. — **Reversibility:** costly — the rebuild reads rows shaped by Phases 17 and 19; changing it later touches the coordinator, the closer and the stores.
- **D-09:** Expiry and emergency close follow the WR-07 ordering rules, defined here (G2-026): expiry cancels a plan's protective legs only with zero fills, using the coordinator's fill state as the source; the emergency close is a reduce-only MARKET order (Phase 19 D-15), and the plan is never declared safe on a flat-confirmation alone. An executed plan stays `APPROVED` and is never moved to `EXPIRED` (G4-036).
- **D-10:** `ENTRY_WITHOUT_PROTECTIVE` is promoted into the `RejectionReason` enum and GLOSSARY 9.3 is updated (G3-005, D044).

### Closing what Q5 leaves UNKNOWN (OWNER-OPEN numbers)
- **D-11:** `resolve_unresolved_intents` no longer records a not-found ENTRY intent that went `UNKNOWN` after an ambiguous error as `REJECTED`. Such an entry is closed only after repeated probes, the GTD expiry passing, and a clean position-and-open-order reconciliation, each with its evidence source written to the journal (G4-034, D051). The probe count, the window and `protection.entry_unknown_grace_ms` stay `NOT_CONFIGURED` (O-04); the owner sets them. A placement is never re-sent (Q5).
- **D-12:** Every Order or Position move out of `UNKNOWN` needs Binance evidence (REST reconcile or a user-data event) and records the evidence source.
- **D-13:** Reconcile updates position quantity and PnL through a new store method (`update_position_snapshot`, G4-043).

### SAFE_MODE durability and operator exit (criterion 3, F-711, F-127)
- **D-14:** SAFE_MODE is persisted. `SafeModeController.state_snapshot` / `rehydrate` already exist; this phase adds the durable store write on enter and the load on start. Entering flips first and fails closed on a store failure; exit is journaled first (17-REVIEW WR-03 ordering stays).
- **D-15:** Exit needs an operator id recorded with the exit event, and still needs a fresh clean three-source compare. A boolean flip, a restart or a timer never exits SAFE_MODE. — **Reversibility:** costly — the operator-id field enters the persisted SAFE_MODE schema and the exit event; undoing it needs a migration.
- **D-16:** Risk-reducing actions execute first and are journaled afterwards, with a fallback when the journal or DB is down (F-702): `disable`, `expire_pending_entry`, `cancel_untriggered_protectives` and `emergency_manual_close` do not wait for the journal. The fallback keeps the record in a local durable spill that is replayed into the journal later. A DB outage never blocks them; it does block a new entry.
- **D-17:** A `-2011` cancel result is verified by a post-cancel query (F-502): the order is not counted canceled until the query shows it gone.

### Rate-limit pause versus protection (Q4, OWNER decided 2026-10-20)
- **D-18:** An HTTP 429/418 pause is never bypassed. `Retry-After` is honoured, otherwise the configured cooldown; never assume the pause ended. `-1008` is not a rate-limit pause (quick task 261020-g1a).
- **D-19:** Before sending, the intent of a protective stop, an entry cancel or an emergency close is recorded durably; when the gateway blocks it, the explicit pending state is recorded (`STOP_NOT_SENT`, `PROTECTION_ENTRY_CANCEL_NOT_SENT`, `CLOSE_NOT_SENT`) in a durable store that survives restart (likely a migration). When sending is allowed again the reconciler reads the current state first and then decides; an old payload is never replayed blindly. If `max_unprotected_ms` runs out during the wait the plan moves to CLOSE_REQUIRED, and a queued old stop is not sent when policy already requires a close. — **Reversibility:** costly — a new table or column plus a state machine used by three actions.
- **D-20:** "Reserved priority for risk-reducing calls" is OWNER-OPEN: it is not defined. Plan it as a question for the owner (for example request-weight headroom or a queue ordering rule) and build nothing for it until answered. The queue never claims that a position always has a stop under every rate-limit condition.

### Emergency close without exchangeInfo (Q3, OWNER decided 2026-10-20)
- **D-21:** The emergency close only may use the last validated MARKET_LOT_SIZE filters, stored with a `filters_stale` flag and the fetch time; a new entry never may. With no valid stored filters nothing is guessed: CLOSE_REQUIRED and SAFE_MODE stay, a critical alert goes out and reconciliation continues. The close quantity comes from the reconciled exposure, floored to the filters, never rounded up to reach minQty. A rejection caused by wrong filters is not re-sent; fresh filters are fetched when readable and the quantity recomputed. A split close still runs one part at a time (WR-03). The planner first checks whether `PlanConstraintSnapshot` is persisted or only in memory.

### Alerts (criterion 4, F-106, OPS-05)
- **D-22:** A real `CriticalAlertSink` sender replaces the rehearsal-only one. Order: write the alert to the journal first, then send; a Telegram send failure has its own handling (journal row, bounded message retry). Retrying a message is allowed; retrying an order is not.
- **D-23:** Alert events: unprotected position; local-vs-exchange divergence; foreign or unknown order; DAILY_STOP; stale data; auth failure; and, from T-05, a duplicate execution attempt, a rejected protective action and a daily-loss WARNING. Already emitted by code and to be wired: `CLOSE_REQUIRED`, `TP_UNAVAILABLE`, `EMERGENCY_CLOSE_FAILED`, `EMERGENCY_CLOSE_NOT_SENT`.
- **D-24:** The entry path gets alerts for SAFE_MODE reasons `ENTRY_STATE_UNKNOWN`, `PROTECTION_HANDOFF_FAILED` and `DB_FAILURE`. NO_TRADE outcomes `ENTRY_REFUSED_BEFORE_SEND` and `EXCHANGE_CONSTRAINT` are journaled, not alerted, unless the owner asks for more (OWNER-OPEN).
- **D-25:** Stale feed (D058): this phase detects and handles a missing or stale mark-price or user-data feed (execution fails closed); Phase 24 owns the LIVE enablement gate. The reconcile cadence, the stale-feed threshold and the WS-silence threshold are registry parameters with provenance labels and `NOT_CONFIGURED` values (T-06); the owner sets the numbers.

### Manual emergency controls (EXEC-06) and tests (criterion 5)
- **D-26:** The manual controls (cancel pending strategy orders, disable new entries, close strategy positions on explicit action, re-place protection, enter SAFE_MODE) are checked against EXEC-06 and gaps are closed; a close or re-placement by a human follows D-06 and D-16.
- **D-27:** Tests that assert the old rule "the reconciler never places" are rewritten (F-604) to the new rule, with the same fake-exchange style. Drills for UNPROTECTED, STALE_FEED and MANUAL_CLOSE (G2-016) are added to `src/ops/drills.py`; two drill outcomes never emitted (08-REVIEW IN-14, IN-15) are emitted.
- **D-28:** Manual close outside the system (G4-035): the code does not rely on either answer (orphan or auto-cancel). The sweeper and reconcile handle both; the behavior is proven on Demo in Phase 25, after the live Binance pages are re-read.

### Claude's Discretion
- Module layout of the new reconciler loop and the alert sender, naming of new divergence kinds, and test file split, as long as `src/core` stays pure, no wall clock is read in pure modules, and decimals are `Decimal`.
- The shape of the local durable spill for D-16, within the existing persistence patterns.

### Folded Todos
None (todo match returned 0).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase inputs
- `.planning/phases/20-reconcile-safe-mode-hardening/20-NOTES.md` — the carried items, Q3, Q4, Q5, D077 and Phase 18 review notes
- `.planning/ROADMAP.md` — Phase 20 goal, criteria and inherited items (D055, D058, G2-026, G4-035, G2-016, G4-029, G4-034, G4-043, G2-019, T-05, T-06, G3-005)
- `.planning/REQUIREMENTS.md` — EXEC-02, OPS-01, RISK-03, EXEC-06, OPS-05

### Phase 19 handoff
- `.planning/phases/19-execution-plan-binding-price-check/19-CONTEXT.md` — D-10 fill-driven protection, D-15 emergency close
- `.planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md` — open owner items and `NOT_CONFIGURED` keys
- `.planning/phases/19-execution-plan-binding-price-check/19-DEC-Q5-DRAFT.md`, `19-DEC-D055-DRAFT.md` — unwritten decisions
- `.planning/phases/19-execution-plan-binding-price-check/19-REVIEW-FIX.md` — WR-03, WR-04, WR-05 owner rulings

### Rules and specs
- `docs/DECISIONS.md` — D034, D044, D051, D055 (open), D058, D077
- `docs/execution/EXECUTION_SPEC.md` — 10.1 intent recovery
- `docs/operations/RUNBOOK.md` — the eight drills and freshness thresholds
- `docs/GLOSSARY.md` — 9.3 rejection reasons
- `docs/01_ENGINEERING_PRINCIPLES.md`, `docs/implementation/AGENT_INSTRUCTIONS.md` — fail closed, no AI in the decision path
- `.planning/audits/2026-09-29-deep-audit/DEEP_AUDIT_REPORT.md` — F-701, F-401, F-952, F-711, F-127, F-702, F-502, F-106, F-604, F-026
- `config/execution/execution-limits-v1.toml` — the `NOT_CONFIGURED` keys

No other external specs; exchange facts (algo-order endpoints, rate-limit behavior) must be re-read from the current Binance docs, not recalled.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/reconcile/compare.py`: pure three-source `compare`, `Divergence`, `CompareDiff`; five existing kinds.
- `src/reconcile/safe_mode.py`: `SafeModeController` with `state_snapshot`, `rehydrate`, `enter_safe_mode`, `exit_safe_mode` (clean compare, exit journaled first).
- `src/reconcile/sweeper.py`: `OrphanSweeper.sweep` with two zero position reads, query-by-id before cancel, `SweepSkip`.
- `src/execution/protection.py` (coordinator, `CriticalAlertSink`), `emergency_close.py` (`MarketEmergencyCloser`), `intent_recovery.py` (`resolve_unresolved_intents`), `live_context.py`, `constraint_snapshot.py`.
- `src/ops/drills.py`: the eight RUNBOOK drills.

### Established Patterns
- Compare and constraint code are pure; clocks are injected; journal-first and fail-closed ordering is tested.
- Limits live in versioned config with `NOT_CONFIGURED` keys; the live path refuses while one is unset.
- A placement is never re-sent; ambiguous results are probed once by client id.
- Tests use fake adapters; PostgreSQL tests are `*_pg.py`.

### Integration Points
- The reconciler loop is not composed into a running process (Phase 24 composes it); this phase builds the loop as a library with a fake-exchange test harness.
- Intent recovery caller wiring is Phase 24 (G4-029); the rebuild logic is here.
- Alert sender plugs into `CriticalAlertSink`; Telegram UX stays Phase 23.
- Blast radius: `SafeModeController` has 24 callers (including `scripts/demo_rehearsal.py`); `OrphanSweeper` 19; `Divergence` 2.

</code_context>

<specifics>
## Specific Ideas

No specific requirements beyond the owner's recorded Q3, Q4, Q5 and D077 behavior in `20-NOTES.md`.

</specifics>

<deferred>
## Deferred Ideas

- "Reserved priority for risk-reducing calls" (D-20) until the owner defines it.
- The numeric values of every `NOT_CONFIGURED` key (O-04, T-06) are the owner's.
- Telegram UX for alerts and approval hardening: Phase 23.
- Demo proof of manual-close behavior and the 11 Demo probes: Phase 25 and the owner.
- Writing the DECISIONS rows (D079, D080 drafts and the Q3/Q4 row): owner, after the drafts.

</deferred>

---

*Phase: 20-Reconcile + SAFE_MODE Hardening + Alerts*
*Context gathered: 2026-10-20*
