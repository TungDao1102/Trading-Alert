# 18-DEC-D01: event types design review (plan 18-03 Task 2 gate)

option: amend
decided by: user
date: 2026-10-16

words:
> dùng đúng câu trên, làm đi

The "câu trên" is the confirmation line the orchestrator proposed in the previous turn and the user adopted verbatim:

> Tôi chấp nhận phản hồi của reviewer (cả hai lượt) làm quyết định của tôi cho Package 1 (kiểu sự kiện, kèm các trường bổ sung) và Package 2 (các con số, môi trường DEMO, tên credential, bốn lớp algo đều UNKNOWN). Tách rate-limit thành ba khóa: 418 chờ 259200 giây, 429 chờ 120 giây, cap 259200 giây. Với 429: lệnh hủy và lệnh đọc chỉ được thử lại có giới hạn như hiện nay, còn lệnh đặt lệnh thì không bao giờ tự thử lại. Cho phép sửa các plan chưa thực thi để thêm khóa.

The reviewer text the user accepted (quoted; the reviewer's words, adopted by the user's line above). Package 1 part:

- Q1: no. Amend OrderUpdateEvent by retaining all fields in section 1.3 of `18-DESIGN-REVIEW-event-types.md` and adding these optional fields from the SDK model:
  - close_position: bool | None from o.cp (StrictBool)
  - price_protect: bool | None from o.pP (StrictBool)
  - activation_price: Decimal | None from o.AP (StrictStr, parsed as Decimal using the existing strict decimal grammar)
  - callback_rate: Decimal | None from o.cr (StrictStr, parsed as Decimal using the existing strict decimal grammar)
  - good_till_date_ms: int | None from o.gtd (StrictInt, non-negative); preserved as the raw integer, no further timestamp semantics inferred without verified documentation.
- Q2: yes. modify_id stays `str | None` (SDK StrictStr).
- Q3: yes. o.ps stays required; a missing position side is an anomaly.
- Q4: no. close_position (o.cp) and price_protect (o.pP) are added as optional strict booleans (see Q1).
- Q5: yes. Empty strings in optional text fields stay FIELD_VALIDATION anomalies.
- Q6: no. AlgoUpdateEvent additionally carries: stp_mode: str | None from o.V (StrictStr); price_match: str | None from o.pm (StrictStr); good_till_date_ms: int | None from o.gtd (StrictInt, non-negative, raw integer). The remaining Task 3 field list as written.
- Q7: yes. reject_reason (o.rm) verbatim, capped at 200 characters, diagnostic only, never a decision input.
- Q8: yes. AccountUpdateEvent, BalanceDelta, PositionDelta are deltas only; an unknown reason is carried verbatim; no equity, margin or position state is inferred; funding_symbol accepted only for FUNDING_FEE.
- Q9: yes. ListenKeyExpiredEvent carries only the event time; the listenKey is never stored in the event, anomaly, repr or diagnostic output.
- Q10: yes. leverage int, multi_assets bool.
- Q11: yes. IgnoredEvent for TRADE_LITE, STRATEGY_UPDATE, GRID_UPDATE; MARGIN_CALL is UNHANDLED_EVENT; CONDITIONAL_ORDER_TRIGGER_REJECT is DEPRECATED_EVENT.
- Q12: yes. All event dataclasses keyword-only (kw_only=True) and frozen.
- Q13: yes. A TRADE with zero last-filled quantity is a parsed event and produces no fill; no fill is synthesized from accumulated quantity.

General conditions for Task 3 (reviewer text, accepted):
- Keep the event module SDK-free; Decimal for money, quantities and prices.
- Unknown status and execution values stay fail-closed anomalies.
- Preserve payload redaction, canonical hashing, UTC-aware timestamps and the anomaly-detail restrictions.
- Do not weaken guards to make synthetic tests pass. Synthetic tests stay labelled synthetic; they are not evidence of live Binance frame behavior.
- Implement the amendments before the remaining parsers of Task 3; update tests and wire-field alias guards accordingly.
- None of these design approvals is live verification of Binance documentation or exchange payloads.

Orchestrator verification note (not a decision): the added SDK fields were checked against the installed models (o.cp, o.pP bool; o.AP, o.cr str; o.gtd int; algo o.V, o.pm str; o.gtd int).
