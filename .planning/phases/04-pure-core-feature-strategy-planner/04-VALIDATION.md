---
phase: "04"
slug: "pure-core-feature-strategy-planner"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-23"
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: 04-RESEARCH.md ## Validation Architecture (Nyquist).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >= 9, `asyncio_mode = "auto"` |
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
| 04-01-01 | 01 | 1 | STRAT-01 | T-04-01 / malformed-candle-reject | Fail-closed quality rejects + GAP_IN_SOURCE invalid, never phantom signal | unit (golden fixtures) | `uv run pytest tests/test_core_features.py -q` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | STRAT-02 | T-04-02 / smuggled-param-reject | Unregistered/ambient strategy keys raise, never silent fallback | unit + determinism suites | `uv run pytest tests/test_no_lookahead.py tests/test_prefix_invariance.py tests/test_candle_close_timing.py tests/test_core_strategy_trend_pullback.py -q` | ❌ W0 | ⬜ pending |
| 04-01-03 | 01 | 1 | STRAT-03 | T-04-03 / float-injection-reject | Decimal(str) only; RR below minimum_rr → NO_TRADE | unit (golden fixtures) + boundary | `uv run pytest tests/test_core_planner.py -q` | ❌ W0 | ⬜ pending |
| 04-0X-01 | 02+ | 2+ | D-06 | — | Enum values verbatim, unknown → load-time error | unit | extend existing enum/translation tests | ❌ W0 | ⬜ pending |
| 04-0X-02 | 02+ | 2+ | D-10 | T-04-04 / precision-tamper-reject | No-float AST guard over `src/core/*` + mypy strict; pinned localcontext | static | `SCANNED_FILES` extension + `mypy` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/fixtures/phase4/` — candles.csv (1H + 4H closed, incl. gap injection + warm-up-short prefixes) + parameters.json + expected_{features,signals,plans}.json (byte-exact, hand-computed EMA/ATR seed values)
- [ ] `tests/test_core_features.py`, `tests/test_core_strategy_*.py` (tracer + 2 slices), `tests/test_core_planner.py` — real expectations replacing Phase-3 placeholder mappings
- [ ] `tests/test_domain_no_float.py::SCANNED_FILES` — append `src/core/*` modules
- [ ] `tests/conftest.py` — `phase4_*` fixtures mirroring the `phase3_*` loader pattern

---

## Manual-Only Verifications

All phase behaviors have automated verification.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
