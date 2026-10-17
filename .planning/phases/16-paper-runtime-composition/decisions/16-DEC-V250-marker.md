# 16-DEC-V250-marker: the one-field Holdout marker edit, protocol_version v2.4.0 to v2.5.0 (16-60 Q2), user decision

option: Q2-authorized
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

marker_sha256_before: 2f6adee3cb3c601fca3945d962f111ee1c47ce7350f37c68bcc4006705f5b5e4

`marker_sha256_before` is the sha256 of `git show HEAD:docs/research/holdout_consumed.json` taken by the executor of plan 16-60 before the edit (HEAD at that moment: the plan base commit plus no marker change). Only the value of `protocol_version` changes, from `v2.4.0` to `v2.5.0`; `schema` (`holdout-consumed/2`) and the empty `entries` array stay. No Holdout data is read.

reviewer text (adopted by the user):

### Q2 — Holdout marker metadata

**Decision: YES — authorize the one-field edit.**

Authorize changing only the `protocol_version` metadata field from v2.4.0 to v2.5.0 in the Holdout marker file. Keep its entries empty. Do not read Holdout data, add any consumption record, alter other fields, or treat this metadata update as Holdout use.

Rejected option: refusing the field update would leave the marker version inconsistent with the protocol header and fail the required alignment test. This is a metadata alignment action only, not authorization to evaluate Holdout.

corrections of 16-DEC-FIXPLANS.md that apply (verbatim): none of the seven corrections amends this question.

note (recorded by the executor of plan 16-60, not part of the decision):

Copied by a script from the source files named above; the reviewer subsection (and the correction and renumbering text where present) are byte-equal to their sources. Implemented by plan 16-60 (Q0 to Q3) and plan 16-61 (Q4).
