# Phase 20 notes (carried from Phase 17)

Input for `/gsd-discuss-phase 20` and the researcher. Not a decision record.

## Verify against current Binance docs and Demo (do not assume)

- When a position is closed manually (outside this system), do the protective SL/TP orders
  (STOP_MARKET and TAKE_PROFIT_MARKET with `closePosition`, placed through
  `POST /fapi/v1/algoOrder`) cancel automatically, or do they stay on the exchange as orphans?
  The answer decides what the orphan sweeper and reconcile must do after a manual close.
  Re-read the live Binance pages and prove the behavior on Binance Demo (Phase 25) before
  relying on either answer. AGENTS.md requires exchange facts to be re-verified, not recalled.

## Other items carried from Phase 17 (see D051 items (h) and (i))

- Crash right after the STOP_LOSS intent leaves an acknowledged entry without a stop, and restart
  does not place one (reconcile must close this gap).
- Journal-outage behavior of controller `disable`, `expire_pending_entry`,
  `cancel_untriggered_protectives` and `emergency_manual_close` (F-702).
- Every Order/Position move out of `UNKNOWN` needs Binance evidence (reconcile over REST or a
  user-data event). Record the evidence source in the journal when the first caller exists.
- An executed TradePlan stays `APPROVED`; its `expiry_utc` governs only an unfilled entry. Do not
  write code that moves an executed plan to `EXPIRED`.
