# 16-DEC-Q-F: how the hourly GitHub freeze check obtains the pinned epoch (plan 16-30, Task 3)

option: commit-pinned-state
decided by: user
date: 2026-10-12
words:
O-01 chọn a, Q-F: commit-pinned-state, Q-Q: off-hour-minute chọn phút 34 đi (tôi nghĩ nó nên ở giữa sẽ cân bằng hơn)

context (recorded for audit): the orchestrator recommended commit-pinned-state beforehand (no storage credential or crypt passphrase on GitHub). The user commits pinned_epoch.json to master after each pin; no credential is written here.
