# 16-DEC-Q-Q: cron minute of the hourly freeze check (plan 16-30, Task 4)

option: off-hour-minute
decided by: user
date: 2026-10-12
words:
O-01 chọn a, Q-F: commit-pinned-state, Q-Q: off-hour-minute chọn phút 34 đi (tôi nghĩ nó nên ở giữa sẽ cân bằng hơn)
cron: 34 * * * *

context (recorded for audit): the minute is the user's own choice; its effect on delayed or dropped runs is unproven (G15). The slot grid is HH:34. The workflow itself is edited in plan 16-47, not here. Decided before the epoch pin (REV-18).
