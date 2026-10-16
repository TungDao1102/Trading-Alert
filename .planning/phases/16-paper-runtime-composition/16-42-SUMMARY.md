---
phase: 16-paper-runtime-composition
plan: 42
status: complete
---
# 16-42 summary: the user authorizes the exact hash

- Task 1: `evidence/16-42-preflight.txt` (candidate ids and hash, Q-A option runtime-exact-hash-all, six tests that pinned the empty allowlist in three files; the plan named those of one file) (`15cae9d`).
- Task 2: `decisions/16-DEC-G4-021.md`, option `exact-entry-pin`, decided by the user on 2026-10-16, with the D054 item (i) wording.
- Task 3 (`0670337`, on develop, not pushed): `PAPER_START_ALLOWLIST` holds exactly one `PaperAllowlistEntry` (trend-pullback, research-run-1-a01, hash 6f42f70e7e7a107b1be02fc4079fbb70f1408b4307099aa253bd93ebdbce6d87, approved_at 2026-10-16); the plan's automated check (one entry, hash equal to the validator evidence) prints True; the three allowlist suites pass; the user ran the tests as well and reported no failure. The entry was written by Claude on the user's explicit words in the same reply as the decision.
- The entry reaches `origin/master` only when the user merges; plan 16-43 needs it there and in the soak image (RUNBOOK 20.6).
