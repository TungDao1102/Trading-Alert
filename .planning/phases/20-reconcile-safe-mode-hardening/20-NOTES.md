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

## From the Phase 18 code review (2026-10-19)

Source: `18-user-data-stream-error-taxonomy/18-REVIEW.md` and `18-REVIEW-FIX.md`. Not decided.

- **Map `StreamDivergenceKind.SINK_FAILURE` (new, from fix src/WR-04).** The router now emits it when a sink fails; the reconciler must handle it as a divergence (a lost fill or ALGO_UPDATE is routed again on redelivery, but the divergence itself must be acted on). Also from Phase 18: the supervisor can halt as `TASK_DIED` (src/WR-05), and the sweeper failure events carry the exception type only (src/WR-07).
- **src/WR-03, event ordering.** `ExchangeStateUpdate` carries processing time, not exchange event time; `update_order_exchange_state` overwrites unconditionally and the algo lifecycle key has no ordering, so an out-of-order or duplicated event can move an order backwards. Needs an event-time field (schema migration) and a monotonic rule in the stores; the consumers are here and in Phase 19.
- **src/WR-12, a 429 pause blocks protection and cancels.** While the gate pauses REST after a 429, protective placement and entry cancel are refused, and the manager swallows the cancel failure. A resting GTC entry can fill with no stop until this phase's reconciler re-places it (D034). Owner decision needed: a reduce-risk exemption from the pause, or a durable pending-cancel record that the reconciler works off first.
- **Related, Phase 19 notes:** src/WR-01, WR-02, WR-08, WR-10 and the rest of src/CR-02 are recorded in `19-execution-plan-binding-price-check/19-NOTES.md`.
