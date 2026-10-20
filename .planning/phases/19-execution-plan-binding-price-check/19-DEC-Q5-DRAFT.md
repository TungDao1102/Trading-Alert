# 19-DEC-Q5-DRAFT: proposed closure of Q5 (draft for the owner)

Status: DRAFT. Not a DECISIONS row. `docs/DECISIONS.md` has no row for it. The owner accepts, edits or rejects it; a row (provisional id D079; the D055 draft waits for D078, and D077 is the stop-lost row of 19-REVIEW WR-04) is written only after that.

Basis: the owner's decision of 2026-10-20 (Q5) that answers the Phase 18 review item src/WR-02 and 19-RESEARCH Q5 (the second `place_entry` attempt), and quick task 261020-jua.

Proposed text:
1. No order placement is re-sent after any error, whatever the error category and whatever the probe answers: no loop, no recursion, no configuration knob. This covers entries, protective stops, take-profits and closes.
2. The entry outcome table:
   - a refusal before send goes to NO_TRADE `ENTRY_REFUSED_BEFORE_SEND`;
   - a definitive rejection goes to NO_TRADE `EXCHANGE_CONSTRAINT`;
   - an ambiguous error gets one probe by the client order id. Found goes to ACKED plus hand-off to the protection coordinator. Not found, a probe error or an indeterminate answer go to intent UNKNOWN, SAFE_MODE `ENTRY_STATE_UNKNOWN` and `RECONCILIATION_REQUIRED`, never REJECTED or NO_TRADE.
3. An UNKNOWN entry is resolved by query only (intent recovery, Phase 20), and new entries stay blocked until then.
4. Open part, owned by the owner (O-04): the numbers for bounded reconciliation (windows, re-probe counts) and whether the 3-day not-found rule of restart recovery (EXECUTION_SPEC 10.1) may apply to an entry that went UNKNOWN after an ambiguous error. None are proposed here.

Evidence (copied from the project sources, not re-fetched):
- Binance New Order `newClientOrderId`: "A unique id among open orders. Automatically generated if not sent." (`docs/SOURCES.md`, Phase 17 rows of 2026-10-01 and the live re-read of 2026-10-07; `docs/integration/BINANCE.md` section 6.1). Confidence: documentation text.
- Error `-1007` TIMEOUT: "Send status unknown; execution status unknown." and `-1006`: "... Execution status unknown." (`ERROR_CODE_TABLE` in `src/domain/exchange_errors.py`, label documented, from research baseline B7 of 2026-10-15). Confidence: a WebFetch summary, not character-exact.
- `BINANCE.md` section 6.1: once an order is FILLED or CANCELED its id is free again; Query Order does not find old CANCELED or EXPIRED orders.
- Demo observations of 2026-10-16 (`docs/SOURCES.md`, "Demo-observed facts"; demo, not mainnet): a reused client id was accepted after CANCELED (normal and algo order) and after FILLED (normal order, second run); a duplicate `clientAlgoId` while the first order was open was rejected with `-4116`.
- The pages read contain no statement of idempotency and none of immediate query visibility for a new order. This is the absence of a statement, not a quote from Binance.

Reasoning: because the id is unique only among open orders and nothing documents that a just-placed order is visible to a query, `found=False` right after an ambiguous error does not prove the order is absent. The entry is a GTD LIMIT and its stop is placed only after a fill (D-10). An entry recorded as REJECTED that was in fact resting could fill with nothing protecting it. Failing closed costs at worst a missed trade.

Implementation status: done by quick task 261020-jua (the `test(q5)` and `feat(q5)` commits on branch p19-15). The entry path was the only placement with a second attempt; the protective, take-profit and close placements have no attempt loop.

Affected lines, to edit only after acceptance: the `docs/DECISIONS.md` row (new). No ROADMAP criterion names Q5. The owner-gap register of plan 19-17 lists Q5 and is not touched here.
