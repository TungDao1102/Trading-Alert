# 16-DEC-CONFIG-PIN: the effective configuration values are bound to the pinned epoch (16-57 Q1), user decision

option: refuse-on-value-change
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

the decision line for this question (16-DEC-FIXPLANS.md, "Decisions adopted (summary of the reviewer text)"):
- 16-57 Q1: B, SHA-256 of the canonical, schema-validated effective values, refused on mismatch with exit 6 and the held state; the raw file hash is recorded for provenance only.

reviewer text (adopted by the user):

### Q1 — Bind effective runtime configuration to the pinned epoch

**Decision: B — hash canonical, parsed configuration values and refuse a semantic mismatch.**

The pin and every service start must record the SHA-256 of the canonical, validated effective configuration values. Every start must recompute this hash and refuse to operate on a mismatch, using exit code 6 and the held/non-operational refusal state from 16-55.

Canonicalization must:
- Validate the complete schema before hashing.
- Reject missing and unknown keys rather than silently ignoring them.
- Include all effective values; do not inject implicit defaults that are absent from the registered configuration.
- Use deterministic key ordering and deterministic serialization.

A change to any effective value during a trial invalidates the pinned configuration and must not be allowed to continue under the same epoch. Whitespace or comment-only edits must not create a different effective configuration identity.

The raw file SHA-256 may be recorded separately for forensic provenance, but it is not the semantic comparison used by the guard.

Rejected options and failure scenarios:
- A: rejected because a comment or whitespace edit would refuse a semantically unchanged configuration. This creates unnecessary trial interruption without strengthening the effective-value guarantee beyond the canonical hash.
- C: rejected because a changed configuration would continue operating during the trial and only be found by the evaluator afterwards. For example, changed `risk_rate` could affect the trial without an immediate refusal.
- D: rejected because an audit-only hash does not prevent a mismatched configuration from operating.

## Re-check of B1-WR-08 (executor of plan 16-57, not the owner's words)

On 2026-10-16, before the fix: a pin with the admission rig's configuration, then an edit of `account.risk_rate` from "0.01" to "0.02" in the file named by PAPER_RUNTIME_CONFIG, then a start. The start exited 0 and the loop received risk_rate 0.02. The EPOCH_PINNED and RUNTIME_START payloads held only `parameter_set_hash`, `parameter_set_id` and `strategy_id`: no record of the configuration and no refusal. The finding holds.

note (recorded by the executor of plan 16-57, not part of the decision):

Copied by a script from the two source files named above (the reviewer section byte for byte from the committed file). Implemented by plan 16-57 Task 3: `config_identity` in `src/paper/runtime_config.py` hashes the validated values (never the file bytes); EPOCH_PINNED and every RUNTIME_START carry it with the raw file SHA-256 and path labelled as provenance; `check_epoch_consistency` refuses a differing or absent identity with `EpochMismatch` (exit 6, held under `--hold-on-refusal`).
