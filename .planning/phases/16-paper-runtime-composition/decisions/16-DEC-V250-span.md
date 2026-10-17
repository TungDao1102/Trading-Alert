# 16-DEC-V250-span: the research warm-up span is 50 days (16-60 Q0), user decision

option: Q0-accept-derived-span
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

derivation (recorded for audit, executor of plan 16-60): `RESEARCH_WARMUP_SPAN` = whole-day ceiling of max(`STRATEGY_WINDOW_BARS` 1000 x 1 h, `CONTEXT_WINDOW_BARS` 300 x 4 h) = max(1000 h, 1200 h) = 1200 h = 50 days. The cold counts of research run 1 that motivated it (review finding B3-CR-01): `WARMUP_INSUFFICIENT` is exactly 8756 in all 192 Validation records and exactly 9552 in all 48 Development records, i.e. 796 hourly bars per symbol per window.

reviewer text (adopted by the user):

### Q0 — 50-day warm-up span

**Decision: ACCEPT.**

Use:

`warmup_span_days = 50`

This follows `ceil(max(1000 × 1h, 300 × 4h))`: the 4-hour context requirement is 1200 hours, which is 50 days. Load price history only before each Development or Validation window as required to initialize indicators. Do not read Holdout data or use prices from the Holdout period.

The first Development window remains cold because the available dataset begins at `2024-10-03T00:00:00Z`. Do not pretend the missing pre-window history exists. Record this boundary limitation explicitly in the new evidence and evaluation. Do not move the Development start just to hide it.

Rejected option: stopping the warm-up fix would leave the previously identified warm-up-insufficient bars in every window, including Validation folds for which historical price candles are available. The new warm-up process must not change the strategy parameter grid.

corrections of 16-DEC-FIXPLANS.md that apply (verbatim): none of the seven corrections amends this question.

note (recorded by the executor of plan 16-60, not part of the decision):

Copied by a script from the source files named above; the reviewer subsection (and the correction and renumbering text where present) are byte-equal to their sources. Implemented by plan 16-60 (Q0 to Q3) and plan 16-61 (Q4).
