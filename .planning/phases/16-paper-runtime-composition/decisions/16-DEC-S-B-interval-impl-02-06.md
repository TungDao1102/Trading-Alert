# 16-DEC-S-B-interval-impl-02-06: authorization of plans 02-06 of quick 261014-nnl

option: authorize-plans-02-06
decided by: user
date: 2026-10-14
words:
ok chạy đi, nếu có thể làm task nào khác song song thì bật worktree cũng được

context (recorded for audit): the words answer the assistant's question "Bạn muốn tôi chạy plan 02–06 không?" after plan 01 landed (e41f759).

## Scope (the assistant's reading)
- Authorized: plans 03, 02, 04, 05, 06 of quick 261014-nnl, in dependency order (03; then 02, 04, 05; then 06). Code and added test files only, as those plans list.
- NOT covered, each needing its own go in the user's words: plan 07 (version bump, regeneration), plan 08 (protocol v2.4.0 text adoption), plan 09 (landing, `holdout_consumed.json` marker), plan 10, manifest freeze, O-03/16-46, any Holdout read, ExperimentRecord, git push.
- Worktrees: the user allowed them "if something can run in parallel". The assistant's choice is to keep executors sequential on the main tree (plans 02/04/05 touch different files but share the engine contract plan 03 sets), so no worktree is enabled.
