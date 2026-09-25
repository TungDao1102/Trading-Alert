---
phase: 05-risk-engine
reviewed: 2026-09-25T14:45:00Z
depth: deep
files_reviewed: 20
files_reviewed_list:
  - src/risk/__init__.py
  - src/risk/types.py
  - src/risk/sizing.py
  - src/risk/quantization.py
  - src/risk/gating.py
  - src/risk/portfolio.py
  - src/domain/enums.py
  - src/domain/registry.py
  - params/trend-pullback/baseline-v2.toml
  - params/breakout-retest/baseline-v2.toml
  - params/range-mr/baseline-v2.toml
  - docs/GLOSSARY.md
  - tests/conftest.py
  - tests/test_risk_sizing.py
  - tests/test_risk_quantization.py
  - tests/test_risk_portfolio.py
  - tests/test_risk_parity.py
  - tests/test_domain_no_float.py
  - tests/test_domain_enums.py
  - tests/test_registry.py
findings:
  critical: 2
  warning: 11
  info: 4
  total: 17
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-09-25T14:45:00Z
**Depth:** deep
**Files Reviewed:** 20
**Status:** issues_found

## Summary

Deep review of the Phase 5 risk engine traced the full `size_position → quantize → check_portfolio` pipeline in `src/risk/gating.py:evaluate_risk`, the Decimal/float boundary, fail-closed paths, and reason-code consistency across `src/risk/types.py`, `src/domain/enums.py`, fixtures, and GLOSSARY §9. All 105 tests in scope pass, reason codes are canonical everywhere checked, and the no-float guard is green — but adversarial probing (runtime probes against the actual source, all confirmed) found **2 critical fail-closed/correctness holes** and 11 warnings.

The dominant theme: **the pipeline does not know the candidate's identity**. `TradePlan` carries no `symbol` or side/direction field, so `evaluate_risk` hardcodes `"LONG"` (CR-01, SHORT plans mis-cluster and can wrongfully PASS) and derives the symbol through a truthy-chain accident (WR-01). The second theme is **unvalidated boundaries on a fail-closed component**: the TTL gate is skippable via a `None` default (CR-02), sides are case-sensitive raw strings (WR-04), and numeric inputs accept floats/silent truncations (WR-05, WR-06).

### Advisory re-verification (from 05-VERIFICATION.md)

| # | Claim | Verdict |
|---|-------|---------|
| A1 | LONG side hardcoded placeholder | **CONFIRMED STILL OPEN** → CR-01 + WR-01. `gating.py:66,92` still hardcode `"LONG"`; `gating.py:65` still uses the `entry_model and symbol` truthy-chain. |
| A2 | Missing structlog lineage event | **RESOLVED**. `quantization.py:174-202` emits `risk.quantize` on every accept and reject path; `test_quantize_emits_lineage_event_on_accept/reject` pass. Residual robustness note kept as IN-01. |
| A3 | Non-positive equity raises ValueError, not NO_TRADE envelope | **CONFIRMED STILL OPEN** → WR-09. Probed: `AccountState(equity=0)` raises `ValueError: equity must be > 0` (`src/core/types.py:323`); no `UNCERTAIN_ACCOUNT_STATE` envelope is ever produced for this input. |
| A4 | Portfolio goldens unasserted | **RESOLVED**. `test_portfolio_case_matches_expected_json` (`test_risk_portfolio.py:980-996`) now asserts all 6 portfolio cases canonical-JSON-exactly; full in-scope suite is 105 passed. |

Reason-code consistency verified clean: `RejectionReason`/`DailyState` match GLOSSARY §§8.1/9 verbatim (pinned by `test_domain_enums.py` Beh. 8), all `src/risk` emissions use canonical codes only, and every `tests/fixtures/phase5/*/expected.json` carries a canonical code. No secrets, injection, or eval-style issues (pure Decimal math, no I/O).

## Critical Issues

### CR-01: evaluate_risk hardcodes candidate side LONG — SHORT plans mis-cluster and can wrongfully PASS

**File:** `src/risk/gating.py:66,92`
**Issue:** Both `check_portfolio` call sites pass `candidate_position_side="LONG"` unconditionally. The cluster gate (`portfolio.py:203-210`) only sums open positions whose `position_side` equals the candidate side, so a SHORT candidate is checked against LONG positions: same-symbol SHORT cluster exposure is invisible, `cluster_sum` under-counts, and a trade that should hit `CLUSTER_CAP_REJECT` returns PASS. This is active incorrect behavior on a money-attached path, not a latent nit — every SHORT plan flowing through `evaluate_risk` is evaluated with the wrong side. Root cause: `TradePlan` (`src/domain/trade_plan.py:59-78`) has no symbol or direction/side field, so the pipeline cannot do better without a schema change; the placeholder comment admits this but the code ships the wrong answer rather than failing closed for unknown side.
**Fix:**
```python
# Option A (fail closed until schema exists): refuse to guess.
# Add a required candidate_position_side parameter to evaluate_risk
# (no default), validated against {"LONG", "SHORT"}; never hardcode.
# Option B (schema fix, Phase 7+ prerequisite): add direction/symbol
# to TradePlan and thread plan.direction.value through both call sites.
from src.domain.enums import Direction
if candidate_position_side not in (Direction.LONG.value, Direction.SHORT.value):
    raise ValueError(f"unknown side {candidate_position_side!r} — refusing to evaluate")
```

### CR-02: TTL freshness gate is skipped when constraint_observed_at_utc is None — fail-open default

**File:** `src/risk/portfolio.py:161`
**Issue:** The staleness check only runs `if constraint_observed_at_utc is not None:`. The parameter defaults to `None`, so any direct caller that omits it bypasses the RISK_MANAGEMENT §12 freshness gate entirely and gets a PASS on arbitrarily stale (or missing) exchange metadata. Probed against live source: `check_portfolio(..., constraint_observed_at_utc=None)` with an otherwise-passing input returns `is_no_trade=False / OK`. A fail-closed component must not have a default that disables a safety gate; `evaluate_risk` always passes the timestamp today, but the public signature invites Phase-7+ callers to silently opt out.
**Fix:**
```python
if constraint_observed_at_utc is None:
    return PortfolioVerdict(
        is_no_trade=True,
        sized=None,
        reason_code=RejectionReason.STALE_CONSTRAINTS.value,
        daily_state=daily_state,  # derive first — see WR-03
    )
_require_utc_aware(constraint_observed_at_utc, "constraint_observed_at_utc")
age = now_utc - constraint_observed_at_utc
if age > ttl or age < timedelta(0):  # also reject future-dated snapshots (WR-08)
    ...
```

## Warnings

### WR-01: Fragile truthy-chain derives candidate symbol; TradePlan has no symbol field

**File:** `src/risk/gating.py:65`
**Issue:** The sizing-reject path passes `candidate_symbol=trade_plan.entry_model and constraint_snapshot.symbol`. Since `entry_model` is a guarded non-empty string (always truthy), this accidentally evaluates to the snapshot symbol — correct output by coincidence, wrong expression by construction. It is also inconsistent with the normal path (`gating.py:91`, plain `constraint_snapshot.symbol`). Deeper: neither path can use the plan's symbol because `TradePlan` has no symbol field at all; candidate identity silently comes from constraints, so a plan/snapshot symbol mismatch would never be detected.
**Fix:** Use `constraint_snapshot.symbol` on both paths today; add `symbol` (+ direction, see CR-01) to `TradePlan` before Phase 7 and assert `plan.symbol == constraint_snapshot.symbol` in `evaluate_risk`.

### WR-02: Raw Decimal ops break the pinned prec-28 determinism guarantee

**File:** `src/risk/gating.py:52`, `src/risk/quantization.py:80-81`
**Issue:** `sizing.py`/`portfolio.py` correctly use pinned `_div/_mul/_add/_sub` from `src/core/_decimal.py`, but `evaluate_risk` computes `entry_ref = (entry_min + entry_max) / Decimal("2")` with ambient-context operators, and `quantize` floors with raw `//` and `*`. Probed: with ambient `prec=10`, the raw `entry_ref` for an odd-sum zone is `50000.55555` vs pinned-prec-28 `50000.55555555505555555550555` — the "byte-identical everywhere regardless of ambient context" claim fails the moment any host/thread mutates the default context. The parity tests cannot catch this either: `test_risk_parity.py:96,106-108` and `test_risk_portfolio.py:169,178-180` compute `entry_ref`/`allowed_risk`/`risk_per_unit` with the same raw operators.
**Fix:**
```python
from src.core._decimal import _add, _div
entry_ref = _div(_add(trade_plan.entry_min_price, trade_plan.entry_max_price), Decimal("2"))
# quantize.py: route steps*step through _mul, or document why // is context-proof
```

### WR-03: Upstream-reject and fail-closed verdicts mask daily_state as NORMAL

**File:** `src/risk/portfolio.py:106-114, 145-171`
**Issue:** The `sized.is_no_trade` short-circuit and all three fail-closed returns (`None` daily loss, unreconciled, stale) hardcode `daily_state=DailyState.NORMAL` without deriving it. Probed: an upstream `MIN_QTY_REJECT` with `daily_loss_quote=100` (== stop threshold) returns `daily_state=NORMAL`, hiding an active `DAILY_STOP` from the Phase-8 SAFE_MODE consumers the docstring says read this field. Same masking applies when constraints are stale *and* the daily stop is hit.
**Fix:** Derive `daily_state` from `daily_loss_quote` + thresholds first (when `daily_loss_quote is not None`), then attach the derived state to every fail verdict instead of `NORMAL`.

### WR-04: position_side is an unvalidated string — case mismatch silently disables cluster counting

**File:** `src/risk/types.py:139-160`, `src/risk/portfolio.py:203-210`
**Issue:** `OpenPosition.position_side` and `candidate_position_side` accept any non-empty string; the cluster gate compares with `==`. Probed: identical exposure evaluated with `candidate_position_side="long"` returns PASS where `"LONG"` returns `CLUSTER_CAP_REJECT` — a casing typo converts a block into an order. No `Direction`-enum enforcement exists anywhere on this path.
**Fix:** Validate both against the `Direction` enum at the boundary (`OpenPosition.__post_init__` + `check_portfolio` entry) and reject unknown values loudly instead of treating them as "matches nothing."

### WR-05: Threshold extraction truncates and raises instead of failing closed with reason codes

**File:** `src/risk/portfolio.py:122-133`
**Issue:** `max_open_positions = int(parameter_set["max_open_positions"])` silently truncates non-int numerics (`Decimal("2.9")` → `2`, confirmed by probe — no error); a missing key raises bare `KeyError`, and a wrong-typed threshold raises `TypeError` from `_require_decimal`. The registry loader guards all of this at load time, but `check_portfolio` accepts any caller-built dict, so a malformed `parameter_set` crashes the risk call (exception, no verdict) instead of returning a `NO_TRADE` envelope with `UNCERTAIN_ACCOUNT_STATE`.
**Fix:** Validate each threshold's type explicitly (`isinstance int, rejecting bool`; `Decimal` for money fields) and return `UNCERTAIN_ACCOUNT_STATE` on violation; use `parameter_set["..."]` misses as the same envelope rather than `KeyError`.

### WR-06: quantize() accepts float-typed numeric inputs — D-12 boundary hole

**File:** `src/risk/quantization.py:32-40`
**Issue:** `allowed_risk`, `risk_per_unit`, `minimum_risk_utilization_after_rounding`, and `reference_price` have no `_require_decimal` guards (unlike `sized.realized_risk` in `portfolio.py:118` or `entry_ref`/`costs` in `sizing.py:56-57`). Probed: `minimum_risk_utilization_after_rounding=0.6` (float) is silently accepted — `Decimal < float` comparisons execute with binary-float noise inside the 60% gate, exactly what D-12 exists to prevent. A float `reference_price`/`risk_per_unit` instead crashes with `TypeError` deep in `_mul` rather than at the boundary.
**Fix:** Add `_require_decimal` guards for all four inputs at the top of `quantize()` (and mirror them in `evaluate_risk` before the call).

### WR-07: No registry-rate → absolute-amount conversion exists; raw rates as caps block everything with misleading codes

**File:** `src/risk/gating.py:45-49`, `src/risk/portfolio.py:173-191`
**Issue:** The docstrings state the caller converts registry rates (e.g. `cluster_cap = 0.005`) to absolute quote amounts before calling, and every test passes a hand-built absolute `PARAMETERS` dict — but no `resolve_thresholds`-style helper exists anywhere, and `evaluate_risk` does not perform the conversion. The first caller to pass raw registry values compares ~50 USDT risk sums against `0.005` caps and rejects every trade with `CLUSTER_CAP_REJECT`. Fail-closed direction, but a total entry block wearing the wrong reason code, with the contradictory portfolio comment block (`:173-183`, "we multiply… we treat as absolute") as the only specification.
**Fix:** Implement one `resolve_absolute_thresholds(parameter_set, equity)` helper (rate × equity via pinned `_mul`), call it in `evaluate_risk`, and delete the contradictory comment block; add a test passing raw registry rates end-to-end.

### WR-08: Future-dated constraint snapshots pass the TTL check (negative age accepted)

**File:** `src/risk/portfolio.py:163-164`
**Issue:** `age = now_utc - constraint_observed_at_utc; if age > ttl` — a snapshot timestamped 5h in the future yields negative age, which is never `> ttl`. Probed: `observed_at = now + 5h` returns PASS/OK. Clock-skewed or corrupt upstream timestamps should fail closed, not bypass freshness.
**Fix:** Reject `age < timedelta(0)` as `STALE_CONSTRAINTS` (see CR-02 fix snippet).

### WR-09: Non-positive equity raises ValueError instead of returning an UNCERTAIN_ACCOUNT_STATE envelope (advisory A3, still open)

**File:** `src/core/types.py:320-327` (guard), `src/risk/sizing.py:30-56` (no envelope path)
**Issue:** `AccountState.__post_init__` requires `equity > 0`, so zero/negative equity raises `ValueError` at construction — confirmed by probe — and `size_position` has no path that converts degenerate account state into a `SizedResult`/`PortfolioVerdict` NO_TRADE envelope. Fail-closed holds (no order path), but downstream reason-code consumers (journal, Telegram, SAFE_MODE) get an exception instead of `UNCERTAIN_ACCOUNT_STATE`, and no test covers the input.
**Fix:** Either construct the envelope at the `evaluate_risk` boundary (try/except around account validation → `UNCERTAIN_ACCOUNT_STATE` verdict) or document the exception contract and add a test pinning it.

### WR-10: quantize() re-gates already-rejected SizedResults and overwrites the upstream reason

**File:** `src/risk/quantization.py:32-59`
**Issue:** `quantize` never checks `sized.is_no_trade`. A direct caller passing a rejected result (e.g. `EXCHANGE_CONSTRAINT` from zero SL distance, with `quantity_before_rounding=0`) gets the floor path: `rounded=0 < min_quantity` → `MIN_QTY_REJECT`, destroying the true reason. The `evaluate_risk` pipeline is safe (it skips `quantize` on sizing reject, `gating.py:62-74`), so this bites the next direct re-user of the function — reason-code integrity for the audit trail.
**Fix:** Short-circuit at the top: `if sized.is_no_trade: return sized` (or re-emit lineage and return unchanged).

### WR-11: reason_code / quantization_decision are unvalidated free strings, unlike the Phase-4 envelope discipline

**File:** `src/risk/types.py:94-132`
**Issue:** `SizedResult` and `PortfolioVerdict` only require non-empty strings; probed: `reason_code="BOGUS_CODE"`, `quantization_decision="MADE_UP"` construct fine. `SetupResult` in `src/core/types.py:258-261` validates against the canonical vocabulary — risk output, which feeds journals and Telegram payloads, is held to a weaker standard, so a typo'd code propagates silently to every downstream consumer.
**Fix:** Validate both fields against `RejectionReason` values (+ `"OK"`) and `QuantizationDecision` values in `__post_init__`, mirroring `_SETUP_REASONS`.

## Info

### IN-01: structlog failure modes propagate out of pure risk math

**File:** `src/risk/quantization.py:174-202`
**Issue:** `_emit_lineage` does a hard `import structlog` + direct `get_logger().info(...)` on every `quantize()` call. structlog is a declared dependency so the import holds, but any logging-pipeline exception (misconfigured processor, closed handler) now crashes sizing instead of merely losing an audit event. The local import preserves module-level purity cosmetically, not operationally.
**Fix:** Wrap the emit body in `try/except Exception: pass` (logging must never break risk math), or move lineage emission to the caller edge.

### IN-02: Non-cluster symbols are still subject to the cluster cap (single-trade cap with a cluster-coded reason)

**File:** `src/risk/portfolio.py:201-217`
**Issue:** When `candidate_symbol` is outside `CLUSTER_SYMBOLS` (e.g. BNBUSDT), `cluster_open_risk` stays 0 but `cluster_sum = 0 + candidate_risk` is still compared to the cap — any single trade riskier than `cluster_cap` rejects with `CLUSTER_CAP_REJECT` even with an empty book. If a single-trade cap is intended, it deserves its own code; if not, gate the check on `candidate_in_cluster`. Currently fail-closed, but the reason misleads post-trade analysis.
**Fix:** Document the intent in the D-03 comment, or skip the cluster gate (with an explicit comment) for non-cluster candidates.

### IN-03: Daily-state edge semantics undocumented (negative PnL, inverted thresholds)

**File:** `src/risk/portfolio.py:53-70`
**Issue:** Negative `daily_loss_quote` (profitable day) maps to NORMAL — presumably correct but unstated; a misconfiguration with `warning_threshold > stop_threshold` silently degrades (values between the two report NORMAL instead of WARNING). No validation that `warning <= stop` exists at the boundary.
**Fix:** Assert `warning_threshold_quote <= stop_threshold_quote` at `check_portfolio` entry (fail closed on misconfiguration) and document the negative-PnL mapping.

### IN-04: Purity docstring overstates the contract ("only" stdlib + _decimal)

**File:** `src/risk/__init__.py:3-7`
**Issue:** The package docstring claims it imports "NOTHING … stdlib + Decimal + `src/core/_decimal.py` only," but `sizing.py`/`gating.py` import `src.core.types`, `src.domain.trade_plan`, and `src.domain.enums` by design (mirroring the Phase-4 precedent). The enforced invariant is really "no third-party / exchange-SDK imports."
**Fix:** Reword to "stdlib + Decimal + in-repo pure modules (`src/core/_decimal`, `src/core/types`, `src/domain/*`); no third-party, SDK, ORM, or framework imports" so the next reader does not misread a legitimate import as a violation.

---

_Reviewed: 2026-09-25T14:45:00Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
