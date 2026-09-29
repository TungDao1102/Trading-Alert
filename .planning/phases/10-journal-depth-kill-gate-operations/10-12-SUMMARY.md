---
phase: 10-journal-depth-kill-gate-operations
plan: 12
subsystem: analytics
tags: [cli, powershell-wrapper, offline-dashboard, kill-gate, record-step, edge-guards, byte-determinism, tdd, tracer]

requires:
  - phase: 10-journal-depth-kill-gate-operations
    provides: "10-09 edge adapters (load_evidence_file, load_decisions_file, load_universe_file, scan_family_facts, confine_output_dir, read_journal_events, read_live_rows, read_candles, append_kill_gate_event); 10-08 report builder; 10-11 renderer, JSON sidecar and verify_render; 10-01..10-07 normalizers and the kill-gate evaluator"
provides:
  - "src/analytics/cli.py: CliArgs, parse_args, main(argv, *, now_fn, session_factory_fn) - the single edge that loads files and optional read-only DB rows, builds the report, renders Markdown + sidecar, verifies both, and writes exactly two files under the confined reports root"
  - "scripts/dev/journal-report.ps1: thin wrapper (-AsOf -OutDir -Universe -Evidence -Decisions -RawRoot -Record -NoDb) over uv run python -m src.analytics.cli, plus its scripts/dev/README.md row"
  - "tests/test_analytics_cli.py (35 tests) and tests/test_analytics_edge_guards.py (22 tests): end-to-end, clock, confinement, secret-free output, --record idempotence, and the phase-closing edge guards"
  - "tests/test_domain_no_float.py SCANNED_FILES extended with every pure src/analytics module (24 files) and a drift guard that fails if one is missing"
affects: []

actuals:
  tokens: 17000
  tasks: 3
  commits: 6
plan_head_before: f9eafcbb21817fe4b0c7e3cd740700e04e38c874
plan_head_after: 9562bb498bec85eca51f5905e668eabb82860850

tech-stack:
  added: []
  patterns:
    - "Report path is read-only by construction: the CLI has no insert/update/delete/text/execute of its own and reaches the journal only through the two adapter functions; the one write is append_kill_gate_event, called once, after both files exist"
    - "Everything that can fail (load, build, render, verify_render against the report tree) happens before the first byte is written; a failed write removes both files of the pair"
    - "Database failures are reduced to the exception type name at a single boundary (private _DatabaseReadError/_RecordError carry only type(exc).__name__, raised from None); DATABASE_URL is read once in _database_url and handed only to the session factory"
    - "Clock discipline is AST-tested: at most one datetime.now call in cli.py and it sits in _resolve_as_of; now_fn is injectable and never called when --as-of is given"
    - "The wrapper follows the scripts/dev convention (dot-source _common.ps1, try/finally Exit-RepoRoot, array splatting, no here-strings, nothing echoed)"

key-files:
  created:
    - src/analytics/cli.py
    - scripts/dev/journal-report.ps1
    - tests/test_analytics_cli.py
    - tests/test_analytics_edge_guards.py
  modified:
    - scripts/dev/README.md
    - tests/test_domain_no_float.py

key-decisions:
  - "stdout paths are the resolved absolute paths of the two files (UI-SPEC says only '<path>'); report CONTENT still carries no path, hostname or clock beyond --as-of"
  - "A provided --as-of with a non-UTC offset is accepted and normalized to UTC; a naive or unparseable value exits 2. A clock-derived value is truncated to whole seconds before it is echoed in the header and the file stem"
  - "Without --evidence the backtest and paper kinds are empty (valid no-data blocks); --universe wins over the evidence file's research_universe; a missing raw root is not an error (the core reports NO_1M_COVERAGE, nothing is fabricated)"
  - "Live-side ledger notes: unmatched joins (per JoinAccount name) as UNMATCHED_JOIN, lifecycle and per-table row rejects and journal rejects as MALFORMED_ROW, live outcome INCOMPLETE listings per reason; candle rejects per symbol as candles:<symbol> MALFORMED_ROW"
  - "Candidate experiments that map to no family (scan_family_facts unknown_experiment_ids) are not added to the ledger: the only UNMATCHED_JOIN copy is 'rows could not be joined to a signal or order', which would mislabel them; they still fail closed if a decision names them"
  - "Resets are merged from the decisions file and reset_from_event over the journal events, de-duplicated on (occurred_at_utc, operator_id, decision_ref) and sorted; prior evaluations come only from the journal (priors_from_events)"
  - "On Windows the CLI runs its asyncio loops with SelectorEventLoop (psycopg async cannot use the default Proactor loop); the read and the record step each use their own asyncio.run and dispose the engine bound to their factory before the loop closes"
  - "Generic exceptions are deliberately not caught: only the typed input/render/OS/database failures map to exit 1, so a genuine internal bug surfaces as a traceback (exit 1, nothing written because writing is last) instead of being relabelled"

patterns-established:
  - "Test selector split: Task 1 cases avoid the substrings 'record' and 'db' in their names so -k 'not record and not db' selects exactly the file-pipeline tests (20), and the DB/record cases (15) are the complement"
  - "Fake database for CLI tests: an in-memory store behind an async session context; every executed statement is recorded so tests assert Select-only on the report path and exactly one Insert for --record; inserts honour ON CONFLICT DO NOTHING by id"

requirements-completed: [JRN-01, GOV-01]

coverage:
  - id: D1
    description: "One CLI (python -m src.analytics.cli) turns evidence/decision/universe files into a byte-identical Markdown + JSON sidecar pair with the four-line stdout contract and exit codes 0/1/2; a terminal INSUFFICIENT_EDGE exits 0 with the calm banner"
    requirement: JRN-01
    human_judgment: false
    verification:
      - kind: unit
        ref: "tests/test_analytics_cli.py#test_tracer_cli_end_to_end"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_cli.py#test_files_are_byte_identical_across_two_runs_and_names_are_stable"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_cli.py#test_terminal_state_exits_zero_with_the_calm_banner"
        status: pass
      - kind: command
        ref: "powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev/journal-report.ps1 -NoDb -AsOf 2027-04-01T00:00:00+00:00 -Evidence tests/fixtures/phase10/loaders/evidence_sample.json -OutDir data/reports/_smoke"
        status: pass
  - id: D2
    description: "Clock, confinement and failure discipline: --as-of naive/unparseable and --resamples below the minimum exit 2; the clock is read once only when --as-of is omitted; malformed input and out-of-root --out-dir exit 1 with the 'Report not produced' copy and no file written"
    requirement: JRN-01
    human_judgment: false
    verification:
      - kind: unit
        ref: "tests/test_analytics_cli.py#test_clock_is_never_read_when_as_of_is_given"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_cli.py#test_out_dir_escape_exits_one_and_writes_nothing"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_cli.py#test_malformed_evidence_exits_one_with_the_copy_and_writes_no_files"
        status: pass
  - id: D3
    description: "Read-only DB path (live rows, prior evaluations, journal and file resets) plus the explicit idempotent --record step; only Select statements on the report path, exactly one guarded Insert for --record, no DATABASE_URL text in any output, --record without a usable database exits 2 before writing"
    requirement: GOV-01
    human_judgment: false
    verification:
      - kind: unit
        ref: "tests/test_analytics_cli.py#test_db_report_path_executes_only_select_statements"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_cli.py#test_record_is_idempotent_for_the_same_inputs_and_as_of"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_cli.py#test_db_failure_exits_one_with_only_the_exception_type"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_cli.py#test_record_without_a_database_url_exits_two_and_writes_nothing"
        status: pass
  - id: D4
    description: "Phase-closing guards: the no-float scan lists every pure analytics module (drift guard), edge modules are float/clock clean with one bounded clock read, the only Insert builder is build_append_stmt, the CLI imports no server/exchange/Telegram/execution code, migration parity unchanged and the full suite green"
    requirement: GOV-01
    human_judgment: false
    verification:
      - kind: unit
        ref: "tests/test_analytics_edge_guards.py#test_no_float_scan_lists_every_pure_analytics_module"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_edge_guards.py#test_the_only_insert_building_code_is_the_guarded_append_statement"
        status: pass
      - kind: unit
        ref: "tests/test_analytics_edge_guards.py#test_wrapper_parses_with_the_powershell_language_parser"
        status: pass
      - kind: command
        ref: "uv run --python 3.13 python scripts/check_migration_parity.py"
        status: pass
  - id: D5
    description: "The CLI against a real PostgreSQL 17 (read of the real journal/entity tables, the real make_session_factory engine on a Windows selector loop, and a real --record append with ON CONFLICT DO NOTHING)"
    requirement: GOV-01
    verification: []
    human_judgment: true
    rationale: "Every DB test runs against an in-memory fake session; statement compilation for the postgresql dialect is exercised by the record tests, but no server was started and the default factory path was only driven with an invalid URL (failure branch). The operator should run journal-report.ps1 and journal-report.ps1 -Record once against the Compose database"

duration: 13min
completed: 2026-09-29
status: complete
---

# Phase 10 Plan 12: Analytics CLI, PowerShell Wrapper and Closing Guards Summary

**One documented command now produces the offline journal-depth and kill-gate dashboard: `journal-report.ps1` wraps `python -m src.analytics.cli`, which loads evidence/decision/universe files and optional read-only DB rows, renders a Markdown + JSON sidecar pair that verify against each other, and writes exactly two files under the git-ignored reports root; `-Record` is the single, idempotent write.**

## Performance

- **Duration:** 13 min (start 2026-09-29T08:27:45Z, executor clock)
- **Completed:** 2026-09-29
- **Tasks:** 3 (tracer plus two auto tasks, all TDD with separate RED and GREEN commits)
- **Files:** 6 created or modified (4 new, 2 modified)
- **Tests added:** 57 (35 CLI, 22 edge guards)

## Accomplishments

- **File pipeline (tracer).** `main(argv, *, now_fn, session_factory_fn)` parses flags (`--as-of`, `--out-dir`, `--record`, `--universe`, `--evidence`, `--decisions`, `--raw-root`, `--resamples`, `--seed`, `--no-db`, test hook `--reports-root`), loads the decisions and evidence files, normalizes backtest trades (duplicate trade or experiment ids across experiments fail closed), reads 1m candles per symbol window from the Parquet store, scans the real registry and family sheets, takes the research clock from the frozen protocol, and runs `build_journal_depth_report -> render_markdown -> sidecar_text -> verify_render` before anything is written. Output is two raw-byte files (UTF-8, LF) named from the report stem; stdout is exactly `Report:`, `Sidecar:`, `Digest: sha256:`, `Kill gate:`. Two runs with the same inputs and `--as-of` are byte-identical; a different `--as-of` changes the file names. A real-repo terminal case (three families TESTED_FAIL, `--as-of 2027-04-01`) exits 0 with the calm INSUFFICIENT_EDGE banner.
- **Database path and record step.** With `DATABASE_URL` present (and no `--no-db`) the CLI reads the five journal event types plus the six live entity tables with SELECT-only adapter calls, builds LIVE lifecycle, outcomes, R map and candles, takes prior evaluations from `prior_from_event` and merges journal and decisions-file resets. `--record` builds the content-hash `KILL_GATE_EVALUATION` event and appends it once after the files exist; a replay prints the same id and inserts nothing. INSUFFICIENT_EDGE additionally prints a reminder that a human must commit `recorded_terminal` (the CLI never edits that file). `--record` without a usable database exits 2 before anything is written; a failed append exits 1 with `Record failed: <Type>.` and keeps the files.
- **Wrapper and guards.** `journal-report.ps1` follows the `scripts/dev` convention. The no-float scan now lists all 24 pure `src/analytics` modules and a drift guard fails if a module is ever missing; edge guards prove the CLI and adapters are float and `total_seconds` free, the CLI has one bounded clock read, the only Insert builder is `build_append_stmt`, and the CLI imports no server, exchange, Telegram or execution code.

## Task Commits

1. **Task 1 (tracer): file pipeline** - `2257ce3` (test, RED: ModuleNotFoundError), `d0af1e1` (feat, GREEN: 20 passed)
2. **Task 2: read-only DB path and --record** - `80cd242` (test, RED: 10 failing on the planned behavior), `2acefb4` (feat, GREEN: 35 passed)
3. **Task 3: wrapper, README, guards** - `0950fb4` (test, RED: drift guard and wrapper checks failing), `9562bb4` (feat, GREEN: 57 passed)

**Plan metadata:** recorded by the docs commit that follows this summary.

_Tracer gate: the tracer `<verify>` is automated only and HUMAN_VERIFY_MODE defaults to end-of-phase, so it was re-run after the GREEN commit (20 passed) and expansion continued._

## Closing Gates (Task 3 verify, all run)

| Gate | Result |
|------|--------|
| `pytest tests/test_analytics_edge_guards.py tests/test_domain_no_float.py tests/test_analytics_cli.py tests/test_analytics_purity.py tests/test_analytics_typing.py` | pass (71 tests) |
| Wrapper smoke `journal-report.ps1 -NoDb -AsOf 2027-04-01T00:00:00+00:00 -Evidence tests/fixtures/phase10/loaders/evidence_sample.json -OutDir data/reports/_smoke` | exit 0; four stdout lines (`Kill gate: WITHIN_BUDGET`, digest `277bcfc1b29f...`); one `.md`/`.json` pair; output deleted afterwards, `data/` left absent |
| `python scripts/check_migration_parity.py` | exit 0 (model and migration parity green, zero schema change) |
| Full suite `uv run --python 3.13 pytest -q` | exit 0, no failures (6 pre-existing skips) |
| `ruff check src/analytics src/adapters/analytics_files.py src/adapters/analytics_store.py tests/test_analytics_cli.py tests/test_analytics_edge_guards.py` | All checks passed |
| `mypy src/analytics/cli.py` | only the pre-existing `src/adapters/telegram_notify.py:287` error (not this plan) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Windows event loop and engine disposal for the real database path**
- **Found during:** Task 2
- **Issue:** The plan calls for a read `asyncio.run` and a second `asyncio.run` for the record step. psycopg's async mode cannot run on the Windows default Proactor loop, and the shared engine cache would hand a pool bound to the closed first loop to the second run. Neither is visible with the fake session used in tests.
- **Fix:** `_LOOP_FACTORY` selects `asyncio.SelectorEventLoop` on win32; each run creates its session through the factory and disposes the engine bound to it (`factory.kw["bind"]`, cleanup errors suppressed) before its loop closes.
- **Files modified:** src/analytics/cli.py
- **Verification:** the fake-session tests exercise the same code path; real-server execution is recorded as coverage D5 (human judgment)
- **Commit:** 2acefb4

**2. [Rule 1 - Test defect, own test] Write-statement guard flagged `dict.update`**
- **Found during:** Task 3 (RED confirmation)
- **Issue:** `test_cli_builds_no_write_statement_of_its_own` matched any call named `update`, which caught `contexts.update(...)`.
- **Fix:** the guard now flags bare-name calls to insert/update/delete/text, any `.execute` attribute call, and any sqlalchemy import in cli.py.
- **Files modified:** tests/test_analytics_edge_guards.py
- **Commit:** 0950fb4

**Total deviations:** 2 auto-fixed (1 missing critical, 1 own-test defect). **Impact:** none on the plan's contract; both are correctness details of the same files.

### Judgment calls inside the plan (no deviation)

- Unmapped candidate experiments are not added to the INCOMPLETE ledger (see key-decisions); the plan did not require it.
- `--as-of` values with a non-UTC offset are normalized to UTC instead of refused (naive is refused, as specified).

## Issues Encountered

None. Repo-wide ruff (about 24 pre-existing findings) and the one pre-existing mypy error were left untouched as directed.

## Known Stubs

None.

## Threat Flags

None. The CLI adds no network endpoint, auth path or schema change; the threat register T-10-41 to T-10-46 is covered by tests (confinement, Select-only report path, single guarded Insert, secret-free output, one bounded clock read, no execution/reset code in the CLI).

## Self-Check: PASSED

- Created files present: src/analytics/cli.py, scripts/dev/journal-report.ps1, tests/test_analytics_cli.py, tests/test_analytics_edge_guards.py
- Commits present: 2257ce3, d0af1e1, 80cd242, 2acefb4, 0950fb4, 9562bb4
- No files under data/ and no change to src/db or Alembic versions; `git status` shows only the two unrelated pre-existing .planning modifications
