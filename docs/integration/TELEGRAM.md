# Telegram Integration

## 1. Purpose

Telegram is the human approval/notification channel, not the strategy engine.

## 2. Required actions

Minimum message actions:

- `SIMULATE`
- `APPROVE`
- `SKIP`

Later:

- `CANCEL ENTRY`
- `CLOSE POSITION`
- `SAFE MODE`

## 3. Approval security

An approval must be bound to:

- SignalId,
- strategy version,
- exact trade plan hash,
- expiry time,
- user identity / authorized chat,
- one-time approval token.

Replaying an old approval must not place a fresh order.

## 4. Message contents

At minimum:

- symbol,
- direction,
- setup,
- entry,
- SL,
- TP(s),
- R:R,
- risk percentage,
- expiry,
- invalidation,
- current exposure,
- clear reason codes.

The APPROVE message also shows the approved quantity on a `Quantity:` line: the plan's `quantity_after_rounding`, the same value that is stored on the approval row as `approved_quantity` (D078 item (6)), written in fixed-point notation with every digit of the Decimal and never rounded. A message without it is refused and not sent. The SIMULATE message has no approval row and does not carry it.

## 5. Failure behavior

If Telegram is unavailable:

- signals must still be journaled;
- live order placement must not be inferred from missing notification;
- system must not auto-approve.

## 6. Callback delivery semantics

Treat Telegram callback delivery as **at-least-once**.

For a callback carrying an already-consumed approval token:

```text
lookup approval token
→ return current approval/order state
→ do not create a new order intent
```

The system must be idempotent across duplicate, delayed, or retried callbacks.
