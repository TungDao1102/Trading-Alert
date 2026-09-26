---
phase: 06-backtest-simulator-experiment-registry
verified: 2026-09-26T00:00:00Z
status: gaps_found
score: 19/22 must-haves verified
covered_files: [".planning/REQUIREMENTS.md", ".planning/phases/06-backtest-simulator-experiment-registry/06-01-PLAN.md", ".planning/phases/06-backtest-simulator-experiment-registry/06-01-SUMMARY.md", ".planning/phases/06-backtest-simulator-experiment-registry/06-02-PLAN.md", ".planning/phases/06-backtest-simulator-experiment-registry/06-02-SUMMARY.md", ".planning/phases/06-backtest-simulator-experiment-registry/06-03-PLAN.md", ".planning/phases/06-backtest-simulator-experiment-registry/06-03-SUMMARY.md", ".planning/phases/06-backtest-simulator-experiment-registry/06-REVIEW.md", "src/backtest/__init__.py", "src/backtest/costs.py", "src/backtest/experiment.py", "src/backtest/report.py", "src/backtest/simulator.py", "src/domain/registry.py", "tests/test_backtest_experiment.py", "tests/test_backtest_report.py", "tests/test_backtest_simulator.py", "tests/test_domain_no_float.py"]
covered_digest: "v1:sha256:bd7ffbeef9e5e93fc52af77e1bc9ffd2e7b9e5a5dc873a8d3c18344d5b57397e"
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "Re-running the recorded six-field tuple yields byte-identical trade lists via canonical sha256 comparison (per D-03)"
    status: failed
    reason: "CR-03 CONFIRMED in code: reproduce() never reads record (experiment.py:236-250), verify_experiment() compares two identical in-process runs of the same dict (lines 269-270) so drift is undetectable, and TradeRecord(**t) rebuilds from stringified dicts leaving str where Decimal/datetime are typed (type corruption breaks downstream arithmetic)"
    artifacts:
      - path: "src/backtest/experiment.py"
        issue: "reproduce ignores record; verify is tautological; TradeRecord reconstruction mistypes Decimal/datetime fields as str"
    missing:
      - "reproduce() must bind inputs to record fields (parameter_set_id/hash, strategy_version, cost_model_hash) and raise ExperimentReproducibilityBroken on mismatch"
      - "verify_experiment() must compare reproduce digest against a stored result digest from assemble time, not a second identical run"
      - "Parse trade dicts back to typed fields (Decimal(...), datetime.fromisoformat(...)) before constructing TradeRecord"
  - truth: "Both-touched bar with missing 1m coverage resolves SL-first with fallback_applied=true and coverage_note=1m_intrabar_missing (per D-01)"
    status: partial
    reason: "CR-01 CONFIRMED behaviorally: resolve_intrabar(intrabar=[]) raises IndexError at simulator.py:219 (only None takes the fallback path, line 176). None path is fixture-pinned and green; empty-list encoding of missing coverage crashes the whole run instead of failing closed"
    artifacts:
      - path: "src/backtest/simulator.py"
        issue: "resolve_intrabar treats None as missing but empty list [] falls through to intrabar[-1].close -> IndexError"
    missing:
      - "Guard `if intrabar is None or len(intrabar) == 0` returning the SL-first fallback outcome"
      - "Empty-list fallback test in tests/test_backtest_simulator.py"
  - truth: "Limit fills/partials/expiry/invalidation are modeled (roadmap SC1) — expiry resolves against the bar being replayed"
    status: partial
    reason: "CR-04 CONFIRMED in code: _entry_now_utc is captured once from the fixture now_utc (simulator.py:647) and reused for every bar's _resolve_entry expiry check (line 752), while evaluate_risk correctly receives now_utc=bar.close_time_utc (line 722). In any multi-bar backtest the fixture now_utc is the dataset end, so every early-bar signal whose expiry_utc predates it resolves EXPIRED. Single-trigger fixtures pass (trigger close + 4h > fixture now), masking the bug. Clock inconsistency between risk gate and entry gate on the same bar"
    artifacts:
      - path: "src/backtest/simulator.py"
        issue: "Expiry gate uses one global fixture clock for every bar instead of bar.close_time_utc"
    missing:
      - "Pass now_utc=bar.close_time_utc to _resolve_entry (same clock as evaluate_risk)"
      - "Multi-bar expiry test: early-bar signal with expired window at dataset end must NOT resolve EXPIRED when its window was open at its own bar time"
  - truth: "Expectancy interval uses the stationary block bootstrap with a recorded seed via random.Random(experiment_seed); reruns are bit-stable and the SE approx sigma-over-sqrt-n diagnostic is printed alongside"
    status: partial
    reason: "CR-08 CONFIRMED in code: build() defaults built_at_utc=None to datetime.now(UTC) (report.py:550-553) and UncertaintyReport.digest() includes built_at_utc (line 362). Any two builds of identical trades/seeds at different wall-clock times hash differently. Seeded bootstrap itself is stable (tests pin with _FIXED_BUILT_AT_UTC); the default API path is non-reproducible"
    artifacts:
      - path: "src/backtest/report.py"
        issue: "Report digest defaults to wall-clock time — default-path rebuilds are non-reproducible"
    missing:
      - "Make built_at_utc a required input (fail closed when absent) or exclude it from the digest path"
behavior_unverified_items: []
---

# Phase 06: Backtest Simulator + Experiment Registry Verification Report

**Phase Goal:** Backtest is the canonical validation authority — selection decisions rest on costs-included, uncertainty-first evidence (ROADMAP SCs: intrabar+costs from run #1; six-field reproducibility + baselines; uncertainty-first reports, no winner without OOS).
**Verified:** 2026-09-26T00:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

> **MVP-mode note:** ROADMAP marks Phase 6 `mode: mvp`, but the phase goal is
> not a User Story (`As a …, I want to …, so that …`), so the MVP User-Flow
> Coverage section cannot be produced to quality. Proceeded with standard
> goal-backward verification against roadmap Success Criteria + PLAN
> must_haves per explicit tasking. Recommend `/gsd mvp-phase 06` goal
> repair or a mode correction, tracked outside this report.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 01-1 | Both-touched SL/TP bar resolves via 1m path, SL-before-TP per candle, LONG + SHORT | ✓ VERIFIED | `resolve_intrabar` checks SL before TP1 inside each 1m candle per direction (simulator.py:185-215); Beh 1-3 green incl. mirrored SHORT fixture |
| 01-2 | Missing 1m coverage → SL-first + fallback_applied=true + coverage_note | ✗ FAILED (partial) | None path pinned green; **`[]` crashes IndexError** (proven: `resolve_intrabar(...,intrabar=[])` → INDEXERROR-CRASH at line 219). Gap G2 |
| 01-3 | Costs (entry/exit fee, funding treatment, slippage) from run #1 via modeled_costs_per_unit + realized PnL; no cost-free path | ✓ VERIFIED | `modeled_costs_per_unit` passed to `evaluate_risk` (simulator.py:711-714); `_apply_costs` computes price×qty×rate fees + slippage into realized_pnl (545-612); Beh 4 green. WR-03 (funding hardcoded 0, slippage_model/spread strings unread) attached as warning — hashed assumptions exceed simulated math |
| 01-4 | Quantization/realized-risk rejects are first-class trade-record outcomes | ✓ VERIFIED | `_make_reject_record` with canonical reason codes; Beh 5 asserts QUANTIZATION_REJECT-class record |
| 01-5 | Exact-threshold inputs PASS (0.6 utilization, caps at equality) | ✓ VERIFIED | Simulator delegates to `evaluate_risk` identically (715-729, no re-implementation); boundary pinned by Phase-5 `test_risk_quantization.py` Beh 1f (exact 0.6 → ACCEPTED); full suite green |
| 01-6 | All exchange-sensitive arithmetic Decimal tick/qty-step aware; no float in src/backtest/ | ✓ VERIFIED | `test_domain_no_float` passes with all 5 src/backtest paths in SCANNED_FILES (ran 2026-09-26) |
| 01-7 | Bars iterate sorted by (close_time_utc, symbol); run-twice byte-identical | ✓ VERIFIED | `sorted(...)` at simulator.py:659; Beh 10 run-twice digest equality green |
| 01-8 | No 1m leakage across the decision boundary (close_time_utc <= bar close only) | ✓ VERIFIED | Closed slices use `<= bar.close_time_utc` (665-666); intrabar keyed per-bar (`SYMBOL\|ISO`, line 766); Beh 12 green |
| 02-1 | Six identity fields carried + parameterSetId alongside; missing field raises | ✓ VERIFIED | `ExperimentRecord.__post_init__` 64-hex + presence gates → IncompleteExperimentRecord (experiment.py:121-146); identity/missing-field tests green |
| 02-2 | Re-running recorded six-field tuple → byte-identical trade lists | ✗ FAILED | **CR-03 confirmed**: `reproduce()` never reads `record` (236-250); `verify_experiment()` compares same-dict-twice (269-272); `TradeRecord(**t)` mistypes Decimal/datetime as str. Reproduce/verify tests exercise only the `{}` stub path. Gap G1 |
| 02-3 | Unregistered/mutated sets fail closed (UnregisteredParameterSet/ParameterSetMutated) | ✓ VERIFIED | `assemble` loads via `load_parameter_set` (196); registry raises `ParameterSetMutated` on re-hash mismatch (registry.py:413-442); unregistered test green |
| 02-4 | Empty input → valid zero-trade record | ✓ VERIFIED | Test green; `reproduce({})` → `[]` deterministic |
| 02-5 | No-trade + simple-trend baselines via identical simulator + costs | ✓ VERIFIED | Both baselines delegate to `simulator_run` (303, 318) and filter to filled trades; baseline tests green. CR-07 (no enforcement that caller passes baseline params) attached as warning |
| 02-6 | Trailing precision discipline (0.00020 vs 0.0002 → different costModelHash) | ✓ VERIFIED | **Review CR-05 REFUTED by behavioral evidence**: `str(Decimal('0.00020'))` preserves exponent (`'0.00020'`); `build_cost_model` over Decimal inputs differing only in trailing zero yields **different** hashes (proven via `uv run python` snippet). String-path test + Decimal-path proof agree |
| 03-1 | Nine uncertainty sections present (counts/slices, R dist, bootstrap, drawdown, stability, plateau, baselines, dual-universe, coverage) | ✓ VERIFIED | Pinned EXPECTED_REPORT_DIGEST test + section-presence test green; report.py builds all nine |
| 03-2 | Seeded stationary bootstrap, bit-stable reruns, SE diagnostic | ✗ FAILED (partial) | Bootstrap math is seeded/stable (getrandbits + Decimal, envelope carries seed); but **default-path rebuilds differ by wall-clock** (CR-08: report.py:550-553 + digest line 362). Stable only when caller pins built_at_utc. Gap G4 |
| 03-3 | Plateau groups by region; isolated optimum = warning, never conclusion | ✓ VERIFIED | Region grouping + isolated-optimum logic (report.py:685-689); plateau test green |
| 03-4 | Dual-universe slices side by side; weak-live rescue marked rejection | ✓ VERIFIED | research/live5 slices (724-727); rejection rule; dual-universe test green |
| 03-5 | <2 trades → valid report, interval absent + insufficient-data note | ✓ VERIFIED | Empty + single-trade tests green |
| 03-6 | Zero-R counted as neither wins nor losses | ✓ VERIFIED | Zero-R test green |
| 03-7 | Stable sorted iteration; rerun digests match | ✓ VERIFIED | 12 `sorted(...)` sites in report.py (389-772); seed-stable rebuild test green with identical inputs. Default-clock caveat tracked under G4, not re-penalized here |
| 03-8 | Report-edge floats never upstream; no-float guard covers src/backtest/ | ✓ VERIFIED | Guard passes on all 5 paths (ran); Decimal-only stats (`_decimal_mean/median/pstdev`, `Decimal.sqrt`) |

**Score:** 19/22 truths verified

### Roadmap Success-Criteria Rollup

| SC | Criterion | Status | Basis |
|----|-----------|--------|-------|
| SC1 | Intrabar SL-first + limit fills/partials/expiry/invalidation modeled, fees/funding/slippage from run #1 | ✗ FAILED (partial) | Mechanism exists and is fixture-green, but G2 (empty-intrabar crash) and G3 (global expiry clock breaks multi-bar correctness) violate canonical-engine correctness |
| SC2 | Six-field reproducibility + no-trade/simple-trend baselines | ✗ FAILED | G1: reproduce/verify tripwire is tautological — the reproducibility claim is unimplemented beyond the empty-input stub path |
| SC3 | Uncertainty-first reports, never headline-only; no winner without OOS | ✓ VERIFIED | Nine sections pinned; plateau/dual-universe anti-headline rules hold; **no rank/select/winner code exists** in src/backtest (grep empty), so the no-winner clause holds vacuously. OOS confirmation itself is Phase 7's forward-observation mandate, not a Phase-6 artifact |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/backtest/__init__.py` | Package marker, D-05 purity, __all__ | ✓ VERIFIED | Exists, substantive, wired (re-exports run/costs/experiment/report) |
| `src/backtest/costs.py` | CostModel + build + per-unit formula | ✓ VERIFIED | 170 lines, Decimal-only, wired into simulator.run + experiment path |
| `src/backtest/simulator.py` | Event loop + intrabar + limit machine + costs | ✓ VERIFIED | 934 lines, substantive; defects are behavioral (G2/G3), not stubs |
| `src/backtest/experiment.py` | Record + assemble/reproduce/verify + baselines | ⚠️ HOLLOW-adjacent | Exists + substantive + imported, but reproduce/verify semantics broken (G1) — present, wired, behaviorally false |
| `src/backtest/report.py` | UncertaintyReport + build + bootstrap | ✓ VERIFIED | ~840 lines, substantive, wired; digest default defect (G4) is a parameter-default issue |
| `src/domain/registry.py` (extended) | 4 cost keys + STRING_KEYS | ✓ VERIFIED | Cost keys present; no existing key modified; registry suites green |
| `tests/test_backtest_{simulator,experiment,report}.py` | Pinned behavioral suites | ✓ VERIFIED | 13 + 11 + 10 tests, all green 2026-09-26 |
| `tests/fixtures/phase6/*` (12 case dirs) | Golden fixtures | ✓ VERIFIED | All 12 dirs present; missing-fallback encodes None (hence G2 untested) |
| `params/trend-pullback/baseline-*.toml` | Degenerated baseline sets | ⚠️ WARNING | Exist and load, but omit 4 of 7 cost keys (WR-04) — cost truth split across fixture dict + TOML |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| simulator.run | risk.gating.evaluate_risk | direct call, identical args + modeled costs | ✓ WIRED | simulator.py:711-729; parity test green |
| simulator.resolve_intrabar | 1m path / SL-first fallback | per-candle SL-before-TP walk | ✓ WIRED | Lines 185-222; LONG+SHORT fixture-pinned |
| costs.build_cost_model | sha256 cost snapshot → costModelHash | __post_init__ sha256 over 7-key snapshot | ✓ WIRED | costs.py:104-110; precision proof green |
| experiment.assemble | sha256 six-field identity | identity payload → experiment_id | ✓ WIRED | Lines 202-212; stability test green (run_type/strategy_id omission → warning CR-06) |
| experiment.reproduce | simulator.run rerun + byte-identical assertion | record-bound rerun + stored-digest compare | ✗ NOT_WIRED | Record never read; no stored-digest comparison (G1) |
| experiment baselines | simulator.run | degenerated TOML sets | ✓ WIRED | Lines 303/318; same-engine tests green |
| report.build | experiment record + trades → UncertaintyReport | typed build() | ✓ WIRED | report.py:541+; digest-pinned test green |
| report bootstrap | seeded random.Random + Decimal stats | getrandbits geometric blocks, seed on envelope | ✓ WIRED | Seed-reproducibility tripwire test green |
| no-float guard | SCANNED_FILES → all src/backtest/ | AST walker | ✓ WIRED | 5 paths listed, suite green |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| simulator._apply_costs | entry_fee/exit_fee/slippage/realized_pnl | price×qty×rate Decimal math (571-582) | ✓ Yes | ✓ FLOWING |
| simulator._apply_costs | funding_amount | hardcoded `Decimal("0")` (577) while funding_treatment hashed | Static | ⚠️ STATIC (WR-03) |
| report.build | R multiples, intervals, slices | trade-list Decimals → Decimal stats | ✓ Yes | ✓ FLOWING |
| report intrabar coverage | coverage_pct | integer `//` truncation (report.py:783, WR-05) | Lossy at non-extreme ratios | ⚠️ WARNING |
| experiment.assemble | parameter_set_hash | registry canonical hash (not re-hash) | ✓ Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite green | `uv run pytest tests/ -q` | 375 passed, 5 skipped | ✓ PASS |
| Simulator suite | `uv run pytest tests/test_backtest_simulator.py -q` | 13 passed | ✓ PASS |
| Experiment + report + no-float | `uv run pytest tests/test_backtest_{experiment,report}.py tests/test_domain_no_float.py -q` | 23 passed | ✓ PASS |
| Empty intrabar fail-closed | `resolve_intrabar(..., intrabar=[])` | **IndexError** (simulator.py:219) | ✗ FAIL → G2 |
| Trailing-precision hash discipline (Decimal path) | `build_cost_model` with `Decimal('0.00020')` vs `Decimal('0.0002')` | Hashes **differ**; `str()` preserves exponent | ✓ PASS (CR-05 refuted) |
| No winner-selection path | grep `rank\|select_best\|declare_winner\|winner\|argmax` src/backtest/ | No matches | ✓ PASS (SC3 vacuous hold) |

### Probe Execution

No probes declared by PLANs/SUMMARYs; no `scripts/*/tests/probe-*.sh` in scope. Step 7c: NOT APPLICABLE.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| BKTS-01 | 06-01 | Intrabar SL/TP ordering, limit fills/partials/expiry/invalidation, fees/funding/slippage before selection | ⚠️ PARTIAL | Simulator + 13 green tests; blocked on G2 (crash edge) + G3 (expiry clock) for canonical multi-bar use |
| BKTS-02 | 06-02 | Reproducible experiments + no-trade/simple-trend baselines | ⚠️ PARTIAL | Identity, gates, baselines green; blocked on G1 (reproduce/verify unimplemented) |
| BKTS-03 | 06-03 | Counts/slices, R distribution, bootstrap intervals, plateau — never headline-only | ⚠️ PARTIAL | Nine sections pinned + 10 green tests; blocked on G4 (default-path digest non-reproducibility) |

No orphaned requirements: REQUIREMENTS.md maps exactly BKTS-01..03 to Phase 6, all claimed across the three PLAN frontmatters. No requirement ID is unaccounted for.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| src/backtest/simulator.py | 219 | `intrabar[-1]` reachable on `[]` — IndexError, fail-open crash | 🛑 Blocker (G2) | Whole run crashes on empty-1m payload |
| src/backtest/experiment.py | 236-275 | Tautological reproduce/verify + str-typed TradeRecord rebuild | 🛑 Blocker (G1) | Reproducibility claim unimplemented; reproduced records unusable downstream |
| src/backtest/simulator.py | 647, 752 | Global fixture clock for per-bar expiry gate | 🛑 Blocker (G3) | Systematic over-expiry of early signals in multi-bar backtests |
| src/backtest/report.py | 550-553, 362 | Wall-clock default inside digest path | 🛑 Blocker (G4) | Default-path report digests non-reproducible |
| src/backtest/simulator.py | 500-516 | trade_id omits symbol/bar-time/quantity; symbol placeholder `"Decimal"` pre-patch | ⚠️ Warning (CR-02) | Latent ID collisions (partial-fill fractions; reused plan IDs); output content correct post-patch |
| src/backtest/experiment.py | 202-212 | identity_payload omits run_type + strategy_id | ⚠️ Warning (CR-06) | Cross-run_type/strategy ID collisions (contrived; param-hash differs in practice) |
| src/backtest/experiment.py | 293-320 | Baseline param guarantees unenforced ("must reference" by discipline) | ⚠️ Warning (CR-07) | Candidate params mislabeled as baseline possible |
| src/backtest/simulator.py | 156-222, 286-289 | TP2 documented in enums, never resolved (only SL/TP1/EOD) | ⚠️ Warning (WR-02) | TP2 legs silently dropped from PnL |
| src/backtest/simulator.py costs.py | 576-577, 142-162 | funding=0 hardcoded; slippage_model/spread strings hashed-but-unread; side-independent per-unit cost | ⚠️ Warning (WR-03) | Hashed cost assumptions exceed simulated math |
| src/backtest/report.py | 783 | Coverage `%` via integer `//` (2/3 → 66) | ⚠️ Warning (WR-05) | Lossy reporting at non-extreme ratios; tests cover only 100%/0% |
| src/backtest/report.py | 625-646 | Bootstrap means + drawdown resamples share identical RNG stream | ⚠️ Warning (WR-06) | Coupled resampling stages; needs domain-separated seeds |
| scripts/gen_phase6_fixtures.py | 361-536 | Per-case dirs never created → FileNotFoundError on fresh clone | ⚠️ Warning (WR-08) | Fixture regeneration claim fails on first run |
| src/domain/registry.py src/backtest/simulator.py | 41, 650 | `REGISTRY_ROOT = Path("params")` CWD-dependent | ⚠️ Warning (WR-09) | Non-root CWD → spurious UnregisteredParameterSet |
| src/backtest/simulator.py | 659-666 | Closed snapshots filtered from unsorted inputs (WR-01); validation helpers defined but uncalled on parse path (IN-01) | ℹ️ Info | Order-dependence smell; boundary validation gap (float-JSON/naive-datetime pass silently) |
| tests/test_backtest_*.py | — | Parity test hand-derives costs (IN-02a); no-lookahead exit decided on candle 0 (IN-02b); reproduce tests use `{}` stub path (IN-02c) | ℹ️ Info | Tests mask G1/CR-04 class defects — gap-closure must strengthen these tests |
| src/backtest/costs.py src/risk/sizing.py | 142-162 | Dimensionless rates added to price-unit sl_distance (parity preserved) | ℹ️ Info (IN-04) | Cross-phase units question for src/risk/, not Phase 6 alone |

Debt-marker scan (`TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER`) over src/backtest: no hits. Stub scan (empty returns, hardcoded `[]/{}/None` flowing to output): no stub patterns — failures are behavioral, not placeholder code.

### Human Verification Required

None. All truths were decided programmatically (code reading + green/red test runs + behavioral snippets). No visual, UX, realtime, or external-integration surface exists in this phase (pure deterministic modules).

### Gaps Summary

Four gaps block the phase goal; all are behavioral defects in substantive, wired code — not missing files:

1. **G1 — Reproducibility tripwire unimplemented (BKTS-02 core).** `reproduce()` ignores the record, `verify_experiment()` can only pass, and rebuilt records are mistyped. The "re-run the recorded tuple → byte-identical" claim has zero non-trivial exercise. Deepest gap: without it, Phase 6 cannot serve as the validation authority.
2. **G2 — Empty-1m crash (fail-closed violation).** One-line guard missing; behaviorally proven IndexError.
3. **G3 — Expiry clock wrong for multi-bar runs (canonical-use correctness).** Entry gate and risk gate disagree on wall-clock for the same bar; early signals systematically expire.
4. **G4 — Report digest wall-clock default (determinism contract).** Seeded bootstrap is sound; the envelope digest is not reproducible on the default path.

Related-grouping for `/gsd-plan-phase --gaps`: G1 is standalone (experiment.py). G2+G3 share the simulator entry/intrabar area but are independent one-line fixes. G4 is standalone (report.py). Suggested wave: G2+G3+G4 first (all small, test-strengthening included), G1 second (requires design: stored result digest at assemble time + typed parsing).

**Review-disposition note:** 06-REVIEW.md CR-05 (trailing-precision destruction) was **refuted** by direct behavioral evidence and is NOT carried as a gap. CR-02/CR-06/CR-07 and WR-01/02/03/05/06/08/09 are recorded as warnings (real, non-blocking: no must-have directly contradicted). IN-02 test-weakness findings should gate the gap-closure plans (fixed tests must exercise real paths, not the `{}` stub).

**Deferred items:** none. No later milestone phase reworks src/backtest/ (Phase 7 builds the paper engine forward; it does not repair backtest correctness), so all four gaps are actionable now.

---
_Verified: 2026-09-26T00:00:00Z_
_Verifier: the agent (gsd-verifier)_
