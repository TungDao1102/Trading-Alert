# Phase 20 proposed wording for the owner (plan 20-26, checkpoint O-A)

Written 2026-10-22 by plan 20-26 Task 1. Base: develop `85ecaa33` (plans 20-01 to 20-25 are in the tree).

## Status of this document

This is a documentation alignment with D077 (accepted 2026-10-20) and with the fill-driven model of Phase 19 (D-10). It is NOT a new policy decision, not D055 closure (D055 stays Accepted for the invariant and the probe plan, with the execution model OPEN until Probe 1), NOT Demo validation and NOT LIVE approval. Live placement stays disabled.

Everything below is PROPOSED text. Nothing outside this file has been edited for this purpose: ROADMAP.md, REQUIREMENTS.md, the canonical docs and `tests/test_phase19_gate.py` are untouched, no checkbox is changed, `docs/DECISIONS.md` is never edited by this plan, and no requirement changes status. The proposal is applied only after the owner's recorded answer at O-A (Task 2), with the accepted text.

The owner is asked for two separate answers: (a) the wording of the six places and the other generic claims, and (b) the separate owner item on the never-confirmed same-id re-place (B2/B3), which is implemented behavior and is NOT a past owner approval.

Evidence labels used here: `[DOC]` read from repository documents or the code at the base commit; `[DESIGN]` built and tested with fakes only; `[NOT_TESTED]` no test or probe exists; no `[DEMO]` claim is made anywhere.

## What the code does (facts the wording rests on)

Read from `src/execution/protection.py` at the base commit `[DOC]`. The wording below must say no more and no less.

1. The first placement. On the first positive fill, `_on_first_fill` calls `_place_stop(tracked)` with a query-first probe by the deterministic STOP_LOSS client id (line 1344). If the probe finds the stop it is adopted (`EXISTS`), nothing is placed. If the probe raises, the stop is placed anyway (the exchange refuses a second open algo order with the same client id). This is the first placement, not a re-placement.
2. The re-placement. `_place_stop` has exactly two call sites: the first fill (line 1344) and `_confirm` (line 1844, `probe_first=False`). The `_confirm` call runs only in the branch `elif reading is _StopReading.ABSENT` (line 1841), which is reached only when all of these hold in the same step:
   - the plan is UNPROTECTED or PROTECTED_ENTRY_OPEN and the stop was never confirmed ACTIVE (`stop_confirmed_at is None`; a once-confirmed stop is `was_confirmed` and goes to the `stop_lost` branch or to B1, never here);
   - the stop was not seen lost earlier (`stop_lost_at is None`);
   - this step's own REST query of the stop by its deterministic id answered `found=False` (`_StopReading.ABSENT`). An exception, an answer that is neither `found=True` nor `found=False` (UNREADABLE) and a found stop whose status is not ACTIVE (NOT_ACTIVE) are never re-placed.
3. Bounds of the re-placement. At most one `place_algo_protective` call per coordinator step per plan, under the same client id, with `trigger_price=entry.sl_trigger_price` (the plan stop; no wider value exists in the code path). There is no attempt counter and no cap on the number of attempts: the only bound is the `max_unprotected_ms` deadline measured from the first fill, and the number of steps before it depends on the step cadence, which is a Phase 24 number and is not decided. A cap by count would be a code change and needs its own plan.
4. The deadline step (the finding of 20-17 Deviation 4, verified `[DOC]`). In `_confirm` the order is: read the stop and the entry, cancel the entry remainder, then the `stop_lost` / `was_confirmed` / ABSENT branches (lines 1837 to 1848), and only after them the deadline check (`_unprotected_deadline_reached`, line 1851). So on the step at which `elapsed >= max_unprotected_ms` is first true, a never-confirmed stop that this step read ABSENT is placed once more under the same id, and only then does the same step enter CLOSE_REQUIRED (B2 when the entry is terminal, B3 when it is not). The stop placed on that step is not read again before the escalation. The step does not place when the reading is NOT_ACTIVE or UNREADABLE (the B2 test scenario).
5. What the outcome of that placement changes (`_on_place_outcome`, line 1355): a definitive rejection (REJECTED_DEFINITIVE, for example -2021) is never resent and enters CLOSE_REQUIRED with branch B5, with its own critical alert `PROTECTIVE_REJECTED`; `PRECONDITION_NO_POSITION` (-4509) reads the position (exposure goes CLOSE_REQUIRED, two zero reads with a terminal entry ends FLAT, otherwise the plan stays UNPROTECTED); an ambiguous result or a pre-send refusal leaves the plan UNPROTECTED and the next step reads the stop by id again. A placed stop counts as protection only after a REST read of ACTIVE.
6. Entering CLOSE_REQUIRED. `_enter_close_required` runs once per plan: the transition, SAFE_MODE `CLOSE_REQUIRED`, a critical alert `CLOSE_REQUIRED`, then the emergency closer. It does NOT read the position before it enters the state. So at the deadline the plan enters CLOSE_REQUIRED (with SAFE_MODE and the alert) whenever the stop is unconfirmed, whether or not exposure exists. Then `MarketEmergencyCloser.close_position` reads the position itself; a zero read is confirmed by a second fresh read, and with two zero reads it sends no order and answers flat (`src/execution/emergency_close.py`, `close_position` and `_refuse_unconfirmed_flat`); a non-zero read sends a reduce-only MARKET close. `_close_flow` then marks the plan FLAT only when the entry was read terminal before the close; with the entry still open and the position flat it goes back to CLOSE_REQUIRED and keeps watching (reason `CLOSED_ENTRY_OPEN`). So the narrowed phrase of the plan, "CLOSE_REQUIRED only for exposure not proven flat", is not what the code does: the state is entered first, the position is read inside it. The proposed text follows the code and is worded accordingly (finding F-1 below).
7. The confirmed-then-lost branch (D077). A stop confirmed ACTIVE and later read ABSENT or NOT_ACTIVE goes to `_on_stop_lost`; it is never re-placed, never read again, `stop_lost_at` is set once, exposure is CLOSE_REQUIRED (B4) and a reduce-only MARKET close, an unreadable position or a flat position with the entry open is UNPROTECTED and escalates to CLOSE_REQUIRED (`B4_STOP_LOST_UNRESOLVED`) at `max_unprotected_ms` from `stop_lost_at`, two zero reads with the entry terminal end FLAT.
8. The operator control `operator_protect_position` (plan 20-17) has no placement of its own. In the never-confirmed branch it runs the coordinator's own step once (the same rule as 2 to 4, it cannot extend `max_unprotected_ms`); it refuses the confirmed-then-lost branch, CLOSE_REQUIRED / CLOSE_FAILED and an unknown stop history with nothing sent. The human action for a confirmed-then-lost stop is `operator_close_position`.

Findings for the owner and for the executor of Task 3:

- F-1 (wording vs code): the plan's must_have says a stop unconfirmed at the deadline "means CLOSE_REQUIRED and a reduce-only close ... exposure unresolved or unprotected (not proven flat)". The code enters CLOSE_REQUIRED, SAFE_MODE and the critical alert at the deadline before any position read; "not proven flat" is decided afterwards by the closer. The proposed text states the sequence as the code has it. If the owner wants the position read BEFORE the escalation, that is a code change and not a wording change.
- F-2 (20-17 Deviation 4): the deadline-step placement of fact 4 is existing behavior, untested by the 19-14 suite (`[DESIGN]`, code reading only); the proposed text states it exactly. It is also listed in `20-DEFERRED.md`.
- F-3 (EXECUTION_SPEC section 10.1, written by plan 20-24): "the coordinator rebuild places it once under the deterministic id" is the same never-confirmed rule applied after a restart (restored UNPROTECTED plan, `first_fill_at` from the journal). "Once" holds for the crash-after-intent test (`test_crash_after_stop_intent_sent_restart_places_stop_once`); the rule is "at most one attempt per step". See the section on the other generic claims below.

## Place 1: ROADMAP Phase 20 criterion 2

Source: D077 item (4); D034 clauses (1) and (2); T-A table of `20-REVIEW-RESOLUTIONS.md`; Phase 20 D-05 (F-401 reworded to the fill-driven model); Phase 19 D-10; Phase 20 D-09 for the WR-07 ordering rules.

Current text (`.planning/ROADMAP.md`, Phase 20 section, criterion 2; identical at commit fffdb6e):

> 2. The entry-time SL of a resting entry is never classified as an orphan (F-401). When an SL is missing, the system re-places it automatically, or closes the position if re-placement fails (D034, F-952). Expiry and emergency-close follow the WR-07 ordering rules.

Proposed text (the full block that would replace it, with criteria 1, 3, 4 and 5 unchanged, is under "ACCEPTED-CRITERIA" at the end of this file):

> 2. A protective of a plan whose entry is still resting or partially filled is never classified as an orphan (F-401). Every positive fill leads to the protection flow within `protection.max_unprotected_ms`, and no new entry opens while any unprotected exposure exists. Missing protection is handled in four separate cases, each with its own basis (D034, D077, F-952). (1) A stop never confirmed ACTIVE that this step's own REST query by its deterministic id proved absent is placed again under the same client id from the plan stop-loss, never a wider one: at most one attempt per coordinator step, bounded by the `max_unprotected_ms` deadline and not by a count, and the step that reaches the deadline still makes its attempt before it escalates (D034 clause (1)). (2) A stop that is rejected definitively (for example -2021) or not acknowledged is never resent: CLOSE_REQUIRED, a reduce-only close, then an alert (D034 clause (2)). (3) A stop that was confirmed ACTIVE and is later lost is never re-placed, neither automatically nor by an operator action: exposure means CLOSE_REQUIRED and a reduce-only MARKET close, an unreadable position or a flat position with the entry still open means UNPROTECTED, escalating to CLOSE_REQUIRED at `max_unprotected_ms` from the first detection of the loss (D077). (4) A stop still unconfirmed at `max_unprotected_ms` after a positive fill enters CLOSE_REQUIRED (SAFE_MODE and a critical alert) and the emergency closer reads the position itself: exposure is closed by a reduce-only MARKET order; when two consecutive fresh position reads are zero it sends no order for a position that does not exist, and the plan ends FLAT only with the entry terminal as well. Expiry and emergency close follow the WR-07 ordering rules defined in Phase 20 D-09: a plan's protective legs are cancelled only with zero fills or after the position is confirmed flat by two consecutive fresh reads with the entry terminal.

Evidence: case (1) `[DESIGN]` implemented behavior, see "Owner item" below; case (2) `[DOC]` D034 and `protection.py` B5; case (3) `[DOC]` D077, `[NOT_TESTED]` on Demo (assumption A3, probe P6); case (4) `[DOC]` `_enter_close_required`, `_close_flow`, `MarketEmergencyCloser.close_position`, fakes only.

## Place 2: ROADMAP Phase 20 checklist summary line

Source: the same cases as Place 1; the checkbox is GSD bookkeeping and stays as it is (only the text after " - " is proposed).

Current text (`.planning/ROADMAP.md` line 57):

> - [ ] **Phase 20: Reconcile + SAFE_MODE Hardening + Alerts** - No blind spots, pending-entry SL kept, auto SL re-place (D034), durable SAFE_MODE, operational alerts

Proposed text after " - ":

> No blind spots, the protective of a resting entry is never an orphan, a never-confirmed stop is re-placed or the exposure closed, a confirmed-then-lost stop is closed (D034, D077), durable SAFE_MODE, operational alerts

## Place 3: REQUIREMENTS RISK-03

Source: D077 items (1) and (4); D034 clause (1) for the never-confirmed case only; owner direction 1 for D-26 (plan 20-17).

Current text (`.planning/REQUIREMENTS.md` line 40, after the checkbox and the id):

> A live protective stop is never loosened or removed while its position is open; any stop change is explicit, logged and permitted by the strategy and execution contract; automatic re-placement restores the original plan stop-loss, never a wider one

Proposed text:

> A live protective stop is never loosened or removed while its position is open; any stop change is explicit, logged and permitted by the strategy and execution contract; the only re-placement is of a stop that was never confirmed ACTIVE and that REST proved absent, under the same client id from the original plan stop-loss, never a wider one; a stop that was confirmed and later lost is never re-placed, neither automatically nor by an operator action (D077), and its exposure is closed by a reduce-only order

The checkbox and the traceability status (`| RISK-03 | Phase 20 | Pending |`) are not touched.

## Place 4: EXECUTION_SPEC section 9 (the F-401 paragraph and the re-placement paragraph)

Source: D077; D034; Phase 19 D-10; `src/reconcile/compare.py` (`_RESTING_ENTRY_STATUSES`: NEW and PARTIALLY_FILLED exempt a plan's protective from the orphan class).

Current text (`docs/trading/EXECUTION_SPEC.md` line 211):

> A protective stop paired with a still-working ENTRY order is not an orphan: the position is zero only because the entry has not filled yet, so the sweeper leaves that stop in place (F-401).

Proposed text:

> A protective of a plan whose entry is still resting or partially filled is not an orphan, even when the position reads zero at that moment: the entry can still fill, so the sweeper leaves that protective in place (F-401). Since Phase 19 (D-10) no stop is placed before the first fill; the entry rests without one and the stop is placed after the fill is seen.

Current text (`docs/trading/EXECUTION_SPEC.md` line 213):

> When a protective stop is missing (canceled, expired, or never acknowledged) while the position is open, the reconciler re-places it at the original plan stop-loss, never wider. This supersedes the earlier cancel-only reconciler decision (Phase 08 D-03 / Phase 09 D-02), per D034; if the re-placed stop is rejected or unacknowledged, the ladder continues with a reduce-only close and a HIGH-priority alert (see `SECURITY_AND_OPERATIONS.md` section 7).

Proposed text:

> The reconciler never places an order. Protection after a fill is the coordinator's (`src/execution/protection.py`), and a missing protective stop is handled in four separate cases. (1) A stop never confirmed ACTIVE that the coordinator's own REST query by the deterministic client id proved absent (`found=False`) is placed again under the same client id at the plan stop-loss, never wider: at most one attempt per coordinator step, bounded by `protection.max_unprotected_ms` and not by a count; the step that reaches the deadline still makes its attempt, then escalates. An exception, an unknown answer or a stop found but not ACTIVE is never re-placed. This is the D034 clause (1) rule and is implemented behavior `[DESIGN]`. (2) A stop rejected definitively (for example -2021) or not acknowledged is never resent: CLOSE_REQUIRED, a reduce-only close, then a HIGH-priority alert (D034 clause (2), `SECURITY_AND_OPERATIONS.md` section 7). (3) A stop that was confirmed ACTIVE and is later lost is never re-placed, neither automatically nor by an operator action (D077 item (4) supersedes D034 clause (1) for this branch only): exposure means CLOSE_REQUIRED and a reduce-only MARKET close; an unreadable position, or a flat position while the entry can still fill, means UNPROTECTED and escalates to CLOSE_REQUIRED at `max_unprotected_ms` from the first detection of the loss. (4) A stop still unconfirmed at `max_unprotected_ms` after a positive fill enters CLOSE_REQUIRED (SAFE_MODE, critical alert) and the emergency closer reads the position itself: exposure is closed by a reduce-only MARKET order; two consecutive fresh zero reads send no order, and the plan ends FLAT only with the entry terminal. This supersedes the earlier cancel-only reconciler decision (Phase 08 D-03 / Phase 09 D-02) for these cases, per D034 and D077.

## Place 5: SECURITY_AND_OPERATIONS section 7 (the re-placement bullet and the implementation-status paragraph)

Source: the same four cases; plan 20-17 (EXEC-06 controls); plan 20-24 (what Phase 20 built).

Current text (`docs/operations/SECURITY_AND_OPERATIONS.md` line 113):

> - a missing or canceled stop-loss is automatically re-placed at the original plan stop-loss, never wider (D034);

Proposed text:

> - a stop-loss that was never confirmed ACTIVE and that REST proved absent is placed again under the same client id at the plan stop-loss, never wider, at most once per coordinator step and only until `max_unprotected_ms` (D034 clause (1)); a stop that was confirmed ACTIVE and is later lost is never re-placed, neither automatically nor by an operator action: the exposure is closed by a reduce-only order (D077);

The next bullet (line 114, "a stop-loss that is rejected or not acknowledged leads to a reduce-only market close, then a HIGH-priority alert (D034);") is unchanged: it is case (2).

Current text (`docs/operations/SECURITY_AND_OPERATIONS.md` line 118):

> Implementation status: the automatic stop re-placement, the reduce-only close and the DB-outage guarantee above are the target behaviour (D034), built in Phase 20 (EXEC-06, OPS-05). Until then the system enters SAFE_MODE and alerts on an unprotected position but does not re-place the stop-loss or close the position itself, so the operator must place the stop-loss or close the position manually.

Proposed text:

> Implementation status (Phase 20): the never-confirmed stop rule, the reduce-only close and the D077 handling of a lost stop, the act-first risk-reducing controls with the local spill (a risk-reducing action does not wait for the journal) and the five EXEC-06 controls are built and tested with fakes and a local PostgreSQL `[DESIGN]`. They are not run by any deployed process yet: the composition is Phase 24, the controls have no command surface and no authentication (the operator id is audit metadata), and no behavior is observed on Binance `[NOT_TESTED]`: assumption A3 (does a closePosition stop leave with its position), probe P6 and the same-id placement of case (1) against the exchange are open. Until the composition exists the operator uses `RUNBOOK.md` section 3: place the stop-loss or close the position manually on the exchange.

## Place 6: OPS-05 traceability note (REQUIREMENTS)

Source: Phase 20 D-23; `OPS05_MATRIX` in `src/ops/alerts.py`; `SECURITY_AND_OPERATIONS.md` section 5.1; `20-DEFERRED.md` "Requirement status after Phase 20".

Current text: the requirement line 78 (`- [ ] **OPS-05**: Operational alerts fire for an unprotected position, local versus exchange divergence, an unknown or foreign order, a duplicate execution attempt, stale data, a rejected protective action, an authentication failure, and daily-loss WARNING and DAILY_STOP`) has no note; the traceability row is `| OPS-05 | Phase 20 | Pending |`.

Proposed text, appended to the requirement line in the style of the EXEC-07 line (italic parenthesis):

> *(Phase 20, 2026-10-21 D-23: the alert contract, the journal-first sender, the dedupe and the bounded retry of the message (never of an order) exist, and the producers listed in `OPS05_MATRIX` (`src/ops/alerts.py`) are built and tested with fakes `[DESIGN]`. DAILY_STOP and the daily-loss WARNING have a contract and a test trigger only (`emit_daily_state_alert`) and are completed by Phase 21, which provides the production source; no producer is wired in a running process until Phase 24. A test trigger is not evidence that the production path works. Stays Pending.)*

The status cell is not changed.

## Owner item: never-confirmed same-id re-place (B2/B3)

This is a separate question. The owner confirms or rejects it on its own line at Task 2.

What it is `[DOC]`: implemented behavior of `src/execution/protection.py` (module docstring B2/B3: "a stop REST proved absent is re-placed under the same id (never blindly)"; code `_confirm` line 1841 to 1848). It was a judgement call of plan 19-14 (`19-14-SUMMARY.md` key decision "A stop REST proved absent (query found=False) is re-placed under the same deterministic id", test-table row "Replace only after absence"). It is tested by `tests/test_protection_branches.py::test_branch_ambiguous_stop_is_replaced_only_after_a_definitive_absence_probe` (fakes, `[DESIGN]`). `19-NOTES.md` ("Fill, stop and entry remainder") says only "Entry terminal first, stop not confirmed: keep querying the stop"; it does not say the stop is placed again.

Policy basis: D034 clause (1), "On a missing or canceled SL, the system automatically re-places the SL". It is NOT an owner approval of this retry. Nothing in this document, in the code or in a SUMMARY states that the owner approved it.

What is separate from it: D034 clause (2) (a rejected or unacknowledged SL leads to a reduce-only close, then an alert) and branch B5 (a definitive rejection such as -2021 is never resent and goes to CLOSE_REQUIRED) are different cases. D077 item (4) overrides clause (1) only for the confirmed-then-lost branch.

The bounds, exactly as the code has them `[DOC]`:

1. Only when this step's own REST query by the deterministic id answered `found=False`. An exception, an unknown answer or a found-but-not-ACTIVE stop is never re-placed.
2. Never when the stop was once confirmed ACTIVE.
3. Same client id, `trigger_price` from the plan (`entry.sl_trigger_price`), `closePosition=true`; the stop is never wider than the plan.
4. At most one attempt per coordinator step per plan. There is no attempt-count cap; a count cap would be a code change and needs its own plan. The bound is the `max_unprotected_ms` deadline from the first fill, and the cadence of the steps (Phase 24) decides how many attempts fit before it.
5. The step that reaches the deadline still makes its one attempt when the stop reads ABSENT, then escalates in the same step (20-17 Deviation 4, fact 4 above). The stop it places is not read again before the escalation.
6. A definitive rejection (B5) is never resent and goes to CLOSE_REQUIRED; an unresolved stop at the deadline goes to CLOSE_REQUIRED.
7. The exchange refuses a second open algo order with the same client id (comment in `_place_stop`), so a repeat cannot create a duplicate open stop; this is a code comment and a fake-exchange behavior, not observed on Binance (`[NOT_TESTED]`).

The operator control (`operator_protect_position`) delegates to the same rule and has no placement of its own, so the automatic path and the control are one path.

If the owner confirms: the accepted text of Places 1 to 5 and the other claims is applied as proposed. If the owner rejects: none of the text that presents the same-id re-place as current policy is applied (the case (1) sentences of Places 1, 3, 4 and 5 are left out), `20-DEFERRED.md` gets the row of the resume signal, and the automatic path and the operator control change together in one gap plan or a DECISIONS row. Criterion 2 does not count as done on a rejection.

## Other generic re-placement claims

Search re-run on the base commit: `git grep -n -i -E "re-?plac(e|es|ed|ement|ing)" -- docs AGENTS.md` (44 hits outside `docs/DECISIONS.md`, read one by one; most are unrelated: "replaced by D064", "tmp + replace", `CANCEL_REPLACE`, "replace the union"), `git grep -n -i "restores the original" -- docs` (1 hit), and a third search for wording that avoids the verb (`again`, `re-protect`, `automatically ... stop`, `ladder`). Also searched: `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, `.planning/PROJECT.md`. `docs/GLOSSARY.md` has no hit. `AGENTS.md` has no hit. No hit is new since the planning-time list (the line numbers of the RUNBOOK moved by two lines after plan 20-24 added text above them).

Hits that claim or imply automatic re-placement and that this proposal edits:

### RISK_MANAGEMENT.md line 88

Current text:

> Automatic re-placement of a missing or canceled stop-loss restores the original plan SL, never a wider one (D034).

Proposed edit:

> Re-placement of a stop is limited to a stop that was never confirmed ACTIVE and that REST proved absent: it is placed again under the same client id at the original plan SL, never a wider one (D034 clause (1)). A stop that was confirmed and later lost is never re-placed, neither automatically nor by an operator action (D077); its exposure is closed by a reduce-only order.

### RUNBOOK.md line 42 (section 3, the ladder)

Current text:

> → if stop is absent or canceled, automatically re-place it at the original plan SL after risk validation (never wider)

Proposed edit (the line after it, "→ if the SL is rejected or not acknowledged, close the position with a reduce-only order, then send a HIGH alert", is case (2) and stays):

> → if the stop was never confirmed ACTIVE and REST proves it absent, the system places it again under the same client id at the original plan SL (never wider), at most once per coordinator step and only until `max_unprotected_ms`; if the stop was confirmed ACTIVE and is later lost, it is never re-placed: the position is closed with a reduce-only order (D077)

### RUNBOOK.md line 47 (the sentence after the ladder)

Current text:

> The automatic ladder is per D034: the operator works full-time and cannot be assumed to react within minutes.

Proposed edit: unchanged except that "D034" becomes "D034 and D077" (D077 narrows the ladder for a lost stop): "The automatic ladder is per D034 and D077: the operator works full-time and cannot be assumed to react within minutes. The operator's control for a confirmed-then-lost stop is the close (`operator_close_position`, `EXECUTION_SPEC.md` section 11); there is no operator re-placement of that stop."

### RUNBOOK.md line 49 (Implementation status)

Current text:

> **Implementation status:** the ladder above is the target behaviour (D034) and is built in Phase 20 (EXEC-06, OPS-05). Until then the system does not re-place a stop-loss or close the position by itself: on an entry without a protective stop it enters SAFE_MODE and alerts, and the operator must place the stop-loss or close the position manually on the exchange. Do not wait for an automatic action.

Proposed edit:

> **Implementation status:** the ladder above (D034, narrowed by D077) is built in Phase 20 and tested with fakes `[DESIGN]`; no deployed process runs it yet (the composition is Phase 24), the controls have no command surface and nothing is observed on Binance `[NOT_TESTED]`. Until the composition exists the system does not place or close anything by itself on the host: on an entry without a protective stop the operator places the stop-loss or closes the position manually on the exchange. Do not wait for an automatic action.

### SECURITY_AND_OPERATIONS.md lines 113 and 118

Proposed in Place 5.

### EXECUTION_SPEC.md line 213

Proposed in Place 4 (section 9 is one of the six places).

### EXECUTION_SPEC.md line 279 (section 11, the protect control paragraph)

Already re-described by plan 20-24 from the 20-17 SUMMARY: "no placement of its own ... In the never-confirmed branch it triggers the coordinator's own same-id rule ... refuses the confirmed-then-lost branch ... The human action for a confirmed-then-lost stop is the close control." It matches cases (1) and (3); no edit proposed. The table row "replace protection | `operator_protect_position` | See the paragraph below" (line 274) and the list item "an explicit protect action (adopt or trigger protection; it has no placement of its own, see below)" (line 262) also match.

### EXECUTION_SPEC.md line 255 (section 10.1, Implementation status (Phase 20))

Current text (the relevant sentence): "A crash after the STOP_LOSS intent was written leaves an acknowledged entry without a stop; since Phase 20 the coordinator rebuild places it once under the deterministic id at the plan stop-loss (never on a guessed history, see D077), but only in a process that runs the restore; until Phase 24 wires it the operator uses `RUNBOOK.md` section 3."

It is the never-confirmed rule after a restart (finding F-3). It depends on the owner's answer on B2/B3. Proposed edit if the owner confirms: replace "places it once under the deterministic id at the plan stop-loss" with "applies the never-confirmed rule of section 9 to it: a REST-proved absence is answered by a placement under the deterministic id at the plan stop-loss, at most once per coordinator step". If the owner rejects B2/B3 the sentence is rewritten to say the rebuilt plan is UNPROTECTED and escalates at the deadline.

### EXECUTION_SPEC.md line 119 (section 6.1)

Current text: "... reconciliation and the D034 ladder in section 9 must cover a stop that fails at trigger." It points at section 9 and is not itself a re-placement claim. No edit; it follows whatever section 9 says after acceptance.

### docs/DECISIONS.md D034 (line 38) and D077 (line 81)

Not edited: the owner's decision record. D034 clause (1) still reads "On a missing or canceled SL, the system automatically re-places the SL"; D077 item (4) is what narrows it for the confirmed-then-lost branch, and says the D034 row text is not edited.

### Found, listed, not edited by this plan

- `.planning/ROADMAP.md` line 397 (Phase 11 criterion 2): "The SAFE_MODE wording in SECURITY_AND_OPERATIONS / RUNBOOK / EXECUTION_SPEC is entries-only, with protective re-placement and a close fallback (D034; F-009, F-952)." This is the success criterion of an earlier phase, dated by D034 of 2026-09-30. Task 3 limits the ROADMAP hunks to the Phase 20 criteria block and the Phase 20 checklist line, so it is left as it is; the owner may decide whether to touch it.
- `.planning/REQUIREMENTS.md` line 68 (EXEC-06): "... close strategy positions on explicit action, re-place protection, and enter SAFE_MODE". It names the control. The behavior of the control is stated in `EXECUTION_SPEC.md` section 11 (no placement of its own, refuses the confirmed-then-lost branch). No edit proposed; the owner may want "re-place protection" to read "adopt or trigger protection".

## ACCEPTED-CRITERIA

The block that would stand in the Phase 20 section of `.planning/ROADMAP.md`, from `**Success Criteria**` to just before `**Audit refs**`, if the owner accepts Place 1 as proposed. Criteria 1, 3, 4 and 5 are the current text, byte for byte. Task 3 would make `tests/test_phase19_gate.py::test_phase20_criteria_match_the_owner_accepted_wording` compare the ROADMAP block with this fenced block (CRLF-normalized, trailing whitespace stripped); if the owner accepts with changes, this block is edited to the accepted text first.

```text ACCEPTED-CRITERIA
**Success Criteria**:
1. The compare runs a reverse pass over exchange orders, compares signed amounts per position, and requires a STOP on the exchange for every open position. A doubled position, a sign-flipped position, a foreign order or a TP-only position is a divergence (F-701).
2. A protective of a plan whose entry is still resting or partially filled is never classified as an orphan (F-401). Every positive fill leads to the protection flow within `protection.max_unprotected_ms`, and no new entry opens while any unprotected exposure exists. Missing protection is handled in four separate cases, each with its own basis (D034, D077, F-952). (1) A stop never confirmed ACTIVE that this step's own REST query by its deterministic id proved absent is placed again under the same client id from the plan stop-loss, never a wider one: at most one attempt per coordinator step, bounded by the `max_unprotected_ms` deadline and not by a count, and the step that reaches the deadline still makes its attempt before it escalates (D034 clause (1)). (2) A stop that is rejected definitively (for example -2021) or not acknowledged is never resent: CLOSE_REQUIRED, a reduce-only close, then an alert (D034 clause (2)). (3) A stop that was confirmed ACTIVE and is later lost is never re-placed, neither automatically nor by an operator action: exposure means CLOSE_REQUIRED and a reduce-only MARKET close, an unreadable position or a flat position with the entry still open means UNPROTECTED, escalating to CLOSE_REQUIRED at `max_unprotected_ms` from the first detection of the loss (D077). (4) A stop still unconfirmed at `max_unprotected_ms` after a positive fill enters CLOSE_REQUIRED (SAFE_MODE and a critical alert) and the emergency closer reads the position itself: exposure is closed by a reduce-only MARKET order; when two consecutive fresh position reads are zero it sends no order for a position that does not exist, and the plan ends FLAT only with the entry terminal as well. Expiry and emergency close follow the WR-07 ordering rules defined in Phase 20 D-09: a plan's protective legs are cancelled only with zero fills or after the position is confirmed flat by two consecutive fresh reads with the entry terminal.
3. SAFE_MODE is persisted and needs an operator id to exit (F-711, F-127). Risk-reducing actions execute first and are journaled afterwards, with a fallback (F-702). The -2011 cancel result is verified by a post-cancel query (F-502).
4. Alerts go out for:
   - an unprotected position;
   - a local-vs-exchange divergence;
   - a foreign order;
   - DAILY_STOP;
   - stale data;
   - an auth failure.
   (F-106)
5. The tests that asserted the old rules ("reconciler never places") are rewritten (F-604).
```

## What is asked of the owner at O-A

1. "approved", "approved with changes: ..." (give the exact text) or "rejected" for the wording of Places 1 to 6 and the other generic claims. Check that no text allows an operator re-placement in the confirmed-then-lost branch, that case (4) is worded as the code has it (finding F-1), and that the header says documentation alignment, that D055 is not closed and that nothing here is Demo validation or LIVE approval.
2. On its own line, "B2/B3: confirm" or "B2/B3: reject" for the never-confirmed same-id re-place (bounds 1 to 7 above, including the one more same-id attempt on the deadline step).
