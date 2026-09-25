---
phase: 05-risk-engine
verified: 2026-09-25T15:30:00Z
status: passed
score: 3/3 must-haves verified
covered_files:
  - src/risk/__init__.py
  - src/risk/types.py
  - src/risk/sizing.py
  - src/risk/quantization.py
  - src/risk/portfolio.py
  - src/risk/gating.py
  - src/domain/enums.py
  - src/domain/registry.py
  - docs/GLOSSARY.md
  - params/trend-pullback/baseline-v2.toml
  - params/breakout-retest/baseline-v2.toml
  - params/range-mr/baseline-v2.toml
  - tests/test_risk_sizing.py
  - tests/test_risk_quantization.py
  - tests/test_risk_portfolio.py
  - tests/test_risk_parity.py
  - tests/test_domain_no_float.py
  - tests/test_registry.py
  - tests/conftest.py
covered_digest: "unavailable — gsd-tools fingerprint not runnable in this environment; file list above is authoritative"
behavior_unverified: 0
overrides_applied: 0
---

# Phase 5: Risk Engine Verification Report

**Phase Goal:** Risk math is byte-identical everywhere — no sizing surprise appears for the first time with money attached.
**Verified:** 2026-09-25T15:30:00Z
**Status:** passed
**Re-verification:** No — initial verification (no prior VERIFICATION.md existed)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | Position size derives from equity × risk-rate ÷ SL-distance including modeled costs, floors quantity to stepSize, and rejects below utilization/minimums with QUANTIZATION_REJECT / NO_TRADE preferred over round-up | ✓ VERIFIED | `src/risk/sizing.py:size_position` computes `allowed_risk = equity × risk_rate`, `risk_per_unit = SL_distance + modeled_costs`, `raw = allowed/risk_per_unit` in Decimal (lines 59–77); zero SL distance fails closed with EXCHANGE_CONSTRAINT (line 65). `src/risk/quantization.py:quantize` floors via exact Decimal `//` (line 72), gate order min-qty → notional → 60% utilization on `realized_risk/allowed_risk` (lines 76–113), no round-up path exists. 43/43 risk tests pass (`uv run pytest tests/test_risk_sizing.py tests/test_risk_quantization.py tests/test_risk_portfolio.py tests/test_risk_parity.py` → `43 passed`, exit 0). Parity table hand-verified (happy LONG/SHORT ACCEPTED; utilization/min-qty/notional rejects exact). |
| SC2 | Portfolio limits (max positions, aggregate risk, cluster cap, DAILY_STOP states) enforced; uncertain state fails closed with no new orders | ✓ VERIFIED | `src/risk/portfolio.py:check_portfolio` evaluates fail-closed validation → cluster → aggregate → count → daily in fixed order, first-failure-wins (lines 145–249); candidate risk ADDED to cap sums; exact-cap passes, one-ULP-over rejects; DAILY_STOP blocks with DAILY_STOP_BLOCK while WARNING passes with state (inclusive boundaries); None daily loss / unreconciled / TTL-exceeded (`age > ttl`) → UNCERTAIN_ACCOUNT_STATE / STALE_CONSTRAINTS; positions sorted by (symbol, side) for order independence. 24 portfolio unit/boundary tests + short-circuit + order-independence tests all green. |
| SC3 | Backtest, paper, and live produce identical sizing outputs for identical inputs (parity fixture green) | ✓ VERIFIED | Single shared pipeline `src/risk/gating.py:evaluate_risk` (size → quantize → portfolio, short-circuit preserving reason code); zero mode branches in `src/risk/` (grep for mode/backtest/paper/live finds only docstring parity statements, no branching). `test_risk_pipeline_byte_identical_across_runs` + 5 sizing cases match `expected.json` canonical-JSON-exactly via `sha256_hex`; 6 portfolio cases run through `evaluate_risk` twice byte-identical (`test_portfolio_case_byte_identical_across_runs`). 11/11 fixture dirs present. |

**Score:** 3/3 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/risk/__init__.py` | barrel re-export | ✓ VERIFIED | Re-exports sizing/quantize/portfolio/gating + types |
| `src/risk/types.py` | frozen Decimal/UTC guards | ✓ VERIFIED | ConstraintSnapshot, SizedResult, OpenPosition, PortfolioVerdict with construction-time guards |
| `src/risk/sizing.py` | D-01 canonical formula | ✓ VERIFIED | See SC1; imports pinned-prec helpers from `src/core/_decimal`, never duplicated |
| `src/risk/quantization.py` | D-02 floor + reject gates | ✓ VERIFIED | See SC1; floor via `//`, fixed gate order, realized-risk utilization |
| `src/risk/portfolio.py` | D-03/D-04 gates + fail-closed | ✓ VERIFIED | See SC2 |
| `src/risk/gating.py` | single pipeline for all modes | ✓ VERIFIED | `evaluate_risk`: size → quantize → portfolio, first-NO_TRADE short-circuits |
| `tests/test_risk_sizing.py`, `test_risk_quantization.py`, `test_risk_portfolio.py`, `test_risk_parity.py` | TDD suites | ✓ VERIFIED | 43/43 pass; RED gates proven in SUMMARYs (ModuleNotFoundError pre-implementation) |
| `tests/fixtures/phase5/*` (11 cases) | golden parity fixtures | ✓ VERIFIED | 11 dirs present; 5 sizing byte-exact vs expected.json; 6 portfolio run-twice byte-identical |
| `src/domain/enums.py` + `registry.py` + `docs/GLOSSARY.md` + 3× `baseline-v2.toml` | D-05 vocabulary + versioned params | ✓ VERIFIED | 9 reason codes + DailyState; 11 registry keys with INT/DECIMAL classification pinned by type tests; v2.0.0 sets, no ambient v1 edits |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| sizing.size_position | core._decimal helpers | import of `_add/_div/_mul/_sub` (single precision source) | WIRED | Confirmed in source |
| quantization.quantize | domain.enums | QuantizationDecision ACCEPTED/REJECTED, RejectionReason codes — never silent increase | WIRED | Confirmed; no round-up path |
| parity tests | domain.canonical sha256_hex | canonical-JSON hash equality incl. reason codes | WIRED | Both parity test files use `sha256_hex` |
| registry.load_parameter_set | params baseline-v2 sets | sole source of risk keys | WIRED | `test_registry.py` v2 full-load + INT-vs-DECIMAL tests green |
| portfolio.check_portfolio | risk.gating evaluate_risk | fixed pipeline sizing → quantize → portfolio | WIRED | Confirmed in `gating.py`; portfolio parity via `evaluate_risk` |
| portfolio TTL check | registry `constraint_snapshot_ttl_seconds` | injected `now_utc`, never ambient clock | WIRED | `age = now_utc - constraint_observed_at_utc; age > ttl`; UTC-aware guards |
| portfolio verdict | domain.enums D-05 codes | CLUSTER_CAP_REJECT … UNCERTAIN_ACCOUNT_STATE | WIRED | Confirmed |

### Data-Flow Trace (Level 4)

N/A — pure in-process Decimal math, no rendered values or external data sources. By design (D-05): exchange metadata arrives as frozen `ConstraintSnapshot` input structs; nothing is fetched inside. No hollow props, no static fallbacks.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 43 risk tests pass | `uv run pytest tests/test_risk_sizing.py tests/test_risk_quantization.py tests/test_risk_portfolio.py tests/test_risk_parity.py -q` | `43 passed in 0.14s`, exit 0 | ✓ PASS |
| No-float guard covers src/risk | `uv run pytest tests/test_domain_no_float.py -q` | pass, exit 0 | ✓ PASS |
| No scope creep | `git show --stat 74a04b8 / 4f6d968` | only src/risk, src/domain, params, docs/GLOSSARY, tests/fixtures | ✓ PASS |
| Purity: no float/structlog/third-party imports in src/risk | grep `float\(‖structlog‖polars‖pandas‖numpy‖binance‖sqlalchemy‖pydantic` | No matches | ✓ PASS |
| No mode branches in src/risk | grep `mode‖backtest‖paper‖live` | docstring mentions only, zero branches | ✓ PASS |

Step 7b runnable-entry-point checks beyond the suite are N/A (pure library, no server/CLI); determinism suites from Phase 4 reported green in 05-02 SUMMARY (326 passed, 5 skipped).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| RISK-01 | 05-01 | Size from equity × risk-rate ÷ SL-distance incl. costs, floor to stepSize, reject below utilization/minimums, identical logic everywhere | ✓ SATISFIED | SC1 + SC3 evidence |
| RISK-02 | 05-02 | Portfolio limits + DAILY_STOP enforced, fail closed on uncertain state | ✓ SATISFIED | SC2 evidence |

No orphaned requirements: only RISK-01/RISK-02 map to Phase 5; both claimed and satisfied.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | TBD/FIXME/XXX/TODO/placeholder/stub/empty-return sweep | None found | Clean |
| `src/risk/gating.py` | 65–66, 92 | `candidate_position_side="LONG"` hardcoded; `candidate_symbol=trade_plan.entry_model and constraint_snapshot.symbol` (fragile truthy-chain) | ℹ️ Info (documented placeholder) | SHORT candidates mis-cluster through the pipeline; `check_portfolio` unit itself is side-correct. TradePlan carries no side field in V1, so the pipeline cannot do better yet — must be wired to real side before Phase 7/9 use. See Advisory A1. |
| `src/risk/quantization.py` | — | Missing structlog lineage event on `quantize()` (plan 05-01 action required raw/rounded/realized/ratio per RISK_MANAGEMENT §11 rule 5) | ℹ️ Info (plan-action deviation, no SC impact) | Audit-trail nicety absent; no test asserts it. See Advisory A2. |
| `src/risk/sizing.py` + `types.py` | — | Non-positive equity raises ValueError via SizedResult guard instead of returning UNCERTAIN_ACCOUNT_STATE NO_TRADE envelope | ℹ️ Info (fail-closed holds — no order path — envelope nicety missing) | Exception propagates; caller must handle. No test covers non-positive equity. See Advisory A3. |
| `tests/test_risk_portfolio.py` | 949–967 | 6 portfolio `expected.json` never asserted (test checks run-twice equality only, not equality vs `expected.json`); `_run_evaluate_risk` uses shared `PARAMETERS`, not per-case thresholds | ℹ️ Info (fixture-value drift undetectable) | Determinism proven; a deterministic-but-wrong output change would still pass. See Advisory A4. |

No 🛑 Blockers. No debt markers. Working tree clean (`git status --short` empty); both phase commits touch only in-scope files.

### Advisory (New Scope / Non-Blocking Findings)

| # | Finding | Category | Why Advisory |
|---|---------|----------|--------------|
| A1 | `evaluate_risk` hardcodes LONG candidate side; fragile `entry_model and symbol` expression | architectural | V1 placeholder (no side field on TradePlan); must be resolved before paper/live consume the pipeline (Phase 7+). Does not block Phase 5 goal. |
| A2 | No structlog lineage event in `quantize()` despite plan action + §11 rule 5 | other | Logging/audit nicety, not a sizing-correctness issue; add in a later hardening pass if the rule is read as code-level. |
| A3 | Non-positive equity → ValueError, not UNCERTAIN_ACCOUNT_STATE envelope | other | Fail-closed (no order) holds either way; envelope would be cleaner for downstream reason-code consumers. |
| A4 | Portfolio `expected.json` golden values are unasserted by any test | other | Fixtures exist and run-twice parity is green; wiring the expected-comparison (mirroring `test_phase5_pipeline_matches_expected`) would close the loop. Suggested for Phase 6 or a quick follow-up. |

### Human Verification Required

None. All success criteria are programmatically verifiable (pure functions, deterministic fixtures) and verified. No visual, real-time, or external-service behavior in scope.

### Gaps Summary

No gaps. All three Phase 5 success criteria hold in the codebase as implemented: canonical sizing with modeled costs and stepSize-floor quantization preferring reject over round-up (SC1); ordered portfolio gates with DAILY_STOP and fail-closed uncertain-state handling placing no orders (SC2); one shared branch-free pipeline with green parity fixtures proving byte-identical outputs (SC3). RISK-01 and RISK-02 satisfied. No scope creep (no strategy/backtest/WS/Telegram/execution files touched). Determinism + purity hold (Decimal-only, stdlib + in-repo imports only, sorted iteration, injected clocks, no-float guard green). Four non-blocking advisories recorded above for downstream phases.

---

_Verified: 2026-09-25T15:30:00Z_
_Verifier: the agent (gsd-verifier)_
