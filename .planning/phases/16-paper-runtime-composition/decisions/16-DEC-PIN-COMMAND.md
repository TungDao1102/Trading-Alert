# 16-DEC-PIN-COMMAND: `--pin-epoch` pins and exits, then the managed service starts at once (16-55 Q3), user decision

option: Q3-pin-and-exit
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

reviewer text (adopted by the user):

### Q3 — `--pin-epoch`

**Decision: A — pin the epoch and exit 0; immediately start the managed service.**

Reason: Pinning and running are separate operations. The pin command must finish before the managed runtime starts, allowing one clear process owner and a deterministic transition to the soak.

The pin-to-service gap counts toward the 900-second uncovered-gap ceiling. The operator must start the managed service as the next operational step, without an unrelated task in between.

Rejected option:
- B: rejected because the one-off Compose process may interact unpredictably with its restart policy and the single-instance guard. The guard could reject the managed service while the one-off process remains the active or ambiguous instance.

The existing single-instance guard remains mandatory. Do not weaken or bypass it.

note (recorded by the executor of plan 16-55, not part of the decision):

Copied by a script from the two source files named above. Implemented by plan 16-55 Task 3 (pin-and-exit, the instance lease also taken by the pin) and Task 4 (one-shot compose pin service with restart "no"; the managed paper service never passes --pin-epoch).
