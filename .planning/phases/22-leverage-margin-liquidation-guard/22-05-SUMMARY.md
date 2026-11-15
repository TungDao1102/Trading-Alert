---
phase: 22-leverage-margin-liquidation-guard
plan: 05
subsystem: probe
tags: [demo-probe, symbol-config, isolated-margin, owner-run, D-18, D-19]
requires:
  - phase: 18
    provides: "BinanceProbeAdapter._call, ProbeObservation, the demo_probe case framework (plans 18-12, 18-17, 18-23)"
  - phase: 21
    provides: "SJ2 case group and the evidence-plan session list this plan extends"
provides:
  - "BinanceProbeAdapter.change_margin_type and change_initial_leverage (one signed PLACEMENT-kind call each, never retried, error as data); two names in SDK_REST_METHODS"
  - "scripts/demo_probe.py: SJ3_CASES = (symbol_config_change_to_isolated,), OPTIONAL_CASES key symbol_config_change, handler, ProbePort/GuardedProbePort operations, MUTATING_OPERATIONS entries"
  - "src/ops/operator_evidence.py: key symbol_config_change in EVIDENCE_CASE_KEYS (before gtd_expiry) and DemoOrderLimits.config_target_leverage (int | None, required exactly when the case is on)"
affects: [22-09, 22-16]
tech-stack:
  added: []
  patterns: ["owner opt-in case that mutates the Demo account: flat precheck, previous state recorded, nothing restored, every answer (error included) is evidence"]
key-files:
  created:
    - tests/test_demo_probe_sj3_cases.py
  modified:
    - src/adapters/binance_probe.py
    - src/ops/operator_evidence.py
    - scripts/demo_probe.py
    - tests/probe_fakes.py
    - tests/test_binance_probe.py
    - tests/test_binance_probe_contract.py
    - tests/test_operator_evidence.py
    - tests/test_demo_probe_cases.py
    - tests/test_demo_probe_cli.py
    - tests/test_demo_probe_sj1_cases.py
    - tests/test_demo_probe_sj2_cases.py
    - .planning/DEMO-EVIDENCE-PLAN.md
key-decisions:
  - "The leverage the probe asks for is the owner's key order.config_target_leverage (positive int, required exactly when symbol_config_change is true, refused otherwise, no default); the guard's own constant stays in the guard module (D-02)."
  - "The case never restores the previous configuration; it records previous_margin_type and previous_leverage and a note (22-RESEARCH Open Question 8: the owner decides)."
  - "If the previous configuration cannot be read, the case is NOT_OBSERVED and changes nothing (the owner could not restore what was not recorded)."
  - "Both change requests are always sent on a flat symbol, even when the symbol is already at the target: the answer to a no-op change is itself evidence (already_at_target is recorded)."
status: complete
requirements-addressed: [EXEC-01, RISK-02]
duration: ~50 min
completed: 2026-10-24
commits: 2
plan_head_before: 085fcd317d0f9d82709335d25a8d6b59de8fff1d
plan_head_after: b8dcefaf762014b9066eba0da7f03dc5648179d3
actuals:
  tokens: 11200
  tasks: 2
  commits: 2
---

# Phase 22 Plan 05: symbol_config_change_to_isolated probe case Summary

**The probe can now change a symbol's margin type and leverage, each request sent exactly once, and the first Phase 22 owner-run Demo case, `symbol_config_change_to_isolated`, uses it on a flat symbol and records every exchange answer. No case was run: criterion 1 is NOT Demo-proven until the owner runs it.**

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 (tracer) | 5d81c1d5 | adapter operations, port/guard/dry-run entries, SJ3 case, owner key and flag, fakes, `tests/test_demo_probe_sj3_cases.py` |
| 2 | b8dcefaf | every probe pin updated, adapter/contract/owner-key tests, runbook session list |

`commits: 2` counts the commits whose subject names `(22-05)` before this SUMMARY. `git rev-list --count plan_head_before..plan_head_after` is 5 because the tree is shared with siblings 22-01 and 22-03, whose commits landed in between.

## What was built

- `src/adapters/binance_probe.py`: `change_margin_type(symbol, margin_type)` (checked against the SDK enum, so only "ISOLATED" or "CROSSED"; anything else raises before an SDK call) and `change_initial_leverage(symbol, leverage)` (strict positive int; bool, float, text, zero and negatives raise before an SDK call). Both go through `_call` with call kind PLACEMENT, so a ban refuses them (`ProbeBanned`) and a failed request is returned as data and never repeated. Summaries record `code`/`msg` and `symbol`/`leverage`/`maxNotionalValue` (wire name) only. Module docstring has the plan paragraph.
- `scripts/demo_probe.py`: `SJ3_CASES`, the `OPTIONAL_CASES` entry before `gtd_expiry`, `FIXTURE_CASES` extended (the owner's run writes the first recorded ISOLATED symbol configuration as a scrubbed fixture), the two `ProbePort` operations, the two `GuardedProbePort` delegations (guard first, a dry run raises `MutationRefused` before the adapter), `MUTATING_OPERATIONS`, `_WriteCase.config_target_leverage`, the handler and its `case_` wrapper (`reduce_only=True`, so a hedge account is NOT_OBSERVED like its neighbours) and the registry entry.
- Case flow: read the owner leverage (missing value is a `ValueError` before anything is sent) -> flat precheck (`_require_flat`) -> read configuration (before) -> request ISOLATED -> request the owner leverage -> read configuration (after). Recorded: `config_before_*`, `previous_*`, `already_at_target`, each answer (`margin_type_answer_*`, `leverage_answer_*` with code/msg or class/code/category/text), `config_after_*` with the exchange's own casing of `marginType`, `config_after_margin_type_equals_ISOLATED`, and a note that the previous configuration was NOT restored. An exchange error is evidence: status stays OBSERVED.
- `src/ops/operator_evidence.py`: `symbol_config_change` in `EVIDENCE_CASE_KEYS` (before `gtd_expiry`), `order.config_target_leverage` (`_config_target_leverage` takes the tuple of configuration-changing flags, `_CONFIG_CASES`, which plan 22-09 extends), `DemoOrderLimits.config_target_leverage` (`int | None`, no default).
- Fakes: `FakeProbeRest` SDK methods, `FakeProbePort` operations that move a fake configuration, `RecordingProbePort` planned requests (mutating), `MUTATING_OPERATIONS`, `TEST_ONLY_CONFIG_LEVERAGE = 5` and the limits writer key.
- Tests: 15 new in `tests/test_demo_probe_sj3_cases.py` (registry, dry run plans both and sends nothing, exactly one of each change on a flat symbol, casing recorded as read, already-at-target still sends both, exchange error stays OBSERVED, not flat by open order / algo order / position sends zero changes, unreadable previous configuration, hedge mode, rate-limit stop, fixtures written); adapter tests (one call, enum member, argument refusals, error as data, no retry, ban refusal); contract tests against the installed SDK signature and enum; owner-key tests (required/refused/only-allowed-when/smoke kind/Phase 18 file).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `.planning/DEMO-EVIDENCE-PLAN.md` edited although the plan assigns the document to 22-09.**
- **Found during:** Task 2
- **Issue:** `tests/test_demo_probe_sj1_cases.py` and `tests/test_demo_probe_sj2_cases.py` pin the "One session: all cases" section (case list in `CASE_ORDER`, session TOML with every `EVIDENCE_CASE_KEYS` key on, the command loading it, the last ids of the list in run order). They fail the moment the case exists unless the document lists it, and those files are named in this plan's verification.
- **Fix:** minimal edits: session list item 23 (`symbol_config_change_to_isolated`) with the GTD case renumbered 24; `symbol_config_change = true` and `config_target_leverage = <OWNER: ...>` in the session TOML; the same two keys and the loader rule in Step 0; counts "twenty-three" -> "twenty-four" and "five new keys" -> "six"; a short Step 3 section `### 24.` saying plainly that this case changes the Demo account and does not restore it. `SESSION_VALUES` in the sj1 test gained `config_target_leverage`. Plan 22-09 should extend, not redo, these sections.
- **Files modified:** `.planning/DEMO-EVIDENCE-PLAN.md`, `tests/test_demo_probe_sj1_cases.py`
- **Commit:** b8dcefaf

**2. [Rule 1 - Pin update] Existing tests that asserted exact lists had one element more.** `tests/test_demo_probe_sj2_cases.py` asserted `order[-9:-1] == NEW_CASES` and `CASE_ORDER[-9:]` positions; now `order[-10:-2]`, `order[-2] == symbol_config_change_to_isolated`, `CASE_ORDER[-10:]`. `FIXTURE_CASES` equality in sj1/sj2 gained `*SJ3_CASES`; `tests/test_demo_probe_cases.py` `EXPECTED_ORDER`/`ALL_OPTIONAL` gained the id/key and the slice `dp.SJ3_CASES == EXPECTED_ORDER[41:42]` (the SJ1/SJ2 slices `[28:33]`, `[33:41]` did not move). `tests/test_demo_probe_cli.py` `_MUTATING_CALLS` gained both operations. No assertion was weakened or deleted.

### Stripped from the plan's "pins" list
- `tests/test_demo_probe_capture_cases.py` and `tests/test_demo_probe_evidence.py` needed no change (they pass as they are).

## Known Stubs

None. (`TEST_ONLY_CONFIG_LEVERAGE = 5` exists only in `tests/probe_fakes.py`; the real number is the owner's.)

## Threat Flags

None beyond the plan's register: T-22-11 (both operations in `MUTATING_OPERATIONS`; tested: dry-run guarded port raises `MutationRefused` with zero inner calls, `RecordingProbePort` only plans), T-22-12 (flat precheck; tested with an open order, an algo order and a position: zero change calls and not even the configuration read), T-22-13 (exactly one call per operation; tested at adapter, case and rate-limit level), T-22-14 (owner key, no default; validator tests), T-22-SC (`git diff --exit-code -- pyproject.toml uv.lock docs/DECISIONS.md params config` exits 0).

## For the owner

No case was run; no agent contacted Binance. To run `symbol_config_change_to_isolated` add to your probe limits file:

- under `[optional_cases]`: `symbol_config_change = true`
- under `[order]`: `config_target_leverage = <your whole number>` (required exactly when the flag is true; refused otherwise; there is no default)

then follow `.planning/DEMO-EVIDENCE-PLAN.md` (Step 3, section 24, or the one-session command). The symbol must be flat. The case changes the symbol to ISOLATED and your leverage and does NOT change it back; it records the previous values (`previous_margin_type`, `previous_leverage`) so you can. Anything seen is demo-observed, not mainnet (D-19). Until you run it, criteria 1 and 2 of Phase 22 are not Demo-proven; the evidence label of this plan is executed unit tests on fakes [DESIGN].

## Verification

- `uv run pytest -m "not docker"` on `tests/test_demo_probe_sj3_cases.py`, `test_demo_probe_cases.py`, `test_demo_probe_sj1_cases.py`, `test_demo_probe_sj2_cases.py`, `test_demo_probe_capture_cases.py`, `test_demo_probe_cli.py`, `test_demo_probe_evidence.py`, `test_binance_probe.py`, `test_binance_probe_contract.py`, `test_operator_evidence.py`: all pass.
- `tests/test_phase18_gate.py` .. `test_phase21_gate.py`: pass.
- `uv run mypy src/adapters/binance_probe.py src/ops/operator_evidence.py`: no issues.
- `uv run ruff check` and `uv run ruff format --check` on the 12 touched code files: clean. `uv run python scripts/verify_decision_alignment.py all`: ALL_PASS.
- Line endings: all edited files are CRLF in the working tree (index LF); edits preserved CRLF (every line has its CR).

## Self-Check: PASSED

- FOUND: tests/test_demo_probe_sj3_cases.py, 22-05-SUMMARY.md
- FOUND commits: 5d81c1d5, b8dcefaf (`git merge-base --is-ancestor` verified)
