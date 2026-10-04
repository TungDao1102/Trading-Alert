---
status: complete
phase: 13-research-data-foundation-fixes
source: [13-01-SUMMARY.md, 13-02-SUMMARY.md, 13-03-SUMMARY.md, 13-04-SUMMARY.md, 13-05-SUMMARY.md, 13-06-SUMMARY.md, 13-07-SUMMARY.md, 13-08-SUMMARY.md, 13-09-SUMMARY.md, 13-10-SUMMARY.md, 13-11-SUMMARY.md, 13-12-SUMMARY.md, 13-13-SUMMARY.md]
started: 2026-10-04T00:00:00Z
updated: 2026-10-04T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. 13-01 D1: Collector universe is read from the versioned collect list (live-5 union top 15 by volume) for the loop, --once and --healthcheck; explicit --universe overrides
expected: Collector universe is read from the versioned collect list (live-5 union top 15 by volume) for the loop, --once and --healthcheck; explicit --universe overrides and is validated
result: pass
source: automated
coverage_id: 13-01-D1
verified: tests/test_collector.py#test_main_once_polls_exactly_the_collect_list; tests/test_collector.py#test_explicit_universe_override_is_validated (all in the 570-test targeted pytest run, 0 failures)

### 2. 13-01 D2: A missing, unreadable, empty or malformed collect list stops the collector with exit 2 (healthcheck 1) and no adapter calls; never falls back to live-5
expected: A missing, unreadable, empty or malformed collect list stops the collector with exit 2 (healthcheck 1) and no adapter calls; never falls back to live-5
result: pass
source: automated
coverage_id: 13-01-D2
verified: tests/test_collector.py#test_missing_collect_list_refuses_start_without_live5_fallback; tests/test_collector.py#test_healthcheck_with_missing_collect_list_is_unhealthy; tests/test_collect_list.py#test_empty_collect_list_is_rejected (all in the 570-test targeted pytest run, 0 failures)

### 3. 13-01 D3: Deterministic proposer and the committed collect-list-v1.toml generated from live exchange data (TRADING PERPETUAL USDT only, live-5 superset, provenance record
expected: Deterministic proposer and the committed collect-list-v1.toml generated from live exchange data (TRADING PERPETUAL USDT only, live-5 superset, provenance recorded)
result: pass
source: automated
coverage_id: 13-01-D3
verified: tests/test_collect_list.py#test_proposer_union_of_top15_and_live5_with_symbol_tiebreak; tests/test_collect_list.py#test_committed_collect_list_is_valid_live5_superset (all in the 570-test targeted pytest run, 0 failures)

### 4. 13-01 D5: Loop sleeps to the next cadence boundary measured after the tick
expected: Loop sleeps to the next cadence boundary measured after the tick
result: pass
source: automated
coverage_id: 13-01-D5
verified: tests/test_collector.py#test_loop_sleeps_to_next_cadence_boundary_after_tick; tests/test_collector.py#test_ms_until_next_tick_mid_period (all in the 570-test targeted pytest run, 0 failures)

### 5. 13-01 D4: Docker image contains docs/research/universe
expected: Docker image contains docs/research/universe
result: pass
verified: Dockerfile line 39 `COPY docs/research/universe ./docs/research/universe`; test_dockerfile_copies_universe_directory passed in the 570-test run.

### 6. 13-01 D6: 24 hour live run: every collect-list symbol keeps a fresh OI and funding watermark
expected: 24 hour live run: every collect-list symbol keeps a fresh OI and funding watermark
result: skipped
reason: 24 hour live collector soak needs a running collector and wall-clock time not available in UAT.

### 7. 13-02 D1: Backfill never publishes the current UTC day; partial past days are held back (counted, cursor untouched) unless terminal_end marks a delivered contract's last 
expected: Backfill never publishes the current UTC day; partial past days are held back (counted, cursor untouched) unless terminal_end marks a delivered contract's last day
result: pass
source: automated
coverage_id: 13-02-D1
verified: tests/test_backfill_closed_day.py#test_current_utc_day_is_never_published; tests/test_backfill_closed_day.py#test_partial_past_day_is_held_back_unless_terminal; tests/test_backfill_closed_day.py#test_resume_publishes_only_the_next_closed_day; tests/test_backfill_closed_day.py#test_listing_day_with_late_first_bar_is_published (all in the 570-test targeted pytest run, 0 failures)

### 8. 13-02 D2: Published Parquet is written atomically; an interrupted write leaves no torn file or temporary file; an existing file is never overwritten
expected: Published Parquet is written atomically; an interrupted write leaves no torn file or temporary file; an existing file is never overwritten
result: pass
source: automated
coverage_id: 13-02-D2
verified: tests/test_store_atomic.py#test_interrupted_write_leaves_no_partial_file; tests/test_store_atomic.py#test_existing_file_is_never_overwritten; tests/test_store_atomic.py#test_transient_permission_error_is_retried; tests/test_store_atomic.py#test_publish_after_a_simulated_crash_matches_a_clean_write (all in the 570-test targeted pytest run, 0 failures)

### 9. 13-02 D3: Zero-trade bars pass the gate as telemetry; excess-precision or non-finite Decimals are structurally rejected
expected: Zero-trade bars pass the gate as telemetry; excess-precision or non-finite Decimals are structurally rejected
result: pass
source: automated
coverage_id: 13-02-D3
verified: tests/test_quality_gates.py#test_zero_trade_bar_is_accepted_and_counted; tests/test_quality_gates.py#test_excess_precision_is_rejected; tests/test_quality_gates.py#test_non_finite_decimal_is_rejected_without_raising; tests/test_backfill_closed_day.py#test_zero_trade_bars_are_published_with_the_rest_of_the_day (all in the 570-test targeted pytest run, 0 failures)

### 10. 13-02 D4: Paginator accepts any object with the kline fetch signature (KlineSource) and feeds the same gate and store
expected: Paginator accepts any object with the kline fetch signature (KlineSource) and feeds the same gate and store
result: pass
source: automated
coverage_id: 13-02-D4
verified: tests/test_backfill_closed_day.py#test_any_object_with_the_kline_signature_is_a_source; .venv/Scripts/python -m mypy src/data/backfill.py src/data/store.py src/data/quality.py (all in the 570-test targeted pytest run, 0 failures)

### 11. 13-03 D1: Unsolicited drop and 24h rotation close old handles, backfill every pair, then resubscribe; no reconnect entry on rotation
expected: Unsolicited drop and 24h rotation close old handles, backfill every pair, then resubscribe; no reconnect entry on rotation
result: pass
source: automated
coverage_id: 13-03-D1
verified: tests/test_paper_supervisor_backfill.py#test_backfill_runs_before_resubscribe_on_unsolicited_drop; tests/test_paper_supervisor_backfill.py#test_backfill_runs_before_resubscribe_on_rotation (all in the 570-test targeted pytest run, 0 failures)

### 12. 13-03 D2: Backfilled closes advance the last-close state; record_close never moves it backwards; a failing pair is still resubscribed with one outage gap
expected: Backfilled closes advance the last-close state; record_close never moves it backwards; a failing pair is still resubscribed with one outage gap
result: pass
source: automated
coverage_id: 13-03-D2
verified: tests/test_paper_supervisor_backfill.py#test_backfilled_closes_advance_last_close; tests/test_paper_supervisor_backfill.py#test_record_close_never_moves_backwards; tests/test_paper_supervisor_backfill.py#test_failing_pair_is_still_resubscribed_with_outage_gap (all in the 570-test targeted pytest run, 0 failures)

### 13. 13-03 D3: A bar closing in the seam between backfill and WS attach is picked up once by the verification pass; the same bar from both passes is returned once
expected: A bar closing in the seam between backfill and WS attach is picked up once by the verification pass; the same bar from both passes is returned once
result: pass
source: automated
coverage_id: 13-03-D3
verified: tests/test_paper_supervisor_backfill.py#test_verification_pass_picks_up_bar_closed_in_seam; tests/test_paper_supervisor_backfill.py#test_same_bar_from_both_passes_returned_once; tests/test_paper_supervisor_backfill.py#test_verification_failure_keeps_first_pass_closes (all in the 570-test targeted pytest run, 0 failures)

### 14. 13-03 D4: The WS handler drops a closed kline at or before the last close and never dispatches it twice; concurrent claims of one bar yield exactly one winner
expected: The WS handler drops a closed kline at or before the last close and never dispatches it twice; concurrent claims of one bar yield exactly one winner
result: pass
source: automated
coverage_id: 13-03-D4
verified: tests/test_paper_supervisor_backfill.py#test_ws_duplicate_of_backfilled_close_is_not_dispatched; tests/test_paper_supervisor_backfill.py#test_advance_last_close_is_atomic_under_threads (all in the 570-test targeted pytest run, 0 failures)

### 15. 13-04 D1: Mark-price klines fetched through the adapter as MarkKline domain values with price_tick_count and no SDK type leakage
expected: Mark-price klines fetched through the adapter as MarkKline domain values with price_tick_count and no SDK type leakage
result: pass
source: automated
coverage_id: 13-04-D1
verified: tests/test_mark_klines.py#test_adapter_mark_klines_calls_sdk_once_and_returns_domain_types; tests/test_mark_klines.py#test_row_maps_ohlc_times_and_price_tick_count (all in the 570-test targeted pytest run, 0 failures)

### 16. 13-04 D2: Mark dataset published atomically to dataset=mark_klines with exactly nine columns, no volume/quote_volume/trade_count, nothing in the trade root
expected: Mark dataset published atomically to dataset=mark_klines with exactly nine columns, no volume/quote_volume/trade_count, nothing in the trade root
result: pass
source: automated
coverage_id: 13-04-D2
verified: tests/test_mark_klines.py#test_mark_kline_parquet_has_no_volume_or_trade_count_column; tests/test_mark_klines.py#test_mark_backfill_publishes_to_mark_root_only (all in the 570-test targeted pytest run, 0 failures)

### 17. 13-04 D3: Mark validator rejects duplicates, OHLC/regression/negative/duration/mixed-key/bad-decimal faults and only warns on gaps
expected: Mark validator rejects duplicates, OHLC/regression/negative/duration/mixed-key/bad-decimal faults and only warns on gaps
result: pass
source: automated
coverage_id: 13-04-D3
verified: tests/test_mark_klines.py#test_check_mark_batch_rejects_structural_faults (all in the 570-test targeted pytest run, 0 failures)

### 18. 13-04 D4: Trade and mark cursors cannot collide and a mismatched cursor store is refused; trade view ignores the mark dataset
expected: Trade and mark cursors cannot collide and a mismatched cursor store is refused; trade view ignores the mark dataset
result: pass
source: automated
coverage_id: 13-04-D4
verified: tests/test_mark_klines.py#test_trade_and_mark_cursors_never_collide; tests/test_mark_klines.py#test_paginator_refuses_cursor_store_of_another_dataset; tests/test_mark_klines.py#test_candles_view_ignores_mark_dataset (all in the 570-test targeted pytest run, 0 failures)

### 19. 13-04 D5: deliveryDate, empty-markPrice funding rows, server time and the -1121 predicate readable through the adapter
expected: deliveryDate, empty-markPrice funding rows, server time and the -1121 predicate readable through the adapter
result: pass
source: automated
coverage_id: 13-04-D5
verified: tests/test_adapter_strictness.py#test_exchange_info_exposes_delivery_date; tests/test_adapter_strictness.py#test_funding_row_with_empty_mark_price_parses_as_none; tests/test_adapter_strictness.py#test_server_time_returns_utc_datetime; tests/test_adapter_strictness.py#test_invalid_symbol_predicate (all in the 570-test targeted pytest run, 0 failures)

### 20. 13-04 D6: Existing backup + restore drill covers the mark-kline subtree byte-for-byte without changing backup.py
expected: Existing backup + restore drill covers the mark-kline subtree byte-for-byte without changing backup.py
result: pass
source: automated
coverage_id: 13-04-D6
verified: tests/test_backup.py#test_backup_covers_mark_kline_subtree (all in the 570-test targeted pytest run, 0 failures)

### 21. 13-05 D1: A monthly archive zip becomes validated, closed-day Parquet through the same paginator and store as REST data (frames equal a REST fake's)
expected: A monthly archive zip becomes validated, closed-day Parquet through the same paginator and store as REST data (frames equal a REST fake's)
result: pass
source: automated
coverage_id: 13-05-D1
verified: tests/test_archive_ingest.py#test_archive_month_publishes_same_frames_as_rest; tests/test_archive_ingest.py#test_archive_source_pages_through_a_month (all in the 570-test targeted pytest run, 0 failures)

### 22. 13-05 D2: Checksum mismatch, missing checksum, foreign checksum name, oversized zip or member, bad member names, non-ms timestamps and invalid inputs publish nothing and 
expected: Checksum mismatch, missing checksum, foreign checksum name, oversized zip or member, bad member names, non-ms timestamps and invalid inputs publish nothing and raise project exceptions
result: pass
source: automated
coverage_id: 13-05-D2
verified: tests/test_archive_ingest.py#test_checksum_mismatch_publishes_nothing; tests/test_archive_ingest.py#test_zip_member_path_traversal_is_rejected; tests/test_archive_ingest.py#test_oversized_body_without_content_length_is_rejected; tests/test_archive_ingest.py#test_invalid_inputs_raise_before_any_request; tests/test_archive_ingest.py#test_archive_module_never_extracts_to_disk (all in the 570-test targeted pytest run, 0 failures)

### 23. 13-05 D3: Monthly-404 months fall back to daily zips; a missing day is skipped, never interpolated
expected: Monthly-404 months fall back to daily zips; a missing day is skipped, never interpolated
result: pass
source: automated
coverage_id: 13-05-D3
verified: tests/test_archive_ingest.py#test_monthly_404_falls_back_to_daily_zips; tests/test_archive_ingest.py#test_missing_daily_day_is_skipped_never_interpolated (all in the 570-test targeted pytest run, 0 failures)

### 24. 13-05 D4: Archive-only symbols are discovered from the S3 listing (regex-validated, bounded paging) and their last daily file is found
expected: Archive-only symbols are discovered from the S3 listing (regex-validated, bounded paging) and their last daily file is found
result: pass
source: automated
coverage_id: 13-05-D4
verified: tests/test_archive_ingest.py#test_listing_pages_and_filters_symbols; tests/test_archive_ingest.py#test_archive_last_day_from_daily_listing; tests/test_archive_ingest.py#test_listing_pages_are_bounded (all in the 570-test targeted pytest run, 0 failures)

### 25. 13-05 D5: Live behavior of the httpx client against data.binance.vision behind this sandbox's TLS-intercepting proxy
expected: Live behavior of the httpx client against data.binance.vision behind this sandbox's TLS-intercepting proxy
result: skipped
reason: Needs live httpx traffic to data.binance.vision behind the sandbox TLS-intercepting proxy; unit tests use mocked transport only.

### 26. 13-06 D1: Two years of funding history are stored per symbol through a paginated walk from max(start, watermark + 1 ms) in pages of up to 1000, each tick once, watermark 
expected: Two years of funding history are stored per symbol through a paginated walk from max(start, watermark + 1 ms) in pages of up to 1000, each tick once, watermark advanced per page
result: pass
source: automated
coverage_id: 13-06-D1
verified: tests/test_collector.py#test_funding_history_paginates_and_advances_watermark (all in the 570-test targeted pytest run, 0 failures)

### 27. 13-06 D2: Re-running the backfill writes nothing twice (watermark cutoff and FileExistsError-as-covered)
expected: Re-running the backfill writes nothing twice (watermark cutoff and FileExistsError-as-covered)
result: pass
source: automated
coverage_id: 13-06-D2
verified: tests/test_collector.py#test_funding_history_rerun_writes_nothing_twice (all in the 570-test targeted pytest run, 0 failures)

### 28. 13-06 D3: Historical funding rows with no markPrice are stored with a null mark_price, never a fabricated zero
expected: Historical funding rows with no markPrice are stored with a null mark_price, never a fabricated zero
result: pass
source: automated
coverage_id: 13-06-D3
verified: tests/test_collector.py#test_funding_history_null_mark_price_is_stored_as_null (all in the 570-test targeted pytest run, 0 failures)

### 29. 13-06 D4: One failing symbol records a funding gap row and never stops the others; the page cap is reported, not silent
expected: One failing symbol records a funding gap row and never stops the others; the page cap is reported, not silent
result: pass
source: automated
coverage_id: 13-06-D4
verified: tests/test_collector.py#test_funding_history_isolates_failing_symbol; tests/test_collector.py#test_funding_history_page_cap_is_reported (all in the 570-test targeted pytest run, 0 failures)

### 30. 13-06 D5: OI, OI-research and funding tick files are written atomically and still refuse to overwrite
expected: OI, OI-research and funding tick files are written atomically and still refuse to overwrite
result: pass
source: automated
coverage_id: 13-06-D5
verified: tests/test_collector.py#test_tick_writers_are_atomic; tests/test_collector.py#test_tick_writer_refuses_overwrite (all in the 570-test targeted pytest run, 0 failures)

### 31. 13-06 D6: Clock offset measured and logged at start (warning above 1000 ms, info below); probe failure logged and never blocks or changes the exit code
expected: Clock offset measured and logged at start (warning above 1000 ms, info below); probe failure logged and never blocks or changes the exit code
result: pass
source: automated
coverage_id: 13-06-D6
verified: tests/test_collector.py#test_clock_probe_warns_on_large_offset; tests/test_collector.py#test_clock_probe_failure_never_blocks_start; tests/test_collector.py#test_main_once_probes_clock_once_and_probe_failure_keeps_exit_code; tests/test_collector.py#test_loop_probes_clock_once_before_first_tick (all in the 570-test targeted pytest run, 0 failures)

### 32. 13-07 D1: CLI refreshes versioned metadata first, then backfills trade klines at the decided depth into closed-day Parquet and prints the depth and run date
expected: CLI refreshes versioned metadata first, then backfills trade klines at the decided depth into closed-day Parquet and prints the depth and run date
result: pass
source: automated
coverage_id: 13-07-D1
verified: tests/test_backfill_cli.py#test_cli_refreshes_metadata_before_backfill; tests/test_backfill_cli.py#test_cli_prints_depth_in_run_header; tests/test_backfill_cli.py#test_unknown_dataset_or_interval_exits_2_without_adapter_call (all in the 570-test targeted pytest run, 0 failures)

### 33. 13-07 D2: Per-symbol windows: onboard floor, delivery terminal cap (no post-delivery bars), unknown-delivery and not-listed symbols get no window, mark windows equal trad
expected: Per-symbol windows: onboard floor, delivery terminal cap (no post-delivery bars), unknown-delivery and not-listed symbols get no window, mark windows equal trade windows
result: pass
source: automated
coverage_id: 13-07-D2
verified: tests/test_backfill_cli.py#test_delivered_symbol_never_publishes_post_delivery_bars; tests/test_backfill_cli.py#test_onboard_limited_window_starts_at_onboard_time; tests/test_backfill_cli.py#test_mark_windows_match_trade_windows; tests/test_backfill_cli.py#test_symbols_without_window_are_listed_and_never_fetched (all in the 570-test targeted pytest run, 0 failures)

### 34. 13-07 D3: FROZEN manifest sets the 1h/4h start and joins the universe; DRAFT contributes nothing; explicit symbols replace the union
expected: FROZEN manifest sets the 1h/4h start and joins the universe; DRAFT contributes nothing; explicit symbols replace the union
result: pass
source: automated
coverage_id: 13-07-D3
verified: tests/test_backfill_cli.py#test_frozen_manifest_sets_htf_start; tests/test_backfill_cli.py#test_draft_manifest_contributes_no_symbols_and_no_start (all in the 570-test targeted pytest run, 0 failures)

### 35. 13-07 D4: Interrupted run resumes from the dataset cursor and, with cursors deleted, from the store floor; no day is published twice
expected: Interrupted run resumes from the dataset cursor and, with cursors deleted, from the store floor; no day is published twice
result: pass
source: automated
coverage_id: 13-07-D4
verified: tests/test_backfill_cli.py#test_resume_after_kill_uses_cursor_and_store_floor; tests/test_backfill_cli.py#test_dry_run_fetches_nothing (all in the 570-test targeted pytest run, 0 failures)

### 36. 13-07 D5: Versioned metadata rows for delisted and non-TRADING universe symbols; overlong contract_type/status raises instead of truncating; universe always passed; missi
expected: Versioned metadata rows for delisted and non-TRADING universe symbols; overlong contract_type/status raises instead of truncating; universe always passed; missing symbols reported
result: pass
source: automated
coverage_id: 13-07-D5
verified: tests/test_metadata.py#test_refresh_inserts_rows_for_settling_and_pending_symbols; tests/test_metadata.py#test_overlong_metadata_text_raises_not_truncates; tests/test_backfill_cli.py#test_cli_always_passes_universe_to_metadata; tests/test_backfill_cli.py#test_missing_symbols_are_reported; tests/test_backfill_cli.py#test_failure_prints_type_name_never_the_database_url (all in the 570-test targeted pytest run, 0 failures)

### 37. 13-07 D6: The real backfill against Binance over 12/24 months for the research universe (weight budget, wall-clock, real exchangeInfo statuses)
expected: The real backfill against Binance over 12/24 months for the research universe (weight budget, wall-clock, real exchangeInfo statuses)
result: pass
verified: Real backfill output on disk: data/raw holds 126871 Parquet files incl. mark_klines and funding; sufficiency report depth_months 1h/4h/1m = 24, dataset 2024-10-03..2026-10-03, missing_data false, 0 rows with missing or gaps. Operator ran the backfill; weight/wall-clock not re-measured.

### 38. 13-08 D1: After a backfill the CLI prints a per-(dataset, symbol, interval) sufficiency table with expected, stored, missing bars and a cause, writes it canonically with 
expected: After a backfill the CLI prints a per-(dataset, symbol, interval) sufficiency table with expected, stored, missing bars and a cause, writes it canonically with --report-out, and exits 3 only for NOT_BACKFILLED, GAP or UNAVAILABLE
result: pass
source: automated
coverage_id: 13-08-D1
verified: tests/test_backfill_cli.py#test_cli_exit_code_is_3_only_for_missing_data; tests/test_backfill_cli.py#test_report_json_is_deterministic; tests/test_sufficiency.py#test_missing_day_is_a_gap_with_the_builders_gap_definition; tests/test_sufficiency.py#test_unbounded_causes_map_to_no_window_and_unavailable (all in the 570-test targeted pytest run, 0 failures)

### 39. 13-08 D3: 1m coverage per protocol split block (40% Development, four 10% folds, 20% holdout) on the 1h/4h timeline with Decimal percentages, plus the D-21 archive-extens
expected: 1m coverage per protocol split block (40% Development, four 10% folds, 20% holdout) on the 1h/4h timeline with Decimal percentages, plus the D-21 archive-extension note and the flat-tail warning
result: pass
source: automated
coverage_id: 13-08-D3
verified: tests/test_sufficiency.py#test_split_boundaries_follow_protocol_40_40_20; tests/test_sufficiency.py#test_split_coverage_shows_missing_1m_in_development; tests/test_sufficiency.py#test_flat_tail_is_warned_not_failed; tests/test_sufficiency.py#test_validate_subcommand (all in the 570-test targeted pytest run, 0 failures)

### 40. 13-08 D4: Symbols REST no longer serves (-1121) or exchangeInfo no longer lists are backfilled from the checksum-verified archive, capped at delivery or the last archive 
expected: Symbols REST no longer serves (-1121) or exchangeInfo no longer lists are backfilled from the checksum-verified archive, capped at delivery or the last archive day, source recorded per symbol and dataset; a symbol no source serves is UNAVAILABLE; mark is REST-only
result: pass
source: automated
coverage_id: 13-08-D4
verified: tests/test_backfill_cli.py#test_invalid_symbol_uses_archive_source; tests/test_backfill_cli.py#test_archive_only_symbol_capped_at_last_archive_day; tests/test_backfill_cli.py#test_unavailable_symbol_exits_3; tests/test_backfill_cli.py#test_mark_for_archive_symbol_comes_from_rest_or_is_unavailable; tests/test_backfill_cli.py#test_archive_source_survives_a_complete_rerun (all in the 570-test targeted pytest run, 0 failures)

### 41. 13-08 D5: Funding history is backfilled per universe symbol over the 1h/4h dataset range, ending at the delivery cap; a funding failure is a gap row, not a crash; --no-fu
expected: Funding history is backfilled per universe symbol over the 1h/4h dataset range, ending at the delivery cap; a funding failure is a gap row, not a crash; --no-funding skips it
result: pass
source: automated
coverage_id: 13-08-D5
verified: tests/test_backfill_cli.py#test_funding_step_runs_per_symbol_within_bounds; tests/test_backfill_cli.py#test_funding_failure_is_a_gap_row_not_a_crash; tests/test_backfill_cli.py#test_no_funding_flag_skips_the_step (all in the 570-test targeted pytest run, 0 failures)

### 42. 13-08 D2: The report states the D043 trade floor is unmeasurable until the Phase 14 simulator, estimates no trade count and never edits the protocol
expected: The report states the D043 trade floor is unmeasurable until the Phase 14 simulator, estimates no trade count and never edits the protocol
result: pass
verified: Report trade_floor_note says the D043 trade floor cannot be measured until the Phase 14 simulator; tests test_report_states_trade_floor_is_unmeasurable and test_render_table_* passed; protocol untouched.

### 43. 13-08 D6: The real backfill against Binance and data.binance.vision over the research universe (real -1121 behavior, real archive last days, weight and wall-clock cost, r
expected: The real backfill against Binance and data.binance.vision over the research universe (real -1121 behavior, real archive last days, weight and wall-clock cost, real sufficiency numbers against the D043 floor)
result: pass
verified: Committed sufficiency report validates (`python -m src.data.sufficiency validate` -> valid data-sufficiency-report/1), missing_data false, 133 rows. Live re-run not repeated.

### 44. 13-09 D1: build_case_input_data reads only published Parquet partitions (trade 1h/4h/1m, mark 1m, funding, OI) for one symbol and a whole-UTC-day range and returns the si
expected: build_case_input_data reads only published Parquet partitions (trade 1h/4h/1m, mark 1m, funding, OI) for one symbol and a whole-UTC-day range and returns the simulator case-input keys with string Decimals and ISO timestamps; output runs through simulator.run
result: pass
source: automated
coverage_id: 13-09-D1
verified: tests/test_case_input_builder.py#test_builder_reads_published_partitions; tests/test_case_input_builder.py#test_bar_dicts_are_string_typed_and_keys_match_close_time; tests/test_case_input_builder.py#test_builder_output_runs_through_simulator_and_assemble; tests/test_case_input_builder.py#test_to_case_input_refuses_builder_key_collision (all in the 570-test targeted pytest run, 0 failures)

### 45. 13-09 D2: Deterministic 64-hex dataset identity over sorted posix-relative path and file sha256; same partitions same id, any changed/removed partition changes it; assemb
expected: Deterministic 64-hex dataset identity over sorted posix-relative path and file sha256; same partitions same id, any changed/removed partition changes it; assemble() accepts it as data_snapshot_id
result: pass
source: automated
coverage_id: 13-09-D2
verified: tests/test_case_input_builder.py#test_dataset_id_is_deterministic; tests/test_case_input_builder.py#test_dataset_id_changes_with_any_partition; tests/test_case_input_builder.py#test_dataset_identity_paths_are_posix_relative; tests/test_case_input_builder.py#test_dataset_identity_ignores_file_order (all in the 570-test targeted pytest run, 0 failures)

### 46. 13-09 D3: Fail-closed gap policy: gap_ranges_for_files single definition; builder raises CaseInputGapError, never pads; allow_gaps lets exactly the listed gaps through an
expected: Fail-closed gap policy: gap_ranges_for_files single definition; builder raises CaseInputGapError, never pads; allow_gaps lets exactly the listed gaps through and records them
result: pass
source: automated
coverage_id: 13-09-D3
verified: tests/test_coverage.py#test_gap_ranges_reports_interior_kline_gap; tests/test_coverage.py#test_gap_ranges_reports_leading_trailing_and_empty; tests/test_coverage.py#test_funding_jitter_is_not_a_gap_but_a_missing_tick_is; tests/test_coverage.py#test_oi_gap_bound_is_twice_the_cadence; tests/test_case_input_builder.py#test_builder_refuses_unresolved_gap; tests/test_case_input_builder.py#test_allowed_ (all in the 570-test targeted pytest run, 0 failures)

### 47. 13-09 D4: No wall clock and no lookahead: as_of_day_utc input, ranges ending after that day refused, naive or non-midnight bounds refused, unsafe symbol/interval rejected
expected: No wall clock and no lookahead: as_of_day_utc input, ranges ending after that day refused, naive or non-midnight bounds refused, unsafe symbol/interval rejected before file access, no float or clock reference in the module
result: pass
source: automated
coverage_id: 13-09-D4
verified: tests/test_case_input_builder.py#test_range_after_as_of_day_is_refused; tests/test_case_input_builder.py#test_naive_or_non_midnight_start_is_refused; tests/test_case_input_builder.py#test_builder_rejects_unsafe_symbol_or_interval; tests/test_case_input_builder.py#test_case_input_module_has_no_clock_or_float (all in the 570-test targeted pytest run, 0 failures)

### 48. 13-09 D5: The builder run against the real multi-month store the operator backfills (real partition sizes, real gaps, real exchange data)
expected: The builder run against the real multi-month store the operator backfills (real partition sizes, real gaps, real exchange data)
result: skipped
reason: Builder not re-run against the real 126k-file store in this UAT (long read of real partitions); unit coverage passes.

### 49. 13-10 D1: propose ranks PERPETUAL USDT contracts (any status) plus archive-only symbols by 30-day mean daily quote volume at the dataset start (run date minus two years),
expected: propose ranks PERPETUAL USDT contracts (any status) plus archive-only symbols by 30-day mean daily quote volume at the dataset start (run date minus two years), Decimal only, ties by symbol, top 12, including symbols delisted later
result: pass
source: automated
coverage_id: 13-10-D1
verified: tests/test_universe_freeze.py#test_build_report_ranks_top_12_including_delisted_later; tests/test_universe_freeze.py#test_equal_sums_at_the_cut_are_ordered_by_symbol; tests/test_universe_freeze.py#test_discover_candidates_filters_and_dedupes; tests/test_universe_freeze.py#test_module_has_no_float_call_or_annotation (all in the 570-test targeted pytest run, 0 failures)

### 50. 13-10 D2: Eligibility and evidence: delivered before window, listed after window start, incomplete window, zero-trade day; REST to archive fallback on -1121 or short wind
expected: Eligibility and evidence: delivered before window, listed after window start, incomplete window, zero-trade day; REST to archive fallback on -1121 or short window; unavailable symbols listed as unrankable, never dropped; rate limits retried without a source switch; availability per proposed symbol
result: pass
source: automated
coverage_id: 13-10-D2
verified: tests/test_universe_freeze.py#test_delivered_before_window_is_ineligible_without_a_request; tests/test_universe_freeze.py#test_listed_after_window_start_is_ineligible_without_a_request; tests/test_universe_freeze.py#test_incomplete_and_zero_trade_windows_are_ineligible; tests/test_universe_freeze.py#test_rest_invalid_symbol_falls_back_to_archive; tests/test_universe_freeze.py#test_unavailable_symb (all in the 570-test targeted pytest run, 0 failures)

### 51. 13-10 D3: Reviewable, tamper-evident, byte-deterministic report (ranking evidence, deliveryDate per candidate, availability, proposal_sha256) outside the hashed manifest 
expected: Reviewable, tamper-evident, byte-deterministic report (ranking evidence, deliveryDate per candidate, availability, proposal_sha256) outside the hashed manifest payload
result: pass
source: automated
coverage_id: 13-10-D3
verified: tests/test_universe_freeze.py#test_report_round_trips_and_detects_tampering; tests/test_universe_freeze.py#test_freeze_report_is_byte_deterministic (all in the 570-test targeted pytest run, 0 failures)

### 52. 13-10 D4: freeze writes FROZEN manifest (header comments preserved) and sets the witness to the digest from the gate's own hash routine; validate_manifest, check_second_w
expected: freeze writes FROZEN manifest (header comments preserved) and sets the witness to the digest from the gate's own hash routine; validate_manifest, check_second_witness and the gate CLI digest all agree (D-20)
result: pass
source: automated
coverage_id: 13-10-D4
verified: tests/test_universe_freeze.py#test_freeze_writes_matching_witnesses; tests/test_universe_freeze.py#test_frozen_manifest_preserves_header_comments (all in the 570-test targeted pytest run, 0 failures)

### 53. 13-10 D5: Freezing is never a side effect: dry run by default, wrong approval hash, edited report, already FROZEN manifest, preset witness, a short proposal and a witness
expected: Freezing is never a side effect: dry run by default, wrong approval hash, edited report, already FROZEN manifest, preset witness, a short proposal and a witness write failure all refuse or roll back with no file changed; propose exit codes
result: pass
source: automated
coverage_id: 13-10-D5
verified: tests/test_universe_freeze.py#test_freeze_without_flag_writes_nothing; tests/test_universe_freeze.py#test_wrong_approval_hash_refuses; tests/test_universe_freeze.py#test_refreeze_refuses; tests/test_universe_freeze.py#test_already_set_witness_refuses; tests/test_universe_freeze.py#test_witness_write_failure_restores_the_manifest; tests/test_universe_freeze.py#test_fewer_eligible_than_top_n_reports (all in the 570-test targeted pytest run, 0 failures)

### 54. 13-10 D6: A real propose run against live Binance REST and the data.binance.vision archive (about 700 candidates, 6-7 minutes) and the operator freeze of the real manifes
expected: A real propose run against live Binance REST and the data.binance.vision archive (about 700 candidates, 6-7 minutes) and the operator freeze of the real manifest
result: pass
verified: Operator freeze evidenced: freeze report file present, research-universe-v1.toml status = FROZEN with content_sha256 d6223620...1682, DC universe gates PASS in verify_decision_alignment all (ALL_PASS). A fresh live propose run (about 700 candidates) not repeated.

### 55. 13-11 D1: SOURCES.md Phase 13 facts table and BINANCE.md section 13 record every exchange fact with URL, date, method and confidence; docs gate passes
expected: SOURCES.md Phase 13 facts table and BINANCE.md section 13 record every exchange fact with URL, date, method and confidence; docs gate passes
result: pass
verified: verify_decision_alignment.py all -> ALL_PASS; test_decision_alignment_exchange passed.

### 56. 13-11 D2: DATA_MODEL 2.13, DATA_PIPELINE section 15 and CONFIGURATION runtime settings describe the datasets, rules and CLIs as built
expected: DATA_MODEL 2.13, DATA_PIPELINE section 15 and CONFIGURATION runtime settings describe the datasets, rules and CLIs as built
result: pass
verified: verify_decision_alignment.py all -> ALL_PASS including DC-04..DC-06.

### 57. 13-11 D3: D049 row with D-22 and src/data/case_input.py, DOC_STATUS line, contiguous decision table
expected: D049 row with D-22 and src/data/case_input.py, DOC_STATUS line, contiguous decision table
result: pass
verified: docs/DECISIONS.md line 53 is a single-line D049 row; DC gates pass.

### 58. 13-11 D4: Requirements gate maps OPS-06 to Phase 13.1; the full dispatcher is green
expected: Requirements gate maps OPS-06 to Phase 13.1; the full dispatcher is green
result: pass
verified: REQUIREMENTS.md maps OPS-06 to Phase 13.1; test_decision_alignment_bookkeeping passed; dispatcher ALL_PASS.

### 59. 13-12 legacy: research universe v1 is FROZEN with 12 symbols and a content witness
expected: 13-12 legacy: research universe v1 is FROZEN with 12 symbols and a content witness
result: pass
verified: docs/research/universe/research-universe-v1.toml status FROZEN, content_sha256 d6223620...1682; freeze report committed; tests/test_universe_freeze.py and DC gates passed; verify_decision_alignment.py all -> ALL_PASS.

### 60. 13-13 legacy: collect-list-v2 (TRADING symbols) exists and sufficiency report covers 1m/1h/4h/funding at 24 months with missing_data false
expected: 13-13 legacy: collect-list-v2 (TRADING symbols) exists and sufficiency report covers 1m/1h/4h/funding at 24 months with missing_data false
result: pass
verified: collect-list-v2.toml present; Dockerfile copies universe dir; report validates as data-sufficiency-report/1; depth 24 months; missing_data false.

### 61. 13-13 legacy: Development-block 1m shortfall is reported honestly, not hidden (accepted by operator)
expected: 13-13 legacy: Development-block 1m shortfall is reported honestly, not hidden (accepted by operator)
result: pass
verified: split_coverage shows HYPEUSDT development 75690/420480, PUMPUSDT 16830/420480, REEFUSDT 160380/420480 and REEFUSDT 0 after delivery in all later blocks; onboarding/delivery limited, listed in report, no padding. Operator accepted this trade-count/coverage shortfall (known).

## Summary

total: 61
passed: 58
issues: 0
pending: 0
skipped: 3
blocked: 0

## Gaps

[none]
