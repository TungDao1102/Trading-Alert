# 16-DEC-V250-row: decision record numbering of the protocol v2.5.0 amendment and the regeneration inventory (16-60 Q1), user decision

option: Q1-D073-and-D074
decided by: user
date: 2026-10-16
source: .planning/phases/16-paper-runtime-composition/16-DEC-FIXPLANS.md (commit bdbdc11)
words:
> Tôi chấp nhận phản hồi của reviewer về Phase 16 làm quyết định của tôi, kèm 7 chỉnh sửa của trợ lý (mục 1–7 ở trên) và việc đổi yêu cầu queueing của 16-59 Q2 thành "phát hiện và ghi tick thiếu". Tôi ủy quyền chạy lại nghiên cứu 2.2.0 / v2.5.0 như văn bản đó nêu, sửa đúng trường protocol_version của holdout marker, và cho phép agent ghi ba file authorization sau khi runner đã bắt buộc trường thứ sáu.

reviewer text (adopted by the user):

### Q1 — Decision record numbering

**Decision: A.**

- D072: protocol v2.5.0 warm-up amendment.
- D073: regeneration inventory and disposition of the original records.

D071 is already occupied. Preserve its existing decision and do not reuse its number.

Rejected option B: rejected because one row would combine a protocol amendment and a research regeneration inventory, weakening traceability between the semantic change and its generated evidence.

corrections of 16-DEC-FIXPLANS.md that apply (verbatim):

6. D072 numbering: the Phase 18 worktree already holds a DECISIONS row D072. At integration the Phase 18 row is renumbered to the next free number; Phase 16 keeps D072 and D073.

renumbering section of 16-DEC-FIXPLANS.md (verbatim; it replaces the integration step of correction 6):

## Renumbering 2026-10-16

Bookkeeping only; the owner's decisions above are unchanged (owner informed 2026-10-16). Phase 18 was merged into develop first (merge 6610bd6) and holds the DECISIONS row D072 ("Phase 18 client configuration, user-data stream and exchange error taxonomy"), which keeps its number; docs/DECISIONS.md ends at D072 and gate DC-02 requires contiguous ids. Phase 16's two new rows are therefore:

- D073: protocol v2.5.0 warm-up amendment (named D072 in 16-60 Q1 above and in the reviewer text).
- D074: regeneration inventory and disposition of the original 240 records (named D073 in 16-60 Q1 and 16-61 above and in the reviewer text).

This replaces the integration step of correction 6: no Phase 18 row is renumbered. The text above and decisions/16-DEC-FIXPLANS-reviewer-text.md are not edited; where they name D072 or D073 for Phase 16, read D073 or D074. Plans 16-60 and 16-61 and ROADMAP.md use the new numbers, and every record that copies the owner's or reviewer's text verbatim adds the mapping line.

mapping (recorded by the executor of plan 16-60): reviewer text says D072 and D073; recorded as D073 and D074
adopted text label: (semantic, D073)

note (recorded by the executor of plan 16-60, not part of the decision):

Copied by a script from the source files named above; the reviewer subsection (and the correction and renumbering text where present) are byte-equal to their sources. Implemented by plan 16-60 (Q0 to Q3) and plan 16-61 (Q4).
