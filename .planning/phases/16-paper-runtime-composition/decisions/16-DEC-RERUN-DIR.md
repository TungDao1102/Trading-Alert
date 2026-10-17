# 16-DEC-RERUN-DIR: directory of the regenerated research records (16-60 Q3), user decision

option: Q3-new-directory
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

path: docs/research/experiments/research-run-1-v2-2-0/

reviewer text (adopted by the user):

### Q3 — Directory for regenerated records

**Decision: A — use a separate directory.**

Use:

`docs/research/experiments/research-run-1-v2-2-0/`

Keep the original directory and every original record untouched. The new location must not cause directory-wide globs, reports or digest generation to mix the original and regenerated record sets.

Rejected options:
- B: rejected because relying on every reader to filter by simulator version is fragile; one reader that omits the filter could silently combine incompatible evidence.
- C: rejected because a separate owner-named path is unnecessary when a version-specific path has already been designated here.

corrections of 16-DEC-FIXPLANS.md that apply (verbatim): none of the seven corrections amends this question.

note (recorded by the executor of plan 16-60, not part of the decision):

Copied by a script from the source files named above; the reviewer subsection (and the correction and renumbering text where present) are byte-equal to their sources. Implemented by plan 16-60 (Q0 to Q3) and plan 16-61 (Q4).
