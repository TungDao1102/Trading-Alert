# 16-DEC-FREEZE-LOG-ASSEMBLY: assembly of the freeze diff log from the run artifacts (16-59 Q2), user decision

option: Q2-merge-artifacts
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

reviewer text (adopted by the user):

### Q2 — Freeze-check diff-log aggregation

**Decision: B — merge available run artifacts and deduplicate by run ID.**

Retain the original workflow artifacts unchanged. Produce a deterministic derived log that merges the relevant lines from all available workflow-run artifacts, with provenance back to each run ID. Do not describe the merged file as a byte-for-byte copy of a single artifact.

The concurrency group remains enabled. Where supported by the repository's GitHub Actions configuration, configure queueing so required runs are not silently replaced by newer pending runs. If a required run is cancelled before producing an artifact, record that missing run/tick explicitly; do not infer a clean result from the absence of an artifact.

Rejected option:
- A: rejected because reading only the newest artifact can permanently lose lines from earlier runs and make the evidence incomplete while appearing clean.

corrections and amendment of 16-DEC-FIXPLANS.md that apply (verbatim):

3. 16-59 Q2: GitHub keeps at most one pending run per concurrency group, so "queue so no required run is replaced" is not achievable. The requirement becomes: detect and record each missing tick explicitly; never infer a clean result from a missing artifact.

## Amendment 2026-10-16 (user): freeze workflow queueing

decided by: user
words:
> Thêm queue: max cho workflow freeze, kèm ghi tick thiếu.

This amends correction 3. The GitHub concurrency documentation read on 2026-10-16 (not verified live) documents `queue: max` (up to 100 pending runs; invalid together with `cancel-in-progress: true`). Plan 16-59 adds `queue: max` beside `cancel-in-progress: false` in the freeze-check workflow and keeps the explicit missing-tick records; absence of an artifact is never read as clean. The first live run on GitHub is the proof that the key is accepted; the plan's workflow test only checks the text.

re-check by the executor of plan 16-59 (not part of the decision):

B2-WR-05 holds as a model of the documented cache behaviour. The workflow restores the newest cache whose key starts with `paper-freeze-` and saves under `paper-freeze-<run_id>`. When two runs overlap, both restore the same state S and save S+a and S+b; the next run restores only the newest cache, so its artifact lacks the line of the other run (model result: the artifact of the third run holds `tick0, tick-b, tick-c`; the artifact of run a holds `tick0, tick-a`). The line of run a survives only in run a's own artifact, which is why the exporter merges every available artifact. Not observed on live GitHub (no network on the development machine). The decision does not depend on this re-check.

dedup identity (plan 16-59 note, not part of the decision):

Every freeze line carries `run_metadata` with `run_id` and `run_attempt` (`src/paper/freeze.py` `RUN_METADATA_ENV`), and `src/paper/coverage.py` `_line_verdict` treats a line with `run_attempt` other than 1 as INVALID_LINE for its slot. The dedup identity is therefore the run as GitHub identifies an execution, `(run_id, run_attempt)`: collapsing a re-run attempt into its first attempt by `run_id` alone could drop the attempt-1 line that is the slot's evidence. Identical lines of one run identity collapse; two different lines with the same run identity are refused; a line without run metadata is deduplicated by its exact bytes.

note (recorded by the executor, not part of the decision):

Copied by a script from the two source files named above; the reviewer section, the correction line and the amendment are byte-equal to their sources. Implemented by plan 16-59 Task 2: `--diff-log` may be given once per downloaded run artifact; the derived `registry_diff.jsonl` is the deterministic union of their lines (ordered by `checked_at_utc`, then run identity), every original artifact is kept byte for byte in the bundle as `freeze_artifact_<sha16>.jsonl`, and the manifest lists each input with its sha256 and the run ids it carried; the derived file is never described as a byte copy of one artifact. The workflow gets `concurrency` with a fixed group, `cancel-in-progress: false` and `queue: max` (never together with `cancel-in-progress: true`). Each scheduled tick without a usable line, including a run that GitHub cancelled before it produced an artifact, is an EVIDENCE_GAP and a row of `missing_ticks.jsonl` with its run id, slot and conclusion.
