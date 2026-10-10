---
phase: 16-paper-runtime-composition
plan: 22
subsystem: paper-runtime / start gate / epoch pin / runtime configuration
tags: [paper-runtime, start-gate, allowlist, exact-hash, q-a, epoch-pin, exit-codes, hold-on-refusal, runtime-config]

requires:
  - phase: 16-paper-runtime-composition
    provides: "16-09: allowlist_entries / find_allowlist_entry accessors and the SKIPPED freeze line; 16-16: RuntimeStatePort, RuntimeRecord, PgRuntimeState; 16-15: HealthThresholds; 16-08: RuntimeEventType including EPOCH_PINNED"
provides:
  - "python -m src.paper.runtime: trade-key refusal, empty-allowlist SKIPPED, strict exact-hash admission for every set (Q-A), runtime configuration, operator-only epoch pin, RUNTIME_START/STOP"
  - "src/paper/runtime_config.py: ALLOWED_ENV_NAMES, ExitCode and REFUSAL_CODES, refuse_trade_capable_env, read_env, RuntimeConfig and load_runtime_config (every key required, no default)"
  - "--hold-on-refusal: a refusal logs and stays up until SIGTERM or SIGINT, then returns its code (restart-loop guard for plan 16-32)"
  - "config/paper/README.md: required keys, units and owning decisions, no values; the two gate layers; restartable codes"
  - "decisions/16-DEC-Q-A.md: option runtime-exact-hash-all, decided by user"
affects: [16-26 live loop (run_loop seam), 16-27 and 16-34 README key parsers, 16-32 compose command, 16-43 real start]

actuals:
  tokens: 15000
  tasks: 3
  commits: 6
plan_head_before: 577767b
plan_head_after: 21081d3c39df6370f5bdd638f0d47b9e7cf7e81d
commits: 6

tech-stack:
  added: []
  patterns:
    - "Two deliberately different gate layers over one allowlist: the runtime process gate (exact hash for every set) and the unchanged per-call rule inside pin_stream_epoch"
    - "Test and composition seams as keyword parameters of main (environ, state, registry_root, clock, run_loop, wait_for_stop); production passes none"
    - "Named ExitCode table whose refusal codes are disjoint from the restartable statuses; a refusal can be held instead of exited"

key-files:
  created:
    - src/paper/runtime.py
    - src/paper/runtime_config.py
    - config/paper/README.md
    - tests/test_paper_runtime_compose.py
    - tests/test_paper_runtime_env.py
    - tests/test_paper_runtime_admission.py
    - .planning/phases/16-paper-runtime-composition/decisions/16-DEC-Q-A.md
  modified:
    - docs/GLOSSARY.md

key-decisions:
  - "Q-A (user): the runtime gate requires an exact-hash allowlist entry for EVERY parameter set, rationalized or not; pin_stream_epoch, freeze.py and the Phase 15 tests are unchanged; the allowlist stays empty"
  - "Admission runs before the runtime configuration and the epoch; a hash match only lets pin_stream_epoch's full validation continue (PLACEHOLDER keys and incomplete rationale still refuse, exit 6)"
  - "EPOCH_PINNED is recorded before the pinned-state file is written, so a failed write leaves an orphan record of an unused epoch instead of a trial with no pin record"
  - "A restart loads the stored epoch and compares strategy id, parameter set id and hash with the admitted entry (exit 6 on any difference); --pin-epoch while a pinned state exists exits 6 (REV-18)"
  - "Timing integers are strictly positive except minute_close_lag_seconds, which may be zero; money and rates are TOML strings parsed to Decimal (a TOML float is refused)"

requirements-completed: [PAPER-01]

coverage:
  - id: D1
    description: "An empty allowlist exits 0 with 'SKIPPED (allowlist empty)' after the trade-key refusal and before any adapter, engine or Telegram application is constructed, with no fallback to any set"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_compose.py#test_empty_allowlist_exits_zero_skipped_and_builds_nothing"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_admission.py#test_empty_allowlist_skips_without_a_fallback_set"
        status: pass
    human_judgment: false
  - id: D2
    description: "Any BINANCE_* variable (even empty) exits 3 with names only, before the allowlist is read; only ALLOWED_ENV_NAMES are read"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_env.py#test_any_binance_variable_refuses_with_code_3_names_only_before_the_allowlist"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_env.py#test_read_env_keeps_only_allowed_names"
        status: pass
    human_judgment: false
  - id: D3
    description: "Q-A runtime-exact-hash-all: a rationalized-but-unauthorized set and a hash mismatch are refused (6) before pin_stream_epoch; an exact match proceeds; the full validation still runs after authorization; every entry path passes the gate first"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_admission.py#test_rationalized_but_unauthorized_set_is_refused_before_the_pin"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_admission.py#test_hash_mismatch_is_refused_before_the_pin"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_admission.py#test_exact_hash_match_proceeds_to_the_pin"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_admission.py#test_authorization_does_not_replace_the_full_validation"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_admission.py#test_gate_runs_first_on_every_entry_path"
        status: pass
    human_judgment: false
  - id: D4
    description: "The epoch is pinned only on --pin-epoch with no pinned state; a restart reuses the stored epoch and never pins; mismatches exit 6; no pin and no flag exits 5; RUNTIME_START on every start, RUNTIME_STOP only on a clean stop"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_admission.py#test_pin_epoch_pins_once_writes_the_file_and_records_both_events"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_admission.py#test_restart_reuses_the_pinned_epoch_and_never_pins_again"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_admission.py#test_pinned_state_that_differs_from_the_admitted_entry_exits_6"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_admission.py#test_clean_shutdown_records_runtime_stop_and_leaves_the_pinned_state_alone"
        status: pass
    human_judgment: false
  - id: D5
    description: "Every runtime configuration key is required (exit 4 naming the key), no numeric default exists in code, and the README lists the keys, the grace wording and the two gate layers"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_admission.py#test_every_missing_key_exits_4_and_names_the_key"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_admission.py#test_no_numeric_default_for_any_configuration_key"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_admission.py#test_readme_distinguishes_the_two_gate_layers_and_the_restartable_codes"
        status: pass
    human_judgment: false
  - id: D6
    description: "The named ExitCode table and --hold-on-refusal keep a refusal from looping under a restart policy"
    requirement: PAPER-01
    verification:
      - kind: unit
        ref: "tests/test_paper_runtime_compose.py#test_exit_code_table_is_exactly_the_documented_one"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_compose.py#test_hold_on_refusal_holds_until_the_stop_then_returns_the_refusal_code"
        status: pass
      - kind: unit
        ref: "tests/test_paper_runtime_compose.py#test_skipped_never_holds_even_with_the_flag"
        status: pass
    human_judgment: false
  - id: D7
    description: "Real start of the paper process against PostgreSQL and the live feed (not exercised here; fake-level green never closes PAPER-01, SC9)"
    requirement: PAPER-01
    verification: []
    human_judgment: true
    rationale: "The live loop is plan 16-26 and the real start is plan 16-43; this plan proves the gate, pin and configuration with in-memory state only"
---

# Phase 16 Plan 22: Paper Runtime Entrypoint Summary

**`python -m src.paper.runtime` now fails closed in order: any `BINANCE_*` name exits 3, an empty allowlist exits 0 as SKIPPED, a missing or different exact-hash allowlist entry exits 6 for every parameter set (user decision Q-A), an unratified configuration exits 4, and an epoch is pinned only by the operator's `--pin-epoch` and reused by every restart.**

## Accomplishments

- **Tracer (Task 1):** the real entrypoint, the `ExitCode` table (0, 2, 3, 4, 5, 6, 7) with `REFUSAL_CODES` = {3, 4, 5, 6} disjoint from the crash status 1 and the restartable 7, `--hold-on-refusal`, and `read_env` limited to `ALLOWED_ENV_NAMES`.
- **Q-A recorded (Task 2):** `decisions/16-DEC-Q-A.md` holds `option: runtime-exact-hash-all`, `decided by: user`, date 2026-10-10 and the reply verbatim ("Chọn Option 1: runtime-exact-hash-all.").
- **Admission (Task 3):** the strict gate reads the allowlist only through `find_allowlist_entry`, loads the registry file's hash through `load_parameter_set_at_root` and compares it to the entry. It runs before the configuration, the epoch and any candle or strategy code. `pin_stream_epoch` is called afterwards and unchanged; a PLACEHOLDER key still refuses with exit 6 after a hash match.
- **Epoch rule:** no pinned state and no flag exits 5; `--pin-epoch` with no state pins once (EPOCH_PINNED recorded, then the file written); a restart loads the file, checks strategy id, parameter set id and hash against the admitted entry, never pins and records RUNTIME_START only; `--pin-epoch` with an existing state exits 6.
- **Configuration:** `RuntimeConfig` with the `[health]`, `[timing]`, `[account]` and `[scope]` sections; every key is required, a missing key exits 4 naming `<section>.<key>`, an AST test proves no numeric literal is bound to any key name in the runtime modules.
- **Docs:** `config/paper/README.md` lists each key (one per line, no value, unit and owning decision), carries the three `freeze_tick_grace_seconds` sentences, and separates the two gate layers; `docs/GLOSSARY.md` gained the entry "Paper-start allowlist: runtime process gate and per-call rule".

## Task Commits

1. Task 1 RED: `27a33a4` test(16-22) tracer tests
2. Task 1 GREEN: `a4d8a46` feat(16-22) tracer entrypoint, trade-key refusal, SKIPPED gate, exit-code table
3. Task 2: `fc34247` docs(16-22) Q-A decision record
4. Task 3 RED: `6eae219` test(16-22) exact-hash admission, epoch pin, required configuration
5. Task 3 GREEN: `324631b` feat(16-22) admission, pin, RUNTIME_START/STOP, RuntimeConfig, README
6. Docs: `21081d3` docs(16-22) glossary entry for the two gate layers

## Verification

- `uv run pytest -m "not docker"`: the whole suite passes except one test outside this plan (see Deferred Issues). The plan's own files pass: `tests/test_paper_runtime_compose.py`, `tests/test_paper_runtime_env.py`, `tests/test_paper_runtime_admission.py`, `tests/test_paper_start_gate.py`, `tests/test_paper_freeze.py`, `tests/test_paper_freeze_allowlist_mode.py`, `tests/test_paper_runtime_state.py`.
- `uv run ruff check` and `uv run ruff format --check`: clean. `uv run mypy src`: no issues in 171 files.
- The commands in the plan use `.venv/Scripts/python`; the worktree had no environment, so `uv sync --frozen --extra dev` was run and `uv run` used instead.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree base was stale**
- **Found during:** start
- **Issue:** the worktree sat at 9186194, which lacked `16-22-PLAN.md` and the 16-09 and 16-16 outputs this plan depends on.
- **Fix:** `git merge --ff-only develop` on the agent branch (a pure fast-forward, nothing lost); base is develop 577767b.
- **Commit:** none (fast-forward)

**2. [Rule 2 - Missing critical] Task 3 tests live in a third test file**
- **Found during:** Task 3
- **Issue:** the plan lists only `test_paper_runtime_compose.py` and `test_paper_runtime_env.py`; Task 3 needs a large registry, config and state rig and a late-import-free module header.
- **Fix:** Task 3 tests are in `tests/test_paper_runtime_admission.py`; the two planned files keep the tracer tests.
- **Files modified:** tests/test_paper_runtime_admission.py (new)
- **Commit:** 6eae219

**3. [Rule 2 - Missing critical] Seams and options not named in the plan**
- `main` gained keyword seams (`state`, `registry_root`, `clock`, `run_loop`) and the options `--pin-epoch` and `--pinned-state` (default `logs/paper/pinned_epoch.json`, as the freeze CLI uses). A missing `PAPER_STRATEGY_ID` or `PAPER_PARAMETER_SET_ID` with a non-empty allowlist exits 4. The production state port (PostgreSQL journal rows, Q-J) is built lazily from `DATABASE_URL_SYNC` or `DATABASE_URL`; absence exits 4, a persistence failure exits 7.
- **Commit:** 324631b

**4. [Scope note] `src/paper/freeze.py` left untouched, including its docstring**
- On the user's instruction the scope clarification went into docs only (README and GLOSSARY). The freeze.py module docstring and the comment above `PAPER_START_ALLOWLIST` still say the allowlist is "consulted only for sets without rationale tables"; the glossary entry states that this describes the per-call rule only.

**Total deviations:** 4 (1 blocking, 2 missing-critical, 1 scope note). **Impact:** none on the ratified decisions; no allowlist entry added, no Phase 15 behavior or test changed.

## Deferred Issues

- `tests/test_cost_parity.py::test_simulator_and_paper_call_evaluate_risk_with_identical_arguments` fails (`sim_kwargs != paper_kwargs`). It fails when run alone, imports none of the files this plan touched, and this plan only adds new modules and tests plus a glossary entry. It is the pre-existing failure plan 16-15 already logged in `deferred-items.md` (list versus tuple for `open_positions`). Not fixed here.

## Known Stubs

- `src/paper/runtime.py`, `main`: when no `run_loop` is passed, an admitted process records RUNTIME_START and then only waits for SIGTERM or SIGINT. The live loop is plan 16-26 (`run_loop` seam, `RuntimeContext`). With the allowlist empty by decision, no real start can reach this path. Not recorded in `.planning/WINDOWS.md` (`gsd_run windows append` unavailable to this executor).

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: persistence | src/paper/runtime.py | An admitted start opens a PostgreSQL engine from `DATABASE_URL_SYNC` or `DATABASE_URL` (journal rows only, Q-J). Not in the plan's threat register; the URL is read from the allowed-name set and never logged, and any failure exits 7 (fail closed, no in-memory fallback). |

Threat register: T-16-50 (trade-key refusal first, names only), T-16-51 (start gate through the freeze accessors, empty allowlist SKIPPED, strict rule per Q-A), T-16-52 (every key required, AST test, exit 4) and T-16-110 (named ExitCode table, `--hold-on-refusal`) are mitigated as planned.

## Next

Plan 16-26 supplies the live loop through the `run_loop` seam; plan 16-32 passes `--hold-on-refusal` in the compose command; plan 16-34 writes `config/paper/paper-runtime-v1.toml` from the user's answers; the real start is plan 16-43. PAPER-01 is not closed by this plan (SC9).

## Self-Check: PASSED

All created files exist; commits 27a33a4, a4d8a46, fc34247, 6eae219, 324631b and 21081d3 are in the branch history; the plan's tests, ruff and mypy pass.
