# Phase 19: Execution Plan Binding + Pre-Placement Checks - Context

**Gathered:** 2026-10-19
**Status:** Ready for planning (gathered with `--auto`; items marked OWNER-OPEN must not be implemented until the owner decides)

<domain>
## Phase Boundary

What the human approved is exactly what is placed: same symbol, same side, a quantity no larger than planned, and a price that is still valid. A rejected or unconfirmed stop after a fill never leaves a naked position. This also absorbs the former Phase 15 live-price check.

Requirements: APRV-01, APRV-02, EXEC-01, EXEC-02, RISK-04, EXEC-07 (ROADMAP.md Phase 19, four success criteria).

Out of scope (stays elsewhere): the reconciler loop and SAFE_MODE persistence (Phase 20), account equity and daily loss (21), leverage and liquidation guard (22), Telegram UX (23), the running live process (24), Demo campaign (25). The TP1 far-half-of-zone rule (Backlog 999.1) and maker or post-only entries are deferred (D059).

No Telegram, Binance or EC2 connection is needed to plan or build this phase. Tests use fakes and the local PostgreSQL 17.
</domain>

<decisions>
## Implementation Decisions

All decisions below were taken in `--auto` mode: the recommended option, or the direction the owner already adopted in `19-NOTES.md` (owner words 2026-10-18: "adopt kèm các điểm trên"). Nothing here edits `docs/DECISIONS.md`; the proposed D055 closure is a draft for the owner (`19-DEC-D055-DRAFT.md`).

### Binding the order to the hashed plan (criterion 1)
- **D-01:** `execute_approved_plan` and `attach_protectives_to_fill` derive symbol and side from the hashed `TradePlan`, never from a caller argument. A caller-supplied symbol or side that disagrees is a rejection, not an override. The plan hash is re-derived and compared, not trusted.
- **D-02:** The placement quantity is `min`-bounded: it may be at most the approved quantity; a larger value rejects the plan and is never clipped up or down silently.
- **D-03:** SL and entry geometry is asserted again after the tick snap (G4-020: the planner has no tick size, so a stop within one tick of the zone edge can be snapped by the risk layer). A failed assertion is NO_TRADE with a reason code.
- **D-04:** `workingType = MARK_PRICE` is recorded on the plan (D037, F-507) and carried to every protective payload.

### Pre-placement refusals (criterion 2)
- **D-05:** The entry is refused when mark or last price has crossed the SL or left the entry zone, when remaining validity is below the minimum, when another plan or position exists on the same symbol, or when `TradePlan.status` or the invalidation rule says the plan is invalid. GTD is set as the exchange-side expiry backstop.
- **D-06:** The live price is read through a new narrow adapter read (mark price) injected into the manager; the manager never reads the clock or the network itself (existing purity rule). A failed or stale price read is NO_TRADE (fail closed).
- **D-07:** The minimum remaining validity and the price-staleness bound are NOT chosen here. They are added to the versioned limits as `NOT_CONFIGURED`; the live path refuses while they are unset (same pattern the repo already tests for ratified keys). The owner fills the numbers.
- **D-08:** `INVALIDATED` keeps two meanings today (planner D-07 reject versus approval and binding invalidation, G4-017). Introduce a distinct reason code for the pre-placement invalidation when criterion 2 is built, without renaming the existing one.
- **D-09:** An executed plan stays `APPROVED`; `expiry_utc` governs only an unfilled entry and nothing moves an executed plan to `EXPIRED` (G4-036, D051 item i). The plan-status check must not contradict this.

### Protection model after the fill (criterion 3, D055 direction)
- **D-10:** One model only: STOP_MARKET `closePosition=true` placed after the first fill with positive quantity (stream or REST; PARTIALLY_FILLED counts). No `quantity`, no `reduceOnly` on that leg. The current placement of the stop right after the entry (gate 6, near `manager.py:613` and the SL intent near `:818`) is replaced by fill-driven placement. — **Reversibility:** costly — changes the order of every entry flow and the intent state machine; undoing it needs a new migration of intent states and re-proving on Demo.
- **D-11:** A position is not protected until Binance confirms the stop by REST query; `NEW`, HTTP success or `ALGO_UPDATE FINISHED` alone is not evidence. No new entry while any position is unprotected.
- **D-12:** On the first fill, stop placement and the cancel of the entry remainder start together, neither waits for the other; both are reconciled until the stop is confirmed and the entry is terminal. The failure branches (stop confirmed but entry not terminal; entry terminal but stop unconfirmed; both ambiguous; a new fill after the stop triggered; `-2021` after a fill) follow `19-NOTES.md` section "Fill, stop and entry remainder" verbatim.
- **D-13:** Two deadlines, kept separate: `max_unprotected_ms` and `entry_terminal_timeout`. Both are `NOT_CONFIGURED` limits keys; the live path refuses while they are unset; no placeholder number is a decision. The owner sets them after the probes.
- **D-14:** Hedge Mode is not supported in V1: if position mode detection returns hedge, the live path refuses (fail closed). Hedge payload differences are tested offline only.

### Emergency close (criterion 3, D034)
- **D-15:** `ExecutionAdapter` gains a MARKET reduce-only close method (One-way: `reduceOnly=true`, closing side) with a deterministic client order id per attempt; an ambiguous result is queried by that id before anything is resent; never a duplicate close. A failed emergency close never declares the position safe.
- **D-16:** Above the symbol's MARKET_LOT_SIZE max, close in valid parts, re-check the position after each part, every part within live exchangeInfo filters. If no valid part can be built or a part fails or is ambiguous: SAFE_MODE, critical alert, keep reconciling, manual intervention. Splitting is proven offline with fake filters.
- **D-17:** `attach_protectives_to_fill`'s statement "no rescue placement is ever issued (D-02)" is corrected: D034 supersedes D-02. `emergency_manual_close` keeps its operator role; the automatic close is a separate path.

### TP legs (criterion 4)
- **D-18:** No continuous TP1 resizing for late fills (settles G2-032 for the normal flow). TP1 and TP2 are placed only after the entry is terminal and the final quantity equals the reconciled real position. TP1 quantity comes from real exposure, floored to stepSize, never above the closable position; TP2 is `closePosition=true` without quantity or reduceOnly. One-way and Hedge payloads are tested separately.
- **D-19:** TP legs are quantized to LOT_SIZE (MARKET_LOT_SIZE for a triggered market exit, filters read from exchangeInfo at runtime). The system does not rely on a MIN_NOTIONAL exemption for reduce-only legs and treats their rejection as a possible failure.
- **D-20:** TP intent rows are written ahead with `record_protective_intent`, and `snapshot_is_valid_for_live` is checked before placement; a stale snapshot is re-sized or refused (G4-038).

### Taxonomy and persistence
- **D-21:** The manager reads the Phase 18 exchange-error taxonomy (`classify`, `retry_eligible`, `safe_mode_eligible`). A refusal raised before anything is sent (rate-limit gate, `EntriesBlocked`, `SignedCallPolicyMissing`) must not be treated as an ambiguous send (no spurious SAFE_MODE or UNKNOWN intent). This is src/WR-02 from the Phase 18 review.
- **D-22:** `realized_risk` is persisted with the live fill record so live R is no longer INCOMPLETE (G4-008, D052 item f). It needs an Alembic migration; follow the Phase 17 migration conventions.

### Claude's Discretion
- Module layout for the new fill-driven protection coordinator, naming of new reason codes, and how fakes model fill and cancel races.
- Test structure (one race test per branch in D-12, offline).

### OWNER-OPEN (planner records them as blockers, does not implement)
- **O-01:** D055 closure as a DECISIONS row (draft in `19-DEC-D055-DRAFT.md`). Until the owner accepts it, LIVE stays blocked and the plan must make the D-10 flow the only flow but not enable live orders.
- **O-02 (T-04, EXEC-07):** the TP1 split fraction is a code constant by D052 item (c); EXEC-07 asks for a versioned registry parameter. Auto default: change nothing, keep the constant, leave EXEC-07 Pending with a note. Reconciling needs a protocol-level decision because the backtest fraction is frozen.
- **O-03 (G4-007):** criterion 4 says fall back to a single TP when a leg is below minQty; backtest rule D-27 says an un-sizeable TP1 is NO_TRADE. The two must move together. Auto default: implement the refusal (NO_TRADE) and do not implement the single-TP fallback until the owner decides.
- **O-04:** numeric limits (D-07, D-13) and the Phase 18 skipped review items WR-08, WR-01, WR-10 and the CR-02 liveness remainder (`19-NOTES.md`, last section).
- **O-05:** the 11 Demo probes listed in `19-NOTES.md`; the user runs every `--execute`.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase inputs
- `.planning/ROADMAP.md` Phase 19 (lines 936-975) - goal, four criteria, inherited items
- `.planning/phases/19-execution-plan-binding-price-check/19-NOTES.md` - D055 direction, fill/stop/entry branches, emergency close, deadlines, probes, Phase 18 skipped review items
- `.planning/phases/19-execution-plan-binding-price-check/19-DEC-D055-DRAFT.md` - draft decision text for the owner
- `.planning/REQUIREMENTS.md` - APRV-01/02, EXEC-01/02/07, RISK-04

### Decisions
- `docs/DECISIONS.md` D034 (auto SL re-place, reduce-only close), D037 (MARK_PRICE), D051 (Phase 17 persistence, item i), D052 (item c TP1 fraction, item f realized_risk), D054, D055 (open execution model), D059, D072 (Phase 18 limits and taxonomy)
- `.planning/phases/09-live-execution-rollout/09-DEMO-REHEARSAL-FINDINGS.md` - the -4509 finding
- `.planning/phases/18-user-data-stream-error-taxonomy/decisions/18-DRAFT-D055-evidence-for-user.md` and `evidence/18-probe-check.txt` - Demo probe evidence
- `.planning/phases/18-user-data-stream-error-taxonomy/18-REVIEW.md`, `18-REVIEW-FIX.md`, `18-UAT.md` - review findings and the open liveness gap
- `.planning/phases/14-backtest-causality-rewrite/14-VERIFICATION.md` (line ~255) - TP1 and single-TP parity

### Specs
- `docs/trading/RISK_MANAGEMENT.md` section 11 (quantization), `docs/` execution and security specs (EXECUTION_SPEC section 10 no-blind-recovery)
- `config/binance/binance-limits-v1.toml` - ratified limits file; new keys are `NOT_CONFIGURED`, existing values are not edited
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/execution/manager.py`: `execute_approved_plan` (fixed gate order 0 to 7, intent consumed before `place_entry`), `_place_entry_no_blind_retry` (probe before re-send, `_ENTRY_MAX_ATTEMPTS = 2`), `attach_protectives_to_fill`, `emergency_manual_close`, `expire_pending_entry`, `safe_mode_freeze`, `cancel_untriggered_protectives`, `size_protectives_to_filled_qty`.
- `src/execution/constraint_snapshot.py` (`snapshot_is_valid_for_live`), `ExecutionIntentStore` (intent rows, `record_protective_intent`), `src/domain/exchange_errors.py` (`classify`, `ErrorFacts`, `CallKind`), `src/risk/cost_rates.py`.
- `ExecutionAdapter` Protocol: `place_entry` (LIMIT only), `place_algo_protective`, `query_order_by_client`, `query_algo_order_by_client`, `get_position_mode`, `cancel_normal_order`, `cancel_algo_order`.

### Established Patterns
- Manager is a pure function of inputs plus injected `now_utc`; no clock, no SDK import; first-failure-wins reason codes; every live-safety gate is required (no `None` skip).
- Decimal for all money; fail closed; an unknown state enters SAFE_MODE; persistence errors fail closed on both sides of placement.
- Only `scripts/demo_rehearsal.py` calls `attach_protectives_to_fill` today, so nothing in `src` drives protection from a fill; that is the main new wiring.

### Integration Points
- Phase 18 user-data stream events (ORDER_TRADE_UPDATE, ALGO_UPDATE) feed fill detection; Phase 20 reconciler consumes the same intent states, so D-10 to D-12 state names must be stable.
- `config/binance/binance-limits-v1.toml` plus its loader and the test that forbids numeric defaults for ratified keys.
- Alembic migrations for `realized_risk` (Phase 17 conventions).
</code_context>

<specifics>
## Specific Ideas

- Failure branches are the test plan: one offline race test per branch of D-12, plus the splitting test of D-16 with fake filters.
- Accepted knowingly (owner note): closing a position that has a good stop because an entry cancel was slow; mitigated by a wide measured timeout, journaled with the reason.
</specifics>

<deferred>
## Deferred Ideas

- Model (b): pre-placed explicit-quantity stop (Demo accepted it; not built).
- Hedge Mode support; TP1 far-half rule (999.1); maker or post-only entries; `binance-sdk-algo` TWAP/VP.
- Phase 18 review items WR-08, WR-01, WR-10 and the CR-02 liveness gap (owner decisions; see `19-NOTES.md`).
- G4-006: the live producer of the TP1 quantity and exit ladder uses the backtest fraction and `size_protectives_to_filled_qty`; wire it only when the producer exists.

### Reviewed Todos (not folded)
None matched.
</deferred>

---

*Phase: 19-execution-plan-binding-price-check*
*Context gathered: 2026-10-19*

## Research corrections (2026-10-19, from 19-RESEARCH.md; these override the wording above)

- D-01: `TradePlan` has no symbol or side field. Symbol and side come from `Signal` through `plan.signal_id`, cross-checked against the hash-bound plan geometry and `constraint_snapshot.symbol`; the plan hash is recomputed. Symbol and side are NOT added to the hash (D051 c).
- D-07/D-13: `binance-limits-v1.toml` is sha256-pinned by D072, so the new `NOT_CONFIGURED` keys go in a separate file and loader, with `GUARDED_NAMES` extended in `tests/test_no_unratified_defaults.py`.
- Frozen code: do not modify `size_protectives_to_filled_qty`, `quantize_protective_qty`, `build_sl_leg`, `ProtectiveTemplate`; live TP sizing is a new function, with a byte-identical regression test.
- Do not extend `OrderRole`, `RejectionReason` (pinned at 20 members) or `ExecutionIntentStatus`; use plain reason strings and document them in GLOSSARY 9.3/9.4.
- D-22 only removes `NO_RISK_VALUE`; live R stays INCOMPLETE (`UNVERIFIED_EXCHANGE_SEMANTICS`).
- New OWNER-OPEN: Q3 (exchangeInfo read fails during emergency close: stale snapshot or refuse), Q4 (rate-limit pause blocks stop/cancel/close, Phase 18 WR-12), Q5 (second `place_entry` attempt, `_ENTRY_MAX_ATTEMPTS = 2`).
- Network gaps: user-data WS event pages (ORDER_TRADE_UPDATE, ALGO_UPDATE) and the New Order MARKET reduce-only section were not retrievable; marked UNVERIFIED in the research. Owner follow-up.
