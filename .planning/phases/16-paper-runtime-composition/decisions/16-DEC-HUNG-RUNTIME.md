# 16-DEC-HUNG-RUNTIME: hung paper runtime detection by a separate paper heartbeat (16-55 Q2), user decision

option: Q2-second-monitor-check
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
paper_heartbeat_interval_seconds: 60
paper_check_period_seconds: 60
paper_check_grace_seconds: 120
ping_url: a second secret URL, provided by the user before plan 16-43; never written in the repository
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

reviewer text (adopted by the user):

### Q2 — Hung-runtime detection

**Decision: B — a separate heartbeat check for the paper runtime.**

Chosen monitoring values:
- Heartbeat interval: 60 seconds.
- Expected check period: 60 seconds.
- Grace period: 120 seconds.
- Use a separate secret heartbeat URL from the existing host/service heartbeat.

Reason: The paper runtime must have an independently observable liveness signal. One combined alert cannot distinguish failure of the general host heartbeat from failure of the paper process. A dedicated check should detect a missed paper heartbeat well before the 900-second uncovered-gap ceiling, allowing time for human investigation or restart.

The heartbeat must be emitted only while the paper runtime is genuinely healthy. A held startup refusal or hung event loop must not continue to report success.

Rejected options and failure scenarios:
- A: rejected because one shared alert obscures which service failed and delays diagnosis.
- C: rejected because the existing unhealthy probe takes approximately 3900 seconds to declare the runtime unhealthy, already beyond the 900-second ceiling. A timer acting only on that probe cannot protect this trial's coverage criterion.
- D: rejected because documentation alone does not detect a hung process.

The heartbeat is an alerting mechanism, not proof of recovery. If the runtime stays down long enough to exceed the coverage ceiling, the trial must fail that criterion.

corrections of 16-DEC-FIXPLANS.md that apply (verbatim):

2. 16-55 Q2 / 16-56 Q1: the paper heartbeat must be driven by the 120 s feed-liveness or loop-alive signal, not the 3900 s bar-age probe. A qualifying message is any frame on the connection, not per symbol. The user must provide a second secret heartbeat URL.

note (recorded by the executor of plan 16-55, not part of the decision):

Copied by a script from the two source files named above. Built by plan 16-56 Task 4 (it reads the feed-silence key and the watchdog stamp that 16-56 creates, 16-DEC-FIXPLANS.md correction 2); plan 16-55 writes no heartbeat code. On 2026-10-16 the user kept option B (16-DEC-FIXPLANS.md, last paragraph).
