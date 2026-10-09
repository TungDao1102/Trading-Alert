---
phase: 16-paper-runtime-composition
plan: 03
subsystem: adapters / exchange-connectivity
tags: [binance, public-market-data, adapter-split, shadow-runtime, no-credentials, ast-guard]

requires:
  - phase: 16-paper-runtime-composition
    provides: "plans 16-01 and 16-02 (paper WS adapter on the real SDK shape; paper gate review fixes); no code dependency"
provides:
  - "src/adapters/binance_public.py: BinancePublicMarketData (klines, mark_klines, open_interest, open_interest_statistics, funding_rate, server_time, exchange_info) and the public value types Kline, MarkKline, OiSnapshot, FundingTick, SymbolFilters"
  - "A default SDK REST client built from an explicit ConfigurationRestAPI(api_key=None, api_secret=None); the module never reads the environment"
  - "BinanceUsdmAdapter delegates its public-data methods to a BinancePublicMarketData on its own SDK client and re-exports the moved types and row converters"
  - "tests/test_binance_public.py: equality with the order adapter and the AST no-order-surface check with a seeded negative control"
affects: [16-08 paper imports move to the public module, 16-22 runtime composition, 16-38 SHADOW module-closure ban on BinanceUsdmAdapter and src.execution.manager]

actuals:
  tokens: 17100
  tasks: 2
  commits: 4
plan_head_before: c0db264831d40917cab1858bf25f9a78a3354a72
plan_head_after: cee64bb3380fc2cf3bac07b3d4136a28053d2040
commits: 4

tech-stack:
  added: []
  patterns:
    - "Composition over inheritance: the order adapter holds the public adapter on the same SDK client and delegates, so one client serves both surfaces"
    - "Explicit `from x import Name as Name` re-exports (mypy strict no-implicit-reexport) keep every existing importer unchanged"
    - "AST surface guard as a pure helper with seeded-violation and clean-module controls (pattern of tests/test_paper_start_gate.py)"

key-files:
  created:
    - src/adapters/binance_public.py
    - tests/test_binance_public.py
  modified:
    - src/adapters/binance_usdm.py

key-decisions:
  - "Planner choice recorded (D-13, 'state which'): split the public class out into its own module and later ban any reference to BinanceUsdmAdapter and src.execution.manager in the SHADOW module closure (plan 16-38); a module-level import ban on binance_usdm could not work because paper code imports Kline from it"
  - "BinanceUsdmAdapter.__init__ keeps constructing DerivativesTradingUsdsFutures() with no arguments, so the existing tests/test_execution_secret_posture.py AST test still holds; the public adapter is handed that client rather than building a second one"
  - "The credential-free default client uses binance_common.configuration.ConfigurationRestAPI (same import precedent as src/adapters/paper_ws.py and scripts/demo_rehearsal.py), with api_key and api_secret passed as the literal None"

patterns-established:
  - "Public/private adapter split: anything the SHADOW process may call lives in binance_public.py and is guarded by an AST test; order, cancel, query, snapshot, position-mode and commission methods stay in binance_usdm.py"

requirements-completed: [PAPER-02]

coverage:
  - id: D1
    description: "BinancePublicMarketData exists, fetches klines, mark klines, open interest (current and statistics), funding rate, server time and exchangeInfo, and returns values equal to the order adapter's for the same fake SDK client"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_binance_public.py#test_public_klines_equal_order_adapter_klines"
        status: pass
      - kind: unit
        ref: "tests/test_binance_public.py#test_every_public_method_equals_the_order_adapter_method"
        status: pass
      - kind: unit
        ref: "tests/test_binance_public.py#test_the_public_values_are_the_expected_real_shaped_values"
        status: pass
    human_judgment: false
  - id: D2
    description: "The public module has no order, cancel, query, snapshot, position-mode or commission method, touches only the market-data rest_api calls, reads no environment variable, imports no os, passes no credential, and never references BinanceUsdmAdapter; the checker reports a seeded violation"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_binance_public.py#test_public_module_has_no_order_account_or_credential_surface"
        status: pass
      - kind: unit
        ref: "tests/test_binance_public.py#test_public_module_does_not_import_os"
        status: pass
      - kind: unit
        ref: "tests/test_binance_public.py#test_the_surface_checker_reports_a_seeded_place_entry"
        status: pass
      - kind: unit
        ref: "tests/test_binance_public.py#test_the_surface_checker_accepts_a_clean_module"
        status: pass
    human_judgment: false
  - id: D3
    description: "The default public client is built with a None key, secret and private key"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_binance_public.py#test_public_class_builds_its_client_with_a_none_key_and_secret"
        status: pass
    human_judgment: false
  - id: D4
    description: "BinanceUsdmAdapter behaviour and every importer of the moved types are unchanged"
    requirement: PAPER-02
    verification:
      - kind: unit
        ref: "tests/test_binance_public.py#test_every_moved_value_type_is_one_object_in_both_modules"
        status: pass
      - kind: unit
        ref: "tests/test_adapter_strictness.py, tests/test_adapter_not_found_mapping.py, tests/test_execution_adapter_contract.py (unedited)"
        status: pass
    human_judgment: false

duration: 14min
completed: 2026-10-09
status: complete
---

# Phase 16 Plan 03: Public market-data adapter split Summary

**The public market-data surface of `BinanceUsdmAdapter` now lives in a credential-free `BinancePublicMarketData` (`src/adapters/binance_public.py`) that the SHADOW runtime can import without loading the order adapter; the order adapter delegates to it and its output is unchanged.**

## Performance

- **Duration:** about 14 min (upper bound: the start time was not recorded; plan 16-02 completed at 03:26Z and this plan finished at 03:40Z)
- **Tasks:** 2 (Task 1 tracer, Task 2 auto, both TDD)
- **Files:** 3 (2 created, 1 modified)

## Accomplishments

- Tracer: `BinancePublicMarketData(sdk_client=None).klines` returns exactly what `BinanceUsdmAdapter.klines` returns on two real-shaped rows (rows from 16-RESEARCH.md), and `Kline` is one type object re-exported by the order adapter.
- Task 2: `mark_klines`, `open_interest`, `open_interest_statistics`, `funding_rate`, `server_time` and `exchange_info` moved unchanged, with `MarkKline`, `OiSnapshot`, `FundingTick`, `SymbolFilters`, `_row_to_mark_kline` and the exchangeInfo helpers (`_find_filter`, `_filter_decimal`, `_parse_market_lot_size`, `_parse_percent_price`, `_filter_blob`, `_order_capabilities_blob`, `_position_mode_blob`). Each order-adapter method delegates; every moved name is an explicit `as` re-export, so the 12+ importers under `src/data`, `src/paper`, `scripts/demo_rehearsal.py` and the tests (including the private `_row_to_kline` and `_row_to_mark_kline` that `src/data/archive.py` and tests import) are untouched.
- `_public_surface_violations(path)` is an AST helper that reports: forbidden method names (the 11 order, cancel, query, snapshot, position-mode and commission names), any SDK client attribute other than `rest_api`, any `rest_api.<call>` outside the seven public market-data calls, any `environ` or `getenv` reference, any credential keyword not the literal None, and any reference to `BinanceUsdmAdapter` or `binance_usdm`. A seeded module (with `place_entry`, `get_position_mode`, `os.environ`, `os.getenv`, `websocket_api`, `rest_api.new_order`, `api_key='abc'`, a `BinanceUsdmAdapter` import) is reported on every count and a clean module is not.
- The default client for the SHADOW process is `DerivativesTradingUsdsFutures(config_rest_api=ConfigurationRestAPI(api_key=None, api_secret=None))`; a test reads the constructed configuration back and asserts key, secret and private key are None.

## RED Evidence

- **Task 1** (`64f1150`, tests only): `tests/test_binance_public.py` failed at collection with `ModuleNotFoundError: No module named 'src.adapters.binance_public'`.
- **Task 2** (`da4b301`, tests only), against the Task 1 module: `test_every_public_method_equals_the_order_adapter_method` and `test_the_public_values_are_the_expected_real_shaped_values` failed with `AttributeError: 'BinancePublicMarketData' object has no attribute 'mark_klines'`, and `test_every_moved_value_type_is_one_object_in_both_modules` with `module 'src.adapters.binance_public' has no attribute 'MarkKline'`. The AST tests, the client-configuration test and the checker controls characterise the plan's intent and pass on the Task 1 module, so they have no RED of their own; the checker's non-vacuity is shown by the seeded-violation test.

## Task Commits

1. **Task 1 (tracer): klines through the public adapter** - `64f1150` (test, RED), `5569ac0` (feat, GREEN)
2. **Task 2: rest of the public surface and the no-order-surface guard** - `da4b301` (test, RED), `cee64bb` (feat, GREEN)

**Plan metadata:** committed separately (docs: complete plan).

## Verification

- `.venv/Scripts/python -m pytest tests/test_binance_public.py tests/test_adapter_strictness.py tests/test_adapter_not_found_mapping.py tests/test_execution_adapter_contract.py -q -p no:cacheprovider`: all pass (65 tests, 11 of them new).
- Also green (two processes): `test_archive_ingest`, `test_backfill`, `test_backfill_cli`, `test_backfill_closed_day`, `test_backfill_resume_floor`, `test_collector`, `test_constraint_snapshot`, `test_mark_klines`, `test_metadata`, `test_universe_freeze`, `test_quality_gates`; and `test_demo_rehearsal_flow`, `test_demo_rehearsal_safety`, `test_drills`, `test_execution_attach`, `test_execution_emergency`, `test_execution_manager`, `test_execution_secret_posture`, `test_paper_resync`, `test_paper_supervisor_backfill`, `test_phase8_audit_reviewfix`, `test_reconcile`, `test_symbol_filters_extra`, `test_tracer_slice`.
- `ruff check src tests/test_binance_public.py`, `ruff format --check` (151 files) and `mypy src` (150 files) are clean. The whole `pytest -m "not docker"` suite was not run in one process (tool limit); targeted suites above replace it.
- No file was deleted by any commit.

## Decisions Made

See `key-decisions` above. The two points worth restating: the split (rather than an import ban on the existing module) is the structure plan 16-38 will enforce, and the order adapter's own no-argument `DerivativesTradingUsdsFutures()` construction is kept so the existing secret-posture AST test holds without edits.

## Deviations from Plan

None - plan executed exactly as written. (Two details the plan left open: the exchangeInfo helper functions moved with `exchange_info` because nothing else used them, and the module docstring of `binance_usdm.py` gained a paragraph describing the delegation.)

## Known Stubs

None.

## Threat Flags

None. No new endpoint, auth path or schema; the new module exposes only unsigned public market-data calls already reachable through the order adapter. T-16-06 (elevation of privilege) is mitigated by the AST test plus the explicit None credentials; T-16-07 (tampering by the refactor) by the equality tests and the unchanged adapter and data suites.

## Notes for later plans

- `tests/test_execution_secret_posture.py` lists `src/adapters/binance_usdm.py` as its only exchange-facing adapter target; `src/adapters/binance_public.py` is not in `TARGET_RELPATHS` (not in this plan's file list). Its env-read and credential rules are covered by `tests/test_binance_public.py`; adding it to that list is a one-line option if wanted.
- Plan 16-08 moves the two `Kline` imports in `src/paper/resync.py` and `src/paper/supervisor.py` to `src.adapters.binance_public`; plan 16-38 can then ban `BinanceUsdmAdapter` and `src.execution.manager` in the SHADOW closure.

## Self-Check: PASSED

- FOUND: src/adapters/binance_public.py, tests/test_binance_public.py, src/adapters/binance_usdm.py
- FOUND commits: 64f1150, 5569ac0, da4b301, cee64bb
