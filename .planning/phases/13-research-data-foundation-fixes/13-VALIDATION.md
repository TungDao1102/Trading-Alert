---
phase: "13"
slug: research-data-foundation-fixes
status: draft
nyquist_compliant: false
wave_0_complete: false
created: "2026-09-30"
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Source: 13-RESEARCH.md § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio (`asyncio_mode = "auto"`), respx |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `.venv/Scripts/python -m pytest tests/test_backfill.py tests/test_quality_gates.py tests/test_tracer_slice.py tests/test_collector.py tests/test_metadata.py tests/test_coverage.py tests/test_paper_resync.py tests/test_paper_supervisor_backfill.py tests/test_decision_alignment_universe.py tests/test_backtest_experiment.py -q -p no:cacheprovider` |
| **Full suite command** | `.venv/Scripts/python -m pytest -q -p no:cacheprovider` |
| **Static gates** | `.venv/Scripts/python -m ruff check src tests` and `.venv/Scripts/python -m mypy src` |
| **Estimated runtime** | ~25 seconds quick subset |

---

## Sampling Rate

- **After every task commit:** the single test file the task touched, plus `tests/test_domain_no_float.py` when a scanned package is touched
- **After every plan wave:** the quick run command
- **Before `/gsd-verify-work`:** full suite, ruff, mypy, and `python scripts/verify_decision_alignment.py` green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 13-D01 | — | — | DATA-02 (D-01/D-02) | symbol injection | collect list validated, empty rejected, no LIVE_5 fallback | unit | `pytest tests/test_collect_list.py tests/test_collector.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 13-D13 | — | — | DATA-01 (D-13) | — | current UTC day never published | unit | `pytest tests/test_backfill_closed_day.py tests/test_backfill.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 13-D14 | — | — | DATA-01 (D-14) | — | interrupted write leaves no partial file | unit | `pytest tests/test_store_atomic.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 13-D15 | — | — | DATA-01 (D-15) | — | zero-trade bar accepted; gaps stay gaps | unit | `pytest tests/test_quality_gates.py -q -p no:cacheprovider` | ✅ extend | ⬜ pending |
| 13-D11 | — | — | D-11 | — | mark klines separate root, no volume | unit | `pytest tests/test_mark_klines.py tests/test_backup.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 13-D04 | — | — | DATA-01 (D-04/D-05/D-26) | — | metadata first, delivery cap, resume, report exit codes | unit | `pytest tests/test_backfill_cli.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 13-D08 | — | — | D-08 | zip tampering, path traversal | checksum mismatch fails closed, size caps, no extractall | unit | `pytest tests/test_archive_ingest.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 13-D10 | — | — | DATA-03 (D-10/D-29) | — | versioned insert, universe filter | unit | `pytest tests/test_metadata.py -q -p no:cacheprovider` | ✅ extend | ⬜ pending |
| 13-D06 | — | — | D-06..D-09 | — | ranking, `--freeze` witnesses match, no re-freeze | unit | `pytest tests/test_universe_freeze.py tests/test_decision_alignment_universe.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 13-D17 | — | — | BKTS-02 (D-17..D-19/D-22) | — | deterministic byte-equal builds, gap refusal, stable dataset hash | unit | `pytest tests/test_case_input_builder.py tests/test_backtest_experiment.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 13-D16 | — | — | D-16/D-28 | — | backfill before subscribe, no duplicate/skip bar | unit | `pytest tests/test_paper_supervisor_backfill.py tests/test_paper_resync.py -q -p no:cacheprovider` | ✅ extend | ⬜ pending |
| 13-FUND | — | — | DATA-02 (D-23) | — | empty markPrice row parses, paginated funding no duplicates | unit | `pytest tests/test_collector.py -q -p no:cacheprovider` | ✅ extend | ⬜ pending |
| 13-D27 | — | — | DATA-04 (D-27) | — | backup bundle includes mark-kline subtree | unit | `pytest tests/test_backup.py -q -p no:cacheprovider` | ✅ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. The planner replaces the placeholder task IDs with real ones.*

---

## Wave 0 Requirements

- [ ] `tests/test_collect_list.py`, `tests/test_store_atomic.py`, `tests/test_backfill_closed_day.py`, `tests/test_mark_klines.py`, `tests/test_backfill_cli.py`, `tests/test_archive_ingest.py`, `tests/test_universe_freeze.py`, `tests/test_case_input_builder.py`
- [ ] Fixtures: trimmed exchangeInfo (~6 symbols incl. SETTLING with `deliveryDate`, PENDING_TRADING, TRADIFI_PERPETUAL, quarterly, USDC), recorded markPriceKlines sample, funding sample with `"markPrice":""`, in-test zip + `.CHECKSUM`
- [ ] Shared fake adapter supporting `klines`, `mark_klines`, `exchange_info`, `funding_rate`
- [ ] Rewrite `test_forming_candle_at_frozen_now_is_excluded` and `test_paginator_drops_forming_candle_at_frozen_clock`; update `test_real_manifest_is_draft_with_empty_freeze_fields` in the freeze commit

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Run the widened collector for a day on a real host | DATA-02 | Needs a live Binance connection and wall-clock time | Start the collector, confirm watermarks advance for every collect-list symbol |
| Freeze the research universe | D-09 | Deliberate operator action against live data | Run the CLI without `--freeze`, review the proposed manifest, then rerun with `--freeze` and commit both hash witnesses |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
