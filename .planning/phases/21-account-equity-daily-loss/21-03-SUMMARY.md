---
phase: 21-account-equity-daily-loss
plan: 03
subsystem: adapters
status: complete
tags: [binance, adapter, account-equity, fixtures, decimal, recorded-demo]
requirements-addressed: [RISK-01]
requires: []
provides:
  - "BinanceUsdmAdapter.account_information_snapshot / account_balances_snapshot / account_config_snapshot"
  - "AccountAssetRow, AccountInformationSnapshot, AccountBalanceRow, AccountConfigSnapshot, _require_exchange_decimal"
  - "scripts/gen_phase21_fixtures.py and tests/fixtures/phase21/recorded_demo/*.json (RECORDED_DEMO, demo-observed, not mainnet)"
affects: [21-04, 21-07, Phase 24 wiring]
tech-stack:
  added: []
  patterns:
    - "strict text-to-Decimal parse naming the field only, never the value"
    - "fixtures unflattened from the Phase 19 Demo capture by a stdlib generator"
key-files:
  created:
    - scripts/gen_phase21_fixtures.py
    - tests/fixtures/phase21/README.md
    - tests/fixtures/phase21/recorded_demo/account_information_v3.json
    - tests/fixtures/phase21/recorded_demo/account_balance_v3.json
    - tests/fixtures/phase21/recorded_demo/account_config.json
    - tests/test_account_reads_adapter.py
    - tests/test_phase21_fixtures.py
  modified:
    - src/adapters/binance_usdm.py
    - tests/test_binance_usdm_signed_calls.py
key-decisions:
  - "Equity field is totalMarginBalance of GET /fapi/v3/account (D-02); capture and docs agree, no difference to record. availableBalance is not read (Phase 22)."
  - "A missing assets list raises (a dropped field must not read as an empty account); an empty list stays empty."
  - "_require_exchange_decimal also rejects surrounding whitespace and underscores (Python Decimal would accept '1_0')."
commits: 2
plan_head_before: 017feeebd8a9fc344a0a6ac3c54c5aabce372e71
plan_head_after: f74dbfc15ff0aa011749ae5db306789ebfc6e46d
actuals:
  tokens: 13400
  tasks: 2
  commits: 2
metrics:
  completed: 2026-10-23
---

# Phase 21 Plan 03: Account reads and recorded-Demo fixtures Summary

Three signed, gated, never-retried read-only account reads (v3/account, v3/balance, accountConfig) return strict Decimal snapshots, tested against fixtures generated from the owner-run Demo capture of 2026-10-22 (demo-observed, not mainnet).

## What was built

- Adapter (`src/adapters/binance_usdm.py`, CRLF kept): `AccountAssetRow`, `AccountInformationSnapshot`, `AccountBalanceRow`, `AccountConfigSnapshot`; methods `account_information_snapshot()`, `account_balances_snapshot()`, `account_config_snapshot()`, all through `_sdk_call(CallKind.QUERY, ...)` (policy, shared REST gate, no retry); helper `_require_exchange_decimal`; module docstring table has three new rows and says "fourteen SDK methods".
- Generator `scripts/gen_phase21_fixtures.py`: stdlib only, imports nothing from `src`/`tests`, unflattens the flattened Phase 19 summary maps, applies `WIRE_TYPES` (bool/int), drops the alias field (constant `ALIAS_FIELD`), deterministic (sorted keys, LF).
- Fixtures + `README.md` (RECORDED_DEMO, source file per output, conversions, removed fields, regenerate command).
- Over the recorded payload: totalMarginBalance 4999.09343961, totalWalletBalance 4999.09343961, totalUnrealizedProfit 0.00000000, USDT row marginBalance 4999.09343961, USDC 5000.00000000 and BTC 0.01000000 as separate rows; v3/balance USDT balance 4999.09343961, crossUnPnl 0; config multiAssetsMargin False, dualSidePosition False.
- Signed-call registry: `SIGNED`, `SIGNATURE_SNAPSHOTS`, `_payloads` extended; count test renamed `test_the_signed_set_is_the_fourteen_methods` (14).

## Task commits

| Task | Commit | Description |
|---|---|---|
| 1 (tracer) | b6720bb9 | capture -> generator -> fixture -> fake SDK -> account_information_snapshot -> Decimal totals |
| 2 | f74dbfc1 | v3/balance and accountConfig reads, strictness, alias never read, registry at fourteen |

The tracer feedback gate: Task 1's `<verify>` (automated only) was re-run end to end after the commit and passed, then Task 2 expanded.

## Verification

- `uv run pytest -m "not docker" tests/test_account_reads_adapter.py tests/test_phase21_fixtures.py tests/test_binance_usdm_signed_calls.py tests/test_adapter_strictness.py tests/test_binance_usdm_source_guard.py`: all passed (376 tests).
- Gate files `tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py`: all passed (81 tests).
- `TRADING_CI_STRICT=1 uv run pytest -m "not docker" tests/test_persistence_exit_evidence_pg.py` with `TEST_DATABASE_URL` set in the environment: 31 passed.
- `uv run mypy src/adapters/binance_usdm.py`: no issues. `uv run ruff check` and `uv run ruff format --check` on the five scoped files: clean.
- `git diff --exit-code -- pyproject.toml uv.lock`: clean (no dependency added, T-21-SC).
- `git log --grep="^[a-z]*(21-03):" -- config params src/execution src/risk pyproject.toml uv.lock` prints nothing.
- No full-suite run (orchestrator does that once per phase). No sibling-file failure was seen in the files I ran.

## Deviations from Plan

None - plan executed as written. Two small choices inside the plan's room: a missing `assets` list raises (listed under key-decisions), and `_require_exchange_decimal` is stricter than `Decimal()` (whitespace, underscore). `commits:` is the count of this plan's own `(21-03)` commits between the recorded base and HEAD; sibling plans 21-02/21-04/21-05/21-06 committed on the same tree in between, so a plain `rev-list` over the range would count theirs too.

## Threat model

T-21-04 (strict parse: tested with None, empty, abc, NaN, Infinity, -Infinity for every amount field), T-21-05 (alias never read: a property that raises on access, a recursive key walk over the fixtures, capture_logs on every read), T-21-06 (gate refusal before the SDK, no retry: tested for all three reads), T-21-SC (no dependency change) are all mitigated and tested.

## Known Stubs

None.

## Threat Flags

None. No new network endpoint or trust boundary beyond the three planned signed GET reads; nothing is wired into a runtime (Phase 24).

## For the owner

- The adapter methods are not on the manager's `ExecutionAdapter` protocol and are not called by any runtime yet; Phase 24 wires them through their own ports.
- Fixture values are Demo (demo-observed, not mainnet). Mainnet account shape (single-asset mode, USDT only) is the documented SDK behavior, not observed here.
- No requirement was marked complete (RISK-01 stays open; plan 21-14 records status).

## Self-Check: PASSED

Files found: scripts/gen_phase21_fixtures.py, tests/fixtures/phase21/README.md, the three recorded_demo JSON files, tests/test_account_reads_adapter.py, tests/test_phase21_fixtures.py. Commits found: b6720bb9, f74dbfc1.
