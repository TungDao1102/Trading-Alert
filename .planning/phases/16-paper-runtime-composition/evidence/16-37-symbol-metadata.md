# 16-37 symbol_metadata read (local `trading` database), 2026-10-13

Read-only SELECTs through the pg-trading MCP server the user enabled for this purpose (user words: "tôi đã bật mcp postgresql cho bạn rồi. hãy select"). No write, no migration, no network call to Binance, no secret in the output. The EC2 database was NOT read (no access from this session); the user must run the same two SELECTs there.

## Whole table (local)

174 rows, 19 symbols, one distinct day: first observation 2026-10-03T03:11:57Z, last 2026-10-03T15:23:11Z. Every row was observed AFTER the end (2026-10-03T00:00Z, exclusive) of the window the reviewer tentatively chose, so no in-window observation exists.

## The 12 symbols of research-universe-v1 (each: one distinct constraint set, 9 rows, 12 for BTCUSDT)

| Symbol | status | tick | step | min_qty | min_notional |
|---|---|---|---|---|---|
| 1000PEPEUSDT | TRADING | 0.0000001 | 1 | 1 | 5 |
| BNBUSDT | TRADING | 0.01 | 0.01 | 0.01 | 5 |
| BTCUSDT | TRADING | 0.1 | 0.001 | 0.001 | 50 |
| DOGEUSDT | TRADING | 0.00001 | 1 | 1 | 5 |
| DOGSUSDT | TRADING | 0.00000001 | 1 | 1 | 5 |
| ETHUSDT | TRADING | 0.01 | 0.001 | 0.001 | 20 |
| REEFUSDT | SETTLING | 0.000001 | 1 | 1 | 5 |
| SOLUSDT | TRADING | 0.01 | 0.01 | 0.01 | 5 |
| SUIUSDT | TRADING | 0.0001 | 0.1 | 0.1 | 5 |
| WIFUSDT | TRADING | 0.0001 | 0.1 | 0.1 | 5 |
| WLDUSDT | TRADING | 0.0001 | 1 | 1 | 5 |
| XRPUSDT | TRADING | 0.0001 | 0.1 | 0.1 | 5 |

Onboard dates (onboard_time_utc): all before 2024-10-03 except none after; DOGS 2024-08-26 and WIF 2024-01-18 are the latest (all within or before the window start).

## What this does and does not show

- All 12 symbols, REEFUSDT included, have a row from a real exchange response (REEFUSDT carries status SETTLING, a Binance status that a test fixture would not normally hold). The table has no provenance/source/version column, so "real collector response" is inferred, not recorded.
- Every symbol has exactly ONE observation day, 2026-10-03. There is no history. The whole window (730 days) lies before the first observation; the runner flags every bar before the first row as `extrapolated` (src/backtest/constraints.py:183-189).
- There is NO evidence in this table that tick, step, min_quantity or min_notional held these values in 2024-10..2026-05. They must not be called historical truth.
- The extrapolation choice is open (reviewer: not decided). Blocker for O-03.
