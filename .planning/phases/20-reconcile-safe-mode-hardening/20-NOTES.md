# Phase 20 notes

## From the Phase 18 code review (2026-10-19)

Source: `18-user-data-stream-error-taxonomy/18-REVIEW.md` and `18-REVIEW-FIX.md`. Not decided.

- **Map `StreamDivergenceKind.SINK_FAILURE` (new, from fix src/WR-04).** The router now emits it when a sink fails; the reconciler must handle it as a divergence (a lost fill or ALGO_UPDATE is routed again on redelivery, but the divergence itself must be acted on). Also from Phase 18: the supervisor can halt as `TASK_DIED` (src/WR-05), and the sweeper failure events carry the exception type only (src/WR-07).
- **src/WR-03, event ordering.** `ExchangeStateUpdate` carries processing time, not exchange event time; `update_order_exchange_state` overwrites unconditionally and the algo lifecycle key has no ordering, so an out-of-order or duplicated event can move an order backwards. Needs an event-time field (schema migration) and a monotonic rule in the stores; the consumers are here and in Phase 19.
- **src/WR-12, a 429 pause blocks protection and cancels.** While the gate pauses REST after a 429, protective placement and entry cancel are refused, and the manager swallows the cancel failure. A resting GTC entry can fill with no stop until this phase's reconciler re-places it (D034). Owner decision needed: a reduce-risk exemption from the pause, or a durable pending-cancel record that the reconciler works off first.
- **Related, Phase 19 notes:** src/WR-01, WR-02, WR-08, WR-10 and the rest of src/CR-02 are recorded in `19-execution-plan-binding-price-check/19-NOTES.md`.
