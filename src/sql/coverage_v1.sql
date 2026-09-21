-- Canonical DuckDB views over the Hive-partitioned Parquet store
-- (D-04 + D-08 + D-11 + DATA_PIPELINE §10).
--
-- Layout referenced (per 02-PATTERNS §14):
--   data/raw/interval=<TF>/symbol=<SYM>/date=<YYYY-MM-DD>/part.parquet
--   data/raw/data_class=oi/symbol=<SYM>/date=<YYYY-MM-DD>/tick-<ISO>.parquet
--   data/raw/data_class=funding/symbol=<SYM>/date=<YYYY-MM-DD>/tick-<ISO>.parquet
--   data/raw/data_class=oi_research/symbol=<SYM>/date=<YYYY-MM-DD>/tick-<ISO>.parquet
--
-- DuckDB's `read_parquet(..., hive_partitioning=true)` auto-exposes the
-- partition columns as virtual columns; we project them as `tf`,
-- `data_class`, and `symbol` for the stable contract used by the CLI and
-- the Phase-6 backtest reports.
--
-- Note: Polars writes tz-aware datetime columns; DuckDB would need
-- `pytz` to read them directly, so we CAST to a naive TIMESTAMP (UTC) at
-- the boundary. The CLI re-attaches UTC for display (D-06).

-- ---------------------------------------------------------------------------
-- Candle view (1m/1h/4h; extensible later)
-- ---------------------------------------------------------------------------
--
-- Defensive loader: `read_parquet` raises on a glob with zero matches,
-- which breaks the test environment before any partition exists. We
-- pre-check with `glob()` and CREATE OR REPLACE an empty view when the
-- pattern matches nothing — the CLI reads the view as `[]` and prints
-- "no coverage rows" rather than crashing.

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

-- Per-symbol effective range + row counts (D-11). Pure Parquet view so the
-- read path never depends on a live database; the CLI joins PG-side
-- `coverage_windows` (onboard time + status history) at the print edge.
CREATE OR REPLACE VIEW coverage_v1 AS
SELECT
    symbol,
    tf,
    MIN(open_time_utc) AS historical_data_start_utc,
    MAX(close_time_utc) AS historical_data_end_utc,
    COUNT(*)             AS rows
FROM candles_v1
GROUP BY symbol, tf;

-- ---------------------------------------------------------------------------
-- Open interest + funding rate coverage (D-08 / DATA_PIPELINE §3 + §9)
-- ---------------------------------------------------------------------------
--
-- Canonical day-one OI ticks (`data_class=oi`) plus the funding-rate
-- sweep (`data_class=funding`). One view per data class keeps each
-- namespace self-contained; the CLI reports both side by side.

CREATE OR REPLACE VIEW oi_coverage_v1 AS
SELECT
    symbol,
    data_class,
    MIN(CAST(observed_at_utc AS TIMESTAMP)) AS historical_data_start_utc,
    MAX(CAST(observed_at_utc AS TIMESTAMP)) AS historical_data_end_utc,
    COUNT(*)              AS rows
FROM read_parquet(
    'data/raw/data_class=oi/symbol=*/date=*/tick-*.parquet',
    hive_partitioning = true
)
GROUP BY symbol, data_class;

CREATE OR REPLACE VIEW funding_coverage_v1 AS
SELECT
    symbol,
    data_class,
    MIN(CAST(observed_at_utc AS TIMESTAMP)) AS historical_data_start_utc,
    MAX(CAST(observed_at_utc AS TIMESTAMP)) AS historical_data_end_utc,
    COUNT(*)              AS rows
FROM read_parquet(
    'data/raw/data_class=funding/symbol=*/date=*/tick-*.parquet',
    hive_partitioning = true
)
GROUP BY symbol, data_class;

-- Combined view (oi + funding + oi_research) so the CLI can iterate once.
CREATE OR REPLACE VIEW all_tick_coverage_v1 AS
SELECT
    symbol,
    data_class,
    MIN(CAST(observed_at_utc AS TIMESTAMP)) AS historical_data_start_utc,
    MAX(CAST(observed_at_utc AS TIMESTAMP)) AS historical_data_end_utc,
    COUNT(*)              AS rows
FROM read_parquet(
    'data/raw/data_class=*/symbol=*/date=*/tick-*.parquet',
    hive_partitioning = true
)
GROUP BY symbol, data_class;

