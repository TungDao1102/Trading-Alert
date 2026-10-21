---
phase: 20-reconcile-safe-mode-hardening
plan: 07
status: in-progress
---

# Phase 20 Plan 07: REST gate restart recovery Summary (draft, Task 1 recorded)

## Owner decision O-C

`option-a1-with-commands`

The owner's own words (Vietnamese, verbatim), given in the orchestrator session on 2026-10-21 after the
options, the purpose of the state file, the 3-day figure (the ratified 259200 s wait) and the
consequences were explained:

> O-C tôi muốn có thể tự gỡ ban, nhưng nếu tôi phát hiện ra ban nhầm thì cũng nên có cơ chế để tôi tắt nó đi trên server chẳng hạn

> O-C chọn a1 kèm status/clear, D-15 accept, thêm mục hoãn vào 20-24.

Accepted operational consequence of option-a1, copied from the checkpoint context of
20-07-PLAN.md: a deleted or corrupt initialized state file blocks every REST call, including
emergency reduce-only closes, protective actions and reconciliation reads, until a human acts
with the clear command (initialize() after checking the account); every restart before that
keeps the block (the loss is re-detected, never read as a fresh install); there is no bypass
for any order category.

Task 1 was satisfied by this answer in the orchestrator session; no executor stop.
