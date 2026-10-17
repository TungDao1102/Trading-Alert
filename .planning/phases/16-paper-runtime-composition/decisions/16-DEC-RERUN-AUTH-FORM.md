# 16-DEC-RERUN-AUTH-FORM: the six-key, simulator-version-bound authorization form of the rerun (16-60 Q4), user decision

option: Q4-six-key-version-bound
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

sixth key: simulator_semantics_version = "2.2.0"

reviewer text (adopted by the user):

### Q4 — Fresh authorization for the rerun

**Decision: B — add a required sixth authorization field and enforce it in the runner.**

Add the required key:

`simulator_semantics_version: "2.2.0"`

The runner must reject an authorization whose semantics version is absent or differs from the active simulator. Create three new family-specific authorization files. Bind each to the exact frozen manifest hash and the matching registered grid hash. Do not use or modify the old authorization files for the new run.

Rejected option A: rejected because file names and dates are human conventions, not machine-enforced safety constraints. The old authorization could still pass the grid/manifest hash checks while authorizing runs under different simulator semantics.

corrections of 16-DEC-FIXPLANS.md that apply (verbatim): none of the seven corrections amends this question.

note (recorded by the executor of plan 16-60, not part of the decision):

Copied by a script from the source files named above; the reviewer subsection (and the correction and renumbering text where present) are byte-equal to their sources. Implemented by plan 16-60 (Q0 to Q3) and plan 16-61 (Q4).
