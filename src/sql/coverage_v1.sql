-- Canonical DuckDB view over the Hive-partitioned candle store (D-04 + D-11).
--
-- Layout referenced (per 02-PATTERNS §14):
--   data/raw/interval=<TF>/symbol=<SYM>/date=<YYYY-MM-DD>/part.parquet
--
-- DuckDB's `read_parquet(..., hive_partitioning=true)` auto-exposes the
-- partition columns as virtual columns; we project them as `tf` for the
-- stable contract used by the CLI and the Phase-6 backtest reports.
--
-- Note: Polars writes tz-aware datetime columns; DuckDB would need
-- `pytz` to read them directly, so we CAST to a naive TIMESTAMP (UTC) at
-- the boundary. The CLI re-attaches UTC for display (D-06).

CREATE OR REPLACE VIEW candles_v1 AS
SELECT
    symbol,
    interval AS tf,
    CAST(open_time_utc AS TIMESTAMP)  AS open_time_utc,
    CAST(close_time_utc AS TIMESTAMP) AS close_time_utc,
    open,
    high,
    low,
    close,
    volume,
    quote_volume,
    trade_count
FROM read_parquet(
    'data/raw/interval=*/symbol=*/date=*/part.parquet',
    hive_partitioning = true
);

-- Per-symbol effective range + row counts. Joined with the PG
-- `coverage_windows` table from the CLI layer (D-11). Kept here as a
-- pure Parquet view so the read path never depends on a live database.
CREATE OR REPLACE VIEW coverage_v1 AS
SELECT
    symbol,
    tf,
    MIN(open_time_utc) AS historical_data_start_utc,
    MAX(close_time_utc) AS historical_data_end_utc,
    COUNT(*)             AS rows
FROM candles_v1
GROUP BY symbol, tf;
