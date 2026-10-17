# 18-DEC-O-18-03: live Demo smoke order limits (O-18-03, smoke)

option: values
decided by: user
date: 2026-10-16

words:
> ok tôi xác nhận

The reply answers the orchestrator's corrected proposal below. The first proposal (quantity at the minimum quantity, far_price_fraction 0.5) was withdrawn before the user's reply: the Demo BTCUSDT filters read on 2026-10-16 (public, unsigned) are MIN_NOTIONAL 50, LOT_SIZE minQty and stepSize 0.0001, PERCENT_PRICE multiplierDown 0.95 and multiplierUp 1.05, so 0.0001 gives a notional of about 8 and a price at 0.5 of the mark is outside the band.

Values written to `18-smoke-limits.toml`:

- order.symbol: BTCUSDT
- order.quantity: 0.0008 (step grid 0.0001; notional about 63 at the mark of that day, above the 50 minimum)
- order.far_price_fraction: 0.96 (a resting BUY limit at 96 percent of the mark, inside the 0.95 band)
- waits.event_wait_seconds: 30
- waits.cleanup_timeout_seconds: 60

The tool re-checks the band, the step grid and the notional at run time and stops before any order if a check fails.
