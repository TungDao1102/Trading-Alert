---
phase: 22-leverage-margin-liquidation-guard
plan: 07
subsystem: risk
tags: [liquidation, isolated-margin, leverage-brackets, fail-closed, pure-module, F-964, criterion-2]
requires:
  - phase: 22
    provides: "tests/fixtures/phase22/recorded_demo/leverage_brackets.json and tests/support/phase22_fixtures.py (plan 22-01); the Phase 22 SCANNED_FILES block (plan 22-04)"
provides:
  - "src/risk/liquidation.py: Bracket, LiquidationVerdict, liquidation_price, liquidation_beyond_stop, liquidation_verdict, brackets_are_fresh, BASIS_POINT_DENOMINATOR, the plain codes LIQUIDATION_TOO_CLOSE, LIQUIDATION_INPUT_UNAVAILABLE, LEVERAGE_ABOVE_BRACKET, NOTIONAL_ABOVE_MAX and LIQUIDATION_OK"
  - "tests/support/phase22_fixtures.py: demo_brackets() builds the pure Bracket list from the generated fixture"
affects: [22-12, 22-13, 22-14, 22-16]
tech-stack:
  added: []
  patterns: ["exact Fraction arithmetic from Decimal inputs; the Decimal output is informational, no decision depends on its rounding"]
key-files:
  created:
    - src/risk/liquidation.py
    - tests/test_liquidation_price.py
  modified:
    - tests/support/phase22_fixtures.py
    - tests/test_domain_no_float.py
key-decisions:
  - "The tier is the bracket containing Q x LP (amendment A6), never the entry notional; every bracket is solved and kept only if its own Q x LP lies in its own [floor, cap]."
  - "If two candidates are self-consistent (exact edge of a table that is not continuous) the conservative one is returned: the larger LP for a LONG, the smaller for a SHORT. On the recorded Demo table both are equal."
  - "buffer_bps must be a plain positive int (0 is refused, like the limits loader and margin_check headroom); no default anywhere."
  - "The verdict decides on the exact Fraction LP, not on the rounded Decimal it also returns (tested under a 6-digit decimal context)."
  - "A computed LP that is non-positive in every candidate is LIQUIDATION_INPUT_UNAVAILABLE; no self-consistent tier with some positive candidate is NOTIONAL_ABOVE_MAX."
status: complete
requirements-addressed: [RISK-02]
duration: ~35 min
completed: 2026-10-24
commits: 2
plan_head_before: be5bfb50e9e2a697497c5363caa606da1f645e80
plan_head_after: d0ace6527533fbda54c85e30ad44066f7e5b3655
actuals:
  tokens: 16000
  tasks: 2
  commits: 2
---

# Phase 22 Plan 07: Pure liquidation guard Summary

**Clock-free, float-free module that computes the isolated one-way liquidation price from the exchange's leverage brackets with the tier of the liquidation notional, in exact Fractions, and applies the strict buffer predicate beyond the stop; the five research goldens G1-G5 are reproduced to 12 decimal places from the recorded Demo table.**

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | d58b02f7 | module with the full tier loop, `Bracket`, `LiquidationVerdict`, `liquidation_price`, `liquidation_beyond_stop`, `liquidation_verdict`; `demo_brackets()` loader; module in `SCANNED_FILES`; goldens G1 and G2, strict boundary tests |
| 2 | d0ace652 | list shape check, `NOTIONAL_ABOVE_MAX`, `LEVERAGE_ABOVE_BRACKET`, non-positive LP, `brackets_are_fresh`; goldens G3, G4, G5, exact edge, continuity fact, AST purity tests |

`commits: 2` counts the commits whose subject starts with `(22-07)`. The shared working tree means `git rev-list plan_head_before..plan_head_after` is 4 because it also contains sibling plans' commits (22-06, 22-08); `plan_head_before` is the parent of the first 22-07 commit. The SUMMARY commit follows. Task 1 and Task 2 were committed as one commit each (tests and code together): a separate RED commit would have left a failing tree.

## What was built

- Formulas (22-RESEARCH 2.5, reconstruction, MEDIUM confidence): LONG `LP = (EP(1-1/L) - cum/Q)/(1-m)`, SHORT `LP = (EP(1+1/L) + cum/Q)/(1+m)`. Equality with the exchange's own isolated `liquidationPrice` is not claimed (A6); the owner-run `isolated_position_liquidation_price` case (plan 22-09) settles it.
- Goldens, all 12 dp: G1 LONG 0.01 = 64257.028112449799; G2 SHORT 0.01 = 95617.529880478088; G3 LONG 0.75 and G5 LONG 0.7 = 64257.028112449799 (a test asserts the entry-tier values 64254.606365159129 and 64249.820531227566 are NOT returned); G4 SHORT 0.75 = 95588.723051409619.
- Exact edge: quantity 0.778125 (Q x LP exactly 50000) returns the common value, and 0.7781250 returns the identical Decimal.
- Structural fact (i): n x rate - cum is equal at all nine edges of the recorded table (tested with Fractions, labelled a property of the table).
- Buffer predicate: `buffer = EP x bps / 10000`; LONG strict `LP < stop - buffer`, SHORT strict `LP > stop + buffer`; both boundaries tested (64200 false, 64199.999999 true; 90800 false, 90800.000001 true).
- Verdict: LONG stop 66000 is OK, stop 65000 is `LIQUIDATION_TOO_CLOSE`. Refusals with their own codes: empty / gap / overlap / first floor not zero / unsorted / duplicate number (`LIQUIDATION_INPUT_UNAVAILABLE`), entry notional above the top cap (`NOTIONAL_ABOVE_MAX`), leverage 5 at 120 000 000 entry notional (`LEVERAGE_ABOVE_BRACKET`, smaller maximum at an edge), no self-consistent tier (`NOTIONAL_ABOVE_MAX`), non-positive LP and inverted stop geometry (`LIQUIDATION_INPUT_UNAVAILABLE`).
- `brackets_are_fresh`: age equal to `max_age` passes, one microsecond more is stale, negative age is stale, naive/non-UTC instants and a non-positive `max_age` raise. No clock is read.
- Purity (AST tests in `tests/test_liquidation_price.py`, to be re-run by plan 22-16's gate): no wall clock, no float constructor or float literal, none of the forbidden imports, no quote-asset string, int literals only 0, 1, 10000. Imports: stdlib, Decimal, Fraction, `src.domain.enums`.
- `tests/support/phase22_fixtures.py::demo_brackets()` reads the JSON with `parse_float=Decimal`; no bracket value is typed in a test.

## Deviations from Plan

None - plan executed as written. Notes on judgement calls:

- `buffer_bps` of 0 raises (the plan did not state it); consistent with the limits loader and `margin_check` which refuse 0.
- The bracket-list-level shape check also raises `TypeError` for a non-`Bracket` element (programming error, not a data refusal).

## Verification

- `uv run pytest -m "not docker" tests/test_liquidation_price.py tests/test_domain_no_float.py tests/test_phase21_gate.py tests/test_paper_shadow_isolation.py`: everything passes except one test outside this plan, see below.
- `uv run mypy src/risk/liquidation.py`: no issues. `ruff check` and `ruff format --check` on the four plan files: clean.
- `git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md params config`: exit 0. No commit of this plan touches `config params src/adapters src/execution src/persistence src/domain`.

## Issues Encountered

- `tests/test_phase21_gate.py::test_invariant_6_the_migration_head_is_0011_risk_reservations` fails because a wave-2 sibling (plan 22-08) added migration `0012_reservation_margin`. It points at a file outside this plan's files_modified; it is the sibling's/plan 22-16's pin to update on purpose. Not touched here.

## Known Stubs

None.

## Threat Flags

None. The module has no I/O, endpoint, file access or schema surface.

## Evidence label

Executed unit tests with recorded Demo bracket inputs (demo-observed, not mainnet) [DESIGN]. The formula is a reconstruction; criterion 2 is not Demo-proven until the owner runs `isolated_position_liquidation_price` (plan 22-09).

## Amendment 2026-10-24

Driven by the owner's Demo run `demo-probe-EVIDENCE-20261024T043134Z.json` (case `isolated_position_liquidation_price`, Demo-observed, not mainnet). The recorded BTC perpetual LONG (entry 80845.8, quantity 0.0014, leverage 5, tier 1) has an exchange `liquidationPrice` of 64968.85373637 and an `isolatedWallet` of 22.59155035, which is the initial margin minus the entry fee (0.0004 x Q x EP). The module as first written ignored the fee and gave 64936.3855, about 32 on the non-conservative side for a long.

- `liquidation_price` and `liquidation_verdict` take a REQUIRED keyword-only `entry_fee_rate: Decimal` (no default, finite, >= 0, 0 allowed; bool, int, float, str and None raise). The wallet is `Q x EP / L - entry_fee_rate x Q x EP` in `Fraction`s; a wallet of zero or less is `None` / `LIQUIDATION_INPUT_UNAVAILABLE`. The rate is never a constant in `src/risk`.
- `liquidation_beyond_stop` is NOT changed: it receives a liquidation price and uses no fee, so a fee argument there would be unused.
- Goldens G1 to G5 pass `entry_fee_rate=Decimal("0")` and their numbers are unchanged. New golden G6 is the Demo record: with the fee the module gives 64968.853735, 1.4e-6 from the exchange value (the exchange rounds the wallet to eight decimals; with the recorded rounded wallet the closed form gives 64968.85373637 exactly). The test asserts within 1e-5 and that the no-fee value differs by more than 30.
- The statement "equality with the exchange value has never been observed" is replaced in the module docstring by the observation above. It is one record, one tier, Demo only: not a proof for other tiers, for a short, or for mainnet. Callers: plan 22-13 and plan 22-14 carry a `plan_check_addenda` block saying they must pass the fee rate.
