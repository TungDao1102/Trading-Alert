# 18-DEC-TAXONOMY-CODES: taxonomy decision on -1106, -4016, -4024 and -1125 (plan 18-26)

option: adopt-with-addition
decided by: user
date: 2026-10-17
source: the user's instruction in the session ("reviewer text adopted", relayed to the planner by the orchestrator). The reviewer's own message is not stored by this plan; the ellipsis in the user's words is the relay's, and the full text of the reviewer's message is not available beyond what is recorded here.
words:
> adopt ... với quyết định bổ sung là thêm -4024 vào cùng thay đổi với -4016

> làm đi, lập plan theo hướng đó

The decision:

1. -1106: REJECTED_DEFINITIVE on PLACEMENT only; evidence 'documented' AND demo_observed_on = 2026-10-16; note says PARAM_NOT_REQUIRED can come from a wrongly built request, including reduceOnly sent together with positionSide in hedge mode; NOT mapped to POSITION_MODE (the code alone does not prove a wrong position mode); the official USD-M page is the source; Nautilus issue #4231 is a secondary technical reference only.
2. -4016: REJECTED_DEFINITIVE on PLACEMENT only; evidence 'documented' + demo_observed_on = 2026-10-16; note distinguishes the page (PRICE_HIGHTER_THAN_MULTIPLIER_UP, price above the mark price multiplier cap) from the Demo wording ("Limit price can't be higher than 86305.10."); no hidden placement retry; a rejection is never evidence that an order is protected; refreshing mark price/filters after -4016 is the CONSUMER's job (recorded as an open follow-up for Phase 19/20, not a landing blocker).
3. -4024 (added): REJECTED_DEFINITIVE on PLACEMENT only; evidence 'documented'; NO demo_observed_on (no probe evidence); note PRICE_LOWER_THAN_MULTIPLIER_DOWN, price below the mark price multiplier floor; no retry; the table must not assume a snapshot was refreshed.
4. -1125: keep INVALID_LISTEN_KEY on LISTEN_KEY; replace the 'assumed' sentence by 'observed on Demo (smoke)' with the evidence reference (evidence/18-smoke-check.txt item f, 'PUT after DELETE ... code=-1125'); demo_observed_on = 2026-10-16; evidence stays 'documented'; classification unchanged.
5. Do not add -4131, -4183, -4184 or any other code. Keep the three-input classification (SDK class, int code, call kind); never read message text.
6. Tests: -1106, -4016, -4024 classify REJECTED_DEFINITIVE only for PLACEMENT and UNKNOWN_EXCHANGE_ERROR for every other call kind; no hidden placement retry for the three (retry_eligible false); a -1106 raised when the protective stop is placed still ends in ENTRY_WITHOUT_PROTECTIVE through the REAL SAFE_MODE branch of the execution manager (place_entry, then the protective leg, then entering SAFE_MODE), asserting the branch, not just safe_mode_eligible; -4016/-4024 do not refresh or reuse a suspect price merely because of the table (the follow-up is recorded for the consumer); -1125 keeps its mapping with updated provenance. STOP and report a blocker if any test shows a rejected protective order treated as protected.

Open follow-up the owner asked to record, not to implement: the Phase 19/20 consumer must refresh mark price and filter data after -4016 or -4024 before any later order decision and fail closed if it cannot; every new order after a rejection needs the normal human approval flow.

## Evidence

- `evidence/18-error-code-page-reread-20261017.txt`: the error-code page read on 2026-10-17 (page last modified 2026-10-16, as the page shows). It is a WebFetch summary and not character-exact. It is the documentation source for -1106, -4016, -4024 and -1125.
- `evidence/18-probe-check.txt`: the Demo probe answers for -1106 (case rejected_protective_variants) and -4016 (case id_reuse_after_filled, first run), both 2026-10-16.
- `evidence/18-smoke-check.txt` item f: the Demo smoke answer for -1125 (PUT after DELETE), 2026-10-16.
- `18-21-SUMMARY.md`: the origin of the open list "codes observed by the probe and not in the table" (-1106, -4016) and of the open "-1125 labelling" item.

## Notes (recorded by the planner, not part of the decision)

- No DECISIONS row is written. No runtime behavior changes: the execution manager and the adapters do not read REJECTED_DEFINITIVE versus UNKNOWN_EXCHANGE_ERROR (D-20 applies to a decision that changes behavior). This is the same practice as the 18-21 table marks and the 18-DEC-D01 record. If the owner wants a row, the next free number at planning time was D077 (recompute at write time).
- The owner answered the plan's open questions with the recommended defaults: plan 18-25 is not edited, its ordering after 18-26 is enforced by running 18-26 first; the stale ROADMAP Phase 18 status lines are left for the phase-closing step.

## Open items (recorded, not implemented)

- (a) The Phase 19/20 consumer must refresh mark price and filter data after -4016 or -4024 before any later order decision and fail closed if it cannot; every new order after a rejection needs the normal human approval flow.
- (b) A consumer must not use `safe_mode_eligible` to decide SAFE_MODE for a rejected protective order: these codes are no longer SAFE_MODE-eligible by the taxonomy, while the manager still enters SAFE_MODE on any unconfirmed protective leg.
- (c) The manager's own bounded query-first re-send of an entry after an ambiguous placement (`_ENTRY_MAX_ATTEMPTS`, 09-REVIEW CR-09) does not consult the taxonomy, so after a -4016 or -4024 on the ENTRY the same prices are sent once more after a probe that finds the order absent. Phase 19/20 decide whether the manager should classify and stop on REJECTED_DEFINITIVE.
- (d) -4131, -4183 and -4184 are listed by the same page and are not added.
