option: reserve-at-confirm
decided by: user
date: 2026-10-10
words:
Chọn Option reserve-at-confirm.

Addendum (same reply): reservation hết hạn cùng thời điểm hết hạn của plan gốc, theo expiry semantics hiện có. Không tạo TTL riêng cho reservation.

## Basis and scope (recorded by the executor from the user's ratification)

- The basis for the reservation timing is this user decision, NOT D041. D041 only says that
  pre-placement checks re-run at CONFIRM and that only CONFIRM triggers placement.
- Reserve exposure only when a valid CONFIRM is accepted AND the SHADOW_CONFIRMED journal write
  succeeded. Not at signal, not at APPROVE. Backtest parity is not forced; the accepted
  consequences: SHADOW risk verdicts can differ from the backtest while a plan waits, and two
  same-symbol plans can both appear as candidates (only one can be confirmed).
- At CONFIRM the plan is re-evaluated on the CURRENT ledger (validity/expiry, the Q-B fill window,
  same-symbol conflict, cluster cap, aggregate cap, position count, daily stop). A plan that fails
  reserves nothing and never becomes fill-eligible.
- The reservation lasts until the original plan's `expiry_utc` (source close + signal expiry hours).
  No reservation TTL; `signal_expiry_hours` and the expiry semantics are unchanged.
  SHADOW_CONFIRM_EXPIRED is the 60 s confirm-card TTL, a different concept, never mixed.
- A confirmed plan that expires unfilled releases its reservation exactly once and journals a
  terminal outcome with reason PLAN_EXPIRED_UNFILLED; the CONFIRM history stays for audit.
- Q-B confirm-plus-one is unchanged: fill eligibility starts the minute after the CONFIRM minute;
  the reservation starts at the accepted CONFIRM and is not a fill. When no valid fill window
  remains (eligibility status PLAN_EXPIRED or NO_MINUTE_BEFORE_EXPIRY) the CONFIRM is refused.
- Recovery is from the existing journal only (Q-J journal-only); no second state store.
- A journal append whose commit outcome is unknown is never assumed unwritten: the stored event is
  read back and is authoritative (its stored `confirmed_at_utc` feeds the Q-B start); an unreadable
  journal fails closed (no reservation, no fill eligibility).
