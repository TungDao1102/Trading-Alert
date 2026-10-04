---
status: complete
phase: 02-data-foundation
source: [02-01-SUMMARY.md, 02-02-SUMMARY.md, 02-03-SUMMARY.md, 02-04-SUMMARY.md, 02-05-SUMMARY.md]
started: 2026-10-04T00:00:00Z
updated: 2026-10-04T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. 02-01 D1 Python 3.13 toolchain and reviewed lockfile
expected: uv Python 3.13, lock with no pre-release or archived connectors
result: pass
verified: uv run python --version -> 3.13.15; uv.lock pins binance-sdk-derivatives-trading-usds-futures 17.4.0; no pre-release version markers and no binance-connector/binance-futures-connector entries in uv.lock/pyproject.toml

### 2. 02-01 D2 fapi.binance.com reachability
expected: Public weight-1 time call returns 200
result: pass
verified: unsigned GET https://fapi.binance.com/fapi/v1/time -> HTTP 200 (public endpoint only)

### 3. 02-01 D3 SDK shapes recorded in COVERAGE.md
expected: COVERAGE.md exists with 5 capabilities INTEGRATE
result: pass
verified: COVERAGE.md present with 5 INTEGRATE rows; adapter tests in test_tracer_slice/test_collector/test_metadata pass against SDK-shaped fixtures

### 4. 02-01 D4 Golden exchangeInfo fixture
expected: Live-5-only secrets-free fixture parses
result: pass
verified: tests/fixtures/exchange_info_sample.json exists; tests/test_wave0_sanity.py passes (run with 8 data-foundation test modules, all green)

### 5. 02-01 D5 Compose stack postgres:17-bookworm, env-only creds
expected: Compose validates; postgres 17 image; credentials from env
result: pass
verified: docker compose config -q exit 0; docker-compose.yml image postgres:17.11-bookworm@sha256; POSTGRES_PASSWORD uses required-env interpolation; named volumes present

### 6. 02-01 D6 Alembic baseline creates 4 tables
expected: 0001_baseline creates symbol_metadata, collector_watermarks, collector_gaps, coverage_windows
result: pass
verified: src/db/alembic/versions/0001_baseline.py present; alembic heads -> 0004_persistence_integrity (head, chain extended by later phases); tests/test_persistence_migration_pg.py 32 passed against live PG with TEST_DATABASE_URL. Original scripts/check_migration_parity.py no longer exists (superseded by later phases), noted only

### 7. 02-01 D7 Async ORM models mirror migration
expected: models mirror migration 1:1
result: pass
verified: src.db.models imports; Base.metadata.sorted_tables includes collector_gaps, collector_watermarks, coverage_windows, symbol_metadata; migration PG tests pass

### 8. 02-01 D8 Shared fixtures and smoke tests
expected: conftest and wave0 smoke tests pass
result: pass
verified: pytest tests/test_wave0_sanity.py green

### 9. 02-02 Adapter is the only SDK importer with Decimal/UTC dataclasses
expected: Adapter exposes frozen Kline/OiSnapshot/FundingTick/SymbolFilters
result: pass
verified: tests/test_tracer_slice.py passes (forming-candle exclusion, cross-page dedup, 429 retry); adapter-driven suites test_metadata/test_collector pass

### 10. 02-02 Quality-gated immutable Parquet publish
expected: Bad batches rejected, existing partition not overwritten
result: pass
verified: tests/test_quality_gates.py passes incl. test_publish_to_existing_partition_raises

### 11. 02-02 Coverage CLI prints per-symbol range
expected: python -m src.data.coverage works with --symbol/--all/--json, HCMC at print edge
result: pass
verified: CLI --help shows --symbol/--all/--json; tests/test_coverage.py passes incl. test_cli_displays_asia_ho_chi_minh_at_print_edge

### 12. 02-03 D1 Duplicate open_time vs timestamp regression distinguished
expected: Duplicate open_time vs timestamp regression distinguished
result: pass
source: automated
coverage_id: 02-03:D1
verified: re-ran tests/test_quality_gates.py and tests/test_backfill.py: all passed

### 13. 02-03 D2 Immutable store FileExistsError on existing partition
expected: Immutable store FileExistsError on existing partition
result: pass
source: automated
coverage_id: 02-03:D2
verified: re-ran tests/test_quality_gates.py and tests/test_backfill.py: all passed

### 14. 02-03 D3 CursorStore resumable
expected: CursorStore resumable
result: pass
source: automated
coverage_id: 02-03:D3
verified: re-ran tests/test_quality_gates.py and tests/test_backfill.py: all passed

### 15. 02-03 D4 Paginator date-buffer honors D-04
expected: Paginator date-buffer honors D-04
result: pass
source: automated
coverage_id: 02-03:D4
verified: re-ran tests/test_quality_gates.py and tests/test_backfill.py: all passed

### 16. 02-03 D5 Forming candle dropped before quality gate
expected: Forming candle dropped before quality gate
result: pass
source: automated
coverage_id: 02-03:D5
verified: re-ran tests/test_quality_gates.py and tests/test_backfill.py: all passed

### 17. 02-03 D6 backfill_universe live-5 x 1m/1h/4h bootstrap with cursor resume
expected: Runner exposes bounded bootstrap with defaults and resume
result: pass
verified: src/data/backfill.py defines LIVE_5 (BTC, ETH, BNB, SOL, XRP) and backfill_universe; tests/test_backfill.py passes

### 18. 02-04 D1 exchangeInfo fixture -> 1 row per live-5 symbol
expected: exchangeInfo fixture -> 1 row per live-5 symbol
result: pass
source: automated
coverage_id: 02-04:D1
verified: re-ran tests/test_metadata.py and tests/test_collector.py: all passed

### 19. 02-04 D2 Second refresh INSERTs new version, no UPDATE
expected: Second refresh INSERTs new version, no UPDATE
result: pass
source: automated
coverage_id: 02-04:D2
verified: re-ran tests/test_metadata.py and tests/test_collector.py: all passed

### 20. 02-04 D3 Filter strings parse to Decimal exactly
expected: Filter strings parse to Decimal exactly
result: pass
source: automated
coverage_id: 02-04:D3
verified: re-ran tests/test_metadata.py and tests/test_collector.py: all passed

### 21. 02-04 D4 Universe trim ignores non-live-5
expected: Universe trim ignores non-live-5
result: pass
source: automated
coverage_id: 02-04:D4
verified: re-ran tests/test_metadata.py and tests/test_collector.py: all passed

### 22. 02-04 D5 OI tick writes 1 snapshot per symbol + atomic watermarks
expected: OI tick writes 1 snapshot per symbol + atomic watermarks
result: pass
source: automated
coverage_id: 02-04:D5
verified: re-ran tests/test_metadata.py and tests/test_collector.py: all passed

### 23. 02-04 D6 Adapter exception writes gap row, no snapshot/watermark
expected: Adapter exception writes gap row, no snapshot/watermark
result: pass
source: automated
coverage_id: 02-04:D6
verified: re-ran tests/test_metadata.py and tests/test_collector.py: all passed

### 24. 02-04 D7 Skipped tick records expected vs observed, no interpolation
expected: Skipped tick records expected vs observed, no interpolation
result: pass
source: automated
coverage_id: 02-04:D7
verified: re-ran tests/test_metadata.py and tests/test_collector.py: all passed

### 25. 02-04 D8 Funding sweep separate namespace/partition
expected: Funding sweep separate namespace/partition
result: pass
source: automated
coverage_id: 02-04:D8
verified: re-ran tests/test_metadata.py and tests/test_collector.py: all passed

### 26. 02-04 D9 Opportunistic OI history tagged research-grade
expected: Opportunistic OI history tagged research-grade
result: pass
source: automated
coverage_id: 02-04:D9
verified: re-ran tests/test_metadata.py and tests/test_collector.py: all passed

### 27. 02-04 D10 Long-running OI loop + funding sweep + harvest against live Binance
expected: Collector runs continuously against live exchange
result: skipped
reason: Needs long wall-clock soak against live Binance; unit-level behaviours (D5-D9) verified instead

### 28. 02-05 D1 Coverage CLI range/violation/gap counts
expected: Coverage CLI range/violation/gap counts
result: pass
source: automated
coverage_id: 02-05:D1
verified: re-ran tests/test_coverage.py: all passed

### 29. 02-05 D2 DuckDB coverage views join Parquet and PG
expected: DuckDB coverage views join Parquet and PG
result: pass
source: automated
coverage_id: 02-05:D2
verified: re-ran tests/test_coverage.py: all passed

### 30. 02-05 D3 Range math MIN open / MAX close
expected: Range math MIN open / MAX close
result: pass
source: automated
coverage_id: 02-05:D3
verified: re-ran tests/test_coverage.py: all passed

### 31. 02-05 D4 Continuity gap_count
expected: Continuity gap_count
result: pass
source: automated
coverage_id: 02-05:D4
verified: re-ran tests/test_coverage.py: all passed

### 32. 02-05 D5 View load from checked-in SQL
expected: View load from checked-in SQL
result: pass
source: automated
coverage_id: 02-05:D5
verified: re-ran tests/test_coverage.py: all passed

### 33. 02-05 D6 Empty partition handling
expected: Empty partition handling
result: pass
source: automated
coverage_id: 02-05:D6
verified: re-ran tests/test_coverage.py: all passed

### 34. 02-05 D7 HCMC display edge only
expected: HCMC display edge only
result: pass
source: automated
coverage_id: 02-05:D7
verified: re-ran tests/test_coverage.py: all passed

### 35. 02-05 D8 JSON output mode
expected: JSON output mode
result: pass
source: automated
coverage_id: 02-05:D8
verified: re-ran tests/test_coverage.py: all passed

### 36. 02-05 D9 No float() in coverage module
expected: No float() in coverage module
result: pass
source: automated
coverage_id: 02-05:D9
verified: re-ran tests/test_coverage.py: all passed

### 37. 02-05 D10 Single-command backup bundle
expected: Single-command backup bundle
result: pass
source: automated
coverage_id: 02-05:D10
verified: re-ran tests/test_backup.py: all passed

### 38. 02-05 D11 Manifest sha256, sorted
expected: Manifest sha256, sorted
result: pass
source: automated
coverage_id: 02-05:D11
verified: re-ran tests/test_backup.py: all passed

### 39. 02-05 D12 Scratch-restore drill asserts equality
expected: Scratch-restore drill asserts equality
result: pass
source: automated
coverage_id: 02-05:D12
verified: re-ran tests/test_backup.py: all passed

### 40. 02-05 D13 Tampered backup exits non-zero
expected: Tampered backup exits non-zero
result: pass
source: automated
coverage_id: 02-05:D13
verified: re-ran tests/test_backup.py: all passed

### 41. 02-05 D14 Multiple Parquet roots
expected: Multiple Parquet roots
result: pass
source: automated
coverage_id: 02-05:D14
verified: re-ran tests/test_backup.py: all passed

### 42. 02-05 D16 No float() in backup module
expected: No float() in backup module
result: pass
source: automated
coverage_id: 02-05:D16
verified: re-ran tests/test_backup.py: all passed

### 43. 02-05 D17 Backup module secret-free
expected: Backup module secret-free
result: pass
source: automated
coverage_id: 02-05:D17
verified: re-ran tests/test_backup.py: all passed

### 44. 02-05 D18 Bundle root outside source roots
expected: Bundle root outside source roots
result: pass
source: automated
coverage_id: 02-05:D18
verified: re-ran tests/test_backup.py: all passed

### 45. 02-05 D19 Bundle root auto-created
expected: Bundle root auto-created
result: pass
source: automated
coverage_id: 02-05:D19
verified: re-ran tests/test_backup.py: all passed

### 46. 02-05 D15 PowerShell backup-drill wrapper defers to Python
expected: Wrapper exists, no SQL/dump/copy logic
result: pass
verified: scripts/backup-drill.ps1 header states it only forwards args to python -m src.ops.backup; test_backup_drill_powershell_wrapper_exists passes. Real pg_dump end-to-end drill not run (pg_dump not on host PATH); covered by fake-pg_dump drill tests

## Summary

total: 46
passed: 45
issues: 0
pending: 0
skipped: 1
blocked: 0

## Gaps

[]
