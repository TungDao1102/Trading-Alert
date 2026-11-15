---
phase: 22-leverage-margin-liquidation-guard
plan: 01
subsystem: adapters
status: complete
tags: [binance, adapter, leverage, margin, liquidation, fixtures, decimal, recorded-demo]
requirements-addressed: [RISK-02, EXEC-01]
requires: []
provides:
  - "BinanceUsdmAdapter.symbol_config_snapshot(*, symbol) and leverage_brackets_snapshot(*, symbol)"
  - "SymbolConfigSnapshot, LeverageBracketRow, SymbolLeverageBrackets, _exchange_number_to_decimal, _row_to_leverage_bracket"
  - "scripts/gen_phase22_fixtures.py and tests/fixtures/phase22/recorded_demo/{symbol_config,leverage_brackets}.json (RECORDED_DEMO, demo-observed, not mainnet)"
  - "tests/support/phase22_fixtures.py (load_symbol_config, load_leverage_brackets: JSON loaders only)"
affects: [22-06, 22-07, 22-11, 22-16]
tech-stack:
  added: []
  patterns:
    - "SDK float -> Decimal(repr(value)) after bool/None/non-finite/negative rejection"
    - "fixtures unflattened from the Phase 19 Demo capture by a stdlib generator (WIRE_TYPES incl. a JSON-number kind)"
key-files:
  created:
    - scripts/gen_phase22_fixtures.py
    - tests/fixtures/phase22/README.md
    - tests/fixtures/phase22/recorded_demo/symbol_config.json
    - tests/fixtures/phase22/recorded_demo/leverage_brackets.json
    - tests/support/phase22_fixtures.py
    - tests/test_phase22_fixtures.py
    - tests/test_leverage_margin_adapter.py
  modified:
    - src/adapters/binance_usdm.py
    - tests/test_binance_usdm_signed_calls.py
    - tests/test_paper_shadow_isolation.py
key-decisions:
  - "Negative maintMarginRatio, cum, notionalFloor, notionalCap and notionalCoef are refused (the plan listed None, bool, NaN, Infinity and negative ratio/cum; the others follow the same rule)."
  - "notional_coef is carried as Decimal or None and never interpreted; the guard (22-11) refuses a value other than 1."
  - "The oneOf wrapper is unwrapped with getattr(data, 'actual_instance', data), so a plain list or entry (fake) and the real wrapper take the same path."
commits: 3
plan_head_before: c04c2aa20f2c45eb8a8195118731671586cbc373
plan_head_after: dd2272547579afcb0fb629d46a4cbf1e80bc36b0
actuals:
  tokens: 12900
  tasks: 3
  commits: 3
metrics:
  completed: 2026-10-24
---

# Phase 22 Plan 01: Leverage and bracket reads and recorded-Demo fixtures Summary

Two signed, gated, never-retried read-only configuration reads (`symbolConfig`, `leverageBracket`) return strict frozen snapshots with exact Decimals, tested against fixtures generated from the owner-run Demo capture of 2026-10-22 (demo-observed, not mainnet); the signed-call registry now counts eighteen.

## What was built

- Adapter (`src/adapters/binance_usdm.py`, CRLF kept): `SymbolConfigSnapshot(symbol, margin_type, leverage, is_auto_add_margin, max_notional_value)`, `LeverageBracketRow(bracket, initial_leverage, notional_floor, notional_cap, maint_margin_ratio, cum)`, `SymbolLeverageBrackets(symbol, notional_coef, brackets)`; methods `symbol_config_snapshot(*, symbol)` (SDK `symbol_configuration`) and `leverage_brackets_snapshot(*, symbol)` (SDK `notional_and_leverage_brackets`), both through `_sdk_call(CallKind.QUERY, ...)` (policy, shared REST gate, no retry). Exactly one row or entry for the requested symbol is required. `marginType` non-empty text, `leverage` an int (not bool) of at least 1, `isAutoAddMargin` a real bool, `maxNotionalValue` a finite decimal text. Bracket floats become `Decimal(repr(value))`; None, bool, text, non-finite and negative values are refused. Every `ValueError` names the field only. Nothing is logged. Module docstring table has two new rows and says "all eighteen SDK methods".
- Generator `scripts/gen_phase22_fixtures.py`: stdlib only, imports nothing from `src`/`tests`, unflattens the flattened Phase 19 summary maps, `WIRE_TYPES` (bool, int, and a `number` kind that writes `maintMarginRatio`/`cum` as JSON numbers because the SDK models declare them `StrictFloat | StrictInt`), deterministic (sorted keys, 2-space indent, LF).
- Fixtures + `README.md` (RECORDED_DEMO label, source file per output, conversions, the "Demo table is not mainnet" note, the sentence that ISOLATED has never been recorded, regenerate command). `tests/support/phase22_fixtures.py` loads the JSON only.
- Over the recorded payload: symbolConfig reads CROSSED, leverage 20, isAutoAddMargin False, maxNotionalValue 20000000 (BTCUSDT). The bracket table has ten brackets in response order; bracket 1 is 125x, floor 0, cap 50000, ratio `Decimal("0.004")`, cum 0; bracket 4 is 20x, 3000000 to 20000000, ratio 0.025, cum 46300. `Decimal(0.004) != Decimal("0.004")` is asserted next to the parsed value.
- Signed-call registry: `SIGNED`, `SIGNATURE_SNAPSHOTS`, `_payloads` gain both reads; `test_the_signed_set_is_the_eighteen_methods` (18); every parametrized registry test (recv window, no policy, paused/banned gate, 418/429, -1008, -1021, signature) runs on both. The shadow isolation control lists both as read-only market-data methods.

## Task commits

| Task | Commit | Description |
|---|---|---|
| 1 (tracer) | 5674ae05 | symbolConfig capture -> generator -> fixture -> fake SDK -> `symbol_config_snapshot` -> CROSSED x20 |
| 2 | db0f3aa3 | `leverage_brackets_snapshot`, both oneOf shapes, `Decimal(repr)`, bracket fixture, loaders |
| 3 | dd227254 | registry at eighteen, shadow control, adapter docstring table |

Tracer feedback gate: Task 1's `<verify>` is automated only; it was run after the commit (and again with the full Task 2 set) and passed before expanding. Write order inside tasks: tests and implementation were written in one pass per task, not as separate red commits (tests were run only after the implementation existed for Task 1 and 2; no red run was recorded).

## Verification

- `uv run pytest -m "not docker" tests/test_phase22_fixtures.py tests/test_leverage_margin_adapter.py tests/test_binance_usdm_signed_calls.py tests/test_paper_shadow_isolation.py tests/test_adapter_strictness.py tests/test_binance_usdm_source_guard.py tests/test_phase18_gate.py tests/test_phase19_gate.py tests/test_phase20_gate.py tests/test_phase21_gate.py`: all passed.
- `uv run mypy src/adapters/binance_usdm.py`: no issues. `uv run ruff check` and `uv run ruff format --check` on the seven touched Python files: clean.
- `git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md params config/binance`: clean (no dependency added, T-22-SC).
- `git log --grep="^[a-z]*(22-01):" -- config params src/execution src/risk src/domain` prints nothing.
- Evidence label: fixtures are recorded owner-run Demo payloads (demo-observed, not mainnet); adapter behaviour is executed tests with a fake SDK [DESIGN]; nothing is Demo-proven by this plan. No full-suite run (the orchestrator does that once per phase).

## Deviations from Plan

None in scope - plan executed as written. Notes:

- **SDK 17.4.0 quirk found during Task 2 (not a deviation, a test input choice).** The object (non-array) shape of the bracket answer, `NotionalAndLeverageBracketsResponse2BracketsInner`, declares `cum` as `StrictInt` only, while the list shape accepts `StrictFloat | StrictInt`. The test for the object shape therefore derives integer `cum` values from the recorded whole-number sums (asserted whole) and checks the parsed result equals the list-shape result. The adapter handles both (`int` and `float` go through the same converter). A real exchange object answer with a fractional `cum` would fail inside the SDK before the adapter sees it; the recorded answer is the list shape.
- `commits:` is the count of this plan's own `(22-01)` commits (3). Sibling plans 22-02..22-05 committed on the same tree in between (the plain `rev-list` over `plan_head_before..HEAD` counts theirs too).
- A mypy `union-attr` error from the oneOf wrapper type was fixed by typing the unwrapped value as `Any` (Task 3 commit).

## Threat model

| Threat | Result |
|---|---|
| T-22-01 float handling | mitigated: `Decimal(repr(value))`, bool/None/non-finite/negative refused; test shows `Decimal(0.004)` differs from the parsed `Decimal("0.004")` |
| T-22-02 dropped or renamed field read as default | mitigated: strict type checks, one row for the symbol, field-name-only `ValueError`, tested with None/empty/wrong type |
| T-22-03 reads during a 418/429 pause | mitigated: both reads in `SIGNED`, so the shared-gate, 418/429 and no-retry registry tests cover them |
| T-22-04 logs and fixtures | mitigated: `capture_logs` tests show no value; the generator reads only the two configuration captures |
| T-22-SC dependencies | mitigated: `pyproject.toml` and `uv.lock` unchanged |

## Known Stubs

None. `notional_coef` is carried but deliberately not interpreted here (plan 22-11 refuses a value other than 1).

## Threat Flags

None. Two new signed read-only GETs on already-trusted endpoints behind the existing gate; no new network surface beyond the adapter's existing REST client, no order surface (shadow control updated).

## For the owner

- Nothing to run. The bracket table in the fixture is the Demo table (first bracket 125x); the mainnet figure quoted by the change-log is 150x. No bracket value is in `src/`.
- The ISOLATED casing of `marginType` is still unobserved (22-RESEARCH A5); the D-18 owner case records it.
- Plan 22-06 takes the signed-call registry from eighteen to twenty.

## Self-Check: PASSED

- Files present: `scripts/gen_phase22_fixtures.py`, `tests/fixtures/phase22/README.md`, `tests/fixtures/phase22/recorded_demo/symbol_config.json`, `tests/fixtures/phase22/recorded_demo/leverage_brackets.json`, `tests/support/phase22_fixtures.py`, `tests/test_phase22_fixtures.py`, `tests/test_leverage_margin_adapter.py`.
- Commits present on HEAD: 5674ae05, db0f3aa3, dd227254.
- `grep -n "def symbol_config_snapshot\|def leverage_brackets_snapshot" src/adapters/binance_usdm.py` prints one line each; `len(SIGNED) == 18` asserted.
