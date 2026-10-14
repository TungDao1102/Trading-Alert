---
phase: quick-261014-nnl
plan: 01
subsystem: research / terminal-settlement evidence
tags: [reefusdt, s-b-interval, evidence, recompute, decimal]
requires: []
provides:
  - committed REEFUSDT settlement evidence (A trade klines, B index klines, F sample-day index klines) with request records
  - src/research/settlement_evidence.py (pure recompute of the bounded settlement interval)
affects: [quick-261014-nnl plans 02-06]
key-files:
  created:
    - src/research/settlement_evidence.py
    - tests/test_research_settlement_evidence.py
    - docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/ (9 files)
  modified:
    - .gitattributes
decisions:
  - "Evidence re-fetched with unauthenticated GETs; request URL, HTTP Date header and fetch time recorded as issued"
  - "The module returns interval ends only; it never chooses a settlement price (16-DEC-S-B-interval item 1)"
status: complete
commits: 3
plan_head_before: d186b9e5193411cd5c27883a48182bf4eaa6b025
plan_head_after: 17fca97b2529138cbb14ac164f62518ab0285570
actuals:
  tokens: 10900   # chars/4 over the diff d186b9e..HEAD
  tasks: 3
  commits: 3
metrics:
  completed: 2026-10-14
---

# Phase quick-261014-nnl Plan 01: Evidence and pure settlement recompute Summary

REEFUSDT settlement evidence is committed byte for byte (all three bodies hash-equal the lost scratch files) and a pure Fraction/Decimal module recomputes the bounded interval 0.000845 / 0.000887 from those bytes.

## Task results

| Task | Name | Commit | Result |
|------|------|--------|--------|
| 1 | User authorization (option authorize-refetch) | d186b9e (before this run, not edited) | grep checks pass: `option: authorize-refetch`, request_url A/B count 2 |
| 2 | Evidence folder, request records, `.gitattributes` | c5d1ba6 | A, B, F bodies hash-equal the known sha256 |
| 3 | Tests first (RED), then module (GREEN) | f3d3f3f (RED), 17fca97 (GREEN) | 52 passed, no skip; mypy, ruff, ruff format, float guard clean |

## Re-fetch and hash comparison

Public unauthenticated GET to `https://fapi.binance.com`, no key, no `.env`. Endpoints checked against the Binance USDS-M futures docs (Context7 copy of developers.binance.com): `GET /fapi/v1/klines` (symbol, interval, startTime, endTime, limit) and `GET /fapi/v1/indexPriceKlines` (pair, interval, startTime, endTime, limit). The developers.binance.com page itself is a JavaScript page that curl cannot read, so the parameter list comes from the Context7 copy of those docs (it shows both a 1000 and a 1500 maximum limit in different pages; no request here depends on the maximum).

| Body | Committed request URL | Date header | Known sha256 | Obtained | Match |
|------|----------------------|-------------|--------------|----------|-------|
| B index klines | `/fapi/v1/indexPriceKlines?pair=REEFUSDT&interval=1m&startTime=1737534600000&limit=30` | Wed, 14 Oct 2026 11:50:06 GMT | 56afae6c...4769b8 | same | yes, shape 1 |
| A trade klines | `/fapi/v1/klines?symbol=REEFUSDT&interval=1m&startTime=1737536400000&limit=4` | Wed, 14 Oct 2026 11:50:48 GMT | 2a822953...fa1 | same | yes, shape 2 |
| F sample-day index klines | `/fapi/v1/indexPriceKlines?pair=REEFUSDT&interval=1m&startTime=1735720200000&limit=30` | Wed, 14 Oct 2026 11:50:48 GMT | c3e7ef5b...9f176 | same | yes, shape 2 |

Requests issued (all single GETs, no network error, no retry needed): B shape 1 (match). For A and F shape 1 was a wide window used to find the original row range: F `startTime=1735689600000&endTime=1735775999999&limit=1500` (whole day, 1440 rows, sha256 9bfa6bea...162d, no match, as expected for a wide window) and A `startTime=1737536400000&limit=1500` (1500 rows, sha256 15722169...47aa, no match). Both wide responses were searched offline for a contiguous row range whose compact-JSON bytes hash to the known value; the only hits were A rows 0-3 (09:00 to 09:03, 4 rows) and F rows 510-539 (08:30 to 08:59, 30 rows), which became shape 2 and matched on the first try. Two request shapes per body at most; the wide responses were not committed.

The 09:00 trade candle: open = close = 0.000880, high 0.000887, low 0.000845, 102 trades; the three following candles are flat at 0.000880 with zero trades.

## Recomputed values (from the committed bytes)

- nominal bounds 5123/6000000 and 347/400000
- tick-widened index bounds 0.000852 and 0.000869
- trade candle at 09:00Z low 0.000845, high 0.000887
- union bounds 0.000845 and 0.000887
- all 120 index OHLC values of 2025-01-22 08:30..08:59 are multiples of 0.000001

## Files

- `docs/research/preregistration/evidence/terminal-settlement/REEFUSDT/`: `A_klines_after_settlement`, `B_indexPriceKlines_before_settlement`, `F_indexklines_sample_day`, each as `.body.json`, `.headers.txt` (CRLF, as received) and `.request.json` (schema fetch-record/1, sorted keys, LF, strings only). D and E are not present (dropped by the user).
- `.gitattributes`: line `docs/research/preregistration/evidence/** -text` added before copying; `git check-attr` reports `text: unset`, `git ls-files --eol` shows the bodies as `i/none` and the headers as `i/crlf`, unchanged by checkout.
- `src/research/settlement_evidence.py`: `SettlementEvidenceError`, `KlineRow`, `RecomputedBounds`, `parse_klines`, `nominal_index_bounds`, `tick_widened_bounds`, `trade_candle_bounds`, `union_bounds`, `recompute_settlement_bounds`, `fraction_text`, `parse_fraction_text`, `sha256_bytes`.
- `tests/test_research_settlement_evidence.py`: design test 9 plus fail-closed cases (RED commit failed with ModuleNotFoundError).

## Verification

- `pytest tests/test_research_settlement_evidence.py tests/test_domain_no_float.py -q`: 52 passed, none skipped
- `mypy src`: no issues in 185 files; `ruff check` and `ruff format --check`: clean; `uv lock --check`: green
- `git diff d186b9e HEAD -- src/backtest src/paper params`: empty; no file deleted by any commit
- LF check: `git show HEAD:` of the module, the test file and `.gitattributes` contain no CR

## Deviations from Plan

1. [Documentation] The plan's Task 2 commit also lists the three S-B-interval decision files. They were already committed (71da0fe, d186b9e) and unchanged, so the evidence commit contains only the evidence folder and `.gitattributes`; the commit message says so.
2. [Judgement] `request_url_source` is `re-fetch 2026-10-14` and `http_date_header` stores the whole `Date: ...` line verbatim, as the plan asks ("the Date line verbatim"). `scratch_name` holds the original scratch body file name.
3. [Test naming] The behavior list names `test_recompute_refuses_a_json_float_or_a_non_string_price` etc.; one extra test replaced a misleading name: the tampered-row case is `test_a_tampered_row_changes_the_hash_and_the_recomputed_bound` because a tampered row yields different bounds and a different sha256 rather than an error inside the pure function (the comparison against the manifest is plan 02's runner check).
4. The branch is `develop`, which the generic executor protected-branch assertion lists; committing there was directed by the caller and the plan, and the work was done on the main tree with no worktree.

No auto-fix rules triggered. No stubs. No threat flags beyond the plan's threat model (the fapi origin is stated outside the KG4 host rule in each request record).

## Not done (by scope)

Plans 02-10, any manifest field, runner check, engine change, version bump, protocol text, `holdout_consumed.json`, ROADMAP and STATE updates.

## Self-Check: PASSED
