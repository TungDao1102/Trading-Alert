---
phase: "06"
slug: "backtest-simulator-experiment-registry"
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: false
created: "2026-09-26"
---

# Phase 06 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (pytest-asyncio auto mode) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/test_backtest_simulator.py tests/test_backtest_experiment.py tests/test_backtest_report.py -q` |
| **Full suite command** | `uv run pytest tests/ -q` |
| **Estimated runtime** | ~120 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_backtest_simulator.py tests/test_backtest_experiment.py tests/test_backtest_report.py -q`
- **After every plan wave:** Run `uv run pytest tests/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 300 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | BKTS-01 | — | N/A (deterministic simulator, no trust boundary) | unit | `uv run pytest tests/test_backtest_simulator.py -q` | ✅ | ✅ green (13 + 4 gap tests) |
| 06-02-01 | 02 | 1 | BKTS-02 | — | N/A (file-canonical registry, no secrets) | unit | `uv run pytest tests/test_backtest_experiment.py -q` | ✅ | ✅ green (11 + 8 gap tests) |
| 06-03-01 | 03 | 1 | BKTS-03 | — | N/A (report-only, no PII) | unit | `uv run pytest tests/test_backtest_report.py -q` | ✅ | ✅ green (10 + 5 gap tests) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Post-Fix Gap Coverage (validate-phase audit 2026-09-26)

The `--fix` run (06-REVIEW-FIX.md: 23 fixed / 3 skipped) landed without new tests. The auditor added 17 gap tests (`-k cr01…wr14` selectors); all green, full suite exit 0.

| Gap | Behavior | Test selector (file) | Status |
|-----|----------|----------------------|--------|
| CR-01 | empty intrabar `[]` → SL fallback + flag | `-k cr01` (simulator) | ✅ green |
| CR-02 | trade_id unique across bar-time/symbol/qty | `-k cr02` (simulator) | ✅ green |
| CR-03a | reproduce rejects mismatched inputs | `-k cr03a` (experiment) | ✅ green |
| CR-03b | reproduced trades typed Decimal/datetime | `-k cr03b` (experiment) | ✅ green |
| CR-03c | verify detects drift vs stored digest | `-k cr03c` (experiment) | ✅ green |
| CR-05 | Decimal/str cost inputs hash identically | `-k cr05` (experiment) | ✅ green |
| CR-06 | experiment_id differs by run_type/strategy | `-k cr06` (experiment) | ✅ green |
| CR-07 | baselines enforce degenerated minimum_rr | `-k cr07` (experiment) | ✅ green |
| CR-08 | build() requires explicit built_at_utc | `-k cr08` (report) | ✅ green |
| CR-09 | forged cost_model_hash rejected | `-k cr09` (experiment) | ✅ green |
| CR-10 | fixture version bound to registry | `-k cr10` (simulator) | ✅ green |
| CR-11 | baseline TOMLs carry atr_period + cost keys | `-k cr11` (experiment) | ✅ green |
| CR-12 | resamples=0 / bad probable rejected | `-k cr12` (report) | ✅ green |
| WR-05 | 2/3 coverage exact (no truncation) | `-k wr05` (report) | ✅ green |
| WR-06 | decoupled RNG streams (S vs S+1) | `-k wr06` (report) | ✅ green |
| WR-10 | risk-zero trades surfaced in note | `-k wr10` (report) | ✅ green |
| WR-14 | float/naive-datetime rejected at parse | `-k wr14` (simulator) | ✅ green |

---

## Wave 0 Requirements

- [ ] `tests/test_backtest_simulator.py` — stubs for BKTS-01 (intrabar resolution, limit fills, costs-from-run-#1)
- [ ] `tests/test_backtest_experiment.py` — stubs for BKTS-02 (six-field identity, baselines, reproducibility)
- [ ] `tests/test_backtest_report.py` — stubs for BKTS-03 (slices, R distribution, bootstrap, plateau)
- [ ] `tests/fixtures/phase6/` — golden inputs (strategy candles + 1m intrabar incl. both-touched bars + parameters + costs)
- [ ] `tests/conftest.py` — shared fixtures (already exists — extend, do not duplicate)

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CR-04 multi-bar expiry-clock semantics (global fixture clock vs per-bar clock for limit-expiry gate) | BKTS-01 (deferred design) | Needs cross-bar plan-lifecycle design call: bar-clock fix makes `EXPIRED` unreachable and breaks pinned `limit_expiry` test; fixer skipped with reason in 06-REVIEW-FIX.md | Re-run `uv run pytest tests/test_backtest_simulator.py -q -k limit_expiry` after the design decision lands; then automate the decided semantics |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 300s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-09-26 (auditor: 17/17 gaps filled, phase-6 subset 53 passed exit 0, full suite exit 0)

## Validation Audit 2026-09-26
| Metric | Count |
|--------|-------|
| Gaps found | 17 |
| Resolved | 17 |
| Escalated | 0 (CR-04 recorded manual-only by design, not an escalation) |
