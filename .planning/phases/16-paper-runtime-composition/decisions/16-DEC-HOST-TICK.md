# 16-DEC-HOST-TICK: second freeze tick source on the soak host (quick task 261113-x91 Task 2; built by quick task 261114-12e)

option: s3-witness
decided by: user
date: 2026-11-14
source: quick task 261113-x91 Task 2 (the owner's answer was relayed by the orchestrator in the description of quick task 261114-12e; the owner's original message is not in the repository)
amends: 16-DEC-O-01.md (accepted by the owner with least privilege; the DECISIONS row is written by plan 261114-12e-PLAN-B)
credential: a dedicated credential that can only create objects (PutObject; no delete, no overwrite, no read or list) under one fixed witness prefix of the existing evidence bucket, held as a systemd credential of the host timer unit, never in the repository, an image, a container environment or a log
words:
> s3-witness đi
> Chấp nhận, quyền tối thiểu

context (recorded for audit): the design the owner answered is the Part 2 section of `261113-x91-PLAN.md` (quick task 261113-x91, freeze tick resilience). Lateness is decided only by the provider-stamped server time of a create-only witness object, never by a time the host writes in its line. The grace (1800 s), the slot grid, the minute list, the thresholds, the criteria set and D065 item 4 are unchanged. A line with no witness object is not evidence. `16-DEC-O-01.md` is kept unchanged as the original record.
