# 16-DEC-REV-16: how the frozen data manifest enters the experiment identity

option: route-b-seventh-field
decided by: user
date: 2026-10-11

words:
route B: thêm trường thứ bảy manifest_hash vào danh tính thí nghiệm, giữ nguyên ngữ nghĩa hiện tại của data_snapshot_id.Việc cập nhật protocol v2.2.0, schema và analytics-evidence phải được thực hiện trong tác vụ sửa đổi protocol riêng, hoàn tất trước lần research execution thật đầu tiên; không thay đổi công thức dataset_id hay di chuyển các ràng buộc hiện có trong quyết định này.

## Notes (recorded by the executor, not part of the user's words)

- Source brief: `decisions/16-REV-16-brief.md` (commit 7583dad). Route B there is the seventh identity
  field; `data_snapshot_id` keeps its current meaning and the `dataset_id == data_snapshot_id`
  bindings stay as they are.
- Brief correction applies: the manifest identity helper is the module function
  `manifest_hash(manifest)` at `src/research/manifest.py:235` (not a method
  `DatasetManifest.manifest_hash()`). The seventh field equals its value.
- The `analytics-evidence/2` loader refuses unknown keys (closed key set,
  `src/adapters/analytics_files.py:98-138`, `_load_experiment` 599-640). The separate protocol
  amendment task must therefore decide between an optional key with a default, an update of the
  evidence fixtures, or a schema bump. This decision does not choose among those.
- Scope: the v2.2.0 protocol, schema and analytics-evidence changes belong to the separate
  amendment task, finished before the first real research execution. No Phase 16 plan edits the
  protocol. The `dataset_id` formula and the existing bindings are not changed by this decision.
- Next: plan 16-28 Task 3 (user starts the separate amendment task; the proof file
  `evidence/16-28-amendment-check.txt` comes only after it lands).
