# 16-DEC-EVIDENCE-KEYS: object keys of the hourly and final evidence bundles (16-59 Q1), user decision

option: Q1-per-bundle-key
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

reviewer text (adopted by the user):

### Q1 — Hourly and final evidence object keys

**Decision: A — each bundle gets its own immutable key.**

Use:

`<epoch>/<as_of>-<sha12>/`

Apply this layout to hourly and final bundles. Use create-only/immutable publication semantics consistent with O-01; do not replace an existing object at the same key. Retain the configured bucket versioning and the existing no-retention/no-Object-Lock decisions.

Reason: A uniform unique-key scheme removes the collision that currently breaks the second hourly publish and preserves each bundle independently.

Rejected options and failure scenarios:
- B: rejected because it introduces separate hourly/final publication semantics and a special final location without providing a necessary advantage over unique per-bundle keys.
- C: rejected because replacing an hourly object violates the immutability requirement even if bucket versioning can retain older versions.
- D: rejected because it reverses O-01 hourly publication timing and leaves the soak dependent on host-disk survival until the final bundle is published.

corrections of 16-DEC-FIXPLANS.md that apply (verbatim):

4. 16-59 Q1: with `sha12` in the key, re-exporting identical bytes hits the same key: identical bytes count as success, different bytes are an error.

re-check by the executor of plan 16-59 (not part of the decision):

B2-CR-04 holds on the parent commit: `publish_bundle` stored `<epoch_id>/<file>` and refused an epoch prefix that already held `manifest.json`, so the second hourly publish of one epoch exited 4 and the final bundle could never be published (`tests/test_soak_evidence_export.py`, the former test `test_an_epoch_prefix_that_already_holds_a_manifest_is_never_published_over`, held that refusal). The decision does not depend on this re-check.

note (recorded by the executor, not part of the decision):

Copied by a script from the two source files named above; the reviewer section and the correction line are byte-equal to their sources. Implemented by plan 16-59 Task 2: the key is `<epoch_id>/<as_of>-<sha12>/<file>` with `<as_of>` the manifest `as_of_utc` as `YYYYMMDDTHHMMSSZ` and `<sha12>` the first 12 hex characters of the SHA-256 of the manifest bytes; files first and `manifest.json` last; an existing complete bundle with identical bytes is a success that uploads nothing; any different bytes at an existing key are an error (exit 4) and nothing is replaced. O-01 (`16-DEC-O-01.md`: versioning on, no Object Lock, no retention, hourly write timing) is unchanged.
