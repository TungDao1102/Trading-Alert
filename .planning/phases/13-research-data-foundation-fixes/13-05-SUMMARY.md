---
phase: 13-research-data-foundation-fixes
plan: 05
subsystem: data-archive
tags: [archive, data-binance-vision, checksum, zip, kline-source, fail-closed, s3-listing, delisted]

requires:
  - phase: 13-research-data-foundation-fixes
    provides: "KlineSource Protocol, closed-day paginator, atomic publisher, zero-trade/precision quality gate (13-02)"
provides:
  - "ArchiveKlineSource: a KlineSource that serves data.binance.vision klines through the same paginator, quality gate, closed-day rule and atomic publisher as REST data"
  - "fetch_archive_klines: sha256-verified, size-capped, in-memory zip reader whose rows map through the adapter's _row_to_kline"
  - "list_archive_symbols and archive_last_day: S3-listing discovery of archive-only (delisted) USDT symbols and their last daily 1d file"
  - "Archive exception family (ArchiveError, ArchiveNotFound, ArchiveChecksumMismatch, ArchiveChecksumMissing, ArchiveTooLarge, ArchiveFormatError) for the CLI to classify"
affects: [13-06, 13-07, research-backfill, sufficiency-report]

actuals:
  tokens: 11661
  tasks: 3
  commits: 6
plan_head_before: fc674f0a4a13f8242498759a9f08899cbaf6fbbc
plan_head_after: eaabe052b7ccd4acf2f0dcb63ffb78ef187a4397

tech-stack:
  added: []
  patterns:
    - "Archive rows reuse the adapter's 12-column _row_to_kline mapping (no second column mapping)"
    - "Streamed byte cap enforced on Content-Length and on decoded bytes actually received; body read only for a 200"
    - "Zip read fully in memory: exactly one member, exact expected name, ZipInfo.file_size cap, bounded read; never any bulk extract"
    - "Month-level row cache (max 3 months) with monthly-zip then daily-zip fallback; missing days are skipped forward, never interpolated"

key-files:
  created:
    - src/data/archive.py
    - tests/test_archive_ingest.py
  modified: []

key-decisions:
  - "Checksum 404 is disambiguated by probing the zip status only (no body read): zip 404 is ArchiveNotFound, zip 200 is ArchiveChecksumMissing"
  - "CSV header is skipped only when the first cell is exactly open_time; any other non-digit first cell is a format error (stricter than the plan's non-digit rule, fail closed)"
  - "Timestamps must be 13-digit integers in both open_time and close_time columns (ms only; seconds or microseconds are rejected)"
  - "list_archive_symbols supports quote USDT only (ValueError otherwise), matching the ^[A-Z0-9]+USDT$ pattern the rest of the project enforces"
  - "Listing bodies that declare a DOCTYPE or entities are rejected outright even though expat does not fetch external entities"
  - "Transport errors (httpx.HTTPError, including TLS verification failure) surface as ArchiveError, never retried by the paginator"

patterns-established:
  - "Fail-closed external file ingestion: verify integrity, cap size, validate names, then parse; every failure is a project exception subclass"

requirements-completed: [DATA-01]

coverage:
  - id: D1
    description: "A monthly archive zip becomes validated, closed-day Parquet through the same paginator and store as REST data (frames equal a REST fake's)"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_archive_ingest.py#test_archive_month_publishes_same_frames_as_rest"
        status: pass
      - kind: unit
        ref: "tests/test_archive_ingest.py#test_archive_source_pages_through_a_month"
        status: pass
    human_judgment: false
  - id: D2
    description: "Checksum mismatch, missing checksum, foreign checksum name, oversized zip or member, bad member names, non-ms timestamps and invalid inputs publish nothing and raise project exceptions"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_archive_ingest.py#test_checksum_mismatch_publishes_nothing"
        status: pass
      - kind: unit
        ref: "tests/test_archive_ingest.py#test_zip_member_path_traversal_is_rejected"
        status: pass
      - kind: unit
        ref: "tests/test_archive_ingest.py#test_oversized_body_without_content_length_is_rejected"
        status: pass
      - kind: unit
        ref: "tests/test_archive_ingest.py#test_invalid_inputs_raise_before_any_request"
        status: pass
      - kind: unit
        ref: "tests/test_archive_ingest.py#test_archive_module_never_extracts_to_disk"
        status: pass
    human_judgment: false
  - id: D3
    description: "Monthly-404 months fall back to daily zips; a missing day is skipped, never interpolated"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_archive_ingest.py#test_monthly_404_falls_back_to_daily_zips"
        status: pass
      - kind: unit
        ref: "tests/test_archive_ingest.py#test_missing_daily_day_is_skipped_never_interpolated"
        status: pass
    human_judgment: false
  - id: D4
    description: "Archive-only symbols are discovered from the S3 listing (regex-validated, bounded paging) and their last daily file is found"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "tests/test_archive_ingest.py#test_listing_pages_and_filters_symbols"
        status: pass
      - kind: unit
        ref: "tests/test_archive_ingest.py#test_archive_last_day_from_daily_listing"
        status: pass
      - kind: unit
        ref: "tests/test_archive_ingest.py#test_listing_pages_are_bounded"
        status: pass
    human_judgment: false
  - id: D5
    description: "Live behavior of the httpx client against data.binance.vision behind this sandbox's TLS-intercepting proxy"
    requirement: DATA-01
    verification: []
    human_judgment: true
    rationale: "The sandbox proxy presents a self-signed certificate; verify=True correctly refused it (fail closed) so no live httpx smoke run was possible. The URL layout, checksum format and listing XML were verified with curl instead; the first real run on the user's machine or VPS is the live confirmation."

duration: 11min
completed: 2026-09-30
status: complete
---

# Phase 13 Plan 05: Archive Kline Source Summary

**A checksum-verified, size-capped reader for data.binance.vision that plugs into the existing paginator as a `KlineSource` (monthly zips with daily fallback), plus bucket-listing discovery of archive-only USDT symbols and their last daily 1d file.**

## Performance

- **Duration:** about 11 min (14:08Z to 14:19Z)
- **Tasks:** 3 (1 tracer, 2 auto; all TDD, RED then GREEN each)
- **Files:** 2 created (`src/data/archive.py`, `tests/test_archive_ingest.py`), none modified

## Facts verified (2026-09-30, curl against the live archive)

- Monthly zip: `https://data.binance.vision/data/futures/um/monthly/klines/FTTUSDT/1h/FTTUSDT-1h-2022-10.zip` answers 200, `Content-Length: 31448`.
- Checksum: the same URL plus `.CHECKSUM` returns `<64 hex>  FTTUSDT-1h-2022-10.zip` (two spaces, trailing newline); `sha256sum` of the downloaded zip equals it exactly.
- CSV: one member, first row is the header `open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore`, then 13-digit millisecond timestamps.
- Listing host: `https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/monthly/klines/` returns S3 `ListBucketResult` XML in the `http://s3.amazonaws.com/doc/2006-03-01/` namespace with `CommonPrefixes/Prefix`, `IsTruncated` and `NextMarker` (the same query on `data.binance.vision` also answers 200).
- Daily listing: `.../daily/klines/SXPUSDT/1d/` returns `Contents/Key` entries in pairs (`.zip` and `.zip.CHECKSUM`), 1,000 keys per page, so a long history needs several marker pages; this is why `archive_last_day` pages instead of reading one page.
- A missing key (for example the 2030-01 month) answers 404 for both zip and checksum.

## Accomplishments

- `ArchiveKlineSource(client, *, search_end_ms).klines(symbol, interval, start_ms, end_ms, limit)` walks month by month from the month of `start_ms`, returns at most `limit` rows with `start_ms <= open < min(end_ms, search_end_ms)` from the first month that has any, and falls back to that month's daily zips when the monthly zip is absent. Months are cached (at most 3), so a zip is downloaded once per instance. It satisfies the `KlineSource` Protocol structurally.
- Tracer proven end to end: an in-test FTTUSDT October 2022 zip (744 hourly rows) published 31 day files whose Parquet frames equal those a REST fake with the same rows produces.
- Every archive failure is a project exception: checksum mismatch or missing checksum (never parsed unchecked), oversized download (Content-Length and decoded-byte cap) or member (ZipInfo cap and bounded read), not exactly one member with the exact expected name, non-13-digit timestamps, malformed rows, corrupt zips, non-200/redirect responses, and transport or TLS failures.
- Symbol, interval, period and stamp are validated before any request; redirects are off and TLS verification is on (`verify=True`).
- `list_archive_symbols` (marker paging, `^[A-Z0-9]+USDT$` filter, skipped names logged once, page and byte caps, non-advancing marker guard, DOCTYPE rejected) and `archive_last_day` (latest `SYM-1d-YYYY-MM-DD.zip`, ignoring `.CHECKSUM`, other symbols and impossible dates).

## Task Commits

1. **Task 1 (tracer): monthly archive to KlineSource to Parquet** - RED `3bd0132` (test), GREEN `0714c16` (feat)
2. **Task 2: fail-closed safety** - RED `92e3609` (test), GREEN `958d2c1` (feat)
3. **Task 3: symbol discovery and last available day** - RED `bb1ba9d` (test), GREEN `eaabe05` (feat)

Tracer gate: the tracer `<verify>` (pytest, mypy) was re-run end to end after Task 1 and passed, so expansion proceeded.

## Files Created/Modified

- `src/data/archive.py` - constants, exceptions, `make_archive_client`, `archive_zip_url`, `fetch_archive_klines`, `ArchiveKlineSource`, `list_archive_symbols`, `archive_last_day`.
- `tests/test_archive_ingest.py` - 45 respx-mocked tests (no network, zips built in-test).

## Decisions Made

See `key-decisions` above. The two places this implementation is stricter than the plan text: the CSV header must be exactly `open_time`, and both timestamp columns (open and close) must be 13 digits.

## Deviations from Plan

None - plan executed exactly as written.

**Total deviations:** 0. **Impact:** none.

## Issues Encountered

- A live httpx smoke run was not possible: the sandbox routes HTTPS through a proxy with a self-signed certificate and the client correctly failed closed with `ArchiveError` wrapping `CERTIFICATE_VERIFY_FAILED`. TLS verification was deliberately not disabled (13-RESEARCH V13). Facts above were verified with curl.
- Known cost, not a defect: a monthly-404 month tries each daily zip in the month (two cheap 404 requests per absent day, bounded by `search_end_ms`). Results are cached per instance; the CLI should start archive-only symbols near their listing date and cap them with `archive_last_day`.
- `archive_last_day` only sees daily files; a symbol whose recent history exists only as monthly zips returns None. The daily 1d listing was confirmed to contain full history for SXPUSDT.
- Pre-existing failures (decision-alignment RQ-01/RQ-04) are unchanged and remain deferred to plan 13-11.

## Known Stubs

None.

## Threat Flags

None. T-13-18 through T-13-22 are mitigated by the tests named in the coverage block; T-13-23 (checksum is transport integrity only) is documented in the module docstring and the full `check_batch` gate still applies via the paginator. No packages were installed (T-13-SC).

## User Setup Required

None.

## TDD Gate Compliance

Each task has a `test(13-05)` RED commit before its `feat(13-05)` GREEN commit (`3bd0132` then `0714c16`; `92e3609` then `958d2c1`; `bb1ba9d` then `eaabe05`). Task 1 RED failed with the module absent (per test, via a lazy import); Task 2 RED failed on 12 tests (missing caps and exceptions, missing member/timestamp checks) while the tests Task 1 already satisfied passed; Task 3 RED failed on all 10 new tests (missing functions and constants). No REFACTOR commits were needed.

## Next Phase Readiness

- The CLI plan can build an `ArchiveKlineSource(make_archive_client(), search_end_ms=...)`, try REST first, fall back to the archive per symbol, and cap archive-only symbols at `archive_last_day`. Candidate discovery is `exchangeInfo` PERPETUAL/USDT plus `list_archive_symbols`.
- Mark-price kline archive files are not covered by this plan (the plan scoped klines only).

## Self-Check: PASSED

- Files present: `src/data/archive.py`, `tests/test_archive_ingest.py`.
- Commits present: `3bd0132`, `0714c16`, `92e3609`, `958d2c1`, `bb1ba9d`, `eaabe05`.
- Acceptance: `_row_to_kline` imported and used once (no second mapping), `verify=True` at `make_archive_client`, `MAX_LISTING_PAGES` defined and used in the paging loop, `test_checksum_mismatch_publishes_nothing`, `test_zip_member_path_traversal_is_rejected`, `test_archive_module_never_extracts_to_disk`, `test_listing_pages_and_filters_symbols`, `test_archive_last_day_from_daily_listing` all pass.
- Plan verification: `pytest tests/test_archive_ingest.py tests/test_backfill_closed_day.py` passes; `mypy src/data/archive.py` prints "Success: no issues found in 1 source file"; `ruff check` on both changed files is clean.
