---
phase: 11-decision-alignment
plan: 03
subsystem: research-universe
tags: [d039, universe, manifest, survivorship-bias, sha256, gate-module]
status: complete

requires:
  - phase: 11-decision-alignment
    provides: plans 11-01/11-02 gate-module pattern (scripts/decision_alignment)
provides:
  - DRAFT point-in-time research-universe manifest (docs/research/universe/research-universe-v1.toml), 12 slots, no symbols
  - scripts/decision_alignment/universe.py with validate_manifest, compute_content_sha256, run() gates UN-01..UN-05 and a hash CLI
  - Phase 13 freeze procedure documented in manifest header and module docstring
affects: [13-dataset-backfill, 11-08]

actuals:
  tokens: 9000
  tasks: 2
  commits: 2
plan_head_before: 32b1e53f8e70ca11c4c9a15ffeae715d8fab1f34
plan_head_after: 214dffefbf63cfdda1691d53f7462c2ccf3bd771

tech-stack:
  added: []
  patterns:
    - "DRAFT/FROZEN manifest states with a canonical-payload hash (sha256_hex over sorted symbols), excluding status and the stored hash"
    - "Manifest kept under docs/research/universe, never under params/, so family scanners cannot see it"

key-files:
  created:
    - docs/research/universe/research-universe-v1.toml
    - scripts/decision_alignment/universe.py
    - tests/test_decision_alignment_universe.py
  modified: []

key-decisions:
  - "Manifest is DRAFT with no symbols and no selection date: ranking needs the Phase 13 volume data, anything earlier would be hand-picking (D-09)"
  - "Hash payload = schema, universe_id, contract_type, quote_asset, rank_metric, rank_date_source, top_n, include_delisted, selection_date, sorted symbols; DRAFT to FROZEN is a metadata flip plus the stored hash"
  - "Any change to these keys after a freeze requires research-universe-v2"

requirements-completed: [RSCH-01, RSCH-02]

coverage:
  - id: D1
    description: "DRAFT manifest with D039 rule and 12 slots validates; gates UN-01..UN-05 ok"
    requirement: "RSCH-01"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_universe.py::test_real_manifest_validates_with_zero_problems, test_run_gates_un01_to_un05_all_ok"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every malformed DRAFT/FROZEN variant rejected; hash order-independent and payload-sensitive"
    requirement: "RSCH-02"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_universe.py (rejection and hash tests)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Manifest invisible to family scanners and research-gate tripwires; params/universe absent; CLI exit codes"
    requirement: "RSCH-02"
    verification:
      - kind: unit
        ref: "tests/test_decision_alignment_universe.py::test_manifest_is_invisible_to_research_gate_and_family_scanners, CLI tests; tests/test_kill_gate_registration.py, tests/test_analytics_files.py green"
        status: pass
    human_judgment: false
---

# Phase 11 Plan 03: Point-in-time Research Universe Manifest Summary

**A machine-validated DRAFT research-universe manifest (D039) records the rule and 12 slots with no symbols, and a validator/hasher module with a CLI lets Phase 13 freeze it deterministically.**

## Performance

- **Completed:** 2026-09-30
- **Tasks:** 2 (1 tracer, 1 auto/tdd)
- **Files:** 3 created, none modified

## Accomplishments

- `docs/research/universe/research-universe-v1.toml`: schema `research-universe/1`, status DRAFT, top_n 12, PERPETUAL/USDT, rank metric trailing 30d mean daily quote volume, include_delisted true, empty symbols/selection_date/content_sha256, freeze_owner Phase 13, live-5 separation note. Header carries the five-step freeze procedure.
- `scripts/decision_alignment/universe.py`: `validate_manifest` (DRAFT forbids any symbol/date/hash; FROZEN requires 10-15 unique uppercase USDT symbols equal to top_n, ISO date, matching hash), `compute_content_sha256` via `src.domain.canonical.sha256_hex`, `run()` gates UN-01..UN-05, CLI printing the hash (exit 2 no argument, 1 missing path).
- 46 tests: real manifest, every rejection, order-independent hash and payload sensitivity, CLI, repo-safety.
- Current DRAFT hash printed by the CLI is `6eca69f0...11b8` (informational only; DRAFT carries no stored hash).

## Task Commits

1. Task 1 (tracer): `7d168b4` - manifest, validator, gates, rejection tests
2. Task 2: `214dffe` - hash/CLI/repo-safety tests (module docstring "Phase 13 handoff" and `main` were already delivered in Task 1)

## Verification

- `pytest tests/test_decision_alignment_universe.py tests/test_kill_gate_registration.py tests/test_analytics_files.py -q -p no:cacheprovider`: all pass (one pre-existing symlink skip in test_analytics_files); universe tests: 46 passed, also under `-W error`.
- CLI on the manifest: one 64-hex line, exit 0.
- `ruff check` and `mypy` on the module: clean.

## Deviations from Plan

### Ordering notes

**1. [Ordering] Task 2 CLI/hash tests were not RED**
- The CLI `main` and the exact hash payload were implemented in Task 1 (the Task 1 action already required the `__main__` hash entry), so the Task 2 CLI and sensitivity tests passed on first run. Task 1 RED was confirmed (ImportError before the module existed).

**Total deviations:** 0 auto-fixes, 1 ordering note. **Impact:** none on scope or outputs.

## Issues Encountered

None. No src/ or params/ files changed.

## Known Stubs

None. The empty `symbols` list is the intentional DRAFT state; Phase 13 owns the freeze.

## Threat Flags

None. T-11-08 (hand-picking/tamper) mitigated by DRAFT symbol ban, FROZEN hash check and freeze-before-evaluation; T-11-09 (misread as strategy family) mitigated by path, UN-03 and the safety test.

## Next Phase Readiness

Ready for 11-04. Phase 13 must run the five freeze steps and commit before any evaluation; protocol section 1 and BACKTEST_SPEC section 10.1 should reference the manifest (belongs to a later Phase 11 docs plan).

## Self-Check: PASSED

Manifest, module and test files exist; commits 7d168b4 and 214dffe found in git log; verify commands re-run green.
