---
phase: quick-261022-t2l
plan: 01
subsystem: docs, decisions, gate tests
tags: [decisions, D055, D079, D080, D081, D082, D083, owner-instruction]
requires: []
provides:
  - "docs/DECISIONS.md rows D079-D083 and the D055 pointer"
  - "EXECUTION_SPEC section 6.3 and GLOSSARY section 11.7"
affects: [phase-20, phase-24, phase-25, phase-26]
key-files:
  created: []
  modified:
    - docs/DECISIONS.md
    - docs/DOC_STATUS.md
    - AGENTS.md
    - docs/trading/EXECUTION_SPEC.md
    - docs/GLOSSARY.md
    - docs/operations/RUNBOOK.md
    - .planning/ROADMAP.md
    - .planning/REQUIREMENTS.md
    - .planning/phases/19-execution-plan-binding-price-check/19-OWNER-GAPS.md
    - .planning/phases/20-reconcile-safe-mode-hardening/20-DEFERRED.md
    - tests/test_phase18_gate.py
    - tests/test_phase19_gate.py
    - tests/test_phase20_gate.py
    - tests/test_transitions.py
decisions:
  - "D079 closure of D055 (model (a)), D080 Q5, D081 Q3/Q4, D082 O-D symbol ownership, D083 -1003 ban end exception to D-10, all Accepted 2026-10-22 on the owner instruction adopting the assistant's recommendation"
metrics:
  duration: "about 40 minutes"
  completed: 2026-10-22
status: complete
plan_head_before: 2e7b56e5ad89504ae599123cbc79951ad7283ca5
plan_head_after: 6c6304485affa618e92fc61138ecf79edf1175c1
commits: 3
actuals:
  tokens: 60000
  tasks: 3
  commits: 3
---

# Quick 261022-t2l: D079-D083 recorded, documents that waited for D055 updated

The owner decisions of 2026-10-22 ("lam 1 va 2 truoc di", adopting the assistant's recommendation) are recorded as DECISIONS rows D079 to D083, and the ROADMAP, REQUIREMENTS, registers, EXECUTION_SPEC and GLOSSARY that waited for D055 now follow them. Docs and gate tests only: no `src/`, no `config/`, no network, no Binance call, no full suite run. Live placement stays disabled.

## Commits

| Task | Commit | Content |
| ---- | ------ | ------- |
| 1 | `fd9a5f1c` | DECISIONS D079-D083 and the D055 pointer, DOC_STATUS lines, four draft headers, AGENTS.md, Phase 18/19/20 D055 gate tests |
| 2 | `e762b562` | ROADMAP notes, REQUIREMENTS EXEC-01 note, owner-gap register, Phase 20 deferred register, roadmap and owner-gap pins |
| 3 | `6c630448` | EXECUTION_SPEC 6.3 (and notes in 1, 6.2, 8), GLOSSARY 11.7, transition parity test, register bullets, D079 DOC_STATUS line, one RUNBOOK sentence |

## Tests

- Baseline at HEAD before the work: `tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_transitions.py tests/test_sources_phase18_section.py` gave 160 passed.
- Final, same command: 161 passed (the extra test is the PROTECTION parametrization of the GLOSSARY parity test). Task 1 line plus `test_binance_limits_ratified_file.py` and `test_agents_md.py`: 182 passed. Task 3 line (adds test_protection_transitions, test_algo_status, the decision-alignment tests): 429 passed with the ratified-file and agents tests.
- `uv run ruff check`, `ruff format --check` on every touched test file, and `scripts/verify_decision_alignment.py all` (ALL_PASS) were green after every task. Line-ending checks: no bare LF in any CRLF file; `tests/test_phase20_gate.py` and `20-DEC-SYMBOL-OWNERSHIP-DRAFT.md` stay LF; `19-OWNER-GAPS.md` is still ASCII.

## Pins moved on purpose

| Test | Move | Why |
| ---- | ---- | --- |
| `test_phase18_gate::test_invariant_8_d055_stays_open` | D055 row must keep "the execution model stays OPEN" (2026-10-07 text) AND contain "the execution model is decided by D079"; exactly one D079 row naming D055; Phase 18 row block unchanged (still OPEN, no closure claim) | D055 row is append-only and now points to D079 |
| `test_phase19_gate::test_invariant_8_...` | D055 row has OPEN and "decided by D079"; D079 row has the item-6 wording, `48a26473`, "the system does not rely on it", `NOT_CONFIGURED`; D080 row names the Q5 draft | pins the new rows |
| `test_phase20_gate::test_invariant_6_...` | rows after D078 equal D079..D083, each "2026-10-22, owner instruction"; D055 names D079 | was "last row is D078" |
| `test_phase19_gate` owner-gap test | `OPEN_OWNER_ITEMS` loses O-01, Q3, Q4; new `DECIDED_OWNER_ITEMS` (O-01 D079, Q3 D081, Q4 D081, Q5 D080); Q3 and Q5 rows also say OPEN; DRAFT no longer required for Q5 | rows are DECIDED now |
| `test_phase19_gate` roadmap pin | baseline fffdb6e plus exactly the two `D079_CRITERIA_NOTES` (criteria 1 and 3), normalized for CRLF | only allowed change |
| `test_transitions` | `GLOSSARY_DEFERRED_KINDS` empty, `SECTION_11_TITLES` gains 11.7, `..._has_the_six_subsections` renamed `..._has_the_seven_subsections` | GLOSSARY 11.7 added; no other file referenced the old name |

## Facts found while planning (F1, F2) and how they were recorded

- **F1 (verified in code).** The brief said D081 is "policy only, not built". The code says Q4 is built as a library by plan 20-14 (migration `0008_pending_protective_actions`, `src/execution/pending_actions.py`) and Q3 by plan 20-18 (migration `0009_validated_lot_filters`, `src/execution/lot_filter_source.py`), both tested with fakes and wired into no running process (Phase 24). Only the maximum age of the stale lot filters is not built: `lot_filter_source.py` applies no age bound and `config/execution/execution-limits-v1.toml` has no key for it. D081 states this as "Build status (read from the code on 2026-10-22, not part of the owner text)". The same is in the Q3/Q4 rows of `19-OWNER-GAPS.md`.
- **F2.** Draft D055 item 3 names `binance-limits-v1.toml`; the two deadlines are `protection.max_unprotected_ms` and `protection.entry_terminal_timeout_ms` in `config/execution/execution-limits-v1.toml`. Item 3 is copied unchanged; D079 adds a labelled "File note (not part of the owner text)".

## Check-only results

- ROADMAP Phase 20 criterion 2: not edited (already reworded by plan 20-26, O-A). Phase 20 criteria untouched; the `[D055]` inherited item got an update line.
- REQUIREMENTS RISK-03: read, not edited (no sentence calls the model open or names an entry-time stop). EXEC-01 got the D079 note and stays Pending.
- EXECUTION_SPEC section 9: read, not edited (it already says the stop is placed after the fill).
- RUNBOOK: section 3 read, not edited. Section 21's status sentence (line 917) said "D055 stays open"; that is a sentence saying the model is open, so it was changed to "the execution model is decided by D079 (2026-10-22)". This is the seventh file of commit 3 (the plan allowed it) and is listed in the D079 DOC_STATUS line.

## Deviations from Plan

- **[Rule 1 - stale statement] RUNBOOK section 21** status sentence fixed as described above; no other deviation. The plan's `AGENTS.md` instruction ("keep three lines") was kept by wrapping the first line at 101 characters (neighbouring lines are up to about 101).
- The GLOSSARY 11.7 "State meanings" bullets are built only from the `ProtectionState` docstring and the comments beside it in `src/execution/protection.py`; that docstring describes edges rather than definitions, so some bullets are edge descriptions and the intro says so.
- No pipe character had to be escaped in any new DECISIONS row (the drafts contain none).

## Left for the owner

1. **D081 Q3 tier order.** The owner text names the plan-time snapshot; the plan 20-18 build tries live read, then the last validated stored filters, then the plan snapshot. The missing maximum-age key (`NOT_CONFIGURED`, not even present in the limits file) means no age bound is applied today.
2. **ROADMAP Phase 19 criterion 2**: "GTD is used as the exchange-side expiry backstop" conflicts with the D079 sentence that a GTD expiry is not confirmed on Demo and the system does not rely on it. Not edited.
3. **ROADMAP Phase 19 criterion 4**: the single-TP fallback is O-03, not edited.
4. **REQUIREMENTS EXEC-01**: "supports both position modes" conflicts with D079 item 4 (Hedge Mode unsupported in V1). Not edited.
5. **ROADMAP Phase 24 and Phase 25 `[D055]` items** and the Phase 18 lines: not edited.
6. **Plan 20-10 (O-F, D-11)**: whether it already answers the 3-day not-found part of D080 item (4) was not checked; D080 leaves item (4) open (O-04).
7. **`.planning/STATE.md`** still calls D055 OPEN (line ~639) and was not touched (left to the orchestrator).
8. **Stale text outside this plan's scope** (not edited): the docstring of `src/domain/transitions.py` still says the PROTECTION GLOSSARY block "waits for the owner's acceptance of the D055 closure draft"; the D078 row of DECISIONS says "D055 stays OPEN; the rows for D-10 and Q5 are still drafts"; RUNBOOK section 21 says "nothing was observed against Binance Demo" although Demo runs happened on 2026-10-22; D083 items remain unbuilt (Phase 24).

## Known Stubs

None.

## Threat Flags

None. No network endpoint, auth path or schema changed; nothing enables live placement.

## Self-Check: PASSED

- Commits `fd9a5f1c`, `e762b562`, `6c630448` exist in `develop` history (`git log`); `git rev-list --count 2e7b56e5..HEAD` is 3.
- `grep` of `docs/DECISIONS.md`: rows D079-D083 are the last five lines; D055 line carries "the execution model is decided by D079"; the four drafts say "ACCEPTED as D0xx"; EXECUTION_SPEC `### 6.3` and GLOSSARY `### 11.7` exist.
- `git status` still shows only the pre-existing `.planning/state.json`, `.gsd/`, `.planning/milestone.lock`, `package.json`, `package-lock.json`.
