---
phase: 15-strategy-geometry-correction
plan: 14
subsystem: docs
tags: [family-sheets, glossary, configuration, d054, f-113, doc-tests]

requires:
  - phase: 15-strategy-geometry-correction
    provides: "15-08 ratified baseline-v6 sets, 15-09 -v4 baselines, GEOMETRY_AUDIT.md rows and flags"
provides:
  - "Implemented as (Phase 15, D054) records in the three family sheets (section 3.2), with each kept deviation and a pointer to D054 and GEOMETRY_AUDIT.md"
  - "Stage-baseline acceptance lines of the three sheets corrected to AS RECORDED (baseline-v6, deviations in D054); Status and variant lines unchanged"
  - "GLOSSARY section 9 prose: Phase 15 planner meanings of STOP_TOO_TIGHT, INVALIDATED, RR_TOO_LOW (enum block untouched)"
  - "CONFIGURATION section 10: Phase 15 geometry key table and the current sets baseline-v6 / baseline-no-trade-v4 / baseline-simple-trend-v4 at v5.0.0"
  - "Doc tests in tests/test_geometry_audit_doc.py for the three sheets, the glossary and the configuration"
affects: [15-15]

actuals:
  tokens: 11500
  tasks: 2
  commits: 2
plan_head_before: 13237df54ef2808ece09987b8e187556d77b30bd
plan_head_after: 850bf165f65469078dc14b84f23490c222922f71

key-files:
  modified:
    - docs/research/families/trend-pullback.md
    - docs/research/families/breakout-retest.md
    - docs/research/families/range-mr.md
    - docs/GLOSSARY.md
    - docs/configuration/CONFIGURATION.md
    - tests/test_geometry_audit_doc.py

key-decisions:
  - "The implemented-as record sits in a new subsection '### 3.2 Implemented as (Phase 15, D054)' (level 3, so the 7-slot heading scan of analytics_files is unaffected)"
  - "Wording follows the code and the ratified values by name; no new number, and no value is claimed to be evidence-backed (PLACEHOLDER labels are stated)"
  - "Family B breakout_confirmation_bars 1 is recorded as equal to sheet B1 (the ratified value), and the legacy value 3 is stated as not used by the set"

requirements-completed: [STRAT-01, STRAT-02]

duration: ~25min
completed: 2026-10-06
status: complete
---

# Phase 15 Plan 14: family sheet implemented-as records, glossary and configuration Summary

**Each family sheet now states exactly what baseline-v6 implements (regime, level/zone, entry, stop, target) and every kept deviation from its Stage baseline with a pointer to D054 and the geometry audit; the glossary and configuration reference describe the planner reason-code meanings and the Phase 15 registry keys. All sheets stay HYPOTHESIS / NOT FROZEN.**

## Accomplishments

- Task 1 (tracer): `docs/research/families/trend-pullback.md` gained section 3.2 "Implemented as (Phase 15, D054)": baseline-v6, strategy_version v5.0.0, geometry_version 1; EMA50(4H) regime proxy (deviation from R1); confirmed-pivot level with the evaluated bar never part of it; single pivot zone (deviation from merged zones); E2 entry; stop beyond the outer edge of the whole entry zone by `sl_buffer_atr` x ATR (reading of S2) with the shared invariants and `min_stop_atr`; TP1 the opposite confirmed pivot and TP2 entry +/- 2 x leg (deviation from T1, CR-03). Acceptance line now reads "Stage A baseline implemented: `AS RECORDED` (baseline-v6, deviations in D054)"; the variants line is still `NO`. The doc test (Status NOT FROZEN, Implemented-as heading, baseline line tokens, variants line ends in `NO`, plus negative cases for a frozen status, a missing record, a reverted baseline line and a flipped variants line) passed together with `tests/test_analytics_files.py` and `tests/test_kill_gate_families.py` before expansion (tracer gate, commit 911ee66).
- Task 2: the same section for `breakout-retest.md` (EMA50 proxy with the with-direction gate; breakout_confirmation_bars 1 equals B1; retest band rule as a deviation from R1, first retest must be the evaluated bar; S3 stop on the narrow S/R zone per D-23; measured-move TP1 as a deviation from T1) and `range-mr.md` (regime on confirmed 4H pivots inside `regime_filter_lookback`, recorded as an approximation of the sheet's binding rule 2; range edges and touches as implemented; S3 stop on the narrow zone; TP1 range midpoint via `tp_mode` T_MID, T-opposite kept as the named variant). Both Stage-baseline lines now read `AS RECORDED` with baseline-v6 and D054; variants lines unchanged.
- `docs/GLOSSARY.md` section 9: one added prose paragraph (Phase 15 planner meanings, D054, D-27) for STOP_TOO_TIGHT (stop not strictly outside the whole entry zone, or closer than `min_stop_atr` x ATR), INVALIDATED (signal bar already through the planned stop) and RR_TOO_LOW (TP1 not on the profit side, checked before the threshold). The 9.1 enum block and every member count are untouched (the diff adds two lines only; a test counts the 20 block members).
- `docs/configuration/CONFIGURATION.md` section 10: the "current sets" bullet now names baseline-v6 (three families), baseline-no-trade-v4 and baseline-simple-trend-v4 at v5.0.0 (older sets unchanged and hash-locked), and a "Phase 15 geometry keys (D054)" table covers pivot_left_bars, pivot_right_bars, geometry_version, tp_mode and min_stop_atr with type, unit, constraint (matching `src/domain/registry.py`) and the reading family, plus the no-reuse and legacy-absent bullets.
- F9: `docs/research/kill_gate_decisions.json` lists no families, so no CANDIDATE evidence existed when the sheets were edited.

## Regeneration inventory

Sheet digests as computed by `src/adapters/analytics_files.py::_sheet_facts` (sha256 of the LF-normalized bytes), before and after this plan (D054, F9). No committed fixture or pin depends on them (`tests/test_analytics_files.py` and `tests/test_kill_gate_families.py` pass unchanged).

| sheet | sha256 before | sha256 after |
|---|---|---|
| trend-pullback | 698017c33d4d8f7bbd59cc344e5e13228d69f34e348edb2b294c9989ca01f672 | fda8afd557ccd69037302881ab788d89454567c60cd07d38c20db6249491ef7b |
| breakout-retest | d1dffc4724983865038f0389fa15bbb396eb9cbce54560e6481d8952d5319273 | 001a3f5dc4b945bfb818665f00686ae5be0bbe170e9dfc30e3565fee01dbdc0d |
| range-mr | 77270d282058362d9d208eabd7b06d72fb8102f0ae6e15f690393371b5c2fcf1 | 32cea773c08ce924c9da8b3063b5f907c45c9ac3d301ad372cb8cfaa45821a93 |

## Deviations from Plan

None - plan executed exactly as written.

Notes (not deviations):

- D054 does not exist in `docs/DECISIONS.md` until plan 15-15; the sheets, glossary and configuration name it as the entry that records the deviations, as the plan and 15-08 do.
- The paragraph is a `###` subsection (3.2) rather than loose text after the section 3 table; the plan allowed "a paragraph headed".
- Sheet and doc files are CRLF in the working tree (git blobs are LF); edits preserved CRLF.

## Verification

- `pytest tests/test_geometry_audit_doc.py tests/test_decision_alignment_ops_risk.py tests/test_decision_alignment_bookkeeping.py tests/test_decision_alignment_authority.py tests/test_decision_alignment_exchange.py tests/test_domain_enums.py tests/test_analytics_files.py tests/test_kill_gate_families.py`: all pass (one skipped test is pre-existing). Also `tests/test_decision_alignment.py tests/test_rationale.py`: pass.
- `python -m scripts.decision_alignment.{ops_risk,bookkeeping,authority,exchange,params,protocol,universe}`: no FAIL (OR-10a, GL gates included).
- `ruff check`: clean; `ruff format --check`: 427 files formatted; `mypy src`: no issues in 149 files.
- Targeted suites only, foreground; no background process left.

## Known Stubs

None.

## Threat Flags

None. T-15-24 mitigated: the doc tests require Status NOT FROZEN, an Implemented-as heading and the acceptance line naming baseline-v6 and D054 for all three sheets; the sheets were edited while no CANDIDATE evidence exists. T-15-SC accepted (no installs).

## Self-Check: PASSED

- FOUND: the six modified files; commits 911ee66 and 850bf16
- FOUND: "Implemented as (Phase 15, D054)" in all three sheets, "Phase 15 geometry keys (D054)" in CONFIGURATION, "min_stop_atr" in GLOSSARY
