# Lane 6: testing_verification

## Scope

- Pre-computed tool output (`tool-output/ruff-check.txt`, `ruff-format.txt`, `mypy-src.txt`, `pytest.txt`, `snapshot-status-after-tools.txt`).
- Test suite design: `tests/` (94 files, 1275 collected, 1268 pass / 7 skip), fixtures under `tests/fixtures/phase3..phase10`, fixture generators `scripts/gen_phase6_fixtures.py`, `scripts/_regen_phase4_expectations.py`, `scripts/_compute_phase4_fixtures.py`, `scripts/check_migration_parity.py`.
- CI: `.github/workflows/{registry-gate,research-gate,paper_freeze_check}.yml`, `pyproject.toml` tool config.
- VALIDATION/Nyquist claims: `.planning/phases/07*/07-VALIDATION.md`, `08*/08-VALIDATION.md`, `09*/09-VALIDATION.md`, `10*/10-VALIDATION.md`, plus the 07-0x/08-01 SUMMARY "mypy clean" lines.
- Stage A/B inputs: the findings lists of `docs_trading_soundness`, `docs_exchange_facts`, `planning_decisions_01_06`, `planning_decisions_07_17` and `requirements_docs_plan`.
- Core question: for each known defect (F-001, F-120/F-901, F-951/F-126, F-952, F-105/F-953, F-102), why did the green suite not catch it?

Probes (in `tmp/testing_verification/`, run with the repo venv, `PYTHONPATH=snapshot`, cwd = snapshot; the snapshot's `git status` stayed clean afterwards):
- `probe_fee.py`: runs `src.backtest.simulator.run` on the committed golden inputs `phase6/intrabar_both_touched{,_short}`.
- `probe_double_exec.py`: calls `execute_approved_plan` twice with the suite's own `FakeExecutionAdapter` and the `phase9` manager fixture.
- `collect_counts.txt`: per-file test counts from `pytest --collect-only`.

Coverage measurement: skipped, because `coverage`/`pytest-cov` are not installed in the venv. A static check instead: every `src/**/*.py` module is imported by at least one test or script, except `src/db/alembic/env.py` and `versions/0002_domain_registry.py`. So the gaps below are about **oracles**, not about unexecuted code.

## Coverage

| File | Level | Note |
|---|---|---|
| tool-output/*.txt | DEEP_READ | all four reports plus the snapshot status |
| tests/test_backtest_simulator.py | DEEP_READ | fixtures, assertions, the tautological cost-parity test, dead `_load_expected` |
| tests/test_backtest_experiment.py | NORMAL_READ | baseline tests; unused `expected.json` |
| tests/test_risk_sizing.py, test_risk_quantization.py, test_risk_parity.py | NORMAL_READ | cost inputs, 60% rule tests |
| tests/test_execution_manager.py | DEEP_READ | FakeExecutionAdapter, happy path, test list |
| tests/test_execution_attach.py | NORMAL_READ | zero-rescue test |
| tests/test_execution_emergency.py | NORMAL_READ | cancel-protectives tests |
| tests/test_execution_enablement.py | NORMAL_READ | WITHIN_BUDGET permit test |
| tests/test_reconcile.py, test_drills.py | NORMAL_READ | "must never place" fakes and static guard |
| tests/test_order_ids.py, test_approval_replay.py, test_phase8_audit_reviewfix.py | NORMAL_READ | replay/dedup coverage, source-text tests |
| tests/test_no_lookahead.py, test_prefix_invariance.py, test_paper_parity.py | NORMAL_READ | what the lookahead/parity suites actually exercise |
| tests/test_paper_ws_connect.py | NORMAL_READ | sync fake vs async SDK |
| tests/test_domain_mappers_pg.py, test_analytics_store.py | NORMAL_READ | PG-gated skips, create_all |
| tests/test_analytics_typing.py, test_quality_gates.py | NORMAL_READ | scoped mypy gate |
| tests/*.py (remaining) | METADATA_ONLY | test-name listing and heuristic scan for source-text assertions |
| tests/fixtures/phase5/*/input.json, happy_path_long/expected.json | NORMAL_READ | `modeled_costs_per_unit` values |
| tests/fixtures/phase6/** | NORMAL_READ | only 2 of 9 case dirs carry expected.json |
| scripts/gen_phase6_fixtures.py | DEEP_READ | 1m data is placed inside the signal bar |
| scripts/_regen_phase4_expectations.py | NORMAL_READ | expectations computed by src itself |
| scripts/check_migration_parity.py | NORMAL_READ + executed | offline SQL, column-name parity only |
| src/backtest/costs.py | DEEP_READ | `modeled_costs_per_unit` |
| src/risk/sizing.py | DEEP_READ | consumer contract |
| src/risk/portfolio.py | NORMAL_READ | ruff F841 lines 310-313 |
| src/adapters/telegram_notify.py, src/paper/supervisor.py, src/paper/resync.py, src/ops/drills.py, src/reconcile/compare.py | NORMAL_READ | each mypy error checked |
| src/approval/replay.py | METADATA_ONLY | ruff E402 |
| src/adapters/paper_ws.py | NORMAL_READ | missing await (F-125) |
| src/execution/enablement.py | NORMAL_READ | enable() |
| .github/workflows/*.yml | DEEP_READ | what CI runs |
| pyproject.toml | NORMAL_READ | pytest/ruff/mypy config |
| .planning/phases/07..10 VALIDATION.md | NORMAL_READ | Nyquist and status claims |
| .planning/v0.3-MILESTONE-AUDIT.md | METADATA_ONLY | M1-M4 composition gaps |
| lanes/*.md, *.findings.json (stage A/B) | NORMAL_READ | known-defect context |

## Tool output interpretation

**pytest** (`pytest.txt`): 1268 passed, 7 skipped, 180 s.
- 5 skips are `tests/test_domain_mappers_pg.py` (live PG).
- 1 skip is `test_analytics_store.py:561` (live PG).
- 1 skip is `test_analytics_files.py:701` (symlinks on Windows).
- The slowest tests are the mypy subprocess test (17 s) and the strategy-level prefix/no-lookahead suites (7-10 s each).
- No test talks to PostgreSQL, Binance, Telegram or a WebSocket. There is no integration or E2E test, and none could exist yet: the runtime composition is missing (M1-M4, KNOWN: v0.3-MILESTONE-AUDIT).

**mypy --strict src** (5 errors). Each was checked against the code; **all 5 are typing noise, with no runtime bug**:

| Site | What mypy sees | Runtime reality | Verdict |
|---|---|---|---|
| `src/adapters/telegram_notify.py:287` | the loop variable `value` was first bound to Decimal (loop at L266-272) and is re-bound to datetime (L286-290) | two independent validation loops. The datetime loop checks `isinstance(value, datetime)` and tz-awareness correctly | noise (variable reuse) |
| `src/paper/supervisor.py:298-299` | `gap` is inferred as `dict[str, object]` from the except-branch literal (L276-282, added by review-fix commit 2d731e5); the later `for gap in gaps` reuses the name | `gaps` comes from `resync.backfill_missed_closes`, which builds `expected_utc`/`observed_utc` as `datetime` (`src/paper/resync.py:249-265`). `.isoformat()` is valid | noise |
| `src/ops/drills.py:814` | `compare_fn: ... \| None` is not narrowed inside the nested closure | `if compare_fn is None: from ... import compare as compare_fn` (L804-805) runs before the closure is called | noise |
| `src/reconcile/compare.py:517` | `value == 0` on `Any` returns Any | Decimal/int `==` returns bool. The TypeError is caught | noise |

The errors come from review-fix commits (2d731e5, 9dbef80, d649dc1, 53f06cc) made after the phase SUMMARY files recorded "mypy clean". Nothing re-ran the repo-wide gate afterwards (see F-605).

**ruff check** (36 issues).
- 23 are auto-fixable style issues (UP017, I001, F401).
- `src/risk/portfolio.py:312-313` F841: `warning_threshold_quote` and `stop_threshold_quote` are dead assignments. The daily state comes from `_derive_daily_state(...)` at L253-255 with the same thresholds, so this is dead code, not a skipped gate.
- `tests/test_backtest_report.py:579` B017 (`pytest.raises(Exception)`) is a weak assertion.
- `src/approval/replay.py:54` E402 is cosmetic.

**ruff format**: 98 files would be reformatted. This is hygiene only.

## Critical-behavior test matrix (would a test FAIL if the behavior broke?)

| Behavior | Test exists that fails on breakage? | Notes |
|---|---|---|
| Quantization floor / minQty / minNotional / 60% rule | YES | `test_risk_quantization.py` (floor, 1-ulp, exact 0.6 boundary, rejects) |
| Sizing formula arithmetic | YES for arithmetic, NO for cost units | F-601 |
| Realized SL loss ≤ risk budget (incl. costs) | **NO** | F-601; the probe shows 2.07× the budget on a committed golden input |
| Approval expiry / stale / wrong chat / wrong token / 5× replay | YES (in-memory) | `test_approval_replay.py`, boundary at expiry ±1 s |
| Approval → at most one entry across replay/restart | **NO** | F-603; the probe shows 2 identical `place_entry` calls |
| Execution failure paths (ambiguous response, probe failure, SL reject) | YES (fakes) | `test_execution_manager.py`, `test_execution_attach.py` |
| Missing stop re-placed / reduce-only close | **Tests assert the opposite** | F-604 |
| SAFE_MODE blocks entries | YES in-process | restart/rehydration is NOT tested (F-606) |
| Reconcile mismatch → SAFE_MODE / orphan sweep | YES (fakes) | |
| Kill gate state machine | YES | `test_kill_gate_*.py` |
| Live enable requires a passing candidate | **Tests assert the opposite** | F-604 |
| Daily loss stop | PARTIAL | gate tested with an injected `daily_loss_quote` constant. No producer of that value exists anywhere in src (every caller supplies it), so there is nothing to test |
| Fee/cost units | **NO** (tautological) | F-601 |
| Backtest causality (fill after signal, exit after fill) | **NO** | F-602 |
| TP1/TP2 structure parity backtest↔live | **NO** | F-602 |
| WS reconnect / resync | YES against sync fakes only | the fake is not bound to the async SDK (F-607) |
| Restart / recovery | **NO** | F-606 |
| Migrations apply on PostgreSQL | **NO** | F-606 |

## Why the known defects were not caught (core analysis)

1. **F-001 fee-unit bug** (`modeled_costs_per_unit` returns a rate sum, sizing adds it to a price distance): see **F-601**.
   - The producer and the consumer are each tested in their own unit system.
   - The only test that joins them (`test_cost_parity_simulator_matches_costs_module`) recomputes the same buggy formula as its oracle.
   - Phase-5 fixtures feed `modeled_costs_per_unit` as quote/unit values (`"1.0"` at a BTC price of 50,000, which is about 0.002% round-trip; `"0.0"` in 5 of 11 cases; `"900.0"` in one edge case), so they never touch the producer.
   - No test compares the simulator's own fee arithmetic (which is correct: `price × qty × rate`, `simulator.py:650-652`) with the `realized_risk` that sizing reported.
   - The committed golden input `intrabar_both_touched` produces an SL trade with `realized_pnl = -103.59` against `realized_risk = 49.99` and an allowed risk of 50. The test run shows it, and no assertion looks.
2. **F-120/F-901 same-bar lookahead**: see **F-602**.
   - `scripts/gen_phase6_fixtures.py` designs every behavior fixture so that "the last 1H bar is the trigger bar … 1m intrabar data resolves the exit". The 1m candles are keyed to the trigger bar's close (`_trigger_bar_close_key`, L356-358) and lie inside hour 249, the signal bar itself.
   - The fixtures therefore encode the lookahead as the intended scenario.
   - 7 of 9 phase-6 case dirs have **no expected.json**. `_load_expected` in `test_backtest_simulator.py:35` is dead code, although the module docstring claims a golden-hash comparison.
   - The tests assert only coarse labels (`exit_kind == "SL"`, `entry_kind`, counts).
   - The "no-lookahead" test for the simulator (L366-402) appends a candle *after* the bar, while the defect uses candles *before* the decision.
   - `test_no_lookahead.py` and `test_prefix_invariance.py` exercise only `strategy.evaluate`. The paper-parity test projects to `(signal_id, reason_code)` ("the paper loop does not simulate fills yet").
   - No test checks `entry_time_utc > signal close` or `exit_time_utc >= entry_time_utc`. On the golden fixture the exit (09:00:59) precedes the entry (09:59:59) and every test passes.
   - Correction to F-901's "golden fixtures pin the current semantics byte for byte": they do not pin anything numeric. They pin only the labels, and the fixture design encodes the wrong timing.
3. **F-102 TP2 never simulated**: see **F-602**.
   - Single-exit scope is a documented simulator choice (`simulator.py:104,122,207`).
   - The live TP1/TP2 split is tested only on the live side (`test_execution_modes.py`, `test_execution_attach.py`).
   - No test compares exit structure across engines. The one backtest↔paper parity gate excludes fills and exits.
4. **F-951/F-126 clientOrderId reuse**: see **F-603**.
   - Validation row 8-0X-04 maps EXEC-03 "Retry/restart/replay" to `tests/test_order_ids.py`, which proves only that the ID derivation is deterministic. That determinism is exactly the premise that makes the bug possible.
   - `FakeExecutionAdapter.place_entry` (`test_execution_manager.py:131-136`) accepts any number of submissions of the same ID and models no exchange dedup at all.
   - No test calls `execute_approved_plan` twice.
   - The probe shows two `OK` outcomes and two `place_entry` calls with `x-3333…EN`.
5. **F-952 stop never re-placed** and **F-105/F-953 enable() accepts WITHIN_BUDGET**: see **F-604**. The suite does not merely miss these, it *asserts* the wrong rules:
   - reconciler and drill fakes raise `AssertionError` on any placement (`test_reconcile.py:275-287`, `test_drills.py:172-185`);
   - a static guard forbids placement code in `src/reconcile` (`test_no_place_order_path_in_src_reconcile`, L872);
   - `test_unconfirmed_sl_leg_yields_entry_without_protective_with_zero_rescue` asserts exactly one adapter call and a filled position left without protection;
   - `test_enable_permits_within_budget_and_passing_candidate` (`test_execution_enablement.py:352-364`) requires WITHIN_BUDGET to enable, and 5 other enablement tests use WITHIN_BUDGET as the happy path.

## Verified Safe Areas

- **Test-suite determinism and isolation:**
  - no test hits the network or a database without an explicit `TEST_DATABASE_URL` guard;
  - `test_analytics_store.py` refuses a non-`_test` database (WR-14 parametrized test);
  - the snapshot stayed clean after full test runs (`snapshot-status-after-tools.txt` and our own runs).
- **Quantization tests (INV quantization, 60% rule):** `test_risk_quantization.py` covers the exact-step floor, 1-ulp round-down, the min-qty and min-notional rejects, and acceptance at the 0.6 boundary. These are real oracles (hand-built step/notional numbers), not implementation-derived.
- **Approval expiry and replay state machine (in-process):**
  - `test_approval_replay.py` pins the boundaries at expiry and 1 s before it, the wrong chat and wrong token rejects, plan-hash and version staleness, and "notify failure stays PENDING";
  - `test_phase8_audit_reviewfix.py` pins SKIP/SIMULATE misuse.
  - The oracles are independent of the implementation.
- **Execution fakes are signature-bound:** `FakeExecutionAdapter._bind_real` binds every call's kwargs against the real `BinanceUsdmAdapter` signature (`test_execution_manager.py:121-129`). That prevents drift in call shape, though not in behavior.
- **Kill-gate clock and state:** `test_kill_gate_state.py` has explicit boundary tests (6 months ± 1 s, month clamping, independence, order invariance).
- **mypy findings:** all 5 were checked and are not runtime bugs (table above).
- **ruff F841 in portfolio.py:** dead code only. The daily state is still derived from the same thresholds.
- **Migration column parity:** `scripts/check_migration_parity.py` passes (offline SQL; 0001→0003 column sets equal the models). See F-606 for what it does not prove.

## Findings

### F-601 — The cost-unit seam between `modeled_costs_per_unit` (rate) and `size_position` (quote per unit) has no oracle; the only joining test is tautological, and the golden input shows an SL loss of 2.07× the risk budget unasserted

- **ID:** F-601 · **Severity:** HIGH · **Confidence:** CONFIRMED (probe) · **Classification:** GAP · **Category:** test oracle / sizing
- **Component:** tests for `src/backtest/costs.py` + `src/risk/sizing.py`
- **File:** `tests/test_backtest_simulator.py` · **Lines:** 326-358 (plus `tests/fixtures/phase5/*/input.json:41-44`)
- **Invariant:** INV sizing / realized-risk (Corrected Rule on cost units, A1 F-001)
- **Phase/commit:** 05 (74a04b8), 06 (77a0659)
- **Known-prior:** the defect is KNOWN (F-001; ROADMAP P11; F-109 says the verification used self-authored fixtures). The test-mechanism analysis is new.
- **Evidence:**
  - Test 11 computes its "expected" value with the implementation's own formula: `expected_costs = Decimal(cost_model.fee_rate_entry) + Decimal(cost_model.fee_rate_exit) + Decimal(cost_model.expected_slippage)`, then `assert sim_costs == expected_costs`. This can never fail for a unit error.
  - Test 4 (`test_costs_apply_from_run_1_realized_pnl_differs_from_gross`, L148-172) asserts only the identity `realized == gross - fees - slippage`.
  - Phase-5 fixtures feed `"modeled_costs_per_unit": "1.0"` at `entry 49900-50100` and `SL 49000` (happy_path_long). Expected `realized_risk 49.04900` = 0.049 × (1000 + 1). Five cases feed `"0.0"`. No fixture calls the producer.
  - Probe `tmp/testing_verification/probe_fee.py` on the committed `phase6/intrabar_both_touched`: `modeled_costs_per_unit 0.0008`, `quantity 635.67`, `realized_risk 49.99998`, `entry_fee 15.45`, `exit_fee 38.59`, `realized_pnl -103.594`. Allowed risk is 50. The SHORT twin gives `-106.76`.
- **Expected:** at least one property test: for a filled trade that exits at SL, `|realized_pnl| ≤ allowed_risk × (1 + tolerance)` (where the tolerance covers only gap/slippage beyond the model), and `realized_risk` (sizing) ≈ the simulated SL loss including fees. Also a unit test that the producer returns quote per unit (it should scale with price).
- **Actual:** no such assertion. The producer and consumer are each tested in their own units, and the only joining test mirrors the implementation.
- **Reproduction:** `cd snapshot; PYTHONPATH=. python -B ../tmp/testing_verification/probe_fee.py`
- **Impact:** the money-critical invariant "one SL = at most 1R" is unprotected. F-001 passed review, verification (05-VERIFICATION "VERIFIED including modeled costs") and 1268 tests. Any P11 fix could regress silently for the same reason.
- **Why tests miss it:** a tautological oracle, fixtures that bypass the producer, and no cross-module property.
- **Remediation:** add a property test over the phase-6 fixtures (SL-exit loss vs `realized_risk`/allowed risk). Make the producer's contract explicit (quote per unit = price × (fee_in + fee_out) + slippage in quote). Give phase-5 fixtures realistic per-unit costs (about $35/BTC at 50k and 7 bps). Replace Test 11's oracle with hand-computed numbers.

### F-602 — Backtest simulator tests have no causality or exit-structure oracle; the fixture generator deliberately places the fill and exit data inside the signal bar, and 7 of 9 "golden" cases have no expected output

- **ID:** F-602 · **Severity:** HIGH · **Confidence:** CONFIRMED · **Classification:** GAP · **Category:** test oracle / backtest methodology
- **Component:** `tests/test_backtest_simulator.py`, `scripts/gen_phase6_fixtures.py`, `tests/test_paper_parity.py`
- **File:** `scripts/gen_phase6_fixtures.py` · **Lines:** 1-12, 211-222, 356-358 (and `tests/test_backtest_simulator.py:1-36, 366-402`)
- **Invariant:** INV-003/INV-004/INV-103/INV-104 (closed-candle, no lookahead); AMB-035
- **Phase/commit:** 06 / 77a0659; 07-02 parity
- **Known-prior:** the defects are KNOWN (F-120, F-901, F-102, 06-REVIEW CR-04/WR-02). F-901's "golden fixtures pin the current semantics byte for byte" is corrected here: nothing numeric is pinned.
- **Evidence:**
  - Generator docstring: "The last 1H bar is the trigger bar (touches the zone) - 1m intrabar data resolves the exit". `_make_1m_intrabar_long_both_touched` starts at `trigger_open = BASE_OPEN + timedelta(hours=249)` (the signal bar) and is keyed by `_trigger_bar_close_key()`.
  - `ls tests/fixtures/phase6/*`: only `registry_identity` and `report_slices` have `expected.json`. `_load_expected` (test_backtest_simulator.py:35) is never called, yet the module docstring says "asserts the canonical-JSON hash of the trade list matches".
  - `baselines/simple_trend/expected.json` reads `"trades": [], "trade_count": 1` (self-contradictory) and is unused.
  - The simulator "no-lookahead" test appends a candle at 10:00 (after the bar) and asserts no change.
  - `test_no_lookahead.py` and `test_prefix_invariance.py` import only `src.core.strategy.evaluate`.
  - `test_paper_parity.py` docstring: "The projection reduces both outputs to a list of (signal_id, reason_code) tuples … (the paper loop does not simulate fills yet)".
  - Probe output on the golden input: `entry_time_utc 2026-09-11T09:59:59`, `exit_time_utc 2026-09-11T09:00:59`, `exit_kind SL`. Every test passes.
  - Exit kinds are only SL/TP1/EOD (single-exit, `simulator.py:104`). No test contrasts this with the live SL+TP1+TP2 legs asserted in `test_execution_modes.py:100-160`.
- **Expected:** golden expected outputs with independent (hand-derived) numbers; invariants asserted on every trade record (`signal_close < entry_time ≤ exit_time`, the fill bar is after the signal bar); a fixture where the signal bar touches the zone but later bars do not (expect no fill); a backtest↔live exit-structure parity check or an explicit test that pins the single-exit approximation as a known deviation.
- **Actual:** coarse label assertions, a fixture design that encodes the lookahead as the happy path, and parity limited to the verdict chain.
- **Reproduction:** `probe_fee.py` prints the entry/exit times. Alternatively run `tmp/planning_decisions_01_06/probe_samebar.py`.
- **Impact:** backtest results, which are the kill-gate and family-selection evidence, can be structurally invalid while the suite stays green. Any fix to F-901/F-102 has no failing test to drive it and no regression net afterwards.
- **Why tests miss it:** there is no temporal-ordering oracle, prefix-invariance cannot detect "using the past as the future", and the golden outputs are absent.
- **Remediation:** add per-record temporal invariants to a shared trade-record validator used by every simulator test. Commit hand-verified `expected.json` for each phase-6 case and actually compare them. Rebuild the generator so 1m data lives in bars N+1… Extend the paper parity projection to fills/exits once paper simulates them.

### F-603 — "No duplicate entry on retry/restart/replay" (EXEC-03, Phase 8 SC4) is validated only by ID-determinism tests and a fake that accepts unlimited identical submissions; running the pipeline twice places two entries

- **ID:** F-603 · **Severity:** HIGH · **Confidence:** CONFIRMED (probe with the suite's own fake) · **Classification:** GAP · **Category:** test oracle / idempotency
- **Component:** `tests/test_order_ids.py`, `tests/test_execution_manager.py::FakeExecutionAdapter`, 08-VALIDATION row 8-0X-04
- **File:** `tests/test_execution_manager.py` · **Lines:** 79-136
- **Invariant:** INV-087, INV-047 (idempotent approval, no duplicate entry); Rule 28
- **Phase/commit:** 08-03, 09-01
- **Known-prior:** the defect is KNOWN (F-951, F-126). New here: the validation-mapping and fake-model mechanism, plus the executable reproduction.
- **Evidence:**
  - 08-VALIDATION.md:49: `8-0X-04 | EXEC-03 | Retry/restart/replay → identical client/algo IDs … | unit (determinism) | pytest tests/test_order_ids.py | ✅ green (21)`.
  - The fake `place_entry` appends to `self.calls` and returns a canned response. No ID set, no dedup, no "order already exists/filled" modeling.
  - `grep execute_approved_plan( tests` → only 6 calls, all in `test_execution_manager.py`, each once per test.
  - Probe `probe_double_exec.py`: `outcomes [(False, 'OK'), (False, 'OK')]`, `place_entry calls: 2 ['x-3333…EN', 'x-3333…EN']`, with the first response `FILLED`.
- **Expected:** a test that runs `execute_approved_plan` (or the future APPROVE handler) twice for one approval, including after the first entry reached FILLED/CANCELED, and asserts exactly one `place_entry` over the process lifetime and across a simulated restart. The fake exchange should model Binance's real rule (a client ID is unique among open orders only).
- **Actual:** the requirement is marked green on the strength of pure-function determinism.
- **Reproduction:** `cd snapshot; PYTHONPATH=. python -B ../tmp/testing_verification/probe_double_exec.py`
- **Impact:** a duplicate live position (2× risk) on an at-least-once Telegram replay or a restart. The green validation row stops anyone from noticing.
- **Why tests miss it:** the fake bakes in "same ID ⇒ same order", and no double-invocation test exists.
- **Remediation:** a stateful fake exchange with Binance's open-order-only uniqueness; double-invoke and restart tests; a persisted execution-intent guard (per F-951).

### F-604 — The suite actively asserts the wrong safety rules (no stop re-placement, zero rescue after an SL reject, cancel protectives before flat, live enable at WITHIN_BUDGET), so the corrected-rule fixes will break "green" tests

- **ID:** F-604 · **Severity:** MEDIUM · **Confidence:** CONFIRMED · **Classification:** DEFECT (tests encode a wrong rule; root cause: plan F-952/F-953, doc F-009) · **Category:** test design / safety
- **Component:** `tests/test_reconcile.py`, `tests/test_drills.py`, `tests/test_execution_attach.py`, `tests/test_execution_emergency.py`, `tests/test_execution_enablement.py`
- **File:** `tests/test_execution_enablement.py` · **Lines:** 352-364 (also `test_reconcile.py:275-287, 872-889`; `test_drills.py:172-185`; `test_execution_attach.py:286-328`; `test_execution_emergency.py:125-142`)
- **Invariant:** INV-074, INV-084, INV-085, AMB-024; Rules 14 and 24; live-enable prerequisites
- **Phase/commit:** 08, 09, 10
- **Known-prior:** the defects are KNOWN (F-952, F-105, F-953, 09 WR-07). The test entrenchment is new.
- **Evidence:**
  - `test_reconcile.py` fake: `async def place_algo_order(...): raise AssertionError("reconciler must never place a new algo order — query/cancel only")`.
  - `test_no_place_order_path_in_src_reconcile` is a static source scan.
  - `test_unconfirmed_sl_leg_yields_entry_without_protective_with_zero_rescue`: `assert len(adapter.calls) == 1, "expected exactly 1 adapter call (no rescue)"`. That leaves a filled position without a stop as the asserted outcome.
  - `test_cancel_untriggered_protectives_isolates_each_leg` asserts SL/TP1/TP2 cancels with no position-flat precondition.
  - `test_enable_permits_within_budget_and_passing_candidate`: `for state in (KillGateState.WITHIN_BUDGET, KillGateState.PASSING_CANDIDATE): controller.enable(...); assert controller.is_disabled is False`.
- **Expected:** tests should encode the corrected rules: a reduce-only/closePosition protective is always allowed (even in SAFE_MODE); an SL reject after a fill triggers a reduce-only close; the emergency close keeps the SL until flat; enable requires PASSING_CANDIDATE (plus the paper exit gate).
- **Actual:** the tests pin the opposite, and the tests are what "verify" these requirements in 08/09/10-VALIDATION.
- **Reproduction:** read the cited lines. Any corrected implementation turns these tests red.
- **Impact:** fixing the money-safety gaps first requires rewriting tests that look like safety guarantees. Risk: a future agent "fixes" the code back to make the tests green.
- **Why tests miss it:** the tests were derived from the plan decisions (D-03 "reconciler never places orders", 10 D-03), not from the corrected rules.
- **Remediation:** when P13-P15 or the new F-952 phase is planned, list these tests explicitly as "to be inverted". Mark them with a comment/xfail reason now that references F-952/F-953, so their intent is not mistaken for a safety invariant.

### F-605 — No CI or test enforces ruff, mypy or the full pytest suite; the scoped in-suite mypy gate hides repo-wide regressions, and the "mypy clean" / "1 pre-existing error" claims are stale

- **ID:** F-605 · **Severity:** LOW · **Confidence:** CONFIRMED · **Classification:** GAP · **Category:** CI / quality gates
- **Component:** `.github/workflows/*`, `tests/test_analytics_typing.py`
- **File:** `.github/workflows/registry-gate.yml` · **Lines:** 1-100 (and `tests/test_analytics_typing.py:1-56`)
- **Invariant:** AGENTS "CI quality gates are the enforcement point"
- **Phase/commit:** 07-10 review-fix commits 2d731e5, 9dbef80, d649dc1, 53f06cc
- **Known-prior:** KNOWN in part (F-101: the workflows never run because origin is a local path). New: what the workflows would *not* run, and the drift.
- **Evidence:**
  - `registry-gate.yml` runs only `pytest tests/test_registry_gate.py tests/test_registry.py`.
  - `research-gate.yml` is grep-only.
  - `paper_freeze_check.yml` is a cron.
  - No workflow runs `ruff`, `mypy` or the full `pytest`.
  - `test_analytics_typing.py` "fails only on error lines that name the analytics paths".
  - 10-VALIDATION.md "Static gates": "one pre-existing mypy error exists in `src/adapters/telegram_notify.py` … repo-wide ruff has 24 pre-existing findings". The snapshot has 5 mypy errors and 36 ruff findings.
  - 07-02-SUMMARY: "`mypy` clean across `src/paper/`", but `supervisor.py:298-299` now fails after review-fix commit 2d731e5.
  - All 5 mypy errors are typing noise (see the tool-output table).
- **Expected:** one CI job (or a local `scripts/dev/test.ps1` gate that is actually required) running `ruff check`, `mypy src` and full `pytest`, with the zero baseline restored.
- **Actual:** gates are per-phase and scoped, and the baseline erodes after every review-fix wave.
- **Reproduction:** `mypy src` / `ruff check` (see tool-output).
- **Impact:** today, hygiene only. Strict typing is the stated protection for Decimal-vs-float and None-safety on order paths, and it is not enforced repo-wide.
- **Why tests miss it:** by design, the in-suite gate filters to the analytics paths.
- **Remediation:** fix the 5 noise errors (rename loop vars, annotate `gap: dict[str, Any]`, bind a non-optional local in drills, `bool(...)`). Run ruff/mypy/pytest in one required gate.

### F-606 — Persistence, migrations and restart/recovery are never exercised: PG tests are skipped and use `create_all`, migrations are checked only as column-name parity, and no test restarts a controller

- **ID:** F-606 · **Severity:** MEDIUM · **Confidence:** CONFIRMED · **Classification:** GAP · **Category:** integration testing / recovery
- **Component:** `tests/test_domain_mappers_pg.py`, `tests/test_analytics_store.py`, `scripts/check_migration_parity.py`, SAFE_MODE/enablement tests
- **File:** `tests/test_domain_mappers_pg.py` · **Lines:** 26-44
- **Invariant:** DATA_MODEL migrations; SAFE_MODE survives restart (F-127); approval conditional UPDATE (replay.py:48-53)
- **Phase/commit:** 03, 08, 10
- **Known-prior:** partly KNOWN (F-127 in-memory SAFE_MODE; milestone M1-M4). The test-side gap is new.
- **Evidence:**
  - `pytestmark = skipif(not os.environ.get("TEST_DATABASE_URL"))` together with `Base.metadata.create_all(engine)` in the fixture, so the Alembic migrations 0001-0003 are never applied to a real DB in any test.
  - `check_migration_parity.py` runs Alembic in offline mode ("Generating static SQL") and compares column-name sets only. Types, constraints and indexes (for example `uq_short_id_mapping_signal_trade_plan`) are verified by substring grep (`test_wr30_migration_documents_retention_and_unique_guard`).
  - `grep -i "restart|rehydrat"` over the reconcile, drills, phase8 and execution tests returns nothing.
  - The approval replay "cross-process race needs a conditional write … at the store layer" (replay.py:48-53) has no store and no test.
  - 7 tests skipped in `pytest.txt`, 6 of them PG.
- **Expected:** a CI/throwaway-PG job running `alembic upgrade head` and the PG tests; restart tests (construct controller → enter SAFE_MODE/enable → reconstruct from the journal → assert state); a conditional-update approval-store test.
- **Actual:** no test has ever run against PostgreSQL in the recorded runs. Restart semantics are untested.
- **Reproduction:** `pytest tests/test_domain_mappers_pg.py -rs` without `TEST_DATABASE_URL` shows 5 skipped.
- **Impact:** migration or constraint drift, and loss of SAFE_MODE or disabled state across a restart, would reach the first live run undetected.
- **Why tests miss it:** PG is optional, `create_all` bypasses the migrations, and restart/recovery tests do not exist.
- **Remediation:** a compose-based PG test target; `alembic upgrade head` + downgrade smoke; journal-rehydration tests for SAFE_MODE, enablement and the kill gate.

### F-607 — WebSocket fakes are not bound to the SDK's async contract (unlike the execution fakes), which let the missing `await` in `paper_ws.subscribe` (F-125) pass

- **ID:** F-607 · **Severity:** MEDIUM · **Confidence:** CONFIRMED · **Classification:** GAP · **Category:** fake fidelity
- **Component:** `tests/test_paper_ws_connect.py`
- **File:** `tests/test_paper_ws_connect.py` · **Lines:** 43-69
- **Invariant:** PAPER-01 feed liveness
- **Phase/commit:** 07-01 / 07 review-fix CR-04
- **Known-prior:** the defect is KNOWN (F-125). The test mechanism is new.
- **Evidence:**
  - Fake: `def kline_candlestick_streams(self, *, symbol, interval, id=None) -> Any: … return self._handle` (sync).
  - Installed SDK: `websocket_streams.py:430: async def kline_candlestick_streams(`.
  - `src/adapters/paper_ws.py:160` calls it without `await`.
  - Execution fakes use `_bind_real` against the real adapter signature. Paper WS fakes have no equivalent check against the SDK (sync vs async, parameter names).
- **Expected:** a contract test that asserts `inspect.iscoroutinefunction` parity between each fake method and the SDK method, or fakes generated from the SDK signatures.
- **Actual:** the sync fake makes the broken call path look green.
- **Reproduction:** `python -c "import inspect,binance_sdk_derivatives_trading_usds_futures.websocket_streams.websocket_streams as w; print(inspect.iscoroutinefunction(w.DerivativesTradingUsdsFuturesWebSocketStreams.kline_candlestick_streams))"` → True, whereas the fake is sync.
- **Impact:** the paper feed never delivers klines. Paper forward-observation evidence (a kill-gate input) would silently be empty once composed.
- **Why tests miss it:** the fake was not bound to the SDK contract.
- **Remediation:** SDK-bound fake contract tests for every WS/REST SDK method the adapters call.

### F-608 — Golden expectations are computed by the implementation itself (phase 4 regen, phase 6 generator), so they act as change detectors, not correctness oracles; stale unused expected files remain

- **ID:** F-608 · **Severity:** LOW · **Confidence:** CONFIRMED · **Classification:** GAP · **Category:** fixture provenance
- **Component:** `scripts/_regen_phase4_expectations.py`, `scripts/_compute_phase4_fixtures.py`, `tests/fixtures/phase4/expected_*.json`, `tests/fixtures/phase6/baselines/*/expected.json`
- **File:** `scripts/_regen_phase4_expectations.py` · **Lines:** 1-45
- **Invariant:** planner geometry vs family sheets (F-113)
- **Phase/commit:** 04 / 1c3c187
- **Known-prior:** F-109 (verification by self-authored fixtures) is related. New: the regeneration mechanism.
- **Evidence:**
  - "The expectation fixtures must be recomputed from the corrected code — never hand-edited to match". The script imports `src.core.features.compute_features`, `src.core.planner.plan` and `src.core.strategy.evaluate` and writes their output as the expectation.
  - "Outputs are printed for hand-verification before committing". No record of that hand verification exists.
  - `baselines/simple_trend/expected.json` = `{"trades": [], "trade_count": 1, …}` and is never loaded.
- **Expected:** at least one independently derived (hand-computed or spec-derived) expectation per family geometry (entry zone, SL, TP1/TP2 per the family sheet), kept separate from regression snapshots.
- **Actual:** regenerating the expectations re-blesses whatever the code does, and the planner-vs-family-sheet mismatch (F-113) cannot fail a test.
- **Reproduction:** read the script header. Run it and compare `git diff`: it reproduces the committed files.
- **Impact:** geometry and planner errors are frozen into the fixtures, and the "byte-exact" wording in VALIDATION overstates correctness.
- **Why tests miss it:** the oracle comes from the implementation.
- **Remediation:** label these files as regression snapshots. Add spec-derived geometry tests per family. Delete or fix the unused `expected.json` files.

### F-609 — Several review-fix "coverage" tests are source-text greps, and the Nyquist/validation claims overstate behavioral coverage (10-VALIDATION `nyquist_compliant: true` rests partly on skipped or grep tests)

- **ID:** F-609 · **Severity:** LOW · **Confidence:** CONFIRMED · **Classification:** DRIFT · **Category:** validation claims
- **Component:** `tests/test_phase8_audit_reviewfix.py`, `.planning/phases/08*/08-VALIDATION.md`, `.planning/phases/10*/10-VALIDATION.md`
- **File:** `tests/test_phase8_audit_reviewfix.py` · **Lines:** 1243-1255, 1416-1425
- **Invariant:** none (process)
- **Phase/commit:** 08, 10
- **Known-prior:** v0.3-MILESTONE-AUDIT notes that phases 07-10 are unverified. New: the specific overstated rows.
- **Evidence:**
  - `test_wr24_synonym_guard_test_is_armed`: `assert "suspicious.append" in path` (it greps another test file).
  - `test_wr25_drill_invariant_test_asserts`: `assert "place_order_calls == 0" in text`.
  - `test_wr30_…`: `assert "purge" in text.lower()`.
  - A heuristic scan finds about 33 tests that assert on source text. Some of them are legitimate architecture guards.
  - 08-VALIDATION: "8-audit | … Each fixed behavior covered by at least one test (auditor-verified)".
  - 10-VALIDATION row 10-09-03 marks `tests/test_analytics_store.py` "SELECT-only reader; guarded idempotent append … ✅ green", but its live-PG append test is skipped in every recorded run. The frontmatter still says `nyquist_compliant: true`.
  - 07/08/09 correctly state `nyquist_compliant: false` with manual-only rows.
- **Expected:** validation rows should distinguish behavioral, static-guard and skipped coverage.
- **Actual:** grep and skipped tests are counted as behavior coverage.
- **Reproduction:** read the cited tests. `pytest tests/test_analytics_store.py -rs` shows the skip.
- **Impact:** overstated confidence in review-fix closure and in the phase-10 journal append path.
- **Why tests miss it:** by construction.
- **Remediation:** re-label the rows. Replace text-grep tests with behavioral tests where a behavior exists (e.g., the unique constraint on a real DB).

## Open Questions

- Daily loss stop: `daily_loss_quote` has no producer in src (the backtest reads a constant from the case input; live/paper callers must supply it). The gate tests are fine, but the value's derivation (UTC day, realized + fees + funding) is untestable until P12. Cross-lane: L3 business_invariants.
- `binance_usdm.py` float serialization of SDK params (A2 F-058): `test_execution_adapter_contract.py` checks signatures only. Whether any test asserts the wire string for small quantities was not checked (L5 lane).
- Coverage %: not measured (`coverage` not installed). The static import check shows every src module is imported by tests, so line coverage is probably high. That is why this lane focused on oracle quality instead.
- 06-REVIEW CR-04 skip plus the missing expected.json: were the expected.json files ever generated for the 7 behavior cases (e.g., deleted in a review fix)? `git log -- tests/fixtures/phase6/intrabar_both_touched` could answer this. L8 historical lane.
