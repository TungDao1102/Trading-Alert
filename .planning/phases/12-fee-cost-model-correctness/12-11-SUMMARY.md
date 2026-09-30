---
phase: 12-fee-cost-model-correctness
plan: 11
subsystem: decisions-docs
tags: [decisions, d046, d047, d048, risk-management, configuration, regression]
status: complete

requires:
  - phase: 12-01..12-10
    provides: rejection vocabulary, v5 sets, cost producer, live commission, guards, fixtures, cutovers, property tests
provides:
  - DECISIONS D046 (design, adverse-edge supersession, ratification flag), D047 (cost hash canonical text), D048 (regeneration inventory)
  - RISK_MANAGEMENT sections 2, 3, 11 and CONFIGURATION amended by appended text
  - MIN_LAST_DECISION raised to 48 with witness-token tests
  - 12-VALIDATION.md finalized
affects: [phase verification, Phase 13, Phase 14, Phase 17, Phase 24]

actuals:
  tokens: 14000
  tasks: 3
  commits: 4

commits: 4
plan_head_before: 04db6322e543d53f5008da139a7592be7b9f7f83
plan_head_after: a74591adb28b2a29c3ab53fa615f25926196c608

key-files:
  created: []
  modified:
    - docs/DECISIONS.md
    - scripts/decision_alignment/bookkeeping.py
    - tests/test_decision_alignment_bookkeeping.py
    - docs/trading/RISK_MANAGEMENT.md
    - docs/configuration/CONFIGURATION.md
    - .planning/phases/12-fee-cost-model-correctness/12-VALIDATION.md

key-decisions:
  - "D046: quote-per-unit cost formula, adverse-edge risk sizing (supersedes the Phase 5 zone-mid entry only as the sizing entry), exit slippage 3 bps, guards, live ACCOUNT_MAX rule, presence-driven cost key."
  - "D047: canonical numeric text in cost_model_hash only; eight legacy registry cost hashes unchanged."
  - "D048: regeneration inventory generated from git for audit F-608."

requirements-completed: [DOMN-02, RISK-01, BKTS-01]
---

# Phase 12 Plan 11: Decisions, doc amendments and full regression Summary

**D046-D048 are on the record (with the max_cost_to_risk 0.15 to ~0.79 percent minimum-stop consequence flagged as ratification pending), RISK_MANAGEMENT and CONFIGURATION describe the corrected cost model, and the pytest suite plus the decision-alignment dispatcher are green.**

## Accomplishments

- **D046** (design): quote-per-unit formula, adverse-edge sizing (superseding the Phase 5 D-02 zone-mid entry only as the risk-sizing entry; the zone mid stays the min-notional reference), unit rule (F-028 wording follow-up for the next protocol bump), slippage (exit 3 bps, no numeric stress convention in the protocol), guards `STOP_TOO_TIGHT` / `COST_TO_RISK_EXCEEDED`, live rate rule (`ACCOUNT_MAX`, `UNCERTAIN_ACCOUNT_STATE`, Phase 24 wiring, Demo behaviour unverified), records, parameter sets, deferred items (Phase 14 fill causality). Item 6 flags for user ratification that ceiling 0.15 at a ~14 bps round trip implies a minimum stop of ~0.79 percent (0.0014 / (0.15/0.85 + 0.0008)), dominating the 0.3 percent floor; values were not touched.
- **D047**: canonical cost-hash text, the eight legacy registry cost hashes (three distinct values) unchanged, fixture-spelled `1.0` hashes like the registry `1`, Phase 7.1 trailing-precision rule superseded for `cost_model_hash` only, rewritten tests named.
- **D048**: full regeneration inventory (phase4 pins, five params files, seven simulator fixtures and two baseline inputs, two deleted baseline `expected.json`, `parity_overlapping_history`, eleven Phase 5 inputs and five expected files with `DERIVATIONS.md`, phase9 `placement_sequences`, rewritten tests) plus what deliberately did not move.
- `MIN_LAST_DECISION` is 48; new tests: `test_d046_row_carries_witness_tokens`, `test_real_table_reaches_d048`, `test_d047_and_d048_rows_carry_witness_tokens`; the synthetic-append test is next-id aware.
- RISK_MANAGEMENT sections 2, 3, 11 and CONFIGURATION (four keys, unit rule, legacy-set handling, current sets) amended by pure additions (0 deleted lines); all Phase 11 gate tokens preserved.
- 12-VALIDATION.md finalized (`nyquist_compliant: true`, `wave_0_complete: true`, approval complete).

## Task Commits

1. RED: `d98647e` test(12-11) - D046 witness tokens, next-id aware synthetic append
2. Task 1 (tracer): `c6d21f1` feat(12-11) - D046 appended
3. Task 2: `960ecd5` feat(12-11) - D047, D048, MIN_LAST_DECISION 48
4. Task 3: `a74591a` docs(12-11) - RISK_MANAGEMENT, CONFIGURATION, VALIDATION

## Full regression results

| Command | Result |
|---------|--------|
| `.venv/Scripts/python -m pytest -q -p no:cacheprovider` | exit 0, all tests pass |
| `.venv/Scripts/python scripts/verify_decision_alignment.py all` | `ALL_PASS all` |
| `.venv/Scripts/python -m ruff check src tests scripts` | 30 errors, all pre-existing, none in a file touched by Phase 12 |
| `.venv/Scripts/python -m mypy src` | 5 errors in 4 files, all pre-existing, none in a Phase 12 file |

Pre-existing ruff findings (not fixed, per instruction): `scripts/_compute_phase4_fixtures.py`, `scripts/_extend_phase4_candles.py`, `src/adapters/telegram_callbacks.py`, `src/approval/replay.py`, `src/ops/drills.py`, `src/risk/portfolio.py` (F841 at 312-313), `tests/test_backtest_report.py`, `tests/test_core_features.py`, `tests/test_domain_boundary.py`, `tests/test_paper_attribution.py`. Verified by intersecting the ruff file list with `git diff --name-only` since the first Phase 12 commit (empty intersection).

Pre-existing mypy findings: `src/adapters/telegram_notify.py:287` (datetime assigned to Decimal), `src/reconcile/compare.py:517` (no-any-return), `src/ops/drills.py:814` ("None" not callable), `src/paper/supervisor.py:298-299` (object has no isoformat). The plan's literal acceptance criteria for ruff (exit 0) and mypy ("Success: no issues found") therefore cannot be met by this phase; they need a separate cleanup owner.

## Deviations from Plan

1. **[Interpretation] "seven legacy cost hashes":** the repository has eight legacy registry sets (v3, three v4, no-trade/simple-trend v1 and v2) mapping to the three distinct hashes named in the plan; D047 says eight, matching `LEGACY_COST_HASHES` in tests/test_cost_per_unit.py.
2. **[Process] RED for Task 2:** the D047/D048 rows were appended before their witness tests were added, so no separate RED commit exists for Task 2 (the reaches-D048 test cannot be RED once the rows exist without breaking the suite per commit, as the plan itself allowed).
3. **[Inventory wording]** D048 names `feed_stale_no_trade` and `warmup_invalid_no_trade` (the real directory names) rather than the plan's shorthand `feed_stale` / `warmup`.

## Known Stubs

None.

## Open item for the user

D046 item 6: ratify or change `max_cost_to_risk` 0.15 (minimum stop ~0.79 percent at the modeled ~14 bps round trip). Changing it means new v6 parameter sets; nothing was tuned.

## Threat Flags

None.

## Self-Check: PASSED

Modified files exist; commits d98647e, c6d21f1, 960ecd5, a74591a found in `git log`; `git rev-list --count` from the ledger base gives 4.
