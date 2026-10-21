# Phase 20: Review Resolutions

**Date:** 2026-10-21
**Status:** Input for `/gsd-plan-phase 20`. Not a decision record. No owner decision below is adopted
until the owner confirms it; `docs/DECISIONS.md`, `.planning/ROADMAP.md` and
`.planning/REQUIREMENTS.md` are NOT edited by this file.
**Precedence:** `20-CONTEXT.md` still wins on anything it states and this file does not correct.
Where this file corrects CONTEXT (items marked CORRECTION) the planner follows this file and the
CONTEXT line is updated in the same plan.

## Evidence labels

Every claim below carries one label. Nothing here is `[DEMO]`.

- `[DOC]` read in a document or in code. No test was run.
- `[DESIGN]` a proposed design, not implemented.
- `[NOT_TESTED]` behavior expected from the design that no executed test has shown.
- `[DEMO]` observed on Binance Demo. None exists for this phase.

LIVE stays blocked: `LIVE_ORDERS_DISABLED` (`src/execution/enablement.py`), unset
`NOT_CONFIGURED` keys, and no Demo evidence.

## What the code review found (all `[DOC]`)

| # | Finding | Where |
|---|---|---|
| 1 | `ProtectionCoordinator._transition` assigns the state, bumps `seq` and journals. It checks no legality. | `src/execution/protection.py:1648` |
| 2 | `ExecutionIntentStore.record_result` takes `status`, `exchange_order_id`, `exchange_status`. No reason code. `finalize_entry_outcome` writes `outcome_reason_code`, but for the ENTRY row once, and is meant for NO_TRADE. | `src/execution/intent_store.py:144`, `src/persistence/execution_state.py:344` |
| 3 | `resolve_unresolved_intents` marks an absent intent younger than `DEFAULT_LOOKUP_WINDOW` (3 days) `REJECTED`. | `src/execution/intent_recovery.py` |
| 4 | No one-plan-per-symbol guard. `max_open_positions` limits the total only. | `src/risk/portfolio.py` |
| 5 | `RestRateLimitGate` keeps `_ban_until` and `_pause_until` in memory only. Nothing persists or restores them. After a restart the gate reports open. | `src/adapters/binance_ratelimit_gate.py` |
| 6 | A transition guard already exists for intent status: `assert_transition(kind, old, new)`, `is_legal`, `IllegalTransition` (DOMN-04). It treats an unchanged state as illegal and leaves the no-op to the caller. | `src/domain/transitions.py:259` |
| 7 | D-23 already lists `auth failure` and `a duplicate execution attempt`. No producer for either was found in `src`. | `20-CONTEXT.md` D-23 |
| 8 | WORDING, not an open policy conflict. D077 is Accepted (2026-10-20, owner): a stop that REST confirmed ACTIVE and that is later lost is never re-placed. `.planning/REQUIREMENTS.md` RISK-03 and ROADMAP Phase 20 criterion 2 still say the system re-places a missing stop automatically; they were not updated. | DECISIONS D077, REQUIREMENTS RISK-03, ROADMAP Phase 20 |
| 9 | The code DOES have a second, legitimate re-placement branch: a stop that was never confirmed and that REST proved absent is re-placed under the same client id before `max_unprotected_ms` (B2/B3), then CLOSE_REQUIRED at the deadline. An existing ACTIVE stop is adopted. | `src/execution/protection.py:33-35`, `:1013-1015`, `:1096-1098` |

## Revised task list

Each task has its own focused tests. Ids are working names; the planner assigns plan numbers.

### T-A. Protection transition guard (CORRECTION to CONTEXT D-09/D-29 scope)

- Build the allowed-transition table from the `ProtectionState` docstring and audit every
  `_transition` call site. A call the docstring does not allow is a finding to resolve, not to hide.
- Prefer a new `TransitionKind` in `src/domain/transitions.py` over a private table (finding 6).
  Check the import boundary first: `src/domain` must not import `src/execution`, so the state names
  or the edge table may have to live on the domain side.
- A rejected transition does not mutate `tracked.state` or `seq`, and leaves a journal row.
- Equal-state events are an idempotent no-op decided by the caller before the guard (finding 6).
- Clearing rules differ per critical state. Do NOT use one generic "flat twice OR stop ACTIVE" rule.
  - `UNPROTECTED` leaves only to `CLOSE_REQUIRED` or `FLAT` (docstring). It is cleared only by
    verified protection of the corresponding exposure, or by the approved flat-confirmation path.
  - `CLOSE_REQUIRED` goes to `CLOSE_FAILED` or `FLAT` only. A stop that later reads ACTIVE does not
    clear it (D077). Default clearance needs the verified-flat path (two independent fresh reads,
    D-09), a terminal entry state and completed cleanup. Any exception that returns to protected
    exposure needs explicit owner approval.
- Each transition that clears a critical state records its evidence and provenance.
- Replay after a restart passes through the same guard (D-08). A valid journal replays; an invalid
  or corrupt replay fails closed (SAFE_MODE), never silently discards a transition.
- Stop re-placement is NOT removed from the wording. The audit (finding 9) found three cases and
  the criterion text must state each one:

  | Case | Behavior | Basis |
  |---|---|---|
  | Stop never confirmed, REST proved it absent, still inside `max_unprotected_ms` | re-placed under the same client id (never blindly); an existing ACTIVE stop is adopted | `protection.py` B2/B3 `[DOC]` |
  | Stop confirmed ACTIVE, later lost or not active | never re-placed; exposure means CLOSE_REQUIRED and a reduce-only MARKET close; unreadable or flat-with-entry-open means UNPROTECTED, escalating at `max_unprotected_ms` from `stop_lost_at` | D077 `[DOC]` |
  | Stop still unconfirmed at the deadline | CLOSE_REQUIRED | B2/B3 `[DOC]` |

  The re-placed stop is built from the plan, so it keeps the plan stop and never widens risk; that
  part of RISK-03 holds for the first case only. Check once whether D034 intends the in-deadline
  re-placement; D077 item (4) says D034 "stays unchanged for a failed initial protective placement"
  without naming it. Do not assume a fourth branch exists.
- The wording change is a documentation checkpoint (O-A). It does not block the plan. It is not
  evidence that D055 is closed (D055 stays Accepted for the invariant and probe plan with the
  execution model OPEN until Probe 1) and it is not Demo validation or LIVE approval.
- Tests: forbidden downgrade of `CLOSE_REQUIRED`; clearing `UNPROTECTED` without evidence; stale or
  duplicate event after a more severe state; valid replay; corrupt replay; rejected transition
  leaves state and `seq` unchanged.
- Limit of the claim: Phase 20 has no event-time column. It detects only what ordering and
  deduplication evidence it has. It does not claim general stale-event detection (D-29 deferral to
  Phase 24 stands).

### T-B. Reconciliation result API (CORRECTION to CONTEXT D-11 last sentence)

- D-11 says the planner "confirms `record_result` accepts" `RECONCILED_ABSENT`. It does not
  (finding 2). The plan chooses, and records why:
  1. extend the result contract with an application reason code; or
  2. add a dedicated reconciliation-finalization API.
- Never write the application reason into `exchange_status` (that field carries Binance's status).
- Open to check before choosing: the intent table already has `outcome_is_no_trade` and
  `outcome_reason_code`. Check whether the ENTRY row of an ambiguous UNKNOWN entry is still
  un-finalized, and whether `outcome_is_no_trade` has a correct value for "reconciled absent". If
  both hold, option 2 may need no migration. `[NOT_TESTED]`.
- Cover the in-memory store (`InMemoryExecutionIntentStore`, used in many tests) and
  `PgExecutionStateStore`. Add one shared contract test for both. Assess call-site compatibility
  before changing `record_result`.
- Tests: `RECONCILED_ABSENT` persists with the reason; a Binance definitive rejection keeps its own
  code; the two cannot be confused.

### T-C. UNKNOWN entry recovery (D-11)

- Remove the rule that finalizes a not-found UNKNOWN entry as `REJECTED` because it is absent and
  younger than 3 days. Absence alone is not evidence: `newClientOrderId` is unique only among OPEN
  orders (`docs/integration/BINANCE.md`; `docs/SOURCES.md` records that the live page was not
  fetched, so this is `[DOC]`, not `[DEMO]`).
- Close only when ALL hold: N consecutive probes by client id answer a clean `found=False` (spaced
  by config); GTD plus `protection.entry_unknown_grace_ms` has passed; positions and open orders
  were read successfully and fresh and show no exposure and no open order for the symbol; each step
  is journaled with `ExitEvidence(REST_RECONCILE, ...)`; no source is conflicting or in error.
  Otherwise the intent stays `UNKNOWN` and SAFE_MODE stays.
- A GTD expiry does not prove the order is terminal. Assumption A2 of the Phase 19 register is
  unobserved and stays so (`[NOT_TESTED]`).
- `INTENDED` (never sent: `mark_sent` commits before `place_entry`) keeps its own path and its own
  reason code, and closes only with certain evidence that nothing was sent.
- Closing an intent does not exit SAFE_MODE (D-15).
- Tests: each missing condition keeps `UNKNOWN`; a probe error keeps `UNKNOWN`; a conflicting
  read keeps `UNKNOWN`; the full protocol closes with the new reason; `INTENDED` path unchanged.

### T-D. REST gate persistence and restart recovery (NEW, owner decision needed)

- `restriction()` shows only what is known in memory (finding 5). An open gate is not proof that
  Binance REST is healthy.
- Specify the authoritative mechanism, and do not assume D-16 spill provides it.
  Preferred (reviewer, 2026-10-21): include the minimum durable recovery in Phase 20, because it
  also feeds the Q4 REST-action queue and the A5 exit condition.
  1. PREFERRED: persist the UTC deadlines of each recorded 418 ban and 429 pause and restore them
     at start. `[DESIGN]`.
  2. If full persistence is deferred to Phase 24: a startup recovery barrier that is implemented
     AND tested in Phase 20. After a restart the empty in-memory state is not proof that the gate
     may dispatch. The plan documents how the gate is revalidated before ordinary dispatch resumes
     (for example an assumed cooldown from a new `NOT_CONFIGURED` key, which needs an owner number).
  3. NOT acceptable: keep today's behavior silently while claiming A5 readiness.
- Restore the restriction BEFORE any gated REST dispatch and before a SAFE_MODE exit.
- An open `restriction()` means only "no currently known restriction". It is not proof that REST
  is healthy; fresh successful Binance reads stay mandatory.
- Fail closed when restoration or persistence fails. Never initialize an unknown recovered state as
  unrestricted.
- Tests: restart with an active 418 ban; with an active 429 pause; with an expired restriction;
  with missing durable state; with corrupt durable state; with a persistence failure on record.
- This is scope beyond `20-NOTES.md` Q4, which asks for a durable record of the protective INTENT
  only. It needs owner confirmation before it is planned in full.

### T-E. SAFE_MODE durability and exit (D-14, D-15)

The exit readiness list is closed. Each condition is independently testable, and each failure case
has its own test.

| # | Condition | Status |
|---|---|---|
| 1 | Non-empty operator id recorded with the exit event (audit metadata, not authentication) | D-15 |
| 2 | Local intent source read successfully. A missing or unreadable source blocks the exit and is never turned into an empty list | D-15, fixes `local_open_orders or []` (F-711) |
| 3 | Positions, open orders and algo orders read successfully from Binance and fresh | D-15 |
| 4 | Compare is clean: no divergence | D-15 |
| 5 | No `UNKNOWN` intent, no `UNPROTECTED`, no `CLOSE_REQUIRED`, no pending safety action | D-15 |
| 6 | REST gate open (`restriction()` is `None`) AND, after T-D, restored | **PENDING A5, owner** |
| 7 | `StreamState.LIVE` | **PENDING A5, owner** |

- An open gate alone never satisfies condition 3: fresh successful Binance reads are required.
- Conditions 6 and 7 are not approved because a reviewer recommended them. Inspect and test the
  semantics of `check()` and `restriction()` before using them as a predicate.
- A boolean flip, a restart or a timer never exits SAFE_MODE.
- Operator authentication or an allow-list is Phase 23/24 and must exist before any LIVE path.

### T-F. Symbol invariant (NEW policy, owner confirmation needed)

- Narrow scope only: detect more than one active plan, or ambiguous exposure ownership, for the
  same symbol during reconciliation, then fail closed. No plan-ingress rejection unless the owner
  approves the larger scope.
- This is a new policy. It is NOT a D-13 decision and must not be attributed to it.
- The plan names the local data source that identifies active plans. Candidates to check:
  protection coordinator state rebuilt from the journal (D-08) and the intent rows. No complete
  `positions` table and no production `Order` writer exist (D-13), so neither may be assumed.
- Binance stays authoritative for positions and orders. Durable intent rows plus replayed journal
  state are evidence for ownership, never sufficient alone. Evaluate whether they can identify
  active plans reliably before relying on them.
- If exposure cannot be mapped to one plan unambiguously, fail closed. Do not guess.
- Conflict state: SAFE_MODE with a specific journal reason (a new reason needs its own row in
  `docs/GLOSSARY.md` section 9.4, the same place as `ENTRY_STATE_UNKNOWN`). It does NOT go
  straight to CLOSE_REQUIRED. If protection is independently unverified, the D077 protection-state
  rules apply on top; CLOSE_REQUIRED only when its own conditions are met or an approved policy
  says so.
- How stale or unreadable data is handled is stated in the plan and tested.
- The D-13 bound check stays: exchange absolute position must not exceed the intended quantity, and
  the sign must match the plan side. It does not detect an over-fill below the intended quantity
  (A6). It is not called exact position reconciliation.

### T-G. Alerts and the OPS-05 acceptance matrix

For each row the plan fills: event contract, actual producer, journal-first behavior, dedupe and
retry expectation, focused test. A test-only trigger is not end-to-end production coverage.

| Alert | Source of the requirement | Phase 20 delivers | Real producer |
|---|---|---|---|
| `ENTRY_STATE_UNKNOWN` | D-24 | contract, dispatcher, test | entry path (exists) |
| `PROTECTION_HANDOFF_FAILED` | D-24 | contract, dispatcher, test | entry path (exists) |
| `DB_FAILURE` | D-24 | contract, dispatcher, test | entry path (exists) |
| `PROTECTIVE_REJECTED` (definitive Binance rejection after a fill; tied to CLOSE_REQUIRED) | D-24 | new contract, dispatcher, test | protection coordinator (to wire) |
| unprotected position | OPS-05, D-23 | contract, dispatcher, test | coordinator (`CLOSE_REQUIRED` etc. exist) |
| local vs exchange divergence | OPS-05 | contract, dispatcher, test | reconcile compare (to wire) |
| unknown or foreign order | OPS-05 | contract, dispatcher, test | reconcile compare (to wire) |
| stale data | OPS-05, D-25 | contract, dispatcher, test | stale-feed detection (this phase) |
| **authentication failure** | OPS-05, D-23 | contract, dispatcher, test | **no producer found; planner states where it is wired** |
| **duplicate execution attempt** | OPS-05, D-23 (T-05) | contract, dispatcher, test | **no producer found; the duplicate-entry guard is the persisted intent (`order_ids.py`) and it raises no alert; planner states where it is wired** |
| `DAILY_STOP` | OPS-05 | contract and test trigger only | Phase 21 |
| daily-loss WARNING | OPS-05 | contract and test trigger only | Phase 21 |

- `ENTRY_REFUSED_BEFORE_SEND` and routine `EXCHANGE_CONSTRAINT` are journaled, not alerted. A
  repeated failure goes through dedupe or escalation.
- OPS-05 is NOT marked complete end-to-end by Phase 20. The acceptance criteria say which part is
  done here and which depends on Phase 21 (D-23).

### T-H. Config keys

- Add to `config/execution/execution-limits-v1.toml` under `reconcile.*`, `stale_feed.*`,
  `alerts.*`, `protection.*`, plus the README, `tests/support/execution_limits.py`, the key dict and
  `require_live_ready()`: `reconcile.tick_interval_ms` (replaces `SAFE_MODE_TICK_SECONDS = 60`),
  `reconcile.entry_unknown_probe_count`, `reconcile.entry_unknown_probe_interval_ms`,
  `reconcile.lot_filter_refresh_interval_ms`, `stale_feed.max_mark_price_age_ms`,
  `stale_feed.max_user_data_silence_ms`, `alerts.dedupe_window_ms`; a gate-cooldown key only if T-D
  chooses option 2.
- Every value stays `NOT_CONFIGURED` with a provenance label. No numeric default is invented.
  `require_live_ready()` refuses LIVE while a required key is unset or invalid.
- Do not reuse the paper runtime's `max_ws_message_silence_seconds`.

### T-I. Local spill and restart (D-16)

- The spill is new design work in this phase, not an existing capability (`[DESIGN]`).
- Rebuild state from durable intents and the journal, then reconcile with Binance. The spill is
  supplementary evidence, never a substitute for Binance truth. Journal alone is not full evidence.
- Tests: pending safety action survives restart; spill missing; spill corrupt; spill conflicts with
  the journal; spill conflicts with Binance; ambiguous recovery enters SAFE_MODE.

### T-J. Tests and drills (D-27)

- Rewrite tests that assert the old "reconciler never places" rule (F-604). Retire
  `OUTCOME_NO_PLACE_ORDER_INVARIANT`; emit `OUTCOME_SAFE_MODE_BLOCKED`.
- Add drills for UNPROTECTED, STALE_FEED and MANUAL_CLOSE (G2-016) in `src/ops/drills.py`.
- `emergency_manual_close` (`src/execution/manager.py:2224-2245`): cancel protective legs only after
  the closer confirms flat by two independent fresh reads (D-09); do not wait for the journal (D-16).

## Owner checkpoint table

| # | Decision | Needed from owner | Blocks |
|---|---|---|---|
| O-A | ALIGN ROADMAP criterion 2 and REQUIREMENTS RISK-03 wording with D077 and the three-case table in T-A. The policy itself is decided (D077). Proposed text goes in as text plus a `checkpoint:human-verify`; ROADMAP and REQUIREMENTS are not edited before the owner accepts. Not D055 closure, not Demo validation, not LIVE approval | yes (documentation) | criterion 2 counting as done; does NOT block the plan |
| O-B | A5: REST gate open and `StreamState.LIVE` as SAFE_MODE exit conditions | yes | implementing T-E conditions 6 and 7 |
| O-C | Gate persistence (T-D): persisted deadlines (preferred) or a tested startup barrier with an owner number | yes | implementing T-D, and A5 condition 6 |
| O-D | Symbol invariant policy (T-F), narrow scope, SAFE_MODE with its own reason | yes | implementing T-F |
| O-E | D-20 reading of "reserved priority" as queue ORDER, not a bypass of 429/418 and not reserved weight | yes (pending since CONTEXT) | queue work |
| O-F | D-11, D-15, D-01a, D-24 review resolutions | yes (pending since CONTEXT) | T-C, T-E, T-G |
| O-G | Numeric values of every `NOT_CONFIGURED` key (O-04, T-06) | yes, after Demo evidence | LIVE |
| O-H | Exception allowing a return from CLOSE_REQUIRED to protected exposure | only if wanted; default is NO | T-A |
| O-I | D055 closure and the unwritten DECISIONS rows (D079, D080, the Q3/Q4 row) | yes | docs only |

## Plan timing

The Phase 20 plan can be drafted now. An open owner question does not block plan creation; it
blocks only the implementation or acceptance criterion that depends on it. Numeric limits stay
`NOT_CONFIGURED`; rehearsal and LIVE-readiness criteria that depend on them stay blocked until the
values, tests and Demo evidence exist.

## Dependency graph (inside the phase)

```
T-A transition guard ----------+--> T-C UNKNOWN recovery (needs guard for replay/evidence)
                               +--> T-E SAFE_MODE exit (needs guard states to test condition 5)
                               +--> T-F symbol guard (D077 rules apply when protection unverified)
T-B result API ---------------------> T-C UNKNOWN recovery
T-D gate persistence/barrier -------> T-E condition 6, REST action queue (D-20)
T-H config keys --------------------> T-C (probe count/interval), T-D (cooldown, if chosen),
                                      T-E, T-G (dedupe window), stale-feed work
T-I local spill + restart ----------> T-A replay, T-C, T-E
T-G alerts -------------------------> consumes events from T-A, T-C, T-E, T-F
T-J tests and drills ---------------> last; rewrites F-604 tests, adds drills
```

Gated by an owner decision (implementation only): T-D by O-C, T-E conditions 6 and 7 by O-B, T-F by
O-D, the queue by O-E (D-20). Gated for acceptance only: criterion 2 wording by O-A.

## Dependencies outside this phase

- Phase 21: real DAILY_STOP and daily-loss producers.
- Phase 23/24: operator authentication or allow-list; Telegram UX.
- Phase 24: `positions` and `fills` ledger with `Order` rows, `update_position_snapshot` (G4-043),
  event-time ordering (D-29), exact signed-quantity comparison, intent-recovery caller wiring (G4-029).
- Phase 25 and the owner: Demo proof of manual-close behavior (G4-035, A1), the 11 Demo probes, and
  A2 (GTD expiry reaches a terminal state).

## Reporting rules for the plan and its summaries

- Keep `[DOC]` inspection apart from executed tests, Demo observations and implemented behavior.
- Do not claim execution safety, a completed probe or LIVE readiness from code inspection.
- Do not write a decision as adopted until the owner confirms it.
- LIVE stays blocked while owner decisions, configuration and Demo validation are incomplete.
