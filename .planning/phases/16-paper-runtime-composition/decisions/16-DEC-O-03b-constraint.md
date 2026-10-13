# 16-DEC-O-03b-constraint: constraint source for research-run-1 (plan 16-37, Task 2, constraint part only)

decided by: user
date: 2026-10-13
words:
chọn C

context (recorded for audit): the words are the user's, verbatim. Option C was advised by the reviewer after reading evidence/16-37-constraint-history.md and evidence/16-37-symbol-metadata.md. This record decides ONLY the constraint source. It does not freeze a manifest, does not authorize research execution, and does not decide the REEFUSDT known_gaps form (KG-1 to KG-4), the cross-family multiplicity blocker, the data snapshot comparison or the Holdout.

## What C means here
- A fixed constraint set is a DECLARED RESEARCH ASSUMPTION for the whole window [2024-10-03T00:00:00Z, 2026-10-03T00:00:00Z). It is not historical truth. Official in-window history of tick, step, min_qty and min_notional could not be established (see the constraint-history evidence).
- Baseline: for each of the 12 symbols the row with the earliest metadata_observed_at_utc in the local symbol_metadata table (rule is deterministic; the table key is (symbol, observed_at) so there are no ties). Values and the real timestamp are kept; the timestamp is not moved to the window start.
- File: docs/research/preregistration/research-run-1-constraints-baseline.json, sha256 4307eec74feeab04081b872866895f70568f1d289b8a249fc7de702e71e11d3f (12 rows; every row observed 2026-10-03T03:11:57.803909+00:00). The file parses with parse_constraint_row. .gitattributes marks it -text so the bytes, and the hash, do not change on checkout.
- All observations are after the window, so 100% of constraint selections for bars in the window are back-extrapolated (D-30). The runner flag `extrapolated` and `constraints_extrapolated_count` are kept as the runner produces them. No gate in src/analytics or src/research refuses a record because of the flag. The actual count must be reported with each result.
- Earliest-row selection does not prove the row equals the historical constraint.

## What is and is not known (to be repeated in the amendment)
- In the snapshot: the values and the timestamp above.
- Source the collector is designed to read: Binance exchangeInfo. The table has no provenance column.
- Not independently verified: the origin and historical validity of every value. BTCUSDT min_notional 50 may have been 100 before 2026-04-14 (secondary report only, not an official source).

## Sensitivity (to be planned, not run)
- Candidate stress scenario: BTCUSDT.min_notional = 100 (secondary source, unverified; it is a stress-test assumption, not a verified fact).
- Other tick, step, min_qty and min_notional values have no historical source and no invented replacement; their uncertainty is reported as unquantified.
- Each scenario needs its own constraint file, hash, manifest, grid and authorization pairing and provenance. Before any real run a plan must define: scenario manifest and hash, which families/grids apply, registration and authorization, and how Holdout single-use is protected. Holdout is never used to choose between scenarios; any Holdout-related sensitivity method needs its own decision first.

## Documents
- RESEARCH_PROTOCOL.md v2.2.0 FROZEN is not edited in place. A new decision/amendment must define the declared assumption, that back-extrapolation does not prove historical executability, that results hold only under the stated constraint assumption, the sensitivity requirement and the reporting of the extrapolated flag.
- docs/research/GEOMETRY_AUDIT.md lines 133 and 165 call back-extrapolation "not valid for strategy evaluation". The old conclusion stays; a reference to this decision must be added so the documents do not contradict each other.

## REEFUSDT diagnostic
Allowed only after the baseline file and hash are verified (done in this record), and only under the limits the reviewer and user set: Development only, no ExperimentRecord, no holdout_consumed.json change, no PnL/expectancy/trade-count ranking, not through run.py main, no parameter choice. It also waits for the user's go-ahead on the method. If a REEF position is open after the last funding instant: no forced close, no relaxed funding coverage, no loosened known_gaps; options go to the user.

## Still open before O-03
KG-1 to KG-4 (plan 16-54), cross-family multiplicity, protocol amendment, canonical dataset local/EC2 comparison, O-03b values for the window, splits and symbols.
