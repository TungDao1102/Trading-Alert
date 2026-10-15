# 16-AMEND-v2.4.0-DRAFT: exact text of research protocol v2.4.0 (S-B-interval terminal settlement)

status: DRAFT, NOT ADOPTED. Nothing in this file is a decision, and nothing in it is protocol text until the user adopts it in their own words (record `16-DEC-V240.md`, quick 261014-nnl plan 08 Task 2, a blocking-human checkpoint that has NOT run). Plan 09 lands only the adopted text, byte for byte. This file edits nothing under `docs/`, `src/`, `tests/`, `scripts/` or `.github/`.
date: 2026-10-15. Drafted against the real text of `docs/research/RESEARCH_PROTOCOL.md` (v2.3.0, 444 lines), `docs/DECISIONS.md` (last row D069), `docs/DOC_STATUS.md` (68 lines), `docs/backtest/BACKTEST_SPEC.md` (178 lines) and against the code that plans 01-06 landed (`src/backtest/semantics.py`, `lifecycle.py`, `engine.py`, `records.py`, `report.py`, `funding.py`, `case.py`, `src/research/manifest.py`, `run.py`, `feasibility.py`, `settlement_evidence.py`).
basis: `16-DEC-S-B-interval.md` (user, 2026-10-14), `16-DRAFT-S-B-interval-design.md` rev3 sections 2-5, `16-DEC-GAP-REASON.md`, `16-DEC-V230.md` (precedent), `261014-nnl-PLAN-INDEX.md` ("User-confirmed at planning").

## Placeholders (filled at landing, never guessed now)

- `<LANDING_DATE>`: the UTC date (YYYY-MM-DD) on which plan 09 lands the text; the header test needs that shape.
- `<ADOPTION_DATE>`: the date written in `16-DEC-V240.md`.
- The commit `f80e0a2d8f58e5cb96ba4633373fd195cd9529ee` in block 2 is the commit that last touched `docs/research/RESEARCH_PROTOCOL.md` when this draft was written (the v2.3.0 landing, `git log -1 -- docs/research/RESEARCH_PROTOCOL.md`). Plan 09 re-reads it before landing and replaces it only if the file changed since.

Each block below gives the target file, the anchor and the exact new text inside a fenced block. The fence is not part of the text.

---

## Block 1. Protocol header (docs/research/RESEARCH_PROTOCOL.md lines 3-7)

Replace the five header lines `> **Protocol version:** v2.3.0` ... `> **Supersedes:** v2.2.0` with:

````text
> **Protocol version:** v2.4.0
> **Status:** FROZEN
> **Frozen on:** 2026-09-19
> **Amended on:** <LANDING_DATE>
> **Supersedes:** v2.3.0
````

`Status` and `Frozen on` stay byte-identical (the D013 clock is not restarted; `tests/test_kill_gate_docs.py` pins both lines).

## Block 2. Migration paragraph (docs/research/RESEARCH_PROTOCOL.md, new subsection after the `### Migration (v2.2.0 to v2.3.0)` paragraph, line 43, and before `**Numeric-gate status (v1.1.0).**`, line 45)

Insert, with one blank line before and after:

````text
### Migration (v2.3.0 to v2.4.0)

This is a semantic amendment (execution simulation and acceptance reporting, §3, §4 and §6) per D032, D043 and D070, decided by the user on <ADOPTION_DATE> (adoption of the text, record `16-DEC-V240`; the design was decided on 2026-10-14, record `16-DEC-S-B-interval`). The v2.3.0 text is unchanged in git history at commit `f80e0a2d8f58e5cb96ba4633373fd195cd9529ee` and is superseded, not edited. What changes: (1) the data manifest may carry an optional entry `terminal_settlements` that binds a bounded settlement interval to a symbol whose terminal declaration already exists (`TerminalDeclaration` is unchanged and its `terminal_at_utc` is the terminal instant T); the interval is derived from committed, hashed evidence (index-price klines of the bound window before T and the trade kline that opens at T), the runner recomputes it from the evidence bytes before any simulation, and the entry records an interval, never a settlement price; (2) a position open at T, also the remainder after a TP1, closes at T as `SETTLEMENT` at the adverse end of the interval (LONG at `price_lower`, SHORT at `price_upper`), with the exit fee at the cost model's exit rate and zero slippage; (3) a plan still resting at T ends as `SETTLEMENT_CANCEL`, which is an unverified assumption; (4) no plan is created when the signal close plus one minute is after T (counted as `TERMINAL_BEFORE_ACTIVATION`); (5) funding stops at T; (6) a declared symbol with input data after T is refused before any simulation; (7) the manifest refuses a terminal settlement whose declared terminal is at or after the Validation start, so a settlement can reach neither Validation nor the Holdout; (8) `SETTLEMENT` is counted apart like `END_OF_DATA` and §4 states which data each gate uses; (9) `simulator_semantics_version` 2.1.0 joins the experiment identity, so a trade id or experiment id computed under v2.4.0 never equals one computed under 2.0.0 (paper decisions and fills behave the same, but their version strings and the ids derived from them change, so they are not byte-identical). In research run 1 the only declared settlement is REEFUSDT and its terminal lies in Development, so the uncertainty of the interval cannot reach G1 to G5. What does not change: G1 to G5 and every threshold (the G1 and G5 sentences word for word), the closed-trade definition (an exit by SL or TP2), G3 as one Holm-Bonferroni procedure over the 48 candidate-level hypotheses (no 96 p-values), the 40/40/20 split and the walk-forward folds, the variant budget N = 25 per family, the seven-field experiment identity tuple, the holdout rule and the consumed marker schema (only the marker's `protocol_version` moves and its entries stay empty), the cost model, the D030 kill-gate firing rule, the `Frozen on` clock start (2026-09-19, so the D013 six-month clock is not restarted), and every strategy version and parameter set (`strategy_version` v5.0.0 and the 48 parameter-set hashes are untouched; see the lineage statement earlier in this section). A symbol without a `terminal_settlements` entry is simulated as under v2.3.0 apart from the version string and the ids derived from it. Nothing is applied backwards: no holdout entry, experiment record or kill-gate decision exists, so v2.3.0 stays historical and no result was produced under it.
````

## Block 3. §3 execution assumptions (docs/research/RESEARCH_PROTOCOL.md)

Note on the plan's anchor: plan 08 says "section 2 bullet after the data end bullet, lines 205-216". The real `data end` bullet is line 214 and sits in §3 "Limit-order simulation — mandatory checklist" (lines 203-214), not in §2. The block is anchored there.

### 3a. New bullet directly after the `- **data end** — ...` bullet (line 214), before `### Baselines` (line 216)

````text
- **terminal settlement (v2.4.0)** — for a symbol with a declared terminal instant T and a `terminal_settlements` manifest entry, a position open at T (also the remainder after a TP1) closes at T as `SETTLEMENT` at the adverse end of the recorded interval (LONG at `price_lower`, SHORT at `price_upper`), with the exit fee at the cost model's exit rate and zero slippage. A plan still resting at T ends as `SETTLEMENT_CANCEL`. No plan is created for a signal whose close plus one minute is after T (`TERMINAL_BEFORE_ACTIVATION`, counted after the equity and conflict checks). Funding stops at T, and a declared symbol with input data after T is refused. `SETTLEMENT` and `SETTLEMENT_CANCEL` are kept as records, counted and reported separately, and excluded from pooled R and the closed-trade floor, like `END_OF_DATA`. A symbol without the entry is unaffected.
````

### 3b. Addition found at drafting (line 201, last sentence of the exit-ladder paragraph; optional, drop if the user prefers the minimum)

Old end of the paragraph: `A position is carried until SL, TP2 or data end; there is no time stop.` New:

````text
A position is carried until SL, TP2, data end or the declared terminal instant of its symbol (`SETTLEMENT`, §3 terminal settlement); there is no time stop.
````

### 3c. Addition found at drafting (line 227, last sentence of "NO_TRADE as a valid outcome"; optional)

Old: `The record also carries the counts of `END_OF_DATA`, `PENDING_AT_DATA_END`, fallback and stop-gap events.` New:

````text
The record also carries the counts of `END_OF_DATA`, `PENDING_AT_DATA_END`, fallback and stop-gap events and, for a case that declares a terminal settlement, the count of `SETTLEMENT` exits (`settlement_count`) and the `TERMINAL_BEFORE_ACTIVATION` no-trade count.
````

## Block 4. §4 acceptance methodology (docs/research/RESEARCH_PROTOCOL.md)

### 4a. Data used by the gates: new paragraph directly after the paragraph `A candidate passes only when G1-G5 all pass. A human may reject ...` (line 264), before `**Holdout consumed marker.**` (line 266)

````text
**Data used by the gates (v2.4.0).** G1, G2 and G3 (pooled Validation closed trades) and G4 use Validation only; G5 uses the Holdout only; no G1-G5 input uses Development. Development keeps the role §1 gives it (exploratory sweep space and selection of parameter regions); that role is unchanged, and it feeds none of the gates G1 to G5.
````

The text does not say Development "feeds reporting only": protocol §1 lines 65-66 give Development a selection role, and the Development equity path and the other symbols' Development trades do depend on the bound (one ledger per window, position sizing, DAILY_STOP). The claim is the narrower one, that no G1-G5 input uses Development. Note: line 258 (G3) does not name the trade set its p-value is computed on; D069 says "pooled Validation trades". This paragraph states it in the protocol for the first time.

### 4b. Reporting: two new bullets at the end of the list `### Uncertainty reporting — required fields`, directly after the `- Constraint sensitivity (v2.3.0): ...` bullet (line 281), before `### Kill gate D013` (line 283)

````text
- Terminal settlement (v2.4.0): `SETTLEMENT` exits and `SETTLEMENT_CANCEL` entries are counted apart, like `END_OF_DATA` and `PENDING_AT_DATA_END`. The frozen definition of a closed trade (an exit by SL or TP2) is unchanged, so a `SETTLEMENT` exit is never a closed trade: it is excluded from pooled R, from the G1 and G5 counts and from every closed-trade figure. A case that declares a settlement reports `settlement_count` in its run summary; a case without one does not carry the key. A settlement inside a Validation fold is refused (the manifest guard keeps a terminal settlement out of Validation and the Holdout); a Development settlement is reported apart.
- Settlement bound (v2.4.0): the side, the bound used, its price and the whole interval are recorded in the trade record's coverage note in a fixed format. The interval is derived from the index-price klines of the bound window before T and the trade kline that opens at T, under stated assumptions that are not verified against an official Binance source: the settlement is the mean of per-second index values over the bound window, one value per second and 60 per minute, so every minute has equal weight; the klines endpoint serves unrevised history; one tick of widening covers the rounding to the price grid. Without the equal-weight rule only the lowest low and highest high of the window are assumption free. The settlement price itself is not known, and no proxy for it (a flat price, the last mark close, an OHLC average, a midpoint) is used. The adverse bound is monotone for the net PnL of the settled trade, but it is not a global worst case: equity changes position sizing and DAILY_STOP for later entries, and R below -1 is possible for the settled trade.
````

## Block 5. §6 simulated end states (docs/research/RESEARCH_PROTOCOL.md line 387)

Replace the whole bullet with:

````text
- **simulated end states (v2.0.0, extended in v2.4.0)** — an entry ends exactly one way: filled, `EXPIRED`, `INVALIDATION_CANCEL`, `DAILY_STOP_CANCEL`, `PENDING_AT_DATA_END` or `SETTLEMENT_CANCEL`; a filled position ends as SL, TP2, `END_OF_DATA` or `SETTLEMENT`. `END_OF_DATA`, `PENDING_AT_DATA_END`, `SETTLEMENT_CANCEL` and `SETTLEMENT` are reported separately and never booked as SL, TP or expiry.
````

## Block 6. §0 lineage sentence and precedent lists (docs/research/RESEARCH_PROTOCOL.md)

Confirmed by the user on 2026-10-14 ("ok theo khuyến nghị"): v2.4.0 changes simulator semantics, not a strategy rule, so `strategy_version` stays v5.0.0.

### 6a. Line 23, second sentence

Old: `... requires a new strategy version and a new backtest record only when a detection rule, entry, SL, TP, invalidation, expiry or feature definition changes; v2.3.0 changes none of them, so `strategy_version` stays `v5.0.0` for the 48 registered parameter sets and no parameter-set hash moves.` New (only the part after the semicolon changes):

````text
; v2.4.0 changes none of them: it changes how the simulator treats a symbol's declared terminal instant (execution simulation and acceptance reporting), which is not a strategy rule of §12, so `strategy_version` stays `v5.0.0` for the 48 registered parameter sets and no parameter-set hash moves. Trade ids and experiment ids do change, because `simulator_semantics_version` 2.1.0 is part of their identity; that is an identity change, not a strategy-version change.
````

(The text starts at the semicolon that ends `... feature definition changes`; everything before it and everything after `no parameter-set hash moves.` through the end of the paragraph, `*Registration lineage* ...`, stays byte-identical.)

### 6b. Line 21, precedent list

Old: `(precedents: `v1.1.0` minor, `v2.0.0` major, `v2.1.0` minor, `v2.2.0` minor, `v2.3.0` minor)` New:

````text
(precedents: `v1.1.0` minor, `v2.0.0` major, `v2.1.0` minor, `v2.2.0` minor, `v2.3.0` minor, `v2.4.0` minor)
````

### 6c. Line 431, precedent list in Appendix A

Same replacement as 6b (the same fragment appears in the bullet `**Semantic change** to dataset splits, ...`).

## Block 7. Amendment log (docs/research/RESEARCH_PROTOCOL.md, new last bullet after the v2.3.0 bullet, line 444)

````text
- **v2.4.0 - <LANDING_DATE> - D070 (semantic).** Execution simulation and acceptance reporting for a symbol with a declared terminal instant. The manifest gains an optional `terminal_settlements` entry (a bounded settlement interval recomputed from committed, hashed evidence; an interval, never a settlement price); a position open at the terminal instant closes as `SETTLEMENT` at the adverse end of the interval, a resting plan ends as `SETTLEMENT_CANCEL`, no plan is created when the signal close plus one minute is after the terminal instant (`TERMINAL_BEFORE_ACTIVATION`), funding stops there, and a declared symbol with later data is refused. `SETTLEMENT` is counted apart like `END_OF_DATA` and never a closed trade; §4 states that G1 to G4 use Validation only, G5 the Holdout only, and no G1-G5 input uses Development; the manifest refuses a settlement at or after the Validation start. `simulator_semantics_version` 2.1.0 joins the experiment identity. G1 to G5 and every threshold, the closed-trade definition, one Holm-Bonferroni over 48, the split, N = 25 per family, the identity tuple, the holdout rule, the cost model, every strategy version and parameter set are unchanged and nothing is applied backwards (no holdout entry or experiment record exists). `Frozen on` is unchanged (the D013 clock is not restarted); `Amended on` is <LANDING_DATE> and `Supersedes: v2.3.0`.
````

## Block 8. docs/DECISIONS.md, new row D070 (append after the D069 row, the last line; the same change appends D071 from block 9)

The only row in the file that may contain the phrase `protocol v2.4.0 frozen` (DC-03 and `tests/test_kill_gate_docs.py` count lines). It must not contain `protocol v2.3.0 frozen` (that test counts exactly one line, D068). No pipe character inside a cell.

````text
| D070 | Research protocol v2.4.0 frozen: bounded terminal settlement of a delisted symbol and the data each acceptance gate uses | Accepted (<LANDING_DATE>, implements the user decision of 2026-10-14 recorded in .planning/phases/16-paper-runtime-composition/decisions/16-DEC-S-B-interval.md, which closes the open item of .planning/phases/16-paper-runtime-composition/decisions/16-DEC-GAP-REASON.md, and the user adoption of the text recorded in .planning/phases/16-paper-runtime-composition/decisions/16-DEC-V240.md) | Semantic amendment (protocol v2.3.0 to v2.4.0), protocol v2.4.0 frozen, made by the D032/D043/D052 procedure because the execution simulation and the acceptance reporting changed (sections 3, 4 and 6). Header `Frozen on` 2026-09-19 is unchanged, `Amended on` is <LANDING_DATE> and `Supersedes` reads v2.3.0, so the D013 six-month clock is not restarted. The v2.3.0 text is preserved in git at commit f80e0a2d8f58e5cb96ba4633373fd195cd9529ee. DECIDED: (a) REEFUSDT stops trading at 2025-01-22T09:00:00Z (the instant and the announcement URL were confirmed by the user on 2026-10-14) and its settlement price is not known; it is carried as a bounded interval and no proxy price is used. (b) The manifest gains an optional entry terminal_settlements keyed by symbol; TerminalDeclaration keeps exactly its four fields and supplies the terminal instant T; each entry stores the nominal bounds as reduced fractions, the tick-widened index bounds, the bounds of the trade kline that opens at T, and the union as price_lower and price_upper (0.000845 and 0.000887 for REEFUSDT, option (a)); the runner recomputes every stored bound from the committed evidence bytes (docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/) and fails closed on a mismatch; the case schema stays backtest-case/2 with an optional key. (c) A position open at T closes as SETTLEMENT at the adverse end (LONG price_lower, SHORT price_upper), exit fee at the cost model's exit rate, zero slippage; a resting plan ends as SETTLEMENT_CANCEL (an unverified assumption); no plan is created when the signal close plus one minute is after T (TERMINAL_BEFORE_ACTIVATION, counted after the equity and conflict checks); funding stops at T; a declared symbol with data after T is refused; the settled or cancelled symbol is not booked again by a later DAILY_STOP. (d) SETTLEMENT is counted apart like END_OF_DATA, is never a closed trade, is excluded from pooled R and the closed-trade floor, and is reported as settlement_count only when the case declares a settlement. (e) The manifest refuses a settlement whose declared terminal is at or after the Validation start, so no settlement can reach Validation or the Holdout; protocol section 4 states that G1, G2, G3 and G4 use Validation only, G5 the Holdout only, and no G1-G5 input uses Development, and does not claim that Development feeds reporting only (section 1 gives Development a selection role). (f) The adverse bound is monotone for the settled trade's net PnL but not a global worst case (equity changes sizing and DAILY_STOP) and R below -1 is possible. (g) simulator_semantics_version moves from 2.0.0 to 2.1.0 and joins the experiment identity; trade ids and experiment ids change; paper decisions and fills behave the same. UNCHANGED: G1 to G5 and every threshold (the G1 and G5 sentences word for word), the closed-trade definition, one Holm-Bonferroni over the 48 hypotheses (no 96 p-values), the split, the variant budget N = 25 per family, the seven-field identity tuple, the holdout rule and the holdout_consumed.json schema (protocol_version moves to v2.4.0, entries stay empty), the cost model, the D030 rule, strategy_version v5.0.0 and the 48 parameter sets and their hashes (a protocol change that is not a strategy rule starts no new strategy version, TRADING_STRATEGY_SPEC section 12). Nothing is applied backwards: no holdout entry, experiment record or kill-gate decision exists, so v2.3.0 stays historical. OPEN, not decided here: the O-03b manifest and its freeze with the terminal_settlements row (the manifest hash changes, so the run authorization O-03 is re-issued), the S1 manifest carrying the same entry with its own hash (S1 p-values stay outside the Holm), the six S0 and S1 execution bindings of plan 16-46, any run authorization, the Holdout; the unverified assumptions (the settlement is the equal-weight mean of per-second index values over the bound window, the one-tick widening, the cancel of a resting plan at T, the fee rate on settlement); the unexplained 09:00 trade kline print at 0.000880, which lies inside the stored interval. Same-change witnesses: this row, the protocol header and the DOC_STATUS index line. SYNCHRONIZED FILES: docs/research/RESEARCH_PROTOCOL.md, docs/research/holdout_consumed.json, docs/DECISIONS.md, docs/DOC_STATUS.md, docs/backtest/BACKTEST_SPEC.md, .github/workflows/research-gate.yml, scripts/decision_alignment/protocol.py, tests/test_kill_gate_docs.py, tests/test_decision_alignment_protocol.py, tests/test_decision_alignment_bookkeeping.py and tests/test_research_protocol_v240.py. Reversibility: one-way (every trade id and experiment id changes and the regenerated fixtures of D071 would need regenerating again). |
````

Drafting note for plan 09 (real code, not in plan 08's text): `tests/test_decision_alignment_bookkeeping.py` line 389 hard-codes `bk._decision_row(text, "D068")` as "the row of the header version"; after the bump the freeze row is D070, so that line (and its docstring "v2.3.0, D068") must move to D070 in the same change, and `tests/test_kill_gate_docs.py` lines 211-222 (the D068/D069 order test counts `protocol v2.3.0 frozen` lines) and 291-292 (`_header_version() == "v2.3.0"`) move with it. D068 keeps its phrase.

## Block 9. docs/DECISIONS.md, new row D071 skeleton (directly after D070)

Style of D053. The MOVED list is NOT written here: plan 09 compiles it from `261014-nnl-07-SUMMARY.md` (which does not exist yet) and the user-approved inventory. The row must not contain the freeze phrase `protocol v2.4.0 frozen`.

````text
| D071 | S-B-interval deliberate regeneration inventory (fixtures, pins and hashes that moved) | Accepted (<LANDING_DATE>, inventory compiled from the quick 261014-nnl plan 07 SUMMARY and the inventory the user approved, D053 style) | Nothing below changed silently; each item was regenerated or re-pinned on purpose, from the test's own build path and never typed, and is guarded by a test. No file under params/ changed, so no registry parameter_set_hash and no strategy version (v5.0.0) moved. The version bump is simulator_semantics_version 2.0.0 to 2.1.0 (D070). MOVED: <TO BE COMPILED IN PLAN 09 FROM 261014-nnl-07-SUMMARY.md: every version-derived trade_id, experiment_id, trades_digest, result_summary_json, golden and stored record that changed, with the old and new values and the plan or test that guards each; classes VERSION_PIN, DERIVED_DIGEST and STORED_RECORD>. NEW, not moved: src/research/settlement_evidence.py, the committed evidence folder docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/ (nine files, covered by .gitattributes -text), and tests/test_research_settlement_evidence.py, tests/test_research_terminal_settlement_manifest.py, tests/test_research_terminal_settlement_integration.py, tests/test_backtest_terminal_settlement.py, tests/test_backtest_terminal_engine.py, tests/test_backtest_terminal_funding.py, tests/test_terminal_settlement_consumers.py and tests/test_research_protocol_v240.py. NOT MOVED by design: every params/ file, the 48 parameter-set hashes, the seven-field identity tuple, the holdout_consumed.json schema and entries, the paper loop and every paper test, tests/test_backtest_funding.py, and every case without a terminal_settlements entry (identical to 2.0.0 apart from the version string and the ids derived from it, design test 10). Reversibility: costly to undo, since every consumer of the regenerated fixtures and hashes would need regenerating. |
````

## Block 10. docs/DOC_STATUS.md

### 10a. Index line 13, replace the whole line

````text
- `research/RESEARCH_PROTOCOL.md` — Frozen on 2026-09-19, amended <LANDING_DATE> (v2.4.0; D029, D030, D043, D052, D057, D060, D065, D067, D068, D069, D070); executable gate at `.github/workflows/research-gate.yml`
````

(`tests/test_kill_gate_docs.py` requires the line to start with ``- `research/RESEARCH_PROTOCOL.md` ``, to contain the header version and D030, D043, D052, D067, D068, D069, and no `pending-freeze`, `DRAFT` or `Living research`.)

### 10b. Dated log line, appended after the last line (the 2026-10-14 v2.3.0 line, line 68)

````text
- <LANDING_DATE> — `research/RESEARCH_PROTOCOL.md` v2.4.0 semantic amendment per D070 (execution simulation and acceptance reporting): an optional manifest entry `terminal_settlements` binds a bounded settlement interval (recomputed from committed, hashed evidence, never a settlement price) to a declared terminal instant; an open position closes as `SETTLEMENT` at the adverse end, a resting plan ends as `SETTLEMENT_CANCEL`, no plan is created when the signal close plus one minute is after the terminal instant (`TERMINAL_BEFORE_ACTIVATION`), funding stops there and a declared symbol with later data is refused; `SETTLEMENT` is counted apart like `END_OF_DATA` and is never a closed trade; section 4 states that G1 to G4 use Validation only, G5 the Holdout only and no G1-G5 input uses Development; `simulator_semantics_version` moves to 2.1.0 and joins the experiment identity; `research/holdout_consumed.json` `protocol_version` moves to v2.4.0 with no entries; `Frozen on` unchanged; nothing applied backwards; no strategy version or parameter set moved; the regeneration inventory is D071; `BACKTEST_SPEC.md` pointers, the research-gate comment, the witness tests and the Validation-only invariant test follow.
````

## Block 11. docs/backtest/BACKTEST_SPEC.md

### 11a. Section 6 (line 64): replace the `data end` bullet and add the terminal settlement bullet after it

Old (line 64): `- data end: an open position closes at the last mark close as `END_OF_DATA`, a resting plan is `PENDING_AT_DATA_END` (never `EXPIRED`); both are kept as records, counted and reported separately and excluded from pooled R and the closed-trade floor.` New (two bullets):

````text
- data end: an open position closes at the last mark close as `END_OF_DATA`, a resting plan is `PENDING_AT_DATA_END` (never `EXPIRED`); both are kept as records, counted and reported separately and excluded from pooled R and the closed-trade floor,
- terminal settlement (protocol v2.4.0, D070): for a symbol with a declared terminal instant T and a `terminal_settlements` manifest entry, an open position closes at T as `SETTLEMENT` at the adverse end of the recorded interval (LONG at `price_lower`, SHORT at `price_upper`, exit fee at the exit rate, zero slippage), a resting plan ends as `SETTLEMENT_CANCEL`, no plan is created when the signal close plus one minute is after T (`TERMINAL_BEFORE_ACTIVATION`), funding stops at T and a declared symbol with later data is refused; the end states are kept as records, counted and reported separately and excluded from pooled R and the closed-trade floor.
````

### 11b. Addition found at drafting (section 4, line 37, last two sentences; optional)

Old: `A position is carried until SL, TP2 or data end; there is no time stop. A position open at data end closes at the last mark close as `END_OF_DATA`.` New:

````text
A position is carried until SL, TP2, data end or the declared terminal instant of its symbol; there is no time stop. A position open at data end closes at the last mark close as `END_OF_DATA`; a position open at a declared terminal instant closes as `SETTLEMENT` (section 6).
````

### 11c. Line 82, version pointer

Old: `... are pre-registered in `docs/research/RESEARCH_PROTOCOL.md` v2.3.0 §1 and §4 per D032 and D043.` New:

````text
Fixed proportions (40% Development, 40% Validation as four consecutive walk-forward test folds, last 20% final holdout, single-use) are pre-registered in `docs/research/RESEARCH_PROTOCOL.md` v2.4.0 §1 and §4 per D032 and D043.
````

### 11d. Line 173, version pointer

New whole line:

````text
The numerical acceptance thresholds (trade floor, expectancy bound, multiple-testing correction, drawdown ceiling, single-use holdout with a floor of at least 30 closed trades in the holdout) are pre-registered in `docs/research/RESEARCH_PROTOCOL.md` v2.4.0 §4 per D032, D043, D060 and D069.
````

Line 14 (`protocol v2.0.0, D052`) is history and stays. `docs/trading/RISK_MANAGEMENT.md` line 62 and `docs/research/GEOMETRY_AUDIT.md` lines 129 and 157 also name v2.0.0 as history and stay.

## Block 12. docs/research/holdout_consumed.json (execution gated; NOT authorized by this draft or by 16-DEC-V240.md)

Shape only (the user accepted this shape at planning on 2026-10-14; the edit itself runs only at plan 09 Task 1 after the user's words at that checkpoint). The file today is exactly:

````text
{
  "schema": "holdout-consumed/2",
  "protocol_version": "v2.3.0",
  "entries": []
}
````

After: only the value of `protocol_version` changes, to `"v2.4.0"`; `schema` and the empty `entries` array stay byte-identical (LF line endings, as the repository stores it). `tests/test_decision_alignment_protocol.py` line 148 requires the marker's `protocol_version` to equal the header version, so the marker and the header must move in the same commit.

---

## Answered at planning (user, 2026-10-14, words: ok theo khuyến nghị)

These settle design choices only. They authorize no code change, no commit, no version bump, no protocol text and no marker edit.

- Block 6: v2.4.0 changes simulator semantics, not a strategy rule, so `strategy_version` stays v5.0.0.
- Numbering: D070 is the amendment and the only freeze row; D071 is the regeneration inventory.
- Block 12: the one-field shape is accepted, execution gated by plan 09 Task 1 (the user's words at that checkpoint; not authorized by this draft).
- Names: exit kind `SETTLEMENT`, entry kind `SETTLEMENT_CANCEL`, no-trade label `TERMINAL_BEFORE_ACTIVATION`.
- The no-trade label is counted after the equity and conflict checks (equity, evaluate, conflict, terminal, plan).
- `settlement_count` appears in the run summary only when the case declares a settlement.
- Bound side and values are recorded in a fixed-format `coverage_note` piece; no new TradeRecord field.

## Items needing the user's words now

- Adopt the text of blocks 1-12 as drafted, or name edits. Additions 3b, 3c and 11b are marked optional because the plan did not list them; they exist so the protocol and BACKTEST_SPEC do not keep a sentence ("a position is carried until SL, TP2 or data end") that the new text contradicts.

## Drafting notes (not part of any block; where plan 08 text and the real files differed)

1. Plan 08 puts the "terminal settlement" bullet in section 2 (lines 205-216); the `data end` bullet is line 214 in section 3. Block 3a is anchored there.
2. Plan 08 says the exit fee is at the taker rate. The code books it at the cost model's `fee_rate_exit` (0.0005 in the canonical sets, the taker rate there). The blocks say "the cost model's exit rate", which stays true if a set ever changes it.
3. The manifest guard also refuses a declared terminal at or before the Development start and a non-minute-aligned one (`src/research/manifest.py`), beyond the "at or after the Validation start" rule of the plan; the blocks state only the Validation rule, which is the one with consequences for G1-G5.
4. Design section 8 and the B13 note said the 09:00 trade print 0.000880 lies above the index upper bound 0.000869; under the decided union interval (0.000845, 0.000887) it lies inside it. D070 says "inside the stored interval".
5. `tests/test_decision_alignment_bookkeeping.py` line 389 and `tests/test_kill_gate_docs.py` lines 211-222 and 291-292 pin D068 and v2.3.0 as the current freeze (see the note after block 8); plan 09 must move them to D070 and v2.4.0.
6. D068's text says the S1 constraint file "does not exist yet"; `docs/research/preregistration/research-run-1-constraints-S1.json` exists in the tree now. Not touched here (D068 is history); noted for the S1 manifest work.
