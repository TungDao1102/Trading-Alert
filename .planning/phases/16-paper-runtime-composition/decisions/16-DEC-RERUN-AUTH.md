# 16-DEC-RERUN-AUTH: fresh authorization of the research run 1 rerun under simulator 2.2.0 / protocol v2.5.0, user decision

option: authorized-by-owner
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

reviewer text (adopted by the user):

### Fresh authorization in the owner's words

I authorize one regenerated research run under `simulator_semantics_version = 2.2.0` and `protocol_version = v2.5.0`, using the accepted 50-day price-only warm-up where pre-window history is available.

The run covers exactly the 3 registered strategy families, their existing 48 immutable parameter sets and the five existing Development/Validation windows, generating up to 240 records. The only allowed market-price history is that required by the registered windows and their pre-window warm-up. Do not run the Holdout window, read Holdout prices/returns/metrics or modify the Holdout consumption entries.

I authorize the agent to create the three fresh authorization files after the runner enforces the required `simulator_semantics_version` field and the relevant gates and tests pass. Each file must use the exact frozen manifest hash and the exact grid hash for that family, along with the existing required authorization fields. The sixth field must be `simulator_semantics_version: "2.2.0"`. Do not manufacture or guess hashes; stop if the exact expected hashes cannot be verified.

This authorization is limited to rerunning the registered Development/Validation research under the new semantics. It does not authorize changing parameters, choosing a new candidate from the new results, changing `strategy_version`, consuming Holdout, or making any live-trading decision. The already designated candidate `research-run-1-a01` remains the designated candidate unless I issue a separate decision.

### Assistant/agent permission to write the authorization files

**Approved**, subject to the conditions above. The agent may write and commit the three new authorization files when the plan, exact hashes, schema and validation tests are ready. It must not start the research run before the fresh authorization files and runner checks are validated.

### Conditions before running

Before authorizing the actual execution:
- Complete 16-55 through 16-59 in the prescribed order.
- Complete the 16-60 semantics/version changes and required validation tests.
- Ensure D072 and D073 are recorded.
- Ensure the Holdout marker has only the authorized `protocol_version` change and its consumption entries remain empty.
- Ensure the runner enforces the sixth authorization field.
- Ensure all three fresh authorization files bind exactly to the frozen manifest and registered grid hashes.
- Ensure the new output directory is isolated from old records.

If any precondition fails, stop and report. Do not run a partial or differently configured study under the same authorization.

reviewer text says D072 and D073; recorded as D073 and D074

note (recorded by the executor of plan 16-61): the three files docs/research/preregistration/research-run-1-v2-2-0-authorization-<family>.json were written after the runner enforced the sixth key. On 2026-10-17 the user repeated the permission in the session in these words: "Ký ba file authorization làm như thế nào, tôi uỷ quyền cho bạn làm luôn". Hashes: evidence/16-61-hashes.txt.
