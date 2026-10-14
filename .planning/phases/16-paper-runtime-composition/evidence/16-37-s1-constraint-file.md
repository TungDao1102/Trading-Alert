# 16-37: S1 constraint file (stress scenario of protocol v2.3.0, D068)

date: 2026-10-14. Created by the orchestrator at the user's request ("làm việc 1 và 3"); the scenario itself was decided by the reviewer and adopted by the user (`decisions/16-DEC-V230.md`, item 3).

## File
- `docs/research/preregistration/research-run-1-constraints-S1.json`
- sha256 `fd86906a686ac7937921d30947f2b2561e5989d2f41b1b32108439e745cd9c63`, 2,857 bytes (S0: 2,856 bytes).
- Built from S0 (`research-run-1-constraints-baseline.json`, sha256 `4307eec74feeab04081b872866895f70568f1d289b8a249fc7de702e71e11d3f`, verified before the copy) by a byte-level replacement inside the BTCUSDT object only: `"min_notional": "50"` to `"min_notional": "100"`. A field-by-field comparison of the two parsed files shows exactly one difference: `BTCUSDT.min_notional`, `50` to `100`. All 12 rows and the real `metadata_observed_at_utc` values are unchanged.
- `.gitattributes` marks it `-text` like S0, so the bytes and the hash do not change on checkout. Every row parses with `parse_constraint_row` (12 rows; BTCUSDT `min_notional` parses as 100).

## What it is and is not
- A stress-test assumption for a descriptive sensitivity run on Development and Validation. The value 100 rests on one secondary report (Longbridge/CoinLive, 2026-04-09: BTCUSDT minimum notional 100 to 50, effective 2026-04-14), not on an official Binance page; see `evidence/16-37-constraint-history.md`. It is not verified history.
- Not a candidate selector: S1 results never choose a candidate, parameter, family or scenario, never enter the Holm correction (D069), and never use the Holdout.
- The file is not referenced by any manifest yet. A manifest that names it, its grid and its authorization are separate steps (16-37 Task 3 and 16-46), after the REEFUSDT decision.
- The file keeps a REEFUSDT row. The runner keeps only rows of manifest symbols, so the row is harmless whether or not REEFUSDT stays in the universe.
