# 16-DEC-RUN1-SUPERSEDED: research run 1 under simulator semantics 2.1.0 is superseded by the rerun under 2.3.0 (owner wording, versions replaced)

option: owner-text
decided by: user
date: 2026-10-17
source: .planning/phases/16-paper-runtime-composition/decisions/16-DEC-V260.md (item R3, adopted; commit afa5a94) and docs/DECISIONS.md rows D074 and D076; the paragraph's source is decisions/16-DEC-FIXPLANS-reviewer-text.md, subsection "Wording for the original 240 records"
words:
> chọn A và đọc chặt, làm đi

> adapt-all

(2026-10-17, verbatim. The second line is the owner's reply to the Task 3 checkpoint of plan 16-63; 16-DEC-V260.md records it as adopt-all for R1 to R6, R3 being the wording below.)

The owner's paragraph of D074, with only "simulator_semantics_version 2.2.0" replaced by "simulator_semantics_version 2.3.0" and "protocol v2.5.0" replaced by "protocol v2.6.0" (each source string occurs once; derived by a script from the reviewer-text file, as R3 of 16-DEC-V260.md adopted):

The original 240 records are retained unchanged as immutable historical evidence under the simulator semantics and protocol versions recorded in those records. They are superseded for the current confirmatory evaluation by the regenerated records produced under simulator_semantics_version 2.3.0 and protocol v2.6.0. The original records must not be pooled with the regenerated records, combined into their digests, or used as if both sets were produced under the same protocol and simulator semantics. The original artifacts and hashes remain available for historical audit and reproduction of the original run.

No experiment record was ever written under simulator_semantics_version 2.2.0 or protocol v2.5.0; the 2.2.0 rerun stopped at its first family with 0 records (evidence/16-61-run-output.txt).

## References (factual only; no number of either run is interpreted here)

- Original records: `docs/research/experiments/research-run-1/`, 240 records (3 families x 16 points x 5 windows), simulator_semantics_version 2.1.0, code_version `a225420ca9c40f2c8fc086d56f9db2f34ad562b6-dirty` as stored in the records (plan 16-46; the dirty flag came from untracked `.gsd/` and `.planning/milestone.lock` only, 16-46-SUMMARY.md). Byte-unchanged, never deleted or moved (checked against 5f8269b).
- Regenerated records: `docs/research/experiments/research-run-1-v2-3-0/`, 240 records (3 families x 16 points x 5 windows), simulator_semantics_version 2.3.0, protocol v2.6.0, code_version `58a5374aea2d99aa59104ca8faa516fbfd680630` (RUN_COMMIT of plan 16-63 Task 6, not dirty), committed in b17312a; run output `evidence/16-63-run-output.txt`, feasibility table `evidence/16-63-feasibility-table.md`.
- The 2.2.0 attempt (plan 16-61 Task 3, RUN_COMMIT dce3195): stopped at its first family (trend-pullback) with exit 1 and 0 records; `docs/research/experiments/research-run-1-v2-2-0/` was never created (`evidence/16-61-run-output.txt`).
- DECISIONS rows D073 (protocol v2.5.0, simulator semantics 2.2.0), D074 (regeneration inventory 2.1.0 to 2.2.0 and the original wording), D075 (protocol v2.6.0, simulator semantics 2.3.0), D076 (regeneration inventory 2.2.0 to 2.3.0 and this disposition).
- Owner records: `decisions/16-DEC-V250.md`, `decisions/16-DEC-V260.md`.
- Finding B3-CR-01 (16-REVIEW.md): `WARMUP_INSUFFICIENT` is 8756 in every one of the 192 Validation records and 9552 in every one of the 48 Development records of the original run (cold start of every window).
