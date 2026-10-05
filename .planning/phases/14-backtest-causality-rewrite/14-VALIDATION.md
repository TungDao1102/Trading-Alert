---
phase: "14"
slug: "backtest-causality-rewrite"
status: validated
nyquist_compliant: true
wave_0_complete: true
created: "2026-10-04"
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Source: 14-RESEARCH.md `## Validation Architecture`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (dev extra), `asyncio_mode = "auto"`, `addopts = "-q"` |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]`, `testpaths = ["tests"]` |
| **Quick run command** | `uv run pytest tests/test_backtest_entry.py tests/test_backtest_exits.py tests/test_backtest_funding.py tests/test_backtest_ledger.py tests/test_trade_record_validator.py -x` |
| **Full suite command** | `uv run pytest -m "not docker" -rs -p no:cacheprovider`, plus `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` |
| **Estimated runtime** | quick under 20 s per module; full suite many minutes (backtest files alone ~3 min locally; CI timeout 30 min) |

---

## Sampling Rate

- **After every task commit:** the relevant new test module only (hand-built `TradePlan` and in-memory minute series, no 250-bar warm-up)
- **After every plan wave:** quick run command plus `uv run pytest tests/test_backtest_*.py tests/test_paper_parity.py tests/test_cost_parity.py tests/test_case_input_builder.py`
- **Before `/gsd-verify-work`:** full suite, ruff, mypy, `uv run python scripts/verify_decision_alignment.py` all green
- **Max feedback latency:** 20 seconds per task

---

## Per-Task Verification Map

Task IDs are assigned by the planner; each row maps a success criterion to its proving command.

| Criterion | Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|-----------|-------------|----------|-----------|-------------------|-------------|--------|
| SC1 (F-120/F-901/F-902/F-804) | BKTS-01 | no fill on signal bar; fill only after N; trade-through >= 1 tick; touch-only is TOUCH_NO_FILL; temporal invariants raise | unit, hand-derived golden | `uv run pytest tests/test_backtest_entry.py tests/test_trade_record_validator.py -x` | ✅ | ✅ green |
| SC1 integration | BKTS-01 | simulator to `normalize_backtest` to `compute_trade_excursion` has no NEGATIVE_INTERVAL | integration | `uv run pytest tests/test_backtest_chain.py -x` | ✅ | ✅ green |
| SC2 (F-102, D037) | BKTS-01 | multi-bar hold to SL / TP1+TP2; TP1 then SL; mark-price triggers; stop-first tie; fallback flag; END_OF_DATA | unit + golden | `uv run pytest tests/test_backtest_exits.py -x` | ✅ | ✅ green |
| SC3 (F-905/F-021/F-305) | BKTS-01 | funding paid/received, between-funding entry, fail-closed coverage, allow-gaps recorded; PIT constraints; ledger equity/daily-loss/resting gates | unit + golden | `uv run pytest tests/test_backtest_funding.py tests/test_backtest_ledger.py tests/test_backtest_pit_constraints.py -x` | ✅ | ✅ green |
| SC4 (F-204/F-123/F-118) | BKTS-04 | R parity live vs backtest; regime slice populated; typed ExperimentRecord rejects invalid construction | unit | `uv run pytest tests/test_r_denominator_parity.py tests/test_backtest_report.py tests/test_backtest_experiment.py -x` | ✅ | ✅ green |
| SC5 (F-602/F-805/F-608) | DOMN-03 | every golden has `expected.json` + derivation; generator never places 1m inside the signal bar; regression snapshots relabeled | golden + meta | `uv run pytest tests/test_backtest_goldens.py tests/test_phase14_fixture_generator.py -x` | ✅ | ✅ green |
| SC6 (G3) | BKTS-01 | limit fills before `signal_expiry_hours`; another expires after; boundary minute | unit | `uv run pytest tests/test_backtest_expiry_clock.py -x` | ✅ | ✅ green |
| Determinism (D-26) | BKTS-02 | byte-identical rerun; shuffled bars identical; prefix-invariance (excluding END_OF_DATA); no float | property/unit | `uv run pytest tests/test_backtest_determinism.py tests/test_domain_no_float.py -x` | ✅ | ✅ green |
| Protocol amendment (D-02/D-28) | BKTS-04 | header, DECISIONS row, DOC_STATUS agree at v2.0.0; gate passes | gate | `uv run pytest tests/test_decision_alignment_protocol.py tests/test_kill_gate_docs.py tests/test_research_gate_negative.py -q` and `uv run python scripts/verify_decision_alignment.py` | ✅ | ✅ green |
| Real-data smoke | BKTS-02 | one symbol, 3 months, bounded RSS, deterministic digest | manual/slow script | `uv run python scripts/smoke_backtest_realdata.py --symbol BTCUSDT --days 90` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_backtest_entry.py`, `test_backtest_exits.py`, `test_backtest_funding.py`, `test_backtest_ledger.py`, `test_backtest_pit_constraints.py`, `test_backtest_expiry_clock.py`, `test_trade_record_validator.py`, `test_backtest_chain.py`, `test_backtest_determinism.py`, `test_backtest_goldens.py`, `test_r_denominator_parity.py`, `test_phase14_fixture_generator.py`
- [x] `tests/fixtures/phase14/<case>/{input.json,expected.json}` and `tests/fixtures/phase14/DERIVATIONS.md` (numbers from a standalone Decimal computation with no project imports; never regenerate an expectation by running the pipeline); fixture file names must not begin with `experiment` or `backtest`; no `"parameters"` key
- [x] Update `tests/test_domain_no_float.py` file list and `tests/phase10_helpers.py` defaults
- [x] `scripts/smoke_backtest_realdata.py` (local only)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full-run time and memory on real data | BKTS-02 | needs local 1.6 GB `data/raw`, not in CI (script CLI covered by `tests/test_smoke_backtest_cli.py`) | run the smoke script above and record RSS and runtime in the plan SUMMARY |
| TP1 fraction decision (D-27) | BKTS-01 | exit policy is the user's decision | answer the plan 14-01 checkpoint |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 20s per task
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-10-05

---

## Validation Audit 2026-10-05

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

Evidence: 19 test modules covering all rows, 424 passed; `ruff check` clean; `mypy src` clean (147 files); `verify_decision_alignment.py all` ALL_PASS. Run after the code-review fixes (commits c7fa4c2..461477b). Real-data smoke run remains manual-only.
