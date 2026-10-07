---
phase: 15-strategy-geometry-correction
plan: 17
subsystem: paper
tags: [paper-start-gate, rationale, allowlist, gap-closure]
status: in-progress
requirements-completed: [STRAT-01, STRAT-02]
---

# Phase 15 Plan 17: Paper start gate wired into run_paper_tick Summary

## Decision on older parameter sets

Decided-by: user (verbatim replies 2026-10-07)

Checkpoint: 15-17-01 (asked and answered in the planning conversation, before execution)

Reply 1 (verbatim):

~~~text
B — chỉ cho phép các tập tham số được chỉ định đích danh và gắn với hash của từng tập.
Không cho phép mọi tập thiếu rationale tự động chạy paper.
Các tập mới của Phase 15 hiện vẫn phải bị reject cho tới khi có authorization/rationale phù hợp.
Giữ cơ chế fail-closed: run_paper_tick phải từ chối ngay trước khi đọc candle nếu parameter set không nằm trong allowlist được phê duyệt.
~~~

Reply 2 (verbatim):

~~~text
đồng ý cả hai, sửa plan 15-17 và chạy lại checker
~~~

Context for Reply 2 (Claude's words, not the user's): after Reply 1, Claude proposed two things and Reply 2 accepts both. (1) Amend plan 15-17: the allowlist is an exact parameter-set identity list (each entry: strategy_id, parameter_set_id, full 64-hex parameter_set_hash, purpose, approved_at, basis; the only pass decision is an exact match of the hash computed from the parameter file through the registry; ids are lookup only), it applies only to sets with no rationale tables, the gate runs in run_paper_tick before any candle is parsed, and a test proves the non-empty allowlist branch. (2) The allowlist is empty at this time and D-27 is not changed: the five Phase 15 sets stay refused and cannot be admitted through the allowlist.

Plain reading (Claude's words): Option B. A set without rationale tables may start a paper stream only if the approved allowlist names it by strategy_id and parameter_set_id with its exact parameter_set_hash. The allowlist is empty at 2026-10-07, so all 20 older sets are refused as not in the approved allowlist; this is the decided safe state, not a fault. Sets with rationale tables always get the full rationale and PLACEHOLDER check, so the five Phase 15 sets stay refused (D-16, D-27 unchanged). Today no committed set can start a paper stream. Phase 16 can start a paper stream only after a new fully rationalized set with no PLACEHOLDER key exists, or after a new user checkpoint adds an exact-hash entry.
