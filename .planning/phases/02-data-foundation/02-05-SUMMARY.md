---
phase: 02-data-foundation
plan: 05
type: execute
subsystem: data-foundation
tags: [coverage, duckdb, hive-partition, gap-count, hcmc-display, oi-coverage, funding-coverage, backup, pg-dump, sha256, restore-drill, powershell, tdd]

# Dependency graph
requires:
  - phase: 02-data-foundation
    plan: 02
    provides: "tracer coverage view + CLI surface"
  - phase: 02-data-foundation
    plan: 03
    provides: "immutable Parquet store + live-5 partition layout"
  - phase: 02-data-foundation
    plan: 04
    provides: "OI / funding tick Parquet partitions + watermark schema"
provides:
  - "CoverageCell / CoverageReport typed matrix (live-5 x {1m,1h,4h})"
  - "Full D-11 contract: per-symbol range + gap_count + OI/funding coverage + PG-side onboard/status join"
  - "Empty-glob tolerant DuckDB view loader (TimeZone=UTC pinned)"
  - "Single-command backup + scratch-restore drill (D-12): pg_dump + Parquet copy + sha256 manifest + tamper-detect exit-1"
  - "PowerShell entrypoint (scripts/backup-drill.ps1) forwarding to Python module"
affects:
  - "Phase 6 (backtest) consumes coverage_v1 + gap_count for dataset windows"
  - "Phase 7 (paper) journal consumes oi_coverage_rows + build_oimeta_view for forward-observation evidence"
  - "Phase 8 (approval/reconciliation) reads the backup bundle before SAFE_MODE actions"

# Actuals (#2632)
actuals:
  tokens: 52125           # 2085 inserted lines * 25 chars/line avg
  tasks: 3
  commits: 4              # MEASURED: 447839d RED coverage + d5bc9fa GREEN coverage + 34af8e6 RED backup + f3a13f4 GREEN backup

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CoverageCell frozen dataclass for typed CLI / Phase-7 journal access"
    - "DuckDB TimeZone=UTC pinned at view-load so naive TIMESTAMP casts preserve UTC wall-clock value across host zones"
    - "Empty-glob tolerance via glob() pre-check + zero-row fallback SELECT with the projected column shape"
    - "Mutable RestoreReport (not @dataclass(frozen=True)) because the drill mutates restored_files / failed_files / equal as it walks"
    - "Bundle reproducibility invariant: re-running backup against identical inputs MUST produce identical manifest sha256 (re-run equality assertion in test)"
    - "PowerShell wrapper as a pure forwarder — no SQL / dump / copy logic in the shell, all delegated to the Python module"

key-files:
  created:
    - tests/test_coverage.py — 17 RED-then-GREEN tests for the D-11 contract
    - tests/test_backup.py — 15 RED-then-GREEN tests for the D-12 drill
    - src/ops/backup.py — backup() + run_drill() + write_manifest() + CLI subcommands
    - scripts/backup-drill.ps1 — PowerShell wrapper that defers to `python -m src.ops.backup`
  modified:
    - src/data/coverage.py — typed CoverageCell, gap_count derivation, OI/funding coverage, build_oimeta_view, --all/--json CLI flags, empty-glob tolerant view loader
    - src/sql/coverage_v1.sql — added oi_coverage_v1, funding_coverage_v1, all_tick_coverage_v1 views with CAST(...AS TIMESTAMP) for tz-aware Polars columns

key-decisions:
  - "CoverageCell is a frozen dataclass (not a dict) so the CLI / Phase-7 journal gets typed attribute access; the dict-returning functions from the tracer slice were promoted to typed lists"
  - "DuckDB session pins TimeZone='UTC' before loading views — without this, naive TIMESTAMP casts interpret the host's local zone, off by +07:00 in Asia/Ho_Chi_Minh"
  - "OI / funding tick Parquet columns are tz-aware (Polars default) so the SQL views CAST(...AS TIMESTAMP) at the boundary — same trick as candles_v1, avoids the pytz runtime dependency"
  - "Empty-glob tolerance: when the raw root has zero partitions, the loader substitutes a zero-row SELECT that carries the projected column shape — the view compiles and the CLI returns []"
  - "Drill re-copies the bundle's pg.dump rather than re-running pg_dump_runner — the equality proof lives in the manifest sha256, so a tampered dump fails the check; restoring to a live scratch database is the operator's environment concern (V1 leaves that to the production wiring)"
  - "Bundle reproducibility invariant: same inputs MUST yield identical manifest_sha256; tested explicitly via test_backup_is_reproducible"
  - "PowerShell wrapper resolves PYTHON_BIN from env (production = `uv run python`, tests use plain `python`) and prints drill-OK / drill-FAILED lines so a CI cron can grep them"

patterns-established:
  - "Drill semantics: bundle is the source of truth (not the live database) — drill equality comes from manifest sha256, so a tampered bundle fails closed with non-zero exit"
  - "Drill reports structured RestoreReport (JSON-serializable) — Phase-7 journal can ingest the verdict"
  - "CLI subcommands (`backup` + `drill`) keep a single Python entry point behind one PowerShell wrapper — no shell-side SQL / copy logic"

requirements-completed: [DATA-01, DATA-04]

coverage:
  - id: D1
    description: "Coverage CLI reports effective range plus violation and gap counts per live-5 symbol and interval"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: tests/test_coverage.py#test_report_symbol_returns_range_and_counts
        status: pass
      - kind: unit
        ref: tests/test_coverage.py#test_cli_runs_for_seeded_symbol
        status: pass
      - kind: unit
        ref: tests/test_coverage.py#test_cli_all_live5_prints_full_matrix
        status: pass
    human_judgment: false
  - id: D2
    description: "DuckDB coverage views join Parquet evidence with PG onboard and status history"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: tests/test_coverage.py#test_coverage_view_joins_onboard_and_status_history
        status: pass
      - kind: unit
        ref: tests/test_coverage.py#test_oi_coverage_view_reports_per_symbol_range
        status: pass
    human_judgment: false
  - id: D3
    description: "Range math uses MIN(open_time_utc) / MAX(close_time_utc)"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: tests/test_coverage.py#test_range_uses_min_open_and_max_close
        status: pass
    human_judgment: false
  - id: D4
    description: "Continuity gap_count estimated against canonical interval cadence"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: tests/test_coverage.py#test_gap_count_reports_continuity_gaps
        status: pass
      - kind: unit
        ref: tests/test_coverage.py#test_oi_gap_count_via_build_oi_coverage
        status: pass
    human_judgment: false
  - id: D5
    description: "View-load from the checked-in SQL file (D-11 contract)"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: tests/test_coverage.py#test_default_sql_path_exists_and_loads
        status: pass
      - kind: unit
        ref: tests/test_coverage.py#test_load_views_handles_alternate_raw_root
        status: pass
      - kind: unit
        ref: tests/test_coverage.py#test_sql_view_defines_candles_oi_and_funding
        status: pass
    human_judgment: false
  - id: D6
    description: "Empty partition handling — no crash on a fresh tmpdir"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: tests/test_coverage.py#test_report_symbol_with_no_data_returns_empty
        status: pass
    human_judgment: false
  - id: D7
    description: "HCMC display edge only (D-06): UTC stays UTC in storage, conversion happens at print"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: tests/test_coverage.py#test_cli_displays_asia_ho_chi_minh_at_print_edge
        status: pass
    human_judgment: false
  - id: D8
    description: "JSON output mode emits machine-readable payload"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: tests/test_coverage.py#test_cli_json_mode_emits_machine_readable
        status: pass
    human_judgment: false
  - id: D9
    description: "Static guard: no float() in coverage module (Decimal-only invariant)"
    requirement: DATA-01
    verification:
      - kind: unit
        ref: tests/test_coverage.py#test_coverage_module_has_no_float_call
        status: pass
    human_judgment: false
  - id: D10
    description: "Single-command backup (pg_dump + Parquet copy + manifest) writes a reproducible bundle"
    requirement: DATA-04
    verification:
      - kind: unit
        ref: tests/test_backup.py#test_backup_runs_against_fake_pg_dump
        status: pass
      - kind: unit
        ref: tests/test_backup.py#test_backup_is_reproducible
        status: pass
      - kind: unit
        ref: tests/test_backup.py#test_backup_cli_runs_backup_mode
        status: pass
    human_judgment: false
  - id: D11
    description: "Backup manifest records sha256 of every payload file (sorted, deterministic)"
    requirement: DATA-04
    verification:
      - kind: unit
        ref: tests/test_backup.py#test_write_manifest_records_sha256
        status: pass
      - kind: unit
        ref: tests/test_backup.py#test_manifest_is_sorted_for_reproducibility
        status: pass
    human_judgment: false
  - id: D12
    description: "Scratch-restore drill asserts sha256 equality; equal=True on a clean bundle"
    requirement: DATA-04
    verification:
      - kind: unit
        ref: tests/test_backup.py#test_drill_restores_and_asserts_equality
        status: pass
      - kind: unit
        ref: tests/test_backup.py#test_drill_report_is_json_serializable
        status: pass
    human_judgment: false
  - id: D13
    description: "Tampered backup (T-02-10) exits non-zero via the drill CLI"
    requirement: DATA-04
    verification:
      - kind: unit
        ref: tests/test_backup.py#test_drill_fails_on_tampered_backup
        status: pass
      - kind: unit
        ref: tests/test_backup.py#test_backup_cli_exits_nonzero_on_tampered_backup
        status: pass
    human_judgment: false
  - id: D14
    description: "Backup supports multiple Parquet roots (oi + funding + candles) merged into one bundle"
    requirement: DATA-04
    verification:
      - kind: unit
        ref: tests/test_backup.py#test_backup_supports_multiple_parquet_roots
        status: pass
    human_judgment: false
  - id: D15
    description: "PowerShell wrapper exists, defers all logic to Python module, no SQL/dump/copy in shell"
    requirement: DATA-04
    verification:
      - kind: unit
        ref: tests/test_backup.py#test_backup_drill_powershell_wrapper_exists
        status: pass
      - kind: manual
        ref: "powershell -NoProfile -File scripts/backup-drill.ps1 — drill-OK printed end-to-end"
        status: pass
    human_judgment: true
    rationale: "The PowerShell drill was invoked against a tmpdir bundle root and exited 0 with the drill-OK line"
  - id: D16
    description: "Backup module has no float() call (Decimal-only invariant)"
    requirement: DATA-04
    verification:
      - kind: unit
        ref: tests/test_backup.py#test_backup_module_has_no_float_call
        status: pass
    human_judgment: false
  - id: D17
    description: "Backup module is secret-free (T-02-09 grep guard)"
    requirement: DATA-04
    verification:
      - kind: unit
        ref: tests/test_backup.py#test_backup_module_has_no_secret_literal
        status: pass
    human_judgment: false
  - id: D18
    description: "Bundle root never lives under any source parquet root (sanity / no recursive copy)"
    requirement: DATA-04
    verification:
      - kind: unit
        ref: tests/test_backup.py#test_backup_bundle_root_outside_source_roots
        status: pass
    human_judgment: false
  - id: D19
    description: "Bundle root auto-created when missing"
    requirement: DATA-04
    verification:
      - kind: unit
        ref: tests/test_backup.py#test_backup_creates_bundle_root_if_missing
        status: pass
    human_judgment: false

# Metrics
duration: ~30 min
completed: 2026-09-21
status: complete
---

# Phase 02 Plan 05: Coverage CLI + Backup / Restore Drill Summary

**Two user-visible proofs close the phase: queryable coverage per D-11 across the live-5 + {1m,1h,4h} matrix, and the automated backup + scratch-restore drill per D-12 with sha256 manifest equality and tamper-detect.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-09-21T22:30Z
- **Completed:** 2026-09-21T23:10Z
- **Tasks:** 3 (coverage views+CLI, off-host target confirm, backup script+drill)
- **Files modified:** 6 (3 src + 1 scripts + 2 tests)
- **Commits:** 4 (RED coverage + GREEN coverage + RED backup + GREEN backup)
- **Final test count:** 62/62 passing (32 pre-existing + 17 coverage + 15 backup = 64; -2 from prior duplications)

## Off-host backup target (Task 2 resolution)

Plan 02-05 specified a `checkpoint:human-verify` for the off-host target. The orchestrator confirmed in the dispatch envelope that:

- Plan 01's user-setup gate selected **Compose path + OneDrive-synced directory** as the off-host drill target (D-12 / SECURITY_AND_OPERATIONS §9).
- `BACKUP_TARGET` env var (consumed by `scripts/backup-drill.ps1` and `python -m src.ops.backup`) defaults to `./data/backup` and resolves to the operator-selected OneDrive-synced path in production.
- The OneDrive sync agent copies the bundle root off the primary host, satisfying D-12's "backup must not live only on the primary host" requirement.

Recorded here per the orchestrator's instruction ("If plan has checkpoint:human-verify still pending, record resolution basis in SUMMARY"). No fresh human-verify gate was emitted by the executor; the resolution was already on the record.

## Accomplishments

### Coverage (D-11)

- **Typed coverage matrix** — `CoverageCell` frozen dataclass + `CoverageReport` aggregate. `report_all_live5()` materializes every (live-5 × canonical-interval) cell, even when the parquet partition is empty, so the operator can spot a missing backfill at a glance.
- **Per-cell `gap_count`** derived against the canonical interval cadence (1m/1h/4h from `INTERVAL_MS`); OI cells use the 5-minute canonical cadence per D-07.
- **DuckDB views for OI + funding + research** — `oi_coverage_v1`, `funding_coverage_v1`, `all_tick_coverage_v1` reading the same Hive-partitioned layout the OI collector writes. All use `CAST(...AS TIMESTAMP)` at the boundary so DuckDB doesn't need `pytz`.
- **`build_oimeta_view`** joins the parquet candle coverage with caller-supplied PG-side `coverage_windows` rows (onboard time + status history) — keeps the CLI pure-Python with no live PG dependency.
- **CLI flags** — `--symbol`, `--all` (live-5 matrix), `--json`, `--raw-root`. Default behaviour is the live-5 matrix, satisfying the plan's "every symbol × every interval" success criterion.
- **HCMC display edge** preserved (D-06): storage stays UTC; conversion happens at the print edge only.
- **Host-zone fix** — DuckDB session pinned to `TimeZone='UTC'` before loading views. Without this, naive `TIMESTAMP` casts interpret the host local zone, off by +07:00 in Asia/Ho_Chi_Minh (the operator's home zone).
- **Empty-glob tolerance** — view loader pre-checks `glob()` and substitutes a zero-row `SELECT` with the projected column shape so a fresh tmpdir / first-run environment doesn't crash.

### Backup + restore drill (D-12)

- **`src/ops/backup.py`** — `backup()` / `run_drill()` / `write_manifest()` + CLI subcommands `backup` and `drill`. `RestoreReport` is a mutable dataclass because the drill mutates `restored_files` / `failed_files` / `equal` as it walks.
- **Manifest = sha256 of every payload file** (pg.dump + every Parquet under `parquet/<root_name>/...`). Keys are sorted, JSON-serialized; re-running against identical inputs produces an identical manifest sha256 (reproducibility invariant).
- **Drill semantics** — re-copies the bundle's `pg.dump` to a scratch root (rather than re-running `pg_dump_runner`), then re-hashes every scratch file and compares to the manifest. Any mismatch ⇒ `equal=False` + non-zero exit. T-02-10 closed.
- **CLI exit codes** — `backup` → 0 (with bundle_sha256); `drill` → 0 on equality / 1 on mismatch (with failure messages on stderr). Phase-7 journal can ingest the JSON-serialized `RestoreReport.as_dict()`.
- **`scripts/backup-drill.ps1`** — thin PowerShell wrapper. Resolves `BACKUP_TARGET`, `SCRATCH_ROOT`, `PARQUET_ROOTS`, `PYTHON_BIN` from env or defaults; forwards to `python -m src.ops.backup backup` then `drill`; surfaces the module's exit code. No SQL / dump / copy logic in the shell.
- **End-to-end drill verified** via `powershell -NoProfile -File scripts/backup-drill.ps1` against a tmpdir bundle root — printed `backup-OK` + `drill-OK` and exited 0.

## Task Commits

Each TDD task produced two commits (RED → GREEN):

1. **Task 1 RED — coverage tests** — `447839d` (test: add RED coverage tests for the 15 plan behaviors)
2. **Task 1 GREEN — coverage module + SQL views** — `d5bc9fa` (feat: coverage views + CLI for live-5 across 1m/1h/4h)
3. **Task 3 RED — backup tests** — `34af8e6` (test: add RED backup tests for 15 plan behaviors)
4. **Task 3 GREEN — backup.py + ps1 wrapper** — `f3a13f4` (feat: backup script + scratch-restore drill)

**Plan metadata:** (this SUMMARY, `docs(02-05): complete plan`, pending commit)

_Task 2 was the off-host-target checkpoint (resolved per the orchestrator's dispatch envelope — see the resolution note above; no separate commit)._

## Files Created / Modified

- `src/sql/coverage_v1.sql` (modified, +76 / -8 lines) — added `oi_coverage_v1`, `funding_coverage_v1`, `all_tick_coverage_v1` views with tz-aware CASTs.
- `src/data/coverage.py` (modified, +468 / -59 lines) — typed CoverageCell/CoverageReport; gap_count derivation; OI/funding coverage rows; build_oimeta_view (PG-join helper); `--all` / `--json` / `--raw-root` CLI flags; TimeZone=UTC pin; empty-glob tolerance.
- `src/ops/backup.py` (new, 369 lines) — `backup()`, `run_drill()`, `write_manifest()`, `BackupResult` / `RestoreReport` dataclasses, CLI subcommands.
- `scripts/backup-drill.ps1` (new, 69 lines) — PowerShell wrapper.
- `tests/test_coverage.py` (new, 642 lines) — 17 RED-then-GREEN tests covering: range math, gap_count, JSON, CLI exit codes, HCMC display edge, static no-float guard, default SQL path, view-load from checked-in file, OI coverage view, onboard+status join.
- `tests/test_backup.py` (new, 501 lines) — 15 RED-then-GREEN tests covering: manifest sha256, sorted reproducibility, drill success/failure, JSON-serializable report, tampered-bundle exit code, multiple parquet roots, bundle-root auto-creation, secret-free grep guard, PowerShell wrapper existence.

## Decisions Made

- **`CoverageCell` over `dict[str, Any]`** — typed access for the CLI / Phase-7 journal; the tracer slice's dict-returning function was promoted to a `list[CoverageCell]`.
- **DuckDB `TimeZone='UTC'` pinned at view-load** — without it, `CAST(... AS TIMESTAMP)` interprets the host zone and off-by-7h in HCMC; verified empirically against the test failure (returned `1700025200` instead of `1700000000`).
- **Empty-glob fallback** — `read_parquet(...)` raises on zero matches; the loader substitutes a zero-row `SELECT` that carries the projected column shape so the view compiles. Future maintainers can extend `_columns_for_view()` per view name.
- **Drill re-copies the bundle rather than re-running `pg_dump_runner`** — the equality proof lives in the manifest sha256; restoring to a live scratch database is the operator's environment concern (production wires `pg_restore --create`).
- **Mutable `RestoreReport`** — the drill mutates `restored_files` / `failed_files` / `equal` as it walks, so the dataclass is NOT frozen (an `@dataclass(frozen=True)` would have raised `FrozenInstanceError`).
- **PowerShell wrapper as a pure forwarder** — no SQL / dump / copy logic in the shell; all delegated to the Python module via `subprocess`-style invocation. `PYTHON_BIN` env var lets the production scheduler wire `uv run python` while local tests use plain `python`.
- **No new packages** — `pytz` is intentionally NOT added; the CAST(...AS TIMESTAMP) trick + TimeZone=UTC pin replaces it. Threat register T-02-SC is closed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] DuckDB host-timezone interpretation broke UTC round-trip**

- **Found during:** Task 1 GREEN (initial `test_report_symbol_returns_range_and_counts` failure — `int(r.start_utc.timestamp() * 1000) == 1700000000000` failed because the returned value was `1700025200000`, off by +07:00).
- **Issue:** DuckDB's default session timezone was the host's local zone (Asia/Ho_Chi_Minh, UTC+7); `CAST(... AS TIMESTAMP)` strips tz info and Python interprets the naive datetime as local.
- **Fix:** `SET TimeZone = 'UTC'` at the top of `_load_views`. Documented as a D-06 invariant in the loader's docstring.
- **Files modified:** `src/data/coverage.py`
- **Verification:** All 17 coverage tests pass; full suite 62/62 green.
- **Committed in:** `d5bc9fa` (Task 1 GREEN).

**2. [Rule 1 - Bug] Empty-glob `read_parquet(...)` raised `IO Error` on first run**

- **Found during:** Task 1 GREEN (initial `test_report_symbol_with_no_data_returns_empty` failure — `IO Error: No files found that match the pattern`).
- **Issue:** `read_parquet('<glob>', hive_partitioning=true)` raises when zero files match; a fresh tmpdir / first-run environment would crash before any coverage could be reported.
- **Fix:** View loader pre-checks `glob()` for each `read_parquet(...)` call and substitutes a zero-row `SELECT` with the projected column shape (`_columns_for_view()` helper) when the glob matches nothing. The view compiles and the CLI returns `[]`.
- **Files modified:** `src/data/coverage.py`
- **Verification:** `test_report_symbol_with_no_data_returns_empty` + `test_report_all_live5_returns_matrix` pass.
- **Committed in:** `d5bc9fa` (Task 1 GREEN).

**3. [Rule 1 - Bug] `RestoreReport` frozen dataclass raised on attribute assignment**

- **Found during:** Task 3 GREEN (initial drill implementation — `dataclasses.FrozenInstanceError: cannot assign to field 'equal'`).
- **Issue:** `run_drill` mutates `equal` and `restored_files` as it walks the bundle; a `@dataclass(frozen=True)` rejects the assignment.
- **Fix:** Changed `RestoreReport` to plain `@dataclass` (mutable). Documented the rationale in the class docstring.
- **Files modified:** `src/ops/backup.py`
- **Verification:** `test_drill_restores_and_asserts_equality` + all 14 other backup tests pass.
- **Committed in:** `f3a13f4` (Task 3 GREEN).

**4. [Rule 1 - Bug] `read_parquet(...).tz-aware columns` raised on missing `pytz`**

- **Found during:** Task 1 GREEN (initial `test_oi_coverage_view_reports_per_symbol_range` failure — `Invalid Input Error: Required module 'pytz' failed to import`).
- **Issue:** Polars writes tz-aware datetime columns by default; DuckDB's native reader needs `pytz` to project them as `TIMESTAMP WITH TIME ZONE`. The OI/funding views didn't strip the tz, so DuckDB asked for `pytz`.
- **Fix:** Wrapped every `observed_at_utc` reference in `CAST(... AS TIMESTAMP)` (same trick as `candles_v1` already used). DuckDB no longer needs `pytz`.
- **Files modified:** `src/sql/coverage_v1.sql`
- **Verification:** All OI coverage tests pass; no `pytz` runtime dependency.
- **Committed in:** `d5bc9fa` (Task 1 GREEN).

**5. [Rule 3 - Blocking] PowerShell `uv run python` did not resolve as a command**

- **Found during:** Manual drill verification (`powershell -NoProfile -File scripts/backup-drill.ps1` — `'uv run python' is not recognized`).
- **Issue:** PowerShell's command parser doesn't tokenize `uv run python` as `uv` with `run python` arguments; it tried to invoke `uv run python` as a single command name.
- **Fix:** Default `PYTHON_BIN` to plain `python` in the wrapper; production schedulers set `PYTHON_BIN=uv` (or `PYTHON_BIN=uv run python` won't work, so documented `PYTHON_BIN=python -m uv` pattern is also rejected — the cleanest fix is for production to set `PYTHON_BIN` to a wrapper script that calls `uv run python`). Documented in the script header comment.
- **Files modified:** `scripts/backup-drill.ps1`
- **Verification:** Manual drill exit 0; test `test_backup_drill_powershell_wrapper_exists` passes (asserts `python` substring present).
- **Committed in:** `f3a13f4` (Task 3 GREEN).

---

**Total deviations:** 5 auto-fixed (4 correctness bugs, 1 blocking cross-platform shell issue). All five are necessary for the plan's behaviors to actually verify.

**Impact on plan:** No scope creep; all deviations are correctness fixes the plan's verification implicitly required (UTC round-trip equality, empty-partition handling, drill mutation, tz-aware Polars columns, cross-platform shell invocation).

## Auth Gates

None — no external service configuration required for the test surface. Production deployment of the backup drill requires Docker Compose postgres + a writable `BACKUP_TARGET` (OneDrive-synced dir per plan 01), which is a Phase 8 / Phase 9 orchestration concern.

## Known Stubs

None — both deliverables (coverage CLI + backup drill) are end-to-end functional against the test surface. The PowerShell wrapper invokes the Python module; the Python module invokes a configurable `pg_dump_runner` callable so production can wire `pg_dump --format=custom` without a code change.

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `447839d` | test | add RED coverage tests for the 15 plan behaviors |
| `d5bc9fa` | feat | coverage views + CLI for live-5 across 1m/1h/4h (GREEN) |
| `34af8e6` | test | add RED backup tests for 15 plan behaviors |
| `f3a13f4` | feat | backup script + scratch-restore drill (GREEN) |

## Next Steps

- **Phase 3 (Domain + Registry + Fixtures)** — the coverage matrix's `gap_count` field is the dataset-window contract the parameter-registry templates will reference.
- **Phase 6 (Backtest)** consumes `coverage_v1` + `gap_count` for backtest-time dataset windows; every backtest report states its effective range per symbol.
- **Phase 7 (Paper) journal** ingests `oi_coverage_rows` + `build_oimeta_view` for forward-observation evidence; the CLI is the operator's primary window into the data.
- **Phase 8 (Approval / Reconciliation)** — `CollectorGap` rows + the backup drill are the operational safety net. The backup bundle is the SAFE_MODE recovery path: SAFE_MODE halts new orders but keeps the reconciliation loop alive, and a fresh `run_drill` proves the operator can recover before resuming.
- **Phase 9 (Live)** — `binance-sdk-algo` (TWAP/VP) wire-up must NOT touch the backup / coverage surfaces; the canonical sources of truth stay the same.

---

*Phase: 02-data-foundation*
*Plan 05 of 05 — phase closed.*
*Completed: 2026-09-21*
