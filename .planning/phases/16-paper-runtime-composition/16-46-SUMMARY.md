---
phase: 16-paper-runtime-composition
plan: 46
status: complete
---
# 16-46 summary: authorization and first real research run

- Task 1: hashes and the runner refusal on the real inputs (`fb0993b`, `evidence/16-46-hashes.txt`).
- Task 2: authorization. Three files (one per grid, `docs/research/preregistration/research-run-1-authorization-<family>.json`), written by Claude on the user's explicit words ("Tôi, Tung Dao, ủy quyền chạy research run 1 kịch bản S0 cho cả ba grid ... và cho phép Claude tạo ba file ủy quyền"); O-03a option (a) amended accordingly (`d4ca261`, note in `16-DEC-O-03b-freeze.md`).
- Task 3: run. Three runner processes in parallel (one per family, `--time-run`, `--checkpoint-dir` per family outside the repo), 240 experiment records (3 families x 16 points x 5 windows), no error. A first attempt was refused by the runner's grid-vs-registry check before any simulation (grid text "1.0" vs registry 1, label pivot_bars); fixed by numeric comparison and a pivot_bars alias (`a225420`), grid files, hashes and authorizations unchanged. Records on code `a225420`, dirty flag from untracked `.gsd/` and `.planning/milestone.lock` only (src/ and params/ were clean, enforced by the runner in checkpoint mode).
- Verification rerun of the three commands: all 240 records printed `present` (byte-equal), no window simulated, report sections identical.
- Evidence: `evidence/16-46-run-output.txt` (the three rerun reports), `16-46-run1-feasibility-table.md`, `16-46-run1-range-mr-lookback-probe.md` (regime_filter_lookback is live but practically flat; c01..c08 behave as c09..c16 on this data).
- Automated checks of Task 3 pass: sections present, no verdict wording, 240 records, `docs/research/holdout_consumed.json` entries empty.
- Not done here: full test suite after the run (stopped by memory pressure); 453 PostgreSQL tests need TEST_DATABASE_URL; BKTS-03 is to be marked complete by the requirements batch since a real run printed the plateau section.
