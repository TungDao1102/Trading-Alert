---
phase: 25-demo-integration-test-campaign
plan: 18
subsystem: owner-packet
tags: [D-01, D-05, D-06, D-07, owner-runbook, owner-decisions, EXEC-01, OPS-01, OPS-02]
requires: [25-06, 25-07, 25-09, 25-10, 25-11, 25-12, 25-13, 25-14, 25-15, 25-16, 25-17]
provides:
  - ".planning/phases/25-demo-integration-test-campaign/25-OWNER-RUNBOOK.md: the owner campaign checklist (preconditions P1-P9, S00 to S19 in safe order, S20 probe cases, clean-up, evidence template, empty Results and Defects)"
  - ".planning/phases/25-demo-integration-test-campaign/25-OWNER-DECISIONS.md: the decision packet Q-AB to Q-G plus finding questions Q-H to Q-L, every answer line pending"
affects: [25-19, 25-20, 25-21, 25-22, 25-24, 25-25]
tech-stack:
  added: []
  patterns:
    - "one copy-paste PowerShell command per step, variable names only, status NOT_OBSERVED until the owner reports"
    - "each question ends with the exact line `Owner answer: pending` so plans 25-19, 25-21 and 25-22 can fill it"
key-files:
  created:
    - .planning/phases/25-demo-integration-test-campaign/25-OWNER-RUNBOOK.md
    - .planning/phases/25-demo-integration-test-campaign/25-OWNER-DECISIONS.md
  modified: []
key-decisions:
  - "No decision was taken for the owner: every option set carries an assistant recommendation labelled as such and an unfilled answer line; no DECISIONS row was written."
  - "The three strict-xfail twins (25-12-F1, 25-14-F1, 25-15-F1) and finding 25-13-F1 are separate questions (Q-H to Q-K) and the runbook precondition P6 makes closing or waiving them an explicit step before the matching scenario."
  - "Remaining observation findings are grouped: six that may need a design answer in Q-L, the rest as an informational list that the owner may promote."
requirements-completed: []
estimate:
  tokens: 55000
actuals:
  tokens: 16200
  tasks: 3
  commits: 3
plan_head_before: a335fa01ae3a0f0167b0b2012cd1fe0ab2b65d0e
plan_head_after: 400d18779eb451a2f179d4f94c0ccfcba030d4c8
duration: about 45min (interrupted once by a rate limit, resumed from a clean tree)
completed: 2026-11-08
status: complete
---

# Phase 25 Plan 18: Owner runbook and owner decision packet Summary

An ordered, secret-free owner checklist for the whole Demo campaign (S00, S01, then S06 S04 S03 S07 S05 S02 S09 S17 S08 S10 S19 S11 S13 S14 S15 S16 S18, with S12 last, plus the four S20 probe cases) and a decision packet that frames Q-AB, Q-C, Q-D, Q-E, Q-F, Q-G and the open findings as options with a labelled recommendation, deciding nothing.

## What was built

- `25-OWNER-RUNBOOK.md` (about 560 lines):
  - who runs what (D-01), rules (variable names only, status vocabulary, label meaning, 418 and 429 never provoked), sequencing (twins and no strict-xfail twin first, no soak on the same Demo account, S12 last, RUNBOOK 22.5 for any live-process stop, the Phase 16 soak host untouched);
  - preconditions P1-P9 with a names-only environment check and the first-install gate-state rule;
  - the command form `$env:TRADING_DEMO_RUN="1"; uv run pytest -m demo -p no:xdist -s <file>` with the two optional switches (`TRADING_DEMO_OWNER=console`, `TRADING_DEMO_SLOW=1`), the evidence file pattern `25-DEMO-SCENARIO-EVIDENCE-<id>-<UTC stamp>.json` and the session index `25-DEMO-SESSION-INDEX-<UTC stamp>.json`;
  - Session 1 (S00 preflight, S01 happy path), what to bring back, a step index, one subsection per scenario (command, expected result and outcome words from the scenario docstrings, labels, evidence, clean-up with `scripts/demo_clear.py` after the four `leaves_state` scenarios and any failure, status NOT_OBSERVED), the stranded-ban recovery for S19, the S20 probe table (`partial_fill_attempt`, `entry_cancel_fill_race`, `timestamp_outside_recv_window`, `gtd_entry_expiry_status`) and the permanent NOT_OBSERVED rows DVM-28 and DVM-29, optional variants (NOT_TESTED), and the R-22 interim restart rule;
  - the evidence template and empty "Results (owner run)" and "Defects" sections.
- `25-OWNER-DECISIONS.md` (about 365 lines): an informational section (D083 supersedes OWNER-3, the optional `rest_gate.ban_end_clock_margin_ms`, R-22 interim, R-23/R-28 deferred, the twin-fidelity observations), then Q-AB, Q-C, Q-D, Q-E, Q-F, Q-G as in the plan, then Q-H (25-12-F1), Q-I (25-14-F1), Q-J (25-15-F1), Q-K (25-13-F1) and Q-L (six observations). Each has context, options with pros and cons, "Assistant recommendation (not a decision)", what it gates, and the last line `Owner answer: pending`.

## Tasks and commits

| Task | Name | Commit |
|---|---|---|
| 1 (tracer) | runbook: preconditions, S00, S01, evidence template, Results, Defects | b524a97d |
| 2 | runbook: S02-S19 in safe order, S20, restart rule | 86497cea |
| 3 | decision packet | 400d1877 |

Tracer gate: the Task 1 verify command was re-run after the commit and exited 0 before expanding.

## Verification (agent-run, no network, no Demo)

- Task 1 verify: exit 0. Task 2 verify: exit 0; the last `test_demo_sNN_` file name in the runbook is `s12` (exit 0). Task 3 verify: exit 0; 12 occurrences of the recommendation label; all 11 `Owner answer:` lines are `pending`.
- The secret grep of the plan (`hc-ping.com/...`, 40+ alphanumeric run, dotted-IP URL) prints nothing for both files.
- No evidence file name in the runbook matches the plan 25-20 existence regex (placeholders only).
- `git diff --exit-code -- pyproject.toml uv.lock` exits 0; `uv run pytest tests/test_phase25_gate.py` passes.
- Not run, by design: the full suite, mypy, ruff and `verify_decision_alignment.py` (only `.planning` Markdown files changed; no `docs/`, `src` or test file).

## Deviations from Plan

### Auto-added

**1. [Rule 2 - hard rule of the orchestrator] Finding questions Q-H to Q-L added to the packet**
- **Found during:** Task 3.
- **Issue:** the plan lists Q-AB to Q-G only, while the dispatch said the findings F1.. and the three open strict-xfail twins belong in the decision packet.
- **Fix:** added Q-H to Q-L after Q-G and an informational list before Q-AB. The Q-AB to Q-G sections and the plan's regex checks are unaffected; each new question ends with `Owner answer: pending`.
- **Files modified:** `25-OWNER-DECISIONS.md`.
- **Commit:** 400d1877.

**2. Probe command uses `--environment DEMO` and `python -m scripts.demo_probe`**
- The plan text says `--environment demo`; the CLI choices are the enum value `DEMO` and the documented form in `.planning/DEMO-EVIDENCE-PLAN.md` is the module invocation. The runbook uses that form.

### Known issues carried, not fixed

- Precondition P6 cannot be met today: three strict-xfail twins are open (S07 cut b, S11, S12). The runbook tells the owner to close or waive them per scenario; it does not waive them.

## Findings

None new. The open findings of plans 25-08 to 25-16 are now framed as questions Q-H to Q-L or listed as informational; I verified by search of `src` that `enforce_daily_state` and `UserDataSupervisor.request_resync` still have no production caller, and that the four twin test names the packet cites exist.

## Not covered by an agent-run test

- Every command in the runbook is unrun by design (D-01): the exact pytest `-k` words for S07 (`cut_a`, `cut_b`, `cut_c`) were chosen by reading the test names, not by running pytest; `-p no:xdist -s` with a path argument was not exercised on Demo.
- Expected results are copied from the scenario docstrings and modules, which describe what the code is meant to do; a Demo run may differ, and the runbook tells the owner to report differences.
- The P2 PowerShell names-only command and the P6 Python one-liner were not executed here (P6 (b) is a plain `xfail` text search).
- The soak procedure is not in this file; plan 25-24 adds the "Soak (owner)" section.
- No requirement is marked complete: all Demo results remain NOT_OBSERVED until plan 25-20 records the owner's evidence.

## Known Stubs

None.

## Threat Flags

None. Both files hold variable names, never values; T-25-43 (secret in the runbook) is mitigated by the grep above, T-25-44 (ban or dirty account) by the "never provoked" rule, S12 last and the clean-up rule, T-25-SC by an unchanged `pyproject.toml` and `uv.lock`.

## Self-Check: PASSED

- FOUND: 25-OWNER-RUNBOOK.md, 25-OWNER-DECISIONS.md
- FOUND commits: b524a97d, 86497cea, 400d1877 (ancestors of HEAD)
