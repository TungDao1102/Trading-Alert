---
phase: "04"
slug: "pure-core-feature-strategy-planner"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: "2026-09-23"
validated: "2026-09-25"
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: 04-RESEARCH.md ## Validation Architecture (Nyquist).
> Audit: retroactive validation 2026-09-25 — all 12 executed tasks mapped to green automated tests, zero gaps.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >= 9 (`pytest 9.1.1` verified), `asyncio_mode = "auto"` |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, `testpaths = ["tests"]`) |
| **Quick run command** | `uv run pytest tests/ -q -x` |
| **Full suite command** | `uv run pytest tests/ -q` (+ `ruff check src tests` + `mypy` per gates) |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/ -q -x`
- **After every plan wave:** Run full suite + `ruff check` + `ruff format --check` + `mypy`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | STRAT-01/02/03 (tracer slice) | T-04-01/02/03 | Closed candles → byte-identical Signal + TradePlan; SignalId deterministic; DEFERRED_TO_RISK | unit (tracer e2e) | `uv run pytest tests/test_core_tracer.py -q` | ✅ | ✅ green (5 passed) |
| 04-01-02 | 01 | 1 | D-06 | — | Enum values verbatim, unknown → load-time ValueError | unit | `uv run pytest tests/test_domain_enums.py -q` | ✅ | ✅ green (26 passed, 14 new) |
| 04-01-03 | 01 | 1 | D-10 | T-04-03/04 | String-only Decimal; no-float AST guard over `src/core/*` | static + harness | `uv run pytest tests/test_domain_no_float.py tests/test_fixture_harness.py -q` | ✅ | ✅ green (11 passed) |
| 04-02-01 | 02 | 2 | STRAT-01 | T-04-01/02 | Warm-up / gap / quality rejects fail closed with exact reason_code | unit (RED-first) | `uv run pytest tests/test_core_features.py -q` | ✅ | ✅ green (19 passed) |
| 04-02-02 | 02 | 2 | STRAT-02 | T-04-03 | No-lookahead, prefix-invariance, close-timing vs real `evaluate` (zero placeholders) | determinism suites | `uv run pytest tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_candle_close_timing.py tests/test_domain_boundary.py -q` | ✅ | ✅ green (19 passed) |
| 04-02-03 | 02 | 2 | STRAT-01/02 | T-04-04 | 1H/4H independence proven; golden features/signals byte-exact | unit + fixtures | covered by 04-02-01/02 commands + `tests/test_fixture_harness.py` | ✅ | ✅ green |
| 04-03-01 | 03 | 2 | STRAT-03 | T-04-05 | TP2 = entry_ref + 2·minimum_rr·risk (option A); locked fingerprint key list | unit (checkpoint) | `uv run pytest tests/test_core_planner.py -q` | ✅ | ✅ green |
| 04-03-02 | 03 | 2 | STRAT-03 | T-04-03/05 | RR gate hard (RR_TOO_LOW, never downgrade); plan_hash recomputable; DEFERRED_TO_RISK | unit (RED-first) | `uv run pytest tests/test_core_planner.py -q` | ✅ | ✅ green (11 passed) |
| 04-03-03 | 03 | 2 | STRAT-03 | T-04-02 | 7 family B/C keys whitelisted + typed; both TOMLs load with stable hashes | unit | `uv run pytest tests/test_registry.py tests/test_registry_gate.py -q` | ✅ | ✅ green |
| 04-04-01 | 04 | 3 | STRAT-02 | T-04-05/06 | Breakout-retest: close-based countdown, window-expiry NO_TRADE, no collisions | unit (RED-first) | `uv run pytest tests/test_core_strategy_breakout_retest.py -q` | ✅ | ✅ green |
| 04-04-02 | 04 | 3 | STRAT-02 | T-04-03/07 | Range-mr: touch/aging/break-invalidation (invalidate-not-redraw); zero winner language | unit (RED-first) | `uv run pytest tests/test_core_strategy_range_mr.py -q` | ✅ | ✅ green |
| 04-04-03 | 04 | 3 | STRAT-02/03 | — | B/C golden fixtures byte-exact; per-family determinism; phase gate green | full gate | `uv run pytest tests/ -q` | ✅ | ✅ green (174 passed, 0 failed) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Deviation (documented in 04-04-SUMMARY.md):** `tests/test_core_strategy_trend_pullback.py` (named in 04-04-PLAN frontmatter) was never created; trend-pullback per-family coverage lives in `test_core_tracer.py` + `test_core_planner.py` + `test_core_features.py` (all green). No redundancy created. Not a gap.

---

## Wave 0 Requirements

- [x] `tests/fixtures/phase4/` — candles.csv (1H + 4H closed, incl. gap injection + warm-up-short prefixes) + parameters.json + expected_{features,signals,plans}.json (byte-exact, hand-computed EMA/ATR seed values)
- [x] `tests/test_core_features.py`, `tests/test_core_strategy_*.py` (tracer + 2 slices), `tests/test_core_planner.py` — real expectations replacing Phase-3 placeholder mappings
- [x] `tests/test_domain_no_float.py::SCANNED_FILES` — `src/core/*` modules appended
- [x] `tests/conftest.py` — `phase4_*` fixtures mirroring the `phase3_*` loader pattern

---

## Manual-Only Verifications

All phase behaviors have automated verification. No manual-only items.

**Out-of-scope observations (other phases' scope, reported not fixed):**
- 10 test modules fail collection on missing optional third-party deps (`sqlalchemy`, `structlog`, `duckdb`, `polars`, `binance_sdk_*`): `test_adapter_strictness`, `test_backfill`, `test_backup`, `test_collector`, `test_coverage`, `test_domain_mappers`, `test_domain_mappers_pg`, `test_metadata`, `test_quality_gates`, `test_tracer_slice`. Phase-4 gate = full suite minus these 10 files → 174 passed, 0 failed.
- `ruff check` on phase-4 test files reports 4 cosmetic findings (I001 import sort + F401 unused import in `test_core_features.py`; 2× UP017 `timezone.utc` → `UTC` in `test_domain_boundary.py`). Behavior-green; needs a dedicated lint pass, not a behavior change.
- `mypy` binary not installed in this environment (`uv run mypy` → program not found); 04-04-SUMMARY records mypy-strict-clean over `src/core` from execution time. Re-verify when mypy is available.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-09-25

---

## Validation Audit 2026-09-25

| Metric | Count |
|--------|-------|
| Tasks audited | 12 (4 plans × 3 tasks) |
| COVERED | 12 |
| PARTIAL | 0 |
| MISSING | 0 |
| Gaps found | 0 |
| Resolved | 0 (no auditor spawn needed — Steps 4–5 skipped per workflow §3) |
| Escalated | 0 |

Evidence (all run 2026-09-25, `uv run pytest`):
- Core phase-4 files (tracer, features, planner, 2 family slices): 50 passed
- Determinism suites + enums + no-float guard + registry + harness: 84 passed
- Full suite minus 10 pre-existing broken-collection modules: 174 passed, 0 failed
