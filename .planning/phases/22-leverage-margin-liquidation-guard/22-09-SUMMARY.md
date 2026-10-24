---
phase: 22-leverage-margin-liquidation-guard
plan: 09
subsystem: probe
tags: [demo-probe, owner-run, isolated-margin, available-balance, liquidation-price, evidence-plan, D-18, D-19]
requires:
  - phase: 22
    provides: "plan 22-05: change_margin_type / change_initial_leverage on the probe port, SJ3_CASES with symbol_config_change_to_isolated, order.config_target_leverage"
  - phase: 22
    provides: "plan 22-01 recorded Demo shapes (symbolConfig, leverageBracket) the fakes and the bracket parser follow"
provides:
  - "scripts/demo_probe.py: SJ3_CASES = six ids in the plan's order; five new handlers and case_ wrappers, OPTIONAL_CASES keys margin_type_resting_order, leverage_above_max, margin_insufficient_target, available_balance_resting, isolated_liquidation; margin_order_refusal/margin_limit take the owner flag of the case that sends the owner's own quantity"
  - "src/ops/operator_evidence.py: the five keys in EVIDENCE_CASE_KEYS after symbol_config_change; insufficient_margin_quantity required exactly with insufficient_margin OR margin_insufficient_target; config_target_leverage required exactly with symbol_config_change, margin_insufficient_target or isolated_liquidation"
  - ".planning/DEMO-EVIDENCE-PLAN.md: sections 25-29 (24 is plan 22-05's), Step 0 keys and rules, session list entries 24-29, consumers rows, Safety sentences and a Phase 22 evidence map"
affects: [22-11, 22-13, 22-14, 22-16]
tech-stack:
  added: []
  patterns: ["one owner flag per Demo case; each mutation sent once; an unexpectedly accepted change is undone once by the case that made it and recorded; raw figures and exact Decimal deltas, never a verdict"]
key-files:
  created: []
  modified:
    - scripts/demo_probe.py
    - src/ops/operator_evidence.py
    - tests/probe_fakes.py
    - tests/test_demo_probe_sj3_cases.py
    - tests/test_demo_probe_cases.py
    - tests/test_demo_probe_sj2_cases.py
    - tests/test_operator_evidence.py
    - .planning/DEMO-EVIDENCE-PLAN.md
key-decisions:
  - "margin_insufficient_at_target_leverage is not a second copy of the shortfall flow: _insufficient_margin_order gained keyword arguments (flag, prefix, require_target) and the new handler calls it. The sj2 pin 'only _insufficient_margin_order reaches margin_limit' therefore stays true, and the owner's own quantity is bound by margin_order_refusal with the case's own flag (MARGIN_ORDER_FLAGS)."
  - "The detail names of the plan 22-05 case and of insufficient_margin_order are unchanged; the new shortfall case writes the same facts under the prefix target_."
  - "A configuration request the exchange accepts by surprise is reversed exactly once, by the case that sent it (margin type: back to the type read before; leverage: back to the leverage read before), and both the acceptance and the undo are recorded. No case restores anything else."
  - "The probe's positions summary carries entry price, mark price, liquidation price and notional but not isolatedMargin, isolatedWallet or maintMargin; those are read from the account answer (positions.<i>.* of the symbol, the quote-asset row, the totals). A missing figure is recorded as NOT_OBSERVED text, never zero."
  - "isolated_position_liquidation_price ends NOT_OBSERVED (all other figures kept) when the exchange row has no liquidationPrice; it computes nothing and imports no risk module (AST-pinned)."
status: complete
requirements-addressed: [EXEC-01, RISK-02]
duration: ~2 h
completed: 2026-10-24
commits: 3
plan_head_before: 3462fb4877c5b5ca696ff94f8b2112e4de9a0bc7
plan_head_after: 905b82a49aa537ae5491d28a4ea3fe77818e16fc
actuals:
  tokens: 27000
  tasks: 3
  commits: 3
---

# Phase 22 Plan 09: the five remaining SJ3 Demo cases and the owner's evidence sections Summary

**The probe now holds all six owner-run Phase 22 Demo cases (margin type with a resting order, leverage above the bracket maximum, margin shortfall at the target leverage, availableBalance with a resting order, isolated liquidation price with every input) and `.planning/DEMO-EVIDENCE-PLAN.md` tells the owner how to run them. No case was run and no agent contacted Binance: criteria 1, 2 and 3 of Phase 22 are NOT Demo-proven until the owner runs the matching cases.**

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | 84f0df22 | `available_balance_with_resting_order`: key, handler, registry, fakes, tests, pins and the session-list entry |
| 2 | 421ab715 | the four other handlers, `margin_order_refusal`/`margin_limit` flag, the two widened owner-key rules, pins |
| 3 | 905b82a4 | sections 25-29, Safety, Step 0 rules, consumers rows, Phase 22 evidence map, document tests |

`commits: 3` counts the commits whose subject names `(22-09)`. `git rev-list --count plan_head_before..plan_head_after` is 5 because the shared tree received two sibling commits (22-08) in between.

## What was built

- `available_balance_with_resting_order` (key `available_balance_resting`): flat precheck, owner caps checked before anything is sent (`check_bounds`), symbol configuration read, account read BEFORE, ONE far resting BUY LIMIT of the approved quantity, account read AFTER while the order rests, cancel. Records the figures before and after, the quote-asset row's open-order initial margin, `config_margin_type`/`config_leverage`, `implied_notional`, `implied_initial_margin` (notional / leverage), the exact Decimal texts `available_balance_delta`, `open_order_margin_delta`, `quote_row_open_order_margin_delta` and the text flags `available_decreased`, `open_order_margin_increased`. No tolerance, no verdict. A missing figure is NOT_OBSERVED text and no delta is written; a rejected order is recorded and the account is still read after it.
- `margin_type_change_with_resting_order` (key `margin_type_resting_order`): flat symbol, configuration read, ONE far resting BUY, ONE change request to the opposite type (CROSSED when the symbol reads ISOLATED, any casing), cancel, configuration read; an accepted change is reversed once (`restore_accepted`, `config_restored_*`). No change is sent if the order was not accepted, filled, or the type is unreadable. The leverage is never touched.
- `leverage_above_bracket_maximum` (key `leverage_above_max`): reads the bracket table, takes `initialLeverage` of bracket 1 from the answer (found by its `bracket` value, wherever it sits), reads the configuration, sends ONE request of maximum + 1; nothing is sent when either value is unreadable; an accepted change is reversed once.
- `margin_insufficient_at_target_leverage` (key `margin_insufficient_target`): requires the configuration to read ISOLATED at exactly the owner's `config_target_leverage` (else NOT_OBSERVED "run symbol_config_change_to_isolated first", nothing changed, nothing sent), then the `insufficient_margin_order` flow with the owner's own `insufficient_margin_quantity`, details under `target_`.
- `isolated_position_liquidation_price` (key `isolated_liquidation`): requires ISOLATED at the target leverage and a flat symbol, opens ONE marketable entry of the approved quantity (caps apply), reads positions, brackets, configuration, account, and records the exchange `liquidationPrice` with entry, mark, notional, margin asset, the full bracket rows, the configuration, the account totals, the symbol's `positions.<i>.*` isolated figures and the quote-asset row. Computes nothing. The runner cleanup closes the position.
- `src/ops/operator_evidence.py`: five keys in script order before `gtd_expiry`; `_MARGIN_CASES` and the widened `_CONFIG_CASES`; refusal messages name every flag.
- `tests/probe_fakes.py`: `fake_account_information(open_order_margin, position)`, `FakeProbePort.resting_order_margin` (a FAKE per-order margin, not an exchange fact), `position_extras`, `account_position_figures`; the limits writer adds the owner numbers for the new flags.
- `.planning/DEMO-EVIDENCE-PLAN.md`: header, Safety (configuration-changing cases; both cap exceptions), Step 0 keys and rules, sections 25-29 (key, owner numbers, what it does, recorded details, consumers, if it stops), session list entries 24-29 with `gtd_entry_expiry_status` as 29, complete session TOML, consumers rows, a Phase 22 evidence map.

## Verification

- `uv run pytest -m "not docker"` on `tests/test_demo_probe_sj3_cases.py`, `test_demo_probe_sj2_cases.py`, `test_demo_probe_sj1_cases.py`, `test_demo_probe_capture_cases.py`, `test_demo_probe_cases.py`, `test_demo_probe_cli.py`, `test_demo_probe_evidence.py`, `test_operator_evidence.py`: all pass.
- `tests/test_phase18_gate.py` .. `test_phase21_gate.py`: all pass.
- `uv run mypy src/ops/operator_evidence.py`: no issues. `uv run ruff check` and `uv run ruff format --check` on the seven touched code files: clean.
- `git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md params config`: clean. `git log --grep="^[a-z]*(22-09):" -- src/adapters src/execution src/risk src/persistence params config` prints nothing.
- Line endings: every touched file kept its own (CRLF in the working tree for all but `tests/test_demo_probe_sj3_cases.py`, which is LF as plan 22-05 left it).
- Evidence label: executed unit tests on fakes [DESIGN]. No [DEMO] claim. Nothing in this plan proves anything about Binance.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Pin update] Tests outside `files_modified` pin the case lists.** `tests/test_demo_probe_sj2_cases.py` asserted `order[-10:-2]` and `CASE_ORDER[-10:]`; both are now relative to the first SJ2 case, so they no longer move when the SJ3 group grows. `tests/test_demo_probe_cases.py` (named in the plan) got the five ids/keys and the slice `[41:47]`. No assertion was weakened.
- **Files modified:** `tests/test_demo_probe_sj2_cases.py`, `tests/test_demo_probe_cases.py`
- **Commits:** 84f0df22, 421ab715

**2. [Rule 3 - Blocking] The session list and TOML of the evidence plan had to change with the code, not only in Task 3.** `tests/test_demo_probe_sj1_cases.py` and `test_demo_probe_sj2_cases.py` pin the document's session list (order of `CASE_ORDER`) and a session TOML with every `EVIDENCE_CASE_KEYS` key on, so Tasks 1 and 2 edited those two parts (the same minimal edit plan 22-05 needed); Task 3 added everything else. Sections 1-23 were not touched.
- **Commits:** 84f0df22, 421ab715, 905b82a4

**3. [Design choice] The shortfall case reuses `_insufficient_margin_order` through keyword arguments** instead of a second handler body, and `margin_order_refusal`/`margin_limit` gained a `flag` argument (`MARGIN_ORDER_FLAGS`). A copy would have broken the sj2 pin that only that function reaches `margin_limit` and duplicated the owner-quantity bound.

### Behaviour worth knowing (not deviations)

- A dry run ends every SJ3 case NOT_REHEARSED with zero mutating calls reaching an adapter. The dry run reads a static CROSSED x20 configuration, so the two cases that require ISOLATED at the target plan no requests; `margin_type_change_with_resting_order` and `leverage_above_bracket_maximum` also list their conditional undo request as planned (the document says it is sent only if the first request is accepted).
- Plan text said the isolated figures come "as the positions summary names them"; the probe's positions summary does not carry `isolatedMargin`, `isolatedWallet` or `maintMargin`, so they are read from the account answer and may be absent on the Demo host (recorded as `NOT_OBSERVED: absent`). If the exchange row has no `liquidationPrice` the case is NOT_OBSERVED.
- `tests/test_phase21_gate.py` and `tests/test_persistence_migration_pg.py` show modified in the shared working tree: they belong to sibling 22-08 and were not touched or staged here.

## Known Stubs

None.

## Threat Flags

None beyond the plan's register. T-22-27: every mutating operation is in `MUTATING_OPERATIONS`; a dry run reaches no adapter (tested for all six cases). T-22-28: flat precheck first and `check_bounds` on every order except the owner-quantity shortfall order (tested with an order, an algo order and a position on the symbol: zero mutating calls; cap tests: nothing sent). T-22-29: an accepted change is undone once by its own case and recorded (tested for both). T-22-30: only raw figures, exact deltas and answers are recorded; the document says criteria 1-3 are not Demo-proven and that `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` changes only through the owner's DECISIONS row. T-22-SC: `git diff --exit-code -- pyproject.toml uv.lock` clean.

## For the owner

No case was run; no agent contacted Binance. Six flags exist in `[optional_cases]` of your probe limits file, each off unless you write `true`:

- `symbol_config_change` (plan 22-05), `margin_type_resting_order`, `leverage_above_max`, `margin_insufficient_target`, `available_balance_resting`, `isolated_liquidation`.

Two conditional numeric keys under `[order]` (no defaults, refused when not needed):

- `insufficient_margin_quantity`: required exactly when `insufficient_margin` OR `margin_insufficient_target` is true.
- `config_target_leverage`: required exactly when `symbol_config_change`, `margin_insufficient_target` or `isolated_liquidation` is true.

Order of use (see `.planning/DEMO-EVIDENCE-PLAN.md`, sections 24 to 29): section 24 first (it leaves the symbol ISOLATED at your leverage and does not restore the old configuration); sections 27 and 29 only afterwards; sections 25, 26 and 28 on any flat symbol; run section 28 twice (current configuration and ISOLATED). The cases change your Demo account only as described in the document. Anything seen is demo-observed, not mainnet (D-19). Until you run them, criteria 1, 2 and 3 of Phase 22 are not Demo-proven; no result sets a number, flips a flag or chooses a parameter, and `AVAILABLE_BALANCE_NETS_RESTING_ORDERS_VERIFIED` stays False until you write a DECISIONS row.

## Self-Check: PASSED

- FOUND: `.planning/phases/22-leverage-margin-liquidation-guard/22-09-SUMMARY.md`, `.planning/DEMO-EVIDENCE-PLAN.md`, `scripts/demo_probe.py`, `src/ops/operator_evidence.py`, `tests/test_demo_probe_sj3_cases.py`
- FOUND commits: 84f0df22, 421ab715, 905b82a4 (`git merge-base --is-ancestor` verified)
