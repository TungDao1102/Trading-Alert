# 19-DEC-D055-DRAFT: proposed closure of D055 (draft for the owner)

Status: DRAFT. Not a DECISIONS row. `docs/DECISIONS.md` has no row for it. The owner accepts, edits or rejects it; a row (provisional id D079; D077 is the stop-lost row of 19-REVIEW WR-04 and D078 is the approved-quantity row of 19-REVIEW WR-01) is written only after that.

Basis: the owner's words of 2026-10-18 ("adopt kèm các điểm trên"), recorded in `19-NOTES.md`, and the Phase 18 Demo probe evidence of 2026-10-16.

Proposed text:
1. Execution model (a) is the only V1 model: the protective stop is STOP_MARKET `closePosition=true`, placed after the first fill with positive quantity, confirmed by REST query. Model (b) is not built.
2. No new entry while any position is unprotected. A stop not confirmed before `max_unprotected_ms`, or an entry not terminal before `entry_terminal_timeout`, leads to CLOSE_REQUIRED and an automatic reduce-only MARKET close (D034 already approves the principle; the parameters are the only open part).
3. Both deadlines are `NOT_CONFIGURED` in `binance-limits-v1.toml`; the live path refuses while they are unset; the owner sets them after the probes.
4. Hedge Mode is unsupported in V1.
5. No continuous TP1 resizing; TP legs are placed after the entry is terminal and the position is reconciled (settles G2-032 for the normal flow).
6. LIVE stays blocked until the 11 Demo probes in `19-NOTES.md` are run by the owner and recorded.

Affected ROADMAP lines (edit only after acceptance): Phase 19 criteria 1 and 3, inherited item [D055], [G2-032].

## Evidence update of 2026-10-22 (added by the assistant; the proposed text above is unchanged)

Source: the Demo runs recorded in `19-OWNER-GAPS.md` section 2a (demo-observed, not mainnet, not verified on mainnet), commit 48a26473. Nothing below changes a proposed item; it is what the owner should read before accepting, editing or rejecting.

Supports the draft:

- Item 1: a `closePosition=true` STOP_MARKET and TAKE_PROFIT_MARKET were accepted with a position open (P1, A6); the same request with no position gets -4509 (Phase 18). Both `closePosition` legs ended `EXPIRED` when the position closed, so no orphan stop was left (A3, P6).
- Item 4: the Demo account is in One-way mode (`dualSidePosition` false).
- Item 5: take-profit legs were accepted after the entry filled; a TP1 of 0.0004 (0.5 of 0.0008) triggered and filled although its notional (32.7 USDT) was below the 50 USDT minimum.

Needs the owner's reading:

- Item 6 (the 11 probes): P1, P2, P6, P8, P10 and P11 were observed; P4, P5 and P9 only in part; P3 (a partial fill) cannot be produced on Demo within the approved quantity and notional cap (the book held about 2866 BTC inside the price band); P7 gave a sample of cancel answers (-2011 after the fill), not the order of a cancel against a fill. The owner chooses: treat the probes as sufficient, reword item 6 (for example "every probe Demo can produce is run and recorded; what Demo cannot show is left to the Phase 26 canary"), or ask for more.
- The GTD entry is not an exchange-side backstop on Demo: it was still `NEW` 120 s and 840 s after `goodTillDate` (A2). Item 2 already relies on `entry_terminal_timeout_ms` and not on the expiry, so the text holds; O-02 (GTD as backstop) and any wording that says an expired GTD entry is terminal should say "not confirmed on Demo, unknown on mainnet".
- A read of an algo order by client id right after its placement answered -2013 although the order was `NEW` and listed in the open algo orders; a second placement with the same id then gets -4116. Item 1 says the stop is "confirmed by REST query". In `src/execution/protection.py`: a never-confirmed stop that reads ABSENT is placed again under the same id (`_confirm`, B2/B3); a -4116 on that placement classifies as `DUPLICATE_CLIENT_ID`, which `_place_stop` returns as `AMBIGUOUS` and `_on_place_outcome` does not act on; the next step reads again. So the exchange refusing the duplicate is harmless. The cost is that a stop which exists but keeps reading ABSENT until `max_unprotected_ms` ends in CLOSE_REQUIRED and a reduce-only close of a position that was in fact protected (fail-safe, not unsafe). How long the by-client-id read lags is not measured (the runs show a miss at 0 ms and a hit at about 90 s). The open-algo-orders listing showed the stop at once. Suggested follow-up, not part of this draft: confirm the stop by the algo id or the open-algo listing as well, with a fake that models the lag (Phase 20/24). `tests/test_protection_coordinator.py` was not checked for such a lag.
- Closing D055 changes tests: `tests/test_phase18_gate.py::test_invariant_8_d055_stays_open` requires the D055 row to contain "stays OPEN", and `tests/test_phase19_gate.py::test_invariant_8_d055_stays_open_and_the_phase18_gate_is_green` requires "OPEN" in it. Writing the new row therefore needs the matching change of those two assertions in the same change, and `verify_decision_alignment.py all` run afterwards.
