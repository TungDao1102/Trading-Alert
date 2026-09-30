# Lane 8: historical_regression

## Scope

- Git history of the snapshot (591 commits, 2026-09-19 .. 2026-09-29), read-only: `git log/show/blame/log -S/-L`, prefix tallies, fixture-modification history, and a scan of test diffs for removed asserts and added skip/xfail.
- Planning artifacts that record decisions, checkpoints, reviews and verification for phases 02–10: `*-PLAN.md` (checkpoint tasks), `*-SUMMARY.md`, `*-REVIEW.md`, `*-REVIEW-FIX.md`, `*-REVIEW-DISPOSITION.md`, `*-VERIFICATION.md`, `STATE.md`, `ROADMAP.md`, `v0.3-MILESTONE-AUDIT.md`.
- Current code, only where it shows a regression: `src/backtest/costs.py`, `src/backtest/simulator.py`, `src/risk/sizing.py`, `src/execution/enablement.py`, `src/analytics/excursion.py`, `src/analytics/inputs.py`, `src/analytics/cli.py`, `src/domain/registry.py`.
- Stage A/B inputs: findings F-001, F-120, F-124, F-901, F-902, F-951, F-953, F-957, and the related F-103, F-109, F-113, F-114, F-115, F-905.
- Probes, in `tmp/historical_regression/`:
  - `probe_costs.py`: cost units in Phase 5 vs Phase 6.
  - `probe_wr12.py`: exit time vs entry time.
  - `probe_excursion.py`: Phase-10 excursion on simulator output.
- Probes ran with the repo venv and `-B`. The snapshot is still clean (`git status --short` is empty).

## Coverage

| File | Level | Note |
|---|---|---|
| git history (all 591 commits) | METADATA_ONLY | Prefix tally. Code commits without a phase reference: only `ea1dd86` and `85c7981`. Fixture-modification list. Assert/skip diff scan |
| src/backtest/costs.py | DEEP_READ | `modeled_costs_per_unit` at 77a0659, 2fd0f75, HEAD; CostModel before and after 3a6b6f3 |
| src/backtest/simulator.py | NORMAL_READ | WR-12 diff 9f5a87d, CR-01 diff 488bcd0, zone_touched origin |
| src/risk/sizing.py | NORMAL_READ | Phase-5 contract at 74a04b8 and HEAD |
| src/execution/enablement.py | NORMAL_READ | d217a2a → 5e9dbb3 diff |
| src/analytics/excursion.py, inputs.py, cli.py (excerpts) | NORMAL_READ | NEGATIVE_INTERVAL path; WR-05/09 contract |
| src/domain/registry.py | NORMAL_READ | `verify_parameter_set` tripwire |
| src/core/planner.py (e0bde92 diff) | NORMAL_READ | 04 CR-03 geometry / TP rule change |
| src/execution/manager.py (1fead61, 2c7f2b7, 150852d, 757b27f stats/diffs) | METADATA_ONLY | Origin of F-951 residual; fixture sequence changes |
| params/*/baseline-v1.toml, baseline-v3.toml (diffs) | NORMAL_READ | bd12652, d0d1bbb, d6bdad4 |
| tests/test_backtest_simulator.py | NORMAL_READ | Docstring vs actual assertions |
| tests/test_backtest_experiment.py (d6bdad4 diff) | NORMAL_READ | `_v3_case_input` rebinding |
| tests/test_approval_message.py, test_approval_replay.py (8532147, db53e6b, 9048ed8, d40d1fd) | NORMAL_READ | Test repairs after 08 REVIEW-FIX |
| tests/test_analytics_approval_delay.py, test_analytics_sidecar.py (29a8374, 504abaf) | NORMAL_READ | Assert removals (duplicate/over-strict; safe) |
| tests/test_paper_resync.py, test_paper_supervisor_backfill.py (ea1dd86) | NORMAL_READ | Commit outside GSD; tenacity wait patch works because wait is resolved at runtime |
| tests/fixtures/phase4/*, phase5/happy_path_long/input.json, phase6/*, phase9/placement_sequences/expected.json | NORMAL_READ | Regeneration history |
| scripts/_regen_phase4_expectations.py, scripts/dev/journal-report.ps1 | NORMAL_READ | Oracle provenance; CLI contract |
| .planning/phases/04-*/04-03-PLAN.md, 04-03-SUMMARY.md, 04-REVIEW-FIX.md, 04-VERIFICATION.md | NORMAL_READ | Checkpoint override |
| .planning/phases/05-*/05-01-SUMMARY.md, 05-REVIEW*.md, 05-VERIFICATION.md, 05-CONTEXT.md | NORMAL_READ | |
| .planning/phases/06-*/06-01-PLAN.md, 06-01-SUMMARY.md, 06-REVIEW.md, 06-REVIEW-FIX.md, 06-VERIFICATION.md, 06-RESEARCH.md, 06-PATTERNS.md, 06-CONTEXT.md | DEEP_READ | Core of the fee-unit and lookahead lineage |
| .planning/phases/07.1-*/07.1-01-PLAN.md, 07.1-01-SUMMARY.md, 07.1-REVIEW.md, 07.1-VERIFICATION.md | NORMAL_READ | |
| .planning/phases/08-*/08-REVIEW.md, 08-REVIEW-FIX.md | NORMAL_READ | |
| .planning/phases/09-*/09-REVIEW.md, 09-REVIEW-FIX.md, 09-REVIEW-DISPOSITION.md, 09-01-SUMMARY.md | NORMAL_READ | |
| .planning/phases/10-*/10-REVIEW.md, 10-REVIEW-FIX.md, 10-07-PLAN.md, 10-UI-SPEC.md, 10-CONTEXT.md | NORMAL_READ | |
| .planning/phases/0{1,2,3,5,7,7.1,8,9,10}-*/*-PLAN.md (checkpoint tasks), *-SUMMARY.md (checkpoint records) | METADATA_ONLY | grep of checkpoint type/gate and resolution text |
| .planning/STATE.md, ROADMAP.md, v0.3-MILESTONE-AUDIT.md | NORMAL_READ | Deferred items, P11 goal, staleness claims |
| docs/configuration/CONFIGURATION.md §5 | NORMAL_READ | Immutable sets |
| lanes/*.md (stage A/B) | NORMAL_READ | Known-defect definitions |

## Known-defect origin trace (task item 1)

This section only traces lineage. The defects themselves are reported under their own IDs.

| Defect | Introduced by | Carried / widened by | Review or verification that should have caught it | Why it did not |
|---|---|---|---|---|
| **F-001** fee-unit bug (rate added to a price distance; P11) | `77a0659` feat(06-01), 2026-09-26 12:29. `modeled_costs_per_unit` returns `fee_rate_entry + fee_rate_exit + expected_slippage`, with the docstring "per-unit cost in quote currency … simplified for the tracer slice". The Phase-5 contract (`74a04b8`) had used quote-per-unit: the phase-5 fixtures carry `"modeled_costs_per_unit": "1.0"` at BTC 50 000, which is 2 bps in quote units (probe_costs.py). See F-801. | `fffef34` feat(07-01): paper calls it. `7e6347a` feat(09-01): live manager calls it. `d6bdad4` (07.1) binds the rates into baseline-v3 | **Caught and dropped:** 06-REVIEW IN-04 (14:42, Info, "rates to price distances … semantics suspect") and deep WR-13 (15:26). 06-REVIEW-FIX skipped WR-13 and WR-03 as "Opened as a cross-phase item; no code touched", but no item exists (F-802). 06-VERIFICATION 01-3 marked costs "✓ VERIFIED" with IN-04 kept as Info. 05-VERIFICATION SC1 "VERIFIED" (F-109). 07-REVIEW and 09-REVIEW never mention `modeled_costs`. | The reviewer framed it as "parity preserved", so both sides were wrong identically. The parity test re-derives the formula by hand (06-REVIEW IN-02a). There was no dimensional oracle. The skip was never recorded as a tracked item. It was tracked only through backlog 999.5 (`a0ef5fc`, 2026-09-29 17:40), which the user added |
| **F-120 / F-901** backtest same-bar lookahead | `77a0659` feat(06-01), following the **plan**: 06-01-PLAN:97 has the "1m map keyed by symbol plus strategy-bar close_time_utc", and :109 has fill "when a strategy-bar range touches the zone". The plan dropped 06-RESEARCH:267 Pitfall 2 ("1m resolution consumes only 1m candles strictly inside `(entry_bar.open, exit_bar.close]`"), which 06-PATTERNS:144 had repeated | `9f5a87d` 06 WR-12 fix: the exit is stamped with the deciding 1m minute, so exit < entry becomes visible, but no test covers it (F-804). `488bcd0` CR-01 widens the SL fallback to `[]` | 06-REVIEW CR-04 (expiry clock) and IN-02b ("no-lookahead test appends a post-horizon candle AFTER the exit was decided on 1m candle 0"). 06-VERIFICATION 01-8 "✓ VERIFIED … intrabar keyed per-bar" | CR-04 was skipped as "needs a planner/simulator design call", never tracked (F-802). IN-02 was Info, so it was out of the fix scope. The verifier checked the strategy prefix slice and read the per-bar key as the guard. The simulator has no golden digests at all (F-805), so no oracle existed |
| **F-902** zone-touch fill at mid | Planner: `df27af6` feat(04-01) (tracer `entry_ref` = zone mid), locked by the 04-03 checkpoint "option A", auto-selected with gate=non-blocking (04-03-SUMMARY:76). Simulator: `77a0659`, `zone_touched = bar.high >= entry_min and bar.low <= entry_max`, per 06-01-PLAN:109 wording | Paper reuses the simulator semantics | 06-REVIEW (32 findings) and 06-VERIFICATION ("limit fills" VERIFIED, BKTS-01 PARTIAL only for G2/G3) | No review compared the simulated fill rule with the live limit price (`placement.py` mid). Fixtures come from `scripts/gen_phase6_fixtures.py` (self-oracle) |
| **F-957** `partial_fill_fraction = 0.5` | The value first appears as the `limit_partial_fill` fixture case in `08a626b` / `6d2d9b7` (06-01, `cost["partial_fill_fraction"] = "0.5"`). It was promoted into the registry by `d6bdad4` feat(07.1-01) per 07.1-01-PLAN:93 ("never 1.0, which normalizes to int") | `d6bdad4` also adds a test helper `_v3_case_input` that rewrites every phase-6 fixture's cost dict from "1.0" to "0.5" in memory (F-812). Paper pins baseline-v3 | 07.1-REVIEW (discusses only the `0.5` spelling, L60-67, L249). 07.1-VERIFICATION:61-62 lists "`partial_fill_fraction = 0.5` fractional" as a ✓ VERIFIED must-have | Verification enforced the plan's value as a requirement. The trading meaning (half-filled candidate vs full-filled baselines) was never questioned |
| **F-951** clientOrderId dedup assumption | `c267970` docs(08) 08-CONTEXT D-04 and `a57a901` 08-RESEARCH:305 ("exchange is the dedup authority"). Code: `7e6347a` (09-01) manager with no persisted execution intent | `1fead61` 09 CR-08 fix adds the docstring "consuming the approval … is NOT handled here". `2c7f2b7` CR-09 fix removes adapter retries (single-call mitigation only) | **Caught and dropped:** 09-REVIEW CR-08/CR-09 (72febd8) state that "Binance deduplicates … only among open orders" and "Nothing marks the approval as consumed". 09-REVIEW-FIX CR-08 is "fixed (partial) … Not done". 09-REVIEW-DISPOSITION records "fixed" (F-808) | 08-03 tests use fakes with "same ID ⇒ same order" semantics. The partial status was lost in the disposition table. 08-CONTEXT D-04 and EXECUTION_SPEC were never corrected. There is no 08 or 09 VERIFICATION |
| **F-953** enable() accepts WITHIN_BUDGET | `d217a2a` feat(09-03): enable() with no kill-gate input. `5e9dbb3` feat(10-07): adds `kill_gate_state` exactly as 10-07-PLAN:189 prescribes ("WITHIN_BUDGET and PASSING_CANDIDATE permit enable()"). All 7 test call sites were updated to pass `KillGateState.WITHIN_BUDGET` (10-07-PLAN:191), which pins the permissive behaviour | none | 10-REVIEW WR-10 ("Any caller can pass WITHIN_BUDGET") was **skipped** (design decision). The 10-05 decision checkpoint was auto-approved (F-124). There is no 10-VERIFICATION | The plan authored the rule, the review flagged it, and the fix was deferred to a human who was never asked |

## Verified Safe Areas

- **Phase-9 review-fix fixture edits are justified.**
  - `150852d` (CR-05) and `757b27f` (WR-02) change `tests/fixtures/phase9/placement_sequences/expected.json` only by inserting the new `query_algo_order_by_client` and `get_position_mode` calls into `method_sequence`.
  - The client ids and plan hash are unchanged, and each commit adds tests (+95 and +61 lines).
- **Assert removals in phase 10 are not weakening.**
  - `29a8374` drops `test_paper_section_digest_is_repinned_after_bucket_fields`. The same pin still lives in `tests/test_analytics_approval_delay.py:121`.
  - `504abaf` drops `", " not in body`. That check is redundant with the byte-equality check against `json.dumps(..., separators=(",", ":"))` at :162, and could false-fail on string values.
- **Test repairs after 08 REVIEW-FIX are consistent, not loosened.**
  - `db53e6b` and `9048ed8` now expect the extra CALLBACK_REJECTED/RESOLVED journal events that WR-04 introduced, and assert more than before.
  - `d40d1fd` uses real derived short ids.
  - `8532147` adds a one-name allowlist (`SHORT_ID_LENGTH`) to the synonym guard. This is a narrow exemption.
- **No skip or xfail was added to hide behaviour.**
  - The scan found skip additions only in 9e41a6d, 703b2a5, 297e70a, b92778f, 9fcb0dc, 2fa30f8 and 0950fb4.
  - All of them are PostgreSQL- or platform-gated (`TEST_DATABASE_URL` / win32), which matches the 7 PG-gated skips in `tool-output/pytest.txt`.
- **Commits outside GSD (`ea1dd86`, `85c7981`) are benign.**
  - `ea1dd86` monkeypatches `tenacity.wait_random_exponential`. That is effective, because `src/paper/resync.py:184` and `supervisor.py:210` resolve the wait at call time.
  - `85c7981` adds dev scripts.
- **Phase-10 fixes CR-01, WR-04, WR-07 and WR-11 do not break earlier-phase callers.**
  - `enable()` and the analytics CLI have no `src/` callers (M1).
  - The journal-report wrapper was updated in the same commits.
  - No phase-10 golden changed (10-REVIEW-FIX: "no fixture under tests/fixtures/phase10/ changed").
  - The contract drift that remains is F-811.
- **The 07.1 WR-03 CostModel coercion (`3a6b6f3`) has no effect on existing inputs.**
  - `build_cost_model` already coerced every field, so the hashes from registry/fixture inputs are unchanged.
  - Only direct `CostModel(...)` construction with str values is affected.

## Findings

### F-801 — Phase 6 silently redefined the Phase-5 `modeled_costs_per_unit` contract from quote-per-unit to a dimensionless rate sum

- **ID:** F-801
- **Severity:** MEDIUM. The money consequence is counted under F-001 (HIGH, P11).
- **Confidence:** CONFIRMED (git and a probe)
- **Classification:** DEFECT (cross-phase regression)
- **Category:** regression / cost model
- **Component:** src/backtest/costs.py `modeled_costs_per_unit`
- **File:** `src/backtest/costs.py`
- **Lines:** 184-203
- **Invariant:** INV-053, INV-054, AMB-002
- **Phase/commit:** 05 `74a04b8` (contract) → 06 `77a0659` (break)
- **Known-prior:**
  - KNOWN: F-001 / ROADMAP P11 (bug), 06-REVIEW IN-04 and WR-13.
  - NEW: this is a regression of an established Phase-5 contract, not an original ambiguity. The costs.py docstring contradicts its own return value.
- **Evidence:**
  - Phase 5 (`74a04b8`) shipped `size_position(..., modeled_costs_per_unit)` with `risk_per_unit = sl_distance + modeled_costs_per_unit`. Its parity fixtures use `"modeled_costs_per_unit": "1.0"` at entry_ref 50 000 and SL 49 000 (`tests/fixtures/phase5/happy_path_long/input.json:41`), i.e. a quote amount (probe: implied rate 2e-05).
  - 05-CONTEXT D-01 says "Modeled costs per unit include entry+exit fee + expected slippage".
  - 06-PATTERNS:359 kept `"1.0"`.
  - `77a0659` introduced `return _add(_add(fee_rate_entry, fee_rate_exit), expected_slippage)`, with the docstring "Return the per-unit cost in quote currency … simplified for the tracer slice". The probe shows it returns `0.0008` for trend-pullback baseline-v3.
  - The 06-01-PLAN:97 action says only "modeled_costs_per_unit delegating to the same per-unit formula src/risk/sizing.py size_position consumes". Sizing has no formula, so the executor invented one.
- **Expected:** When a function is consumed across phases, its unit (quote per base unit) stays the unit the owning phase established and tested.
- **Actual:**
  - The Phase-6 implementation returns a rate.
  - Every Phase-5 test still passes, because sizing accepts any Decimal.
  - Paper (`fffef34`) and live (`7e6347a`) then consumed the Phase-6 function.
- **Reproduction:** `PYTHONPATH=snapshot python -B tmp/historical_regression/probe_costs.py`
- **Impact:**
  - This is the origin of F-001 in backtest, paper and live.
  - "Tracer simplification" wording was never revisited.
- **Why tests miss it:**
  - The Phase-5 parity tests inject the cost value directly.
  - The Phase-6 cost-parity test re-derives the rate-sum by hand (06-REVIEW IN-02a).
  - No test checks units (for example, cost ≈ price × rate).
- **Remediation:**
  - Covered by P11.
  - In addition, add a cross-phase contract test: for any cost model and entry price, `modeled_costs_per_unit` must scale linearly with price.
  - Fix the docstring.

### F-802 — 06-REVIEW-FIX closed three skips as "Opened as a cross-phase item", but no such item exists

- **ID:** F-802
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP (process)
- **Category:** review follow-through
- **Component:** 06-REVIEW-FIX skip handling
- **File:** `.planning/phases/06-backtest-simulator-experiment-registry/06-REVIEW-FIX.md`
- **Lines:** 283-325
- **Invariant:** INV-003, INV-053
- **Phase/commit:** 06 / `efa09f6`
- **Known-prior:**
  - PARTIAL: F-905 (funding WR-03 has no owner) and F-901 (CR-04 never scheduled).
  - F-115 covers only the 09/10 skips.
  - NEW: the fix report *claims* tracking that does not exist, and the fee-unit bug (WR-13/IN-04) sat behind that claim for 3 days while two more phases were built on it.
- **Evidence:**
  - 06-REVIEW-FIX WR-03: "Opened as a cross-phase item; no code touched."
  - WR-13: "Opened as a cross-phase item; no code touched."
  - CR-04: "Needs a planner/simulator design call before any code change."
  - `grep -rln "cross-phase" .planning` finds only 06-REVIEW, 06-REVIEW-FIX, 06-VERIFICATION and a heading in v0.3-MILESTONE-AUDIT.
  - STATE.md:259-269 Deferred Items has no entry for any of the three.
  - There is no `.planning/todos/`.
  - ROADMAP has no item until backlog 999.5 (`a0ef5fc`, 2026-09-29 17:40), which covers only the fee part.
  - CR-04 (the same-bar/expiry design, i.e. F-901) is still untracked.
- **Expected:** A skip that cites "cross-phase" creates a tracked artifact (STATE deferred row, backlog item or ROADMAP phase) in the same commit.
- **Actual:**
  - The claim is prose only.
  - 07-01 (6.5 h later) and 09-01 consumed `modeled_costs_per_unit`.
  - Neither 07-REVIEW nor 09-REVIEW mentions it.
- **Reproduction:** Run the grep commands above on the snapshot.
- **Impact:**
  - Known HIGH defects (F-001, F-901, F-905) stay invisible to planning.
  - The user found the fee bug independently on the last day.
- **Why tests miss it:** Process artifact.
- **Remediation:**
  - Make gsd-code-fixer "skipped: cross-phase" require a STATE Deferred-Items row or a backlog id, and have the disposition gate reject a skip without it.
  - Now: add backlog items for 06 CR-04 (cross-bar lifecycle) and WR-03 (funding).

### F-803 — The 06 and 08 REVIEW-FIX waves (57 fixes) were committed without running the affected test suites; the "no regression" claims are vacuous

- **ID:** F-803
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP (process)
- **Category:** review-fix verification
- **Component:** gsd-code-fixer runs for phases 06 and 08
- **File:** `.planning/phases/06-backtest-simulator-experiment-registry/06-REVIEW-FIX.md`
- **Lines:** 23-37
- **Invariant:** —
- **Phase/commit:** 06 `488bcd0`..`177fd57`; 08 `2fbcbca`..`0bf2fdf`
- **Known-prior:** NEW
- **Evidence:**
  - 06-REVIEW-FIX:23-37 says "Full phase-6 subset … **23 passed / 13 failed — byte-identical to the pre-fix baseline**. All 13 failures are `ModuleNotFoundError: No module named 'structlog'` … system Python (3.14.3)". The 13 failures are exactly the simulator tests.
  - WR-02 fix (06-REVIEW-FIX): "cannot be validated while simulator tests are structlog-blocked".
  - 08-REVIEW-FIX:24-30 says "The full pytest suite could not run here (`structlog`/`tenacity`/Binance SDK not installed …); Tier 2 failures … did not block commits".
  - The 08-REVIEW-FIX `review_path` is `C:/Users/daotu/OneDrive/Documents/Trading-Alert/...`, a different checkout.
  - Four follow-up commits repaired tests that the 08 fixes had broken (23:35-23:37): `8532147`, `db53e6b`, `9048ed8`, `d40d1fd`.
  - The 06 WR-12 fix `9f5a87d` touched `src/` only, with no test, and changed observable output (F-804).
  - For contrast, 02, 03, 04, 05, 07, 07.1, 09 and 10 each report a full `uv run pytest`.
- **Expected:** Every fix is verified by the project suite in the project environment (uv/.venv, Python 3.13) before it is committed.
- **Actual:** 23 + 34 behavioural fixes to the backtest core and the approval/reconciliation core were committed with the relevant tests failing on import.
- **Reproduction:** Read the cited report lines and `git log --grep='^fix(0[68])'`.
- **Impact:**
  - Regressions from these waves were caught only by chance.
  - F-804 is one that was not caught.
  - 06-VERIFICATION, written against a pre-fix view, then reported CR-01 and CR-03 as open.
- **Why tests miss it:** The tests were not run.
- **Remediation:**
  - The fixer must refuse to commit when the in-scope suite cannot import. It should run under `uv run` and never under the system Python.
  - Re-run the full suite at each fixed SHA for phases 06 and 08 (bisect) to confirm that no intermediate commit was broken.

### F-804 — The 06 WR-12 review fix makes `exit_time_utc` precede `entry_time_utc`, so Phase-10 MFE/MAE drops every 1m-resolved backtest trade as NEGATIVE_INTERVAL

- **ID:** F-804
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED (probe)
- **Classification:** DEFECT (cross-phase regression)
- **Category:** regression / backtest→analytics
- **Component:** src/backtest/simulator.py `run` / `resolve_intrabar`; src/analytics/excursion.py
- **File:** `src/backtest/simulator.py`
- **Lines:** 862-878 (exit stamping); `src/analytics/excursion.py:192-196`
- **Invariant:** INV-003, INV-104
- **Phase/commit:** 06 `9f5a87d` (WR-12) → consumed by 10 (`src/analytics/excursion.py`)
- **Known-prior:**
  - Root: F-120/F-901 (same-bar lookahead).
  - NEW:
    - The review fix turned a hidden inconsistency (exit = entry = bar close) into a temporal inversion.
    - No test was added.
    - The Phase-10 analytics silently turn it into INCOMPLETE rows.
- **Evidence:**
  - Before `9f5a87d`: `exit_time_utc=bar.close_time_utc`, which is equal to the entry time.
  - After: `exit_time_utc=outcome.exit_time_utc` (the deciding 1m candle's close).
  - The 1m candles are those of the signal bar itself.
  - `probe_wr12.py`:
    - `intrabar_both_touched`: `entry 2026-09-11T09:59:59+00:00 exit 2026-09-11T09:00:59+00:00 EXIT_BEFORE_ENTRY`.
    - The same result for `intrabar_both_touched_short` and `limit_partial_fill`.
  - `probe_excursion.py`: `normalize_backtest` + `compute_trade_excursion` returns `IncompleteReason.NEGATIVE_INTERVAL`, because of `excursion.py:194`: `if exit_time < entry_time: return _incomplete(... NEGATIVE_INTERVAL)`.
  - The WR-12 runtime check in 06-REVIEW-FIX checked only "SL touch on candle 2 stamps candle 2's close".
- **Expected:**
  - `exit_time_utc >= entry_time_utc` for every trade record, asserted by a test (the F-901 remediation).
  - A review fix that changes an output field gets a regression test.
- **Actual:**
  - Every non-fallback, non-EOD backtest trade has exit before entry.
  - The Phase-10 MFE/MAE section for BACKTEST evidence will be incomplete for all such trades.
  - The Phase-10 tests use hand-written evidence (`tests/fixtures/phase10/loaders/evidence_sample.json`), not simulator output.
- **Reproduction:** `PYTHONPATH=snapshot python -B tmp/historical_regression/probe_wr12.py` and `probe_excursion.py`
- **Impact:**
  - Backtest excursion diagnostics (METRICS §6: TP too close, SL too tight) are empty.
  - The red flag that would have exposed F-901 on 2026-09-26 was produced but never looked at.
- **Why tests miss it:**
  - `9f5a87d` added no test.
  - No test checks entry/exit ordering.
  - The Phase-10 goldens do not come from the simulator.
- **Remediation:**
  - Fix together with F-901 (cross-bar lifecycle).
  - Until then, add the ordering assertion so the suite fails loudly.
  - Add an integration test simulator → `normalize_backtest` → excursion.

### F-805 — 06-01 commits do not match the 06-01 plan: simulator goldens and hash pinning were never built, the implementation was committed before its tests, and verification accepted the gap

- **ID:** F-805
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DRIFT (plan ↔ commit)
- **Category:** test oracle / plan compliance
- **Component:** tests/test_backtest_simulator.py, tests/fixtures/phase6/*
- **File:** `tests/test_backtest_simulator.py`
- **Lines:** 1-40
- **Invariant:** INV-003
- **Phase/commit:** 06 / `77a0659`, `6d2d9b7`, `08a626b`, `114e483`
- **Known-prior:**
  - 06-01-SUMMARY "Known Limitations" admits the omissions.
  - 06-REVIEW IN-02(d).
  - NEW:
    - Verification passed it anyway.
    - Stage-B F-901/F-120 say "golden fixtures pin the current semantics byte for byte". This is inaccurate for the simulator: nothing pins its bytes.
- **Evidence:**
  - Plan vs build:
    - 06-01-PLAN:13-25 and :169 list `expected.json` for 7 case directories.
    - :97 says "asserts sha256_hex of the canonical trade dict equals expected.json".
    - Threat model T-06-02 (:145): "Canonical sha256_hex equality assertions fail the suite on any fixture mutation".
    - The tree has only `input.json` in each simulator case directory.
    - The test module docstring still says "asserts the canonical-JSON hash of the trade list matches".
    - `_load_expected` is never called.
  - Commit order:
    - `77a0659` (impl, 12:29:15) precedes `08a626b` (fixtures, 12:29:31) and `114e483` (tests, 12:29:40), against the plan's "RED first … confirm it errors on missing src.backtest".
    - The distinguishing fixture `risk_parity_nonzero_costs` from 06-PATTERNS:370 was never created.
  - 06-01-SUMMARY:116-124 lists these limitations:
    - "expected.json files not generated"
    - "test_domain_no_float.py not extended"
    - "mypy strict not run"
    - It also lists a nonexistent "Plan 06-04: CLI integration" as a next step.
  - 06-VERIFICATION:113 rates the tests "Pinned behavioral suites ✓ VERIFIED".
- **Expected:** The golden digest per case is implemented as planned, or the deviation is re-planned; verification does not credit pinning that does not exist.
- **Actual:** The simulator's trade outputs (prices, quantities, times, PnL) are unpinned. The tests assert only `entry_kind`/`exit_kind`/flags and run-twice equality.
- **Reproduction:** `ls tests/fixtures/phase6/intrabar_both_touched` shows `input.json` only. Also run `git log --format='%h %ad %s' --date=format:%T --grep=06-01`.
- **Impact:**
  - Any change to simulator math, including F-804 and cost changes, passes silently.
  - Good news for remediation: fixing F-901, F-902 or F-001 does not need a regeneration of the phase-6 simulator goldens, only new assertions.
- **Why tests miss it:** They are the gap.
- **Remediation:**
  - Add per-case `expected.json` with values from an independent hand oracle, not from the implementation.
  - Add the missing nonzero-cost parity fixture.
  - Correct the stage-B "why tests miss" text for F-901/F-120.

### F-806 — A Phase-4 review fix overrode the one-way 04-03 checkpoint decision (TP rule) and regenerated goldens from the new code, after verification had passed

- **ID:** F-806
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DRIFT (decision regression)
- **Category:** REVIEW-FIX vs recorded decision
- **Component:** src/core/planner.py; tests/fixtures/phase4/*
- **File:** `.planning/STATE.md`
- **Lines:** 124
- **Invariant:** —
- **Phase/commit:** 04 / `e0bde92`, `2e19c5a`, `1c3c187` (after 04-VERIFICATION `6bdbe4c`)
- **Known-prior:**
  - F-113 (the geometry differs from the family sheets), F-103 (TP2 multiple not registered).
  - NEW:
    - The overridden artifact is a recorded one-way checkpoint decision.
    - STATE and SUMMARY still assert the old rule.
    - The change landed after the phase was marked passed.
- **Evidence:**
  - 04-03-PLAN:73 is a `checkpoint:decision`, "Lock TP2 rule …", with reversibility "one-way" (:123).
  - 04-03-SUMMARY:76-80: "Auto-selected **option A** … TP2 = entry_ref + 2 * minimum_rr * risk … TP1 = entry_ref + minimum_rr * risk".
  - STATE.md:124 repeats this.
  - `e0bde92` (2026-09-24 22:54) replaces it: "TP1 is structure-derived … TP2 extends the structure move: entry ± 2 * (TP1 − entry)".
  - `2e19c5a` moves the Family B stops "so structure RR can clear minimum".
  - `1c3c187` (2026-09-25 00:52) regenerates `expected_plans/signals/features.json` with `scripts/_regen_phase4_expectations.py`, from the corrected code, e.g. `tp1 53910.74 → 52840.00`.
  - 04-VERIFICATION (`6bdbe4c`, 2026-09-24 22:16) says `status: passed`, 14/14. It was never re-run.
  - 04-REVIEW-FIX:68 says "**Human verification requested:** TP/SL construction is a strategy-semantics choice". No record of that verification exists.
- **Expected:**
  - Changing a one-way checkpoint decision re-opens the checkpoint (a human decision) and updates STATE/SUMMARY/family sheets.
  - The phase is re-verified after behaviour-changing fixes.
- **Actual:**
  - The executor/fixer changed strategy semantics.
  - The oracle was regenerated from the new code.
  - Status artifacts still describe the old rule.
- **Reproduction:** `git show e0bde92 -- src/core/planner.py`; `git show 1c3c187 -- tests/fixtures/phase4/expected_plans.json`; compare with STATE.md:124.
- **Impact:**
  - The TP/SL geometry that all backtest evidence uses was chosen by a review-fixer. The human never saw it, and the recorded decision says something else.
  - The kill-gate family evidence rests on it (see F-113).
- **Why tests miss it:** The goldens were regenerated from the implementation in the same wave.
- **Remediation:**
  - Record the new TP/SL rule as a DECISIONS row with a human sign-off.
  - Update STATE.md:124 and 04-03-SUMMARY.
  - Re-run 04 verification.
  - Forbid fixture regeneration inside REVIEW-FIX when a finding is marked "human verification requested".

### F-807 — Four phases' VERIFICATION reports predate their review-fix waves; the milestone audit counts them as passed

- **ID:** F-807
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** verification staleness
- **Component:** .planning/phases/{02,04,05,07.1}-*/*-VERIFICATION.md
- **File:** `.planning/v0.3-MILESTONE-AUDIT.md`
- **Lines:** 214-234
- **Invariant:** —
- **Phase/commit:** 02, 04, 05, 07.1
- **Known-prior:**
  - KNOWN for 06 (milestone audit: "06-VERIFICATION stale … pre-fix").
  - F-109 (05 verdict wrong on the merits).
  - NEW: the same ordering defect in 02, 04, 05 and 07.1.
- **Evidence:** Git first/last commit times for each artifact:

  | Phase | VERIFICATION | REVIEW | REVIEW-FIX | Fix commits after verification |
  |---|---|---|---|---|
  | 02 | `a02851a` 09-22 00:03 | 00:23–20:03 | 02:00–20:12 | 36 `fix(02)`, last `6a096e4` 20:11 |
  | 04 | `6bdbe4c` 09-24 22:16 | 22:16–22:28 | `02c3637` 09-25 00:56 | 12, including geometry and golden regeneration (F-806) |
  | 05 | `cd2f6e9` 09-25 22:28 | 22:43 | 23:10 | 13, including CR-01 (position side), CR-02 (stale constraints), WR-03 (daily state) |
  | 07.1 | `ac935d3`/`bffb6df` 09-26 19:12–19:15 | 19:00–20:26 | 20:54 | 3 (WR-01..03, CostModel coercion) |

  - 06-VERIFICATION was committed at 16:53, after the fixes (15:40–15:57), but reports CR-01 and CR-03 as open "CONFIRMED in code". It verified a pre-fix view.
  - v0.3-MILESTONE-AUDIT:222: "Phases verified 6/11 | 01–05, 07.1".
- **Expected:** Verification runs after the last behaviour-changing commit of the phase, and its `covered_digest` matches HEAD of the covered files.
- **Actual:** Verifications certify code that no longer exists. The milestone audit and REQUIREMENTS use them as evidence.
- **Reproduction:** For each phase `p`, run `git log --reverse --format='%h %ad' -- .planning/phases/<p>-*/<p>-VERIFICATION.md` against `git log --grep="^fix(<p>)"`.
- **Impact:** "Verified" phases 02, 04, 05 and 07.1 carry unreviewed post-verification behaviour. This includes the risk-engine fail-closed changes and the Phase-4 strategy geometry.
- **Why tests miss it:** Process artifact. `covered_digest` exists (06) but nothing compares it.
- **Remediation:**
  - Re-verify 02, 04, 05, 06 and 07.1.
  - Have the milestone audit compare each VERIFICATION `covered_digest`/timestamp with the latest fix commit touching its covered files.

### F-808 — Review dispositions flatten partial fixes to "fixed", and about 30 fixes flagged "requires human verification" were never verified

- **ID:** F-808
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED
- **Classification:** GAP (process)
- **Category:** review bookkeeping
- **Component:** 09-REVIEW-DISPOSITION.md; *-REVIEW-FIX.md (04, 07, 08, 09, 10)
- **File:** `.planning/phases/09-live-execution-rollout/09-REVIEW-DISPOSITION.md`
- **Lines:** 130-152
- **Invariant:** INV-087
- **Phase/commit:** 04, 07, 08, 09, 10
- **Known-prior:**
  - PARTIAL: the milestone audit says "7 fixes to review" for phase 10 only.
  - F-115 covers skipped (not partial) items.
  - NEW:
    - The partial fixes are shown as "fixed".
    - The cross-phase total is 30 unverified human-verification items.
- **Evidence:**
  - 09-REVIEW-FIX:20: "Ten of these are marked 'requires human verification'. Three of those ten (CR-04, CR-08, WR-06) are only partial fixes".
  - CR-08: "**Not done** … marking the approval as consumed". This is the F-951/F-126 residual.
  - WR-06: "**Not done:** detecting the limit dynamically from `MAX_NUM_ALGO_ORDERS` … literal 200 stays". Compare F-051: the limit is account-wide.
  - CR-04: "**Not done** … resizing TP1".
  - 09-REVIEW-DISPOSITION shows `CR-04 | fixed`, `CR-08 | fixed`, `WR-06 | fixed`. The vocabulary has no "partial" value.
  - Count of "requires human verification" markers: 04 = 4, 07 = 4, 08 = 5, 09 = 10, 10 = 7.
  - No 07, 08, 09 or 10 VERIFICATION exists, and 04's predates the fixes (F-807).
- **Expected:**
  - The disposition vocabulary includes `partial`, with the open remainder tracked.
  - Human-verification-required fixes are listed in VERIFICATION `human_verification` and cleared by the user.
- **Actual:** The residual live-money risks (duplicate entry on replay, the hard-coded 200-algo headroom) show as closed.
- **Reproduction:** Compare 09-REVIEW-FIX:83,122,212 with 09-REVIEW-DISPOSITION rows.
- **Impact:** A reader of the disposition gate, or the milestone audit, sees 21/22 critical/warning fixed. The approval-replay duplicate-entry risk (F-951, HIGH) is hidden.
- **Why tests miss it:** Process artifact.
- **Remediation:**
  - Add the `partial` disposition.
  - Back-fill CR-04, CR-08 and WR-06 as partial, with backlog ids.
  - Put the 30 human-verification items into the pending 07–10 VERIFICATION runs.

### F-809 — More one-way and blocking checkpoints were cleared without a recorded human decision (beyond F-124)

- **ID:** F-809
- **Severity:** MEDIUM
- **Confidence:** CONFIRMED (records)
- **Classification:** GAP (process)
- **Category:** human gates bypassed
- **Component:** checkpoint tasks in 02-05, 03-01, 03-02, 03-04, 05-01, 07.1-01, 04-03
- **File:** `.planning/phases/03-domain-registry-fixtures/03-04-SUMMARY.md`
- **Lines:** 207-216
- **Invariant:** —
- **Phase/commit:** 02, 03, 04, 05, 07.1
- **Known-prior:**
  - F-124 covers 09-01 (ACK-ONE-WAY by auto-executor), 10-05 (auto-approved), 08-02 and 09-04.
  - F-910/F-108 cover the backup target on its merits.
  - NEW: the checkpoint instances listed below.
- **Evidence:** Checkpoint inventory (`grep '<task type="checkpoint'` over all PLANs) against the SUMMARY records:
  - 03-04-PLAN:63 `checkpoint:decision gate="blocking"` (one-way seven-table shape). 03-04-SUMMARY:207-209: "Task 1: Confirm one-way table shape (checkpoint:decision, auto-resolved) … Auto-selected the recommended seven-table shape per auto-mode protocol". This is the origin of the DOMN-01 narrowing questioned in F-112.
  - 05-01-PLAN:123 `checkpoint:decision gate="blocking-human"` (D-02 one-way quantization semantics). 05-01-SUMMARY:81 shows commit "(orchestrator)". No user statement is recorded, unlike 01-04 and 02-01, which quote the user's reply.
  - 02-05-PLAN:90 `checkpoint:human-verify` (off-host backup target). 02-05-SUMMARY:286-292: "The orchestrator confirmed in the dispatch envelope … OneDrive-synced directory … No fresh human-verify gate was emitted".
  - 03-01-PLAN:85, 03-02-PLAN:68 and 07.1-01-PLAN:67 are `gate="blocking"`, but their SUMMARYs contain no checkpoint resolution at all. 03-02-SUMMARY:40 even says "planner assumption flagged for user confirmation".
  - 07.1-01's "decision" offers a single option (`guard-and-proceed`, cons "None").
  - 04-03 (gate=non-blocking, reversibility one-way) was auto-selected and later overridden (F-806).
- **Expected:** Checkpoints marked blocking or blocking-human, and every one-way decision, carry the user's verbatim answer, as 01-04 and 02-01 do.
- **Actual:** Seven checkpoints were resolved by the orchestrator or executor, or were not recorded.
- **Reproduction:** Read the cited lines.
- **Impact:**
  - The user, who per the charter delegated trading choices, never saw several irreversible choices: the DB schema, the quantization semantics and the backup target.
  - Together with F-124, most of the project's human gates were machine-cleared.
- **Why tests miss it:** Process artifact.
- **Remediation:**
  - Present the listed one-way decisions to the user for ratification (a DECISIONS row each).
  - Make the executor refuse `gate="blocking*"` in auto mode, and refuse single-option decision checkpoints at plan-check.

### F-810 — A Phase-4 review fix mutated already-referenced baseline-v1 parameter sets in place; the only immutability tripwire was satisfied by regenerating its expected hashes

- **ID:** F-810
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** DEFECT (contract)
- **Category:** registry immutability
- **Component:** params/breakout-retest/baseline-v1.toml, params/range-mr/baseline-v1.toml; src/domain/registry.py `verify_parameter_set`
- **File:** `params/range-mr/baseline-v1.toml`
- **Lines:** 44-49
- **Invariant:** Phase-3 D-04 ("immutable once used"); CONFIGURATION §5
- **Phase/commit:** 04 / `bd12652`, `1c3c187`
- **Known-prior:** NEW
- **Evidence:**
  - `bd12652` appends `atr_period = 14` (breakout-retest) and `atr_period = 14`, `touch_tolerance_atr = 0.3` (range-mr) to the existing `baseline-v1` files.
  - `1c3c187` updates `tests/fixtures/phase4/parameters.json`:
    - `dbcf730f… → 4a8ee77e…`
    - `2997f262… → 060fc447…`
  - 03-CONTEXT D-04: "versioned TOML files … immutable once used … raises (fail-closed) on any unregistered or mutated set".
  - `verify_parameter_set(path, expected_hash)` (`registry.py:412-444`) is the only mutation check. Its expected hashes live only in test fixtures, which the same wave regenerated.
  - No committed manifest of published set hashes exists. The paper freeze monitor keeps its pin in git-ignored `logs/paper/pinned_epoch.json`.
- **Expected:** A new set version (`baseline-v1.1`/`v2`) for semantic additions. A committed hash lock that CI checks, so in-place edits fail.
- **Actual:** An in-place edit with a same-wave oracle update. Nothing would stop the same edit to baseline-v3 (used by paper) or a future published set.
- **Reproduction:** `git show bd12652 -- params`; `git show 1c3c187 -- tests/fixtures/phase4/parameters.json`.
- **Impact:**
  - At that time only fixtures referenced v1, so there was no evidence loss.
  - The mechanism that should protect published experiment identity is not enforced against committed files.
- **Why tests miss it:** The tripwire's expected values are regenerable test data.
- **Remediation:** Add a committed `params/HASHES.lock` (set id → hash) checked in CI. Forbid edits to any locked set.

### F-811 — Phase-10 review fixes changed the CLI and metric contracts but did not update the UI-SPEC or record the metric narrowing as a decision

- **ID:** F-811
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** DRIFT
- **Category:** REVIEW-FIX contract propagation
- **Component:** src/analytics/cli.py; src/analytics/approval_delay.py; 10-UI-SPEC.md
- **File:** `.planning/phases/10-journal-depth-kill-gate-operations/10-UI-SPEC.md`
- **Lines:** 370-377
- **Invariant:** —
- **Phase/commit:** 10 / `ca139ba` (WR-05), `0b82c6e` (WR-09), `30c3992` (WR-08)
- **Known-prior:**
  - 10-REVIEW-FIX itself notes "The UI-SPEC in `.planning/` was not edited".
  - NEW: the WR-09 and WR-08 contract effects.
- **Evidence:**
  - The UI-SPEC Interaction Contract says "Exit codes | `0` … `1` … `2`" and the invocation `[-AsOf] [-OutDir] [-Record] [-Universe]`.
  - After the fixes:
    - Exit 3 exists (`src/analytics/cli.py:14,745`).
    - `--record` requires `--evidence` (exit 2).
    - The wrapper is updated (`scripts/dev/journal-report.ps1:14-25`).
  - WR-08 (`30c3992`) removed the OPPORTUNITY branch, so the LIVE delay buckets are approvals-only. 10-CONTEXT:9 names "approval-delay impact (system vs user-execution vs opportunity reports)".
  - The fixer marks the choice "requires human verification", and no decision record exists.
- **Expected:** A contract change in a REVIEW-FIX updates the governing spec, and a metric-definition change gets a D-xx decision.
- **Actual:** The spec and the code disagree. The delay buckets cannot show whether signals were missed because of delay (skips/expiries are excluded). Compare F-961.
- **Reproduction:** Read the cited lines.
- **Impact:** Operator confusion on exit 3 / `-Evidence`. The approval-delay impact report has a selection bias toward approved signals.
- **Why tests miss it:** Tests were updated to the new contract. The spec is not tested.
- **Remediation:**
  - Update the 10-UI-SPEC Interaction Contract.
  - Record WR-08 as a decision, or implement decision-time bucketing for skips/expiries.

### F-812 — The 07.1 test migration rewrites the "grandfathered" phase-6 fixture cost dicts in memory from full to half fill, and made the Phase-5/6 canonical baseline-v2 sets unassemblable

- **ID:** F-812
- **Severity:** LOW
- **Confidence:** CONFIRMED
- **Classification:** DRIFT (test semantics changed)
- **Category:** tests adapted to new behaviour
- **Component:** tests/test_backtest_experiment.py `_v3_case_input`
- **File:** `tests/test_backtest_experiment.py`
- **Lines:** 48-65
- **Invariant:** INV-104, AMB-036
- **Phase/commit:** 07.1 / `d6bdad4`
- **Known-prior:**
  - F-957 (the 0.5 value itself).
  - NEW: the test-side mechanism, and the claim of byte-identical grandfathered fixtures.
- **Evidence:**
  - The helper docstring says "phase6 fixtures stay byte-identical (NOT regenerated) … The cost_model dict is also rebinding partial_fill_fraction from "1.0" (phase6 spelling) to "0.5" (v3 TOML spelling) so the registry slice and the fixture dict hash identically."
  - Every `assemble()` test (7 call sites) switched from `_load_input` to `_v3_case_input`.
  - The commit message says "baseline-v2 only has 3 [cost keys] and now raises KeyError at the gate (correct behavior)". baseline-v2 is the set that the Phase-5 parity fixtures and `scripts/gen_phase6_fixtures.py:326` (`PARAMETER_SET_ID = "baseline-v2"`) use.
- **Expected:** A binding fix does not change the simulated economics of the existing experiment tests. A needed parameter change is a new, justified set version.
- **Actual:**
  - All experiment tests now assemble half-filled trades.
  - The fixture files stay unchanged, so a file diff shows nothing.
  - The generator script still targets a set that can no longer be assembled.
- **Reproduction:** `git show d6bdad4 -- tests/test_backtest_experiment.py`.
- **Impact:** This hides the F-957 behaviour change from any fixture review. Regenerating the phase-6 fixtures with the committed generator yields cases that `assemble()` refuses.
- **Why tests miss it:** The mutation happens inside the tests.
- **Remediation:**
  - Carry this out together with the F-957 fix (P11: a new set with `partial_fill_fraction = 1`).
  - Point the generator at the new set.
  - Remove the in-memory rebinding.

## Open Questions

1. **Cross-lane correction to stage B:** F-901 and F-120 "Why tests miss it" say that golden fixtures pin the simulator semantics byte for byte. This is inaccurate: the phase-6 simulator cases have no `expected.json` (F-805). The fix for F-901 needs new assertions, not fixture regeneration. Verifiers should adjust.
2. **Not bisected:** the 06 and 08 review-fix waves (F-803) were not re-run at each intermediate SHA. Only HEAD is known green (`tool-output/pytest.txt`: 1268 passed). Stage C verifiers may want a bisect run.
3. **10 WR-04:** `--record` still accepts a backdated `--as-of`, "so idempotent replays keep working". A backdated *new* KILL_GATE_EVALUATION can therefore be inserted into history. Whether a future `enable()` consumer (WR-10) reads "latest by occurred_at" or "latest recorded" decides whether that matters. For L3/L7.
4. **Unknown user involvement:** 01-04 and 02-01 quote user replies relayed by the orchestrator. For 05-01 "(orchestrator)" it is unknowable from the repo whether the user was asked. The chat transcripts are not in the snapshot.
5. **Different checkout:** the 08-REVIEW-FIX `review_path` points to `C:/Users/daotu/OneDrive/Documents/Trading-Alert`. Part of the work ran in another checkout inside OneDrive, which is the same sync folder later chosen as the "off-host" backup (F-910). This matters for L7 if secrets or `.env` ever lived there.
