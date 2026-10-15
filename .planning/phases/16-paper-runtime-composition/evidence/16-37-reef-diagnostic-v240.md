# 16-37 REEFUSDT technical diagnostic on simulator semantics 2.1.0 with the bounded terminal settlement: 48 of 48 points run, the 33 formerly failing points now end in one SETTLEMENT

date: 2026-10-15. Authorised by the user's "chạy lại chẩn đoán REEF trên code mới đi" (2026-10-15) inside the reviewer's scope of 2026-10-14 (read-only, REEF-only, 48 registered points, S0, Development only). This is evidence for a decision, not a decision. It is NOT a research run: no `run.py main`, no `assemble`, no ExperimentRecord, no manifest file, no `holdout_consumed.json` change, no Validation or Holdout day read, no O-03, no 12-symbol portfolio run, no change to code, gaps or semantics, no push. No PnL, expectancy, R, win rate or ranking figure is computed or reported.

Code under test: repository HEAD `bdb47a2c93f472cb24068f895aba982d9af7b7c6` (quick 261014-nnl plans 01-10 landed: `SIMULATOR_SEMANTICS_VERSION` 2.1.0, protocol v2.4.0, `terminal_settlements`). The tree had no source change between the sanity run and the 48 runs.

## Method (as run)
- Script: `evidence/16-37-reef-diagnostic-v240-script.txt` (sha256 `d98e9b10bdaf72a07fabb0e5f16056a70ec1d1ee1059a96f9f67436c2d4614de`; throwaway, copied as text so it is not linted). It keeps the structure of `evidence/16-37-reef-diagnostic-script.txt` (old run, sha256 `00d2c53e...42f79`): preconditions, one process per grid point (`REEF_ONLY=<id>`, `.venv` Python, `-I`, never parallel, one process at a time), whitelist output.
- Preconditions, asserted by every one of the 48 processes (48 `PRECONDITIONS OK` lines): constraint file S0 sha256 `4307eec74feeab04081b872866895f70568f1d289b8a249fc7de702e71e11d3f` with one REEFUSDT row; the inventory file sha256 `b9b8426a31a2821d27d07fc49457cabcdc7cd887910b8185269de3bfa5982b34`; the dataset id derived from that inventory over its 49,549 runner-read files (date before 2026-05-10) equals `34a1efa2622b04eca14af58365d5d9d539525e8982c1271e1a9d5b006d18d7d2`; all 1,077 REEFUSDT files re-hashed equal to the inventory; `simulator_semantics_version` 2.1.0. (As in the old run the 11 other symbols' files were not re-hashed here.)
- The REEF terminal declaration and the `terminal_settlements` row go through the landed code, not hand-made dicts: `TerminalDeclaration` (REEFUSDT, DELISTED_CAPPED, T = 2025-01-22T09:00:00Z, the announcement URL of the old run); `recompute_settlement_bounds` over the committed evidence bytes (`docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/`, index klines B, trade kline A, supporting F) with the S0 row's `price_tick_size` 0.000001, asserted to give nominal 5123/6000000 and 347/400000, tick-widened index 0.000852 / 0.000869, trade candle 0.000845 / 0.000887, union 0.000845 / 0.000887; a `TerminalSettlement` and a one-symbol `DatasetManifest` built from those values (the manifest object exists only in memory, its post-init cross-validation ran; its Validation and Holdout dates are the reviewer's tentative window of `evidence/16-37-data-snapshot.md` and are metadata only); then `src.research.run._load_constraints`, `check_terminal_settlement_evidence(manifest, repo_root)` (sha256 of every evidence file, full recompute, comparison with all eight stored values; passed in all 48 processes) and `terminal_settlement_case_rows(manifest, development_window)`, which returned the single row `{kind BOUNDED_BY_INDEX_KLINES, price_lower 0.000845, price_upper 0.000887, recorded_evaluation UNION_ADVERSE_BOUND, symbol REEFUSDT, terminal_at_utc 2025-01-22T09:00:00+00:00}`.
- Window: Development `[2024-10-03T00:00Z, 2025-07-22T00:00Z)`, `as_of_day_utc` 2025-07-22 (as the old run; the runner would use the manifest's validation end date, which was not used so that no Validation day is touched), strategy 1h, context 4h, `account_state` equity 600 and risk_rate 0.005, cost model from each registered set (asserted equal to the registry hash), `build_case_input_data(..., terminal_declarations=[decl])` (no hand-written GapRange; `allowed_gaps_used` is 4 on every point, as in the old run), then `data.to_case_input(..., constraint_history=<S0 REEF row>, terminal_settlements=<case row>)` and `simulator.run`. `_check_manifest_against_store` was not called (it reads the Validation range) and `_run_split`/`assemble` were not called (no record).
- Tick and the manifest `condition` text are the values of the landed tests (`tests/test_research_terminal_settlement_manifest.py`); a real manifest file does not exist yet, so the hash of this in-memory manifest is not a registered value and is not reported.

## Result
- **48 of 48 points OK, 0 errors** (old run: 15 clean, 33 `FundingCoverageError`). No error of any kind, so no error other than the old one appeared. Every process had an empty stderr.
- **The 33 formerly failing points are exactly the 33 points that now carry one `SETTLEMENT` trade; the 15 formerly clean points have none** (set difference empty both ways). Formerly failing: a01-a14, a16, b07, b08, c01-c16. Formerly clean: a15, b01-b06, b09-b16.
- `SETTLEMENT_CANCEL`: 0 points, 0 trades. `settlement_count` in `run_summary` (the key is present on all 48 points because the case declares a settlement): 1 on the 33 points, 0 on the other 15.
- `TERMINAL_BEFORE_ACTIVATION` (no plan because the signal close + 1 minute is after T): 1 on a15, 0 on the other 47. a15 is the one formerly clean trend-pullback point; it has no SETTLEMENT.
- `pending_at_data_end`: none on any point (`pending_at_data_end_count` 0 on 48 of 48); `end_of_data_count` 0 on 48 of 48. `allowed_gaps_used` 4 on 48 of 48.
- Every point reports `simulator_semantics_version` 2.1.0.

Per point, counts only (exit kinds are of filled trades; entry kinds include unfilled plans):

| point | status | exit kinds | entry kinds | settlement_count | TERMINAL_BEFORE_ACTIVATION |
|---|---|---|---|---|---|
| a01 | OK | SETTLEMENT 1, SL 43, TP2 7 | ENTRY_FILLED 51, EXPIRED 36, REJECT 23 | 1 | 0 |
| a02 | OK | SETTLEMENT 1, SL 47, TP2 6 | ENTRY_FILLED 54, EXPIRED 19, REJECT 25 | 1 | 0 |
| a03 | OK | SETTLEMENT 1, SL 24, TP2 4 | ENTRY_FILLED 29, EXPIRED 29, REJECT 78 | 1 | 0 |
| a04 | OK | SETTLEMENT 1, SL 29, TP2 3 | ENTRY_FILLED 33, EXPIRED 16, REJECT 78 | 1 | 0 |
| a05 | OK | SETTLEMENT 1, SL 21, TP2 1 | ENTRY_FILLED 23, EXPIRED 39, REJECT 243 | 1 | 0 |
| a06 | OK | SETTLEMENT 1, SL 23, TP2 1 | ENTRY_FILLED 25, EXPIRED 21, REJECT 230 | 1 | 0 |
| a07 | OK | SETTLEMENT 1, SL 16 | ENTRY_FILLED 17, EXPIRED 25, REJECT 313 | 1 | 0 |
| a08 | OK | SETTLEMENT 1, SL 16 | ENTRY_FILLED 17, EXPIRED 13, REJECT 296 | 1 | 0 |
| a09 | OK | SETTLEMENT 1, SL 21, TP2 5 | ENTRY_FILLED 27, EXPIRED 18, REJECT 18 | 1 | 0 |
| a10 | OK | SETTLEMENT 1, SL 23, TP2 5 | ENTRY_FILLED 29, EXPIRED 13, REJECT 18 | 1 | 0 |
| a11 | OK | SETTLEMENT 1, SL 16, TP2 2 | ENTRY_FILLED 19, EXPIRED 17, REJECT 34 | 1 | 0 |
| a12 | OK | SETTLEMENT 1, SL 17, TP2 2 | ENTRY_FILLED 20, EXPIRED 13, REJECT 34 | 1 | 0 |
| a13 | OK | SETTLEMENT 1, SL 20, TP2 2 | ENTRY_FILLED 23, EXPIRED 28, REJECT 84 | 1 | 0 |
| a14 | OK | SETTLEMENT 1, SL 21, TP2 2 | ENTRY_FILLED 24, EXPIRED 16, REJECT 84 | 1 | 0 |
| a15 | OK | SL 14, TP2 2 | ENTRY_FILLED 16, EXPIRED 25, REJECT 135 | 0 | 1 |
| a16 | OK | SETTLEMENT 1, SL 15, TP2 2 | ENTRY_FILLED 18, EXPIRED 12, REJECT 103 | 1 | 0 |
| b01 | OK | SL 17 | ENTRY_FILLED 17, EXPIRED 10 | 0 | 0 |
| b02 | OK | SL 16 | ENTRY_FILLED 16, EXPIRED 11 | 0 | 0 |
| b03 | OK | SL 7, TP2 1 | ENTRY_FILLED 8, EXPIRED 4 | 0 | 0 |
| b04 | OK | SL 6, TP2 1 | ENTRY_FILLED 7, EXPIRED 4 | 0 | 0 |
| b05 | OK | SL 22, TP2 3 | ENTRY_FILLED 25, EXPIRED 10, REJECT 1 | 0 | 0 |
| b06 | OK | SL 19, TP2 3 | ENTRY_FILLED 22, EXPIRED 9, REJECT 1 | 0 | 0 |
| b07 | OK | SETTLEMENT 1, SL 2, TP2 1 | ENTRY_FILLED 4, EXPIRED 1 | 1 | 0 |
| b08 | OK | SETTLEMENT 1, SL 2, TP2 1 | ENTRY_FILLED 4, EXPIRED 1 | 1 | 0 |
| b09 | OK | SL 17, TP2 1 | ENTRY_FILLED 18, EXPIRED 11 | 0 | 0 |
| b10 | OK | SL 18, TP2 1 | ENTRY_FILLED 19, EXPIRED 12 | 0 | 0 |
| b11 | OK | SL 7, TP2 1 | ENTRY_FILLED 8, EXPIRED 4 | 0 | 0 |
| b12 | OK | SL 6, TP2 1 | ENTRY_FILLED 7, EXPIRED 4 | 0 | 0 |
| b13 | OK | SL 23, TP2 2 | ENTRY_FILLED 25, EXPIRED 11, REJECT 1 | 0 | 0 |
| b14 | OK | SL 20, TP2 2 | ENTRY_FILLED 22, EXPIRED 10, REJECT 1 | 0 | 0 |
| b15 | OK | SL 7, TP2 2 | ENTRY_FILLED 9, EXPIRED 4, REJECT 1 | 0 | 0 |
| b16 | OK | SL 7, TP2 2 | ENTRY_FILLED 9, EXPIRED 3, REJECT 1 | 0 | 0 |
| c01 | OK | SETTLEMENT 1, SL 17, TP2 3 | ENTRY_FILLED 21, EXPIRED 11, REJECT 2 | 1 | 0 |
| c02 | OK | SETTLEMENT 1, SL 18, TP2 3 | ENTRY_FILLED 22, EXPIRED 7, REJECT 2 | 1 | 0 |
| c03 | OK | SETTLEMENT 1, SL 17, TP2 3 | ENTRY_FILLED 21, EXPIRED 11, REJECT 2 | 1 | 0 |
| c04 | OK | SETTLEMENT 1, SL 18, TP2 3 | ENTRY_FILLED 22, EXPIRED 7, REJECT 2 | 1 | 0 |
| c05 | OK | SETTLEMENT 1, SL 17, TP2 3 | ENTRY_FILLED 21, EXPIRED 10, REJECT 2 | 1 | 0 |
| c06 | OK | SETTLEMENT 1, SL 18, TP2 3 | ENTRY_FILLED 22, EXPIRED 6, REJECT 2 | 1 | 0 |
| c07 | OK | SETTLEMENT 1, SL 17, TP2 3 | ENTRY_FILLED 21, EXPIRED 10, REJECT 2 | 1 | 0 |
| c08 | OK | SETTLEMENT 1, SL 18, TP2 3 | ENTRY_FILLED 22, EXPIRED 6, REJECT 2 | 1 | 0 |
| c09 | OK | SETTLEMENT 1, SL 17, TP2 3 | ENTRY_FILLED 21, EXPIRED 11, REJECT 2 | 1 | 0 |
| c10 | OK | SETTLEMENT 1, SL 18, TP2 3 | ENTRY_FILLED 22, EXPIRED 7, REJECT 2 | 1 | 0 |
| c11 | OK | SETTLEMENT 1, SL 17, TP2 3 | ENTRY_FILLED 21, EXPIRED 11, REJECT 2 | 1 | 0 |
| c12 | OK | SETTLEMENT 1, SL 18, TP2 3 | ENTRY_FILLED 22, EXPIRED 7, REJECT 2 | 1 | 0 |
| c13 | OK | SETTLEMENT 1, SL 17, TP2 3 | ENTRY_FILLED 21, EXPIRED 10, REJECT 2 | 1 | 0 |
| c14 | OK | SETTLEMENT 1, SL 18, TP2 3 | ENTRY_FILLED 22, EXPIRED 6, REJECT 2 | 1 | 0 |
| c15 | OK | SETTLEMENT 1, SL 17, TP2 3 | ENTRY_FILLED 21, EXPIRED 10, REJECT 2 | 1 | 0 |
| c16 | OK | SETTLEMENT 1, SL 18, TP2 3 | ENTRY_FILLED 22, EXPIRED 6, REJECT 2 | 1 | 0 |

## SETTLEMENT trades (33), direction, bound side, timing
- Every SETTLEMENT trade is a SHORT and used the **upper** bound (`price_upper` 0.000887), the adverse side for a SHORT, as the rule says; none used the lower bound; 0 trades with another direction.
- Exit time equals T (`2025-01-22T09:00:00Z`) on all 33. The exit price equals the bound exactly on all 33 (by construction, stated rather than discovered). On the other 15 points and on every non-SETTLEMENT trade of the 33, **no exit price equals either bound**.
- Entry times of the SETTLEMENT trades: b07, b08: `2024-12-10T00:34:59.999Z` (2); a01-a08: `2025-01-19T19:06:59.999Z` (8); a09, a10, a11, a12, a14, a16: `2025-01-20T06:55:59.999Z` (6); a13, c01-c16: `2025-01-20T07:02:59.999Z` (17). These four groups, with these members and times, are identical to the table of `evidence/16-37-reef-diagnostic-cut.md` (the open SHORT at the cut at 2025-01-22T00:00Z). The open position seen there is therefore still open at 09:00 and is the one that is settled.
- No entry after 2025-01-22T08:30Z on any point (`entry_after_0830` none on 48 of 48). Thus the second stop condition of the old run (entry after 08:30) does not occur.
- Funding stops at T: the last REEFUSDT funding row in the case is `2025-01-22T08:00:00Z` on 48 of 48 points, and on every SETTLEMENT trade `funding_event_count` equals the number of REEF funding rows with entry <= row < exit (16 for a01-a08, 13 for a09-a14, a16, c01-c16, 260 for b07 and b08), so the 08:00 row is charged and nothing is charged at or after T. The engine itself refuses any funding row of a declared symbol at or after T; no point raised.
- `coverage_note` of a SETTLEMENT trade (identical text on all 33; no other note piece because the walk had no mark hole): `terminal_settlement SETTLEMENT side=SHORT bound=price_upper price=0.000887 interval=[0.000845, 0.000887] kind=BOUNDED_BY_INDEX_KLINES evaluation=UNION_ADVERSE_BOUND (settlement price unknown; the bound is an unverified assumption)`
- **No `mark_price_1m_missing` marker on any settlement note** (0 of 33): the gap between the last mark minute and T is not annotated as a data hole.

## What this establishes and what it does not
- Establishes, for REEFUSDT alone, S0, equity 600, risk_rate 0.005, the full Development window and the 48 registered points: on the landed code (semantics 2.1.0, protocol v2.4.0) with the REEF terminal declaration and the bounded `terminal_settlements` row built through the real manifest and evidence-check code, every point runs to completion and the `FundingCoverageError` of the old run is gone. The 33 points that failed are the 33 that have an open SHORT at T, and each of those ends in exactly one SETTLEMENT at T with funding stopping at T; the 15 others had no position or resting plan at T (a15 additionally had one signal blocked by the no-plan rule). No SETTLEMENT_CANCEL occurs in REEF alone.
- Also establishes that the `terminal_settlements` evidence check, the case-row builder, the case parser, the engine's data-after-T checks, the funding clip and the `settlement_count` summary key accept a real REEF dataset, not only the synthetic worlds of the landed tests.
- Does NOT establish: that the manifest is frozen (it is NOT: no manifest file exists, nothing was frozen, no hash registered), that REEFUSDT stays in or leaves the universe (REEFUSDT is NOT removed and the window is NOT shortened), any statement about the settlement price (the bound is the recorded unverified assumption, not a Binance fact; `official_confirmation` stays null), anything about a 12-symbol portfolio (it could open fewer or different REEF positions, a RESTING plan at T and hence a SETTLEMENT_CANCEL may appear there), Validation or Holdout (not read), or any performance. No PnL or ranking figure was produced, and none of these counts is evidence for or against any strategy.
- Not exercised by this run: the RESTING-at-T branch on real data (0 cases), the DAILY_STOP interplay at T (REEF alone has no other symbol), an entry between 08:00 and 08:30 that is still resting at T.

## State after this evidence
Manifest NOT frozen; REEFUSDT NOT removed; window NOT shortened; no ExperimentRecord written; `holdout_consumed.json` untouched; no O-03; 12-symbol portfolio NOT run; no code, gap, funding-coverage or semantics change; nothing pushed. The decision on freezing the research-run-1 manifest with the REEF row remains with the reviewer and the user.
