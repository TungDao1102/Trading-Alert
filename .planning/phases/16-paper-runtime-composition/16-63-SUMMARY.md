---
phase: 16-paper-runtime-composition
plan: 63
subsystem: research-runner
status: complete
tags: [research, planner, tp2-guard, simulator-semantics-2.3.0, protocol-v2.6.0, rerun, supersession, BKTS-03]
requires: [16-60, 16-61]
requirements: [BKTS-03]
requirements-completed: [BKTS-03]
provides:
  - "plan() returns NO_TRADE RR_TOO_LOW when the stored TP2 is not above zero (SHORT only; Decimal zero; no new enum, no DB change); tests/test_planner_tp2_positive.py"
  - "SIMULATOR_SEMANTICS_VERSION 2.3.0 and protocol v2.6.0 with D075 and D076, landed in one commit (6f599dd) after the owner's adoption record (afa5a94)"
  - "three owner-signed six-key 2.3.0 authorization files (f5ee61a); the agent wrote none"
  - "research run 1 regenerated under 2.3.0: 240 records in docs/research/experiments/research-run-1-v2-3-0/ (b17312a)"
  - "evidence/16-63-run-output.txt and evidence/16-63-feasibility-table.md"
  - "decisions/16-DEC-RUN1-SUPERSEDED.md and the note appended to evidence/16-46-run1-feasibility-table.md (f8453f9)"
  - "evidence/16-63-final-gate.txt: eight exit=0 lines, PostgreSQL tests run (03e29ee)"
affects: [16-43, 16-44, 16-61, 16-62]
plan_head_before: 3550d9c14565c517c88d5d1f972b05c5a070716d
plan_head_after: 03e29ee2377aa746f5ef8211160e76e91be69b65
actuals:
  tokens: 332000
  tasks: 7
  commits: 11
key-files:
  created:
    - tests/test_planner_tp2_positive.py
    - tests/test_research_protocol_v260.py
    - .planning/phases/16-paper-runtime-composition/scripts/16-63-sign-authorizations.py
    - docs/research/experiments/research-run-1-v2-3-0/ (240 records)
    - .planning/phases/16-paper-runtime-composition/evidence/16-63-red-evidence.txt
    - .planning/phases/16-paper-runtime-composition/evidence/16-63-regen-inventory.md
    - .planning/phases/16-paper-runtime-composition/evidence/16-63-gate.txt
    - .planning/phases/16-paper-runtime-composition/evidence/16-63-hashes.txt
    - .planning/phases/16-paper-runtime-composition/evidence/16-63-run-output.txt
    - .planning/phases/16-paper-runtime-composition/evidence/16-63-feasibility-table.md
    - .planning/phases/16-paper-runtime-composition/evidence/16-63-final-gate.txt
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-V260.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-RERUN-AUTH-V230.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-RERUN-PARALLEL.md
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-RUN1-SUPERSEDED.md
  modified:
    - src/core/planner.py
    - src/backtest/semantics.py
    - docs/research/RESEARCH_PROTOCOL.md
    - docs/DECISIONS.md
    - docs/research/holdout_consumed.json
    - .planning/phases/16-paper-runtime-composition/evidence/16-46-run1-feasibility-table.md
key-decisions:
  - "16-63: a plan whose stored TP2 is not above zero is NO_TRADE RR_TOO_LOW (owner Option A, strict reading); simulator semantics 2.3.0, protocol v2.6.0, D075 and D076"
  - "16-63: research run 1 regenerated under 2.3.0 (240 records, three families in parallel by owner decision of 2026-10-19); the 2.1.0 records are kept and superseded in the owner's wording with only the versions replaced (16-DEC-RUN1-SUPERSEDED.md)"
  - "16-63: R7 answered 2026-10-19: the soak image is rebuilt from a commit containing the TP2 guard and the 16-62 gate repeated before plan 16-43 pins the epoch"
duration: "2026-10-17 to 2026-10-20 (Tasks 6 remainder and 7 in this session: about 50 min, plus the 29 min full suite)"
completed: 2026-10-20
---

# Phase 16 Plan 63: TP2 positivity guard, simulator 2.3.0, protocol v2.6.0 and the 2.3.0 rerun of research run 1 Summary

A SHORT plan whose TP2 is not a positive price is now NO_TRADE RR_TOO_LOW in research and paper alike (simulator semantics 2.3.0, protocol v2.6.0, D075 and D076), and research run 1 exists again as 240 records under 2.3.0 that supersede the 2.1.0 records in the owner's words.

## Tasks and commits

| Task | What | Commit(s) |
|---|---|---|
| 1 | Guard in plan() with tests (tracer, TDD) | RED: evidence/16-63-red-evidence.txt (4 failed, 10 passed, base 3550d9c); GREEN landed in 6f599dd |
| 2 | Regeneration inventory 2.2.0 to 2.3.0 | b349f9b |
| 3 | Owner adoption record (R1 to R6 adopted, R7 open) | afa5a94; R7 answer 7f4f090 |
| 4 | Landing commit (guard, version, protocol, D075, D076, regenerated pins) and its gate | 6f599dd, 2be5260 |
| 5 | Preconditions, hashes, refusals, signing script; owner-signed files | 8bea35b, f5ee61a |
| 6 | The 2.3.0 rerun (parallel by owner decision), verification rerun, evidence | 58a5374 (decision and plan amendment), b17312a |
| 7 | Supersede record, note on the 2026-10-16 table, final gate | f8453f9, 03e29ee |

Commits measured: 11 commits labelled `(16-63)` in 3550d9c..03e29ee (the range holds 69 commits; the other 58 belong to phases 18 and 19, which ran on develop in the same days), plus the closing docs commit of this SUMMARY.

## RED evidence and inventory

- RED (Task 1): `tests/test_planner_tp2_positive.py`, 14 tests, 4 failed and 10 passed with the planner unmodified; all failures on the planned behaviour.
- Inventory (Task 2, evidence/16-63-regen-inventory.md): 108 failing tests on the first full run after the bump: VERSION_PIN 11, DERIVED_DIGEST 9, STORED_RECORD 88, other 0. Leak check over 28 cases: only the version string and trade_id differ. Guard-reach count 0 (no committed plan or case holds a TP2 at or below zero).

## Owner answers R1 to R7 (16-DEC-V260.md)

- R1 to R6: adopted as drafted on 2026-10-17 (reply "adapt-all", recorded as adopt-all): 2.3.0 and v2.6.0 with D075 and D076; the normative v2.6.0 block; the supersession wording with only the two versions replaced; strategy_version stays v5.0.0; the Holdout marker changes only protocol_version; directory `research-run-1-v2-3-0` and sixth key "2.3.0".
- R7 (answered 2026-10-19, "option 1 đi"): the 16-62 gate is repeated and the soak image rebuilt from a commit containing the TP2 guard (6f599dd or later) before plan 16-43 pins the epoch.
- Rerun mode (2026-10-19, 16-DEC-RERUN-PARALLEL.md): the three families run at the same time, replacing the sequential rule for this rerun only.

## DECISIONS rows

- D075: research protocol v2.6.0 frozen; a plan whose TP2 is not a positive price is NO_TRADE RR_TOO_LOW; simulator semantics 2.3.0.
- D076: regeneration inventory 2.2.0 to 2.3.0 and the disposition of the original 240 records.
- D072, D073, D074 byte-unchanged (witness test).

## Gates

- Task 4 gate (evidence/16-63-gate.txt, landing commit 6f599dd, PostgreSQL container): 10257 passed, 6 skipped, 0 failed; ruff, format, mypy, uv lock clean; byte checks clean.
- Final gate (evidence/16-63-final-gate.txt, HEAD f8453f9, 2026-10-20T00:13:18Z to 00:42:15Z): `pytest -m "not docker"` 10394 passed, 19 skipped (platform skips 7 and shellcheck 12; no PostgreSQL skip), 0 failed; ruff check, ruff format --check (631 files), mypy src (202 files), uv lock --check: clean; byte-unchanged against 5f8269b, dce3195 and f5ee61a. The PostgreSQL server was a native Windows PostgreSQL 17.11 service at 127.0.0.1:5432 (TEST_DATABASE_URL set, database trading_test), not the Docker container of the earlier gates; Docker was not running. A PostgreSQL test (tests/test_paper_shadow_pg.py) passed 4 of 4 before the run.

## The rerun (Task 6)

RUN_COMMIT 58a5374aea2d99aa59104ca8faa516fbfd680630; worktree C:\rerun-v230\trading-rerun-v230 (detached, clean, import root checked); checkpoint directories C:\rerun-v230\ck\<family>. The run was executed by the orchestrator; this executor wrote the evidence from its logs and the record files.

```
family=trend-pullback start=2026-10-19T11:22:09Z end=2026-10-19T16:05:40Z exit=0 records=80
family=breakout-retest start=2026-10-19T11:22:30Z end=2026-10-19T23:54:23Z exit=0 records=80
family=range-mr start=2026-10-19T11:22:51Z end=2026-10-19T19:16:04Z exit=0 records=80
```

Wall time: trend-pullback 4 h 43 min, breakout-retest 12 h 32 min, range-mr 7 h 53 min (in parallel, so the times overlap). Verification rerun, one family at a time: 80 `present` lines each, all 80 timing lines `checkpoint=reused`, exit 0, nothing written (ended 2026-10-19T23:59:21Z, 2026-10-20T00:03:21Z, 00:07:23Z). The 240 file ids equal the 240 `recorded` ids and the 240 `present` ids.

WARMUP_INSUFFICIENT as stored in the records (full list in evidence/16-63-run-output.txt): every DEVELOPMENT record (48) holds 9552 (cold window, data begins 2024-10-03); every VALIDATION record (192) holds no WARMUP_INSUFFICIENT key, printed as 0.

Task 6 checks: 240 records all 2.3.0 with a trades digest (True); family-line check (names sorted, exit 0, 80 records: True); `git diff --quiet 5f8269b HEAD` over research-run-1, params and the manifest: exit 0; Holdout marker entries empty and protocol_version v2.6.0: exit 0. The run output holds the feasibility, plateau, mark-hole, modeled_costs_per_unit and timing sections; a scan of the two evidence files for the forbidden judgement words of the owner rule found none.

## Supersession (Task 7)

`decisions/16-DEC-RUN1-SUPERSEDED.md` holds option owner-text, decided by user, date 2026-10-17, the owner's words, the D074 paragraph with "simulator_semantics_version 2.2.0" and "protocol v2.5.0" replaced by the 2.3.0 and v2.6.0 forms (derived by script, asserted equal to R3), the sentence that no record was ever written under 2.2.0 or v2.5.0, and factual references. `evidence/16-46-run1-feasibility-table.md` is the 5f8269b blob bytes plus the appended note (prefix check True, also on the committed blob). All four Task 7 verify commands pass.

## Deviations from Plan

1. **[Owner decision] Families ran in parallel**, not one at a time (16-DEC-RERUN-PARALLEL.md, 2026-10-19; plan Task 6 text and its order check were amended in 58a5374 before the run).
2. **[Rule 3 - naming] Checkpoint directories** are `C:\rerun-v230\ck\<family>`, not `<abs-path>/rerun-v230-ck/<family>`: new, empty at start, outside both trees and carrying v230 in the path, as the threat mitigation T-16-185 requires.
3. **[Rule 2 - reporting] WARMUP_INSUFFICIENT counts** are not printed by the runner; the acceptance criterion asks for them in the run output, so the evidence copies each record's stored count (key absent printed as 0, marked as absent).
4. **[Environment] Cleanup of the 2.2.0 attempt:** `trading-rerun-v220` is not registered in `git worktree list` and neither it nor `rerun-v220-ck` exists on this machine (the 16-61 paths are under `C:\Users\daotu\`, which does not exist here); nothing was removed or deleted. The 2.3.0 worktree was removed with `git worktree remove` after the records commit.
5. **[Environment] PostgreSQL:** the orchestrator expected PostgreSQL off; a native Windows PostgreSQL 17.11 service was reachable through TEST_DATABASE_URL, so the final gate ran with the PostgreSQL tests (none skipped). No WINDOWS.md unrun-verify entry was written because the suite with PostgreSQL did run; writing one would be false.
6. **Extra byte check** against f5ee61a (2.3.0 authorization files, Holdout marker) added to the final gate (eight exit=0 lines, seven required).

## Disposition of plan 16-61

16-61 remains partial and its SUMMARY is unchanged. Its Tasks 1 and 2 are done (d5067a3 to dce3195); its Tasks 3 and 4 were replaced by Tasks 6 and 7 of this plan, both done. `16-61-gate.txt` and `16-61-feasibility-table.md` were never produced.

## Leftovers (for the owner)

- `C:\rerun-v230\ck\<family>` (checkpoints of the 2.3.0 run) and `C:\rerun-v230\logs` (full run logs, about 170 MB) kept as instructed; deleting them is the owner's call.
- The 2.2.0 checkpoint directories `rerun-v220-ck` (recorded under `C:\Users\daotu\`): not present on this machine.
- The three unused 2.2.0 authorization files, `16-DEC-RERUN-AUTH.md` and the three five-key files stay in the repository, unchanged and unused.
- The keep-awake helper of the orchestrator (`C:\rerun-v230\keepawake.ps1`, powershell PID 73944) was still running at the end of this session.
- Open, not authorized by the owner (16-DEC-V260.md): the real-bar planner replay; hardening of `src/paper/shadow.py` (finiteness only) and of the non-finite raise in `quantize_for_storage`; the same class of defect for a LONG stop at or below zero (not observed).

## Next

Plan 16-43 on the soak host, after the soak image is rebuilt from a commit containing the TP2 guard and the 16-62 gate is repeated (R7). BKTS-03: `requirements.ready-ids` reports it ready and REQUIREMENTS.md already marks it Complete; nothing changed. PAPER-01 is not marked.

## Self-Check: PASSED

- Files: the 240 records, 16-63-run-output.txt, 16-63-feasibility-table.md, 16-DEC-RUN1-SUPERSEDED.md, 16-63-final-gate.txt exist.
- Commits: b17312a, f8453f9, 03e29ee present on develop.
