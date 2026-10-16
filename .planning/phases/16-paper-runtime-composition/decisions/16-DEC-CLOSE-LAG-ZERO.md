# 16-DEC-CLOSE-LAG-ZERO: the loader rejects a zero minute close lag (16-56 Q2), user decision

option: Q2-reject-zero
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

reviewer text (adopted by the user):

### Q2 — Zero `minute_close_lag_seconds`

**Decision: A — the loader must reject zero.**

Keep the existing value 5 seconds. Enforce the same positive-value rule in the configuration validator and the poller contract.

Rejected option:
- B: rejected because polling exactly at candle close has no demonstrated guarantee that the final bar is complete. Reading a partial or not-yet-published bar could create non-deterministic candle processing.

corrections of 16-DEC-FIXPLANS.md that apply (verbatim): none of the seven corrections amends this question.

## Re-check of B1-WR-10 (executor of plan 16-56, not the owner's words)

On 2026-10-16, before the fix: `parse_runtime_config` accepted `minute_close_lag_seconds = 0` (`_ZERO_ALLOWED` held the key) while `LiveMinutePoller.__init__` raised "close_lag_seconds must be positive, got 0". The finding holds: a value the loader accepted made the SHADOW chain refuse to build after RUNTIME_START. The ratified value stays 5 (16-DEC-O-07).
