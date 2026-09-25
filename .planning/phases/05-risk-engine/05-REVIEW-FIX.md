---
phase: 05-risk-engine
fixed_at: 2026-09-25T16:09:24Z
review_path: C:/Users/daotu/OneDrive/Documents/Trading-Alert/.planning/phases/05-risk-engine/05-REVIEW.md
iteration: 1
findings_in_scope: 13
fixed: 13
skipped: 0
status: all_fixed
---

# Phase 05: Code Review Fix Report

**Fixed at:** 2026-09-25T16:09:24Z
**Source review:** C:/Users/daotu/OneDrive/Documents/Trading-Alert/.planning/phases/05-risk-engine/05-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 13 (2 critical + 11 warnings; 4 info items out of scope)
- Fixed: 13
- Skipped: 0

**Verification environment:** main checkout (workflow.use_worktrees=false, no isolated worktree). Per-fix verification: Tier 1 re-read always; Tier 2 Python `ast.parse` syntax check always; behavioral runtime probes for CR-01, CR-02, WR-02, WR-03, WR-04, WR-05, WR-08, WR-10. Full in-scope suite run once at the end via project venv: **107 passed** (105 pre-existing + 2 new pinning tests).

## Fixed Issues

### CR-01: evaluate_risk hardcodes candidate side LONG — SHORT plans mis-cluster and can wrongfully PASS

**Files modified:** `src/risk/gating.py`, `tests/test_risk_portfolio.py`
**Commit:** c06ff5f
**Applied fix:** Added a required keyword-only `candidate_position_side` parameter (no default) to `evaluate_risk`, validated against `Direction` LONG/SHORT with `ValueError` on unknown side (refuse to guess, fail closed). Both `check_portfolio` call sites now thread the parameter through; no hardcoded `"LONG"` remains. Updated `_run_evaluate_risk` test helper to pass `"LONG"` explicitly, preserving parity-golden byte-identity (all 6 golden cases use LONG positions).

### CR-02: TTL freshness gate is skipped when constraint_observed_at_utc is None — fail-open default

**Files modified:** `src/risk/portfolio.py`, `tests/test_risk_portfolio.py`
**Commit:** b571b9b
**Applied fix:** `constraint_observed_at_utc=None` now returns `STALE_CONSTRAINTS` with the derived daily state instead of bypassing the §12 gate. Updated the 13 direct `check_portfolio` test call sites that relied on the fail-open default to pass `constraint_observed_at_utc=FROZEN_NOW` explicitly (age 0, verdicts unchanged). `evaluate_risk` is unaffected (it always forwards the snapshot timestamp, which is construction-guarded non-null).

### WR-01: Fragile truthy-chain derives candidate symbol; TradePlan has no symbol field

**Files modified:** `src/risk/gating.py`
**Commit:** 2729d1a
**Applied fix:** Replaced `trade_plan.entry_model and constraint_snapshot.symbol` with plain `constraint_snapshot.symbol` on the sizing-reject path, matching the normal path. (Adding `symbol`/`direction` to `TradePlan` stays a Phase 7+ schema prerequisite, as the review notes.)

### WR-02: Raw Decimal ops break the pinned prec-28 determinism guarantee

**Files modified:** `src/risk/gating.py`, `src/risk/quantization.py`
**Commit:** 8439391
**Applied fix:** `entry_ref` now computes via `_div(_add(min, max), Decimal("2"))`; the quantize floor rescales via `_mul(steps, step)`. Runtime probe confirmed: pinned output matches the legacy value under default context (byte-identity preserved) and is immune to ambient `prec=10` (raw `50000.55555` vs pinned `50000.555555555055555555`).

### WR-03: Upstream-reject and fail-closed verdicts mask daily_state as NORMAL

**Files modified:** `src/risk/portfolio.py`
**Commit:** 04a4ba9
**Applied fix:** Daily state is derived once (when `daily_loss_quote` is known) before any verdict, and the sized short-circuit, unreconciled, and stale paths now carry the derived state. Probe of the review's exact case (upstream `MIN_QTY_REJECT` + daily loss 100) now returns `DAILY_STOP` instead of `NORMAL`; unknown-loss and rejected+unknown-loss behaviors are byte-identical to before. All 6 parity goldens still match.

### WR-04: position_side is an unvalidated string — case mismatch silently disables cluster counting

**Files modified:** `src/risk/types.py`, `src/risk/portfolio.py`
**Commit:** 46d4b72
**Applied fix:** `OpenPosition.__post_init__` rejects any `position_side` outside `Direction` (LONG/SHORT) with `ValueError`; `check_portfolio` validates `candidate_position_side` the same way at entry. Probe confirmed `"long"` is now rejected while `"LONG"` passes. All existing tests/fixtures use uppercase LONG — no suite changes needed.

### WR-05: Threshold extraction truncates and raises instead of failing closed with reason codes

**Files modified:** `src/risk/portfolio.py`
**Commit:** 77f88b1
**Applied fix:** New `_extract_thresholds` helper: `max_open_positions` must be non-bool `int` (no `int(Decimal("2.9"))` truncation); money fields must be `Decimal`; missing keys return `None` instead of raising `KeyError`. Any violation yields an `UNCERTAIN_ACCOUNT_STATE` envelope with `NORMAL` state. Probes confirmed for truncated count, bool count, missing key, and float money threshold; valid sets still pass.

### WR-06: quantize() accepts float-typed numeric inputs — D-12 boundary hole

**Files modified:** `src/risk/quantization.py`
**Commit:** fb1097b
**Applied fix:** Added a local `_require_decimal` helper (mirroring the sizing/portfolio boundary pattern) and guards for `allowed_risk`, `risk_per_unit`, `minimum_risk_utilization_after_rounding`, and `reference_price` at the top of `quantize()`. Float inputs now raise `TypeError` at the boundary instead of executing binary-float comparisons inside the 60% gate or crashing deep in `_mul`.

### WR-07: No registry-rate → absolute-amount conversion exists; raw rates as caps block everything with misleading codes

**Files modified:** `src/risk/portfolio.py`, `src/risk/__init__.py`, `src/risk/gating.py`, `tests/test_risk_portfolio.py`
**Commit:** ef425a6
**Applied fix (adapted):** Implemented and exported `resolve_absolute_thresholds(parameter_set, equity)` (rate × equity via pinned `_mul`, loud on missing keys/bad types/non-positive equity, input never mutated); replaced the contradictory portfolio comment block with a one-paragraph absolute-amount contract; `evaluate_risk` docstring now points raw-registry callers at the helper. Deliberately did NOT auto-call the helper inside `evaluate_risk`: the pipeline/test/parity contract is absolute quote amounts, and auto-conversion would double-convert existing callers and break the parity goldens (rate vs absolute is not auto-discriminable). Added `test_resolve_absolute_thresholds_converts_rates` pinning rates→absolutes at equity=10000.

### WR-08: Future-dated constraint snapshots pass the TTL check (negative age accepted)

**Files modified:** `src/risk/portfolio.py`
**Commit:** 5dc606a
**Applied fix:** The TTL condition is now `age > ttl or age < timedelta(0)` — a snapshot 5h in the future returns `STALE_CONSTRAINTS` (probe-confirmed) instead of PASS.

### WR-09: Non-positive equity raises ValueError instead of returning an UNCERTAIN_ACCOUNT_STATE envelope (advisory A3, still open)

**Files modified:** `src/risk/gating.py`, `tests/test_risk_sizing.py`
**Commit:** 77e2131
**Applied fix:** Took the review's second option (document + pin): `evaluate_risk` docstring now records that `AccountState` construction raises `ValueError` for `equity <= 0` — that exception IS the fail-closed contract (no order path exists past it) — and that callers map it to `UNCERTAIN_ACCOUNT_STATE` downstream. Added `test_non_positive_equity_raises_at_account_boundary` pinning the `ValueError` for zero and negative equity. (An envelope inside `evaluate_risk` is impossible: construction fails at the call site before the function is entered.)

### WR-10: quantize() re-gates already-rejected SizedResults and overwrites the upstream reason

**Files modified:** `src/risk/quantization.py`
**Commit:** e74cb33
**Applied fix:** `quantize()` short-circuits at the top with `if sized.is_no_trade: return sized` — the rejected envelope (with its true reason) passes through untouched. Probe confirmed an `EXCHANGE_CONSTRAINT` reject is no longer overwritten with `MIN_QTY_REJECT`. The `evaluate_risk` pipeline already skipped `quantize` on reject, so pipeline behavior is unchanged.

### WR-11: reason_code / quantization_decision are unvalidated free strings, unlike the Phase-4 envelope discipline

**Files modified:** `src/risk/types.py`
**Commit:** 4639a34
**Applied fix:** `SizedResult.__post_init__` now validates `reason_code` against `RejectionReason` values + `"OK"` and `quantization_decision` against `QuantizationDecision` values; `PortfolioVerdict.__post_init__` validates `reason_code` the same way — mirroring `_SETUP_REASONS` in `src/core/types.py`. Verified no in-repo or test construction uses non-canonical codes (the `"ACCEPT"` strings in `test_domain_mappers*.py` attach to domain mapper types, not risk envelopes — untouched).

---

_Fixed: 2026-09-25T16:09:24Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_
