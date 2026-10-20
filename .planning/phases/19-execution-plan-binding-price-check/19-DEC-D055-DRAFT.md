# 19-DEC-D055-DRAFT: proposed closure of D055 (draft for the owner)

Status: DRAFT. Not a DECISIONS row. `docs/DECISIONS.md` has no row for it. The owner accepts, edits or rejects it; a row (provisional id D078; D077 is the stop-lost row of 19-REVIEW WR-04) is written only after that.

Basis: the owner's words of 2026-10-18 ("adopt kèm các điểm trên"), recorded in `19-NOTES.md`, and the Phase 18 Demo probe evidence of 2026-10-16.

Proposed text:
1. Execution model (a) is the only V1 model: the protective stop is STOP_MARKET `closePosition=true`, placed after the first fill with positive quantity, confirmed by REST query. Model (b) is not built.
2. No new entry while any position is unprotected. A stop not confirmed before `max_unprotected_ms`, or an entry not terminal before `entry_terminal_timeout`, leads to CLOSE_REQUIRED and an automatic reduce-only MARKET close (D034 already approves the principle; the parameters are the only open part).
3. Both deadlines are `NOT_CONFIGURED` in `binance-limits-v1.toml`; the live path refuses while they are unset; the owner sets them after the probes.
4. Hedge Mode is unsupported in V1.
5. No continuous TP1 resizing; TP legs are placed after the entry is terminal and the position is reconciled (settles G2-032 for the normal flow).
6. LIVE stays blocked until the 11 Demo probes in `19-NOTES.md` are run by the owner and recorded.

Affected ROADMAP lines (edit only after acceptance): Phase 19 criteria 1 and 3, inherited item [D055], [G2-032].
