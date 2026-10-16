# 16-DEC-RESTART-POLICY: restart policy of the paper service and the held refused start (16-55 Q1), user decision

option: Q1-unless-stopped-hold-skipped
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

reviewer text (adopted by the user):

### Q1 — Restart after host reboot or Docker daemon restart

**Decision: A — `restart: unless-stopped` plus hold on refused start.**

Reason: A Docker restart policy must cover both an application exit and a daemon restart. The official Docker documentation states that `on-failure` does not restart a container when the daemon restarts, whereas `unless-stopped` does. The trial cannot rely on an operator being present to restart a service after a reboot.

The startup-refusal behavior is an explicit amendment to the prior "a refused start exits at once" rule. When startup is refused, the process must enter a held, non-operational state: no paper tick, no signal processing, no new journal event that suggests a healthy runtime, and no order-related action. The healthcheck and heartbeat must report startup refusal as unhealthy, not healthy. A refused startup must remain clearly observable and must never be confused with a running soak.

The managed service must preserve the requested-stop behavior: an intentional stop must remain stopped until the operator starts it again.

Rejected options and failure scenarios:
- B: rejected because changing the exit code does not solve the documented `on-failure` daemon-restart limitation. A host or daemon restart may leave the runtime stopped and exceed the coverage gap ceiling.
- C: rejected as written because a boot unit alone does not establish recovery after an independent Docker daemon restart. A manual stop being undone on the next boot is also an avoidable operational surprise.
- D: rejected because manual recovery after a reboot is not guaranteed within the 900-second uncovered-gap ceiling.

Before landing, test the refused-start, requested-stop, process-crash, host-reboot and Docker-daemon-restart paths. If the held refusal state cannot be distinguished reliably from a healthy runtime, stop and report a blocker rather than weakening the guard.

corrections of 16-DEC-FIXPLANS.md that apply (verbatim):

1. 16-55 Q1: `unless-stopped` keeps a stopped state only after `docker stop` / `compose stop`; a runtime-initiated exit 0 would be restarted. The plan tests that case. The held refused-start state needs an explicit marker that makes the healthcheck report unhealthy (the existing probe only checks bar age, 3900 s).

note (recorded by the executor of plan 16-55, not part of the decision):

Copied by a script from the two source files named above; the reviewer section and the correction line are byte-equal to their sources. Implemented by plan 16-55 Task 3 (held refused start with an explicit held marker, SKIPPED held under --hold-on-refusal, exit-0 path inventory) and Task 4 (compose restart policy). The five paths are drilled on the soak host by plan 16-43 before the pin (RUNBOOK, "Restart drill before the pin").
