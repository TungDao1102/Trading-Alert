---
phase: 16-paper-runtime-composition
plan: 13
subsystem: research candidate registration validator (read-only)
status: complete
tags: [candidate-freeze, registry, rationale, pin-file, grid, d-28, l-03, l-10, p22]

requires:
  - phase: 16-paper-runtime-composition
    provides: "16-06 ParameterGrid, GridPoint, load_grid (src/research/manifest.py)"
provides:
  - "src/research/register.py: validate_candidate, CandidateCheck, list_grid, GridListing, main (python -m src.research.register)"
affects: [16-45 registers the approved grid (each point checked with --check), 16-48 records the user-designated candidate and prints the hash the user authorizes (O-04, 16-42)]

requirements-completed: [BKTS-03]

actuals:
  tokens: 6800
  tasks: 2
  commits: 4
plan_head_before: 126aa5a33a593b1943bccd1db3c32c4e8ccefc48
plan_head_after: eaf2f553748c61d56691a5b810747c8e3264aab8
commits: 4

tech-stack:
  added: []
  patterns:
    - "Single read of the candidate file: hash, rationale verdict and placeholder verdict all derive from the same bytes"
    - "Refusals are named reason codes; every loader exception becomes a reason, never a crash; the hash is printed only on VALID"
    - "Listing order is the grid file's own order; the listing carries structure verdicts only"

key-files:
  created:
    - src/research/register.py
    - tests/test_research_register.py
  modified: []

key-decisions:
  - "The hash is printed only for a VALID candidate (and the INVALID output holds no 64-hex value), so the user cannot be shown a hash to authorize that failed a check"
  - "--list-grid structure verdict = loads through the registry parse path, complete rationale table, file hash equal to the hash listed in the grid. PLACEHOLDER and pin checks belong to --check only"
  - "The no-write scan flags replace/remove/copy/move only on os and shutil bases, so str.replace used to strip paths from messages is not a false positive"

patterns-established:
  - "AST no-write scan with a seeded-violation negative control, plus a source check that the module names neither the paper-start policy list nor the holdout marker"

coverage:
  - id: D1
    description: "A rationalized, PLACEHOLDER-free set that equals one grid point and has a matching pin entry is VALID, exit 0, and prints parameter_set_hash=<64 hex> equal to the loader hash; every file is byte-identical afterwards"
    requirement: BKTS-03
    verification:
      - kind: unit
        ref: "tests/test_research_register.py#test_valid_candidate_is_valid_and_prints_the_loader_hash"
        status: pass
      - kind: unit
        ref: "tests/test_research_register.py#test_the_check_leaves_every_file_byte_identical"
        status: pass
    human_judgment: false
  - id: D2
    description: "Missing rationale, a value without a provenance label, PLACEHOLDER, non-grid-point (absent or hash-differing), missing pin entry, pin hash mismatch, a file outside the registry family layout and a structurally invalid set are each INVALID with their own reason code and exit 1 with no hash printed; the committed baseline-v6 sets are INVALID for PLACEHOLDER and stay byte-identical"
    requirement: BKTS-03
    verification:
      - kind: unit
        ref: "tests/test_research_register.py#test_placeholder_label_is_refused"
        status: pass
      - kind: unit
        ref: "tests/test_research_register.py#test_every_refusal_exits_one_and_prints_no_hash"
        status: pass
      - kind: unit
        ref: "tests/test_research_register.py#test_committed_baseline_v6_sets_are_invalid_for_placeholder"
        status: pass
    human_judgment: false
  - id: D3
    description: "--list-grid prints one line per grid point in the grid file's own order with a structure verdict and reason only; no ranking vocabulary; the module cannot write (AST scan with negative control) and does not name the paper-start policy list"
    requirement: BKTS-03
    verification:
      - kind: unit
        ref: "tests/test_research_register.py#test_list_grid_follows_the_file_order_with_structure_only"
        status: pass
      - kind: unit
        ref: "tests/test_research_register.py#test_register_source_has_no_write_call_and_does_not_name_the_allowlist"
        status: pass
      - kind: unit
        ref: "tests/test_research_register.py#test_write_scan_catches_seeded_violations"
        status: pass
    human_judgment: false

duration: not measured (single session)
completed: 2026-10-09
---

# Phase 16 Plan 13: Candidate-registration validator Summary

`python -m src.research.register --check <toml> --grid <grid>` is one read-only machine check that reports VALID only for a structurally valid, fully rationalized, PLACEHOLDER-free set that equals exactly one preregistered grid point and has a matching pin entry, and then prints the exact 64-hex `parameter_set_hash` the user authorizes; `--list-grid` lists the grid in file order with structure verdicts only.

## Accomplishments

- Tracer (Task 1): `validate_candidate(toml_path, *, grid_path, pin_path, registry_root) -> CandidateCheck` and the `--check` CLI (exit 0 on VALID, 1 on INVALID). Hash, rationale and PLACEHOLDER verdicts come from one read of the file, using the same registry parse path as `freeze` (`_parameter_set_from_text`), `check_rationale_text` and `placeholder_keys_text`.
- Refusal reason codes (Task 2): `STRUCTURALLY_INVALID`, `RATIONALE_INCOMPLETE`, `PLACEHOLDER`, `NOT_A_GRID_POINT`, `NO_PIN_ENTRY`, `PIN_HASH_MISMATCH`, `OUTSIDE_REGISTRY`. All applicable reasons are reported together; the INVALID output carries no 64-hex value.
- `list_grid(grid_path, *, registry_root)` and `--list-grid`: one line per point, `<parameter_set_id> STRUCTURALLY_VALID|STRUCTURALLY_INVALID[: reason]`, in the grid file's own order. No index, count, metric or rank is printed.
- The committed baseline-v6 sets for the three families are reported INVALID with reason PLACEHOLDER, and their files and the pin file are unchanged by the run.
- AST scan proves `src/research/register.py` has no write call and no mention of the paper-start policy list or the holdout marker; a seeded-violation test proves the scan fires.

## Task Commits

1. Task 1 (tracer): `03b3f36` (test, RED), `9b9a925` (feat, GREEN)
2. Task 2: `d51fb39` (test, RED), `eaf2f55` (feat, GREEN)

## Verification

- `tests/test_research_register.py`, `tests/test_registry_gate.py`, `tests/test_paper_start_gate.py`: 102 passed (the Task 2 verify command).
- Also pass: `tests/test_domain_no_float.py`, `tests/test_domain_boundary.py`, `tests/test_research_runner.py`, `tests/test_research_gate_negative.py`, `tests/test_research_feasibility.py`.
- `ruff check`, `ruff format --check` (463 files) and `mypy src` (162 files) clean.
- No network, no PostgreSQL needed.

## Deviations from Plan

None in behavior. Notes:

- `list_grid` takes `registry_root` as a keyword instead of the plan's `registry_template` parameter name, matching `validate_candidate`; the plan gave no template format.
- TDD: the Task 1 GREEN implements the complete check pipeline the Task 1 action lists, so most Task 2 refusal tests passed as soon as the file could be imported; the Task 2 RED failed at import (`list_grid` missing) and at the listing and scan tests.
- The no-write scan was narrowed after first run (str.replace in a message helper was flagged); the seeded-violation control still fires for `os.replace`.

## Known Stubs

None.

## Threat Flags

None. T-16-31: grid-point equality is required, the listing has no result field and is file-ordered, an AST test forbids writes. T-16-32: the hash comes from the registry parse path and is cross-checked against the pin file before it is printed.

## Self-Check: PASSED

Files `src/research/register.py` and `tests/test_research_register.py` exist; commits 03b3f36, 9b9a925, d51fb39 and eaf2f55 are in `git log`.
